"""Small, dependency-free GarageBand automation helpers for macOS."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time
import wave
from pathlib import Path
from typing import Any

from garageband_bridge import image_tab, score_midi, tab_midi


APP_NAME = "GarageBand"
APP_PATH = Path("/Applications/GarageBand.app")
MIDI_CONTROL_NAMES = {
    7: "volume",
    10: "pan",
    64: "sustain",
    91: "reverb",
    93: "chorus",
}


def _midi_key_signature_summary(fifths: int, mode_value: int, tick: int) -> dict[str, Any]:
    mode = "minor" if mode_value == 1 else "major"
    names = score_midi.MINOR_KEY_FIFTHS if mode == "minor" else score_midi.MAJOR_KEY_FIFTHS
    key_name = next((name for name, value in names.items() if value == fifths), f"{fifths} fifths")
    return {
        "name": f"{key_name} {mode}",
        "fifths": fifths,
        "mode": mode,
        "tick": tick,
        "beat": round(tick / tab_midi.TICKS_PER_BEAT, 4),
    }


def _midi_time_signature_summary(beats: int, denominator_power: int, tick: int) -> dict[str, Any]:
    return {
        "beats": beats,
        "beat_type": 2 ** denominator_power,
        "tick": tick,
        "beat": round(tick / tab_midi.TICKS_PER_BEAT, 4),
    }


SAMPLE_TAB = """e|--0--2--3--|
B|--1--3--0--|
G|--0--2--0--|
D|--2--0--0--|
A|--3-----2--|
E|--------3--|"""
PROJECT_SETTING_CONTROLS: dict[str, tuple[str, str]] = {
    "tempo": ("Tempo", "AXSlider"),
    "time_signature": ("Time Signature", "AXPopUpButton"),
    "key_signature": ("Key Signature", "AXPopUpButton"),
}
PROJECT_SETTING_OPTIONS: dict[str, list[str]] = {
    "time_signature": [
        "2/2",
        "2/4",
        "3/4",
        "4/4",
        "5/4",
        "6/4",
        "7/4",
        "3/8",
        "4/8",
        "5/8",
        "6/8",
        "7/8",
        "9/8",
        "12/8",
    ],
    "key_signature": [
        "C major",
        "G major",
        "D major",
        "A major",
        "E major",
        "B major",
        "F# major",
        "C# major",
        "F major",
        "Bb major",
        "Eb major",
        "Ab major",
        "Db major",
        "Gb major",
        "Cb major",
        "A minor",
        "E minor",
        "B minor",
        "F# minor",
        "C# minor",
        "G# minor",
        "D# minor",
        "A# minor",
        "D minor",
        "G minor",
        "C minor",
        "F minor",
        "Bb minor",
        "Eb minor",
        "Ab minor",
    ],
}
PROJECT_SETTING_LABEL_TO_KEY = {label: key for key, (label, _role) in PROJECT_SETTING_CONTROLS.items()}
UI_ACTION_ALIASES: dict[str, str] = {
    "increment": "AXIncrement",
    "decrement": "AXDecrement",
    "press": "AXPress",
    "confirm": "AXConfirm",
    "show_menu": "AXShowMenu",
    "show-menu": "AXShowMenu",
    "showmenu": "AXShowMenu",
    "axincrement": "AXIncrement",
    "axdecrement": "AXDecrement",
    "axpress": "AXPress",
    "axconfirm": "AXConfirm",
    "axshowmenu": "AXShowMenu",
}


LLM_RECIPES: list[dict[str, Any]] = [
    {
        "name": "make_song_from_online_tab_image",
        "goal": "Turn a web image of six-line guitar tab into a GarageBand-opened MIDI project seed.",
        "steps": [
            "garageband_image_to_tab with image_url to inspect OCR text",
            "garageband_arrange_image_to_midi or garageband_make_from_tab with image_url and arrange true",
            "garageband_ui_snapshot to confirm the generated project window",
            "garageband_screenshot for visual proof",
        ],
        "safe_defaults": {
            "open_in_garageband": True,
            "discard_unsaved": False,
            "show_library": True,
            "show_smart_controls": True,
        },
    },
    {
        "name": "make_music_from_band_score",
        "goal": "Turn a MusicXML band/full score into a multi-track GarageBand-openable song, with optional audio export.",
        "steps": [
            "garageband_make_music when the user wants one direct route from MusicXML, JSON score spec, tab, or tab image to GarageBand music",
            "garageband_score_spec_schema to get the JSON score contract before composing a score object",
            "garageband_validate_score_spec to check the score object before opening GarageBand",
            "garageband_score_to_midi with score_path to create a multi-track MIDI from the score parts",
            "garageband_score_spec_to_midi when the LLM has converted a score into the bridge JSON score spec",
            "garageband_midi_info to verify track names, channels, and note counts",
            "garageband_make_from_score or garageband_make_from_score_spec when the user wants the score opened in GarageBand with optional screenshot or audio export",
        ],
        "safe_defaults": {
            "open_in_garageband": True,
            "export_format": "WAVE",
            "export_overwrite": False,
        },
        "input_note": "Use MusicXML .musicxml/.xml/.mxl for exported notation files, or the JSON score spec when an LLM has already interpreted the score into parts/notes. Plain guitar tab is handled by the tab/image tools.",
    },
    {
        "name": "operate_visible_control",
        "goal": "Click or edit a visible GarageBand control without guessing coordinates.",
        "steps": [
            "garageband_ui_snapshot with max_depth 2 or 3",
            "garageband_ui_search_details to discover values, min/max bounds, attributes, and available actions",
            "garageband_click_ui_search, garageband_ui_search_info, or garageband_ui_search_set for uniquely named controls",
            "garageband_ui_search_action for controls that expose increment, decrement, or press actions",
            "garageband_ui_info_path, garageband_click_ui_path, or garageband_set_ui_value when you already have a path",
            "garageband_screenshot to verify the visible change",
        ],
    },
    {
        "name": "edit_visible_tracks",
        "goal": "Inspect imported GarageBand tracks and adjust mute, solo, volume, pan, or visible track names.",
        "steps": [
            "garageband_list_tracks to get visible track indexes, names, and control paths",
            "garageband_set_track with index or name plus mute, solo, volume, pan, or rename",
            "garageband_list_tracks again to verify the visible values GarageBand accepted",
            "garageband_list_regions to inspect visible MIDI/audio regions created from tab or image imports",
        ],
        "warning": "These commands operate on visible track headers. Scroll or zoom the tracks area first when the target track is not visible.",
    },
    {
        "name": "choose_visible_library_sound",
        "goal": "Search GarageBand's visible Library and select a shown sound/category/result for the selected track.",
        "steps": [
            "garageband_library_search with query to show the Library, fill the Library search field, and list visible results",
            "garageband_library_select with query plus name or allow_first to press one visible result",
            "garageband_screenshot or garageband_list_tracks to verify the visible state",
        ],
        "warning": "GarageBand's installed sound packs vary. Treat returned Library results as the source of truth instead of assuming a fixed patch catalog.",
    },
    {
        "name": "search_and_select_apple_loops",
        "goal": "Filter GarageBand's Apple Loops browser, select a visible loop row, or guarded-drag it into the timeline.",
        "steps": [
            "garageband_loop_search with query to show the Loop Browser, set its search field, and read the visible result count",
            "garageband_loop_select with query and index to click a visible row in the loop table",
            "garageband_screenshot to inspect row download icons before placement",
            "garageband_loop_drag with destination coordinates and acknowledge_content_install_risk true only after deciding the selected row is safe to drag",
        ],
        "warning": "GarageBand exposes the Loop Browser as a huge table. The bridge avoids enumerating all loop names and uses visible row indexes after search. Rows with download icons can open Apple's sound/content installer if dragged.",
    },
    {
        "name": "operate_visual_only_control",
        "goal": "Click or drag a UI target that lacks a useful Accessibility name.",
        "steps": [
            "garageband_annotated_screenshot to see numbered UI targets, a coordinate grid, and a click map",
            "garageband_window_rect to calibrate macOS window points",
            "garageband_window_click or garageband_window_drag",
            "garageband_ui_snapshot or garageband_screenshot to verify the result",
        ],
    },
    {
        "name": "export_current_song",
        "goal": "Export the current GarageBand project to an audio file.",
        "steps": [
            "garageband_status to confirm a project window is open",
            "garageband_export_song with output_path and format WAVE, AIFF, MP3, or AAC",
            "Verify the returned file path and byte count",
            "Use garageband_export_dialog plus UI tools for unusual dialog choices",
        ],
        "safe_defaults": {
            "overwrite": False,
            "format": "WAVE",
        },
    },
    {
        "name": "transport_and_edit",
        "goal": "Use common GarageBand keyboard actions.",
        "steps": [
            "garageband_transport with play_stop, rewind, record, undo, redo, save, copy, paste, cut",
            "garageband_shortcut for a specific keyboard shortcut",
            "garageband_screenshot to verify visible state",
        ],
    },
    {
        "name": "set_project_musical_settings",
        "goal": "Read or set the current GarageBand project's tempo, key signature, and time signature.",
        "steps": [
            "garageband_project_settings to inspect current values",
            "garageband_set_project_settings with tempo, key_signature, or time_signature",
            "garageband_project_settings again to verify the values GarageBand accepted",
        ],
    },
    {
        "name": "run_multi_step_agent_plan",
        "goal": "Execute a structured list of inspected GarageBand actions and get per-step results.",
        "steps": [
            "garageband_run_plan with steps containing action and args",
            "Use status, menu_map, menu_search, ui_snapshot, screenshot, menu, shortcut, transport, tab_to_midi, image_to_midi, make_music, make_from_tab, or visible UI actions",
            "Inspect the returned step list before continuing",
        ],
        "safe_defaults": {
            "stop_on_error": True,
            "verify_after_visual_actions": True,
        },
    },
]

AGENT_DECISION_GUIDE: list[dict[str, Any]] = [
    {
        "when": "User wants a song seed from guitar tab text, a local tab image, or an online tab image.",
        "prefer": [
            "garageband_make_music with tab_text, tab_file, image_path, or image_url for the highest-level GarageBand workflow",
            "garageband_image_to_tab when the source is an image and OCR text should be inspected first",
            "Use detected or explicit bpm, capo, and tuning for tab/image sources when the source says BPM 140, Capo 2, capo on 3rd fret, Drop D tuning, Tuning: DADGBE, or uses custom row labels like D| A| F#| D| A| D|; muted x/X strums are preserved as short guitar hits",
            "garageband_make_from_tab with arrange true for the highest-level GarageBand workflow",
            "garageband_arrange_tab_to_midi or garageband_arrange_image_to_midi when the user only needs a MIDI file",
        ],
        "verify": ["garageband_midi_info", "garageband_ui_snapshot", "garageband_screenshot"],
    },
    {
        "when": "User provides a band score, full score, sheet-music export, or multi-instrument composition.",
        "prefer": [
            "garageband_make_music with score_path, score_spec, score_json, or score_json_file when the user wants direct music output",
            "garageband_score_spec_schema before generating a structured JSON score from prose or visual score understanding",
            "Use MusicXML score-partwise or score-timewise tempo changes, time-signature changes, written-to-sounding transposition, 8va/8vb octave-shift directions, grace notes, harmony/chord symbols, sustain pedal directions, drum score-instrument names and midi-unpitched values, specific-before-broad instrument program mapping, tied-note sustain, single- and multi-measure repeat symbols, simple forward/backward repeats, common first/second endings, rehearsal/words markers, and midi-instrument channel/program/volume/pan metadata when the source score already contains song structure or playback setup",
            "Use score_spec sections with name/repeat/dynamic when the user wants intro, verse, chorus, bridge, or outro structure",
            "Use score_spec articulation on parts, sections, or notes for staccato, tenuto, legato, accent, or marcato phrasing",
            "Use score_spec part mix with volume, pan, reverb, and chorus when the generated arrangement should import with a basic balance",
            "Use score_spec key_signature when the generated arrangement should preserve the score key, such as Bb major or E minor",
            "Use score_spec tempo_changes when the arrangement needs tempo shifts across sections",
            "garageband_validate_score_spec before opening GarageBand or exporting audio",
            "garageband_score_to_midi for MusicXML .musicxml/.xml/.mxl scores when a multi-track MIDI file is enough",
            "garageband_score_spec_to_midi when the LLM has a structured JSON score with parts and notes",
            "garageband_make_from_score when the user wants the generated score opened in GarageBand or exported to audio",
            "garageband_make_from_score_spec when the structured JSON score should be opened/exported",
            "garageband_midi_info after generation to verify track names, channels, note counts, note lengths, velocities, section markers, key signature, tempo changes, time-signature changes, and control changes",
        ],
        "verify": ["garageband_midi_info", "garageband_screenshot"],
    },
    {
        "when": "User wants to click, set, or inspect a visible control.",
        "prefer": [
            "garageband_ui_snapshot or garageband_ui_controls_summary to inspect the current screen",
            "garageband_ui_search_details before unfamiliar controls",
            "garageband_click_ui_path, garageband_ui_action_path, or garageband_set_ui_value when a path is available",
            "garageband_click_ui_search or garageband_ui_search_action only when the label should be unique",
        ],
        "fallback": [
            "garageband_annotated_screenshot",
            "garageband_window_click or garageband_window_drag with window-relative coordinates",
        ],
        "verify": ["garageband_ui_snapshot", "garageband_screenshot"],
    },
    {
        "when": "User wants a menu command, panel, export dialog, or common transport/edit command.",
        "prefer": [
            "garageband_menu_map or garageband_find_menu_items before clicking a menu",
            "garageband_click_menu_search for a unique menu match",
            "garageband_transport for common play, rewind, record, undo, redo, save, copy, paste, or cut actions",
            "garageband_export_song for normal audio export instead of manually driving the dialog",
        ],
        "verify": ["garageband_wait_ui", "garageband_screenshot"],
    },
    {
        "when": "User wants to change sound, instrument flavor, track selection, Smart Controls, or Apple Loops.",
        "prefer": [
            "garageband_list_tracks then garageband_select_track before track-specific Library or Smart Controls changes",
            "garageband_library_search before garageband_library_select",
            "garageband_smart_controls before garageband_set_smart_control",
            "garageband_loop_search and a screenshot before garageband_loop_select or garageband_loop_drag",
        ],
        "caution": [
            "GarageBand Library and loop content varies by Mac.",
            "Loop rows with download icons can trigger Apple's sound/content installer; drag only after explicit acknowledgement.",
        ],
        "verify": ["garageband_list_tracks", "garageband_smart_controls", "garageband_screenshot"],
    },
]


class GarageBandError(RuntimeError):
    """Raised when GarageBand automation cannot complete."""


def _run(args: list[str], timeout: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _osa(script: str, *args: str, timeout: float = 30) -> str:
    proc = subprocess.run(
        ["osascript", "-"] + list(args),
        input=script,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "osascript failed").strip()
        raise GarageBandError(msg)
    return proc.stdout.strip()


def _json_osa(script: str, *args: str, timeout: float = 30) -> Any:
    out = _osa(script, *args, timeout=timeout)
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise GarageBandError(f"Expected JSON from AppleScript, got: {out}") from exc


def _q(value: str) -> str:
    return json.dumps(value)


def _norm_menu_part(value: str) -> str:
    return value.strip().replace("...", chr(8230))


def app_version() -> str | None:
    plist = APP_PATH / "Contents" / "Info.plist"
    if not plist.exists():
        return None
    with plist.open("rb") as handle:
        data = plistlib.load(handle)
    return data.get("CFBundleShortVersionString") or data.get("CFBundleVersion")


def app_installed() -> bool:
    return APP_PATH.exists()


def is_running() -> bool:
    script = 'tell application "System Events" to exists process "GarageBand"'
    return _osa(script).lower() == "true"


def launch(activate: bool = True) -> dict[str, Any]:
    if not app_installed():
        raise GarageBandError("GarageBand.app was not found in /Applications.")
    if activate:
        _osa('tell application "GarageBand" to activate')
    else:
        proc = _run(["open", "-a", APP_NAME])
        if proc.returncode != 0:
            raise GarageBandError((proc.stderr or proc.stdout).strip())
    wait_until_running()
    return status()


def activate() -> dict[str, Any]:
    _osa('tell application "GarageBand" to activate')
    return status()


def quit_app() -> dict[str, Any]:
    if is_running():
        _osa('tell application "GarageBand" to quit', timeout=10)
    return status()


def wait_until_running(timeout: float = 15) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_running():
            return
        time.sleep(0.25)
    raise GarageBandError("Timed out waiting for GarageBand to launch.")


def open_path(path: str, activate_after: bool = True) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise GarageBandError(f"Path does not exist: {p}")
    proc = _run(["open", "-a", APP_NAME, str(p)])
    if proc.returncode != 0:
        raise GarageBandError((proc.stderr or proc.stdout).strip())
    if activate_after:
        _osa('tell application "GarageBand" to activate')
    return {"opened": str(p), "status": status()}


def render_preview(path: str | None = None) -> dict[str, Any]:
    """Call GarageBand's only documented scripting command."""
    if path:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise GarageBandError(f"Project path does not exist: {p}")
        script = textwrap.dedent(
            """
            on run argv
              set projectFile to POSIX file (item 1 of argv)
              tell application "GarageBand"
                renderPreview projectFile
              end tell
              return "ok"
            end run
            """
        )
        _osa(script, str(p), timeout=120)
        return {"rendered_preview_for": str(p)}

    _osa('tell application "GarageBand" to renderPreview', timeout=120)
    return {"rendered_preview_for": "front project or default target"}


def status() -> dict[str, Any]:
    running = is_running()
    data: dict[str, Any] = {
        "installed": app_installed(),
        "app_path": str(APP_PATH) if app_installed() else None,
        "version": app_version(),
        "running": running,
    }
    if running:
        script = textwrap.dedent(
            """
            tell application "System Events"
              tell process "GarageBand"
                set winTitles to {}
                repeat with w in windows
                  try
                    set end of winTitles to name of w as text
                  end try
                end repeat
                set payload to "{\\"frontmost\\":" & (frontmost as text) & ",\\"window_count\\":" & ((count of windows) as text) & ",\\"windows\\":["
                repeat with i from 1 to count of winTitles
                  set t to item i of winTitles
                  set t to my replaceText("\\\\", "\\\\\\\\", t)
                  set t to my replaceText("\\"", "\\\\\\"", t)
                  set payload to payload & "\\"" & t & "\\""
                  if i is not count of winTitles then set payload to payload & ","
                end repeat
                set payload to payload & "]}"
                return payload
              end tell
            end tell

            on replaceText(find, repl, sourceText)
              set AppleScript's text item delimiters to find
              set parts to text items of sourceText
              set AppleScript's text item delimiters to repl
              set joined to parts as text
              set AppleScript's text item delimiters to ""
              return joined
            end replaceText
            """
        )
        try:
            data.update(_json_osa(script))
        except GarageBandError as exc:
            data["ui_error"] = str(exc)
    return data


def list_menus(include_disabled: bool = True) -> dict[str, Any]:
    if not is_running():
        launch()
    wait_until_running()
    script = textwrap.dedent(
        """
        tell application "GarageBand" to activate
        delay 0.3
        tell application "System Events"
          tell process "GarageBand"
            set output to ""
            repeat with mi in menu bar items of menu bar 1
              set output to output & "## " & (name of mi as text) & linefeed
              try
                repeat with childItem in menu items of menu 1 of mi
                  set itemName to name of childItem as text
                  if itemName is "missing value" then set itemName to ""
                  set output to output & itemName & "|" & (enabled of childItem as text) & linefeed
                end repeat
              end try
            end repeat
            return output
          end tell
        end tell
        """
    )
    raw = _osa(script, timeout=45)
    menus: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in raw.splitlines():
        if line.startswith("## "):
            current = {"name": line[3:], "items": []}
            menus.append(current)
            continue
        if current is None or "|" not in line:
            continue
        name, enabled = line.rsplit("|", 1)
        if not name:
            continue
        item = {
            "name": name,
            "path": f"{current['name']} > {name}",
            "enabled": enabled.lower() == "true",
            "children": [],
        }
        current["items"].append(item)
    if not include_disabled:
        def trim(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            result = []
            for item in items:
                children = trim(item.get("children", []))
                if item.get("enabled") or children:
                    new_item = dict(item)
                    new_item["children"] = children
                    result.append(new_item)
            return result

        for menu in menus:
            menu["items"] = trim(menu.get("items", []))
    return {"menus": menus}


def menu_map(include_disabled: bool = True, max_depth: int = 5, top_menu: str | None = None) -> dict[str, Any]:
    """Return a recursive, flat map of GarageBand menu paths."""
    if not is_running():
        launch()
    wait_until_running()
    max_depth = max(1, min(8, int(max_depth)))
    script = textwrap.dedent(
        """
        on run argv
          set maxDepth to (item 1 of argv) as integer
          set requestedTopMenu to item 2 of argv
          tell application "GarageBand" to activate
          delay 0.3
          tell application "System Events"
            tell process "GarageBand"
              set output to ""
              repeat with mi in menu bar items of menu bar 1
                set topName to name of mi as text
                ignoring case
                  set topOK to (requestedTopMenu is "" or topName is requestedTopMenu)
                end ignoring
                if topOK then
                  try
                    set output to my dumpMenu(menu 1 of mi, topName, 1, maxDepth, output)
                  end try
                end if
              end repeat
              return output
            end tell
          end tell
        end run

        on dumpMenu(menuRef, prefixText, depth, maxDepth, output)
          tell application "System Events"
            repeat with childItem in menu items of menuRef
              set itemName to ""
              set itemEnabled to false
              set childCount to 0
              try
                set itemName to name of childItem as text
              end try
              if itemName is not "" and itemName is not "missing value" then
                try
                  set itemEnabled to enabled of childItem
                end try
                try
                  set childCount to count of menu items of menu 1 of childItem
                end try
                set itemPath to prefixText & " > " & itemName
                set output to output & my cleanField(itemPath) & tab & depth & tab & (itemEnabled as text) & tab & childCount & linefeed
                if childCount > 0 and depth < maxDepth then
                  try
                    set output to my dumpMenu(menu 1 of childItem, itemPath, depth + 1, maxDepth, output)
                  end try
                end if
              end if
            end repeat
            return output
          end tell
        end dumpMenu

        on cleanField(sourceText)
          if sourceText is missing value then set sourceText to ""
          set sourceText to sourceText as text
          set sourceText to my replaceText(tab, " ", sourceText)
          set sourceText to my replaceText(return, " ", sourceText)
          set sourceText to my replaceText(linefeed, " ", sourceText)
          return sourceText
        end cleanField

        on replaceText(find, repl, sourceText)
          set AppleScript's text item delimiters to find
          set parts to text items of sourceText
          set AppleScript's text item delimiters to repl
          set joined to parts as text
          set AppleScript's text item delimiters to ""
          return joined
        end replaceText
        """
    )
    raw = _osa(script, str(max_depth), top_menu or "", timeout=90)
    items: list[dict[str, Any]] = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        path, depth, enabled, child_count = parts
        if not path:
            continue
        if not include_disabled and enabled.lower() != "true":
            continue
        name = path.split(" > ")[-1]
        try:
            parsed_child_count = int(child_count)
        except ValueError:
            parsed_child_count = 0
        items.append(
            {
                "path": path,
                "name": name,
                "depth": int(depth),
                "enabled": enabled.lower() == "true",
                "child_count": parsed_child_count,
                "has_children": parsed_child_count > 0,
            }
        )
    return {"max_depth": max_depth, "top_menu": top_menu, "count": len(items), "items": items}


def find_menu_items(
    query: str,
    *,
    enabled_only: bool = False,
    max_depth: int = 5,
    limit: int = 50,
    top_menu: str | None = None,
) -> dict[str, Any]:
    if not query.strip():
        raise GarageBandError("Menu search query is empty.")
    menu_data = menu_map(include_disabled=not enabled_only, max_depth=max_depth, top_menu=top_menu)
    needle = query.casefold()
    matches = [
        item for item in menu_data["items"]
        if needle in item["path"].casefold() or needle in item["name"].casefold()
    ]
    limit = max(1, min(500, int(limit)))
    return {
        "query": query,
        "enabled_only": enabled_only,
        "max_depth": max_depth,
        "top_menu": top_menu,
        "count": len(matches),
        "matches": matches[:limit],
        "truncated": len(matches) > limit,
    }


def _select_match(matches: list[dict[str, Any]], *, allow_first: bool, kind: str) -> dict[str, Any]:
    if not matches:
        raise GarageBandError(f"No {kind} match found.")
    if len(matches) > 1 and not allow_first:
        paths = ", ".join(str(match.get("path", match.get("name", ""))) for match in matches[:5])
        raise GarageBandError(f"Expected one {kind} match, found {len(matches)}. Narrow the query. First matches: {paths}")
    return matches[0]


def click_menu_search(
    query: str,
    *,
    enabled_only: bool = True,
    max_depth: int = 5,
    top_menu: str | None = None,
    allow_first: bool = False,
) -> dict[str, Any]:
    found = find_menu_items(
        query,
        enabled_only=enabled_only,
        max_depth=max_depth,
        limit=20,
        top_menu=top_menu,
    )
    match = _select_match(found["matches"], allow_first=allow_first, kind="menu")
    clicked = click_menu(match["path"])
    return {"query": query, "selected": match, "clicked": clicked, "match_count": found["count"]}


def click_menu(path: str) -> dict[str, Any]:
    parts = [_norm_menu_part(part) for part in path.split(">") if part.strip()]
    if len(parts) < 2:
        raise GarageBandError('Menu path must look like "File > Open..."')
    if not is_running():
        launch()
    script = textwrap.dedent(
        """
        on run argv
          tell application "GarageBand" to activate
          delay 0.2
          tell application "System Events"
            tell process "GarageBand"
              set currentMenu to menu 1 of menu bar item (item 1 of argv) of menu bar 1
              repeat with i from 2 to (count of argv)
                set partName to item i of argv
                if i is (count of argv) then
                  click menu item partName of currentMenu
                else
                  set currentMenu to menu 1 of menu item partName of currentMenu
                end if
              end repeat
            end tell
          end tell
          return "ok"
        end run
        """
    )
    _osa(script, *parts, timeout=20)
    return {"clicked": " > ".join(parts)}


def ui_snapshot(max_depth: int = 4) -> dict[str, Any]:
    if not is_running():
        launch()
    wait_until_running()
    max_depth = max(1, min(8, max_depth))
    script = textwrap.dedent(
        """
        on run argv
          set maxDepth to (item 1 of argv) as integer
          tell application "GarageBand" to activate
          delay 0.3
          tell application "System Events"
            tell process "GarageBand"
              set output to ""
              set idx to 0
              repeat with w in windows
                set idx to idx + 1
                set output to my dumpElement(w, "window[" & idx & "]", 0, maxDepth, output)
              end repeat
              return output
            end tell
          end tell
        end run

        on dumpElement(el, pathText, depth, maxDepth, output)
          tell application "System Events"
            set elRole to ""
            set elName to ""
            set elDesc to ""
            set elEnabled to ""
            set elPosition to ""
            set elSize to ""
            try
              set elRole to role of el as text
            end try
            try
              set elName to name of el as text
            end try
            try
              set elDesc to description of el as text
            end try
            try
              set elEnabled to enabled of el as text
            end try
            try
              set elPos to position of el
              set elPosition to (item 1 of elPos as text) & "," & (item 2 of elPos as text)
            end try
            try
              set elSz to size of el
              set elSize to (item 1 of elSz as text) & "," & (item 2 of elSz as text)
            end try
            set output to output & pathText & tab & depth & tab & my cleanField(elRole) & tab & my cleanField(elName) & tab & my cleanField(elDesc) & tab & elEnabled & tab & elPosition & tab & elSize & linefeed
            if depth < maxDepth then
              set childIndex to 0
              try
                repeat with childRef in UI elements of el
                  set childIndex to childIndex + 1
                  set output to my dumpElement(childRef, pathText & "/" & childIndex, depth + 1, maxDepth, output)
                end repeat
              end try
            end if
            return output
          end tell
        end dumpElement

        on cleanField(sourceText)
          if sourceText is missing value then set sourceText to ""
          set sourceText to sourceText as text
          set sourceText to my replaceText(tab, " ", sourceText)
          set sourceText to my replaceText(return, " ", sourceText)
          set sourceText to my replaceText(linefeed, " ", sourceText)
          return sourceText
        end cleanField

        on replaceText(find, repl, sourceText)
          set AppleScript's text item delimiters to find
          set parts to text items of sourceText
          set AppleScript's text item delimiters to repl
          set joined to parts as text
          set AppleScript's text item delimiters to ""
          return joined
        end replaceText
        """
    )
    raw = _osa(script, str(max_depth), timeout=60)
    elements = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) not in (6, 8):
            continue
        path, depth, role, name, description, enabled = parts[:6]
        item = {
            "path": path,
            "depth": int(depth),
            "role": role,
            "name": name,
            "description": description,
            "enabled": enabled.lower() == "true" if enabled else None,
        }
        if len(parts) == 8:
            item["position"] = parts[6]
            item["size"] = parts[7]
        elements.append(item)
    return {"max_depth": max_depth, "count": len(elements), "elements": elements}


def find_ui_elements(
    query: str,
    *,
    role: str | None = None,
    enabled_only: bool = False,
    max_depth: int = 4,
    limit: int = 50,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not query.strip():
        raise GarageBandError("UI search query is empty.")
    snap = snapshot or ui_snapshot(max_depth=max_depth)
    needle = query.casefold()
    role_filter = role.casefold() if role else None
    matches = []
    for element in snap["elements"]:
        haystack = " ".join(
            str(element.get(key, ""))
            for key in ("path", "role", "name", "description", "position", "size")
        ).casefold()
        if needle not in haystack:
            continue
        if role_filter and role_filter != str(element.get("role", "")).casefold():
            continue
        if enabled_only and element.get("enabled") is not True:
            continue
        matches.append(element)
    limit = max(1, min(500, int(limit)))
    return {
        "query": query,
        "role": role,
        "enabled_only": enabled_only,
        "max_depth": max_depth,
        "count": len(matches),
        "matches": matches[:limit],
        "truncated": len(matches) > limit,
    }


def ui_controls_summary(max_depth: int = 3) -> dict[str, Any]:
    snap = ui_snapshot(max_depth=max_depth)
    return _ui_controls_summary_from_snapshot(snap, max_depth=max_depth)


def _ui_controls_summary_from_snapshot(snap: dict[str, Any], max_depth: int = 3) -> dict[str, Any]:
    roles: dict[str, int] = {}
    actionable_roles = {"AXButton", "AXCheckBox", "AXSlider", "AXTextField", "AXPopUpButton", "AXRadioButton"}
    actionable = []
    for element in snap["elements"]:
        role = str(element.get("role", ""))
        roles[role] = roles.get(role, 0) + 1
        if role in actionable_roles:
            actionable.append(element)
    return {
        "max_depth": max_depth,
        "total": snap["count"],
        "roles": dict(sorted(roles.items())),
        "actionable_count": len(actionable),
        "actionable": actionable,
    }


def _parse_point(raw: str | None) -> dict[str, int] | None:
    if not raw or "," not in raw:
        return None
    try:
        x, y = [int(float(part)) for part in raw.split(",", 1)]
    except ValueError:
        return None
    return {"x": x, "y": y}


def _parse_rect_text(raw: str) -> tuple[int, int, int, int]:
    try:
        x, y, width, height = [int(float(part)) for part in raw.split(",", 3)]
    except ValueError as exc:
        raise GarageBandError(f"Could not parse window rectangle: {raw!r}") from exc
    return x, y, width, height


def _parse_size(raw: str | None) -> dict[str, int] | None:
    if not raw or "," not in raw:
        return None
    try:
        width, height = [int(float(part)) for part in raw.split(",", 1)]
    except ValueError:
        return None
    return {"width": width, "height": height}


def _missing_to_empty(value: Any) -> str:
    text = str(value or "")
    return "" if text == "missing value" else text


def _element_under(elements: list[dict[str, Any]], parent_path: str) -> list[dict[str, Any]]:
    prefix = parent_path.rstrip("/") + "/"
    return [element for element in elements if str(element.get("path", "")).startswith(prefix)]


def _ui_subtree_snapshot(path: str, *, max_depth: int = 4, timeout: float = 45) -> dict[str, Any]:
    if not path.strip():
        raise GarageBandError("UI path is empty.")
    if not is_running():
        launch()
    wait_until_running()
    max_depth = max(1, min(8, max_depth))
    script = textwrap.dedent(
        """
        on run argv
          set targetPath to item 1 of argv
          set maxDepth to (item 2 of argv) as integer
          tell application "GarageBand" to activate
          delay 0.3
          tell application "System Events"
            set targetElement to my elementAtPath(targetPath)
            return my dumpElement(targetElement, targetPath, 0, maxDepth, "")
          end tell
        end run

        on elementAtPath(targetPath)
          tell application "System Events"
            tell process "GarageBand"
              if targetPath does not start with "window[" then error "UI path must start with window[index]"
              set AppleScript's text item delimiters to "]"
              set pathParts to text items of targetPath
              set windowPart to item 1 of pathParts
              set AppleScript's text item delimiters to "["
              set windowIndex to (item 2 of text items of windowPart) as integer
              set currentElement to window windowIndex
              set restPath to ""
              if (count of pathParts) > 1 then set restPath to item 2 of pathParts
              if restPath starts with "/" then set restPath to text 2 thru -1 of restPath
              if restPath is not "" then
                set AppleScript's text item delimiters to "/"
                repeat with childPart in text items of restPath
                  if childPart is not "" then set currentElement to UI element (childPart as integer) of currentElement
                end repeat
              end if
              set AppleScript's text item delimiters to ""
              return currentElement
            end tell
          end tell
        end elementAtPath

        on dumpElement(el, pathText, depth, maxDepth, output)
          tell application "System Events"
            set elRole to ""
            set elName to ""
            set elDesc to ""
            set elEnabled to ""
            set elPosition to ""
            set elSize to ""
            try
              set elRole to role of el as text
            end try
            try
              set elName to name of el as text
            end try
            try
              set elDesc to description of el as text
            end try
            try
              set elEnabled to enabled of el as text
            end try
            try
              set elPos to position of el
              set elPosition to (item 1 of elPos as text) & "," & (item 2 of elPos as text)
            end try
            try
              set elSz to size of el
              set elSize to (item 1 of elSz as text) & "," & (item 2 of elSz as text)
            end try
            set output to output & pathText & tab & depth & tab & my cleanField(elRole) & tab & my cleanField(elName) & tab & my cleanField(elDesc) & tab & elEnabled & tab & elPosition & tab & elSize & linefeed
            if depth < maxDepth then
              set childIndex to 0
              try
                repeat with childRef in UI elements of el
                  set childIndex to childIndex + 1
                  set output to my dumpElement(childRef, pathText & "/" & childIndex, depth + 1, maxDepth, output)
                end repeat
              end try
            end if
            return output
          end tell
        end dumpElement

        on cleanField(sourceText)
          if sourceText is missing value then set sourceText to ""
          set sourceText to sourceText as text
          set sourceText to my replaceText(tab, " ", sourceText)
          set sourceText to my replaceText(return, " ", sourceText)
          set sourceText to my replaceText(linefeed, " ", sourceText)
          return sourceText
        end cleanField

        on replaceText(find, repl, sourceText)
          set AppleScript's text item delimiters to find
          set parts to text items of sourceText
          set AppleScript's text item delimiters to repl
          set joined to parts as text
          set AppleScript's text item delimiters to ""
          return joined
        end replaceText
        """
    )
    raw = _osa(script, path, str(max_depth), timeout=timeout)
    elements = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 8:
            continue
        item_path, depth, role, name, description, enabled, position, size = parts
        elements.append(
            {
                "path": item_path,
                "depth": int(depth),
                "role": role,
                "name": name,
                "description": description,
                "enabled": enabled.lower() == "true" if enabled else None,
                "position": position,
                "size": size,
            }
        )
    return {"root": path, "max_depth": max_depth, "count": len(elements), "elements": elements}


def _track_header_elements(snap: dict[str, Any]) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    for element in snap["elements"]:
        if element.get("role") != "AXLayoutItem":
            continue
        description = str(element.get("description", ""))
        match = re.match(r"^Track (\d+) [“\"](.+)[”\"]$", description)
        if not match:
            continue
        size = _parse_size(element.get("size"))
        if not size or size["width"] <= 0 or size["height"] <= 0:
            continue
        descendants = _element_under(snap["elements"], str(element["path"]))
        has_track_name_field = any(
            child.get("role") == "AXTextField"
            and str(child.get("description", "")) == match.group(2)
            for child in descendants
        )
        if not has_track_name_field:
            continue
        tracks.append(element)
    return sorted(
        tracks,
        key=lambda item: int(re.match(r"^Track (\d+)", str(item.get("description", ""))).group(1)),  # type: ignore[union-attr]
    )


def _find_descendant(
    elements: list[dict[str, Any]],
    parent_path: str,
    *,
    role: str | None = None,
    description: str | None = None,
) -> dict[str, Any] | None:
    for child in _element_under(elements, parent_path):
        if role is not None and child.get("role") != role:
            continue
        if description is not None and str(child.get("description", "")) != description:
            continue
        return child
    return None


def _control_info(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        return ui_info_path(path)
    except GarageBandError as exc:
        return {"path": path, "error": str(exc)}


def list_tracks(
    *,
    max_depth: int = 7,
    include_values: bool = True,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snap = snapshot or ui_snapshot(max_depth=max_depth)
    tracks: list[dict[str, Any]] = []
    for header in _track_header_elements(snap):
        description = str(header.get("description", ""))
        match = re.match(r"^Track (\d+) [“\"](.+)[”\"]$", description)
        if not match:
            continue
        index = int(match.group(1))
        name = match.group(2)
        path = str(header["path"])
        mute = _find_descendant(snap["elements"], path, role="AXCheckBox", description="Mute")
        solo = _find_descendant(snap["elements"], path, role="AXCheckBox", description="Solo")
        volume = _find_descendant(snap["elements"], path, role="AXSlider", description="Volume")
        pan = _find_descendant(snap["elements"], path, role="AXSlider", description="")
        name_field = _find_descendant(snap["elements"], path, role="AXTextField", description=name)
        item: dict[str, Any] = {
            "index": index,
            "name": name,
            "description": description,
            "path": path,
            "position": _parse_point(header.get("position")),
            "size": _parse_size(header.get("size")),
            "controls": {
                "mute": mute,
                "solo": solo,
                "volume": volume,
                "pan": pan,
                "name": name_field,
            },
        }
        if include_values:
            item["values"] = {
                key: _control_info(control.get("path") if control else None)
                for key, control in item["controls"].items()
            }
        tracks.append(item)
    return {"count": len(tracks), "tracks": tracks, "max_depth": max_depth}


def _select_track(
    tracks_data: dict[str, Any],
    *,
    index: int | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    tracks = tracks_data["tracks"]
    if index is None and not name:
        if len(tracks) == 1:
            return tracks[0]
        raise GarageBandError("Provide track index or name when more than one track is visible.")
    if index is not None:
        for track in tracks:
            if int(track["index"]) == int(index):
                return track
        raise GarageBandError(f"No visible track with index {index}.")
    needle = str(name or "").casefold()
    matches = [track for track in tracks if needle in str(track["name"]).casefold()]
    return _select_match(matches, allow_first=False, kind="track")


def _visible_track_headers(snap: dict[str, Any]) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    for element in snap["elements"]:
        if element.get("role") != "AXLayoutItem":
            continue
        description = str(element.get("description", ""))
        match = re.match(r"^Track (\d+) [“\"](.+)[”\"]$", description)
        if not match:
            continue
        size = _parse_size(element.get("size"))
        position = _parse_point(element.get("position"))
        if not size or not position or size["width"] <= 0 or size["height"] <= 0:
            continue
        tracks.append(
            {
                "index": int(match.group(1)),
                "name": match.group(2),
                "description": description,
                "path": element.get("path"),
                "position": position,
                "size": size,
            }
        )
    return sorted(tracks, key=lambda item: int(item["index"]))


def select_track(
    *,
    index: int | None = None,
    name: str | None = None,
    max_depth: int = 6,
    x_offset: float = 110.0,
    y_fraction: float = 0.5,
    fast: bool = False,
    row_height: float = 129.0,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if fast:
        if index is None:
            raise GarageBandError("Fast track selection requires a visible track index.")
        if name:
            raise GarageBandError("Fast track selection uses visible index only; omit name.")
        snap = snapshot or ui_snapshot(max_depth=min(max_depth, 5))
        header = next(
            (
                element for element in snap["elements"]
                if element.get("role") == "AXGroup" and element.get("description") == "Tracks header"
            ),
            None,
        )
        if not header:
            raise GarageBandError("Could not find visible GarageBand Tracks header area for fast selection.")
        position = _parse_point(header.get("position"))
        size = _parse_size(header.get("size"))
        if not position or not size:
            raise GarageBandError("Tracks header geometry is not available.")
        selected_y = float(position["y"]) + (float(row_height) * (int(index) - 1)) + (float(row_height) * max(0.1, min(0.9, float(y_fraction))))
        if selected_y > float(position["y"] + size["height"]):
            raise GarageBandError(f"Visible track index {index} is outside the current Tracks header area.")
        screen_x = float(position["x"]) + max(8.0, min(float(x_offset), float(size["width"]) - 8.0))
        screen_y = selected_y
        rect = window_rect()
        clicked = click_window(screen_x - rect["x"], screen_y - rect["y"])
        time.sleep(0.2)
        return {
            "selected": {
                "index": int(index),
                "name": None,
                "path": header.get("path"),
                "mode": "fast_visible_index",
                "tracks_header": {"position": position, "size": size},
            },
            "clicked": clicked,
            "screen_point": {"x": round(screen_x, 1), "y": round(screen_y, 1)},
            "max_depth": min(max_depth, 5),
            "row_height": row_height,
            "verify_next": "Use screenshot, smart-controls, library-search, or robust select-track without fast mode to verify the selected track.",
        }

    snap = snapshot or ui_snapshot(max_depth=max_depth)
    tracks = _visible_track_headers(snap)
    if not tracks:
        raise GarageBandError("No visible GarageBand track headers found.")
    selected = _select_track({"tracks": tracks}, index=index, name=name)
    position = selected["position"]
    size = selected["size"]
    safe_x_offset = max(8.0, min(float(x_offset), float(size["width"]) - 8.0))
    safe_y_fraction = max(0.1, min(0.9, float(y_fraction)))
    screen_x = float(position["x"]) + safe_x_offset
    screen_y = float(position["y"]) + (float(size["height"]) * safe_y_fraction)
    rect = window_rect()
    clicked = click_window(screen_x - rect["x"], screen_y - rect["y"])
    time.sleep(0.2)
    return {
        "selected": selected,
        "clicked": clicked,
        "screen_point": {"x": round(screen_x, 1), "y": round(screen_y, 1)},
        "visible_tracks": tracks,
        "max_depth": max_depth,
        "verify_next": "Use screenshot, smart-controls, library-search, or list-tracks to verify the selected track-dependent state.",
    }


def _bool_text(value: bool | str | int | float) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "muted", "soloed"}:
        return "1"
    if text in {"0", "false", "no", "off", "unmuted", "unsoloed"}:
        return "0"
    raise GarageBandError(f"Expected a boolean value, got {value!r}.")


def _set_track_control(track: dict[str, Any], control_name: str, value: Any) -> dict[str, Any]:
    control = track["controls"].get(control_name)
    if not control:
        raise GarageBandError(f"Track {track['index']} has no visible {control_name} control.")
    path = control["path"]
    if control_name in {"mute", "solo"}:
        requested = _bool_text(value)
    else:
        requested = str(value)
    result = set_ui_value_path(path, requested)
    result["track"] = {"index": track["index"], "name": track["name"]}
    result["control"] = control_name
    result["requested_value"] = requested
    return result


def set_track(
    *,
    index: int | None = None,
    name: str | None = None,
    mute: bool | str | int | None = None,
    solo: bool | str | int | None = None,
    volume: str | int | float | None = None,
    pan: str | int | float | None = None,
    rename: str | None = None,
    max_depth: int = 7,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tracks_data = list_tracks(max_depth=max_depth, include_values=False, snapshot=snapshot)
    track = _select_track(tracks_data, index=index, name=name)
    updates: dict[str, Any] = {}
    if mute is not None:
        updates["mute"] = _set_track_control(track, "mute", mute)
    if solo is not None:
        updates["solo"] = _set_track_control(track, "solo", solo)
    if volume is not None:
        updates["volume"] = _set_track_control(track, "volume", volume)
    if pan is not None:
        updates["pan"] = _set_track_control(track, "pan", pan)
    if rename is not None:
        updates["name"] = _set_track_control(track, "name", rename)
    if not updates:
        raise GarageBandError("Provide at least one track update: mute, solo, volume, pan, or rename.")
    time.sleep(0.2)
    after = list_tracks(max_depth=max_depth, include_values=True)
    selected_after = None
    try:
        selected_after = _select_track(after, index=int(track["index"]))
    except GarageBandError:
        selected_after = None
    return {
        "selected": {"index": track["index"], "name": track["name"], "path": track["path"]},
        "updated": updates,
        "after": selected_after,
    }


def list_regions(*, max_depth: int = 8, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    snap = snapshot or ui_snapshot(max_depth=max_depth)
    regions: list[dict[str, Any]] = []
    for element in snap["elements"]:
        if element.get("role") != "AXLayoutItem":
            continue
        description = str(element.get("description", ""))
        if not description or description in {"Track Background"} or description.startswith("Track "):
            continue
        descendants = _element_under(snap["elements"], str(element["path"]))
        has_region_name = any(
            child.get("role") == "AXTextField"
            and str(child.get("description", "")) == description
            for child in descendants
        )
        if not has_region_name:
            continue
        regions.append(
            {
                "name": description,
                "path": element["path"],
                "position": _parse_point(element.get("position")),
                "size": _parse_size(element.get("size")),
                "handles": [
                    {
                        "description": child.get("description"),
                        "path": child.get("path"),
                        "position": _parse_point(child.get("position")),
                        "size": _parse_size(child.get("size")),
                    }
                    for child in descendants
                    if child.get("role") == "AXHandle"
                ],
            }
        )
    return {"count": len(regions), "regions": regions, "max_depth": max_depth}


SMART_CONTROL_ROLES = {"AXButton", "AXCheckBox", "AXSlider", "AXTextField", "AXPopUpButton", "AXRadioButton"}
SMART_CONTROL_TAB_LABELS = {"Track", "Master", "Controls", "EQ", "Compare"}


def _find_smart_controls_panel(snap: dict[str, Any]) -> dict[str, Any] | None:
    candidates = []
    for element in snap["elements"]:
        if element.get("role") != "AXGroup" or element.get("description") != "Smart Controls":
            continue
        size = _parse_size(element.get("size"))
        pos = _parse_point(element.get("position"))
        if not size or not pos:
            continue
        area = size["width"] * size["height"]
        candidates.append((area, pos["y"], element, size, pos))
    if not candidates:
        return None
    _, _, element, size, pos = max(candidates, key=lambda item: (item[0], item[1]))
    return {
        "path": element["path"],
        "position": pos,
        "size": size,
        "element": element,
    }


def _smart_control_label(element: dict[str, Any]) -> str:
    description = _missing_to_empty(element.get("description"))
    name = _missing_to_empty(element.get("name"))
    if description and description not in {"button", "checkbox", "pop up button", "radio group"}:
        return description
    if name:
        return name
    return str(element.get("role", "control"))


def smart_controls(
    *,
    show: bool = True,
    max_depth: int = 4,
    include_values: bool = False,
    include_disabled: bool = True,
    limit: int = 200,
) -> dict[str, Any]:
    snap_depth = max(3, min(8, int(max_depth)))
    snap = ui_snapshot(max_depth=snap_depth)
    panel_info = _find_smart_controls_panel(snap)
    show_result: dict[str, Any] = {"panel": "Smart Controls", "visible": panel_info is not None}
    if panel_info is None and show:
        clicked = click_ui("Smart Controls", role="AXCheckBox", exact=True)
        time.sleep(0.5)
        snap = ui_snapshot(max_depth=snap_depth)
        panel_info = _find_smart_controls_panel(snap)
        show_result = {"panel": "Smart Controls", "visible": panel_info is not None, "clicked": clicked}
    if panel_info is None:
        raise GarageBandError("GarageBand Smart Controls panel is not visible.")
    elements = _element_under(snap["elements"], str(panel_info["path"]))
    controls: list[dict[str, Any]] = []
    tabs: list[dict[str, Any]] = []
    limit = max(1, min(500, int(limit)))
    for element in elements:
        role = str(element.get("role", ""))
        if role not in SMART_CONTROL_ROLES:
            continue
        if not include_disabled and element.get("enabled") is not True:
            continue
        size = _parse_size(element.get("size"))
        if not size or size["width"] <= 0 or size["height"] <= 0:
            continue
        label = _smart_control_label(element)
        item: dict[str, Any] = {
            "index": len(controls) + len(tabs) + 1,
            "label": label,
            "path": element.get("path"),
            "role": role,
            "name": _missing_to_empty(element.get("name")),
            "description": _missing_to_empty(element.get("description")),
            "enabled": element.get("enabled"),
            "position": _parse_point(element.get("position")),
            "size": size,
        }
        if include_values:
            try:
                item["value"] = ui_info_path(str(element["path"])).get("value")
            except GarageBandError as exc:
                item["value_error"] = str(exc)
        is_tab = label in SMART_CONTROL_TAB_LABELS and role in {"AXRadioButton", "AXButton"}
        if is_tab:
            tabs.append(item)
        else:
            controls.append(item)
        if len(controls) + len(tabs) >= limit:
            break
    return {
        "panel": {
            "path": panel_info["path"],
            "position": panel_info["position"],
            "size": panel_info["size"],
            "show": show_result,
        },
        "max_depth": snap_depth,
        "tab_count": len(tabs),
        "control_count": len(controls),
        "tabs": tabs,
        "controls": controls,
        "empty_state": len(controls) == 0,
        "note": "When control_count is 0, GarageBand is showing an empty Smart Controls state for the selected track/patch.",
    }


def _select_smart_control(
    controls_data: dict[str, Any],
    *,
    query: str | None = None,
    path: str | None = None,
    role: str | None = None,
    include_tabs: bool = True,
    allow_first: bool = False,
) -> dict[str, Any]:
    candidates = list(controls_data.get("controls", []))
    if include_tabs:
        candidates.extend(controls_data.get("tabs", []))
    role_filter = role.casefold() if role else None
    if path:
        matches = [item for item in candidates if str(item.get("path", "")) == path]
        return _select_match(matches, allow_first=allow_first, kind="Smart Control")
    if not query or not query.strip():
        raise GarageBandError("Provide Smart Control query or path.")
    needle = query.casefold()
    matches = []
    for item in candidates:
        haystack = " ".join(str(item.get(key, "")) for key in ("label", "name", "description", "path", "role")).casefold()
        if needle not in haystack:
            continue
        if role_filter and role_filter != str(item.get("role", "")).casefold():
            continue
        matches.append(item)
    return _select_match(matches, allow_first=allow_first, kind="Smart Control")


def set_smart_control(
    *,
    query: str | None = None,
    path: str | None = None,
    value: str | int | float | bool | None = None,
    action: str | None = None,
    role: str | None = None,
    show: bool = True,
    max_depth: int = 4,
    include_tabs: bool = True,
    allow_first: bool = False,
) -> dict[str, Any]:
    controls_data = smart_controls(show=show, max_depth=max_depth, include_values=False, include_disabled=True)
    selected = _select_smart_control(
        controls_data,
        query=query,
        path=path,
        role=role,
        include_tabs=include_tabs,
        allow_first=allow_first,
    )
    target_path = str(selected["path"])
    if value is not None and action is not None:
        raise GarageBandError("Provide either Smart Control value or action, not both.")
    if value is not None:
        performed = set_ui_value_path(target_path, str(value))
        method = "set_value"
    else:
        action_name = action or "press"
        performed = perform_ui_action_path(target_path, action_name)
        method = "action"
    time.sleep(0.2)
    try:
        after = ui_info_path(target_path)
    except GarageBandError as exc:
        after = {"path": target_path, "error": str(exc)}
    return {
        "selected": selected,
        "method": method,
        "requested": {"value": value, "action": action},
        "performed": performed,
        "after": after,
    }


def wait_ui(
    query: str,
    *,
    role: str | None = None,
    enabled_only: bool = False,
    max_depth: int = 4,
    timeout_seconds: float = 10.0,
    interval_seconds: float = 0.5,
    limit: int = 10,
) -> dict[str, Any]:
    if not query.strip():
        raise GarageBandError("UI wait query is empty.")
    timeout_seconds = max(0.1, min(120.0, float(timeout_seconds)))
    interval_seconds = max(0.1, min(5.0, float(interval_seconds)))
    started = time.time()
    deadline = time.time() + timeout_seconds
    attempts = 0
    last_result: dict[str, Any] | None = None
    while True:
        attempts += 1
        result = find_ui_elements(
            query,
            role=role,
            enabled_only=enabled_only,
            max_depth=max_depth,
            limit=limit,
        )
        last_result = result
        if result["count"] > 0:
            result["found"] = True
            result["attempts"] = attempts
            result["waited_seconds"] = round(time.time() - started, 3)
            return result
        if time.time() >= deadline:
            break
        time.sleep(interval_seconds)
    return {
        "found": False,
        "attempts": attempts,
        "waited_seconds": round(time.time() - started, 3),
        "last_result": last_result,
    }


def click_ui_search(
    query: str,
    *,
    role: str | None = None,
    enabled_only: bool = True,
    max_depth: int = 4,
    allow_first: bool = False,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    found = find_ui_elements(
        query,
        role=role,
        enabled_only=enabled_only,
        max_depth=max_depth,
        limit=20,
        snapshot=snapshot,
    )
    match = _select_match(found["matches"], allow_first=allow_first, kind="UI")
    clicked = click_ui_path(match["path"])
    return {"query": query, "selected": match, "clicked": clicked, "match_count": found["count"]}


def ui_info_search(
    query: str,
    *,
    role: str | None = None,
    enabled_only: bool = True,
    max_depth: int = 4,
    allow_first: bool = False,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    found = find_ui_elements(
        query,
        role=role,
        enabled_only=enabled_only,
        max_depth=max_depth,
        limit=20,
        snapshot=snapshot,
    )
    match = _select_match(found["matches"], allow_first=allow_first, kind="UI")
    info = ui_info_path(match["path"])
    return {"query": query, "selected": match, "info": info, "match_count": found["count"]}


def set_ui_value_search(
    query: str,
    value: str,
    *,
    role: str | None = None,
    enabled_only: bool = True,
    max_depth: int = 4,
    allow_first: bool = False,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    found = find_ui_elements(
        query,
        role=role,
        enabled_only=enabled_only,
        max_depth=max_depth,
        limit=20,
        snapshot=snapshot,
    )
    match = _select_match(found["matches"], allow_first=allow_first, kind="UI")
    result = set_ui_value_path(match["path"], str(value))
    return {"query": query, "selected": match, "set": result["set"], "match_count": found["count"]}


def project_settings(
    *,
    max_depth: int = 3,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for key, (query, role) in PROJECT_SETTING_CONTROLS.items():
        settings[key] = ui_info_search(
            query,
            role=role,
            enabled_only=True,
            max_depth=max_depth,
            snapshot=snapshot,
        )
    return {
        "settings": settings,
        "values": {key: result["info"]["value"] for key, result in settings.items()},
    }


def project_setting_options() -> dict[str, Any]:
    return {
        "options": PROJECT_SETTING_OPTIONS,
        "notes": {
            "tempo": "Tempo is a numeric slider. Use project-settings to read the current value and set-project-settings to request a target; the bridge reports the actual accepted value.",
            "source": "GarageBand project LCD controls do not expose AXAllowedValues here, so these are built-in catalogs for the known key and time-signature popups.",
            "setting_method": "Key signature and time signature are selected by opening the native popup, typing the target label, pressing Return, and reading the accepted value back.",
            "verification": "Always inspect exact/all_exact from set-project-settings; false means GarageBand did not accept that UI change.",
        },
    }


def _normalize_project_popup_value(key: str, value: str) -> str:
    requested = " ".join(str(value).strip().replace("♯", "#").replace("♭", "b").split())
    options = PROJECT_SETTING_OPTIONS[key]
    for option in options:
        if requested.lower() == option.lower():
            return option
    raise GarageBandError(
        f"Unsupported {key.replace('_', ' ')}: {value!r}. "
        f"Use one of: {', '.join(options)}"
    )


def _normalize_garageband_setting_value(value: str) -> str:
    return " ".join(str(value).strip().replace("♯", "#").replace("♭", "b").split())


def _project_popup_type_select(path: str, target: str) -> dict[str, str]:
    script = _ui_path_action_script(
        """
        set targetValue to item 2 of argv
        click targetElement
        delay 0.2
        keystroke targetValue
        delay 0.1
        key code 36
        delay 0.4
        return my describeElement(targetElement)
        """
    )
    raw = _osa(script, path, target, timeout=15)
    role_value, name, description, accepted = (raw.split("\t") + ["", "", "", ""])[:4]
    return {
        "role": role_value,
        "name": name,
        "description": description,
        "value": accepted,
        "method": "popup_type_select",
    }


def _project_key_sharp_select(path: str, target: str) -> dict[str, Any]:
    base = target.replace("#", "", 1)
    base_result = _project_popup_type_select(path, base)
    if _normalize_garageband_setting_value(base_result["value"]) != base:
        return {
            **base_result,
            "method": "popup_type_select_then_arrow_up",
            "intermediate": base_result,
            "intermediate_exact": False,
        }
    script = _ui_path_action_script(
        """
        click targetElement
        delay 0.2
        key code 126
        delay 0.1
        key code 36
        delay 0.4
        return my describeElement(targetElement)
        """
    )
    raw = _osa(script, path, timeout=15)
    role_value, name, description, accepted = (raw.split("\t") + ["", "", "", ""])[:4]
    return {
        "role": role_value,
        "name": name,
        "description": description,
        "value": accepted,
        "method": "popup_type_select_then_arrow_up",
        "intermediate": base_result,
        "intermediate_exact": True,
    }


def set_project_popup_setting(
    key: str,
    value: str,
    *,
    max_depth: int = 3,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if key not in PROJECT_SETTING_OPTIONS:
        raise GarageBandError(f"{key} is not a popup project setting.")
    target = _normalize_project_popup_value(key, value)
    query, role = PROJECT_SETTING_CONTROLS[key]
    found = find_ui_elements(
        query,
        role=role,
        enabled_only=True,
        max_depth=max_depth,
        limit=20,
        snapshot=snapshot,
    )
    match = _select_match(found["matches"], allow_first=False, kind="UI")
    before = ui_info_path(match["path"])
    if _normalize_garageband_setting_value(str(before.get("value", ""))) == target:
        return {
            "query": query,
            "selected": match,
            "set": {
                "path": match["path"],
                "requested_value": str(value),
                "canonical_requested_value": target,
                "role": before["role"],
                "name": before["name"],
                "description": before["description"],
                "value": before["value"],
                "accepted_value": before["value"],
                "exact": True,
                "already": True,
                "method": "already_exact",
            },
            "match_count": found["count"],
        }

    if key == "key_signature" and "#" in target:
        selected = _project_key_sharp_select(match["path"], target)
    else:
        selected = _project_popup_type_select(match["path"], target)
    accepted = selected["value"]
    return {
        "query": query,
        "selected": match,
        "set": {
            "path": match["path"],
            "requested_value": str(value),
            "canonical_requested_value": target,
            "role": selected["role"],
            "name": selected["name"],
            "description": selected["description"],
            "value": accepted,
            "accepted_value": accepted,
            "normalized_accepted_value": _normalize_garageband_setting_value(accepted),
            "exact": _normalize_garageband_setting_value(accepted) == target,
            "method": selected["method"],
        },
        "match_count": found["count"],
        "before": before,
        "selection": selected,
    }


def set_project_settings(
    *,
    tempo: str | int | float | None = None,
    key_signature: str | None = None,
    time_signature: str | None = None,
    max_depth: int = 3,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested = {
        "tempo": tempo,
        "key_signature": key_signature,
        "time_signature": time_signature,
    }
    updates: dict[str, Any] = {}
    for key, value in requested.items():
        if value is None or str(value).strip() == "":
            continue
        if key == "tempo":
            updates[key] = set_project_tempo(
                value,
                max_depth=max_depth,
                snapshot=snapshot,
            )
        else:
            updates[key] = set_project_popup_setting(
                key,
                str(value),
                max_depth=max_depth,
                snapshot=snapshot,
            )
    if not updates:
        raise GarageBandError("Provide at least one project setting: tempo, key_signature, or time_signature.")
    for key, result in updates.items():
        set_payload = result.get("set", {})
        requested_value = str(requested[key])
        accepted_value = str(set_payload.get("value", ""))
        set_payload.setdefault("requested_value", requested_value)
        set_payload["accepted_value"] = accepted_value
        exact_target = str(set_payload.get("canonical_requested_value", requested_value))
        set_payload.setdefault("exact", _normalize_garageband_setting_value(accepted_value) == exact_target)
        result["set"] = set_payload
    return {
        "updated": updates,
        "values": {key: result["set"]["value"] for key, result in updates.items()},
        "all_exact": all(bool(result["set"].get("exact")) for result in updates.values()),
    }


def click_ui(name: str, role: str | None = None, exact: bool = False) -> dict[str, Any]:
    if not name.strip():
        raise GarageBandError("UI control name is empty.")
    if not is_running():
        launch()
    wait_until_running()
    role = role or ""
    script = textwrap.dedent(
        """
        on run argv
          set targetName to item 1 of argv
          set targetRole to item 2 of argv
          set exactMatch to ((item 3 of argv) is "true")
          tell application "GarageBand" to activate
          delay 0.2
          tell application "System Events"
            tell process "GarageBand"
              set found to my clickFirst(UI elements, targetName, targetRole, exactMatch)
              if found is "" then error "No visible GarageBand UI element matched name: " & targetName
              return found
            end tell
          end tell
        end run

        on clickFirst(elementsList, targetName, targetRole, exactMatch)
          tell application "System Events"
            repeat with el in elementsList
              set elName to ""
              set elRole to ""
              try
                set elName to name of el as text
              end try
              try
                set elRole to role of el as text
              end try
              set roleOK to (targetRole is "" or elRole is targetRole)
              set nameOK to false
              ignoring case
                if exactMatch then
                  if elName is targetName then set nameOK to true
                else
                  if elName contains targetName then set nameOK to true
                end if
              end ignoring
              if roleOK and nameOK then
                click el
                return elRole & tab & elName
              end if
              try
                set nested to my clickFirst(UI elements of el, targetName, targetRole, exactMatch)
                if nested is not "" then return nested
              end try
            end repeat
            return ""
          end tell
        end clickFirst
        """
    )
    raw = _osa(script, name, role, "true" if exact else "false", timeout=30)
    found_role, _, found_name = raw.partition("\t")
    return {"clicked": {"role": found_role, "name": found_name}, "query": {"name": name, "role": role, "exact": exact}}


def _ui_path_action_script(action_body: str) -> str:
    return textwrap.dedent(
        f"""
        on run argv
          set targetPath to item 1 of argv
          tell application "GarageBand" to activate
          delay 0.5
          tell application "System Events"
            set targetElement to my elementAtPath(targetPath)
            {action_body}
          end tell
        end run

        on elementAtPath(targetPath)
          tell application "System Events"
            tell process "GarageBand"
              set triesLeft to 30
              repeat while ((count of windows) is 0 and triesLeft > 0)
                delay 0.1
                set triesLeft to triesLeft - 1
              end repeat
              if (count of windows) is 0 then error "GarageBand has no visible windows"
              if targetPath does not start with "window[" then error "UI path must start with window[index]"
              set AppleScript's text item delimiters to "]"
              set pathParts to text items of targetPath
              set windowPart to item 1 of pathParts
              set AppleScript's text item delimiters to "["
              set windowIndex to (item 2 of text items of windowPart) as integer
              set currentElement to window windowIndex

              set restPath to ""
              if (count of pathParts) > 1 then set restPath to item 2 of pathParts
              if restPath starts with "/" then set restPath to text 2 thru -1 of restPath
              if restPath is not "" then
                set AppleScript's text item delimiters to "/"
                set childParts to text items of restPath
                repeat with childPart in childParts
                  if childPart is not "" then
                    set currentElement to UI element (childPart as integer) of currentElement
                  end if
                end repeat
              end if
              set AppleScript's text item delimiters to ""
              return currentElement
            end tell
          end tell
        end elementAtPath

        on describeElement(el)
          tell application "System Events"
            set elRole to ""
            set elName to ""
            set elDesc to ""
            set elValue to ""
            try
              set elRole to role of el as text
            end try
            try
              set elName to name of el as text
            end try
            try
              set elDesc to description of el as text
            end try
            try
              set elValue to value of el as text
            end try
            return elRole & tab & elName & tab & elDesc & tab & elValue
          end tell
        end describeElement
        """
    )


def ui_info_path(path: str) -> dict[str, Any]:
    if not path.strip():
        raise GarageBandError("UI path is empty.")
    if not is_running():
        launch()
    wait_until_running()
    script = _ui_path_action_script("return my describeElement(targetElement)")
    raw = _osa(script, path, timeout=30)
    role, name, description, value = (raw.split("\t") + ["", "", "", ""])[:4]
    return {
        "path": path,
        "role": role,
        "name": name,
        "description": description,
        "value": value,
    }


def ui_details_path(path: str) -> dict[str, Any]:
    if not path.strip():
        raise GarageBandError("UI path is empty.")
    if not is_running():
        launch()
    wait_until_running()
    script = textwrap.dedent(
        """
        on run argv
          set targetPath to item 1 of argv
          tell application "GarageBand" to activate
          delay 0.5
          tell application "System Events"
            set targetElement to my elementAtPath(targetPath)
            set sep to ASCII character 31
            return targetPath & tab & ¬
              my safeText("role", targetElement) & tab & ¬
              my safeText("name", targetElement) & tab & ¬
              my safeText("description", targetElement) & tab & ¬
              my safeText("value", targetElement) & tab & ¬
              my safeText("value description", targetElement) & tab & ¬
              my boolText(my safeBool("enabled", targetElement)) & tab & ¬
              my boolText(my safeBool("focused", targetElement)) & tab & ¬
              my safeText("position", targetElement) & tab & ¬
              my safeText("size", targetElement) & tab & ¬
              my safeText("minimum value", targetElement) & tab & ¬
              my safeText("maximum value", targetElement) & tab & ¬
              my countText("UI elements", targetElement) & tab & ¬
              my actionNamesText(targetElement, sep) & tab & ¬
              my attributeNamesText(targetElement, sep)
          end tell
        end run

        on elementAtPath(targetPath)
          tell application "System Events"
            tell process "GarageBand"
              set triesLeft to 30
              repeat while ((count of windows) is 0 and triesLeft > 0)
                delay 0.1
                set triesLeft to triesLeft - 1
              end repeat
              if (count of windows) is 0 then error "GarageBand has no visible windows"
              if targetPath does not start with "window[" then error "UI path must start with window[index]"
              set AppleScript's text item delimiters to "]"
              set pathParts to text items of targetPath
              set windowPart to item 1 of pathParts
              set AppleScript's text item delimiters to "["
              set windowIndex to (item 2 of text items of windowPart) as integer
              set currentElement to window windowIndex

              set restPath to ""
              if (count of pathParts) > 1 then set restPath to item 2 of pathParts
              if restPath starts with "/" then set restPath to text 2 thru -1 of restPath
              if restPath is not "" then
                set AppleScript's text item delimiters to "/"
                set childParts to text items of restPath
                repeat with childPart in childParts
                  if childPart is not "" then
                    set currentElement to UI element (childPart as integer) of currentElement
                  end if
                end repeat
              end if
              set AppleScript's text item delimiters to ""
              return currentElement
            end tell
          end tell
        end elementAtPath

        on safeText(propName, el)
          tell application "System Events"
            try
              if propName is "role" then return role of el as text
              if propName is "name" then return name of el as text
              if propName is "description" then return description of el as text
              if propName is "value" then return value of el as text
              if propName is "value description" then return value of attribute "AXValueDescription" of el as text
              if propName is "position" then
                set p to position of el
                return (item 1 of p as text) & "," & (item 2 of p as text)
              end if
              if propName is "size" then
                set s to size of el
                return (item 1 of s as text) & "," & (item 2 of s as text)
              end if
              if propName is "minimum value" then return minimum value of el as text
              if propName is "maximum value" then return maximum value of el as text
            end try
          end tell
          return ""
        end safeText

        on safeBool(propName, el)
          tell application "System Events"
            try
              if propName is "enabled" then return enabled of el
              if propName is "focused" then return focused of el
            end try
          end tell
          return missing value
        end safeBool

        on boolText(value)
          if value is missing value then return ""
          if value then return "true"
          return "false"
        end boolText

        on countText(propName, el)
          tell application "System Events"
            try
              if propName is "UI elements" then return count of UI elements of el as text
            end try
          end tell
          return "0"
        end countText

        on actionNamesText(el, sep)
          tell application "System Events"
            set namesList to {}
            try
              repeat with a in actions of el
                try
                  set end of namesList to name of a as text
                end try
              end repeat
            end try
            return my textListText(namesList, sep)
          end tell
        end actionNamesText

        on attributeNamesText(el, sep)
          tell application "System Events"
            set namesList to {}
            try
              repeat with a in attributes of el
                try
                  set end of namesList to name of a as text
                end try
              end repeat
            end try
            return my textListText(namesList, sep)
          end tell
        end attributeNamesText

        on textListText(valuesList, sep)
          set payload to ""
          repeat with i from 1 to count of valuesList
            if i > 1 then set payload to payload & sep
            set payload to payload & (item i of valuesList as text)
          end repeat
          return payload
        end textListText
        """
    )
    raw = _osa(script, path, timeout=30)
    fields = (raw.split("\t") + [""] * 15)[:15]
    (
        returned_path,
        role,
        name,
        description,
        value,
        value_description,
        enabled,
        focused,
        position,
        size,
        min_value,
        max_value,
        child_count,
        actions,
        attributes,
    ) = fields

    def parse_bool(raw_value: str) -> bool | None:
        if raw_value == "true":
            return True
        if raw_value == "false":
            return False
        return None

    def parse_count(raw_value: str) -> int:
        try:
            return int(raw_value)
        except ValueError:
            return 0

    def parse_list(raw_value: str) -> list[str]:
        return [item for item in raw_value.split("\x1f") if item]

    details = {
        "path": returned_path,
        "role": role,
        "name": name,
        "description": description,
        "value": value,
        "value_description": value_description,
        "enabled": parse_bool(enabled),
        "focused": parse_bool(focused),
        "position": position,
        "size": size,
        "min_value": min_value,
        "max_value": max_value,
        "child_count": parse_count(child_count),
        "actions": parse_list(actions),
        "attributes": parse_list(attributes),
    }
    setting_key = PROJECT_SETTING_LABEL_TO_KEY.get(description)
    if setting_key in PROJECT_SETTING_OPTIONS:
        details["known_options"] = PROJECT_SETTING_OPTIONS[setting_key]
        details["known_options_source"] = "garageband_bridge_project_setting_catalog"
    return details


def ui_details_search(
    query: str,
    *,
    role: str | None = None,
    enabled_only: bool = True,
    max_depth: int = 4,
    allow_first: bool = False,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    found = find_ui_elements(
        query,
        role=role,
        enabled_only=enabled_only,
        max_depth=max_depth,
        limit=20,
        snapshot=snapshot,
    )
    match = _select_match(found["matches"], allow_first=allow_first, kind="UI")
    details = ui_details_path(match["path"])
    return {"query": query, "selected": match, "details": details, "match_count": found["count"]}


def click_ui_path(path: str) -> dict[str, Any]:
    if not path.strip():
        raise GarageBandError("UI path is empty.")
    if not is_running():
        launch()
    wait_until_running()
    script = _ui_path_action_script(
        """
        click targetElement
        return my describeElement(targetElement)
        """
    )
    raw = _osa(script, path, timeout=30)
    role, name, description, value = (raw.split("\t") + ["", "", "", ""])[:4]
    return {
        "clicked": {"path": path, "role": role, "name": name, "description": description, "value": value}
    }


def set_ui_value_path(path: str, value: str) -> dict[str, Any]:
    if not path.strip():
        raise GarageBandError("UI path is empty.")
    if not is_running():
        launch()
    wait_until_running()
    script = _ui_path_action_script(
        """
        set newValue to item 2 of argv
        set value of targetElement to newValue
        return my describeElement(targetElement)
        """
    )
    raw = _osa(script, path, str(value), timeout=30)
    role, name, description, new_value = (raw.split("\t") + ["", "", "", ""])[:4]
    return {
        "set": {
            "path": path,
            "requested_value": str(value),
            "role": role,
            "name": name,
            "description": description,
            "value": new_value,
        }
    }


def perform_ui_action_path(path: str, action_name: str) -> dict[str, Any]:
    if not path.strip():
        raise GarageBandError("UI path is empty.")
    normalized_action = UI_ACTION_ALIASES.get(action_name.strip().lower(), action_name.strip())
    if normalized_action not in set(UI_ACTION_ALIASES.values()):
        supported = ", ".join(sorted(set(UI_ACTION_ALIASES) | set(UI_ACTION_ALIASES.values())))
        raise GarageBandError(f"Unsupported UI action: {action_name}. Supported: {supported}")
    if not is_running():
        launch()
    wait_until_running()
    script = _ui_path_action_script(
        """
        set actionName to item 2 of argv
        perform action actionName of targetElement
        return my describeElement(targetElement)
        """
    )
    raw = _osa(script, path, normalized_action, timeout=30)
    role, name, description, new_value = (raw.split("\t") + ["", "", "", ""])[:4]
    return {
        "performed": {
            "path": path,
            "action": normalized_action,
            "requested_action": action_name,
            "role": role,
            "name": name,
            "description": description,
            "value": new_value,
        }
    }


def perform_ui_action_search(
    query: str,
    action_name: str,
    *,
    role: str | None = None,
    enabled_only: bool = True,
    max_depth: int = 4,
    allow_first: bool = False,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    found = find_ui_elements(
        query,
        role=role,
        enabled_only=enabled_only,
        max_depth=max_depth,
        limit=20,
        snapshot=snapshot,
    )
    match = _select_match(found["matches"], allow_first=allow_first, kind="UI")
    performed = perform_ui_action_path(match["path"], action_name)
    return {"query": query, "selected": match, "performed": performed["performed"], "match_count": found["count"]}


def _float_value(value: Any, label: str) -> float:
    try:
        return float(str(value).strip())
    except ValueError as exc:
        raise GarageBandError(f"{label} must be numeric, got {value!r}.") from exc


def set_project_tempo(
    tempo: str | int | float,
    *,
    max_depth: int = 3,
    snapshot: dict[str, Any] | None = None,
    tolerance: float = 0.5,
    max_steps: int = 300,
) -> dict[str, Any]:
    target = _float_value(tempo, "tempo")
    found = find_ui_elements(
        "Tempo",
        role="AXSlider",
        enabled_only=True,
        max_depth=max_depth,
        limit=20,
        snapshot=snapshot,
    )
    match = _select_match(found["matches"], allow_first=False, kind="UI")
    info = ui_info_path(match["path"])
    current = _float_value(info["value"], "current tempo")
    steps = 0
    action_history: list[dict[str, Any]] = []

    while abs(current - target) > tolerance and steps < max_steps:
        action_name = "AXIncrement" if current < target else "AXDecrement"
        previous = current
        action_result = perform_ui_action_path(match["path"], action_name)
        steps += 1
        new_value = _float_value(action_result["performed"]["value"], "tempo")
        action_history.append(
            {
                "action": action_name,
                "before": previous,
                "after": new_value,
            }
        )
        if abs(new_value - target) > abs(previous - target):
            reverse = "AXDecrement" if action_name == "AXIncrement" else "AXIncrement"
            reverse_result = perform_ui_action_path(match["path"], reverse)
            restored = _float_value(reverse_result["performed"]["value"], "tempo")
            action_history.append(
                {
                    "action": reverse,
                    "before": new_value,
                    "after": restored,
                    "reason": "restore_closer_value",
                }
            )
            current = restored
            break
        if new_value == previous:
            break
        current = new_value

    final_info = ui_info_path(match["path"])
    final_value = _float_value(final_info["value"], "tempo")
    return {
        "query": "Tempo",
        "selected": match,
        "set": {
            "path": match["path"],
            "requested_value": str(tempo),
            "role": final_info["role"],
            "name": final_info["name"],
            "description": final_info["description"],
            "value": final_info["value"],
            "exact": abs(final_value - target) <= tolerance,
            "method": "AXIncrement/AXDecrement",
            "steps": steps,
            "tolerance": tolerance,
        },
        "match_count": found["count"],
        "action_history": action_history,
    }


def screenshot(output_path: str) -> dict[str, Any]:
    if not output_path:
        raise GarageBandError("Screenshot output path is required.")
    if not is_running():
        launch()
    wait_until_running()
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    script = textwrap.dedent(
        """
        tell application "GarageBand" to activate
        delay 0.3
        tell application "System Events"
          tell process "GarageBand"
            if (count of windows) is 0 then error "GarageBand has no visible windows"
            set winPos to position of window 1
            set winSize to size of window 1
            set x to item 1 of winPos
            set y to item 2 of winPos
            set w to item 1 of winSize
            set h to item 2 of winSize
            return (x as text) & "," & (y as text) & "," & (w as text) & "," & (h as text)
          end tell
        end tell
        """
    )
    rect = _osa(script, timeout=20)
    proc = _run(["screencapture", "-x", "-R", rect, str(output)], timeout=20)
    if proc.returncode != 0:
        raise GarageBandError((proc.stderr or proc.stdout or "screencapture failed").strip())
    return {"path": str(output), "rect": rect, "bytes": output.stat().st_size}


def annotated_screenshot(
    output_path: str,
    *,
    map_output_path: str | None = None,
    max_depth: int = 3,
    include_grid: bool = True,
    grid_step: int = 100,
    include_disabled: bool = False,
    limit: int = 120,
) -> dict[str, Any]:
    if not output_path:
        raise GarageBandError("Annotated screenshot output path is required.")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise GarageBandError("annotated-screenshot requires Pillow for drawing overlays.") from exc

    capture = screenshot(output_path)
    snap = ui_snapshot(max_depth=max_depth)
    image_path = Path(capture["path"])
    image = Image.open(image_path).convert("RGBA")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    rect_x, rect_y, rect_width, rect_height = _parse_rect_text(capture["rect"])
    scale_x = image.width / rect_width if rect_width else 1.0
    scale_y = image.height / rect_height if rect_height else 1.0

    if include_grid:
        step = max(25, int(grid_step))
        for x in range(0, rect_width + 1, step):
            px = int(round(x * scale_x))
            draw.line([(px, 0), (px, image.height)], fill=(255, 255, 255, 70), width=1)
            draw.text((px + 4, 4), str(x), fill=(255, 255, 255, 210), font=font)
        for y in range(0, rect_height + 1, step):
            py = int(round(y * scale_y))
            draw.line([(0, py), (image.width, py)], fill=(255, 255, 255, 70), width=1)
            draw.text((4, py + 4), str(y), fill=(255, 255, 255, 210), font=font)

    actionable_roles = {"AXButton", "AXCheckBox", "AXSlider", "AXTextField", "AXPopUpButton", "AXRadioButton", "AXMenuButton"}
    targets: list[dict[str, Any]] = []
    for element in snap["elements"]:
        role = str(element.get("role", ""))
        if role not in actionable_roles:
            continue
        if not include_disabled and element.get("enabled") is not True:
            continue
        pos = _parse_point(element.get("position"))
        size = _parse_size(element.get("size"))
        if not pos or not size:
            continue
        if size["width"] < 4 or size["height"] < 4:
            continue
        window_x = pos["x"] - rect_x
        window_y = pos["y"] - rect_y
        if window_x + size["width"] < 0 or window_y + size["height"] < 0:
            continue
        if window_x > rect_width or window_y > rect_height:
            continue
        targets.append(
            {
                "id": len(targets) + 1,
                "path": element.get("path"),
                "role": role,
                "name": _missing_to_empty(element.get("name")),
                "description": _missing_to_empty(element.get("description")),
                "enabled": element.get("enabled"),
                "window_box": {
                    "x": window_x,
                    "y": window_y,
                    "width": size["width"],
                    "height": size["height"],
                },
                "window_center": {
                    "x": round(window_x + (size["width"] / 2), 1),
                    "y": round(window_y + (size["height"] / 2), 1),
                },
                "screen_center": {
                    "x": round(pos["x"] + (size["width"] / 2), 1),
                    "y": round(pos["y"] + (size["height"] / 2), 1),
                },
            }
        )
        if len(targets) >= max(1, min(500, int(limit))):
            break

    for target in targets:
        box = target["window_box"]
        left = int(round(box["x"] * scale_x))
        top = int(round(box["y"] * scale_y))
        right = int(round((box["x"] + box["width"]) * scale_x))
        bottom = int(round((box["y"] + box["height"]) * scale_y))
        color = (53, 162, 255, 230)
        draw.rectangle([(left, top), (right, bottom)], outline=color, width=3)
        label = str(target["id"])
        label_w = max(16, len(label) * 7 + 8)
        label_h = 17
        draw.rectangle([(left, max(0, top - label_h)), (left + label_w, top)], fill=(0, 0, 0, 180))
        draw.text((left + 4, max(0, top - label_h + 2)), label, fill=(255, 255, 255, 255), font=font)

    image.convert("RGB").save(image_path)
    manifest_path = Path(map_output_path).expanduser().resolve() if map_output_path else image_path.with_suffix(".map.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "screenshot_path": str(image_path),
        "window_rect": {"x": rect_x, "y": rect_y, "width": rect_width, "height": rect_height},
        "image_size": {"width": image.width, "height": image.height},
        "scale": {"x": scale_x, "y": scale_y},
        "max_depth": max_depth,
        "include_disabled": include_disabled,
        "grid_step": grid_step if include_grid else None,
        "target_count": len(targets),
        "targets": targets,
        "usage": "Use window_center with garageband_window_click, or path with garageband_click_ui_path.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "path": str(image_path),
        "map_path": str(manifest_path),
        "bytes": image_path.stat().st_size,
        "target_count": len(targets),
        "window_rect": manifest["window_rect"],
        "usage": manifest["usage"],
    }


def window_rect() -> dict[str, Any]:
    if not is_running():
        launch()
    wait_until_running()
    script = textwrap.dedent(
        """
        tell application "GarageBand" to activate
        delay 0.3
        tell application "System Events"
          tell process "GarageBand"
            if (count of windows) is 0 then error "GarageBand has no visible windows"
            set winPos to position of window 1
            set winSize to size of window 1
            set x to item 1 of winPos
            set y to item 2 of winPos
            set w to item 1 of winSize
            set h to item 2 of winSize
            return (x as text) & "," & (y as text) & "," & (w as text) & "," & (h as text)
          end tell
        end tell
        """
    )
    rect = _osa(script, timeout=20)
    x, y, width, height = [int(float(part)) for part in rect.split(",")]
    return {"x": x, "y": y, "width": width, "height": height, "rect": rect}


def click_window(x: float, y: float) -> dict[str, Any]:
    rect = window_rect()
    absolute_x = int(round(rect["x"] + x))
    absolute_y = int(round(rect["y"] + y))
    script = textwrap.dedent(
        """
        on run argv
          set clickX to (item 1 of argv) as integer
          set clickY to (item 2 of argv) as integer
          tell application "GarageBand" to activate
          delay 0.2
          tell application "System Events"
            click at {clickX, clickY}
          end tell
          return (clickX as text) & "," & (clickY as text)
        end run
        """
    )
    clicked = _osa(script, str(absolute_x), str(absolute_y), timeout=10)
    return {"window_point": {"x": x, "y": y}, "screen_point": clicked, "window_rect": rect}


def drag_window(x1: float, y1: float, x2: float, y2: float, delay_seconds: float = 0.2) -> dict[str, Any]:
    rect = window_rect()
    start_x = int(round(rect["x"] + x1))
    start_y = int(round(rect["y"] + y1))
    end_x = int(round(rect["x"] + x2))
    end_y = int(round(rect["y"] + y2))
    delay_seconds = max(0.0, min(5.0, float(delay_seconds)))
    _osa('tell application "GarageBand" to activate', timeout=5)
    helper = Path(__file__).with_name("mouse_event.swift")
    proc = _run(
        [
            "swift",
            str(helper),
            "drag",
            str(start_x),
            str(start_y),
            str(end_x),
            str(end_y),
            str(delay_seconds),
        ],
        timeout=20,
    )
    if proc.returncode != 0:
        raise GarageBandError((proc.stderr or proc.stdout or "mouse drag failed").strip())
    dragged = proc.stdout.strip()
    return {
        "window_start": {"x": x1, "y": y1},
        "window_end": {"x": x2, "y": y2},
        "screen_drag": dragged,
        "window_rect": rect,
    }


def type_text(text: str) -> dict[str, Any]:
    if text is None:
        text = ""
    script = textwrap.dedent(
        """
        on run argv
          set textToType to item 1 of argv
          tell application "GarageBand" to activate
          delay 0.2
          tell application "System Events"
            keystroke textToType
          end tell
          return "ok"
        end run
        """
    )
    _osa(script, text, timeout=10)
    return {"typed_characters": len(text)}


def _find_ui_element(name: str, role: str | None = None, max_depth: int = 3) -> dict[str, Any] | None:
    snap = ui_snapshot(max_depth=max_depth)
    for element in snap["elements"]:
        if element.get("name") == name and (role is None or element.get("role") == role):
            return element
    return None


def _set_named_checkbox(name: str, enabled: bool) -> dict[str, Any]:
    element = _find_ui_element(name, role="AXCheckBox", max_depth=3)
    if not element:
        raise GarageBandError(f"Could not find GarageBand checkbox: {name}")
    info = ui_info_path(element["path"])
    current = str(info.get("value", "")).strip()
    desired = "1" if enabled else "0"
    if current == desired:
        return {"name": name, "path": element["path"], "already": True, "value": current}
    try:
        result = set_ui_value_path(element["path"], desired)
        result["name"] = name
        return result
    except GarageBandError:
        clicked = click_ui_path(element["path"])
        clicked["name"] = name
        clicked["fallback_click"] = True
        return clicked


def _panel_visible(panel_description: str) -> bool:
    snap = ui_snapshot(max_depth=3)
    return any(
        element.get("role") == "AXGroup"
        and element.get("description") == panel_description
        for element in snap["elements"]
    )


def _show_panel(button_name: str, panel_description: str) -> dict[str, Any]:
    if _panel_visible(panel_description):
        return {"panel": panel_description, "visible": True, "already": True}
    clicked = click_ui(button_name, role="AXCheckBox", exact=True)
    time.sleep(0.5)
    visible = _panel_visible(panel_description)
    return {"panel": panel_description, "visible": visible, "clicked": clicked}


def _library_controls() -> dict[str, Any]:
    snap = ui_snapshot(max_depth=6)
    search_fields = [
        element for element in snap["elements"]
        if element.get("role") == "AXTextField"
        and element.get("description") == "search text field"
        and _parse_point(element.get("position"))
        and (_parse_point(element.get("position")) or {"x": 999999})["x"] < 500
    ]
    browser_matches = [
        element for element in snap["elements"]
        if element.get("role") == "AXBrowser"
        and element.get("description") == "Library"
        and _parse_point(element.get("position"))
        and (_parse_point(element.get("position")) or {"x": 999999})["x"] < 500
    ]
    if not search_fields:
        raise GarageBandError("Could not find GarageBand Library search field. Show the Library panel and try again.")
    if not browser_matches:
        raise GarageBandError("Could not find GarageBand Library browser. Show the Library panel and try again.")
    return {
        "search_field": search_fields[0],
        "browser": browser_matches[0],
    }


def library_search(
    query: str | None = None,
    *,
    show: bool = True,
    limit: int = 50,
    result_depth: int = 4,
) -> dict[str, Any]:
    panel = _show_panel("Library", "Library") if show else {"panel": "Library", "visible": _panel_visible("Library")}
    if not panel.get("visible"):
        raise GarageBandError("GarageBand Library panel is not visible.")
    controls = _library_controls()
    if query is not None:
        set_ui_value_path(str(controls["search_field"]["path"]), query)
        time.sleep(0.6)
        controls = _library_controls()
    subtree = _ui_subtree_snapshot(str(controls["browser"]["path"]), max_depth=result_depth, timeout=45)
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for element in subtree["elements"]:
        if element.get("role") != "AXStaticText":
            continue
        label = str(element.get("name") or element.get("description") or "").strip()
        if not label or label == "missing value":
            continue
        key = (label, str(element.get("path")))
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "index": len(results) + 1,
                "name": label,
                "path": element["path"],
                "enabled": element.get("enabled"),
                "position": _parse_point(element.get("position")),
                "size": _parse_size(element.get("size")),
            }
        )
    limit = max(1, min(500, int(limit)))
    return {
        "query": query,
        "panel": panel,
        "search_field": {
            "path": controls["search_field"]["path"],
            "value": ui_info_path(str(controls["search_field"]["path"])).get("value"),
        },
        "browser": {
            "path": controls["browser"]["path"],
            "position": _parse_point(controls["browser"].get("position")),
            "size": _parse_size(controls["browser"].get("size")),
        },
        "count": len(results),
        "results": results[:limit],
        "truncated": len(results) > limit,
    }


def library_select(
    query: str | None = None,
    *,
    name: str | None = None,
    index: int | None = None,
    allow_first: bool = False,
    show: bool = True,
) -> dict[str, Any]:
    search_query = query if query is not None else name
    found = library_search(search_query, show=show, limit=200)
    results = found["results"]
    selected: dict[str, Any]
    if index is not None:
        matches = [result for result in results if int(result["index"]) == int(index)]
        selected = _select_match(matches, allow_first=False, kind="Library result")
    else:
        needle = str(name if name is not None else (query or "")).casefold().strip()
        if needle:
            matches = [result for result in results if needle in str(result["name"]).casefold()]
            selected = _select_match(matches, allow_first=allow_first, kind="Library result")
        else:
            selected = _select_match(results, allow_first=allow_first, kind="Library result")
    pressed = perform_ui_action_path(str(selected["path"]), "press")
    time.sleep(0.8)
    return {
        "query": query,
        "name": name,
        "index": index,
        "selected": selected,
        "pressed": pressed,
        "match_count": found["count"],
        "visible_results": results,
    }


def _loop_visible_row_count(table_path: str) -> int | None:
    script = _ui_path_action_script(
        """
        try
          set rowsList to value of attribute "AXVisibleRows" of targetElement
          return count of rowsList as text
        on error
          return ""
        end try
        """
    )
    raw = _osa(script, table_path, timeout=10).strip()
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_item_count(text: str) -> int | None:
    match = re.search(r"(\d+)", text.replace(",", ""))
    if not match:
        return None
    return int(match.group(1))


def _loop_browser_controls() -> dict[str, Any]:
    snap = ui_snapshot(max_depth=5)
    apple_loops_roots = [
        element for element in snap["elements"]
        if element.get("role") == "AXGroup"
        and element.get("description") == "Apple Loops"
        and element.get("depth") == 1
    ]
    if not apple_loops_roots:
        raise GarageBandError("Could not find GarageBand Loop Browser panel. Show the Loop Browser and try again.")
    root = apple_loops_roots[-1]
    root_path = str(root["path"])
    descendants = _element_under(snap["elements"], root_path)
    search_fields = [
        element for element in descendants
        if element.get("role") == "AXTextField"
        and element.get("description") == "search text field"
    ]
    tables = [
        element for element in descendants
        if element.get("role") == "AXTable"
        and element.get("description") == "Loops"
    ]
    scroll_areas = [
        element for element in descendants
        if element.get("role") == "AXScrollArea"
        and _parse_size(element.get("size"))
        and (_parse_size(element.get("size")) or {"height": 0})["height"] > 100
    ]
    item_labels = [
        element for element in descendants
        if element.get("role") == "AXStaticText"
        and re.search(r"\d+\s+items?", str(element.get("name", "")), re.IGNORECASE)
    ]
    if not search_fields:
        raise GarageBandError("Could not find GarageBand Loop Browser search field.")
    if not tables:
        raise GarageBandError("Could not find GarageBand Loop Browser table.")
    table = tables[0]
    table_position = _parse_point(table.get("position"))
    table_size = _parse_size(table.get("size"))
    scroll_area = scroll_areas[0] if scroll_areas else None
    scroll_position = _parse_point(scroll_area.get("position")) if scroll_area else None
    scroll_size = _parse_size(scroll_area.get("size")) if scroll_area else None
    item_text = str(item_labels[-1].get("name")) if item_labels else ""
    return {
        "root": root,
        "search_field": search_fields[0],
        "table": table,
        "table_position": table_position,
        "table_size": table_size,
        "scroll_area": scroll_area,
        "scroll_position": scroll_position,
        "scroll_size": scroll_size,
        "item_count_text": item_text,
        "item_count": _parse_item_count(item_text),
        "visible_row_count": _loop_visible_row_count(str(table["path"])),
    }


def loop_search(
    query: str | None = None,
    *,
    show: bool = True,
) -> dict[str, Any]:
    panel = _show_panel("Loop Browser", "Apple Loops") if show else {"panel": "Apple Loops", "visible": _panel_visible("Apple Loops")}
    if not panel.get("visible"):
        raise GarageBandError("GarageBand Loop Browser panel is not visible.")
    controls = _loop_browser_controls()
    if query is not None:
        set_ui_value_path(str(controls["search_field"]["path"]), query)
        try:
            perform_ui_action_path(str(controls["search_field"]["path"]), "confirm")
        except GarageBandError:
            pass
        time.sleep(0.8)
        controls = _loop_browser_controls()
    search_value = ui_info_path(str(controls["search_field"]["path"])).get("value")
    return {
        "query": query,
        "panel": panel,
        "search_field": {
            "path": controls["search_field"]["path"],
            "value": search_value,
        },
        "table": {
            "path": controls["table"]["path"],
            "position": controls["table_position"],
            "size": controls["table_size"],
            "visible_row_count": controls["visible_row_count"],
        },
        "scroll_area": {
            "path": controls["scroll_area"]["path"] if controls.get("scroll_area") else None,
            "position": controls["scroll_position"],
            "size": controls["scroll_size"],
        },
        "item_count_text": controls["item_count_text"],
        "item_count": controls["item_count"],
        "note": "GarageBand does not expose visible Apple Loop names cheaply here; use index with loop-select after inspecting the filtered count. Rows with download icons can trigger Apple's sound/content installer if dragged.",
    }


def loop_select(
    query: str | None = None,
    *,
    index: int = 1,
    show: bool = True,
    row_height: float = 24.0,
    x_offset: float = 70.0,
) -> dict[str, Any]:
    search_result = loop_search(query, show=show)
    table_position = search_result["table"]["position"]
    visible_row_count = search_result["table"].get("visible_row_count")
    if not table_position:
        raise GarageBandError("Loop table position is not available.")
    index = int(index)
    if index < 1:
        raise GarageBandError("Loop row index must be 1 or greater.")
    if visible_row_count is not None and index > int(visible_row_count):
        raise GarageBandError(f"Loop row index {index} is outside the visible row count {visible_row_count}.")
    rect = window_rect()
    screen_x = float(table_position["x"]) + float(x_offset)
    screen_y = float(table_position["y"]) + (float(row_height) * (index - 0.5))
    clicked = click_window(screen_x - rect["x"], screen_y - rect["y"])
    time.sleep(0.4)
    return {
        "query": query,
        "index": index,
        "search": search_result,
        "clicked": clicked,
        "screen_point": {"x": int(round(screen_x)), "y": int(round(screen_y))},
        "row_height": row_height,
        "x_offset": x_offset,
    }


LOOP_DRAG_WARNING = (
    "Dragging an Apple Loop row can trigger Apple's sound/content installer when the row has a download icon. "
    "Inspect a screenshot first and drag only an already-installed row unless the user is ready for that prompt."
)


def loop_drag(
    query: str | None = None,
    *,
    index: int = 1,
    destination_x: float = 390.0,
    destination_y: float = 195.0,
    show: bool = True,
    row_height: float = 24.0,
    x_offset: float = 70.0,
    delay_seconds: float = 0.7,
    acknowledge_content_install_risk: bool = False,
) -> dict[str, Any]:
    if not acknowledge_content_install_risk:
        raise GarageBandError(
            "Refusing to drag an Apple Loop row until acknowledge_content_install_risk is true. "
            + LOOP_DRAG_WARNING
        )
    search_result = loop_search(query, show=show)
    table_position = search_result["table"]["position"]
    visible_row_count = search_result["table"].get("visible_row_count")
    if not table_position:
        raise GarageBandError("Loop table position is not available.")
    index = int(index)
    if index < 1:
        raise GarageBandError("Loop row index must be 1 or greater.")
    if visible_row_count is not None and index > int(visible_row_count):
        raise GarageBandError(f"Loop row index {index} is outside the visible row count {visible_row_count}.")

    rect = window_rect()
    source_screen_x = float(table_position["x"]) + float(x_offset)
    source_screen_y = float(table_position["y"]) + (float(row_height) * (index - 0.5))
    dragged = drag_window(
        source_screen_x - rect["x"],
        source_screen_y - rect["y"],
        float(destination_x),
        float(destination_y),
        delay_seconds=delay_seconds,
    )
    time.sleep(0.7)
    return {
        "query": query,
        "index": index,
        "search": search_result,
        "source_screen_point": {"x": int(round(source_screen_x)), "y": int(round(source_screen_y))},
        "destination_window_point": {"x": float(destination_x), "y": float(destination_y)},
        "dragged": dragged,
        "row_height": row_height,
        "x_offset": x_offset,
        "warning": LOOP_DRAG_WARNING,
        "verify_next": "Capture a screenshot or list regions after dragging to confirm GarageBand accepted the loop.",
    }


def dismiss_save_prompt(discard: bool = False) -> dict[str, Any]:
    """Dismiss GarageBand's save confirmation prompt when it is visible."""
    snap = ui_snapshot(max_depth=1)
    has_save_prompt = any(
        element.get("role") == "AXStaticText"
        and "Do you want to save the document" in str(element.get("name", ""))
        for element in snap["elements"]
    )
    if not has_save_prompt:
        return {"dismissed": False, "reason": "no_save_prompt"}
    if not discard:
        raise GarageBandError("GarageBand is showing a save prompt. Re-run with discard_unsaved enabled to click Don't Save.")
    for label in ("Don’t Save", "Don't Save"):
        try:
            result = click_ui(label, role="AXButton", exact=True)
            result["dismissed"] = True
            result["button"] = label
            return result
        except GarageBandError:
            continue
    raise GarageBandError("GarageBand save prompt was visible, but the Don't Save button could not be clicked.")


def make_from_tab(
    *,
    output_dir: str,
    name: str = "garageband-tab-song",
    tab_text: str | None = None,
    tab_file: str | None = None,
    image_path: str | None = None,
    image_url: str | None = None,
    bpm: int | None = None,
    open_in_garageband: bool = True,
    show_library: bool = False,
    show_smart_controls: bool = False,
    show_loop_browser: bool = False,
    master_volume: str | None = None,
    screenshot_output: str | None = None,
    snapshot_depth: int = 2,
    discard_unsaved: bool = False,
    arrange: bool = False,
    include_bass: bool = True,
    include_drums: bool = True,
    arrangement_style: str = "rock",
    repeat_count: int = 1,
    capo: int | None = None,
    tuning: str | None = None,
    export_output: str | None = None,
    export_format: str | None = None,
    export_quality: str | None = None,
    export_include_cycle: bool | str | int | None = None,
    export_overwrite: bool = False,
    export_timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    sources = [bool(tab_text), bool(tab_file), bool(image_path), bool(image_url)]
    if sum(sources) != 1:
        raise GarageBandError("Provide exactly one source: tab_text, tab_file, image_path, or image_url.")

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in name).strip("-") or "garageband-tab-song"
    midi_path = out_dir / f"{safe_name}.mid"

    extracted: dict[str, Any] | None = None
    if tab_file:
        tab_text = Path(tab_file).expanduser().read_text(encoding="utf-8")
    elif image_path or image_url:
        extracted = extract_tab_from_image(image_path=image_path, image_url=image_url, download_dir=out_dir / "source-images")
        tab_text = extracted["tab_text"]

    if arrange:
        midi = create_arranged_midi_from_tab(
            tab_text or "",
            str(midi_path),
            bpm=bpm if bpm is not None else (extracted or {}).get("bpm"),
            open_in_garageband=False,
            title=safe_name,
            include_bass=include_bass,
            include_drums=include_drums,
            style=arrangement_style,
            repeat_count=repeat_count,
            capo=capo if capo is not None else (extracted or {}).get("capo"),
            tuning=tuning if tuning is not None else (extracted or {}).get("tuning"),
        )
    else:
        midi = create_midi_from_tab(
            tab_text or "",
            str(midi_path),
            bpm=bpm if bpm is not None else (extracted or {}).get("bpm"),
            open_in_garageband=False,
            track_name=safe_name,
            capo=capo if capo is not None else (extracted or {}).get("capo"),
            tuning=tuning if tuning is not None else (extracted or {}).get("tuning"),
        )

    prompt_actions = []
    if open_in_garageband:
        prompt_actions.append({"before_open": dismiss_save_prompt(discard=discard_unsaved)})
        midi["garageband"] = open_path(midi["path"])
        prompt_actions.append({"after_open": dismiss_save_prompt(discard=discard_unsaved)})

    ui_actions = []
    if open_in_garageband:
        if show_library:
            ui_actions.append({"library": _show_panel("Library", "Library")})
        if show_smart_controls:
            ui_actions.append({"smart_controls": _show_panel("Smart Controls", "Smart Controls")})
        if show_loop_browser:
            ui_actions.append({"loop_browser": _show_panel("Loop Browser", "Apple Loops")})
        if master_volume is not None:
            volume_element = _find_ui_element("missing value", role="AXSlider", max_depth=2)
            if volume_element:
                ui_actions.append({"master_volume": set_ui_value_path(volume_element["path"], str(master_volume))})

    shot = None
    if screenshot_output:
        shot = screenshot(screenshot_output)
    elif open_in_garageband:
        shot = screenshot(str(out_dir / f"{safe_name}-garageband.png"))

    audio_export = None
    if export_output:
        if not open_in_garageband:
            raise GarageBandError("export_output requires open_in_garageband to be true.")
        audio_export = export_song(
            export_output,
            format_name=export_format,
            quality=export_quality,
            include_cycle=export_include_cycle,
            overwrite=export_overwrite,
            timeout_seconds=export_timeout_seconds,
        )

    return {
        "source": {
            "kind": "tab_text" if tab_text and not tab_file and not image_path and not image_url else (
                "tab_file" if tab_file else ("image_path" if image_path else "image_url")
            ),
            "tab_file": str(Path(tab_file).expanduser().resolve()) if tab_file else None,
            "image_path": str(Path(image_path).expanduser().resolve()) if image_path else None,
            "image_url": image_url,
            "capo": midi.get("capo"),
            "tuning": midi.get("tuning"),
        },
        "extracted": extracted,
        "midi": midi,
        "arrange": arrange,
        "arrangement_style": arrangement_style,
        "repeat_count": repeat_count,
        "prompt_actions": prompt_actions,
        "ui_actions": ui_actions,
        "snapshot": ui_snapshot(max_depth=snapshot_depth) if open_in_garageband else None,
        "screenshot": shot,
        "audio_export": audio_export,
    }


KEY_ALIASES = {
    "space": "space",
    "return": "return",
    "enter": "return",
    "escape": "escape",
    "esc": "escape",
    "tab": "tab",
    "delete": "delete",
    "backspace": "delete",
    "left": "left arrow",
    "right": "right arrow",
    "up": "up arrow",
    "down": "down arrow",
}


def shortcut(key: str, modifiers: list[str] | None = None) -> dict[str, Any]:
    modifiers = modifiers or []
    normalized_mods = []
    for mod in modifiers:
        mod = mod.lower().strip()
        if mod in {"cmd", "command"}:
            normalized_mods.append("command down")
        elif mod in {"opt", "option", "alt"}:
            normalized_mods.append("option down")
        elif mod in {"ctrl", "control"}:
            normalized_mods.append("control down")
        elif mod == "shift":
            normalized_mods.append("shift down")
        else:
            raise GarageBandError(f"Unknown modifier: {mod}")

    key_name = KEY_ALIASES.get(key.lower().strip(), key)
    using = ""
    if normalized_mods:
        using = " using {" + ", ".join(normalized_mods) + "}"
    if len(key_name) == 1:
        key_expr = f"keystroke {_q(key_name)}"
    else:
        key_expr = f"key code (ASCII character 0)"
        special_codes = {
            "space": 49,
            "return": 36,
            "escape": 53,
            "tab": 48,
            "delete": 51,
            "left arrow": 123,
            "right arrow": 124,
            "down arrow": 125,
            "up arrow": 126,
        }
        if key_name not in special_codes:
            raise GarageBandError(f"Unknown special key: {key}")
        key_expr = f"key code {special_codes[key_name]}"

    script = textwrap.dedent(
        f"""
        tell application "GarageBand" to activate
        delay 0.1
        tell application "System Events"
          tell process "GarageBand"
            {key_expr}{using}
          end tell
        end tell
        """
    )
    _osa(script, timeout=10)
    return {"sent": {"key": key, "modifiers": modifiers}}


TRANSPORT_SHORTCUTS = {
    "play_stop": ("space", []),
    "record": ("r", []),
    "rewind": ("return", []),
    "undo": ("z", ["command"]),
    "redo": ("z", ["command", "shift"]),
    "cut": ("x", ["command"]),
    "copy": ("c", ["command"]),
    "paste": ("v", ["command"]),
    "save": ("s", ["command"]),
    "new": ("n", ["command"]),
    "open": ("o", ["command"]),
}
EXPORT_FORMAT_EXTENSIONS = {
    "AAC": ".m4a",
    "MP3": ".mp3",
    "AIFF": ".aif",
    "WAVE": ".wav",
}


def transport(action: str) -> dict[str, Any]:
    if action not in TRANSPORT_SHORTCUTS:
        raise GarageBandError(
            "Unknown transport/action. Use one of: "
            + ", ".join(sorted(TRANSPORT_SHORTCUTS))
        )
    key, mods = TRANSPORT_SHORTCUTS[action]
    result = shortcut(key, mods)
    result["action"] = action
    return result


def open_export_dialog() -> dict[str, Any]:
    return click_menu("Share > Export Song to Disk...")


def _normalize_export_format(format_name: str | None, output_path: Path) -> str:
    if format_name:
        normalized = format_name.strip().upper()
        if normalized in {"WAV"}:
            normalized = "WAVE"
        if normalized not in EXPORT_FORMAT_EXTENSIONS:
            raise GarageBandError("Export format must be one of: AAC, MP3, AIFF, WAVE.")
        return normalized
    suffix = output_path.suffix.lower()
    if suffix in {".m4a", ".aac"}:
        return "AAC"
    if suffix == ".mp3":
        return "MP3"
    if suffix in {".aif", ".aiff"}:
        return "AIFF"
    if suffix in {".wav", ".wave"}:
        return "WAVE"
    return "WAVE"


def _export_output_path(output_path: str, format_name: str | None) -> tuple[Path, str]:
    raw = Path(output_path).expanduser()
    export_format = _normalize_export_format(format_name, raw)
    expected_suffix = EXPORT_FORMAT_EXTENSIONS[export_format]
    if raw.suffix.lower() not in {expected_suffix, ".aiff" if export_format == "AIFF" else expected_suffix}:
        raw = raw.with_suffix(expected_suffix)
    return raw.resolve(), export_format


def export_song(
    output_path: str,
    *,
    format_name: str | None = None,
    quality: str | None = None,
    include_cycle: bool | str | int | None = None,
    overwrite: bool = False,
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    output, export_format = _export_output_path(output_path, format_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        raise GarageBandError(f"Export output already exists: {output}. Use overwrite to replace it.")
    if output.exists():
        output.unlink()

    timeout_seconds = max(5.0, min(600.0, float(timeout_seconds)))
    script = textwrap.dedent(
        """
        on run argv
          set folderPath to item 1 of argv
          set fileName to item 2 of argv
          set formatName to item 3 of argv
          set qualityName to item 4 of argv
          set cycleValue to item 5 of argv
          tell application "GarageBand" to activate
          delay 0.2
          tell application "System Events"
            tell process "GarageBand"
              click menu item "Export Song to Disk…" of menu 1 of menu bar item "Share" of menu bar 1
              set triesLeft to 50
              repeat while triesLeft > 0
                if (count of windows) > 0 then
                  try
                    if name of window 1 is "Export Song to Disk" then exit repeat
                  end try
                end if
                delay 0.1
                set triesLeft to triesLeft - 1
              end repeat
              if (count of windows) is 0 or name of window 1 is not "Export Song to Disk" then error "Export Song to Disk dialog did not open"
              set dialogWindow to window 1
              set dialogGroup to splitter group 1 of dialogWindow

              keystroke "g" using {command down, shift down}
              delay 0.2
              keystroke folderPath
              delay 0.1
              key code 36
              delay 0.5

              set value of text field "Save As:" of dialogGroup to fileName
              click radio button formatName of dialogGroup
              delay 0.1

              if qualityName is not "" then
                try
                  click pop up button 2 of dialogGroup
                  delay 0.1
                  keystroke qualityName
                  delay 0.1
                  key code 36
                  delay 0.1
                end try
              end if

              if cycleValue is not "" then
                set desiredValue to cycleValue
                set cycleBox to checkbox 1 of dialogGroup
                set currentValue to value of cycleBox as text
                if currentValue is not desiredValue then click cycleBox
              end if

              click button "Export" of dialogGroup
            end tell
          end tell
          return "ok"
        end run
        """
    )
    cycle_arg = ""
    if include_cycle is not None:
        cycle_arg = _bool_text(include_cycle)
    _osa(
        script,
        str(output.parent),
        output.stem,
        export_format,
        quality or "",
        cycle_arg,
        timeout=30,
    )

    deadline = time.time() + timeout_seconds
    last_size = -1
    stable_count = 0
    while time.time() < deadline:
        if output.exists():
            size = output.stat().st_size
            if size > 0 and size == last_size:
                stable_count += 1
                if stable_count >= 2:
                    info = audio_info(str(output))
                    return {
                        "path": str(output),
                        "format": export_format,
                        "bytes": size,
                        "quality": quality,
                        "include_cycle": include_cycle,
                        "overwrote": overwrite,
                        "audio_info": info,
                        "verified": bool(info.get("verification", {}).get("playable_header")),
                    }
            else:
                stable_count = 0
                last_size = size
        time.sleep(0.5)
    raise GarageBandError(f"Timed out waiting for GarageBand export: {output}")


def create_midi_from_tab(
    tab_text: str,
    output_path: str,
    *,
    bpm: int | None = None,
    open_in_garageband: bool = False,
    track_name: str = "GarageBand Bridge Tab",
    ticks_per_column: int = 120,
    sustain_columns: int = 2,
    capo: int | None = None,
    tuning: str | None = None,
) -> dict[str, Any]:
    if not tab_text.strip():
        raise GarageBandError("Tab text is empty.")
    result = tab_midi.tab_to_midi(
        tab_text,
        output_path,
        bpm=bpm,
        track_name=track_name,
        ticks_per_column=ticks_per_column,
        sustain_columns=sustain_columns,
        capo=capo,
        tuning=tuning,
    )
    if open_in_garageband:
        result["garageband"] = open_path(result["path"])
    return result


def create_arranged_midi_from_tab(
    tab_text: str,
    output_path: str,
    *,
    bpm: int | None = None,
    open_in_garageband: bool = False,
    title: str = "GarageBand Bridge Arrangement",
    ticks_per_column: int = 120,
    sustain_columns: int = 2,
    include_bass: bool = True,
    include_drums: bool = True,
    style: str = "rock",
    repeat_count: int = 1,
    capo: int | None = None,
    tuning: str | None = None,
) -> dict[str, Any]:
    if not tab_text.strip():
        raise GarageBandError("Tab text is empty.")
    result = tab_midi.tab_to_arranged_midi(
        tab_text,
        output_path,
        bpm=bpm,
        title=title,
        ticks_per_column=ticks_per_column,
        sustain_columns=sustain_columns,
        include_bass=include_bass,
        include_drums=include_drums,
        style=style,
        repeat_count=repeat_count,
        capo=capo,
        tuning=tuning,
    )
    if open_in_garageband:
        result["garageband"] = open_path(result["path"])
    return result


def extract_tab_from_image(
    *,
    image_path: str | None = None,
    image_url: str | None = None,
    download_dir: str | None = None,
) -> dict[str, Any]:
    if bool(image_path) == bool(image_url):
        raise GarageBandError("Provide exactly one of image_path or image_url.")
    if image_url:
        return image_tab.image_url_to_tab_text(image_url, download_dir)
    return image_tab.image_to_tab_text(image_path or "")


def create_midi_from_tab_image(
    output_path: str,
    *,
    image_path: str | None = None,
    image_url: str | None = None,
    download_dir: str | None = None,
    bpm: int | None = None,
    open_in_garageband: bool = False,
    track_name: str = "GarageBand Bridge Image Tab",
    ticks_per_column: int = 120,
    sustain_columns: int = 2,
    capo: int | None = None,
    tuning: str | None = None,
) -> dict[str, Any]:
    extracted = extract_tab_from_image(
        image_path=image_path,
        image_url=image_url,
        download_dir=download_dir,
    )
    midi = create_midi_from_tab(
        extracted["tab_text"],
        output_path,
        bpm=bpm if bpm is not None else extracted.get("bpm"),
        open_in_garageband=open_in_garageband,
        track_name=track_name,
        ticks_per_column=ticks_per_column,
        sustain_columns=sustain_columns,
        capo=capo if capo is not None else extracted.get("capo"),
        tuning=tuning if tuning is not None else extracted.get("tuning"),
    )
    return {"extracted": extracted, "midi": midi}


def create_arranged_midi_from_tab_image(
    output_path: str,
    *,
    image_path: str | None = None,
    image_url: str | None = None,
    download_dir: str | None = None,
    bpm: int | None = None,
    open_in_garageband: bool = False,
    title: str = "GarageBand Bridge Arrangement",
    ticks_per_column: int = 120,
    sustain_columns: int = 2,
    include_bass: bool = True,
    include_drums: bool = True,
    style: str = "rock",
    repeat_count: int = 1,
    capo: int | None = None,
    tuning: str | None = None,
) -> dict[str, Any]:
    extracted = extract_tab_from_image(
        image_path=image_path,
        image_url=image_url,
        download_dir=download_dir,
    )
    midi = create_arranged_midi_from_tab(
        extracted["tab_text"],
        output_path,
        bpm=bpm if bpm is not None else extracted.get("bpm"),
        open_in_garageband=open_in_garageband,
        title=title,
        ticks_per_column=ticks_per_column,
        sustain_columns=sustain_columns,
        include_bass=include_bass,
        include_drums=include_drums,
        style=style,
        repeat_count=repeat_count,
        capo=capo if capo is not None else extracted.get("capo"),
        tuning=tuning if tuning is not None else extracted.get("tuning"),
    )
    return {"extracted": extracted, "midi": midi}


def create_midi_from_score(
    score_path: str,
    output_path: str,
    *,
    bpm: int | None = None,
    velocity: int = score_midi.DEFAULT_VELOCITY,
    open_in_garageband: bool = False,
) -> dict[str, Any]:
    """Convert a MusicXML full/band score into a GarageBand-importable multi-track MIDI."""
    result = score_midi.musicxml_to_midi(
        score_path,
        output_path,
        bpm=bpm,
        velocity=velocity,
    )
    if open_in_garageband:
        result["garageband"] = open_path(result["path"])
    return result


def create_midi_from_score_spec(
    score_spec: dict[str, Any],
    output_path: str,
    *,
    velocity: int = score_midi.DEFAULT_VELOCITY,
    open_in_garageband: bool = False,
    source: str | None = None,
) -> dict[str, Any]:
    """Convert an LLM-friendly JSON score spec into a GarageBand-importable multi-track MIDI."""
    result = score_midi.score_spec_to_midi(
        score_spec,
        output_path,
        velocity=velocity,
        source=source,
    )
    if open_in_garageband:
        result["garageband"] = open_path(result["path"])
    return result


def score_spec_schema() -> dict[str, Any]:
    return score_midi.score_spec_schema()


def validate_score_spec(score_spec: dict[str, Any]) -> dict[str, Any]:
    return score_midi.validate_score_spec(score_spec)


def make_from_score(
    *,
    score_path: str,
    output_dir: str,
    name: str | None = None,
    bpm: int | None = None,
    velocity: int = score_midi.DEFAULT_VELOCITY,
    open_in_garageband: bool = True,
    show_library: bool = False,
    show_smart_controls: bool = False,
    show_loop_browser: bool = False,
    screenshot_output: str | None = None,
    snapshot_depth: int = 2,
    discard_unsaved: bool = False,
    export_output: str | None = None,
    export_format: str | None = None,
    export_quality: str | None = None,
    export_include_cycle: bool | str | int | None = None,
    export_overwrite: bool = False,
    export_timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = score_midi.safe_score_name(name or Path(score_path).stem)
    midi_path = out_dir / f"{safe_name}.mid"
    midi = create_midi_from_score(
        score_path,
        str(midi_path),
        bpm=bpm,
        velocity=velocity,
        open_in_garageband=False,
    )

    prompt_actions = []
    if open_in_garageband:
        prompt_actions.append({"before_open": dismiss_save_prompt(discard=discard_unsaved)})
        midi["garageband"] = open_path(midi["path"])
        prompt_actions.append({"after_open": dismiss_save_prompt(discard=discard_unsaved)})

    ui_actions = []
    if open_in_garageband:
        if show_library:
            ui_actions.append({"library": _show_panel("Library", "Library")})
        if show_smart_controls:
            ui_actions.append({"smart_controls": _show_panel("Smart Controls", "Smart Controls")})
        if show_loop_browser:
            ui_actions.append({"loop_browser": _show_panel("Loop Browser", "Apple Loops")})

    shot = None
    if screenshot_output:
        shot = screenshot(screenshot_output)
    elif open_in_garageband:
        shot = screenshot(str(out_dir / f"{safe_name}-garageband.png"))

    audio_export = None
    if export_output:
        if not open_in_garageband:
            raise GarageBandError("export_output requires open_in_garageband to be true.")
        audio_export = export_song(
            export_output,
            format_name=export_format,
            quality=export_quality,
            include_cycle=export_include_cycle,
            overwrite=export_overwrite,
            timeout_seconds=export_timeout_seconds,
        )

    return {
        "source": {
            "kind": "musicxml_score",
            "score_path": str(Path(score_path).expanduser().resolve()),
        },
        "midi": midi,
        "prompt_actions": prompt_actions,
        "ui_actions": ui_actions,
        "snapshot": ui_snapshot(max_depth=snapshot_depth) if open_in_garageband else None,
        "screenshot": shot,
        "audio_export": audio_export,
    }


def make_from_score_spec(
    *,
    score_spec: dict[str, Any],
    output_dir: str,
    name: str | None = None,
    velocity: int = score_midi.DEFAULT_VELOCITY,
    open_in_garageband: bool = True,
    show_library: bool = False,
    show_smart_controls: bool = False,
    show_loop_browser: bool = False,
    screenshot_output: str | None = None,
    snapshot_depth: int = 2,
    discard_unsaved: bool = False,
    export_output: str | None = None,
    export_format: str | None = None,
    export_quality: str | None = None,
    export_include_cycle: bool | str | int | None = None,
    export_overwrite: bool = False,
    export_timeout_seconds: float = 180.0,
    source: str | None = None,
) -> dict[str, Any]:
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = score_midi.safe_score_name(name or str(score_spec.get("title") or score_spec.get("name") or "garageband-score-spec"))
    midi_path = out_dir / f"{safe_name}.mid"
    midi = create_midi_from_score_spec(
        score_spec,
        str(midi_path),
        velocity=velocity,
        open_in_garageband=False,
        source=source,
    )

    prompt_actions = []
    if open_in_garageband:
        prompt_actions.append({"before_open": dismiss_save_prompt(discard=discard_unsaved)})
        midi["garageband"] = open_path(midi["path"])
        prompt_actions.append({"after_open": dismiss_save_prompt(discard=discard_unsaved)})

    ui_actions = []
    if open_in_garageband:
        if show_library:
            ui_actions.append({"library": _show_panel("Library", "Library")})
        if show_smart_controls:
            ui_actions.append({"smart_controls": _show_panel("Smart Controls", "Smart Controls")})
        if show_loop_browser:
            ui_actions.append({"loop_browser": _show_panel("Loop Browser", "Apple Loops")})

    shot = None
    if screenshot_output:
        shot = screenshot(screenshot_output)
    elif open_in_garageband:
        shot = screenshot(str(out_dir / f"{safe_name}-garageband.png"))

    audio_export = None
    if export_output:
        if not open_in_garageband:
            raise GarageBandError("export_output requires open_in_garageband to be true.")
        audio_export = export_song(
            export_output,
            format_name=export_format,
            quality=export_quality,
            include_cycle=export_include_cycle,
            overwrite=export_overwrite,
            timeout_seconds=export_timeout_seconds,
        )

    return {
        "source": {
            "kind": "score_spec_json",
            "source": source,
        },
        "midi": midi,
        "prompt_actions": prompt_actions,
        "ui_actions": ui_actions,
        "snapshot": ui_snapshot(max_depth=snapshot_depth) if open_in_garageband else None,
        "screenshot": shot,
        "audio_export": audio_export,
    }


def _load_score_spec_source(
    *,
    score_spec: dict[str, Any] | None = None,
    score_json: str | None = None,
    score_json_file: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    sources = [score_spec is not None, bool(score_json), bool(score_json_file)]
    if sum(sources) == 0:
        return None, None
    if sum(sources) > 1:
        raise GarageBandError("Provide only one JSON score source: score_spec, score_json, or score_json_file.")
    if score_spec is not None:
        if not isinstance(score_spec, dict):
            raise GarageBandError("score_spec must be a JSON object.")
        return score_spec, None
    if score_json:
        loaded = json.loads(score_json)
        if not isinstance(loaded, dict):
            raise GarageBandError("score_json must decode to a JSON object.")
        return loaded, "inline_json"
    assert score_json_file is not None
    source_path = str(Path(score_json_file).expanduser().resolve())
    loaded = json.loads(Path(score_json_file).expanduser().read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise GarageBandError("score_json_file must contain a JSON object.")
    return loaded, source_path


def make_music(
    *,
    output_dir: str,
    name: str | None = None,
    score_path: str | None = None,
    score_spec: dict[str, Any] | None = None,
    score_json: str | None = None,
    score_json_file: str | None = None,
    tab_text: str | None = None,
    tab_file: str | None = None,
    image_path: str | None = None,
    image_url: str | None = None,
    bpm: int | None = None,
    velocity: int = score_midi.DEFAULT_VELOCITY,
    open_in_garageband: bool = True,
    show_library: bool = False,
    show_smart_controls: bool = False,
    show_loop_browser: bool = False,
    master_volume: str | None = None,
    screenshot_output: str | None = None,
    snapshot_depth: int = 2,
    discard_unsaved: bool = False,
    arrange: bool = True,
    include_bass: bool = True,
    include_drums: bool = True,
    arrangement_style: str = "rock",
    repeat_count: int = 1,
    capo: int | None = None,
    tuning: str | None = None,
    export_output: str | None = None,
    export_format: str | None = None,
    export_quality: str | None = None,
    export_include_cycle: bool | str | int | None = None,
    export_overwrite: bool = False,
    export_timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """One high-level route from score/tab/image source to GarageBand music output."""
    spec, spec_source = _load_score_spec_source(
        score_spec=score_spec,
        score_json=score_json,
        score_json_file=score_json_file,
    )
    source_kinds = [
        ("score_spec_json", spec is not None),
        ("musicxml_score", bool(score_path)),
        ("tab_text", bool(tab_text)),
        ("tab_file", bool(tab_file)),
        ("image_path", bool(image_path)),
        ("image_url", bool(image_url)),
    ]
    selected = [kind for kind, present in source_kinds if present]
    if len(selected) != 1:
        raise GarageBandError(
            "make_music requires exactly one source: score_spec/score_json/score_json_file, score_path, tab_text, tab_file, image_path, or image_url."
        )
    route = selected[0]

    common = {
        "output_dir": output_dir,
        "name": name,
        "open_in_garageband": open_in_garageband,
        "show_library": show_library,
        "show_smart_controls": show_smart_controls,
        "show_loop_browser": show_loop_browser,
        "screenshot_output": screenshot_output,
        "snapshot_depth": snapshot_depth,
        "discard_unsaved": discard_unsaved,
        "export_output": export_output,
        "export_format": export_format,
        "export_quality": export_quality,
        "export_include_cycle": export_include_cycle,
        "export_overwrite": export_overwrite,
        "export_timeout_seconds": export_timeout_seconds,
    }

    if route == "score_spec_json":
        result = make_from_score_spec(
            score_spec=spec or {},
            velocity=velocity,
            source=spec_source,
            **common,
        )
    elif route == "musicxml_score":
        result = make_from_score(
            score_path=score_path or "",
            bpm=bpm,
            velocity=velocity,
            **common,
        )
    else:
        result = make_from_tab(
            output_dir=output_dir,
            name=name or "garageband-tab-song",
            tab_text=tab_text,
            tab_file=tab_file,
            image_path=image_path,
            image_url=image_url,
            bpm=int(bpm) if bpm is not None else None,
            open_in_garageband=open_in_garageband,
            show_library=show_library,
            show_smart_controls=show_smart_controls,
            show_loop_browser=show_loop_browser,
            master_volume=master_volume,
            screenshot_output=screenshot_output,
            snapshot_depth=snapshot_depth,
            discard_unsaved=discard_unsaved,
            arrange=arrange,
            include_bass=include_bass,
            include_drums=include_drums,
            arrangement_style=arrangement_style,
            repeat_count=repeat_count,
            capo=capo,
            tuning=tuning,
            export_output=export_output,
            export_format=export_format,
            export_quality=export_quality,
            export_include_cycle=export_include_cycle,
            export_overwrite=export_overwrite,
            export_timeout_seconds=export_timeout_seconds,
        )

    result["route"] = route
    result["make_music"] = {
        "source_kind": route,
        "output_dir": str(Path(output_dir).expanduser().resolve()),
    }
    return result


def recipes() -> dict[str, Any]:
    return {"recipes": LLM_RECIPES}


def capabilities(include_live: bool = True) -> dict[str, Any]:
    """Return the bridge's feature map in a shape LLM clients can reason over."""
    data: dict[str, Any] = {
        "summary": "GarageBand has a very small native script API, so this bridge combines app launch/open, macOS UI automation, screenshots, MIDI generation, and optional Vision OCR.",
        "garageband_native_api": {
            "documented_command": "renderPreview",
            "broad_project_editing_api": False,
        },
        "surfaces": [
            {
                "name": "app_control",
                "commands": ["status", "launch", "activate", "quit", "open", "render-preview"],
                "mcp_tools": [
                    "garageband_status",
                    "garageband_launch",
                    "garageband_open",
                    "garageband_render_preview",
                ],
                "coverage": "Launch GarageBand, open files/projects, and call the one useful native AppleScript command.",
            },
            {
                "name": "menus_shortcuts_transport",
                "commands": ["menus", "menu-map", "menu-search", "menu-search-click", "menu", "shortcut", "transport", "export-dialog", "export-song", "audio-info"],
                "mcp_tools": [
                    "garageband_list_menus",
                    "garageband_menu_map",
                    "garageband_find_menu_items",
                    "garageband_click_menu_search",
                    "garageband_click_menu",
                    "garageband_shortcut",
                    "garageband_transport",
                    "garageband_export_dialog",
                    "garageband_export_song",
                    "garageband_audio_info",
                ],
                "coverage": "Most menu-visible GarageBand actions plus common keyboard actions, recursive menu discovery/search, current-song audio export through GarageBand's export dialog, and exported-audio metadata verification.",
            },
            {
                "name": "visible_ui_control",
                "commands": [
                    "ui-snapshot",
                    "ui-search",
                    "ui-controls",
                    "wait-ui",
                    "ui-search-click",
                    "ui-search-info",
                    "ui-search-details",
                    "ui-search-set",
                    "ui-search-action",
                    "ui-click",
                    "ui-info-path",
                    "ui-details-path",
                    "ui-click-path",
                    "ui-action-path",
                    "ui-set-value",
                    "screenshot",
                    "annotated-screenshot",
                    "window-rect",
                    "window-click",
                    "window-drag",
                    "type-text",
                ],
                "mcp_tools": [
                    "garageband_ui_snapshot",
                    "garageband_find_ui_elements",
                    "garageband_ui_controls_summary",
                    "garageband_wait_ui",
                    "garageband_click_ui_search",
                    "garageband_ui_search_info",
                    "garageband_ui_search_details",
                    "garageband_ui_search_set",
                    "garageband_ui_search_action",
                    "garageband_click_ui",
                    "garageband_ui_info_path",
                    "garageband_ui_details_path",
                    "garageband_click_ui_path",
                    "garageband_ui_action_path",
                    "garageband_set_ui_value",
                    "garageband_screenshot",
                    "garageband_annotated_screenshot",
                    "garageband_window_rect",
                    "garageband_window_click",
                    "garageband_window_drag",
                    "garageband_type_text",
                ],
                "coverage": "Inspect, search, summarize, wait for, click, drag, type, screenshot, generate annotated click maps, and set supported values for currently visible controls.",
            },
            {
                "name": "tracks_regions",
                "commands": ["list-tracks", "select-track", "set-track", "list-regions"],
                "mcp_tools": [
                    "garageband_list_tracks",
                    "garageband_select_track",
                    "garageband_set_track",
                    "garageband_list_regions",
                ],
                "coverage": "List and select visible tracks, inspect visible regions, then adjust track mute, solo, volume, pan, or visible track name through GarageBand's track header controls.",
            },
            {
                "name": "smart_controls",
                "commands": ["smart-controls", "set-smart-control"],
                "mcp_tools": [
                    "garageband_smart_controls",
                    "garageband_set_smart_control",
                ],
                "coverage": "Show GarageBand's Smart Controls panel, list visible Track/Master/Controls/EQ controls, and press or set a visible Smart Control by label or path.",
            },
            {
                "name": "library_sounds",
                "commands": ["library-search", "library-select"],
                "mcp_tools": [
                    "garageband_library_search",
                    "garageband_library_select",
                ],
                "coverage": "Show GarageBand's Library, search the visible sound library, list returned results, and press a selected visible result for the selected track.",
            },
            {
                "name": "apple_loops",
                "commands": ["loop-search", "loop-select", "loop-drag"],
                "mcp_tools": [
                    "garageband_loop_search",
                    "garageband_loop_select",
                    "garageband_loop_drag",
                ],
                "coverage": "Show GarageBand's Apple Loops browser, filter loops by search text, report result counts and visible rows, select a visible loop row by index, and guarded-drag a row into the timeline when the content-install risk has been acknowledged.",
            },
            {
                "name": "project_musical_settings",
                "commands": ["project-settings", "project-setting-options", "set-project-settings"],
                "mcp_tools": [
                    "garageband_project_settings",
                    "garageband_project_setting_options",
                    "garageband_set_project_settings",
                ],
                "coverage": "Read and set the current project's tempo, key signature, and time signature through GarageBand's visible LCD controls, with built-in option catalogs for key and time signature.",
            },
            {
                "name": "tab_image_to_music",
                "commands": ["midi-info", "tab-to-midi", "arrange-tab-to-midi", "image-to-tab", "image-to-midi", "arrange-image-to-midi", "make-from-tab", "make-music"],
                "mcp_tools": [
                    "garageband_midi_info",
                    "garageband_tab_to_midi",
                    "garageband_arrange_tab_to_midi",
                    "garageband_image_to_tab",
                    "garageband_image_to_midi",
                    "garageband_arrange_image_to_midi",
                    "garageband_make_from_tab",
                    "garageband_make_music",
                ],
                "coverage": "Convert ASCII guitar tab or a local/online tab image into a GarageBand-importable MIDI seed or a styled/repeated guitar/bass/drums arrangement, with detected or explicit tempo, capo, alternate-tuning transposition, and muted-strum rhythm preservation.",
                "arrangement_styles": sorted(tab_midi.ARRANGEMENT_STYLES),
            },
            {
                "name": "score_to_music",
                "commands": ["score-spec-schema", "score-spec-validate", "score-to-midi", "score-spec-to-midi", "make-from-score", "make-from-score-spec", "make-music"],
                "mcp_tools": [
                    "garageband_score_spec_schema",
                    "garageband_validate_score_spec",
                    "garageband_score_to_midi",
                    "garageband_score_spec_to_midi",
                    "garageband_make_from_score",
                    "garageband_make_from_score_spec",
                    "garageband_make_music",
                ],
                "coverage": "Convert a MusicXML band/full score, LLM-friendly JSON score spec, tab, or tab image into a multi-track GarageBand-importable MIDI file with score transposition, octave-shift directions, grace notes, harmony/chord symbol accompaniment, sustain pedal directions, drum score-instrument and midi-unpitched mapping, specific instrument program mapping, tied-note sustain, and single-/multi-measure repeat symbols applied, then optionally open it in GarageBand, capture proof, and export audio.",
                "supported_inputs": ["MusicXML score-partwise .musicxml/.xml", "MusicXML score-timewise .musicxml/.xml", "compressed MusicXML .mxl", "JSON score spec"],
            },
            {
                "name": "agent_plan_runner",
                "commands": ["run-plan"],
                "mcp_tools": ["garageband_run_plan"],
                "coverage": "Execute a JSON sequence of bridge actions with per-step results, UI snapshot reuse, and automatic cache clearing after visible UI changes.",
            },
        ],
        "safe_operating_loop": [
            "garageband_capabilities",
            "garageband_self_test with include_ui true",
            "garageband_ui_snapshot before UI actions",
            "perform one menu/path/coordinate action",
            "garageband_screenshot or garageband_ui_snapshot after the action",
            "garageband_audio_info after exporting audio",
        ],
        "agent_decision_guide": AGENT_DECISION_GUIDE,
        "limits": [
            "GarageBand does not expose a full project/track/plugin editing API.",
            "Deep instrument/plugin editing should be captured as tested UI recipes for the current GarageBand version.",
            "OCR quality depends on the tab image; inspect extracted tab before opening the result when the source image is messy.",
        ],
        "recipes": LLM_RECIPES,
    }
    if include_live:
        try:
            data["live_status"] = status()
        except Exception as exc:
            data["live_status_error"] = str(exc)
    return data


def _check(name: str, func: Any) -> dict[str, Any]:
    started = time.time()
    try:
        data = func()
        return {
            "name": name,
            "ok": True,
            "elapsed_seconds": round(time.time() - started, 3),
            "data": data,
        }
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "elapsed_seconds": round(time.time() - started, 3),
            "error": str(exc),
            "type": exc.__class__.__name__,
        }


def _midi_file_summary(path: str | Path) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    data = p.read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise GarageBandError(f"Not a MIDI file: {p}")
    track_names: list[str] = []
    note_on_by_channel: dict[str, int] = {}
    velocities_by_channel: dict[str, list[int]] = {}
    lengths_by_channel: dict[str, list[int]] = {}
    markers: list[dict[str, Any]] = []
    tempo_changes: list[dict[str, Any]] = []
    time_signatures: list[dict[str, Any]] = []
    key_signatures: list[dict[str, Any]] = []
    control_changes: dict[str, dict[str, list[dict[str, Any]]]] = {}
    offset = 14
    track_chunks = 0
    while offset + 8 <= len(data):
        chunk_name = data[offset:offset + 4]
        chunk_len = int.from_bytes(data[offset + 4:offset + 8], "big")
        chunk_data = data[offset + 8:offset + 8 + chunk_len]
        offset += 8 + chunk_len
        if chunk_name != b"MTrk":
            continue
        track_chunks += 1
        parsed = _parse_midi_track_summary(chunk_data)
        if parsed["track_name"]:
            track_names.append(parsed["track_name"])
        for channel, count in parsed["note_on_by_channel"].items():
            note_on_by_channel[channel] = note_on_by_channel.get(channel, 0) + count
        for channel, velocities in parsed["velocities_by_channel"].items():
            velocities_by_channel.setdefault(channel, []).extend(velocities)
        for channel, lengths in parsed["lengths_by_channel"].items():
            lengths_by_channel.setdefault(channel, []).extend(lengths)
        markers.extend(parsed["markers"])
        tempo_changes.extend(parsed["tempo_changes"])
        time_signatures.extend(parsed["time_signatures"])
        key_signatures.extend(parsed["key_signatures"])
        for channel, controls in parsed["control_changes"].items():
            channel_controls = control_changes.setdefault(channel, {})
            for control_name, changes in controls.items():
                channel_controls.setdefault(control_name, []).extend(changes)
    velocity_summary = {
        channel: {
            "min": min(values),
            "max": max(values),
            "avg": round(sum(values) / len(values), 2),
        }
        for channel, values in sorted(velocities_by_channel.items(), key=lambda item: int(item[0]))
        if values
    }
    length_summary = {
        channel: {
            "min_ticks": min(values),
            "max_ticks": max(values),
            "avg_ticks": round(sum(values) / len(values), 2),
            "min_beats": round(min(values) / tab_midi.TICKS_PER_BEAT, 4),
            "max_beats": round(max(values) / tab_midi.TICKS_PER_BEAT, 4),
            "avg_beats": round((sum(values) / len(values)) / tab_midi.TICKS_PER_BEAT, 4),
        }
        for channel, values in sorted(lengths_by_channel.items(), key=lambda item: int(item[0]))
        if values
    }
    return {
        "path": str(p),
        "bytes": len(data),
        "header": data[:4].decode("ascii"),
        "format": int.from_bytes(data[8:10], "big"),
        "tracks": int.from_bytes(data[10:12], "big"),
        "track_chunks": track_chunks,
        "division": int.from_bytes(data[12:14], "big"),
        "track_names": track_names,
        "note_on_by_channel": note_on_by_channel,
        "note_on_count": sum(note_on_by_channel.values()),
        "velocity_by_channel": velocity_summary,
        "note_length_by_channel": length_summary,
        "markers": markers,
        "tempo_changes": tempo_changes,
        "time_signature": time_signatures[0] if time_signatures else None,
        "time_signatures": time_signatures,
        "key_signature": key_signatures[0] if key_signatures else None,
        "key_signatures": key_signatures,
        "control_changes": control_changes,
    }


def _read_midi_var_len(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if offset >= len(data):
            return value, offset
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if not (byte & 0x80):
            break
    return value, offset


def _parse_midi_track_summary(data: bytes) -> dict[str, Any]:
    offset = 0
    running_status: int | None = None
    track_name = ""
    note_on_by_channel: dict[str, int] = {}
    velocities_by_channel: dict[str, list[int]] = {}
    lengths_by_channel: dict[str, list[int]] = {}
    markers: list[dict[str, Any]] = []
    tempo_changes: list[dict[str, Any]] = []
    time_signatures: list[dict[str, Any]] = []
    key_signatures: list[dict[str, Any]] = []
    control_changes: dict[str, dict[str, list[dict[str, Any]]]] = {}
    active_notes: dict[tuple[int, int], list[int]] = {}
    absolute_tick = 0
    while offset < len(data):
        delta, offset = _read_midi_var_len(data, offset)
        absolute_tick += delta
        if offset >= len(data):
            break
        status = data[offset]
        if status & 0x80:
            offset += 1
            running_status = status
        elif running_status is not None:
            status = running_status
        else:
            break

        if status == 0xFF:
            if offset >= len(data):
                break
            meta_type = data[offset]
            offset += 1
            length, offset = _read_midi_var_len(data, offset)
            payload = data[offset:offset + length]
            offset += length
            if meta_type == 0x03 and not track_name:
                track_name = payload.decode("utf-8", errors="replace")
            if meta_type == 0x06:
                markers.append(
                    {
                        "name": payload.decode("utf-8", errors="replace"),
                        "tick": absolute_tick,
                        "beat": round(absolute_tick / tab_midi.TICKS_PER_BEAT, 4),
                    }
                )
            if meta_type == 0x51 and len(payload) == 3:
                micros_per_quarter = int.from_bytes(payload, "big")
                if micros_per_quarter > 0:
                    tempo_changes.append(
                        {
                            "bpm": round(60_000_000 / micros_per_quarter, 2),
                            "tick": absolute_tick,
                            "beat": round(absolute_tick / tab_midi.TICKS_PER_BEAT, 4),
                        }
                    )
            if meta_type == 0x58 and len(payload) >= 2:
                time_signatures.append(_midi_time_signature_summary(payload[0], payload[1], absolute_tick))
            if meta_type == 0x59 and len(payload) >= 2:
                fifths = payload[0] - 256 if payload[0] > 127 else payload[0]
                key_signatures.append(_midi_key_signature_summary(fifths, payload[1], absolute_tick))
            if meta_type == 0x2F:
                break
            continue
        if status in {0xF0, 0xF7}:
            length, offset = _read_midi_var_len(data, offset)
            offset += length
            continue

        event_type = status & 0xF0
        channel = status & 0x0F
        data_len = 1 if event_type in {0xC0, 0xD0} else 2
        payload = data[offset:offset + data_len]
        offset += data_len
        if event_type == 0x90 and len(payload) == 2 and payload[1] > 0:
            key = str(channel + 1)
            note_on_by_channel[key] = note_on_by_channel.get(key, 0) + 1
            velocities_by_channel.setdefault(key, []).append(payload[1])
            active_notes.setdefault((channel, payload[0]), []).append(absolute_tick)
        if len(payload) == 2 and (event_type == 0x80 or (event_type == 0x90 and payload[1] == 0)):
            starts = active_notes.get((channel, payload[0]))
            if starts:
                start_tick = starts.pop(0)
                key = str(channel + 1)
                lengths_by_channel.setdefault(key, []).append(max(0, absolute_tick - start_tick))
        if event_type == 0xB0 and len(payload) == 2:
            control_name = MIDI_CONTROL_NAMES.get(payload[0], f"cc_{payload[0]}")
            key = str(channel + 1)
            control_changes.setdefault(key, {}).setdefault(control_name, []).append(
                {
                    "tick": absolute_tick,
                    "beat": round(absolute_tick / tab_midi.TICKS_PER_BEAT, 4),
                    "value": payload[1],
                }
            )
    return {
        "track_name": track_name,
        "note_on_by_channel": note_on_by_channel,
        "velocities_by_channel": velocities_by_channel,
        "lengths_by_channel": lengths_by_channel,
        "markers": markers,
        "tempo_changes": tempo_changes,
        "time_signatures": time_signatures,
        "key_signatures": key_signatures,
        "control_changes": control_changes,
    }


def midi_info(path: str) -> dict[str, Any]:
    return _midi_file_summary(path)


def audio_info(path: str) -> dict[str, Any]:
    """Inspect an exported audio file enough for LLM-side verification."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise GarageBandError(f"Audio file does not exist: {p}")
    data = p.read_bytes()
    if not data:
        raise GarageBandError(f"Audio file is empty: {p}")

    suffix = p.suffix.lower()
    summary: dict[str, Any] = {
        "path": str(p),
        "bytes": len(data),
        "nonempty": True,
        "suffix": suffix,
        "format": "unknown",
        "duration_seconds": None,
        "channels": None,
        "sample_rate": None,
        "sample_width_bits": None,
        "frame_count": None,
    }

    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        with wave.open(str(p), "rb") as wav:
            frames = wav.getnframes()
            sample_rate = wav.getframerate()
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            duration = frames / sample_rate if sample_rate else 0.0
        summary.update(
            {
                "format": "WAVE",
                "duration_seconds": round(duration, 6),
                "channels": channels,
                "sample_rate": sample_rate,
                "sample_width_bits": sample_width * 8,
                "frame_count": frames,
                "verification": {
                    "playable_header": True,
                    "has_audio_frames": frames > 0,
                    "has_duration": duration > 0,
                },
            }
        )
        return summary

    if data.startswith(b"FORM") and data[8:12] in {b"AIFF", b"AIFC"}:
        summary["format"] = data[8:12].decode("ascii")
        offset = 12
        while offset + 8 <= len(data):
            chunk_id = data[offset:offset + 4]
            chunk_size = int.from_bytes(data[offset + 4:offset + 8], "big")
            chunk = data[offset + 8:offset + 8 + chunk_size]
            if chunk_id == b"COMM" and len(chunk) >= 18:
                channels = int.from_bytes(chunk[0:2], "big")
                frames = int.from_bytes(chunk[2:6], "big")
                sample_width = int.from_bytes(chunk[6:8], "big")
                sample_rate = _extended_float80_to_float(chunk[8:18])
                duration = frames / sample_rate if sample_rate else None
                summary.update(
                    {
                        "channels": channels,
                        "sample_rate": round(sample_rate, 3) if sample_rate else None,
                        "sample_width_bits": sample_width,
                        "frame_count": frames,
                        "duration_seconds": round(duration, 6) if duration else None,
                    }
                )
                break
            offset += 8 + chunk_size + (chunk_size % 2)
        summary["verification"] = {
            "playable_header": True,
            "has_audio_frames": bool(summary.get("frame_count")),
            "has_duration": bool(summary.get("duration_seconds")),
        }
        return summary

    if data.startswith(b"ID3") or (len(data) > 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        summary.update({"format": "MP3", "verification": {"playable_header": True, "has_audio_frames": None, "has_duration": None}})
        return summary

    if b"ftyp" in data[:16]:
        brand = data[8:12].decode("ascii", errors="replace") if len(data) >= 12 else ""
        summary.update({"format": "M4A/AAC", "brand": brand, "verification": {"playable_header": True, "has_audio_frames": None, "has_duration": None}})
        return summary

    summary["verification"] = {"playable_header": False, "has_audio_frames": None, "has_duration": None}
    return summary


def _extended_float80_to_float(raw: bytes) -> float | None:
    if len(raw) != 10:
        return None
    expon = int.from_bytes(raw[0:2], "big")
    mantissa = int.from_bytes(raw[2:10], "big")
    if expon == 0 and mantissa == 0:
        return 0.0
    sign = -1 if (expon & 0x8000) else 1
    exponent = (expon & 0x7FFF) - 16383
    return sign * mantissa * (2.0 ** (exponent - 63))


def _swift_version() -> dict[str, Any]:
    proc = _run(["swift", "--version"], timeout=10)
    if proc.returncode != 0:
        raise GarageBandError((proc.stderr or proc.stdout or "swift --version failed").strip())
    lines = (proc.stdout or proc.stderr).splitlines()
    return {"swift": lines[0] if lines else "available"}


def self_test(
    *,
    output_dir: str | None = None,
    include_ui: bool = True,
    include_screenshot: bool = True,
    image_path: str | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    """Run a non-destructive health check for LLM clients."""
    if output_dir:
        out_dir = Path(output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(tempfile.mkdtemp(prefix="garageband-bridge-self-test-"))

    checks: list[dict[str, Any]] = []
    checks.append(_check("garageband_status", status))
    checks.append(_check("permissions_note", permissions_note))
    checks.append(_check("swift_available_for_vision_ocr", _swift_version))

    midi_path = out_dir / "self-test-tab.mid"

    def make_midi() -> dict[str, Any]:
        created = create_midi_from_tab(SAMPLE_TAB, str(midi_path), bpm=112, open_in_garageband=False)
        created["file"] = _midi_file_summary(midi_path)
        return created

    checks.append(_check("tab_to_midi", make_midi))

    if include_ui:
        checks.append(_check("ui_snapshot", lambda: {"count": ui_snapshot(max_depth=2)["count"]}))
        checks.append(_check("window_rect", window_rect))
    if include_screenshot:
        checks.append(_check("screenshot", lambda: screenshot(str(out_dir / "garageband-self-test.png"))))
    if image_path or image_url:
        checks.append(
            _check(
                "image_to_tab",
                lambda: extract_tab_from_image(image_path=image_path, image_url=image_url, download_dir=str(out_dir / "source-images")),
            )
        )

    return {
        "ok": all(check["ok"] for check in checks),
        "output_dir": str(out_dir),
        "checks": checks,
    }


def _step_args(step: dict[str, Any]) -> dict[str, Any]:
    args = dict(step.get("args") or {})
    for key, value in step.items():
        if key not in {"action", "tool", "name", "args", "note", "description"}:
            args.setdefault(key, value)
    return args


def _one_of(args: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in args:
            return args[name]
    return default


def _cached_ui_snapshot(context: dict[str, Any] | None, max_depth: int) -> dict[str, Any]:
    if context is None or not context.get("cache_ui", True):
        return ui_snapshot(max_depth=max_depth)
    cache = context.setdefault("ui_snapshots", {})
    key = str(max_depth)
    if key not in cache:
        cache[key] = ui_snapshot(max_depth=max_depth)
    return cache[key]


def _action_changes_ui(action: str) -> bool:
    normalized = action.strip().lower().replace("-", "_")
    return normalized in {
        "launch",
        "activate",
        "quit",
        "dismiss_save_prompt",
        "open",
        "render_preview",
        "menu",
        "click_menu",
        "menu_search_click",
        "click_menu_search",
        "ui_click",
        "click_ui",
        "ui_search_click",
        "click_ui_search",
        "ui_search_set",
        "ui_set_search",
        "set_ui_value_search",
        "ui_action_search",
        "ui_search_action",
        "perform_ui_action_search",
        "ui_action_path",
        "perform_ui_action_path",
        "set_project_settings",
        "project_settings_set",
        "select_track",
        "track_select",
        "set_track",
        "track_set",
        "smart_controls",
        "list_smart_controls",
        "set_smart_control",
        "smart_control_set",
        "library_search",
        "search_library",
        "library_select",
        "select_library",
        "loop_search",
        "search_loops",
        "loop_select",
        "select_loop",
        "loop_drag",
        "drag_loop",
        "ui_click_path",
        "click_ui_path",
        "ui_set_value",
        "set_ui_value",
        "annotated_screenshot",
        "annotated-screenshot",
        "click_map",
        "window_click",
        "window_drag",
        "type_text",
        "shortcut",
        "transport",
        "export_dialog",
        "export_song",
        "export",
        "audio_info",
        "tab_to_midi",
        "arrange_tab_to_midi",
        "tab_to_arranged_midi",
        "image_to_midi",
        "arrange_image_to_midi",
        "image_to_arranged_midi",
        "score_to_midi",
        "musicxml_to_midi",
        "score_spec_to_midi",
        "score_json_to_midi",
        "score_spec_validate",
        "validate_score_spec",
        "make_music",
        "make_from_tab",
        "make_from_score",
        "make_from_score_spec",
    }


def _invalidate_plan_ui_cache(context: dict[str, Any] | None) -> None:
    if context is not None:
        context.pop("ui_snapshots", None)


def _call_bridge_action(action: str, args: dict[str, Any], context: dict[str, Any] | None = None) -> Any:
    normalized = action.strip().lower().replace("-", "_")
    if normalized in {"status"}:
        return status()
    if normalized in {"capabilities"}:
        return capabilities(include_live=bool(args.get("include_live", True)))
    if normalized in {"recipes"}:
        return recipes()
    if normalized in {"self_test", "selftest"}:
        return self_test(
            output_dir=args.get("output_dir"),
            include_ui=bool(args.get("include_ui", True)),
            include_screenshot=bool(args.get("include_screenshot", True)),
            image_path=args.get("image_path") or args.get("image"),
            image_url=args.get("image_url") or args.get("url"),
        )
    if normalized == "launch":
        return launch()
    if normalized == "activate":
        return activate()
    if normalized == "quit":
        return quit_app()
    if normalized == "permissions":
        return permissions_note()
    if normalized == "dismiss_save_prompt":
        return dismiss_save_prompt(discard=bool(args.get("discard", False)))
    if normalized == "open":
        return open_path(args["path"])
    if normalized == "render_preview":
        return render_preview(args.get("path"))
    if normalized in {"menus", "list_menus"}:
        return list_menus(include_disabled=not bool(args.get("enabled_only", False)))
    if normalized == "menu_map":
        return menu_map(
            include_disabled=not bool(args.get("enabled_only", False)),
            max_depth=int(args.get("max_depth", 5)),
            top_menu=args.get("top_menu"),
        )
    if normalized in {"menu_search", "find_menu_items"}:
        return find_menu_items(
            args["query"],
            enabled_only=bool(args.get("enabled_only", False)),
            max_depth=int(args.get("max_depth", 5)),
            limit=int(args.get("limit", 50)),
            top_menu=args.get("top_menu"),
        )
    if normalized in {"menu_search_click", "click_menu_search"}:
        return click_menu_search(
            args["query"],
            enabled_only=bool(args.get("enabled_only", True)),
            max_depth=int(args.get("max_depth", 5)),
            top_menu=args.get("top_menu"),
            allow_first=bool(args.get("allow_first", False)),
        )
    if normalized in {"menu", "click_menu"}:
        return click_menu(args["path"])
    if normalized == "ui_snapshot":
        max_depth = int(args.get("max_depth", 4))
        snap = ui_snapshot(max_depth)
        if context is not None and context.get("cache_ui", True):
            context.setdefault("ui_snapshots", {})[str(max_depth)] = snap
        return snap
    if normalized in {"ui_search", "find_ui_elements"}:
        max_depth = int(args.get("max_depth", 4))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        return find_ui_elements(
            args["query"],
            role=args.get("role"),
            enabled_only=bool(args.get("enabled_only", False)),
            max_depth=max_depth,
            limit=int(args.get("limit", 50)),
            snapshot=snap,
        )
    if normalized in {"ui_controls", "ui_controls_summary"}:
        max_depth = int(args.get("max_depth", 3))
        if args.get("use_cache", True):
            return _ui_controls_summary_from_snapshot(_cached_ui_snapshot(context, max_depth), max_depth=max_depth)
        return ui_controls_summary(max_depth=max_depth)
    if normalized in {"wait_ui", "ui_wait"}:
        return wait_ui(
            args["query"],
            role=args.get("role"),
            enabled_only=bool(args.get("enabled_only", False)),
            max_depth=int(args.get("max_depth", 4)),
            timeout_seconds=float(args.get("timeout_seconds", args.get("timeout", 10.0))),
            interval_seconds=float(args.get("interval_seconds", args.get("interval", 0.5))),
            limit=int(args.get("limit", 10)),
        )
    if normalized in {"ui_search_click", "click_ui_search"}:
        max_depth = int(args.get("max_depth", 4))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        return click_ui_search(
            args["query"],
            role=args.get("role"),
            enabled_only=bool(args.get("enabled_only", True)),
            max_depth=max_depth,
            allow_first=bool(args.get("allow_first", False)),
            snapshot=snap,
        )
    if normalized in {"ui_search_info", "ui_info_search"}:
        max_depth = int(args.get("max_depth", 4))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        return ui_info_search(
            args["query"],
            role=args.get("role"),
            enabled_only=bool(args.get("enabled_only", True)),
            max_depth=max_depth,
            allow_first=bool(args.get("allow_first", False)),
            snapshot=snap,
        )
    if normalized in {"ui_search_details", "ui_details_search"}:
        max_depth = int(args.get("max_depth", 4))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        return ui_details_search(
            args["query"],
            role=args.get("role"),
            enabled_only=bool(args.get("enabled_only", True)),
            max_depth=max_depth,
            allow_first=bool(args.get("allow_first", False)),
            snapshot=snap,
        )
    if normalized in {"ui_search_set", "ui_set_search", "set_ui_value_search"}:
        max_depth = int(args.get("max_depth", 4))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        return set_ui_value_search(
            args["query"],
            str(args["value"]),
            role=args.get("role"),
            enabled_only=bool(args.get("enabled_only", True)),
            max_depth=max_depth,
            allow_first=bool(args.get("allow_first", False)),
            snapshot=snap,
        )
    if normalized in {"ui_search_action", "ui_action_search", "perform_ui_action_search"}:
        max_depth = int(args.get("max_depth", 4))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        return perform_ui_action_search(
            args["query"],
            args["action"],
            role=args.get("role"),
            enabled_only=bool(args.get("enabled_only", True)),
            max_depth=max_depth,
            allow_first=bool(args.get("allow_first", False)),
            snapshot=snap,
        )
    if normalized in {"project_settings", "read_project_settings"}:
        max_depth = int(args.get("max_depth", 3))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        return project_settings(max_depth=max_depth, snapshot=snap)
    if normalized in {"project_setting_options", "project_settings_options"}:
        return project_setting_options()
    if normalized in {"set_project_settings", "project_settings_set"}:
        max_depth = int(args.get("max_depth", 3))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        return set_project_settings(
            tempo=args.get("tempo"),
            key_signature=args.get("key_signature"),
            time_signature=args.get("time_signature"),
            max_depth=max_depth,
            snapshot=snap,
        )
    if normalized in {"list_tracks", "tracks"}:
        max_depth = int(args.get("max_depth", 7))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        return list_tracks(
            max_depth=max_depth,
            include_values=bool(args.get("include_values", True)),
            snapshot=snap,
        )
    if normalized in {"select_track", "track_select"}:
        max_depth = int(args.get("max_depth", 6))
        fast = bool(args.get("fast", False))
        snapshot_depth = min(max_depth, 5) if fast else max_depth
        snap = _cached_ui_snapshot(context, snapshot_depth) if args.get("use_cache", True) else None
        index_value = args.get("index")
        return select_track(
            index=int(index_value) if index_value is not None else None,
            name=args.get("name"),
            max_depth=snapshot_depth,
            x_offset=float(args.get("x_offset", 110.0)),
            y_fraction=float(args.get("y_fraction", 0.5)),
            fast=fast,
            row_height=float(args.get("row_height", 129.0)),
            snapshot=snap,
        )
    if normalized in {"set_track", "track_set"}:
        max_depth = int(args.get("max_depth", 7))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        index_value = args.get("index")
        return set_track(
            index=int(index_value) if index_value is not None else None,
            name=args.get("name"),
            mute=args.get("mute"),
            solo=args.get("solo"),
            volume=args.get("volume"),
            pan=args.get("pan"),
            rename=args.get("rename"),
            max_depth=max_depth,
            snapshot=snap,
        )
    if normalized in {"list_regions", "regions"}:
        max_depth = int(args.get("max_depth", 7))
        snap = _cached_ui_snapshot(context, max_depth) if args.get("use_cache", True) else None
        return list_regions(max_depth=max_depth, snapshot=snap)
    if normalized in {"smart_controls", "list_smart_controls"}:
        return smart_controls(
            show=bool(args.get("show", True)),
            max_depth=int(args.get("max_depth", 4)),
            include_values=bool(args.get("include_values", False)),
            include_disabled=bool(args.get("include_disabled", True)),
            limit=int(args.get("limit", 200)),
        )
    if normalized in {"set_smart_control", "smart_control_set"}:
        return set_smart_control(
            query=args.get("query"),
            path=args.get("path"),
            value=args.get("value"),
            action=args.get("action"),
            role=args.get("role"),
            show=bool(args.get("show", True)),
            max_depth=int(args.get("max_depth", 4)),
            include_tabs=bool(args.get("include_tabs", True)),
            allow_first=bool(args.get("allow_first", False)),
        )
    if normalized in {"library_search", "search_library"}:
        return library_search(
            args.get("query"),
            show=bool(args.get("show", True)),
            limit=int(args.get("limit", 50)),
            result_depth=int(args.get("result_depth", 4)),
        )
    if normalized in {"library_select", "select_library"}:
        index_value = args.get("index")
        return library_select(
            args.get("query"),
            name=args.get("name"),
            index=int(index_value) if index_value is not None else None,
            allow_first=bool(args.get("allow_first", False)),
            show=bool(args.get("show", True)),
        )
    if normalized in {"loop_search", "search_loops"}:
        return loop_search(
            args.get("query"),
            show=bool(args.get("show", True)),
        )
    if normalized in {"loop_select", "select_loop"}:
        return loop_select(
            args.get("query"),
            index=int(args.get("index", 1)),
            show=bool(args.get("show", True)),
            row_height=float(args.get("row_height", 24.0)),
            x_offset=float(args.get("x_offset", 70.0)),
        )
    if normalized in {"loop_drag", "drag_loop"}:
        return loop_drag(
            args.get("query"),
            index=int(args.get("index", 1)),
            destination_x=float(args.get("destination_x", 390.0)),
            destination_y=float(args.get("destination_y", 195.0)),
            show=bool(args.get("show", True)),
            row_height=float(args.get("row_height", 24.0)),
            x_offset=float(args.get("x_offset", 70.0)),
            delay_seconds=float(args.get("delay_seconds", 0.7)),
            acknowledge_content_install_risk=bool(args.get("acknowledge_content_install_risk", False)),
        )
    if normalized in {"ui_click", "click_ui"}:
        return click_ui(args["name"], role=args.get("role"), exact=bool(args.get("exact", False)))
    if normalized == "ui_info_path":
        return ui_info_path(args["path"])
    if normalized in {"ui_details_path", "ui_path_details"}:
        return ui_details_path(args["path"])
    if normalized in {"ui_click_path", "click_ui_path"}:
        return click_ui_path(args["path"])
    if normalized in {"ui_action_path", "perform_ui_action_path"}:
        return perform_ui_action_path(args["path"], args["action"])
    if normalized in {"ui_set_value", "set_ui_value"}:
        return set_ui_value_path(args["path"], str(args["value"]))
    if normalized == "screenshot":
        return screenshot(args["output_path"] if "output_path" in args else args["output"])
    if normalized in {"annotated_screenshot", "annotated-screenshot", "click_map"}:
        return annotated_screenshot(
            args["output_path"] if "output_path" in args else args["output"],
            map_output_path=args.get("map_output_path"),
            max_depth=int(args.get("max_depth", 3)),
            include_grid=bool(args.get("include_grid", True)),
            grid_step=int(args.get("grid_step", 100)),
            include_disabled=bool(args.get("include_disabled", False)),
            limit=int(args.get("limit", 120)),
        )
    if normalized == "window_rect":
        return window_rect()
    if normalized == "window_click":
        return click_window(float(args["x"]), float(args["y"]))
    if normalized == "window_drag":
        return drag_window(
            float(args["x1"]),
            float(args["y1"]),
            float(args["x2"]),
            float(args["y2"]),
            delay_seconds=float(args.get("delay_seconds", args.get("delay", 0.2))),
        )
    if normalized == "type_text":
        return type_text(str(args.get("text", "")))
    if normalized == "shortcut":
        return shortcut(args["key"], list(args.get("modifiers", args.get("mods", []))))
    if normalized == "transport":
        return transport(args["action"])
    if normalized == "export_dialog":
        return open_export_dialog()
    if normalized in {"export_song", "export"}:
        return export_song(
            _one_of(args, "output_path", "output", "path"),
            format_name=args.get("format"),
            quality=args.get("quality"),
            include_cycle=args.get("include_cycle"),
            overwrite=bool(args.get("overwrite", False)),
            timeout_seconds=float(args.get("timeout_seconds", args.get("timeout", 180.0))),
        )
    if normalized in {"midi_info", "inspect_midi"}:
        return midi_info(args["path"])
    if normalized in {"audio_info", "inspect_audio"}:
        return audio_info(args["path"])
    if normalized == "tab_to_midi":
        tab_text = _one_of(args, "tab_text", "tab")
        if not tab_text and args.get("tab_file"):
            tab_text = Path(args["tab_file"]).expanduser().read_text(encoding="utf-8")
        return create_midi_from_tab(
            tab_text or "",
            _one_of(args, "output_path", "output"),
            bpm=int(args["bpm"]) if args.get("bpm") is not None else None,
            open_in_garageband=bool(args.get("open_in_garageband", args.get("open", False))),
            track_name=args.get("track_name", "GarageBand Bridge Tab"),
            ticks_per_column=int(args.get("ticks_per_column", 120)),
            sustain_columns=int(args.get("sustain_columns", 2)),
            capo=int(args["capo"]) if args.get("capo") is not None else None,
            tuning=args.get("tuning"),
        )
    if normalized in {"arrange_tab_to_midi", "tab_to_arranged_midi"}:
        tab_text = _one_of(args, "tab_text", "tab")
        if not tab_text and args.get("tab_file"):
            tab_text = Path(args["tab_file"]).expanduser().read_text(encoding="utf-8")
        return create_arranged_midi_from_tab(
            tab_text or "",
            _one_of(args, "output_path", "output"),
            bpm=int(args["bpm"]) if args.get("bpm") is not None else None,
            open_in_garageband=bool(args.get("open_in_garageband", args.get("open", False))),
            title=args.get("title", "GarageBand Bridge Arrangement"),
            ticks_per_column=int(args.get("ticks_per_column", 120)),
            sustain_columns=int(args.get("sustain_columns", 2)),
            include_bass=bool(args.get("include_bass", True)),
            include_drums=bool(args.get("include_drums", True)),
            style=args.get("style", args.get("arrangement_style", "rock")),
            repeat_count=int(args.get("repeat_count", args.get("repeats", 1))),
            capo=int(args["capo"]) if args.get("capo") is not None else None,
            tuning=args.get("tuning"),
        )
    if normalized == "image_to_tab":
        return extract_tab_from_image(
            image_path=args.get("image_path") or args.get("image"),
            image_url=args.get("image_url") or args.get("url"),
            download_dir=args.get("download_dir"),
        )
    if normalized == "image_to_midi":
        return create_midi_from_tab_image(
            _one_of(args, "output_path", "output"),
            image_path=args.get("image_path") or args.get("image"),
            image_url=args.get("image_url") or args.get("url"),
            download_dir=args.get("download_dir"),
            bpm=int(args["bpm"]) if args.get("bpm") is not None else None,
            open_in_garageband=bool(args.get("open_in_garageband", args.get("open", False))),
            track_name=args.get("track_name", "GarageBand Bridge Image Tab"),
            ticks_per_column=int(args.get("ticks_per_column", 120)),
            sustain_columns=int(args.get("sustain_columns", 2)),
            capo=int(args["capo"]) if args.get("capo") is not None else None,
            tuning=args.get("tuning"),
        )
    if normalized in {"arrange_image_to_midi", "image_to_arranged_midi"}:
        return create_arranged_midi_from_tab_image(
            _one_of(args, "output_path", "output"),
            image_path=args.get("image_path") or args.get("image"),
            image_url=args.get("image_url") or args.get("url"),
            download_dir=args.get("download_dir"),
            bpm=int(args["bpm"]) if args.get("bpm") is not None else None,
            open_in_garageband=bool(args.get("open_in_garageband", args.get("open", False))),
            title=args.get("title", "GarageBand Bridge Arrangement"),
            ticks_per_column=int(args.get("ticks_per_column", 120)),
            sustain_columns=int(args.get("sustain_columns", 2)),
            include_bass=bool(args.get("include_bass", True)),
            include_drums=bool(args.get("include_drums", True)),
            style=args.get("style", args.get("arrangement_style", "rock")),
            repeat_count=int(args.get("repeat_count", args.get("repeats", 1))),
            capo=int(args["capo"]) if args.get("capo") is not None else None,
            tuning=args.get("tuning"),
        )
    if normalized in {"score_to_midi", "musicxml_to_midi"}:
        bpm_value = args.get("bpm")
        return create_midi_from_score(
            _one_of(args, "score_path", "score", "path"),
            _one_of(args, "output_path", "output"),
            bpm=int(bpm_value) if bpm_value is not None else None,
            velocity=int(args.get("velocity", score_midi.DEFAULT_VELOCITY)),
            open_in_garageband=bool(args.get("open_in_garageband", args.get("open", False))),
        )
    if normalized in {"score_spec_to_midi", "score_json_to_midi"}:
        score_spec = args.get("score_spec", args.get("spec"))
        if score_spec is None and args.get("score_json"):
            score_spec = json.loads(args["score_json"])
        if score_spec is None and args.get("score_json_file"):
            score_spec = json.loads(Path(args["score_json_file"]).expanduser().read_text(encoding="utf-8"))
        if not isinstance(score_spec, dict):
            raise GarageBandError("score_spec_to_midi requires score_spec object, score_json, or score_json_file.")
        return create_midi_from_score_spec(
            score_spec,
            _one_of(args, "output_path", "output"),
            velocity=int(args.get("velocity", score_midi.DEFAULT_VELOCITY)),
            open_in_garageband=bool(args.get("open_in_garageband", args.get("open", False))),
            source=args.get("score_json_file"),
        )
    if normalized in {"score_spec_schema", "score_schema"}:
        return score_spec_schema()
    if normalized in {"score_spec_validate", "validate_score_spec"}:
        score_spec = args.get("score_spec", args.get("spec"))
        if score_spec is None and args.get("score_json"):
            score_spec = json.loads(args["score_json"])
        if score_spec is None and args.get("score_json_file"):
            score_spec = json.loads(Path(args["score_json_file"]).expanduser().read_text(encoding="utf-8"))
        if not isinstance(score_spec, dict):
            raise GarageBandError("validate_score_spec requires score_spec object, score_json, or score_json_file.")
        return validate_score_spec(score_spec)
    if normalized == "make_from_tab":
        return make_from_tab(
            output_dir=args["output_dir"],
            name=args.get("name", "garageband-tab-song"),
            tab_text=args.get("tab_text") or args.get("tab"),
            tab_file=args.get("tab_file"),
            image_path=args.get("image_path") or args.get("image"),
            image_url=args.get("image_url") or args.get("url"),
            bpm=int(args["bpm"]) if args.get("bpm") is not None else None,
            open_in_garageband=bool(args.get("open_in_garageband", not bool(args.get("no_open", False)))),
            show_library=bool(args.get("show_library", False)),
            show_smart_controls=bool(args.get("show_smart_controls", False)),
            show_loop_browser=bool(args.get("show_loop_browser", False)),
            master_volume=args.get("master_volume"),
            screenshot_output=args.get("screenshot_output"),
            snapshot_depth=int(args.get("snapshot_depth", 2)),
            discard_unsaved=bool(args.get("discard_unsaved", False)),
            arrange=bool(args.get("arrange", False)),
            include_bass=bool(args.get("include_bass", True)),
            include_drums=bool(args.get("include_drums", True)),
            arrangement_style=args.get("arrangement_style", args.get("style", "rock")),
            repeat_count=int(args.get("repeat_count", args.get("repeats", 1))),
            capo=int(args["capo"]) if args.get("capo") is not None else None,
            tuning=args.get("tuning"),
            export_output=args.get("export_output") or args.get("export"),
            export_format=args.get("export_format"),
            export_quality=args.get("export_quality"),
            export_include_cycle=args.get("export_include_cycle"),
            export_overwrite=bool(args.get("export_overwrite", False)),
            export_timeout_seconds=float(args.get("export_timeout_seconds", args.get("export_timeout", 180.0))),
        )
    if normalized == "make_from_score":
        bpm_value = args.get("bpm")
        return make_from_score(
            score_path=_one_of(args, "score_path", "score", "path"),
            output_dir=args["output_dir"],
            name=args.get("name"),
            bpm=int(bpm_value) if bpm_value is not None else None,
            velocity=int(args.get("velocity", score_midi.DEFAULT_VELOCITY)),
            open_in_garageband=bool(args.get("open_in_garageband", not bool(args.get("no_open", False)))),
            show_library=bool(args.get("show_library", False)),
            show_smart_controls=bool(args.get("show_smart_controls", False)),
            show_loop_browser=bool(args.get("show_loop_browser", False)),
            screenshot_output=args.get("screenshot_output"),
            snapshot_depth=int(args.get("snapshot_depth", 2)),
            discard_unsaved=bool(args.get("discard_unsaved", False)),
            export_output=args.get("export_output") or args.get("export"),
            export_format=args.get("export_format"),
            export_quality=args.get("export_quality"),
            export_include_cycle=args.get("export_include_cycle"),
            export_overwrite=bool(args.get("export_overwrite", False)),
            export_timeout_seconds=float(args.get("export_timeout_seconds", args.get("export_timeout", 180.0))),
        )
    if normalized == "make_from_score_spec":
        score_spec = args.get("score_spec", args.get("spec"))
        if score_spec is None and args.get("score_json"):
            score_spec = json.loads(args["score_json"])
        if score_spec is None and args.get("score_json_file"):
            score_spec = json.loads(Path(args["score_json_file"]).expanduser().read_text(encoding="utf-8"))
        if not isinstance(score_spec, dict):
            raise GarageBandError("make_from_score_spec requires score_spec object, score_json, or score_json_file.")
        return make_from_score_spec(
            score_spec=score_spec,
            output_dir=args["output_dir"],
            name=args.get("name"),
            velocity=int(args.get("velocity", score_midi.DEFAULT_VELOCITY)),
            open_in_garageband=bool(args.get("open_in_garageband", not bool(args.get("no_open", False)))),
            show_library=bool(args.get("show_library", False)),
            show_smart_controls=bool(args.get("show_smart_controls", False)),
            show_loop_browser=bool(args.get("show_loop_browser", False)),
            screenshot_output=args.get("screenshot_output"),
            snapshot_depth=int(args.get("snapshot_depth", 2)),
            discard_unsaved=bool(args.get("discard_unsaved", False)),
            export_output=args.get("export_output") or args.get("export"),
            export_format=args.get("export_format"),
            export_quality=args.get("export_quality"),
            export_include_cycle=args.get("export_include_cycle"),
            export_overwrite=bool(args.get("export_overwrite", False)),
            export_timeout_seconds=float(args.get("export_timeout_seconds", args.get("export_timeout", 180.0))),
            source=args.get("score_json_file"),
        )
    if normalized == "make_music":
        return make_music(
            output_dir=args["output_dir"],
            name=args.get("name"),
            score_path=args.get("score_path") or args.get("score"),
            score_spec=args.get("score_spec", args.get("spec")),
            score_json=args.get("score_json"),
            score_json_file=args.get("score_json_file") or args.get("score_spec_file"),
            tab_text=args.get("tab_text") or args.get("tab"),
            tab_file=args.get("tab_file"),
            image_path=args.get("image_path") or args.get("image"),
            image_url=args.get("image_url") or args.get("url"),
            bpm=int(args["bpm"]) if args.get("bpm") is not None else None,
            velocity=int(args.get("velocity", score_midi.DEFAULT_VELOCITY)),
            open_in_garageband=bool(args.get("open_in_garageband", not bool(args.get("no_open", False)))),
            show_library=bool(args.get("show_library", False)),
            show_smart_controls=bool(args.get("show_smart_controls", False)),
            show_loop_browser=bool(args.get("show_loop_browser", False)),
            master_volume=args.get("master_volume"),
            screenshot_output=args.get("screenshot_output"),
            snapshot_depth=int(args.get("snapshot_depth", 2)),
            discard_unsaved=bool(args.get("discard_unsaved", False)),
            arrange=bool(args.get("arrange", True)),
            include_bass=bool(args.get("include_bass", True)),
            include_drums=bool(args.get("include_drums", True)),
            arrangement_style=args.get("arrangement_style", args.get("style", "rock")),
            repeat_count=int(args.get("repeat_count", args.get("repeats", 1))),
            capo=int(args["capo"]) if args.get("capo") is not None else None,
            tuning=args.get("tuning"),
            export_output=args.get("export_output") or args.get("export"),
            export_format=args.get("export_format"),
            export_quality=args.get("export_quality"),
            export_include_cycle=args.get("export_include_cycle"),
            export_overwrite=bool(args.get("export_overwrite", False)),
            export_timeout_seconds=float(args.get("export_timeout_seconds", args.get("export_timeout", 180.0))),
        )
    if normalized in {"wait", "sleep"}:
        seconds = max(0.0, min(30.0, float(args.get("seconds", args.get("delay", 1.0)))))
        time.sleep(seconds)
        return {"waited_seconds": seconds}
    raise GarageBandError(f"Unknown plan action: {action}")


def run_plan(plan: Any, *, stop_on_error: bool = True) -> dict[str, Any]:
    """Execute a list of bridge actions with per-step structured results."""
    cache_ui = True
    if isinstance(plan, dict):
        steps = plan.get("steps", plan.get("actions"))
        plan_name = plan.get("name")
        if "stop_on_error" in plan:
            stop_on_error = bool(plan["stop_on_error"])
        if "cache_ui" in plan:
            cache_ui = bool(plan["cache_ui"])
    else:
        steps = plan
        plan_name = None
    if not isinstance(steps, list) or not steps:
        raise GarageBandError("Plan must be a non-empty list or an object with a non-empty steps/actions list.")

    results: list[dict[str, Any]] = []
    context: dict[str, Any] = {"cache_ui": cache_ui, "ui_snapshots": {}}
    for index, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, dict):
            step_result = {
                "index": index,
                "ok": False,
                "error": "Each plan step must be an object.",
                "type": "GarageBandError",
            }
            results.append(step_result)
            if stop_on_error:
                break
            continue
        action = str(raw_step.get("action") or raw_step.get("tool") or "").strip()
        if not action:
            step_result = {
                "index": index,
                "ok": False,
                "error": "Plan step is missing action.",
                "type": "GarageBandError",
            }
            results.append(step_result)
            if stop_on_error:
                break
            continue
        started = time.time()
        try:
            data = _call_bridge_action(action, _step_args(raw_step), context=context)
            if _action_changes_ui(action):
                _invalidate_plan_ui_cache(context)
            results.append(
                {
                    "index": index,
                    "action": action,
                    "ok": True,
                    "elapsed_seconds": round(time.time() - started, 3),
                    "data": data,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "index": index,
                    "action": action,
                    "ok": False,
                    "elapsed_seconds": round(time.time() - started, 3),
                    "error": str(exc),
                    "type": exc.__class__.__name__,
                }
            )
            if stop_on_error:
                break

    return {
        "ok": all(step.get("ok") for step in results) and len(results) == len(steps),
        "name": plan_name,
        "stop_on_error": stop_on_error,
        "cache_ui": cache_ui,
        "steps_requested": len(steps),
        "steps_completed": len(results),
        "results": results,
    }


def permissions_note() -> dict[str, Any]:
    return {
        "needed": [
            "Automation permission for the terminal or MCP client to control GarageBand",
            "Accessibility permission for menu clicks and keyboard shortcuts via System Events",
        ],
        "where": "System Settings > Privacy & Security > Automation and Accessibility",
        "why": "GarageBand exposes almost no native AppleScript API, so UI scripting is required for most commands.",
    }


def ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def fail(exc: BaseException) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), "type": exc.__class__.__name__}


def _load_json_arg(json_text: str | None, json_file: str | None) -> Any:
    if bool(json_text) == bool(json_file):
        raise GarageBandError("Provide exactly one of --json or --file.")
    if json_file:
        source = Path(json_file).expanduser().read_text(encoding="utf-8")
    else:
        source = json_text or ""
    try:
        return json.loads(source)
    except json.JSONDecodeError as exc:
        raise GarageBandError(f"Invalid JSON plan: {exc}") from exc


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="garageband-bridge",
        description="CLI bridge that lets LLM agents control GarageBand through macOS automation.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    p_capabilities = sub.add_parser("capabilities")
    p_capabilities.add_argument("--no-live", action="store_true", help="Do not inspect current GarageBand state.")

    p_self_test = sub.add_parser("self-test")
    p_self_test.add_argument("--output-dir", default=None, help="Where proof artifacts should be written.")
    p_self_test.add_argument("--no-ui", action="store_true", help="Skip UI snapshot and window rectangle checks.")
    p_self_test.add_argument("--no-screenshot", action="store_true", help="Skip screenshot capture.")
    self_test_source = p_self_test.add_mutually_exclusive_group()
    self_test_source.add_argument("--image", help="Optional local tab image to verify OCR extraction.")
    self_test_source.add_argument("--url", help="Optional online tab image URL to verify OCR extraction.")

    sub.add_parser("recipes")
    p_run_plan = sub.add_parser("run-plan")
    plan_source = p_run_plan.add_mutually_exclusive_group(required=True)
    plan_source.add_argument("--json", help="Inline JSON plan object or step list.")
    plan_source.add_argument("--file", help="Path to a JSON plan file.")
    p_run_plan.add_argument("--continue-on-error", action="store_true", help="Continue after a failed plan step.")

    sub.add_parser("launch")
    sub.add_parser("activate")
    sub.add_parser("quit")
    sub.add_parser("permissions")

    p_dismiss = sub.add_parser("dismiss-save-prompt")
    p_dismiss.add_argument("--discard", action="store_true", help="Click Don't Save if a GarageBand save prompt is visible.")

    p_open = sub.add_parser("open")
    p_open.add_argument("path")

    p_preview = sub.add_parser("render-preview")
    p_preview.add_argument("path", nargs="?")

    p_menus = sub.add_parser("menus")
    p_menus.add_argument("--enabled-only", action="store_true")

    p_menu_map = sub.add_parser("menu-map")
    p_menu_map.add_argument("--enabled-only", action="store_true")
    p_menu_map.add_argument("--max-depth", type=int, default=5)
    p_menu_map.add_argument("--top-menu", default=None, help='Optional top-level menu, such as "File", "View", or "Share".')

    p_menu_search = sub.add_parser("menu-search")
    p_menu_search.add_argument("query")
    p_menu_search.add_argument("--enabled-only", action="store_true")
    p_menu_search.add_argument("--max-depth", type=int, default=5)
    p_menu_search.add_argument("--limit", type=int, default=50)
    p_menu_search.add_argument("--top-menu", default=None, help='Optional top-level menu, such as "File", "View", or "Share".')

    p_menu_search_click = sub.add_parser("menu-search-click")
    p_menu_search_click.add_argument("query")
    p_menu_search_click.add_argument("--enabled-only", action=argparse.BooleanOptionalAction, default=True)
    p_menu_search_click.add_argument("--max-depth", type=int, default=5)
    p_menu_search_click.add_argument("--top-menu", default=None, help='Optional top-level menu, such as "File", "View", or "Share".')
    p_menu_search_click.add_argument("--allow-first", action="store_true", help="Click the first match even when multiple matches are found.")

    p_menu = sub.add_parser("menu")
    p_menu.add_argument("path", help='Example: "File > Open..."')

    p_ui_snapshot = sub.add_parser("ui-snapshot")
    p_ui_snapshot.add_argument("--max-depth", type=int, default=4)

    p_ui_search = sub.add_parser("ui-search")
    p_ui_search.add_argument("query")
    p_ui_search.add_argument("--role", default=None)
    p_ui_search.add_argument("--enabled-only", action="store_true")
    p_ui_search.add_argument("--max-depth", type=int, default=4)
    p_ui_search.add_argument("--limit", type=int, default=50)

    p_ui_controls = sub.add_parser("ui-controls")
    p_ui_controls.add_argument("--max-depth", type=int, default=3)

    p_wait_ui = sub.add_parser("wait-ui")
    p_wait_ui.add_argument("query")
    p_wait_ui.add_argument("--role", default=None)
    p_wait_ui.add_argument("--enabled-only", action="store_true")
    p_wait_ui.add_argument("--max-depth", type=int, default=4)
    p_wait_ui.add_argument("--timeout", type=float, default=10.0)
    p_wait_ui.add_argument("--interval", type=float, default=0.5)
    p_wait_ui.add_argument("--limit", type=int, default=10)

    p_ui_search_click = sub.add_parser("ui-search-click")
    p_ui_search_click.add_argument("query")
    p_ui_search_click.add_argument("--role", default=None)
    p_ui_search_click.add_argument("--enabled-only", action=argparse.BooleanOptionalAction, default=True)
    p_ui_search_click.add_argument("--max-depth", type=int, default=4)
    p_ui_search_click.add_argument("--allow-first", action="store_true", help="Click the first match even when multiple matches are found.")

    p_ui_search_info = sub.add_parser("ui-search-info")
    p_ui_search_info.add_argument("query")
    p_ui_search_info.add_argument("--role", default=None)
    p_ui_search_info.add_argument("--enabled-only", action=argparse.BooleanOptionalAction, default=True)
    p_ui_search_info.add_argument("--max-depth", type=int, default=4)
    p_ui_search_info.add_argument("--allow-first", action="store_true", help="Read the first match even when multiple matches are found.")

    p_ui_search_details = sub.add_parser("ui-search-details")
    p_ui_search_details.add_argument("query")
    p_ui_search_details.add_argument("--role", default=None)
    p_ui_search_details.add_argument("--enabled-only", action=argparse.BooleanOptionalAction, default=True)
    p_ui_search_details.add_argument("--max-depth", type=int, default=4)
    p_ui_search_details.add_argument("--allow-first", action="store_true", help="Describe the first match even when multiple matches are found.")

    p_ui_search_set = sub.add_parser("ui-search-set")
    p_ui_search_set.add_argument("query")
    p_ui_search_set.add_argument("value")
    p_ui_search_set.add_argument("--role", default=None)
    p_ui_search_set.add_argument("--enabled-only", action=argparse.BooleanOptionalAction, default=True)
    p_ui_search_set.add_argument("--max-depth", type=int, default=4)
    p_ui_search_set.add_argument("--allow-first", action="store_true", help="Set the first match even when multiple matches are found.")

    p_ui_search_action = sub.add_parser("ui-search-action")
    p_ui_search_action.add_argument("query")
    p_ui_search_action.add_argument("action", help="Accessibility action: increment, decrement, press, AXIncrement, AXDecrement, or AXPress.")
    p_ui_search_action.add_argument("--role", default=None)
    p_ui_search_action.add_argument("--enabled-only", action=argparse.BooleanOptionalAction, default=True)
    p_ui_search_action.add_argument("--max-depth", type=int, default=4)
    p_ui_search_action.add_argument("--allow-first", action="store_true", help="Act on the first match even when multiple matches are found.")

    p_ui_click = sub.add_parser("ui-click")
    p_ui_click.add_argument("name")
    p_ui_click.add_argument("--role", default=None)
    p_ui_click.add_argument("--exact", action="store_true")

    p_ui_info_path = sub.add_parser("ui-info-path")
    p_ui_info_path.add_argument("path", help='Path from ui-snapshot, for example "window[1]/6/5".')

    p_ui_details_path = sub.add_parser("ui-details-path")
    p_ui_details_path.add_argument("path", help='Path from ui-snapshot, for example "window[1]/6/1/3".')

    p_ui_click_path = sub.add_parser("ui-click-path")
    p_ui_click_path.add_argument("path", help='Path from ui-snapshot, for example "window[1]/6/5".')

    p_ui_action_path = sub.add_parser("ui-action-path")
    p_ui_action_path.add_argument("path", help='Path from ui-snapshot, for example "window[1]/6/1/3".')
    p_ui_action_path.add_argument("action", help="Accessibility action: increment, decrement, press, AXIncrement, AXDecrement, or AXPress.")

    p_ui_set_value = sub.add_parser("ui-set-value")
    p_ui_set_value.add_argument("path", help='Path from ui-snapshot, for example "window[1]/6/17".')
    p_ui_set_value.add_argument("value")

    p_project_settings = sub.add_parser("project-settings")
    p_project_settings.add_argument("--max-depth", type=int, default=3)

    sub.add_parser("project-setting-options")

    p_set_project_settings = sub.add_parser("set-project-settings")
    p_set_project_settings.add_argument("--tempo", default=None)
    p_set_project_settings.add_argument("--key-signature", default=None)
    p_set_project_settings.add_argument("--time-signature", default=None)
    p_set_project_settings.add_argument("--max-depth", type=int, default=3)

    p_list_tracks = sub.add_parser("list-tracks")
    p_list_tracks.add_argument("--max-depth", type=int, default=7)
    p_list_tracks.add_argument("--no-values", action="store_true", help="Skip reading live control values.")

    p_select_track = sub.add_parser("select-track")
    track_select_selector = p_select_track.add_mutually_exclusive_group()
    track_select_selector.add_argument("--index", type=int, default=None, help="Visible track index, such as 1.")
    track_select_selector.add_argument("--name", default=None, help="Visible track name or unique substring.")
    p_select_track.add_argument("--max-depth", type=int, default=6)
    p_select_track.add_argument("--x-offset", type=float, default=110.0, help="Horizontal click offset inside the visible track header.")
    p_select_track.add_argument("--y-fraction", type=float, default=0.5, help="Vertical click fraction inside the visible track header.")
    p_select_track.add_argument("--fast", action="store_true", help="Use visible index geometry without recovering track names.")
    p_select_track.add_argument("--row-height", type=float, default=129.0, help="Visible track row height for --fast mode.")

    p_set_track = sub.add_parser("set-track")
    track_selector = p_set_track.add_mutually_exclusive_group()
    track_selector.add_argument("--index", type=int, default=None, help="Visible track index, such as 1.")
    track_selector.add_argument("--name", default=None, help="Visible track name or unique substring.")
    p_set_track.add_argument("--mute", default=None, help="true/false, on/off, or 1/0.")
    p_set_track.add_argument("--solo", default=None, help="true/false, on/off, or 1/0.")
    p_set_track.add_argument("--volume", default=None, help="Track volume value accepted by GarageBand's visible slider.")
    p_set_track.add_argument("--pan", default=None, help="Track pan value accepted by GarageBand's visible slider.")
    p_set_track.add_argument("--rename", default=None, help="Set the visible track name text field.")
    p_set_track.add_argument("--max-depth", type=int, default=7)

    p_list_regions = sub.add_parser("list-regions")
    p_list_regions.add_argument("--max-depth", type=int, default=8)

    p_smart_controls = sub.add_parser("smart-controls")
    p_smart_controls.add_argument("--no-show", action="store_true", help="Do not click the Smart Controls button first.")
    p_smart_controls.add_argument("--max-depth", type=int, default=4)
    p_smart_controls.add_argument("--values", action="store_true", help="Read live Smart Control values. This can be slower.")
    p_smart_controls.add_argument("--exclude-disabled", action="store_true", help="Hide disabled Smart Controls and tabs.")
    p_smart_controls.add_argument("--limit", type=int, default=200)

    p_set_smart_control = sub.add_parser("set-smart-control")
    smart_selector = p_set_smart_control.add_mutually_exclusive_group(required=True)
    smart_selector.add_argument("--query", default=None, help="Visible Smart Control label, description, role, or path substring.")
    smart_selector.add_argument("--path", default=None, help="Exact Smart Control path from smart-controls.")
    p_set_smart_control.add_argument("--value", default=None, help="Value to set on a visible Smart Control.")
    p_set_smart_control.add_argument("--action", default=None, help="Accessibility action to perform, defaulting to press when no value is provided.")
    p_set_smart_control.add_argument("--role", default=None, help="Optional Accessibility role filter.")
    p_set_smart_control.add_argument("--no-show", action="store_true", help="Do not click the Smart Controls button first.")
    p_set_smart_control.add_argument("--max-depth", type=int, default=4)
    p_set_smart_control.add_argument("--exclude-tabs", action="store_true", help="Do not match Track/Master/Controls/EQ tabs.")
    p_set_smart_control.add_argument("--allow-first", action="store_true", help="Use the first match when the query is ambiguous.")

    p_library_search = sub.add_parser("library-search")
    p_library_search.add_argument("query", nargs="?", default=None, help="Optional text for GarageBand's Library search field.")
    p_library_search.add_argument("--no-show", action="store_true", help="Do not click the Library button first.")
    p_library_search.add_argument("--limit", type=int, default=50)
    p_library_search.add_argument("--result-depth", type=int, default=4)

    p_library_select = sub.add_parser("library-select")
    p_library_select.add_argument("query", nargs="?", default=None, help="Optional Library search query.")
    p_library_select.add_argument("--name", default=None, help="Visible Library result name or unique substring to select.")
    p_library_select.add_argument("--index", type=int, default=None, help="Visible Library result index from library-search.")
    p_library_select.add_argument("--allow-first", action="store_true", help="Press the first result when multiple matches are found.")
    p_library_select.add_argument("--no-show", action="store_true", help="Do not click the Library button first.")

    p_loop_search = sub.add_parser("loop-search")
    p_loop_search.add_argument("query", nargs="?", default=None, help="Optional text for GarageBand's Apple Loops search field.")
    p_loop_search.add_argument("--no-show", action="store_true", help="Do not click the Loop Browser button first.")

    p_loop_select = sub.add_parser("loop-select")
    p_loop_select.add_argument("query", nargs="?", default=None, help="Optional text for GarageBand's Apple Loops search field before selecting.")
    p_loop_select.add_argument("--index", type=int, default=1, help="Visible row index to select after filtering.")
    p_loop_select.add_argument("--no-show", action="store_true", help="Do not click the Loop Browser button first.")
    p_loop_select.add_argument("--row-height", type=float, default=24.0, help="Visible Loop Browser table row height in screen points.")
    p_loop_select.add_argument("--x-offset", type=float, default=70.0, help="Horizontal click offset inside the loop table in screen points.")

    p_loop_drag = sub.add_parser("loop-drag")
    p_loop_drag.add_argument("query", nargs="?", default=None, help="Optional text for GarageBand's Apple Loops search field before dragging.")
    p_loop_drag.add_argument("--index", type=int, default=1, help="Visible row index to drag after filtering.")
    p_loop_drag.add_argument("--destination-x", type=float, default=390.0, help="Window-relative timeline X coordinate to drop onto.")
    p_loop_drag.add_argument("--destination-y", type=float, default=195.0, help="Window-relative timeline Y coordinate to drop onto.")
    p_loop_drag.add_argument("--no-show", action="store_true", help="Do not click the Loop Browser button first.")
    p_loop_drag.add_argument("--row-height", type=float, default=24.0, help="Visible Loop Browser table row height in screen points.")
    p_loop_drag.add_argument("--x-offset", type=float, default=70.0, help="Horizontal drag-start offset inside the loop table in screen points.")
    p_loop_drag.add_argument("--delay", type=float, default=0.7, help="Mouse hold delay while dragging in seconds.")
    p_loop_drag.add_argument(
        "--acknowledge-content-install-risk",
        action="store_true",
        help="Required because dragging downloadable loop rows can open Apple's sound/content installer.",
    )

    p_screenshot = sub.add_parser("screenshot")
    p_screenshot.add_argument("--output", required=True, help="Output PNG path.")

    p_annotated_screenshot = sub.add_parser("annotated-screenshot")
    p_annotated_screenshot.add_argument("--output", required=True, help="Output annotated PNG path.")
    p_annotated_screenshot.add_argument("--map-output", default=None, help="Optional JSON click-map output path.")
    p_annotated_screenshot.add_argument("--max-depth", type=int, default=3, help="Accessibility snapshot depth for target boxes.")
    p_annotated_screenshot.add_argument("--no-grid", action="store_true", help="Do not draw the coordinate grid.")
    p_annotated_screenshot.add_argument("--grid-step", type=int, default=100, help="Coordinate grid step in GarageBand window points.")
    p_annotated_screenshot.add_argument("--include-disabled", action="store_true", help="Include disabled visible controls in the map.")
    p_annotated_screenshot.add_argument("--limit", type=int, default=120, help="Maximum number of numbered targets to draw.")

    sub.add_parser("window-rect")

    p_window_click = sub.add_parser("window-click")
    p_window_click.add_argument("x", type=float, help="X coordinate in GarageBand window points.")
    p_window_click.add_argument("y", type=float, help="Y coordinate in GarageBand window points.")

    p_window_drag = sub.add_parser("window-drag")
    p_window_drag.add_argument("x1", type=float)
    p_window_drag.add_argument("y1", type=float)
    p_window_drag.add_argument("x2", type=float)
    p_window_drag.add_argument("y2", type=float)
    p_window_drag.add_argument("--delay", type=float, default=0.2)

    p_type_text = sub.add_parser("type-text")
    p_type_text.add_argument("text")

    p_shortcut = sub.add_parser("shortcut")
    p_shortcut.add_argument("key")
    p_shortcut.add_argument("--mod", action="append", default=[])

    p_transport = sub.add_parser("transport")
    p_transport.add_argument("action", choices=sorted(TRANSPORT_SHORTCUTS))

    p_midi_info = sub.add_parser("midi-info")
    p_midi_info.add_argument("path")

    p_audio_info = sub.add_parser("audio-info")
    p_audio_info.add_argument("path")

    p_tab = sub.add_parser("tab-to-midi")
    tab_source = p_tab.add_mutually_exclusive_group(required=True)
    tab_source.add_argument("--tab", help="Inline six-line ASCII guitar tab text.")
    tab_source.add_argument("--tab-file", help="Path to a text file containing six-line ASCII guitar tab.")
    p_tab.add_argument("--output", required=True, help="Output .mid path.")
    p_tab.add_argument("--bpm", type=int, default=None, help="Override detected tab tempo.")
    p_tab.add_argument("--track-name", default="GarageBand Bridge Tab")
    p_tab.add_argument("--ticks-per-column", type=int, default=120)
    p_tab.add_argument("--sustain-columns", type=int, default=2)
    p_tab.add_argument("--capo", type=int, default=None, help="Override detected capo fret for tab sources.")
    p_tab.add_argument("--tuning", default=None, help="Override detected tuning, such as 'drop d' or 'D A D G B E'.")
    p_tab.add_argument("--open", action="store_true", help="Open the generated MIDI file in GarageBand.")

    p_arrange_tab = sub.add_parser("arrange-tab-to-midi")
    arrange_tab_source = p_arrange_tab.add_mutually_exclusive_group(required=True)
    arrange_tab_source.add_argument("--tab", help="Inline six-line ASCII guitar tab text.")
    arrange_tab_source.add_argument("--tab-file", help="Path to a text file containing six-line ASCII guitar tab.")
    p_arrange_tab.add_argument("--output", required=True, help="Output .mid path.")
    p_arrange_tab.add_argument("--bpm", type=int, default=None, help="Override detected tab tempo.")
    p_arrange_tab.add_argument("--title", default="GarageBand Bridge Arrangement")
    p_arrange_tab.add_argument("--ticks-per-column", type=int, default=120)
    p_arrange_tab.add_argument("--sustain-columns", type=int, default=2)
    p_arrange_tab.add_argument("--capo", type=int, default=None, help="Override detected capo fret for tab sources.")
    p_arrange_tab.add_argument("--tuning", default=None, help="Override detected tuning, such as 'drop d' or 'D A D G B E'.")
    p_arrange_tab.add_argument("--no-bass", action="store_true", help="Do not add a bass track.")
    p_arrange_tab.add_argument("--no-drums", action="store_true", help="Do not add a drum track.")
    p_arrange_tab.add_argument("--style", default="rock", choices=sorted(tab_midi.ARRANGEMENT_STYLES), help="Arrangement feel for generated drums.")
    p_arrange_tab.add_argument("--repeat-count", type=int, default=1, help="Repeat the parsed tab section this many times.")
    p_arrange_tab.add_argument("--open", action="store_true", help="Open the generated MIDI file in GarageBand.")

    p_image_tab = sub.add_parser("image-to-tab")
    image_tab_source = p_image_tab.add_mutually_exclusive_group(required=True)
    image_tab_source.add_argument("--image", help="Local image path containing guitar tab.")
    image_tab_source.add_argument("--url", help="Image URL containing guitar tab.")
    p_image_tab.add_argument("--download-dir", default=None, help="Where URL images should be saved.")

    p_image_midi = sub.add_parser("image-to-midi")
    image_midi_source = p_image_midi.add_mutually_exclusive_group(required=True)
    image_midi_source.add_argument("--image", help="Local image path containing guitar tab.")
    image_midi_source.add_argument("--url", help="Image URL containing guitar tab.")
    p_image_midi.add_argument("--download-dir", default=None, help="Where URL images should be saved.")
    p_image_midi.add_argument("--output", required=True, help="Output .mid path.")
    p_image_midi.add_argument("--bpm", type=int, default=None, help="Override detected tab tempo.")
    p_image_midi.add_argument("--track-name", default="GarageBand Bridge Image Tab")
    p_image_midi.add_argument("--ticks-per-column", type=int, default=120)
    p_image_midi.add_argument("--sustain-columns", type=int, default=2)
    p_image_midi.add_argument("--capo", type=int, default=None, help="Override detected capo fret from OCR text.")
    p_image_midi.add_argument("--tuning", default=None, help="Override detected tuning from OCR text.")
    p_image_midi.add_argument("--open", action="store_true", help="Open the generated MIDI file in GarageBand.")

    p_arrange_image = sub.add_parser("arrange-image-to-midi")
    arrange_image_source = p_arrange_image.add_mutually_exclusive_group(required=True)
    arrange_image_source.add_argument("--image", help="Local image path containing guitar tab.")
    arrange_image_source.add_argument("--url", help="Image URL containing guitar tab.")
    p_arrange_image.add_argument("--download-dir", default=None, help="Where URL images should be saved.")
    p_arrange_image.add_argument("--output", required=True, help="Output .mid path.")
    p_arrange_image.add_argument("--bpm", type=int, default=None, help="Override detected tab tempo.")
    p_arrange_image.add_argument("--title", default="GarageBand Bridge Arrangement")
    p_arrange_image.add_argument("--ticks-per-column", type=int, default=120)
    p_arrange_image.add_argument("--sustain-columns", type=int, default=2)
    p_arrange_image.add_argument("--capo", type=int, default=None, help="Override detected capo fret from OCR text.")
    p_arrange_image.add_argument("--tuning", default=None, help="Override detected tuning from OCR text.")
    p_arrange_image.add_argument("--no-bass", action="store_true", help="Do not add a bass track.")
    p_arrange_image.add_argument("--no-drums", action="store_true", help="Do not add a drum track.")
    p_arrange_image.add_argument("--style", default="rock", choices=sorted(tab_midi.ARRANGEMENT_STYLES), help="Arrangement feel for generated drums.")
    p_arrange_image.add_argument("--repeat-count", type=int, default=1, help="Repeat the parsed tab section this many times.")
    p_arrange_image.add_argument("--open", action="store_true", help="Open the generated MIDI file in GarageBand.")

    p_score = sub.add_parser("score-to-midi")
    p_score.add_argument("--score", required=True, help="MusicXML .musicxml/.xml or compressed .mxl full-score path.")
    p_score.add_argument("--output", required=True, help="Output .mid path.")
    p_score.add_argument("--bpm", type=int, default=None, help="Override the score tempo.")
    p_score.add_argument("--velocity", type=int, default=score_midi.DEFAULT_VELOCITY)
    p_score.add_argument("--open", action="store_true", help="Open the generated MIDI file in GarageBand.")

    sub.add_parser("score-spec-schema")

    p_score_spec_validate = sub.add_parser("score-spec-validate")
    score_spec_validate_source = p_score_spec_validate.add_mutually_exclusive_group(required=True)
    score_spec_validate_source.add_argument("--json", help="Inline JSON score spec object.")
    score_spec_validate_source.add_argument("--file", help="Path to a JSON score spec file.")

    p_score_spec = sub.add_parser("score-spec-to-midi")
    score_spec_source = p_score_spec.add_mutually_exclusive_group(required=True)
    score_spec_source.add_argument("--json", help="Inline JSON score spec object.")
    score_spec_source.add_argument("--file", help="Path to a JSON score spec file.")
    p_score_spec.add_argument("--output", required=True, help="Output .mid path.")
    p_score_spec.add_argument("--velocity", type=int, default=score_midi.DEFAULT_VELOCITY)
    p_score_spec.add_argument("--open", action="store_true", help="Open the generated MIDI file in GarageBand.")

    p_make = sub.add_parser("make-from-tab")
    make_source = p_make.add_mutually_exclusive_group(required=True)
    make_source.add_argument("--tab", help="Inline six-line ASCII guitar tab text.")
    make_source.add_argument("--tab-file", help="Path to a text file containing six-line ASCII guitar tab.")
    make_source.add_argument("--image", help="Local image path containing guitar tab.")
    make_source.add_argument("--url", help="Image URL containing guitar tab.")
    p_make.add_argument("--output-dir", required=True)
    p_make.add_argument("--name", default="garageband-tab-song")
    p_make.add_argument("--bpm", type=int, default=None, help="Override detected tab/image tempo.")
    p_make.add_argument("--no-open", action="store_true", help="Generate MIDI without opening GarageBand.")
    p_make.add_argument("--show-library", action="store_true")
    p_make.add_argument("--show-smart-controls", action="store_true")
    p_make.add_argument("--show-loop-browser", action="store_true")
    p_make.add_argument("--master-volume", default=None)
    p_make.add_argument("--screenshot-output", default=None)
    p_make.add_argument("--snapshot-depth", type=int, default=2)
    p_make.add_argument("--discard-unsaved", action="store_true", help="If GarageBand asks about an unsaved generated project, click Don't Save.")
    p_make.add_argument("--arrange", action="store_true", help="Create a guitar/bass/drums arrangement MIDI instead of a single guitar MIDI.")
    p_make.add_argument("--no-bass", action="store_true", help="With --arrange, do not add a bass track.")
    p_make.add_argument("--no-drums", action="store_true", help="With --arrange, do not add a drum track.")
    p_make.add_argument("--style", default="rock", choices=sorted(tab_midi.ARRANGEMENT_STYLES), help="With --arrange, choose the generated drum feel.")
    p_make.add_argument("--repeat-count", type=int, default=1, help="With --arrange, repeat the parsed tab section this many times.")
    p_make.add_argument("--capo", type=int, default=None, help="Override detected capo fret for tab/image sources.")
    p_make.add_argument("--tuning", default=None, help="Override detected tuning for tab/image sources.")
    p_make.add_argument("--export-output", default=None, help="Optional audio output path to export after opening in GarageBand.")
    p_make.add_argument("--export-format", choices=sorted(EXPORT_FORMAT_EXTENSIONS), default=None)
    p_make.add_argument("--export-quality", default=None)
    p_make.add_argument("--export-include-cycle", action=argparse.BooleanOptionalAction, default=None)
    p_make.add_argument("--export-overwrite", action="store_true")
    p_make.add_argument("--export-timeout", type=float, default=180.0)

    p_make_score = sub.add_parser("make-from-score")
    p_make_score.add_argument("--score", required=True, help="MusicXML .musicxml/.xml or compressed .mxl full-score path.")
    p_make_score.add_argument("--output-dir", required=True)
    p_make_score.add_argument("--name", default=None)
    p_make_score.add_argument("--bpm", type=int, default=None, help="Override the score tempo.")
    p_make_score.add_argument("--velocity", type=int, default=score_midi.DEFAULT_VELOCITY)
    p_make_score.add_argument("--no-open", action="store_true", help="Generate MIDI without opening GarageBand.")
    p_make_score.add_argument("--show-library", action="store_true")
    p_make_score.add_argument("--show-smart-controls", action="store_true")
    p_make_score.add_argument("--show-loop-browser", action="store_true")
    p_make_score.add_argument("--screenshot-output", default=None)
    p_make_score.add_argument("--snapshot-depth", type=int, default=2)
    p_make_score.add_argument("--discard-unsaved", action="store_true", help="If GarageBand asks about an unsaved generated project, click Don't Save.")
    p_make_score.add_argument("--export-output", default=None, help="Optional audio output path to export after opening in GarageBand.")
    p_make_score.add_argument("--export-format", choices=sorted(EXPORT_FORMAT_EXTENSIONS), default=None)
    p_make_score.add_argument("--export-quality", default=None)
    p_make_score.add_argument("--export-include-cycle", action=argparse.BooleanOptionalAction, default=None)
    p_make_score.add_argument("--export-overwrite", action="store_true")
    p_make_score.add_argument("--export-timeout", type=float, default=180.0)

    p_make_score_spec = sub.add_parser("make-from-score-spec")
    make_score_spec_source = p_make_score_spec.add_mutually_exclusive_group(required=True)
    make_score_spec_source.add_argument("--json", help="Inline JSON score spec object.")
    make_score_spec_source.add_argument("--file", help="Path to a JSON score spec file.")
    p_make_score_spec.add_argument("--output-dir", required=True)
    p_make_score_spec.add_argument("--name", default=None)
    p_make_score_spec.add_argument("--velocity", type=int, default=score_midi.DEFAULT_VELOCITY)
    p_make_score_spec.add_argument("--no-open", action="store_true", help="Generate MIDI without opening GarageBand.")
    p_make_score_spec.add_argument("--show-library", action="store_true")
    p_make_score_spec.add_argument("--show-smart-controls", action="store_true")
    p_make_score_spec.add_argument("--show-loop-browser", action="store_true")
    p_make_score_spec.add_argument("--screenshot-output", default=None)
    p_make_score_spec.add_argument("--snapshot-depth", type=int, default=2)
    p_make_score_spec.add_argument("--discard-unsaved", action="store_true", help="If GarageBand asks about an unsaved generated project, click Don't Save.")
    p_make_score_spec.add_argument("--export-output", default=None, help="Optional audio output path to export after opening in GarageBand.")
    p_make_score_spec.add_argument("--export-format", choices=sorted(EXPORT_FORMAT_EXTENSIONS), default=None)
    p_make_score_spec.add_argument("--export-quality", default=None)
    p_make_score_spec.add_argument("--export-include-cycle", action=argparse.BooleanOptionalAction, default=None)
    p_make_score_spec.add_argument("--export-overwrite", action="store_true")
    p_make_score_spec.add_argument("--export-timeout", type=float, default=180.0)

    p_make_music = sub.add_parser("make-music")
    make_music_source = p_make_music.add_mutually_exclusive_group(required=True)
    make_music_source.add_argument("--score", help="MusicXML .musicxml/.xml or compressed .mxl full-score path.")
    make_music_source.add_argument("--score-json", help="Inline JSON score spec object.")
    make_music_source.add_argument("--score-json-file", help="Path to a JSON score spec file.")
    make_music_source.add_argument("--tab", help="Inline six-line ASCII guitar tab text.")
    make_music_source.add_argument("--tab-file", help="Path to a text file containing six-line ASCII guitar tab.")
    make_music_source.add_argument("--image", help="Local image path containing guitar tab.")
    make_music_source.add_argument("--url", help="Image URL containing guitar tab.")
    p_make_music.add_argument("--output-dir", required=True)
    p_make_music.add_argument("--name", default=None)
    p_make_music.add_argument("--bpm", type=int, default=None, help="Override score tempo, or set tab/image tempo.")
    p_make_music.add_argument("--velocity", type=int, default=score_midi.DEFAULT_VELOCITY)
    p_make_music.add_argument("--no-open", action="store_true", help="Generate MIDI without opening GarageBand.")
    p_make_music.add_argument("--show-library", action="store_true")
    p_make_music.add_argument("--show-smart-controls", action="store_true")
    p_make_music.add_argument("--show-loop-browser", action="store_true")
    p_make_music.add_argument("--master-volume", default=None)
    p_make_music.add_argument("--screenshot-output", default=None)
    p_make_music.add_argument("--snapshot-depth", type=int, default=2)
    p_make_music.add_argument("--discard-unsaved", action="store_true", help="If GarageBand asks about an unsaved generated project, click Don't Save.")
    p_make_music.add_argument("--no-arrange", action="store_true", help="For tab/image sources, create only one guitar track.")
    p_make_music.add_argument("--no-bass", action="store_true", help="For arranged tab/image sources, do not add a bass track.")
    p_make_music.add_argument("--no-drums", action="store_true", help="For arranged tab/image sources, do not add a drum track.")
    p_make_music.add_argument("--style", default="rock", choices=sorted(tab_midi.ARRANGEMENT_STYLES), help="For arranged tab/image sources, choose the generated drum feel.")
    p_make_music.add_argument("--repeat-count", type=int, default=1, help="For arranged tab/image sources, repeat the parsed tab section this many times.")
    p_make_music.add_argument("--capo", type=int, default=None, help="Override detected capo fret for tab/image sources.")
    p_make_music.add_argument("--tuning", default=None, help="Override detected tuning for tab/image sources.")
    p_make_music.add_argument("--export-output", default=None, help="Optional audio output path to export after opening in GarageBand.")
    p_make_music.add_argument("--export-format", choices=sorted(EXPORT_FORMAT_EXTENSIONS), default=None)
    p_make_music.add_argument("--export-quality", default=None)
    p_make_music.add_argument("--export-include-cycle", action=argparse.BooleanOptionalAction, default=None)
    p_make_music.add_argument("--export-overwrite", action="store_true")
    p_make_music.add_argument("--export-timeout", type=float, default=180.0)

    sub.add_parser("export-dialog")
    p_export_song = sub.add_parser("export-song")
    p_export_song.add_argument("--output", required=True, help="Output audio path. Extension can imply format.")
    p_export_song.add_argument("--format", choices=sorted(EXPORT_FORMAT_EXTENSIONS), default=None)
    p_export_song.add_argument("--quality", default=None, help="Optional quality label to type into GarageBand's quality popup.")
    p_export_song.add_argument("--include-cycle", action=argparse.BooleanOptionalAction, default=None, help="Export cycle area or selected region length.")
    p_export_song.add_argument("--overwrite", action="store_true", help="Replace an existing output file.")
    p_export_song.add_argument("--timeout", type=float, default=180.0, help="Seconds to wait for the exported file.")

    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            result = status()
        elif args.command == "capabilities":
            result = capabilities(include_live=not args.no_live)
        elif args.command == "self-test":
            result = self_test(
                output_dir=args.output_dir,
                include_ui=not args.no_ui,
                include_screenshot=not args.no_screenshot,
                image_path=args.image,
                image_url=args.url,
            )
        elif args.command == "recipes":
            result = recipes()
        elif args.command == "run-plan":
            result = run_plan(
                _load_json_arg(args.json, args.file),
                stop_on_error=not args.continue_on_error,
            )
        elif args.command == "launch":
            result = launch()
        elif args.command == "activate":
            result = activate()
        elif args.command == "quit":
            result = quit_app()
        elif args.command == "permissions":
            result = permissions_note()
        elif args.command == "dismiss-save-prompt":
            result = dismiss_save_prompt(discard=args.discard)
        elif args.command == "open":
            result = open_path(args.path)
        elif args.command == "render-preview":
            result = render_preview(args.path)
        elif args.command == "menus":
            result = list_menus(include_disabled=not args.enabled_only)
        elif args.command == "menu-map":
            result = menu_map(include_disabled=not args.enabled_only, max_depth=args.max_depth, top_menu=args.top_menu)
        elif args.command == "menu-search":
            result = find_menu_items(
                args.query,
                enabled_only=args.enabled_only,
                max_depth=args.max_depth,
                limit=args.limit,
                top_menu=args.top_menu,
            )
        elif args.command == "menu-search-click":
            result = click_menu_search(
                args.query,
                enabled_only=args.enabled_only,
                max_depth=args.max_depth,
                top_menu=args.top_menu,
                allow_first=args.allow_first,
            )
        elif args.command == "menu":
            result = click_menu(args.path)
        elif args.command == "ui-snapshot":
            result = ui_snapshot(args.max_depth)
        elif args.command == "ui-search":
            result = find_ui_elements(
                args.query,
                role=args.role,
                enabled_only=args.enabled_only,
                max_depth=args.max_depth,
                limit=args.limit,
            )
        elif args.command == "ui-controls":
            result = ui_controls_summary(max_depth=args.max_depth)
        elif args.command == "wait-ui":
            result = wait_ui(
                args.query,
                role=args.role,
                enabled_only=args.enabled_only,
                max_depth=args.max_depth,
                timeout_seconds=args.timeout,
                interval_seconds=args.interval,
                limit=args.limit,
            )
        elif args.command == "ui-search-click":
            result = click_ui_search(
                args.query,
                role=args.role,
                enabled_only=args.enabled_only,
                max_depth=args.max_depth,
                allow_first=args.allow_first,
            )
        elif args.command == "ui-search-info":
            result = ui_info_search(
                args.query,
                role=args.role,
                enabled_only=args.enabled_only,
                max_depth=args.max_depth,
                allow_first=args.allow_first,
            )
        elif args.command == "ui-search-details":
            result = ui_details_search(
                args.query,
                role=args.role,
                enabled_only=args.enabled_only,
                max_depth=args.max_depth,
                allow_first=args.allow_first,
            )
        elif args.command == "ui-search-set":
            result = set_ui_value_search(
                args.query,
                args.value,
                role=args.role,
                enabled_only=args.enabled_only,
                max_depth=args.max_depth,
                allow_first=args.allow_first,
            )
        elif args.command == "ui-search-action":
            result = perform_ui_action_search(
                args.query,
                args.action,
                role=args.role,
                enabled_only=args.enabled_only,
                max_depth=args.max_depth,
                allow_first=args.allow_first,
            )
        elif args.command == "ui-click":
            result = click_ui(args.name, role=args.role, exact=args.exact)
        elif args.command == "ui-info-path":
            result = ui_info_path(args.path)
        elif args.command == "ui-details-path":
            result = ui_details_path(args.path)
        elif args.command == "ui-click-path":
            result = click_ui_path(args.path)
        elif args.command == "ui-action-path":
            result = perform_ui_action_path(args.path, args.action)
        elif args.command == "ui-set-value":
            result = set_ui_value_path(args.path, args.value)
        elif args.command == "project-settings":
            result = project_settings(max_depth=args.max_depth)
        elif args.command == "project-setting-options":
            result = project_setting_options()
        elif args.command == "set-project-settings":
            result = set_project_settings(
                tempo=args.tempo,
                key_signature=args.key_signature,
                time_signature=args.time_signature,
                max_depth=args.max_depth,
            )
        elif args.command == "list-tracks":
            result = list_tracks(max_depth=args.max_depth, include_values=not args.no_values)
        elif args.command == "select-track":
            result = select_track(
                index=args.index,
                name=args.name,
                max_depth=args.max_depth,
                x_offset=args.x_offset,
                y_fraction=args.y_fraction,
                fast=args.fast,
                row_height=args.row_height,
            )
        elif args.command == "set-track":
            result = set_track(
                index=args.index,
                name=args.name,
                mute=args.mute,
                solo=args.solo,
                volume=args.volume,
                pan=args.pan,
                rename=args.rename,
                max_depth=args.max_depth,
            )
        elif args.command == "list-regions":
            result = list_regions(max_depth=args.max_depth)
        elif args.command == "smart-controls":
            result = smart_controls(
                show=not args.no_show,
                max_depth=args.max_depth,
                include_values=args.values,
                include_disabled=not args.exclude_disabled,
                limit=args.limit,
            )
        elif args.command == "set-smart-control":
            result = set_smart_control(
                query=args.query,
                path=args.path,
                value=args.value,
                action=args.action,
                role=args.role,
                show=not args.no_show,
                max_depth=args.max_depth,
                include_tabs=not args.exclude_tabs,
                allow_first=args.allow_first,
            )
        elif args.command == "library-search":
            result = library_search(
                args.query,
                show=not args.no_show,
                limit=args.limit,
                result_depth=args.result_depth,
            )
        elif args.command == "library-select":
            result = library_select(
                args.query,
                name=args.name,
                index=args.index,
                allow_first=args.allow_first,
                show=not args.no_show,
            )
        elif args.command == "loop-search":
            result = loop_search(args.query, show=not args.no_show)
        elif args.command == "loop-select":
            result = loop_select(
                args.query,
                index=args.index,
                show=not args.no_show,
                row_height=args.row_height,
                x_offset=args.x_offset,
            )
        elif args.command == "loop-drag":
            result = loop_drag(
                args.query,
                index=args.index,
                destination_x=args.destination_x,
                destination_y=args.destination_y,
                show=not args.no_show,
                row_height=args.row_height,
                x_offset=args.x_offset,
                delay_seconds=args.delay,
                acknowledge_content_install_risk=args.acknowledge_content_install_risk,
            )
        elif args.command == "screenshot":
            result = screenshot(args.output)
        elif args.command == "annotated-screenshot":
            result = annotated_screenshot(
                args.output,
                map_output_path=args.map_output,
                max_depth=args.max_depth,
                include_grid=not args.no_grid,
                grid_step=args.grid_step,
                include_disabled=args.include_disabled,
                limit=args.limit,
            )
        elif args.command == "window-rect":
            result = window_rect()
        elif args.command == "window-click":
            result = click_window(args.x, args.y)
        elif args.command == "window-drag":
            result = drag_window(args.x1, args.y1, args.x2, args.y2, delay_seconds=args.delay)
        elif args.command == "type-text":
            result = type_text(args.text)
        elif args.command == "shortcut":
            result = shortcut(args.key, args.mod)
        elif args.command == "transport":
            result = transport(args.action)
        elif args.command == "midi-info":
            result = midi_info(args.path)
        elif args.command == "audio-info":
            result = audio_info(args.path)
        elif args.command == "tab-to-midi":
            tab_text = args.tab
            if args.tab_file:
                tab_text = Path(args.tab_file).expanduser().read_text(encoding="utf-8")
            result = create_midi_from_tab(
                tab_text or "",
                args.output,
                bpm=args.bpm,
                open_in_garageband=args.open,
                track_name=args.track_name,
                ticks_per_column=args.ticks_per_column,
                sustain_columns=args.sustain_columns,
                capo=args.capo,
                tuning=args.tuning,
            )
        elif args.command == "arrange-tab-to-midi":
            tab_text = args.tab
            if args.tab_file:
                tab_text = Path(args.tab_file).expanduser().read_text(encoding="utf-8")
            result = create_arranged_midi_from_tab(
                tab_text or "",
                args.output,
                bpm=args.bpm,
                open_in_garageband=args.open,
                title=args.title,
                ticks_per_column=args.ticks_per_column,
                sustain_columns=args.sustain_columns,
                include_bass=not args.no_bass,
                include_drums=not args.no_drums,
                style=args.style,
                repeat_count=args.repeat_count,
                capo=args.capo,
                tuning=args.tuning,
            )
        elif args.command == "image-to-tab":
            result = extract_tab_from_image(
                image_path=args.image,
                image_url=args.url,
                download_dir=args.download_dir,
            )
        elif args.command == "image-to-midi":
            result = create_midi_from_tab_image(
                args.output,
                image_path=args.image,
                image_url=args.url,
                download_dir=args.download_dir,
                bpm=args.bpm,
                open_in_garageband=args.open,
                track_name=args.track_name,
                ticks_per_column=args.ticks_per_column,
                sustain_columns=args.sustain_columns,
                capo=args.capo,
                tuning=args.tuning,
            )
        elif args.command == "arrange-image-to-midi":
            result = create_arranged_midi_from_tab_image(
                args.output,
                image_path=args.image,
                image_url=args.url,
                download_dir=args.download_dir,
                bpm=args.bpm,
                open_in_garageband=args.open,
                title=args.title,
                ticks_per_column=args.ticks_per_column,
                sustain_columns=args.sustain_columns,
                include_bass=not args.no_bass,
                include_drums=not args.no_drums,
                style=args.style,
                repeat_count=args.repeat_count,
                capo=args.capo,
                tuning=args.tuning,
            )
        elif args.command == "score-to-midi":
            result = create_midi_from_score(
                args.score,
                args.output,
                bpm=args.bpm,
                velocity=args.velocity,
                open_in_garageband=args.open,
            )
        elif args.command == "score-spec-schema":
            result = score_spec_schema()
        elif args.command == "score-spec-validate":
            result = validate_score_spec(_load_json_arg(args.json, args.file))
        elif args.command == "score-spec-to-midi":
            source_path = str(Path(args.file).expanduser().resolve()) if args.file else None
            result = create_midi_from_score_spec(
                _load_json_arg(args.json, args.file),
                args.output,
                velocity=args.velocity,
                open_in_garageband=args.open,
                source=source_path,
            )
        elif args.command == "make-from-tab":
            result = make_from_tab(
                output_dir=args.output_dir,
                name=args.name,
                tab_text=args.tab,
                tab_file=args.tab_file,
                image_path=args.image,
                image_url=args.url,
                bpm=args.bpm,
                open_in_garageband=not args.no_open,
                show_library=args.show_library,
                show_smart_controls=args.show_smart_controls,
                show_loop_browser=args.show_loop_browser,
                master_volume=args.master_volume,
                screenshot_output=args.screenshot_output,
                snapshot_depth=args.snapshot_depth,
                discard_unsaved=args.discard_unsaved,
                arrange=args.arrange,
                include_bass=not args.no_bass,
                include_drums=not args.no_drums,
                arrangement_style=args.style,
                repeat_count=args.repeat_count,
                capo=args.capo,
                tuning=args.tuning,
                export_output=args.export_output,
                export_format=args.export_format,
                export_quality=args.export_quality,
                export_include_cycle=args.export_include_cycle,
                export_overwrite=args.export_overwrite,
                export_timeout_seconds=args.export_timeout,
            )
        elif args.command == "make-from-score":
            result = make_from_score(
                score_path=args.score,
                output_dir=args.output_dir,
                name=args.name,
                bpm=args.bpm,
                velocity=args.velocity,
                open_in_garageband=not args.no_open,
                show_library=args.show_library,
                show_smart_controls=args.show_smart_controls,
                show_loop_browser=args.show_loop_browser,
                screenshot_output=args.screenshot_output,
                snapshot_depth=args.snapshot_depth,
                discard_unsaved=args.discard_unsaved,
                export_output=args.export_output,
                export_format=args.export_format,
                export_quality=args.export_quality,
                export_include_cycle=args.export_include_cycle,
                export_overwrite=args.export_overwrite,
                export_timeout_seconds=args.export_timeout,
            )
        elif args.command == "make-from-score-spec":
            source_path = str(Path(args.file).expanduser().resolve()) if args.file else None
            result = make_from_score_spec(
                score_spec=_load_json_arg(args.json, args.file),
                output_dir=args.output_dir,
                name=args.name,
                velocity=args.velocity,
                open_in_garageband=not args.no_open,
                show_library=args.show_library,
                show_smart_controls=args.show_smart_controls,
                show_loop_browser=args.show_loop_browser,
                screenshot_output=args.screenshot_output,
                snapshot_depth=args.snapshot_depth,
                discard_unsaved=args.discard_unsaved,
                export_output=args.export_output,
                export_format=args.export_format,
                export_quality=args.export_quality,
                export_include_cycle=args.export_include_cycle,
                export_overwrite=args.export_overwrite,
                export_timeout_seconds=args.export_timeout,
                source=source_path,
            )
        elif args.command == "make-music":
            result = make_music(
                output_dir=args.output_dir,
                name=args.name,
                score_path=args.score,
                score_json=args.score_json,
                score_json_file=args.score_json_file,
                tab_text=args.tab,
                tab_file=args.tab_file,
                image_path=args.image,
                image_url=args.url,
                bpm=args.bpm,
                velocity=args.velocity,
                open_in_garageband=not args.no_open,
                show_library=args.show_library,
                show_smart_controls=args.show_smart_controls,
                show_loop_browser=args.show_loop_browser,
                master_volume=args.master_volume,
                screenshot_output=args.screenshot_output,
                snapshot_depth=args.snapshot_depth,
                discard_unsaved=args.discard_unsaved,
                arrange=not args.no_arrange,
                include_bass=not args.no_bass,
                include_drums=not args.no_drums,
                arrangement_style=args.style,
                repeat_count=args.repeat_count,
                capo=args.capo,
                tuning=args.tuning,
                export_output=args.export_output,
                export_format=args.export_format,
                export_quality=args.export_quality,
                export_include_cycle=args.export_include_cycle,
                export_overwrite=args.export_overwrite,
                export_timeout_seconds=args.export_timeout,
            )
        elif args.command == "export-dialog":
            result = open_export_dialog()
        elif args.command == "export-song":
            result = export_song(
                args.output,
                format_name=args.format,
                quality=args.quality,
                include_cycle=args.include_cycle,
                overwrite=args.overwrite,
                timeout_seconds=args.timeout,
            )
        else:
            raise GarageBandError(f"Unknown command: {args.command}")
        payload = ok(result)
        print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps(fail(exc), indent=2 if args.pretty else None, sort_keys=True), file=sys.stderr)
        return 1


def shell_command_for_readme() -> str:
    here = Path(__file__).resolve().parents[1]
    return shlex.join([sys.executable, str(here / "garageband_cli.py")])

#!/usr/bin/env python3
"""Minimal MCP stdio server for GarageBand Bridge.

This intentionally avoids third-party dependencies. It implements the MCP
methods most clients need: initialize, tools/list, and tools/call.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from garageband_bridge import __version__
from garageband_bridge import core


PROTOCOL_VERSION = "2024-11-05"


def _tool(name: str, description: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "description": description, "inputSchema": schema}


TOOLS = [
    _tool(
        "garageband_status",
        "Report whether GarageBand is installed/running and summarize visible windows.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _tool(
        "garageband_capabilities",
        "Return a live feature map, safe operating loop, limits, and recipe catalog for LLM GarageBand control.",
        {
            "type": "object",
            "properties": {"include_live": {"type": "boolean", "default": True}},
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_self_test",
        "Run a non-destructive bridge health check and write proof artifacts such as a generated MIDI and screenshot.",
        {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string"},
                "include_ui": {"type": "boolean", "default": True},
                "include_screenshot": {"type": "boolean", "default": True},
                "image_path": {"type": "string"},
                "image_url": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_recipes",
        "Return tested high-level workflows for common LLM GarageBand tasks.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _tool(
        "garageband_run_plan",
        "Execute a JSON sequence of GarageBand bridge actions with per-step structured results.",
        {
            "type": "object",
            "properties": {
                "plan": {
                    "description": "A plan object with steps/actions, or a raw list of step objects. Each step has action and optional args.",
                    "oneOf": [{"type": "object"}, {"type": "array"}],
                },
                "stop_on_error": {"type": "boolean", "default": True},
            },
            "required": ["plan"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_launch",
        "Launch GarageBand and bring it forward.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _tool(
        "garageband_open",
        "Open a GarageBand project or supported audio file in GarageBand.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_render_preview",
        "Call GarageBand's native renderPreview AppleScript command.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_dismiss_save_prompt",
        "Dismiss GarageBand's save confirmation prompt. It only clicks Don't Save when discard is true.",
        {
            "type": "object",
            "properties": {"discard": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_list_menus",
        "List GarageBand menu items with enabled/disabled state.",
        {
            "type": "object",
            "properties": {"enabled_only": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_menu_map",
        "Recursively list GarageBand menu paths, including submenu paths, enabled state, and child counts.",
        {
            "type": "object",
            "properties": {
                "enabled_only": {"type": "boolean", "default": False},
                "max_depth": {"type": "integer", "default": 5, "minimum": 1, "maximum": 8},
                "top_menu": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_find_menu_items",
        "Search recursive GarageBand menu paths before clicking an exact path.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "enabled_only": {"type": "boolean", "default": False},
                "max_depth": {"type": "integer", "default": 5, "minimum": 1, "maximum": 8},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
                "top_menu": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_click_menu",
        'Click a menu item by path, for example "File > Open..." or "View > Show Loop Browser".',
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_click_menu_search",
        "Search GarageBand menus and click the unique matching enabled menu item.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "enabled_only": {"type": "boolean", "default": True},
                "max_depth": {"type": "integer", "default": 5, "minimum": 1, "maximum": 8},
                "top_menu": {"type": "string"},
                "allow_first": {"type": "boolean", "default": False},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_ui_snapshot",
        "Inspect visible GarageBand windows and controls through macOS Accessibility.",
        {
            "type": "object",
            "properties": {"max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8}},
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_find_ui_elements",
        "Search visible GarageBand Accessibility elements by path, role, name, description, or position.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "role": {"type": "string"},
                "enabled_only": {"type": "boolean", "default": False},
                "max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_ui_controls_summary",
        "Return a compact summary of visible actionable GarageBand controls and role counts.",
        {
            "type": "object",
            "properties": {"max_depth": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8}},
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_wait_ui",
        "Wait until a visible GarageBand Accessibility element matching a query appears.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "role": {"type": "string"},
                "enabled_only": {"type": "boolean", "default": False},
                "max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
                "timeout_seconds": {"type": "number", "default": 10},
                "interval_seconds": {"type": "number", "default": 0.5},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 500},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_click_ui",
        "Click the first visible GarageBand UI control matching a name and optional Accessibility role.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "role": {"type": "string"},
                "exact": {"type": "boolean", "default": False},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_click_ui_search",
        "Search visible GarageBand controls and click the unique matching enabled UI element.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "role": {"type": "string"},
                "enabled_only": {"type": "boolean", "default": True},
                "max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
                "allow_first": {"type": "boolean", "default": False},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_ui_search_info",
        "Search visible GarageBand controls and read role/name/description/value for the unique matching UI element.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "role": {"type": "string"},
                "enabled_only": {"type": "boolean", "default": True},
                "max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
                "allow_first": {"type": "boolean", "default": False},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_ui_search_details",
        "Search visible GarageBand controls and return rich Accessibility details: actions, attributes, bounds, geometry, and value.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "role": {"type": "string"},
                "enabled_only": {"type": "boolean", "default": True},
                "max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
                "allow_first": {"type": "boolean", "default": False},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_ui_search_set",
        "Search visible GarageBand controls and set the unique matching slider or editable field when Accessibility supports it.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "value": {"type": "string"},
                "role": {"type": "string"},
                "enabled_only": {"type": "boolean", "default": True},
                "max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
                "allow_first": {"type": "boolean", "default": False},
            },
            "required": ["query", "value"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_ui_search_action",
        "Search visible GarageBand controls and perform an Accessibility action such as increment, decrement, or press on the unique match.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "action": {
                    "type": "string",
                    "description": "increment, decrement, press, AXIncrement, AXDecrement, or AXPress.",
                },
                "role": {"type": "string"},
                "enabled_only": {"type": "boolean", "default": True},
                "max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
                "allow_first": {"type": "boolean", "default": False},
            },
            "required": ["query", "action"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_ui_info_path",
        "Read role/name/description/value for a GarageBand UI element path returned by garageband_ui_snapshot.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_ui_details_path",
        "Return rich Accessibility details for a GarageBand UI path, including actions, attributes, bounds, geometry, and value.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_click_ui_path",
        "Click a GarageBand UI element by path returned by garageband_ui_snapshot.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_set_ui_value",
        "Set the value of a GarageBand UI element by path, useful for sliders and editable fields when supported by Accessibility.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["path", "value"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_ui_action_path",
        "Perform an Accessibility action such as increment, decrement, or press on a GarageBand UI path.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "action": {
                    "type": "string",
                    "description": "increment, decrement, press, AXIncrement, AXDecrement, or AXPress.",
                },
            },
            "required": ["path", "action"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_project_settings",
        "Read the current GarageBand project's tempo, key signature, and time signature from the visible LCD controls.",
        {
            "type": "object",
            "properties": {
                "max_depth": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_project_setting_options",
        "Return built-in option catalogs for GarageBand project key signature and time signature popups.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _tool(
        "garageband_set_project_settings",
        "Set the current GarageBand project's tempo, key signature, or time signature through the visible LCD controls.",
        {
            "type": "object",
            "properties": {
                "tempo": {"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "integer"}]},
                "key_signature": {"type": "string"},
                "time_signature": {"type": "string"},
                "max_depth": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_list_tracks",
        "List visible GarageBand track headers and controls such as mute, solo, volume, pan, and name.",
        {
            "type": "object",
            "properties": {
                "max_depth": {"type": "integer", "default": 7, "minimum": 1, "maximum": 8},
                "include_values": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_select_track",
        "Select a visible GarageBand track by index or visible name, so Library and Smart Controls act on that track.",
        {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "minimum": 1},
                "name": {"type": "string"},
                "max_depth": {"type": "integer", "default": 6, "minimum": 1, "maximum": 8},
                "x_offset": {"type": "number", "default": 110},
                "y_fraction": {"type": "number", "default": 0.5},
                "fast": {"type": "boolean", "default": False},
                "row_height": {"type": "number", "default": 129},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_set_track",
        "Set a visible GarageBand track header control: mute, solo, volume, pan, or visible track name.",
        {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "minimum": 1},
                "name": {"type": "string"},
                "mute": {"oneOf": [{"type": "boolean"}, {"type": "string"}, {"type": "integer"}]},
                "solo": {"oneOf": [{"type": "boolean"}, {"type": "string"}, {"type": "integer"}]},
                "volume": {"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "integer"}]},
                "pan": {"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "integer"}]},
                "rename": {"type": "string"},
                "max_depth": {"type": "integer", "default": 7, "minimum": 1, "maximum": 8},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_list_regions",
        "List visible GarageBand MIDI/audio regions and region edit handles.",
        {
            "type": "object",
            "properties": {
                "max_depth": {"type": "integer", "default": 8, "minimum": 1, "maximum": 8},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_smart_controls",
        "Show GarageBand's Smart Controls panel and list visible Track/Master/Controls/EQ tabs plus actionable Smart Controls.",
        {
            "type": "object",
            "properties": {
                "show": {"type": "boolean", "default": True},
                "max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
                "include_values": {"type": "boolean", "default": False},
                "include_disabled": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "default": 200, "minimum": 1, "maximum": 500},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_set_smart_control",
        "Press or set a visible GarageBand Smart Control by label/path after inspecting garageband_smart_controls.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "value": {"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "integer"}, {"type": "boolean"}]},
                "action": {"type": "string"},
                "role": {"type": "string"},
                "show": {"type": "boolean", "default": True},
                "max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
                "include_tabs": {"type": "boolean", "default": True},
                "allow_first": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_library_search",
        "Show GarageBand's Library, optionally set the Library search text, and list visible Library results.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "show": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
                "result_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_library_select",
        "Search GarageBand's Library and press one visible Library result by name or index.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "name": {"type": "string"},
                "index": {"type": "integer", "minimum": 1},
                "allow_first": {"type": "boolean", "default": False},
                "show": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_loop_search",
        "Show GarageBand's Apple Loops browser, optionally set the search text, and report filtered result counts and visible rows.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "show": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_loop_select",
        "Search GarageBand's Apple Loops browser and select a visible loop row by index.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "index": {"type": "integer", "default": 1, "minimum": 1},
                "show": {"type": "boolean", "default": True},
                "row_height": {"type": "number", "default": 24},
                "x_offset": {"type": "number", "default": 70},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_loop_drag",
        "Search GarageBand's Apple Loops browser and guarded-drag a visible row into the timeline. Requires acknowledging that downloadable rows can open Apple's sound/content installer.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "index": {"type": "integer", "default": 1, "minimum": 1},
                "destination_x": {"type": "number", "default": 390},
                "destination_y": {"type": "number", "default": 195},
                "show": {"type": "boolean", "default": True},
                "row_height": {"type": "number", "default": 24},
                "x_offset": {"type": "number", "default": 70},
                "delay_seconds": {"type": "number", "default": 0.7},
                "acknowledge_content_install_risk": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_screenshot",
        "Capture the visible GarageBand window to a PNG file.",
        {
            "type": "object",
            "properties": {"output_path": {"type": "string"}},
            "required": ["output_path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_annotated_screenshot",
        "Capture GarageBand to an annotated PNG with numbered UI targets plus a JSON click map of window coordinates and Accessibility paths.",
        {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "map_output_path": {"type": "string"},
                "max_depth": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
                "include_grid": {"type": "boolean", "default": True},
                "grid_step": {"type": "integer", "default": 100, "minimum": 25, "maximum": 500},
                "include_disabled": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 120, "minimum": 1, "maximum": 500},
            },
            "required": ["output_path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_window_rect",
        "Return the visible GarageBand window rectangle in macOS screen points.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _tool(
        "garageband_window_click",
        "Click a point inside the GarageBand window using window-relative macOS point coordinates.",
        {
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_window_drag",
        "Drag between two points inside the GarageBand window using window-relative macOS point coordinates.",
        {
            "type": "object",
            "properties": {
                "x1": {"type": "number"},
                "y1": {"type": "number"},
                "x2": {"type": "number"},
                "y2": {"type": "number"},
                "delay_seconds": {"type": "number", "default": 0.2},
            },
            "required": ["x1", "y1", "x2", "y2"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_type_text",
        "Type text into the currently focused GarageBand UI element.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_shortcut",
        "Send a keyboard shortcut to GarageBand.",
        {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "modifiers": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["command", "shift", "option", "control"]},
                    "default": [],
                },
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_transport",
        "Send a common GarageBand action such as play_stop, record, rewind, save, undo, redo, copy, paste.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": sorted(core.TRANSPORT_SHORTCUTS),
                }
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_export_dialog",
        "Open GarageBand's Share > Export Song to Disk dialog for the current project.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _tool(
        "garageband_export_song",
        "Export the current GarageBand song to AAC, MP3, AIFF, or WAVE by driving GarageBand's export dialog.",
        {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "format": {"type": "string", "enum": sorted(core.EXPORT_FORMAT_EXTENSIONS)},
                "quality": {"type": "string"},
                "include_cycle": {"oneOf": [{"type": "boolean"}, {"type": "string"}, {"type": "integer"}]},
                "overwrite": {"type": "boolean", "default": False},
                "timeout_seconds": {"type": "number", "default": 180},
            },
            "required": ["output_path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_audio_info",
        "Inspect an exported audio file and report non-empty status, format, duration, channels, sample rate, and frame count when available.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_midi_info",
        "Inspect a MIDI file generated for GarageBand and report format, track names, channels, and note counts.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_tab_to_midi",
        "Convert six-line ASCII guitar tab text into a GarageBand-importable MIDI file, optionally opening it in GarageBand.",
        {
            "type": "object",
            "properties": {
                "tab_text": {
                    "type": "string",
                    "description": "Six-line guitar tab text, such as e|--0--| through E|--0--|.",
                },
                "output_path": {"type": "string"},
                "bpm": {"type": "integer", "minimum": 20, "maximum": 300, "description": "Override detected tab tempo."},
                "track_name": {"type": "string", "default": "GarageBand Bridge Tab"},
                "ticks_per_column": {"type": "integer", "default": 120},
                "sustain_columns": {"type": "integer", "default": 2},
                "capo": {"type": "integer", "minimum": 0, "maximum": core.tab_midi.MAX_CAPO},
                "tuning": {"type": "string", "description": "Preset or six notes, such as drop d or D A D G B E."},
                "open_in_garageband": {"type": "boolean", "default": False},
            },
            "required": ["tab_text", "output_path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_arrange_tab_to_midi",
        "Convert six-line ASCII guitar tab into a GarageBand-importable guitar/bass/drums arrangement MIDI.",
        {
            "type": "object",
            "properties": {
                "tab_text": {"type": "string"},
                "output_path": {"type": "string"},
                "bpm": {"type": "integer", "minimum": 20, "maximum": 300, "description": "Override detected tab tempo."},
                "title": {"type": "string", "default": "GarageBand Bridge Arrangement"},
                "ticks_per_column": {"type": "integer", "default": 120},
                "sustain_columns": {"type": "integer", "default": 2},
                "include_bass": {"type": "boolean", "default": True},
                "include_drums": {"type": "boolean", "default": True},
                "style": {"type": "string", "default": "rock", "enum": sorted(core.tab_midi.ARRANGEMENT_STYLES)},
                "repeat_count": {"type": "integer", "default": 1, "minimum": 1, "maximum": 32},
                "capo": {"type": "integer", "minimum": 0, "maximum": core.tab_midi.MAX_CAPO},
                "tuning": {"type": "string", "description": "Preset or six notes, such as drop d or D A D G B E."},
                "open_in_garageband": {"type": "boolean", "default": False},
            },
            "required": ["tab_text", "output_path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_image_to_tab",
        "Use macOS Vision OCR to extract six-line guitar tab text from a local image path or image URL.",
        {
            "type": "object",
            "properties": {
                "image_path": {"type": "string"},
                "image_url": {"type": "string"},
                "download_dir": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_image_to_midi",
        "Use macOS Vision OCR to extract tab from a local image or image URL, convert it to MIDI, and optionally open it in GarageBand.",
        {
            "type": "object",
            "properties": {
                "image_path": {"type": "string"},
                "image_url": {"type": "string"},
                "download_dir": {"type": "string"},
                "output_path": {"type": "string"},
                "bpm": {"type": "integer", "minimum": 20, "maximum": 300, "description": "Override detected OCR tab tempo."},
                "track_name": {"type": "string", "default": "GarageBand Bridge Image Tab"},
                "ticks_per_column": {"type": "integer", "default": 120},
                "sustain_columns": {"type": "integer", "default": 2},
                "capo": {"type": "integer", "minimum": 0, "maximum": core.tab_midi.MAX_CAPO},
                "tuning": {"type": "string", "description": "Override OCR-detected tuning."},
                "open_in_garageband": {"type": "boolean", "default": False},
            },
            "required": ["output_path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_arrange_image_to_midi",
        "Use macOS Vision OCR to extract tab from a local image or image URL, then create a guitar/bass/drums arrangement MIDI.",
        {
            "type": "object",
            "properties": {
                "image_path": {"type": "string"},
                "image_url": {"type": "string"},
                "download_dir": {"type": "string"},
                "output_path": {"type": "string"},
                "bpm": {"type": "integer", "minimum": 20, "maximum": 300, "description": "Override detected OCR tab tempo."},
                "title": {"type": "string", "default": "GarageBand Bridge Arrangement"},
                "ticks_per_column": {"type": "integer", "default": 120},
                "sustain_columns": {"type": "integer", "default": 2},
                "include_bass": {"type": "boolean", "default": True},
                "include_drums": {"type": "boolean", "default": True},
                "style": {"type": "string", "default": "rock", "enum": sorted(core.tab_midi.ARRANGEMENT_STYLES)},
                "repeat_count": {"type": "integer", "default": 1, "minimum": 1, "maximum": 32},
                "capo": {"type": "integer", "minimum": 0, "maximum": core.tab_midi.MAX_CAPO},
                "tuning": {"type": "string", "description": "Override OCR-detected tuning."},
                "open_in_garageband": {"type": "boolean", "default": False},
            },
            "required": ["output_path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_score_to_midi",
        "Convert a MusicXML band/full score into a multi-track GarageBand-importable MIDI file, optionally opening it in GarageBand.",
        {
            "type": "object",
            "properties": {
                "score_path": {"type": "string"},
                "output_path": {"type": "string"},
                "bpm": {"type": "integer", "minimum": 20, "maximum": 300},
                "velocity": {"type": "integer", "default": core.score_midi.DEFAULT_VELOCITY, "minimum": 1, "maximum": 127},
                "open_in_garageband": {"type": "boolean", "default": False},
            },
            "required": ["score_path", "output_path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_score_spec_schema",
        "Return the LLM-friendly JSON score spec schema, examples, supported pitch/drum names, and timing rules.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _tool(
        "garageband_validate_score_spec",
        "Validate an LLM-friendly JSON band score spec before generating MIDI or opening GarageBand.",
        {
            "type": "object",
            "properties": {
                "score_spec": {"type": "object"},
            },
            "required": ["score_spec"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_score_spec_to_midi",
        "Convert an LLM-friendly JSON band score spec into a multi-track GarageBand-importable MIDI file, optionally opening it in GarageBand.",
        {
            "type": "object",
            "properties": {
                "score_spec": {
                    "type": "object",
                    "description": "JSON score object with title/bpm/time_signature/parts. Part notes use beat-based start/duration and pitches like C4, F#3, or drum names.",
                },
                "output_path": {"type": "string"},
                "velocity": {"type": "integer", "default": core.score_midi.DEFAULT_VELOCITY, "minimum": 1, "maximum": 127},
                "open_in_garageband": {"type": "boolean", "default": False},
            },
            "required": ["score_spec", "output_path"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_make_music",
        "Unified high-level recipe: accept MusicXML, JSON score spec, tab text/file, or tab image/URL, create music, open GarageBand, optionally screenshot and export audio.",
        {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string"},
                "name": {"type": "string"},
                "score_path": {"type": "string"},
                "score_spec": {"type": "object"},
                "score_json": {"type": "string"},
                "score_json_file": {"type": "string"},
                "tab_text": {"type": "string"},
                "tab_file": {"type": "string"},
                "image_path": {"type": "string"},
                "image_url": {"type": "string"},
                "bpm": {"type": "integer", "minimum": 20, "maximum": 300},
                "velocity": {"type": "integer", "default": core.score_midi.DEFAULT_VELOCITY, "minimum": 1, "maximum": 127},
                "open_in_garageband": {"type": "boolean", "default": True},
                "show_library": {"type": "boolean", "default": False},
                "show_smart_controls": {"type": "boolean", "default": False},
                "show_loop_browser": {"type": "boolean", "default": False},
                "master_volume": {"type": "string"},
                "screenshot_output": {"type": "string"},
                "snapshot_depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 8},
                "discard_unsaved": {"type": "boolean", "default": False},
                "arrange": {"type": "boolean", "default": True},
                "include_bass": {"type": "boolean", "default": True},
                "include_drums": {"type": "boolean", "default": True},
                "arrangement_style": {"type": "string", "default": "rock", "enum": sorted(core.tab_midi.ARRANGEMENT_STYLES)},
                "repeat_count": {"type": "integer", "default": 1, "minimum": 1, "maximum": 32},
                "capo": {"type": "integer", "minimum": 0, "maximum": core.tab_midi.MAX_CAPO},
                "tuning": {"type": "string", "description": "Preset or six notes for tab/image sources."},
                "export_output": {"type": "string"},
                "export_format": {"type": "string", "enum": sorted(core.EXPORT_FORMAT_EXTENSIONS)},
                "export_quality": {"type": "string"},
                "export_include_cycle": {"oneOf": [{"type": "boolean"}, {"type": "string"}, {"type": "integer"}]},
                "export_overwrite": {"type": "boolean", "default": False},
                "export_timeout_seconds": {"type": "number", "default": 180},
            },
            "required": ["output_dir"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_make_from_score",
        "High-level recipe: accept a MusicXML full score, create multi-track MIDI, open it in GarageBand, optionally show panels, screenshot, and export audio.",
        {
            "type": "object",
            "properties": {
                "score_path": {"type": "string"},
                "output_dir": {"type": "string"},
                "name": {"type": "string"},
                "bpm": {"type": "integer", "minimum": 20, "maximum": 300},
                "velocity": {"type": "integer", "default": core.score_midi.DEFAULT_VELOCITY, "minimum": 1, "maximum": 127},
                "open_in_garageband": {"type": "boolean", "default": True},
                "show_library": {"type": "boolean", "default": False},
                "show_smart_controls": {"type": "boolean", "default": False},
                "show_loop_browser": {"type": "boolean", "default": False},
                "screenshot_output": {"type": "string"},
                "snapshot_depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 8},
                "discard_unsaved": {"type": "boolean", "default": False},
                "export_output": {"type": "string"},
                "export_format": {"type": "string", "enum": sorted(core.EXPORT_FORMAT_EXTENSIONS)},
                "export_quality": {"type": "string"},
                "export_include_cycle": {"oneOf": [{"type": "boolean"}, {"type": "string"}, {"type": "integer"}]},
                "export_overwrite": {"type": "boolean", "default": False},
                "export_timeout_seconds": {"type": "number", "default": 180},
            },
            "required": ["score_path", "output_dir"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_make_from_score_spec",
        "High-level recipe: accept an LLM-friendly JSON band score spec, create multi-track MIDI, open it in GarageBand, optionally screenshot and export audio.",
        {
            "type": "object",
            "properties": {
                "score_spec": {"type": "object"},
                "output_dir": {"type": "string"},
                "name": {"type": "string"},
                "velocity": {"type": "integer", "default": core.score_midi.DEFAULT_VELOCITY, "minimum": 1, "maximum": 127},
                "open_in_garageband": {"type": "boolean", "default": True},
                "show_library": {"type": "boolean", "default": False},
                "show_smart_controls": {"type": "boolean", "default": False},
                "show_loop_browser": {"type": "boolean", "default": False},
                "screenshot_output": {"type": "string"},
                "snapshot_depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 8},
                "discard_unsaved": {"type": "boolean", "default": False},
                "export_output": {"type": "string"},
                "export_format": {"type": "string", "enum": sorted(core.EXPORT_FORMAT_EXTENSIONS)},
                "export_quality": {"type": "string"},
                "export_include_cycle": {"oneOf": [{"type": "boolean"}, {"type": "string"}, {"type": "integer"}]},
                "export_overwrite": {"type": "boolean", "default": False},
                "export_timeout_seconds": {"type": "number", "default": 180},
            },
            "required": ["score_spec", "output_dir"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_make_from_tab",
        "High-level recipe: accept tab text/file/image/URL, create MIDI, open it in GarageBand, optionally show panels, set master volume, snapshot, screenshot, and export audio.",
        {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string"},
                "name": {"type": "string", "default": "garageband-tab-song"},
                "tab_text": {"type": "string"},
                "tab_file": {"type": "string"},
                "image_path": {"type": "string"},
                "image_url": {"type": "string"},
                "bpm": {"type": "integer", "minimum": 20, "maximum": 300, "description": "Override detected tab/image tempo."},
                "open_in_garageband": {"type": "boolean", "default": True},
                "show_library": {"type": "boolean", "default": False},
                "show_smart_controls": {"type": "boolean", "default": False},
                "show_loop_browser": {"type": "boolean", "default": False},
                "master_volume": {"type": "string"},
                "screenshot_output": {"type": "string"},
                "snapshot_depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 8},
                "discard_unsaved": {"type": "boolean", "default": False},
                "arrange": {"type": "boolean", "default": False},
                "include_bass": {"type": "boolean", "default": True},
                "include_drums": {"type": "boolean", "default": True},
                "arrangement_style": {"type": "string", "default": "rock", "enum": sorted(core.tab_midi.ARRANGEMENT_STYLES)},
                "repeat_count": {"type": "integer", "default": 1, "minimum": 1, "maximum": 32},
                "capo": {"type": "integer", "minimum": 0, "maximum": core.tab_midi.MAX_CAPO},
                "tuning": {"type": "string", "description": "Preset or six notes for tab/image sources."},
                "export_output": {"type": "string"},
                "export_format": {"type": "string", "enum": sorted(core.EXPORT_FORMAT_EXTENSIONS)},
                "export_quality": {"type": "string"},
                "export_include_cycle": {"oneOf": [{"type": "boolean"}, {"type": "string"}, {"type": "integer"}]},
                "export_overwrite": {"type": "boolean", "default": False},
                "export_timeout_seconds": {"type": "number", "default": 180},
            },
            "required": ["output_dir"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "garageband_permissions",
        "Explain the macOS permissions needed for GarageBand automation.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
]


def _content(data: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, indent=2, sort_keys=True),
            }
        ]
    }


def _call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    calls: dict[str, Callable[[], Any]] = {
        "garageband_status": lambda: core.status(),
        "garageband_capabilities": lambda: core.capabilities(include_live=args.get("include_live", True)),
        "garageband_self_test": lambda: core.self_test(
            output_dir=args.get("output_dir"),
            include_ui=args.get("include_ui", True),
            include_screenshot=args.get("include_screenshot", True),
            image_path=args.get("image_path"),
            image_url=args.get("image_url"),
        ),
        "garageband_recipes": lambda: core.recipes(),
        "garageband_run_plan": lambda: core.run_plan(
            args["plan"],
            stop_on_error=args.get("stop_on_error", True),
        ),
        "garageband_launch": lambda: core.launch(),
        "garageband_open": lambda: core.open_path(args["path"]),
        "garageband_render_preview": lambda: core.render_preview(args.get("path")),
        "garageband_dismiss_save_prompt": lambda: core.dismiss_save_prompt(discard=args.get("discard", False)),
        "garageband_list_menus": lambda: core.list_menus(include_disabled=not args.get("enabled_only", False)),
        "garageband_menu_map": lambda: core.menu_map(
            include_disabled=not args.get("enabled_only", False),
            max_depth=args.get("max_depth", 5),
            top_menu=args.get("top_menu"),
        ),
        "garageband_find_menu_items": lambda: core.find_menu_items(
            args["query"],
            enabled_only=args.get("enabled_only", False),
            max_depth=args.get("max_depth", 5),
            limit=args.get("limit", 50),
            top_menu=args.get("top_menu"),
        ),
        "garageband_click_menu": lambda: core.click_menu(args["path"]),
        "garageband_click_menu_search": lambda: core.click_menu_search(
            args["query"],
            enabled_only=args.get("enabled_only", True),
            max_depth=args.get("max_depth", 5),
            top_menu=args.get("top_menu"),
            allow_first=args.get("allow_first", False),
        ),
        "garageband_ui_snapshot": lambda: core.ui_snapshot(args.get("max_depth", 4)),
        "garageband_find_ui_elements": lambda: core.find_ui_elements(
            args["query"],
            role=args.get("role"),
            enabled_only=args.get("enabled_only", False),
            max_depth=args.get("max_depth", 4),
            limit=args.get("limit", 50),
        ),
        "garageband_ui_controls_summary": lambda: core.ui_controls_summary(
            max_depth=args.get("max_depth", 3),
        ),
        "garageband_wait_ui": lambda: core.wait_ui(
            args["query"],
            role=args.get("role"),
            enabled_only=args.get("enabled_only", False),
            max_depth=args.get("max_depth", 4),
            timeout_seconds=args.get("timeout_seconds", 10.0),
            interval_seconds=args.get("interval_seconds", 0.5),
            limit=args.get("limit", 10),
        ),
        "garageband_click_ui": lambda: core.click_ui(
            args["name"],
            role=args.get("role"),
            exact=args.get("exact", False),
        ),
        "garageband_click_ui_search": lambda: core.click_ui_search(
            args["query"],
            role=args.get("role"),
            enabled_only=args.get("enabled_only", True),
            max_depth=args.get("max_depth", 4),
            allow_first=args.get("allow_first", False),
        ),
        "garageband_ui_search_info": lambda: core.ui_info_search(
            args["query"],
            role=args.get("role"),
            enabled_only=args.get("enabled_only", True),
            max_depth=args.get("max_depth", 4),
            allow_first=args.get("allow_first", False),
        ),
        "garageband_ui_search_details": lambda: core.ui_details_search(
            args["query"],
            role=args.get("role"),
            enabled_only=args.get("enabled_only", True),
            max_depth=args.get("max_depth", 4),
            allow_first=args.get("allow_first", False),
        ),
        "garageband_ui_search_set": lambda: core.set_ui_value_search(
            args["query"],
            args["value"],
            role=args.get("role"),
            enabled_only=args.get("enabled_only", True),
            max_depth=args.get("max_depth", 4),
            allow_first=args.get("allow_first", False),
        ),
        "garageband_ui_search_action": lambda: core.perform_ui_action_search(
            args["query"],
            args["action"],
            role=args.get("role"),
            enabled_only=args.get("enabled_only", True),
            max_depth=args.get("max_depth", 4),
            allow_first=args.get("allow_first", False),
        ),
        "garageband_ui_info_path": lambda: core.ui_info_path(args["path"]),
        "garageband_ui_details_path": lambda: core.ui_details_path(args["path"]),
        "garageband_click_ui_path": lambda: core.click_ui_path(args["path"]),
        "garageband_set_ui_value": lambda: core.set_ui_value_path(args["path"], args["value"]),
        "garageband_ui_action_path": lambda: core.perform_ui_action_path(args["path"], args["action"]),
        "garageband_project_settings": lambda: core.project_settings(
            max_depth=args.get("max_depth", 3),
        ),
        "garageband_project_setting_options": lambda: core.project_setting_options(),
        "garageband_set_project_settings": lambda: core.set_project_settings(
            tempo=args.get("tempo"),
            key_signature=args.get("key_signature"),
            time_signature=args.get("time_signature"),
            max_depth=args.get("max_depth", 3),
        ),
        "garageband_list_tracks": lambda: core.list_tracks(
            max_depth=args.get("max_depth", 7),
            include_values=args.get("include_values", True),
        ),
        "garageband_select_track": lambda: core.select_track(
            index=args.get("index"),
            name=args.get("name"),
            max_depth=args.get("max_depth", 6),
            x_offset=args.get("x_offset", 110),
            y_fraction=args.get("y_fraction", 0.5),
            fast=args.get("fast", False),
            row_height=args.get("row_height", 129),
        ),
        "garageband_set_track": lambda: core.set_track(
            index=args.get("index"),
            name=args.get("name"),
            mute=args.get("mute"),
            solo=args.get("solo"),
            volume=args.get("volume"),
            pan=args.get("pan"),
            rename=args.get("rename"),
            max_depth=args.get("max_depth", 7),
        ),
        "garageband_list_regions": lambda: core.list_regions(max_depth=args.get("max_depth", 8)),
        "garageband_smart_controls": lambda: core.smart_controls(
            show=args.get("show", True),
            max_depth=args.get("max_depth", 4),
            include_values=args.get("include_values", False),
            include_disabled=args.get("include_disabled", True),
            limit=args.get("limit", 200),
        ),
        "garageband_set_smart_control": lambda: core.set_smart_control(
            query=args.get("query"),
            path=args.get("path"),
            value=args.get("value"),
            action=args.get("action"),
            role=args.get("role"),
            show=args.get("show", True),
            max_depth=args.get("max_depth", 4),
            include_tabs=args.get("include_tabs", True),
            allow_first=args.get("allow_first", False),
        ),
        "garageband_library_search": lambda: core.library_search(
            args.get("query"),
            show=args.get("show", True),
            limit=args.get("limit", 50),
            result_depth=args.get("result_depth", 4),
        ),
        "garageband_library_select": lambda: core.library_select(
            args.get("query"),
            name=args.get("name"),
            index=args.get("index"),
            allow_first=args.get("allow_first", False),
            show=args.get("show", True),
        ),
        "garageband_loop_search": lambda: core.loop_search(
            args.get("query"),
            show=args.get("show", True),
        ),
        "garageband_loop_select": lambda: core.loop_select(
            args.get("query"),
            index=args.get("index", 1),
            show=args.get("show", True),
            row_height=args.get("row_height", 24),
            x_offset=args.get("x_offset", 70),
        ),
        "garageband_loop_drag": lambda: core.loop_drag(
            args.get("query"),
            index=args.get("index", 1),
            destination_x=args.get("destination_x", 390),
            destination_y=args.get("destination_y", 195),
            show=args.get("show", True),
            row_height=args.get("row_height", 24),
            x_offset=args.get("x_offset", 70),
            delay_seconds=args.get("delay_seconds", 0.7),
            acknowledge_content_install_risk=args.get("acknowledge_content_install_risk", False),
        ),
        "garageband_screenshot": lambda: core.screenshot(args["output_path"]),
        "garageband_annotated_screenshot": lambda: core.annotated_screenshot(
            args["output_path"],
            map_output_path=args.get("map_output_path"),
            max_depth=args.get("max_depth", 3),
            include_grid=args.get("include_grid", True),
            grid_step=args.get("grid_step", 100),
            include_disabled=args.get("include_disabled", False),
            limit=args.get("limit", 120),
        ),
        "garageband_window_rect": lambda: core.window_rect(),
        "garageband_window_click": lambda: core.click_window(args["x"], args["y"]),
        "garageband_window_drag": lambda: core.drag_window(
            args["x1"],
            args["y1"],
            args["x2"],
            args["y2"],
            delay_seconds=args.get("delay_seconds", 0.2),
        ),
        "garageband_type_text": lambda: core.type_text(args["text"]),
        "garageband_shortcut": lambda: core.shortcut(args["key"], args.get("modifiers", [])),
        "garageband_transport": lambda: core.transport(args["action"]),
        "garageband_export_dialog": lambda: core.open_export_dialog(),
        "garageband_export_song": lambda: core.export_song(
            args["output_path"],
            format_name=args.get("format"),
            quality=args.get("quality"),
            include_cycle=args.get("include_cycle"),
            overwrite=args.get("overwrite", False),
            timeout_seconds=args.get("timeout_seconds", 180),
        ),
        "garageband_audio_info": lambda: core.audio_info(args["path"]),
        "garageband_midi_info": lambda: core.midi_info(args["path"]),
        "garageband_tab_to_midi": lambda: core.create_midi_from_tab(
            args["tab_text"],
            args["output_path"],
            bpm=args.get("bpm"),
            open_in_garageband=args.get("open_in_garageband", False),
            track_name=args.get("track_name", "GarageBand Bridge Tab"),
            ticks_per_column=args.get("ticks_per_column", 120),
            sustain_columns=args.get("sustain_columns", 2),
            capo=args.get("capo"),
            tuning=args.get("tuning"),
        ),
        "garageband_arrange_tab_to_midi": lambda: core.create_arranged_midi_from_tab(
            args["tab_text"],
            args["output_path"],
            bpm=args.get("bpm"),
            open_in_garageband=args.get("open_in_garageband", False),
            title=args.get("title", "GarageBand Bridge Arrangement"),
            ticks_per_column=args.get("ticks_per_column", 120),
            sustain_columns=args.get("sustain_columns", 2),
            include_bass=args.get("include_bass", True),
            include_drums=args.get("include_drums", True),
            style=args.get("style", "rock"),
            repeat_count=args.get("repeat_count", 1),
            capo=args.get("capo"),
            tuning=args.get("tuning"),
        ),
        "garageband_image_to_tab": lambda: core.extract_tab_from_image(
            image_path=args.get("image_path"),
            image_url=args.get("image_url"),
            download_dir=args.get("download_dir"),
        ),
        "garageband_image_to_midi": lambda: core.create_midi_from_tab_image(
            args["output_path"],
            image_path=args.get("image_path"),
            image_url=args.get("image_url"),
            download_dir=args.get("download_dir"),
            bpm=args.get("bpm"),
            open_in_garageband=args.get("open_in_garageband", False),
            track_name=args.get("track_name", "GarageBand Bridge Image Tab"),
            ticks_per_column=args.get("ticks_per_column", 120),
            sustain_columns=args.get("sustain_columns", 2),
            capo=args.get("capo"),
            tuning=args.get("tuning"),
        ),
        "garageband_arrange_image_to_midi": lambda: core.create_arranged_midi_from_tab_image(
            args["output_path"],
            image_path=args.get("image_path"),
            image_url=args.get("image_url"),
            download_dir=args.get("download_dir"),
            bpm=args.get("bpm"),
            open_in_garageband=args.get("open_in_garageband", False),
            title=args.get("title", "GarageBand Bridge Arrangement"),
            ticks_per_column=args.get("ticks_per_column", 120),
            sustain_columns=args.get("sustain_columns", 2),
            include_bass=args.get("include_bass", True),
            include_drums=args.get("include_drums", True),
            style=args.get("style", "rock"),
            repeat_count=args.get("repeat_count", 1),
            capo=args.get("capo"),
            tuning=args.get("tuning"),
        ),
        "garageband_score_to_midi": lambda: core.create_midi_from_score(
            args["score_path"],
            args["output_path"],
            bpm=args.get("bpm"),
            velocity=args.get("velocity", core.score_midi.DEFAULT_VELOCITY),
            open_in_garageband=args.get("open_in_garageband", False),
        ),
        "garageband_score_spec_schema": lambda: core.score_spec_schema(),
        "garageband_validate_score_spec": lambda: core.validate_score_spec(args["score_spec"]),
        "garageband_score_spec_to_midi": lambda: core.create_midi_from_score_spec(
            args["score_spec"],
            args["output_path"],
            velocity=args.get("velocity", core.score_midi.DEFAULT_VELOCITY),
            open_in_garageband=args.get("open_in_garageband", False),
        ),
        "garageband_make_music": lambda: core.make_music(
            output_dir=args["output_dir"],
            name=args.get("name"),
            score_path=args.get("score_path"),
            score_spec=args.get("score_spec"),
            score_json=args.get("score_json"),
            score_json_file=args.get("score_json_file"),
            tab_text=args.get("tab_text"),
            tab_file=args.get("tab_file"),
            image_path=args.get("image_path"),
            image_url=args.get("image_url"),
            bpm=args.get("bpm"),
            velocity=args.get("velocity", core.score_midi.DEFAULT_VELOCITY),
            open_in_garageband=args.get("open_in_garageband", True),
            show_library=args.get("show_library", False),
            show_smart_controls=args.get("show_smart_controls", False),
            show_loop_browser=args.get("show_loop_browser", False),
            master_volume=args.get("master_volume"),
            screenshot_output=args.get("screenshot_output"),
            snapshot_depth=args.get("snapshot_depth", 2),
            discard_unsaved=args.get("discard_unsaved", False),
            arrange=args.get("arrange", True),
            include_bass=args.get("include_bass", True),
            include_drums=args.get("include_drums", True),
            arrangement_style=args.get("arrangement_style", args.get("style", "rock")),
            repeat_count=args.get("repeat_count", 1),
            capo=args.get("capo"),
            tuning=args.get("tuning"),
            export_output=args.get("export_output"),
            export_format=args.get("export_format"),
            export_quality=args.get("export_quality"),
            export_include_cycle=args.get("export_include_cycle"),
            export_overwrite=args.get("export_overwrite", False),
            export_timeout_seconds=args.get("export_timeout_seconds", 180),
        ),
        "garageband_make_from_score": lambda: core.make_from_score(
            score_path=args["score_path"],
            output_dir=args["output_dir"],
            name=args.get("name"),
            bpm=args.get("bpm"),
            velocity=args.get("velocity", core.score_midi.DEFAULT_VELOCITY),
            open_in_garageband=args.get("open_in_garageband", True),
            show_library=args.get("show_library", False),
            show_smart_controls=args.get("show_smart_controls", False),
            show_loop_browser=args.get("show_loop_browser", False),
            screenshot_output=args.get("screenshot_output"),
            snapshot_depth=args.get("snapshot_depth", 2),
            discard_unsaved=args.get("discard_unsaved", False),
            export_output=args.get("export_output"),
            export_format=args.get("export_format"),
            export_quality=args.get("export_quality"),
            export_include_cycle=args.get("export_include_cycle"),
            export_overwrite=args.get("export_overwrite", False),
            export_timeout_seconds=args.get("export_timeout_seconds", 180),
        ),
        "garageband_make_from_score_spec": lambda: core.make_from_score_spec(
            score_spec=args["score_spec"],
            output_dir=args["output_dir"],
            name=args.get("name"),
            velocity=args.get("velocity", core.score_midi.DEFAULT_VELOCITY),
            open_in_garageband=args.get("open_in_garageband", True),
            show_library=args.get("show_library", False),
            show_smart_controls=args.get("show_smart_controls", False),
            show_loop_browser=args.get("show_loop_browser", False),
            screenshot_output=args.get("screenshot_output"),
            snapshot_depth=args.get("snapshot_depth", 2),
            discard_unsaved=args.get("discard_unsaved", False),
            export_output=args.get("export_output"),
            export_format=args.get("export_format"),
            export_quality=args.get("export_quality"),
            export_include_cycle=args.get("export_include_cycle"),
            export_overwrite=args.get("export_overwrite", False),
            export_timeout_seconds=args.get("export_timeout_seconds", 180),
        ),
        "garageband_make_from_tab": lambda: core.make_from_tab(
            output_dir=args["output_dir"],
            name=args.get("name", "garageband-tab-song"),
            tab_text=args.get("tab_text"),
            tab_file=args.get("tab_file"),
            image_path=args.get("image_path"),
            image_url=args.get("image_url"),
            bpm=args.get("bpm"),
            open_in_garageband=args.get("open_in_garageband", True),
            show_library=args.get("show_library", False),
            show_smart_controls=args.get("show_smart_controls", False),
            show_loop_browser=args.get("show_loop_browser", False),
            master_volume=args.get("master_volume"),
            screenshot_output=args.get("screenshot_output"),
            snapshot_depth=args.get("snapshot_depth", 2),
            discard_unsaved=args.get("discard_unsaved", False),
            arrange=args.get("arrange", False),
            include_bass=args.get("include_bass", True),
            include_drums=args.get("include_drums", True),
            arrangement_style=args.get("arrangement_style", args.get("style", "rock")),
            repeat_count=args.get("repeat_count", 1),
            capo=args.get("capo"),
            tuning=args.get("tuning"),
            export_output=args.get("export_output"),
            export_format=args.get("export_format"),
            export_quality=args.get("export_quality"),
            export_include_cycle=args.get("export_include_cycle"),
            export_overwrite=args.get("export_overwrite", False),
            export_timeout_seconds=args.get("export_timeout_seconds", 180),
        ),
        "garageband_permissions": lambda: core.permissions_note(),
    }
    if name not in calls:
        raise core.GarageBandError(f"Unknown tool: {name}")
    return _content({"ok": True, "data": calls[name]()})


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "garageband-llm-bridge", "version": __version__},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params", {})
        try:
            result = _call_tool(params.get("name", ""), params.get("arguments", {}) or {})
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": _content({"ok": False, "error": str(exc), "type": exc.__class__.__name__})
                | {"isError": True},
            }

    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = _handle(message)
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(exc)},
            }
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Open a NEXPT score, choose recorded kits and export through GarageBand.

The score and MIDI preparation work on every platform.  ``render`` and
``discover``/``inventory`` require macOS, GarageBand and
Accessibility/Automation access.
Use ``--dry-run`` to inspect the exact macOS actions without executing them.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from garageband.instrument_catalog import (  # noqa: E402
    INSTRUMENT_CATALOG,
    build_patch_inventory,
    catalog_search_queries,
)

BRIDGE = ROOT / "tools" / "garageband-llm-bridge" / "garageband_cli.py"
DEFAULT_SCORE = ROOT / "garageband" / "scores" / "nexpt-work-68.json"
DEFAULT_PRESET = ROOT / "garageband" / "presets" / "recorded-kit.json"
DEFAULT_OUTPUT_DIR = ROOT / "garageband" / "arrangements" / "nexpt-work-68"
DEFAULT_AUDIO = ROOT / "out" / "music-garageband.wav"
DEFAULT_INVENTORY = ROOT / "garageband" / "catalogs" / "installed-patches.json"


class SessionError(RuntimeError):
    pass


def bridge_command(*args: str) -> list[str]:
    return [sys.executable, str(BRIDGE), "--pretty", *args]


def bridge_call(*args: str) -> dict:
    command = bridge_command(*args)
    print("> " + " ".join(json.dumps(part) if " " in part else part
                          for part in command), flush=True)
    process = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True)
    stream = process.stdout if process.returncode == 0 else process.stderr
    try:
        payload = json.loads(stream)
    except json.JSONDecodeError as exc:
        raise SessionError(stream.strip() or "Bridge returned no JSON") from exc
    if process.returncode or not payload.get("ok"):
        raise SessionError(payload.get("error") or "Bridge command failed")
    return payload["data"]


def load_preset(path: Path) -> dict:
    if not path.exists():
        raise SessionError(f"Preset does not exist: {path}")
    try:
        preset = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SessionError(f"Invalid preset JSON: {exc}") from exc
    if not isinstance(preset, dict):
        raise SessionError("Preset must be a JSON object")
    if preset.get("schema_version") != 1:
        raise SessionError("Preset schema_version must be 1")
    tracks = preset.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise SessionError("Preset needs a non-empty tracks list")
    seen: set[str] = set()
    for index, track in enumerate(tracks, start=1):
        if not isinstance(track, dict):
            raise SessionError(f"Preset track {index} must be an object")
        part = str(track.get("part") or "").strip()
        patch = track.get("patch")
        if not part or part in seen:
            raise SessionError(f"Preset track {index} needs a unique part")
        if (not isinstance(patch, dict) or
                not isinstance(patch.get("query"), str) or
                not patch["query"].strip()):
            raise SessionError(f"Preset track {part} needs patch.query")
        preferred = patch.get("preferred", [])
        if not isinstance(preferred, list):
            raise SessionError(f"Preset track {part} patch.preferred must be a list")
        if any(not isinstance(value, str) or not value.strip() for value in preferred):
            raise SessionError(
                f"Preset track {part} patch.preferred must contain non-empty strings")
        allow_first = patch.get("allow_first", False)
        if not isinstance(allow_first, bool):
            raise SessionError(f"Preset track {part} patch.allow_first must be Boolean")
        if not preferred and not allow_first:
            raise SessionError(
                f"Preset track {part} needs a preferred patch or allow_first=true")
        fallback_index = track.get("fallback_index")
        if (fallback_index is not None and
                (not isinstance(fallback_index, int) or isinstance(fallback_index, bool)
                 or fallback_index < 1)):
            raise SessionError(
                f"Preset track {part} fallback_index must be a positive integer")
        seen.add(part)
    return preset


def _track_index(track_spec: dict, visible: list[dict]) -> int:
    needle = str(track_spec["part"]).casefold()
    matches = [row for row in visible if needle in str(row.get("name", "")).casefold()]
    if len(matches) == 1:
        return int(matches[0]["index"])
    fallback = track_spec.get("fallback_index")
    if fallback is not None and any(int(row["index"]) == int(fallback)
                                    for row in visible):
        return int(fallback)
    names = ", ".join(f"{row.get('index')}: {row.get('name')}" for row in visible)
    raise SessionError(
        f"Could not resolve imported track {track_spec['part']!r}. Visible: {names}")


def _choose_patch(patch: dict, results: list[dict]) -> dict:
    preferred = [str(value).strip() for value in patch.get("preferred", [])
                 if str(value).strip()]
    for candidate in preferred:
        exact = [row for row in results
                 if str(row.get("name", "")).casefold() == candidate.casefold()]
        if exact:
            return exact[0]
    for candidate in preferred:
        partial = [row for row in results
                   if candidate.casefold() in str(row.get("name", "")).casefold()]
        if len(partial) == 1:
            return partial[0]
    if patch.get("allow_first") and results:
        return results[0]
    available = ", ".join(str(row.get("name")) for row in results[:20]) or "none"
    raise SessionError(
        "No preferred GarageBand patch was found. "
        f"Search returned: {available}. Update the preset after `discover`."
    )


def render_plan(score: Path, preset_path: Path, output_dir: Path,
                audio: Path, discard_unsaved: bool, overwrite: bool) -> dict:
    preset = load_preset(preset_path)
    open_args = [
        "make-from-score-spec", "--file", str(score.resolve()),
        "--output-dir", str(output_dir.resolve()),
        "--name", score.stem, "--show-library",
        "--screenshot-output", str((output_dir/"01-import.png").resolve()),
    ]
    if discard_unsaved:
        open_args.append("--discard-unsaved")
    steps: list[dict[str, Any]] = [
        {"phase": "validate", "command": bridge_command(
            "score-spec-validate", "--file", str(score.resolve()))},
        {"phase": "open", "command": bridge_command(*open_args)},
        {"phase": "inspect_tracks", "command": bridge_command("list-tracks")},
    ]
    for track in preset["tracks"]:
        steps.append({
            "phase": "select_patch",
            "part": track["part"],
            "fallback_index": track.get("fallback_index"),
            "search": track["patch"]["query"],
            "preferred": track["patch"].get("preferred", []),
            "allow_first": bool(track["patch"].get("allow_first")),
            "volume": track.get("volume"),
            "pan": track.get("pan"),
        })
    steps.append({
        "phase": "verify", "command": bridge_command(
            "screenshot", "--output", str((output_dir/"02-kits.png").resolve()))})
    export_args = [
        "export-song", "--output", str(audio.resolve()),
        "--format", str(preset.get("export", {}).get("format", "WAVE")),
        "--timeout", str(preset.get("export", {}).get("timeout_seconds", 240)),
    ]
    if overwrite:
        export_args.append("--overwrite")
    steps.append({"phase": "export", "command": bridge_command(*export_args)})
    return {
        "schema_version": 1,
        "score": str(score.resolve()),
        "preset": str(preset_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "audio": str(audio.resolve()),
        "platform_required": "macOS",
        "steps": steps,
    }


def prepare_plan(score: Path, preset_path: Path, output_dir: Path,
                 reference_audio: Path, discard_unsaved: bool) -> dict:
    """Describe the edit-project workflow without touching GarageBand."""
    base = render_plan(
        score, preset_path, output_dir, ROOT/"out"/"unused-prepare.wav",
        discard_unsaved, overwrite=False,
    )
    steps = [step for step in base["steps"]
             if step["phase"] not in {"verify", "export"}]
    steps.extend([
        {
            "phase": "reveal_reference",
            "command": ["open", "-R", str(reference_audio.resolve())],
        },
        {
            "phase": "user_drag_reference",
            "instruction": (
                "Drag the revealed audio file to the empty area below the "
                "GarageBand tracks at project start 1 1 1 1."
            ),
        },
        {
            "phase": "label_and_mute_reference",
            "instruction": (
                "After confirmation, detect the new track, rename it "
                "REFERENCE — Original 1:1, and mute it for A/B comparison."
            ),
        },
        {
            "phase": "save_project",
            "instruction": "Use Command-S in GarageBand and choose the .band project path.",
        },
    ])
    return {
        "schema_version": 1,
        "score": str(score.resolve()), "preset": str(preset_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "reference_audio": str(reference_audio.resolve()),
        "platform_required": "macOS", "steps": steps,
        "result": (
            "One unaltered source-audio reference track plus editable "
            "transcribed MIDI tracks in the same GarageBand project."
        ),
    }


def _open_and_patch(score: Path, preset_path: Path, output_dir: Path,
                    discard_unsaved: bool) -> dict:
    """Open one score and apply every generated GarageBand Library patch."""
    preset = load_preset(preset_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    validation = bridge_call(
        "score-spec-validate", "--file", str(score.resolve()))
    open_args = [
        "make-from-score-spec", "--file", str(score.resolve()),
        "--output-dir", str(output_dir.resolve()),
        "--name", score.stem, "--show-library",
        "--screenshot-output", str((output_dir/"01-import.png").resolve()),
    ]
    if discard_unsaved:
        open_args.append("--discard-unsaved")
    opened = bridge_call(*open_args)
    tracks = bridge_call("list-tracks")
    visible = tracks.get("tracks", [])
    selected = []
    for track_spec in preset["tracks"]:
        index = _track_index(track_spec, visible)
        bridge_call("select-track", "--index", str(index))
        patch = track_spec["patch"]
        query = str(patch["query"])
        found = bridge_call("library-search", query, "--no-show", "--limit", "100")
        choice = _choose_patch(patch, found.get("results", []))
        applied = bridge_call(
            "library-select", query, "--index", str(choice["index"]), "--no-show")
        set_args = ["set-track", "--index", str(index)]
        if track_spec.get("volume") is not None:
            set_args += ["--volume", str(track_spec["volume"])]
        if track_spec.get("pan") is not None:
            set_args += ["--pan", str(track_spec["pan"])]
        mix = bridge_call(*set_args) if len(set_args) > 3 else None
        selected.append({
            "part": track_spec["part"], "track_index": index,
            "patch": choice.get("name"), "applied": applied, "mix": mix,
        })
    return {
        "validation": validation, "opened": opened,
        "tracks_before_patch": tracks, "selected_patches": selected,
    }


def run_render(args: argparse.Namespace) -> dict:
    if not args.score.exists():
        raise SessionError(f"Score does not exist: {args.score}")
    plan = render_plan(
        args.score, args.preset, args.output_dir, args.output,
        args.discard_unsaved, args.overwrite,
    )
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return {"dry_run": True, "plan": plan}
    if platform.system() != "Darwin":
        raise SessionError(
            "GarageBand rendering requires macOS. Use --dry-run here, then run "
            "the same command on the Mac that has GarageBand installed.")
    if args.output.exists() and not args.overwrite:
        raise SessionError(
            f"Output already exists: {args.output}. Pass --overwrite explicitly.")

    prepared = _open_and_patch(
        args.score, args.preset, args.output_dir, args.discard_unsaved)
    validation = prepared["validation"]
    preset = load_preset(args.preset)

    screenshot = bridge_call(
        "screenshot", "--output", str((args.output_dir/"02-kits.png").resolve()))
    export_args = [
        "export-song", "--output", str(args.output.resolve()),
        "--format", str(preset.get("export", {}).get("format", "WAVE")),
        "--timeout", str(preset.get("export", {}).get("timeout_seconds", 240)),
    ]
    if args.overwrite:
        export_args.append("--overwrite")
    exported = bridge_call(*export_args)
    expected_seconds = (float(validation["duration_beats"])*60.0 /
                        float(validation["bpm"]))
    actual_seconds = float(exported.get("audio_info", {}).get(
        "duration_seconds", 0.0))
    duration_verification = {
        "expected_minimum_seconds": round(expected_seconds-.25, 3),
        "expected_score_seconds": round(expected_seconds, 3),
        "actual_seconds": round(actual_seconds, 3),
        "not_short": actual_seconds >= expected_seconds-.25,
        "note": "A longer file is allowed for GarageBand reverb tails.",
    }
    success = bool(exported.get("verified")) and duration_verification["not_short"]
    result = {
        "ok": success,
        "score_validation": validation,
        "opened": prepared["opened"],
        "tracks_before_patch": prepared["tracks_before_patch"],
        "selected_patches": prepared["selected_patches"],
        "verification_screenshot": screenshot,
        "audio_export": exported,
        "duration_verification": duration_verification,
        "music_output": str(args.output.resolve()),
        "sfx_output": str((ROOT/"out"/"sfx-original.wav").resolve()),
        "separation": "Music and sound effects are independent files.",
    }
    manifest = args.output_dir/"session-result.json"
    manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if not success:
        raise SessionError(
            "GarageBand created an export, but audio verification failed or "
            f"the file is too short. Inspect {manifest} and keep the WAV for diagnosis.")
    print(f"Done: {args.output}")
    print(f"Session manifest: {manifest}")
    return result


def run_prepare(args: argparse.Namespace) -> dict:
    """Open an editable reconstruction and attach the original A/B reference."""
    if not args.score.exists():
        raise SessionError(f"Score does not exist: {args.score}")
    if not args.reference_audio.exists():
        raise SessionError(f"Reference audio does not exist: {args.reference_audio}")
    plan = prepare_plan(
        args.score, args.preset, args.output_dir,
        args.reference_audio, args.discard_unsaved)
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return {"dry_run": True, "plan": plan}
    if platform.system() != "Darwin":
        raise SessionError(
            "Preparing a GarageBand edit project requires macOS. Use --dry-run "
            "here and run the same command on the GarageBand Mac.")

    prepared = _open_and_patch(
        args.score, args.preset, args.output_dir, args.discard_unsaved)
    subprocess.run(["open", "-R", str(args.reference_audio.resolve())], check=True)
    before = {
        int(row["index"])
        for row in prepared["tracks_before_patch"].get("tracks", [])
    }
    print("\nFinder zeigt jetzt die Originaldatei.")
    print("Ziehe sie in GarageBand unter die vorhandenen Spuren ganz an den Anfang (1 1 1 1).")
    if args.no_wait:
        result = {
            **prepared, "reference_audio": str(args.reference_audio.resolve()),
            "reference_track": None,
            "next": (
                "Drag the file, then run session.py reference-track "
                "--index TRACK_INDEX to label and mute it."
            ),
        }
        print("Projekt bleibt offen; die Referenzspur wird nach dem Ziehen manuell fertiggestellt.")
        return result
    if not sys.stdin.isatty():
        raise SessionError(
            "Interactive Finder drag needs a terminal. Re-run with --no-wait, "
            "drag the file, then label/mute the new track in GarageBand.")
    input("Wenn die Wellenform in GarageBand sichtbar ist, hier Enter druecken: ")

    after = bridge_call("list-tracks")
    new_rows = [row for row in after.get("tracks", [])
                if int(row["index"]) not in before]
    if args.reference_track_index is not None:
        reference_index = args.reference_track_index
    elif len(new_rows) == 1:
        reference_index = int(new_rows[0]["index"])
    else:
        visible = ", ".join(
            f"{row.get('index')}: {row.get('name')}" for row in after.get("tracks", []))
        raise SessionError(
            "The new reference track could not be identified uniquely. "
            f"Visible tracks: {visible}. Re-run with --reference-track-index INDEX.")
    set_args = [
        "set-track", "--index", str(reference_index),
        "--rename", "REFERENCE — Original 1:1",
    ]
    if not args.keep_reference_audible:
        set_args += ["--mute", "true"]
    reference_track = bridge_call(*set_args)
    screenshot = bridge_call(
        "screenshot", "--output", str((args.output_dir/"02-edit-project.png").resolve()))
    result = {
        **prepared, "reference_audio": str(args.reference_audio.resolve()),
        "reference_track": {"index": reference_index, "update": reference_track},
        "tracks_after_reference": after, "verification_screenshot": screenshot,
        "ready_to_edit": True,
        "save_instruction": "Press Command-S in GarageBand and choose the .band project path.",
    }
    manifest = args.output_dir/"prepare-result.json"
    manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("Bearbeitbares Projekt ist bereit. Die Originalspur ist als A/B-Referenz stummgeschaltet.")
    print("Jetzt in GarageBand mit Command-S als .band-Projekt speichern.")
    return result


def run_reference_track(args: argparse.Namespace) -> dict:
    """Label an already dragged source-audio track for A/B comparison."""
    if platform.system() != "Darwin":
        raise SessionError("Reference-track setup requires an open GarageBand project on macOS")
    set_args = [
        "set-track", "--index", str(args.index),
        "--rename", "REFERENCE — Original 1:1",
    ]
    if not args.keep_audible:
        set_args += ["--mute", "true"]
    result = bridge_call(*set_args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def run_export_current(args: argparse.Namespace) -> dict:
    """Export the currently open, manually edited GarageBand project."""
    if platform.system() != "Darwin":
        raise SessionError("Exporting the current GarageBand project requires macOS")
    if args.output.exists() and not args.overwrite:
        raise SessionError(
            f"Output already exists: {args.output}. Pass --overwrite explicitly.")
    export_args = [
        "export-song", "--output", str(args.output.resolve()),
        "--format", args.format, "--timeout", str(args.timeout),
    ]
    if args.overwrite:
        export_args.append("--overwrite")
    result = bridge_call(*export_args)
    if not result.get("verified"):
        raise SessionError("GarageBand export finished but audio verification failed")
    print(f"Done: {args.output}")
    return result


def run_doctor(args: argparse.Namespace) -> dict:
    preset = load_preset(args.preset)
    result: dict[str, Any] = {
        "platform": platform.system(),
        "platform_ok": platform.system() == "Darwin",
        "bridge": str(BRIDGE),
        "bridge_exists": BRIDGE.exists(),
        "score": str(args.score),
        "score_exists": args.score.exists(),
        "preset": preset["name"],
    }
    if BRIDGE.exists() and args.score.exists():
        result["score_validation"] = bridge_call(
            "score-spec-validate", "--file", str(args.score.resolve()))
    if platform.system() == "Darwin" and BRIDGE.exists():
        result["garageband"] = bridge_call("status")
        result["permissions"] = bridge_call("permissions")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and (not result["platform_ok"] or not result["bridge_exists"] or
                        not result["score_exists"] or
                        not result.get("garageband", {}).get("installed", False)):
        raise SessionError("Doctor checks did not pass")
    return result


def run_discover(args: argparse.Namespace) -> dict:
    if platform.system() != "Darwin":
        raise SessionError("Kit discovery requires macOS and an open GarageBand project")
    bridge_call("select-track", "--index", str(args.track_index))
    result = bridge_call("library-search", args.query, "--limit", str(args.limit))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def run_inventory(args: argparse.Namespace) -> dict:
    """Inventory the software-instrument patches installed on this Mac."""
    if platform.system() != "Darwin":
        raise SessionError(
            "Library inventory requires macOS and an open GarageBand project")
    bridge_call("select-track", "--index", str(args.track_index))
    garageband = bridge_call("status")
    queries = args.query or catalog_search_queries(INSTRUMENT_CATALOG)
    searches = []
    for index, query in enumerate(queries):
        command = ["library-search", query, "--limit", str(args.limit)]
        if index:
            command.append("--no-show")
        try:
            result = bridge_call(*command)
            searches.append({
                "query": query, "results": result.get("results", []),
            })
        except SessionError as exc:
            searches.append({"query": query, "results": [], "error": str(exc)})
    inventory = build_patch_inventory(
        searches, garageband=garageband, catalog=INSTRUMENT_CATALOG)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    summary = {
        "output": str(output),
        "queries": len(inventory["searches"]),
        "visible_patch_rows": len(inventory["patches"]),
        "mapped_instruments": len(inventory["by_instrument"]),
        "mapped_families": len(inventory["by_family"]),
        "taxonomy": inventory["taxonomy"],
        "failed_queries": [
            row["query"] for row in inventory["searches"] if row.get("error")
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return inventory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="validate the score and Mac setup")
    doctor.add_argument("--score", type=Path, default=DEFAULT_SCORE)
    doctor.add_argument("--preset", type=Path, default=DEFAULT_PRESET)
    doctor.add_argument("--strict", action="store_true")

    render = sub.add_parser("render", help="open, patch and export through GarageBand")
    render.add_argument("--score", type=Path, default=DEFAULT_SCORE)
    render.add_argument("--preset", type=Path, default=DEFAULT_PRESET)
    render.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    render.add_argument("--output", type=Path, default=DEFAULT_AUDIO)
    render.add_argument("--discard-unsaved", action="store_true")
    render.add_argument("--overwrite", action="store_true")
    render.add_argument("--dry-run", action="store_true")

    prepare = sub.add_parser(
        "prepare", help="open editable MIDI tracks plus an original A/B reference")
    prepare.add_argument("--score", type=Path, required=True)
    prepare.add_argument("--preset", type=Path, required=True)
    prepare.add_argument("--reference-audio", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path,
                         default=ROOT/"garageband"/"arrangements"/"transcription")
    prepare.add_argument("--discard-unsaved", action="store_true")
    prepare.add_argument("--reference-track-index", type=int)
    prepare.add_argument("--keep-reference-audible", action="store_true")
    prepare.add_argument("--no-wait", action="store_true")
    prepare.add_argument("--dry-run", action="store_true")

    reference = sub.add_parser(
        "reference-track", help="label and mute an already imported source-audio track")
    reference.add_argument("--index", type=int, required=True)
    reference.add_argument("--keep-audible", action="store_true")

    current = sub.add_parser(
        "export-current", help="export the currently open edited GarageBand project")
    current.add_argument("--output", type=Path,
                         default=ROOT/"out"/"music-garageband-edited.wav")
    current.add_argument("--format", choices=("WAVE", "AIFF", "AAC", "MP3"),
                         default="WAVE")
    current.add_argument("--timeout", type=float, default=360)
    current.add_argument("--overwrite", action="store_true")

    discover = sub.add_parser("discover", help="list installed Library patches")
    discover.add_argument("query", nargs="?", default="Drums")
    discover.add_argument("--track-index", type=int, default=1)
    discover.add_argument("--limit", type=int, default=100)

    inventory = sub.add_parser(
        "inventory", help="map all installed software-instrument Library patches")
    inventory.add_argument("--track-index", type=int, default=1)
    inventory.add_argument("--limit", type=int, default=500)
    inventory.add_argument("--output", type=Path, default=DEFAULT_INVENTORY)
    inventory.add_argument(
        "--query", action="append",
        help="scan only this Library query; repeat for multiple queries",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "doctor":
            run_doctor(args)
        elif args.command == "render":
            run_render(args)
        elif args.command == "prepare":
            run_prepare(args)
        elif args.command == "reference-track":
            run_reference_track(args)
        elif args.command == "export-current":
            run_export_current(args)
        elif args.command == "discover":
            run_discover(args)
        else:
            run_inventory(args)
    except SessionError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()

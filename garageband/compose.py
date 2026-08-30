#!/usr/bin/env python3
"""Build a multi-track GarageBand score from a reference-audio profile.

The analyzer learns statistical rhythm, dynamics and microtiming from a
reference. ``reference_arrangement.py`` creates a new performance from that
grammar. This module maps its four musical roles to drum-kit articulations
without synthesizing a single sound.

Examples::

    python3 garageband/compose.py --midi
    python3 garageband/compose.py --profile out/analysis/reference-profile.json
    python3 garageband/compose.py --bericht
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "render"
if str(RENDER) not in sys.path:
    sys.path.insert(0, str(RENDER))

from audio_common import OUT, cue_sheet, timing  # noqa: E402
from reference_arrangement import ROLES, plan_reference_events  # noqa: E402
from reference_sound import load_profile  # noqa: E402


BRIDGE = ROOT / "tools" / "garageband-llm-bridge" / "garageband_cli.py"
DEFAULT_PROFILE = OUT / "analysis" / "reference-profile.json"
DEFAULT_SCORE = Path(__file__).resolve().parent / "scores" / "nexpt-work-68.json"
DEFAULT_MIDI = DEFAULT_SCORE.with_suffix(".mid")


# Separate MIDI channels let GarageBand retain four tracks. Each track can
# then receive its own recorded kit patch and mix settings. Notes still use
# GM drum pitches because ``is_percussion`` remains true.
ROLE_CONFIG: dict[str, dict[str, Any]] = {
    "low": {
        "name": "NEXPT Low",
        "channel": 1,
        "mix": {"volume": "86%", "pan": "center", "reverb": .05},
        "duration": .30,
        "velocity": (38, 118),
    },
    "body": {
        "name": "NEXPT Body",
        "channel": 2,
        "mix": {"volume": "80%", "pan": -.08, "reverb": .11},
        "duration": .22,
        "velocity": (32, 112),
    },
    "tonal": {
        "name": "NEXPT Tonal",
        "channel": 3,
        "mix": {"volume": "78%", "pan": .07, "reverb": .15},
        "duration": .34,
        "velocity": (28, 108),
    },
    "detail": {
        "name": "NEXPT Detail",
        "channel": 4,
        "mix": {"volume": "68%", "pan": .13, "reverb": .09},
        "duration": .14,
        "velocity": (20, 98),
    },
}


def drum_for_event(event: dict) -> str:
    """Map an abstract role to an articulation available in real drum kits."""
    role = event["role"]
    position = int(event["position"])
    energy = float(event["energy"])
    section = str(event["section"])

    if role == "low":
        return "kick"
    if role == "body":
        return "snare" if position in {4, 12} or energy >= .70 else "rim"
    if role == "tonal":
        toms = ("low_tom", "mid_tom", "high_tom", "mid_tom")
        return toms[int(event.get("pitch_variant", 0)) % len(toms)]
    if section == "final-hit" or (position == 0 and energy >= .92):
        return "crash"
    if position in {7, 15} and energy >= .62:
        return "open_hat"
    if energy >= .84 and position in {2, 6, 10, 14}:
        return "ride"
    return "closed_hat"


def midi_velocity(event: dict) -> int:
    low, high = ROLE_CONFIG[event["role"]]["velocity"]
    performance = max(0.0, min(1.0, float(event["gain"])))
    return int(round(low+(high-low)*performance))


def build_score(
    profile: dict,
    *,
    total_seconds: float,
    bars: int,
    bpm: float,
    cues: list[dict] | None = None,
    seed: int | None = None,
) -> tuple[dict, dict]:
    """Return Bridge Score Spec v1 plus a compact, testable report."""
    plan = plan_reference_events(
        profile, total_seconds, bars, bpm, cues=cues, seed=seed)
    beat_seconds = 60.0/bpm
    by_role: dict[str, list[dict]] = {role: [] for role in ROLES}
    articulation_counts: Counter[str] = Counter()

    for event in plan.events:
        role = event["role"]
        config = ROLE_CONFIG[role]
        drum = drum_for_event(event)
        articulation_counts[drum] += 1
        by_role[role].append({
            "drum": drum,
            "start": round(max(0.0, float(event["time"])/beat_seconds), 5),
            "duration": config["duration"],
            "velocity": midi_velocity(event),
            # Extra fields are ignored by the Bridge but make the generated
            # score auditable without storing the reference event sequence.
            "nexpt_role": role,
            "nexpt_section": event["section"],
            "nexpt_grid_offset_ms": event["grid_offset_ms"],
        })

    # A MIDI note outside the General-MIDI drum range keeps the imported
    # GarageBand region exactly as long as the film. Velocity 1 and MIDI 0 are
    # silent on normal drum kits; the note-off lands on the final bar line.
    anchor_role = "detail" if by_role["detail"] else "low"
    by_role[anchor_role].append({
        "midi": 0,
        "start": round(bars*4.0-.05, 5),
        "duration": .05,
        "velocity": 1,
        "nexpt_role": anchor_role,
        "nexpt_section": "timeline-anchor",
        "nexpt_grid_offset_ms": 0.0,
        "nexpt_timeline_anchor": True,
    })

    parts = []
    for role in ROLES:
        notes = sorted(by_role[role], key=lambda row: (
            row["start"], row.get("drum", "")))
        if not notes:
            continue
        config = ROLE_CONFIG[role]
        parts.append({
            "id": f"nexpt-{role}",
            "name": config["name"],
            "instrument": "drum kit",
            "is_percussion": True,
            "channel": config["channel"],
            "mix": config["mix"],
            "notes": notes,
        })

    source = profile.get("source", {})
    spec = {
        "format": "garageband_score_spec_v1",
        "title": f"NEXPT Reference Percussion — {bars} bars",
        "bpm": int(round(bpm)),
        "time_signature": "4/4",
        "parts": parts,
        "nexpt": {
            "schema_version": 1,
            "generator": "garageband/compose.py",
            "reference_profile": {
                "schema_version": profile.get("schema_version"),
                "source_file_name": source.get("file_name"),
                "source_sha256": source.get("sha256"),
            },
            "composition": plan.context(),
            "role_mapping": {
                role: {
                    "track": ROLE_CONFIG[role]["name"],
                    "channel": ROLE_CONFIG[role]["channel"],
                }
                for role in ROLES
            },
            "principle": (
                "Original performance generated from descriptor statistics; "
                "no source audio, source stem or source event sequence embedded."
            ),
        },
    }

    offsets = [abs(float(event["grid_offset_ms"])) for event in plan.events]
    velocities = [note["velocity"] for part in parts for note in part["notes"]
                  if not note.get("nexpt_timeline_anchor")]
    report = {
        "bars": bars,
        "bpm": bpm,
        "events": len(plan.events),
        "score_notes": len(plan.events)+1,
        "tracks": len(parts),
        "events_by_role": {
            role: sum(1 for event in plan.events if event["role"] == role)
            for role in ROLES
        },
        "articulations": dict(sorted(articulation_counts.items())),
        "velocity": {
            "min": min(velocities) if velocities else None,
            "median": statistics.median(velocities) if velocities else None,
            "max": max(velocities) if velocities else None,
        },
        "absolute_microtiming_ms": {
            "median": round(statistics.median(offsets), 3) if offsets else 0.0,
            "max": round(max(offsets), 3) if offsets else 0.0,
        },
        "seed": plan.seed,
        "halts": len(plan.halt_regions),
        "cue_ducks": len(plan.cue_ducks),
    }
    return spec, report


def bridge_call(*args: str) -> dict:
    if not BRIDGE.exists():
        raise FileNotFoundError(f"Bridge fehlt: {BRIDGE}")
    process = subprocess.run(
        [sys.executable, str(BRIDGE), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    stream = process.stdout if process.returncode == 0 else process.stderr
    try:
        payload = json.loads(stream)
    except json.JSONDecodeError as exc:
        raise RuntimeError(stream.strip() or "Bridge returned no JSON") from exc
    if process.returncode or not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "Bridge command failed")
    return payload["data"]


def write_score(spec: dict, score_path: Path, midi_path: Path | None = None) -> dict:
    score_path = score_path.resolve()
    score_path.parent.mkdir(parents=True, exist_ok=True)
    score_path.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    validation = bridge_call("score-spec-validate", "--file", str(score_path))
    result = {"score": str(score_path), "validation": validation}
    if midi_path is not None:
        midi_path = midi_path.resolve()
        midi_path.parent.mkdir(parents=True, exist_ok=True)
        result["midi"] = bridge_call(
            "score-spec-to-midi", "--file", str(score_path),
            "--output", str(midi_path),
        )
    return result


def _print_report(report: dict) -> None:
    print(f"{report['bars']} bars · {report['bpm']:.2f} BPM · "
          f"{report['events']} hits · {report['tracks']} GarageBand tracks")
    print("Roles: " + ", ".join(
        f"{name} {count}" for name, count in report["events_by_role"].items()))
    velocity = report["velocity"]
    timing_report = report["absolute_microtiming_ms"]
    print(f"Velocity {velocity['min']}..{velocity['max']} "
          f"(median {velocity['median']}) · microtiming median "
          f"{timing_report['median']:.1f} ms")
    print("Kit articulations: " + ", ".join(
        f"{name} {count}" for name, count in report["articulations"].items()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_SCORE)
    parser.add_argument("--midi", nargs="?", const=DEFAULT_MIDI, type=Path,
                        help="also write MIDI; an optional path may follow")
    parser.add_argument("--target-bpm", type=float)
    parser.add_argument("--bars", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--without-cues", action="store_true")
    parser.add_argument("--bericht", "--report-only", action="store_true",
                        dest="report_only")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.profile.exists():
        raise SystemExit(
            f"{args.profile} fehlt. Zuerst die Referenz analysieren:\n"
            "  python3 render/reference_analyzer.py /pfad/referenz.mp3 --bpm 118"
        )
    profile = load_profile(args.profile)
    _, film_total = timing()
    cue_data = {"cues": [], "film": {}}
    if not args.without_cues:
        try:
            cue_data = cue_sheet()
        except FileNotFoundError as exc:
            print(f"Hinweis: {exc}; Score wird ohne SFX-Freiraeume erzeugt.",
                  file=sys.stderr)
    bpm = float(
        args.target_bpm or cue_data.get("film", {}).get("bpm") or
        profile["tempo"]["bpm"]
    )
    bars = args.bars or int(round(film_total/(240.0/bpm)))
    total_seconds = bars*(240.0/bpm) if args.bars else film_total
    spec, report = build_score(
        profile,
        total_seconds=total_seconds,
        bars=bars,
        bpm=bpm,
        cues=cue_data.get("cues", []),
        seed=args.seed,
    )
    _print_report(report)
    if args.report_only:
        return

    result = write_score(spec, args.output, args.midi)
    score_path = Path(result["score"])
    print(f"Score: {score_path.relative_to(ROOT)} · Bridge validation passed")
    if "midi" in result:
        midi_path = Path(result["midi"]["path"])
        print(f"MIDI:  {midi_path.relative_to(ROOT)} · {midi_path.stat().st_size} bytes")


if __name__ == "__main__":
    main()

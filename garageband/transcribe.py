#!/usr/bin/env python3
"""Transcribe instrumental audio into an editable multi-track GarageBand score.

This is deliberately separate from :mod:`garageband.compose`:

* ``compose.py`` learns descriptors and writes a *new* performance.
* ``transcribe.py`` preserves measured source onsets, pitches, velocities and
  duration as closely as the available analysis engines permit.

High-fidelity mode uses Demucs for stems and Spotify Basic Pitch for note
events. Both are optional so the deterministic DSP fallback still works on a
plain NEXPT checkout. A finished stereo master remains an underdetermined
source: original samples, plug-ins, automation and perfectly isolated stems
cannot be recovered from it.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "render"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(RENDER) not in sys.path:
    sys.path.insert(0, str(RENDER))

from garageband.compose import write_score  # noqa: E402
from reference_analyzer import SR, analyze_reference, decode_audio  # noqa: E402


class TranscriptionError(RuntimeError):
    """A requested transcription engine or stage could not run."""


DRUM_TRACKS: dict[str, dict[str, Any]] = {
    "drums-low": {
        "name": "Transcribed Low Drums", "channel": 1,
        "instrument": "drum kit", "mix": {"volume": .86, "pan": 0, "reverb": .06},
    },
    "drums-body": {
        "name": "Transcribed Body Drums", "channel": 2,
        "instrument": "drum kit", "mix": {"volume": .80, "pan": -.06, "reverb": .10},
    },
    "drums-toms": {
        "name": "Transcribed Toms", "channel": 3,
        "instrument": "drum kit", "mix": {"volume": .76, "pan": .06, "reverb": .13},
    },
    "drums-detail": {
        "name": "Transcribed Cymbals", "channel": 4,
        "instrument": "drum kit", "mix": {"volume": .68, "pan": .12, "reverb": .10},
    },
}

TONAL_TRACKS: dict[str, dict[str, Any]] = {
    "bass": {
        "name": "Transcribed Bass", "channel": 5, "instrument": "electric bass",
        "program": 33, "mix": {"volume": .76, "pan": 0, "reverb": .04},
    },
    "harmony": {
        "name": "Transcribed Harmony", "channel": 6, "instrument": "piano",
        "program": 0, "mix": {"volume": .70, "pan": -.05, "reverb": .12},
    },
    "melody": {
        "name": "Transcribed Melody", "channel": 7, "instrument": "synth lead",
        "program": 80, "mix": {"volume": .72, "pan": .05, "reverb": .14},
    },
}

DRUM_TO_TRACK = {
    "kick": "drums-low",
    "low_tom": "drums-toms",
    "mid_tom": "drums-toms",
    "high_tom": "drums-toms",
    "snare": "drums-body",
    "rim": "drums-body",
    "clap": "drums-body",
    "cowbell": "drums-body",
    "closed_hat": "drums-detail",
    "open_hat": "drums-detail",
    "ride": "drums-detail",
    "crash": "drums-detail",
}

PATCHES = {
    "drums": {
        "query": "SoCal", "preferred": ["SoCal"], "allow_first": False,
    },
    "bass": {
        "query": "Bass",
        "preferred": ["Liverpool Bass", "Picked Bass", "Fingerstyle Bass"],
        "allow_first": True,
    },
    "harmony": {
        "query": "Piano",
        "preferred": ["Steinway Grand Piano", "Classic Electric Piano"],
        "allow_first": True,
    },
    "melody": {
        "query": "Synthesizer",
        "preferred": ["Classic Analog Lead", "Analog Mono"],
        "allow_first": True,
    },
}


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return text or "instrumental"


def engine_availability() -> dict[str, Any]:
    """Return cheap, import-free optional-engine diagnostics."""
    return {
        "python": sys.version.split()[0],
        "demucs": bool(importlib.util.find_spec("demucs")),
        "basic_pitch": bool(importlib.util.find_spec("basic_pitch")),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "high_fidelity_ready": bool(
            importlib.util.find_spec("demucs") and
            importlib.util.find_spec("basic_pitch") and
            shutil.which("ffmpeg")
        ),
    }


def _engine_install_hint() -> str:
    return (
        "Hochpraezise Transkription braucht eine kompatible Python-3.10/3.11-"
        "Umgebung (Apple Silicon: 3.10) sowie die optionalen Pakete aus "
        "garageband/requirements-transcription.txt."
    )


def separate_stems(
    source: Path,
    work_dir: Path,
    *,
    mode: str = "auto",
    model: str = "htdemucs",
    device: str = "cpu",
) -> tuple[dict[str, Path], dict[str, Any]]:
    """Run Demucs when available and return role -> temporary WAV paths."""
    if mode not in {"auto", "demucs", "off"}:
        raise ValueError(f"Unknown stem mode: {mode}")
    if mode == "off":
        return {"mix": source}, {
            "requested": mode, "used": "off", "isolated_drums": False,
            "temporary_stems": False,
        }

    available = bool(importlib.util.find_spec("demucs"))
    if not available:
        if mode == "demucs":
            raise TranscriptionError(f"Demucs ist nicht installiert. {_engine_install_hint()}")
        return {"mix": source}, {
            "requested": mode, "used": "unavailable-dsp-fallback",
            "isolated_drums": False, "temporary_stems": False,
        }

    output = work_dir / "demucs"
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "demucs", "-n", model, "-d", device,
        "-j", "1", "--float32", "-o", str(output), str(source),
    ]
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if process.returncode:
        message = process.stderr.strip() or process.stdout.strip()
        if mode == "demucs":
            raise TranscriptionError(f"Demucs ist fehlgeschlagen: {message}")
        return {"mix": source}, {
            "requested": mode, "used": "failed-dsp-fallback",
            "isolated_drums": False, "temporary_stems": False,
            "error": message[-1200:],
        }

    stems: dict[str, Path] = {}
    for role in ("drums", "bass", "other", "vocals"):
        candidates = sorted(output.rglob(f"{role}.wav"))
        if candidates:
            stems[role] = candidates[0]
    if "drums" not in stems:
        message = "Demucs hat keine drums.wav erzeugt"
        if mode == "demucs":
            raise TranscriptionError(message)
        return {"mix": source}, {
            "requested": mode, "used": "invalid-output-dsp-fallback",
            "isolated_drums": False, "temporary_stems": False,
            "error": message,
        }
    return stems, {
        "requested": mode, "used": "demucs", "model": model,
        "device": device, "jobs": 1, "isolated_drums": True,
        "temporary_stems": True, "roles": sorted(stems),
    }


def _drum_confidence(event: dict, isolated: bool) -> float:
    family = str(event.get("family", "click"))
    base = {
        "sub": .82, "body": .72, "click": .66, "tick": .82,
        "air": .78, "noise": .74, "tonal": .46,
    }.get(family, .50)
    decay = float(event.get("decay_seconds", 0.0))
    strength = float(event.get("strength", .5))
    flatness = float(event.get("flatness", 0.0))
    if decay <= .14:
        base += .09
    if flatness >= .025:
        base += .04
    base += .07*strength
    if isolated:
        base += .14
    return max(0.0, min(1.0, base))


def drum_for_descriptor(event: dict) -> str:
    """Map one measured attack to a General-MIDI kit articulation."""
    family = str(event.get("family", "click"))
    dominant = float(event.get("dominant_hz", 0.0))
    centroid = float(event.get("centroid_hz", 0.0))
    decay = float(event.get("decay_seconds", 0.0))
    flatness = float(event.get("flatness", 0.0))

    if family == "sub":
        return "kick" if dominant < 115 or centroid < 430 else "low_tom"
    if family == "tonal":
        if dominant < 115 and centroid < 800:
            return "kick"
        if dominant < 430:
            return "low_tom"
        if dominant < 950:
            return "mid_tom"
        if dominant < 1900:
            return "high_tom"
        return "rim"
    if family == "body":
        return "clap" if flatness >= .10 and centroid >= 2100 else "snare"
    if family == "click":
        if centroid >= 5200:
            return "closed_hat"
        return "cowbell" if dominant >= 1500 and decay >= .08 else "rim"
    if family == "air":
        return "crash" if decay >= .18 else "open_hat"
    if family == "noise":
        return "crash" if decay >= .20 else ("open_hat" if decay >= .09 else "closed_hat")
    if family == "tick":
        return "ride" if decay >= .10 and dominant >= 3000 else "closed_hat"
    return "rim"


def _event_velocity(event: dict, confidence: float) -> int:
    strength = max(0.0, min(1.0, float(event.get("strength", .5))))
    peak = max(-36.0, min(0.0, float(event.get("peak_dbfs", -12.0))))
    peak_strength = 1.0+peak/36.0
    value = .66*strength + .24*peak_strength + .10*confidence
    return int(round(max(20, min(124, 22+102*value))))


def transcribe_drum_events(
    profile: dict,
    *,
    bpm: float,
    isolated: bool,
    confidence_threshold: float | None = None,
) -> tuple[dict[str, list[dict]], dict[str, Any]]:
    beat_seconds = 60.0/bpm
    threshold = confidence_threshold if confidence_threshold is not None else (
        .48 if isolated else .64)
    tracks: dict[str, list[dict]] = {name: [] for name in DRUM_TRACKS}
    articulations: Counter[str] = Counter()
    confidences: list[float] = []
    rejected = 0
    for event in profile.get("events", []):
        confidence = _drum_confidence(event, isolated)
        if confidence < threshold:
            rejected += 1
            continue
        drum = drum_for_descriptor(event)
        track = DRUM_TO_TRACK[drum]
        decay = max(.035, min(.75, float(event.get("decay_seconds", .10))))
        tracks[track].append({
            "drum": drum,
            "start": round(max(0.0, float(event["time"])/beat_seconds), 6),
            "duration": round(max(.04, min(1.25, decay/beat_seconds)), 5),
            "velocity": _event_velocity(event, confidence),
            "nexpt_source_time_seconds": round(float(event["time"]), 5),
            "nexpt_grid_offset_ms": float(event.get("grid_offset_ms", 0.0)),
            "nexpt_confidence": round(confidence, 4),
            "nexpt_family": event.get("family"),
        })
        articulations[drum] += 1
        confidences.append(confidence)
    for notes in tracks.values():
        notes.sort(key=lambda row: (row["start"], row["drum"]))
    return tracks, {
        "detected_onsets": len(profile.get("events", [])),
        "accepted_hits": sum(len(notes) for notes in tracks.values()),
        "rejected_onsets": rejected,
        "confidence_threshold": threshold,
        "mean_confidence": round(statistics.fmean(confidences), 4) if confidences else 0.0,
        "articulations": dict(sorted(articulations.items())),
        "source": "isolated-drums-stem" if isolated else "full-mix-fallback",
    }


def _read_note_value(raw: Any, names: Iterable[str], default: Any = None) -> Any:
    if isinstance(raw, dict):
        for name in names:
            if name in raw:
                return raw[name]
    for name in names:
        if hasattr(raw, name):
            return getattr(raw, name)
    return default


def normalize_basic_pitch_events(raw_events: Iterable[Any]) -> list[dict]:
    """Normalize Basic Pitch tuple, dict and object event variants."""
    normalized = []
    for raw in raw_events:
        if isinstance(raw, (tuple, list)) and len(raw) >= 4:
            start, end, midi, amplitude = raw[:4]
            bends = raw[4] if len(raw) > 4 else None
        else:
            start = _read_note_value(raw, ("start_time_s", "start_time", "start"))
            end = _read_note_value(raw, ("end_time_s", "end_time", "end"))
            midi = _read_note_value(raw, ("pitch_midi", "midi_pitch", "midi", "pitch"))
            amplitude = _read_note_value(raw, ("amplitude", "confidence", "velocity"), .7)
            bends = _read_note_value(raw, ("pitch_bends", "bends"))
        try:
            start_f, end_f = float(start), float(end)
            midi_i, amplitude_f = int(round(float(midi))), float(amplitude)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(start_f) and math.isfinite(end_f) and end_f > start_f):
            continue
        if not 0 <= midi_i <= 127 or end_f-start_f < .035:
            continue
        if amplitude_f > 1.0:
            amplitude_f /= 127.0
        has_bends = bends is not None
        if isinstance(bends, (list, tuple, np.ndarray)):
            has_bends = len(bends) > 0
        normalized.append({
            "start_s": max(0.0, start_f), "end_s": end_f, "midi": midi_i,
            "amplitude": max(0.0, min(1.0, amplitude_f)),
            "has_pitch_bends": bool(has_bends),
        })
    normalized.sort(key=lambda row: (row["start_s"], row["midi"], row["end_s"]))
    return normalized


def basic_pitch_events(source: Path) -> list[dict]:
    if not importlib.util.find_spec("basic_pitch"):
        raise TranscriptionError(f"Basic Pitch ist nicht installiert. {_engine_install_hint()}")
    try:
        from basic_pitch.inference import predict
        _model_output, _midi_data, raw_events = predict(str(source))
    except Exception as exc:  # optional engines expose several backend errors
        raise TranscriptionError(f"Basic Pitch ist fehlgeschlagen: {exc}") from exc
    return normalize_basic_pitch_events(raw_events)


def _merge_contiguous_notes(notes: list[dict], maximum_gap: float = .055) -> list[dict]:
    by_pitch: dict[int, list[dict]] = defaultdict(list)
    for note in notes:
        by_pitch[int(note["midi"])].append(dict(note))
    merged: list[dict] = []
    for pitch_notes in by_pitch.values():
        pitch_notes.sort(key=lambda row: (row["start_s"], row["end_s"]))
        for note in pitch_notes:
            if (merged and merged[-1]["midi"] == note["midi"] and
                    note["start_s"] <= merged[-1]["end_s"]+maximum_gap):
                merged[-1]["end_s"] = max(merged[-1]["end_s"], note["end_s"])
                merged[-1]["amplitude"] = max(merged[-1]["amplitude"], note["amplitude"])
                merged[-1]["has_pitch_bends"] = (
                    merged[-1].get("has_pitch_bends", False) or
                    note.get("has_pitch_bends", False))
            else:
                merged.append(note)
    merged.sort(key=lambda row: (row["start_s"], row["midi"]))
    return merged


def split_tonal_notes(notes: list[dict], *, stem_role: str = "mix") -> dict[str, list[dict]]:
    """Separate normalized notes into editable bass/harmony/melody roles."""
    roles = {name: [] for name in TONAL_TRACKS}
    if stem_role == "bass":
        # Demucs bass can make Basic Pitch emit upper harmonics. Keep the
        # strongest low note per near-simultaneous attack.
        grouped: list[list[dict]] = []
        for note in notes:
            if not grouped or note["start_s"]-grouped[-1][0]["start_s"] > .045:
                grouped.append([note])
            else:
                grouped[-1].append(note)
        for group in grouped:
            lows = [row for row in group if row["midi"] <= 64] or group
            roles["bass"].append(max(lows, key=lambda row: (row["amplitude"], -row["midi"])))
        roles["bass"] = _merge_contiguous_notes(roles["bass"])
        return roles

    groups: list[list[dict]] = []
    for note in notes:
        if not groups or note["start_s"]-groups[-1][0]["start_s"] > .045:
            groups.append([note])
        else:
            groups[-1].append(note)
    for group in groups:
        low = [row for row in group if row["midi"] < 52]
        upper = [row for row in group if row["midi"] >= 52]
        if low:
            roles["bass"].append(max(low, key=lambda row: row["amplitude"]))
        if len(upper) == 1:
            roles["melody"].append(upper[0])
        elif upper:
            melody = max(upper, key=lambda row: (row["midi"], row["amplitude"]))
            roles["melody"].append(melody)
            roles["harmony"].extend(row for row in upper if row is not melody)
    return {role: _merge_contiguous_notes(rows) for role, rows in roles.items()}


def _band_peak(magnitude: np.ndarray, frequencies: np.ndarray, frequency: float) -> float:
    width = max(7.0, frequency*.018)
    selected = magnitude[(frequencies >= frequency-width) & (frequencies <= frequency+width)]
    return float(np.max(selected)) if len(selected) else 0.0


def _segment_pitch_candidates(segment: np.ndarray, *, maximum: int = 4) -> list[tuple[int, float]]:
    if len(segment) < 256 or float(np.max(np.abs(segment))) < 1e-5:
        return []
    frame = segment.astype(np.float64)
    frame -= float(np.mean(frame))
    n_fft = min(65536, max(8192, 1 << int(math.ceil(math.log2(len(frame))))))
    magnitude = np.abs(np.fft.rfft(frame*np.hanning(len(frame)), n=n_fft))
    frequencies = np.fft.rfftfreq(n_fft, 1.0/SR)
    scores = []
    fundamentals = []
    for midi in range(28, 97):
        fundamental = 440.0*2**((midi-69)/12)
        harmonic_values = [
            _band_peak(magnitude, frequencies, fundamental*harmonic)
            for harmonic in range(1, 6) if fundamental*harmonic < 10_000
        ]
        if not harmonic_values:
            scores.append(0.0)
            fundamentals.append(0.0)
            continue
        weighted = sum(value/weight for value, weight in zip(harmonic_values, (1.0, 1.7, 2.5, 3.3, 4.1)))
        support = harmonic_values[0]/(max(harmonic_values)+1e-20)
        scores.append(weighted*(.32+.68*support))
        fundamentals.append(harmonic_values[0])
    values = np.asarray(scores, dtype=float)
    if not np.any(values > 0):
        return []
    local_maxima = [
        index for index in range(1, len(values)-1)
        if values[index] >= values[index-1] and values[index] > values[index+1]
    ]
    peak = float(np.max(values))
    floor = max(float(np.percentile(values, 78)), peak*.20)
    candidates = []
    for index in local_maxima:
        if values[index] < floor:
            continue
        confidence = float(values[index]/(peak+1e-20))
        if fundamentals[index] < float(np.max(magnitude))*.012:
            confidence *= .70
        candidates.append((28+index, confidence))
    candidates.sort(key=lambda row: row[1], reverse=True)
    selected: list[tuple[int, float]] = []
    for midi, confidence in candidates:
        if any(abs(midi-existing) <= 1 for existing, _ in selected):
            continue
        selected.append((midi, confidence))
        if len(selected) >= maximum:
            break
    return sorted(selected, key=lambda row: row[0])


def dsp_pitch_events(source: Path, profile: dict) -> tuple[list[dict], dict[str, Any]]:
    """Conservative onset-aligned multi-pitch fallback without ML models."""
    stereo = decode_audio(source)
    mono = stereo.mean(axis=1)
    source_events = [
        row for row in profile.get("events", [])
        if row.get("family") in {"tonal", "sub", "body"}
        and float(row.get("flatness", 0.0)) <= .075
    ]
    notes: list[dict] = []
    for index, event in enumerate(source_events):
        start = float(event["time"])
        next_start = (float(source_events[index+1]["time"])
                      if index+1 < len(source_events) else start+.65)
        analysis_end = min(len(mono)/SR, start+.42, max(start+.09, next_start-.008))
        a = max(0, int(round((start+.012)*SR)))
        b = min(len(mono), int(round(analysis_end*SR)))
        candidates = _segment_pitch_candidates(mono[a:b])
        if not candidates:
            continue
        duration = max(.06, min(2.0, next_start-start-.012))
        strength = max(.04, min(1.0, float(event.get("strength", .5))))
        for midi, confidence in candidates:
            if confidence < .28:
                continue
            notes.append({
                "start_s": start, "end_s": start+duration, "midi": midi,
                "amplitude": max(.08, min(1.0, strength*(.60+.40*confidence))),
                "has_pitch_bends": False, "dsp_confidence": confidence,
            })
    notes = _merge_contiguous_notes(notes)
    return notes, {
        "candidate_onsets": len(source_events), "note_events": len(notes),
        "method": "onset-aligned-harmonic-spectrum",
    }


def detect_content(profile: dict) -> dict[str, Any]:
    events = profile.get("events", [])
    families = Counter(str(row.get("family", "unknown")) for row in events)
    count = max(1, len(events))
    percussive_share = sum(families[name] for name in (
        "sub", "body", "click", "tick", "air", "noise"))/count
    decays = [float(row.get("decay_seconds", 0.0)) for row in events]
    median_decay = statistics.median(decays) if decays else 0.0
    events_per_bar = float(profile.get("generation_targets", {}).get(
        "events_per_bar", len(events)/max(1, profile.get("arrangement", {}).get("bars", 1))))
    percussion = (
        percussive_share >= .53 or
        (median_decay <= .11 and events_per_bar >= 5.0)
    )
    return {
        "detected": "percussion" if percussion else "full",
        "percussive_family_share": round(percussive_share, 4),
        "median_event_decay_seconds": round(median_decay, 4),
        "events_per_bar": round(events_per_bar, 3),
    }


def transcribe_tonal_events(
    source: Path,
    stems: dict[str, Path],
    profile: dict,
    *,
    engine: str,
    content: str,
) -> tuple[dict[str, list[dict]], dict[str, Any]]:
    roles = {name: [] for name in TONAL_TRACKS}
    if engine == "off" or content == "percussion":
        return roles, {"requested": engine, "used": "off", "note_events": 0}

    available = bool(importlib.util.find_spec("basic_pitch"))
    selected = engine
    if engine == "auto":
        selected = "basic-pitch" if available else "dsp"
    if selected == "basic-pitch" and not available:
        raise TranscriptionError(f"Basic Pitch ist nicht installiert. {_engine_install_hint()}")

    details: dict[str, Any] = {}
    bends = 0
    if selected == "basic-pitch":
        inputs = []
        if "bass" in stems:
            inputs.append(("bass", stems["bass"]))
        if "other" in stems:
            inputs.append(("other", stems["other"]))
        if not inputs:
            inputs.append(("mix", source))
        for stem_role, path in inputs:
            notes = basic_pitch_events(path)
            bends += sum(bool(row.get("has_pitch_bends")) for row in notes)
            split = split_tonal_notes(notes, stem_role=stem_role)
            for role, values in split.items():
                roles[role].extend(values)
            details[stem_role] = len(notes)
    elif selected == "dsp":
        notes, dsp_report = dsp_pitch_events(source, profile)
        split = split_tonal_notes(notes)
        for role, values in split.items():
            roles[role].extend(values)
        details["mix"] = dsp_report
    else:
        raise ValueError(f"Unknown pitch engine: {engine}")

    for role in roles:
        roles[role] = _merge_contiguous_notes(roles[role])
    return roles, {
        "requested": engine, "used": selected,
        "note_events": sum(len(values) for values in roles.values()),
        "notes_by_role": {role: len(values) for role, values in roles.items()},
        "pitch_bend_events_flattened": bends,
        "details": details,
    }


def _tonal_score_note(note: dict, beat_seconds: float) -> dict:
    amplitude = max(0.0, min(1.0, float(note.get("amplitude", .7))))
    return {
        "midi": int(note["midi"]),
        "start": round(max(0.0, float(note["start_s"])/beat_seconds), 6),
        "duration": round(max(.04, (float(note["end_s"])-float(note["start_s"]))/beat_seconds), 6),
        "velocity": int(round(28+94*amplitude)),
        "nexpt_source_time_seconds": round(float(note["start_s"]), 5),
        "nexpt_confidence": round(float(note.get("dsp_confidence", amplitude)), 4),
    }


def build_transcription_score(
    profile: dict,
    drum_tracks: dict[str, list[dict]],
    tonal_tracks: dict[str, list[dict]],
    *,
    bpm: float,
    duration_seconds: float,
    engines: dict[str, Any],
    content: dict[str, Any],
) -> tuple[dict, dict[str, Any]]:
    """Build Bridge Score Spec v1 while retaining absolute source timing."""
    beat_seconds = 60.0/bpm
    parts = []
    for role, config in DRUM_TRACKS.items():
        notes = [dict(row) for row in drum_tracks.get(role, [])]
        if not notes:
            continue
        parts.append({
            "id": role, "name": config["name"], "instrument": config["instrument"],
            "is_percussion": True, "channel": config["channel"],
            "mix": config["mix"], "notes": notes,
            "nexpt_role": "drums",
        })
    for role, config in TONAL_TRACKS.items():
        notes = [_tonal_score_note(row, beat_seconds) for row in tonal_tracks.get(role, [])]
        if not notes:
            continue
        parts.append({
            "id": role, "name": config["name"], "instrument": config["instrument"],
            "program": config["program"], "channel": config["channel"],
            "mix": config["mix"], "notes": notes,
            "nexpt_role": role,
        })

    # The silent note keeps GarageBand's imported project at the exact source
    # duration, including an incomplete final bar. MIDI 0 is outside normal
    # kit mappings. Prefer an existing drum part so it creates no extra track.
    anchor_start = max(0.0, duration_seconds/beat_seconds-.05)
    anchor = {
        "midi": 0, "start": round(anchor_start, 6), "duration": .05,
        "velocity": 1, "nexpt_timeline_anchor": True,
    }
    percussion = next((part for part in parts if part.get("is_percussion")), None)
    if percussion is None:
        config = DRUM_TRACKS["drums-detail"]
        percussion = {
            "id": "timeline-anchor", "name": "Transcribed Timeline",
            "instrument": "drum kit", "is_percussion": True,
            "channel": config["channel"], "mix": config["mix"],
            "notes": [], "nexpt_role": "timeline",
        }
        parts.append(percussion)
    percussion["notes"].append(anchor)
    percussion["notes"].sort(key=lambda row: (row["start"], row.get("midi", -1)))

    source = profile.get("source", {})
    score = {
        "format": "garageband_score_spec_v1",
        "title": f"Transcription — {source.get('file_name', 'instrumental')}",
        "bpm": round(float(bpm), 5), "time_signature": "4/4", "parts": parts,
        "nexpt": {
            "schema_version": 2, "generator": "garageband/transcribe.py",
            "mode": "source-transcription",
            "source": {
                "file_name": source.get("file_name"), "sha256": source.get("sha256"),
                "duration_seconds": round(duration_seconds, 6),
            },
            "content": content, "engines": engines,
            "timing": (
                "Starts are source seconds converted to beats at project BPM; "
                "measured microtiming and event order are preserved."
            ),
            "principle": (
                "Editable MIDI transcription; no source waveform or source sample "
                "is embedded in the score."
            ),
            "limit": (
                "A stereo master cannot reveal the exact original samples, plug-ins, "
                "automation or perfectly isolated performances."
            ),
        },
    }
    sounding = [
        note for part in parts for note in part["notes"]
        if not note.get("nexpt_timeline_anchor")
    ]
    report = {
        "tracks": len(parts), "score_notes": len(sounding)+1,
        "sounding_notes": len(sounding),
        "duration_seconds": round(duration_seconds, 6),
        "duration_beats": round(duration_seconds/beat_seconds, 6),
        "notes_by_track": {
            part["name"]: sum(not note.get("nexpt_timeline_anchor") for note in part["notes"])
            for part in parts
        },
    }
    return score, report


def build_garageband_preset(score: dict) -> dict:
    tracks = []
    for index, part in enumerate(score["parts"], start=1):
        role = str(part.get("nexpt_role", "drums"))
        if role == "timeline":
            patch = PATCHES["drums"]
        elif role in {"bass", "harmony", "melody"}:
            patch = PATCHES[role]
        else:
            patch = PATCHES["drums"]
        mix = part.get("mix", {})
        tracks.append({
            "part": part["name"], "fallback_index": index,
            "patch": dict(patch),
            "volume": str(mix.get("volume", .75)),
            "pan": str(mix.get("pan", 0)),
        })
    return {
        "schema_version": 1,
        "name": "NEXPT Audio Transcription",
        "description": "Generated patch plan for an editable audio transcription.",
        "tracks": tracks,
        "export": {"format": "WAVE", "timeout_seconds": 360},
    }


def _write_json(path: Path, payload: dict) -> Path:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return path


def transcribe_audio(
    source: Path,
    *,
    score_path: Path,
    midi_path: Path,
    preset_path: Path,
    report_path: Path,
    profile_path: Path,
    work_dir: Path,
    bpm_hint: float | None = None,
    downbeat_hint: float | None = None,
    quality: str = "auto",
    separation: str | None = None,
    pitch_engine: str | None = None,
    content_mode: str = "auto",
    demucs_model: str = "htdemucs",
    device: str = "cpu",
) -> dict[str, Any]:
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if quality not in {"auto", "high", "fast"}:
        raise ValueError(f"Unknown quality: {quality}")
    if content_mode not in {"auto", "full", "percussion"}:
        raise ValueError(f"Unknown content mode: {content_mode}")

    separation = separation or ({"high": "demucs", "fast": "off"}.get(quality, "auto"))
    pitch_engine = pitch_engine or ({"high": "basic-pitch", "fast": "dsp"}.get(quality, "auto"))
    work_dir.mkdir(parents=True, exist_ok=True)

    mix_profile = analyze_reference(
        source, bpm_hint=bpm_hint, downbeat_hint=downbeat_hint,
        include_events=True, ebu=False,
    )
    bpm = float(mix_profile["tempo"]["bpm"])
    downbeat = float(mix_profile["tempo"]["downbeat_seconds"])
    duration = float(mix_profile["source"]["duration_seconds_decoded"])
    detected_content = detect_content(mix_profile)
    selected_content = (detected_content["detected"]
                        if content_mode == "auto" else content_mode)
    content_report = {
        **detected_content, "requested": content_mode, "used": selected_content,
    }

    stems, separation_report = separate_stems(
        source, work_dir, mode=separation, model=demucs_model, device=device)
    drum_profile = mix_profile
    if "drums" in stems:
        drum_profile = analyze_reference(
            stems["drums"], bpm_hint=bpm, downbeat_hint=downbeat,
            include_events=True, ebu=False,
        )
    drum_tracks, drum_report = transcribe_drum_events(
        drum_profile, bpm=bpm, isolated="drums" in stems,
        # In an explicitly percussion-dominant source, tonal attacks are very
        # often toms/wood/metal rather than melodic notes. Keep the complete
        # detected event sequence instead of discarding the uncertain hits.
        confidence_threshold=.45 if selected_content == "percussion" else None,
    )
    tonal_tracks, pitch_report = transcribe_tonal_events(
        source, stems, mix_profile, engine=pitch_engine, content=selected_content)
    engines = {"separation": separation_report, "pitch": pitch_report}
    score, score_report = build_transcription_score(
        mix_profile, drum_tracks, tonal_tracks, bpm=bpm,
        duration_seconds=duration, engines=engines, content=content_report)
    preset = build_garageband_preset(score)

    _write_json(profile_path, mix_profile)
    written = write_score(score, score_path, midi_path)
    _write_json(preset_path, preset)
    confidence_components = [drum_report["mean_confidence"]]
    if pitch_report["used"] == "basic-pitch":
        confidence_components.append(.82)
    elif pitch_report["used"] == "dsp":
        confidence_components.append(.48)
    overall_confidence = statistics.fmean(confidence_components)
    report = {
        "schema_version": 1, "mode": "source-transcription",
        "source": mix_profile["source"],
        "tempo": mix_profile["tempo"], "content": content_report,
        "engines": engines, "drums": drum_report, "score": score_report,
        "quality": {
            "requested": quality, "estimated_confidence": round(overall_confidence, 4),
            "arrangement_and_timing": "source event order retained",
            "sound_identity": "GarageBand patches approximate the source instruments",
            "one_to_one_claim": False,
        },
        "outputs": {
            "profile": str(profile_path.resolve()), "score": str(Path(written["score"])),
            "midi": str(midi_path.resolve()), "preset": str(preset_path.resolve()),
            "reference_audio": str(source),
            "report": str(report_path.resolve()),
        },
        "limitations": [
            "Original samples, plug-ins, automation and exact stems are not recoverable from a stereo mix.",
            "Pitch bends are flattened because Bridge Score Spec v1 stores note events, not continuous pitch curves.",
            "GarageBand Library patch names and installed Sound Library content vary between Macs.",
        ],
        "rights_note": "Use and publish the transcription only where you have the necessary rights.",
    }
    _write_json(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help="instrumental MP3/M4A/WAV")
    parser.add_argument("--doctor", action="store_true", help="only show optional engine availability")
    parser.add_argument("--quality", choices=("auto", "high", "fast"), default="auto")
    parser.add_argument("--separate", choices=("auto", "demucs", "off"))
    parser.add_argument("--pitch-engine", choices=("auto", "basic-pitch", "dsp", "off"))
    parser.add_argument("--content", choices=("auto", "full", "percussion"), default="auto")
    parser.add_argument("--bpm", type=float)
    parser.add_argument("--downbeat", type=float)
    parser.add_argument("--demucs-model", default="htdemucs")
    parser.add_argument("--device", choices=("cpu", "cuda", "mps"), default="cpu")
    parser.add_argument("--output", type=Path, help="Bridge Score JSON")
    parser.add_argument("--midi", type=Path)
    parser.add_argument("--preset-output", type=Path)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--profile-output", type=Path)
    parser.add_argument("--work-dir", type=Path,
                        help="keep Demucs work files here; default uses a temporary directory")
    return parser.parse_args()


def _display_path(path: str) -> str:
    value = Path(path)
    try:
        return str(value.relative_to(ROOT))
    except ValueError:
        return str(value)


def main() -> None:
    args = parse_args()
    if args.doctor:
        print(json.dumps(engine_availability(), ensure_ascii=False, indent=2))
        return
    if args.source is None:
        raise SystemExit("SOURCE fehlt (oder --doctor verwenden)")
    slug = slugify(args.source.stem)
    score = args.output or ROOT/"garageband"/"scores"/f"{slug}-transcription.json"
    midi = args.midi or score.with_suffix(".mid")
    preset = args.preset_output or ROOT/"garageband"/"presets"/f"{slug}-transcription.json"
    report = args.report_output or ROOT/"out"/"analysis"/f"{slug}-transcription-report.json"
    profile = args.profile_output or ROOT/"out"/"analysis"/f"{slug}-transcription-profile.json"

    def run(work: Path) -> dict[str, Any]:
        return transcribe_audio(
            args.source, score_path=score, midi_path=midi, preset_path=preset,
            report_path=report, profile_path=profile, work_dir=work,
            bpm_hint=args.bpm, downbeat_hint=args.downbeat,
            quality=args.quality, separation=args.separate,
            pitch_engine=args.pitch_engine, content_mode=args.content,
            demucs_model=args.demucs_model, device=args.device,
        )

    try:
        if args.work_dir:
            result = run(args.work_dir.resolve())
        else:
            with tempfile.TemporaryDirectory(prefix="nexpt-transcribe-") as directory:
                result = run(Path(directory))
    except (TranscriptionError, FileNotFoundError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    print(f"Transkription: {result['score']['sounding_notes']} klingende Noten/Hits")
    print(f"BPM: {result['tempo']['bpm']:.3f} · Dauer: {result['score']['duration_seconds']:.3f}s")
    print(f"Stem-Engine: {result['engines']['separation']['used']}")
    print(f"Pitch-Engine: {result['engines']['pitch']['used']}")
    for name in ("score", "midi", "preset", "report"):
        print(f"{name.capitalize()}: {_display_path(result['outputs'][name])}")
    print(f"Reference: {_display_path(result['outputs']['reference_audio'])}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Measure an exported reconstruction against its unchanged audio reference.

The report focuses on facts that survive a change of GarageBand instrument:
duration, event timing, tempo/rhythm structure, frequency balance and global
pitch-class content. It is a technical A/B gate, not a claim that a stereo
master has been reverse-engineered sample-for-sample.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Iterable

import numpy as np
from scipy import signal


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RENDER = ROOT/"render"
if str(RENDER) not in sys.path:
    sys.path.insert(0, str(RENDER))

from reference_analyzer import (  # noqa: E402
    SR,
    analyze_reference,
    decode_audio,
    file_sha256,
)
from reference_compare import similarity_report  # noqa: E402


class EvaluationError(RuntimeError):
    """The reference/export comparison could not be completed."""


def _event_times(profile: dict[str, Any]) -> list[float]:
    values = []
    for row in profile.get("events", []):
        try:
            value = float(row["time"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0:
            values.append(value)
    return sorted(values)


def estimate_event_offset(
    reference_times: Iterable[float],
    candidate_times: Iterable[float],
    *,
    maximum_seconds: float = .50,
    bin_seconds: float = .01,
) -> float:
    """Estimate candidate-minus-reference latency from local onset pairs."""
    reference = list(reference_times)
    candidate = list(candidate_times)
    differences = [
        candidate_time-reference_time
        for reference_time in reference
        for candidate_time in candidate
        if abs(candidate_time-reference_time) <= maximum_seconds
    ]
    if not differences:
        return 0.0
    bins = Counter(int(round(value/bin_seconds)) for value in differences)
    best_bin = max(bins, key=lambda key: (bins[key], -abs(key)))
    close = [
        value for value in differences
        if abs(value-best_bin*bin_seconds) <= bin_seconds*1.5
    ]
    return float(np.median(close or [best_bin*bin_seconds]))


def event_match_metrics(
    reference_times: Iterable[float],
    candidate_times: Iterable[float],
    *,
    tolerance_seconds: float = .065,
) -> dict[str, Any]:
    """Greedily match ordered onsets after compensating constant latency."""
    reference = sorted(float(value) for value in reference_times)
    candidate = sorted(float(value) for value in candidate_times)
    offset = estimate_event_offset(reference, candidate)
    aligned = [value-offset for value in candidate]
    left = right = matches = 0
    errors: list[float] = []
    while left < len(reference) and right < len(aligned):
        delta = aligned[right]-reference[left]
        if abs(delta) <= tolerance_seconds:
            matches += 1
            errors.append(abs(delta))
            left += 1
            right += 1
        elif delta < -tolerance_seconds:
            right += 1
        else:
            left += 1
    precision = matches/max(1, len(candidate))
    recall = matches/max(1, len(reference))
    f1 = 2*precision*recall/max(1e-12, precision+recall)
    median_error = float(np.median(errors)) if errors else None
    return {
        "reference_events": len(reference),
        "candidate_events": len(candidate),
        "matched_events": matches,
        "tolerance_seconds": tolerance_seconds,
        "estimated_candidate_latency_seconds": round(offset, 6),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "median_absolute_timing_error_seconds": (
            round(median_error, 6) if median_error is not None else None),
    }


def chroma_vector(audio: np.ndarray, sample_rate: int = SR) -> np.ndarray:
    """Return a normalized pitch-class energy vector without librosa."""
    if audio.ndim == 2:
        mono = audio.mean(axis=1)
    else:
        mono = np.asarray(audio, dtype=float)
    if len(mono) < 1024 or float(np.max(np.abs(mono))) < 1e-8:
        return np.zeros(12, dtype=float)
    frequencies, _times, spectrum = signal.stft(
        mono, fs=sample_rate, window="hann", nperseg=4096,
        noverlap=3072, boundary=None, padded=False,
    )
    power = np.square(np.abs(spectrum), dtype=np.float64).sum(axis=1)
    keep = (frequencies >= 40.0) & (frequencies <= 5000.0)
    frequencies = frequencies[keep]
    power = power[keep]
    chroma = np.zeros(12, dtype=float)
    valid = frequencies > 0
    midi = np.rint(69+12*np.log2(frequencies[valid]/440.0)).astype(int)
    for pitch_class, value in zip(np.mod(midi, 12), power[valid]):
        chroma[int(pitch_class)] += float(value)
    norm = float(np.linalg.norm(chroma))
    return chroma/norm if norm > 0 else chroma


def chroma_cosine(reference: np.ndarray, candidate: np.ndarray) -> float:
    left = np.asarray(reference, dtype=float)
    right = np.asarray(candidate, dtype=float)
    denominator = float(np.linalg.norm(left)*np.linalg.norm(right))
    return max(0.0, min(1.0, float(np.dot(left, right))/denominator)) \
        if denominator > 0 else 0.0


def build_evaluation(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    reference_chroma: np.ndarray,
    candidate_chroma: np.ndarray,
    minimum_score: float = 70.0,
) -> dict[str, Any]:
    if not 0 <= minimum_score <= 100:
        raise ValueError("minimum_score must be between 0 and 100")
    structural = similarity_report(reference, candidate)
    events = event_match_metrics(_event_times(reference), _event_times(candidate))
    reference_duration = float(reference["source"]["duration_seconds_decoded"])
    candidate_duration = float(candidate["source"]["duration_seconds_decoded"])
    duration_ratio = candidate_duration/max(1e-9, reference_duration)
    duration_score = 100*math.exp(-abs(math.log(max(1e-9, duration_ratio)))/.10)
    chroma_score = 100*chroma_cosine(reference_chroma, candidate_chroma)
    event_score = 100*float(events["f1"])
    technical_score = (
        .35*chroma_score + .30*event_score +
        .20*float(structural["overall_score_0_100"]) + .15*duration_score
    )
    if technical_score >= 85:
        verdict = "strong_match"
    elif technical_score >= 70:
        verdict = "usable_match"
    elif technical_score >= 55:
        verdict = "review_required"
    else:
        verdict = "weak_match"
    findings = []
    if duration_score < 90:
        findings.append("The GarageBand export duration differs materially from the source.")
    if event_score < 70:
        findings.append("Many source attacks are missing, added or shifted in the reconstruction.")
    if chroma_score < 70:
        findings.append("The reconstructed pitch-class distribution differs from the source.")
    if structural["scores_0_100"].get("frequency_balance", 100) < 65:
        findings.append("The frequency balance differs; review patches, octaves and mix levels.")
    return {
        "schema_version": 1,
        "purpose": (
            "Technical A/B evaluation of an editable GarageBand reconstruction; "
            "not sample identity or proof of recovered original stems."
        ),
        "technical_score_0_100": round(technical_score, 1),
        "minimum_score": minimum_score,
        "passed": technical_score >= minimum_score,
        "verdict": verdict,
        "component_scores_0_100": {
            "pitch_class_content": round(chroma_score, 1),
            "event_timing": round(event_score, 1),
            "structure_and_timbre": structural["overall_score_0_100"],
            "duration": round(duration_score, 1),
        },
        "duration": {
            "reference_seconds": round(reference_duration, 6),
            "candidate_seconds": round(candidate_duration, 6),
            "ratio": round(duration_ratio, 6),
        },
        "event_alignment": events,
        "structural_profile": structural,
        "findings": findings,
        "limitations": [
            "Global chroma compares pitch classes, not exact voicing, octave or continuous pitch bends.",
            "Onset matching measures timing but cannot prove which instrument produced each event.",
            "Different GarageBand patches may sound unlike the source even when notes and timing match.",
            "Only the unchanged reference track is a bit-for-bit copy of the supplied source file.",
        ],
    }


def evaluate_files(
    reference_path: Path,
    candidate_path: Path,
    *,
    bpm: float | None = None,
    downbeat: float | None = None,
    minimum_score: float = 70.0,
) -> dict[str, Any]:
    reference_path = reference_path.resolve()
    candidate_path = candidate_path.resolve()
    for label, path in (("Reference", reference_path), ("Candidate", candidate_path)):
        if not path.is_file():
            raise EvaluationError(f"{label} audio does not exist: {path}")
    reference = analyze_reference(
        reference_path, bpm_hint=bpm, downbeat_hint=downbeat,
        include_events=True, ebu=False,
    )
    effective_bpm = bpm or float(reference["tempo"]["bpm"])
    effective_downbeat = (
        downbeat if downbeat is not None else
        float(reference["tempo"]["downbeat_seconds"])
    )
    candidate = analyze_reference(
        candidate_path, bpm_hint=effective_bpm, downbeat_hint=effective_downbeat,
        include_events=True, ebu=False,
    )
    result = build_evaluation(
        reference, candidate,
        reference_chroma=chroma_vector(decode_audio(reference_path)),
        candidate_chroma=chroma_vector(decode_audio(candidate_path)),
        minimum_score=minimum_score,
    )
    result["reference"] = {
        "path": str(reference_path), "sha256": file_sha256(reference_path),
    }
    result["candidate"] = {
        "path": str(candidate_path), "sha256": file_sha256(candidate_path),
    }
    return result


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="unchanged source MP3/M4A/WAV")
    parser.add_argument("candidate", type=Path, help="GarageBand reconstruction export")
    parser.add_argument("--output", type=Path,
                        default=ROOT/"out"/"analysis"/"garageband-ab-report.json")
    parser.add_argument("--bpm", type=float)
    parser.add_argument("--downbeat", type=float)
    parser.add_argument("--minimum-score", type=float, default=70.0)
    parser.add_argument("--strict", action="store_true",
                        help="exit with status 2 when the minimum score is missed")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = evaluate_files(
            args.reference, args.candidate, bpm=args.bpm,
            downbeat=args.downbeat, minimum_score=args.minimum_score,
        )
    except (EvaluationError, RuntimeError, OSError, ValueError,
            subprocess.SubprocessError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    _write_json_atomic(args.output, result)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "technical_score_0_100": result["technical_score_0_100"],
        "passed": result["passed"],
        "verdict": result["verdict"],
        "findings": result["findings"],
    }, ensure_ascii=False, indent=2))
    if args.strict and not result["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

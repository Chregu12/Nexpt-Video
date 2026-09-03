#!/usr/bin/env python3
"""Create an auditable music/speech/SFX confidence map for local audio."""
from __future__ import annotations

import importlib.metadata
import importlib.util
from pathlib import Path
import subprocess
from typing import Any, Iterable

import numpy as np

from reference_analyzer import decode_audio, file_sha256  # type: ignore


SAMPLE_RATE = 48_000
SEGMENT_SCHEMA_VERSION = 1
SILERO_SAMPLE_RATE = 16_000


class SegmentationError(RuntimeError):
    """Speech detection or segment analysis could not be completed."""


def _round(value: float, digits: int = 4) -> float:
    if not np.isfinite(value):
        return 0.0
    return round(float(value), digits)


def _clip(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def silero_available() -> bool:
    try:
        return importlib.util.find_spec("silero_vad") is not None
    except (ImportError, ValueError):
        return False


def silero_version() -> str | None:
    if not silero_available():
        return None
    for package in ("silero-vad", "silero_vad"):
        try:
            return importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "installed"


def speech_backend_status() -> dict[str, Any]:
    return {
        "silero": {
            "available": silero_available(),
            "version": silero_version(),
            "purpose": "speech timestamps; no audio is uploaded",
        },
        "heuristic": {
            "available": True,
            "version": "nexpt-1",
            "purpose": "low-confidence local fallback, not a trained VAD",
        },
    }


def _silero_intervals(path: Path) -> list[dict[str, float]]:
    if not silero_available():
        raise SegmentationError(
            "Silero VAD fehlt. Installiere garageband/requirements-transcription.txt "
            "oder waehle --vad heuristic ausdruecklich."
        )
    try:
        from silero_vad import (  # type: ignore
            get_speech_timestamps,
            load_silero_vad,
            read_audio,
        )

        model = load_silero_vad()
        waveform = read_audio(str(path), sampling_rate=SILERO_SAMPLE_RATE)
        timestamps = get_speech_timestamps(
            waveform,
            model,
            sampling_rate=SILERO_SAMPLE_RATE,
            return_seconds=True,
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise SegmentationError(f"Silero VAD ist fehlgeschlagen: {exc}") from exc

    intervals: list[dict[str, float]] = []
    for item in timestamps:
        start = float(item["start"])
        end = float(item["end"])
        if end > start >= 0:
            intervals.append({"start": _round(start, 6), "end": _round(end, 6)})
    return intervals


def interval_overlap(
    start: float,
    end: float,
    intervals: Iterable[dict[str, float]],
) -> float:
    """Return the fraction of ``start:end`` covered by merged intervals."""

    if end <= start:
        return 0.0
    clipped: list[tuple[float, float]] = []
    for item in intervals:
        left = max(start, float(item["start"]))
        right = min(end, float(item["end"]))
        if right > left:
            clipped.append((left, right))
    if not clipped:
        return 0.0
    clipped.sort()
    merged: list[list[float]] = []
    for left, right in clipped:
        if not merged or left > merged[-1][1]:
            merged.append([left, right])
        else:
            merged[-1][1] = max(merged[-1][1], right)
    covered = sum(right - left for left, right in merged)
    return _clip(covered / (end - start))


def _band_share(power: np.ndarray, frequencies: np.ndarray, low: float, high: float) -> float:
    total = float(np.sum(power)) + 1e-15
    selected = power[(frequencies >= low) & (frequencies < high)]
    return _clip(float(np.sum(selected)) / total)


def _features(frame: np.ndarray) -> dict[str, float]:
    mono = np.mean(frame, axis=1, dtype=np.float64)
    rms = float(np.sqrt(np.mean(np.square(mono)) + 1e-15))
    peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
    rms_dbfs = 20.0 * np.log10(max(rms, 1e-12))
    crest_db = 20.0 * np.log10(max(peak, 1e-12) / max(rms, 1e-12))

    if len(mono) < 8:
        return {
            "rms_dbfs": _round(rms_dbfs, 2),
            "crest_db": _round(crest_db, 2),
            "spectral_centroid_hz": 0.0,
            "spectral_flatness": 0.0,
            "zero_crossing_rate": 0.0,
            "speech_band_share": 0.0,
            "bass_share": 0.0,
            "high_share": 0.0,
            "stereo_width": 0.0,
            "transient_strength": 0.0,
            "tonal_strength": 0.0,
        }

    windowed = mono * np.hanning(len(mono))
    spectrum = np.fft.rfft(windowed)
    power = np.square(np.abs(spectrum)) + 1e-15
    frequencies = np.fft.rfftfreq(len(mono), 1.0 / SAMPLE_RATE)
    centroid = float(np.sum(frequencies * power) / np.sum(power))
    # Restrict flatness to the reliably encoded band.  AAC low-pass bins above
    # its cutoff otherwise make broadband noise look artificially tonal.
    flatness_band = power[(frequencies >= 50.0) & (frequencies <= 14_000.0)]
    flatness = float(
        np.exp(np.mean(np.log(flatness_band))) / np.mean(flatness_band)
    )
    zcr = float(np.mean(np.signbit(mono[1:]) != np.signbit(mono[:-1])))
    mid = (frame[:, 0].astype(np.float64) + frame[:, 1].astype(np.float64)) * 0.5
    side = (frame[:, 0].astype(np.float64) - frame[:, 1].astype(np.float64)) * 0.5
    stereo_width = float(
        np.sqrt(np.mean(np.square(side)) + 1e-15)
        / np.sqrt(np.mean(np.square(mid)) + 1e-15)
    )
    # Crest factor and short-block envelope changes provide a robust local
    # transient cue without depending on a learned SFX classifier.
    block = max(1, int(0.01 * SAMPLE_RATE))
    usable = len(mono) // block * block
    if usable:
        envelope = np.sqrt(
            np.mean(np.square(mono[:usable].reshape(-1, block)), axis=1) + 1e-15
        )
        envelope_jump = float(
            np.percentile(np.abs(np.diff(envelope)), 90) / max(np.mean(envelope), 1e-9)
        ) if len(envelope) > 1 else 0.0
    else:
        envelope_jump = 0.0
    transient = _clip(0.55 * ((crest_db - 6.0) / 18.0) + 0.45 * envelope_jump)
    tonal = _clip(1.0 - min(1.0, flatness * 12.0))
    return {
        "rms_dbfs": _round(rms_dbfs, 2),
        "crest_db": _round(crest_db, 2),
        "spectral_centroid_hz": _round(centroid, 1),
        "spectral_flatness": _round(flatness, 5),
        "zero_crossing_rate": _round(zcr, 5),
        "speech_band_share": _round(_band_share(power, frequencies, 120.0, 4_000.0)),
        "bass_share": _round(_band_share(power, frequencies, 40.0, 500.0)),
        "high_share": _round(_band_share(power, frequencies, 4_000.0, 18_000.0)),
        "stereo_width": _round(min(stereo_width, 2.0) / 2.0),
        "transient_strength": _round(transient),
        "tonal_strength": _round(tonal),
    }


def _probabilities(
    features: dict[str, float],
    *,
    speech_overlap: float,
    vad_engine: str,
) -> dict[str, float]:
    if features["rms_dbfs"] <= -60.0:
        return {"music": 0.01, "speech": 0.01, "sfx": 0.01, "silence": 0.97}

    tonal = features["tonal_strength"]
    transient = features["transient_strength"]
    flatness = _clip(features["spectral_flatness"] * 10.0)
    width = features["stereo_width"]
    speech_band = features["speech_band_share"]
    high = features["high_share"]
    bass = features["bass_share"]
    zcr_focus = _clip(1.0 - abs(features["zero_crossing_rate"] - 0.08) / 0.08)

    music_raw = (
        0.12 + 0.48 * tonal + 0.16 * bass + 0.12 * width + 0.12 * (1.0 - transient)
    ) * (1.0 - 0.70 * transient)
    speech_raw = (
        0.10 + 0.42 * speech_band + 0.18 * (1.0 - width) + 0.15 * zcr_focus
    ) * (1.0 - 0.40 * transient)
    raw = {
        "music": music_raw,
        "speech": speech_raw,
        "sfx": 0.08 + 0.75 * transient + 0.20 * flatness + 0.18 * high,
    }
    total = sum(raw.values())
    probs = {key: value / total for key, value in raw.items()}
    if vad_engine == "silero":
        speech = max(probs["speech"] * 0.35, 0.03 + 0.94 * speech_overlap)
        speech = min(speech, 0.98)
        remainder_before = probs["music"] + probs["sfx"]
        remainder_after = 1.0 - speech
        probs["music"] = remainder_after * probs["music"] / remainder_before
        probs["sfx"] = remainder_after * probs["sfx"] / remainder_before
        probs["speech"] = speech
    elif vad_engine == "off":
        speech = min(probs["speech"], 0.10)
        scale = (1.0 - speech) / (probs["music"] + probs["sfx"])
        probs["music"] *= scale
        probs["sfx"] *= scale
        probs["speech"] = speech
    probs["silence"] = 0.0
    return {key: _round(value) for key, value in probs.items()}


def analyze_segments(
    path: Path,
    *,
    vad: str = "auto",
    segment_seconds: float = 1.0,
    hop_seconds: float = 0.5,
) -> dict[str, Any]:
    """Measure local segments and return probabilities, provenance and caveats."""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SegmentationError(f"Audiodatei fehlt: {resolved}")
    if vad not in {"auto", "silero", "heuristic", "off"}:
        raise SegmentationError(f"Unbekannte VAD-Engine: {vad}")
    if not 0.25 <= segment_seconds <= 10.0:
        raise SegmentationError("segment_seconds muss zwischen 0.25 und 10 liegen")
    if not 0.1 <= hop_seconds <= segment_seconds:
        raise SegmentationError("hop_seconds muss zwischen 0.1 und segment_seconds liegen")

    if vad == "auto":
        vad_engine = "silero" if silero_available() else "heuristic"
    else:
        vad_engine = vad
    intervals = _silero_intervals(resolved) if vad_engine == "silero" else []
    try:
        audio = decode_audio(resolved, sample_rate=SAMPLE_RATE)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        raise SegmentationError(
            f"Segmentanalyse konnte Audio nicht dekodieren: {exc}"
        ) from exc
    duration = len(audio) / SAMPLE_RATE
    window_samples = max(1, round(segment_seconds * SAMPLE_RATE))
    hop_samples = max(1, round(hop_seconds * SAMPLE_RATE))
    segments: list[dict[str, Any]] = []
    totals = {"music": 0.0, "speech": 0.0, "sfx": 0.0, "silence": 0.0}
    dominant = {key: 0.0 for key in totals}
    analyzed_seconds = 0.0
    start_sample = 0
    while start_sample < len(audio):
        remaining_samples = len(audio) - start_sample
        # AAC and container time bases often leave a few padding samples.  Do
        # not turn a sub-100 ms encoder tail into a misleading extra segment.
        if segments and remaining_samples < min(hop_samples, int(0.1 * SAMPLE_RATE)):
            break
        end_sample = min(len(audio), start_sample + window_samples)
        start = start_sample / SAMPLE_RATE
        end = end_sample / SAMPLE_RATE
        measured = _features(audio[start_sample:end_sample])
        overlap = interval_overlap(start, end, intervals)
        probabilities = _probabilities(
            measured,
            speech_overlap=overlap,
            vad_engine=vad_engine,
        )
        label = max(probabilities, key=probabilities.get)
        weight = min(hop_seconds, duration - start)
        analyzed_seconds += weight
        for key, value in probabilities.items():
            totals[key] += value * weight
        dominant[label] += weight
        confidence = probabilities[label]
        segments.append(
            {
                "start_seconds": _round(start, 6),
                "end_seconds": _round(end, 6),
                "label": label,
                "confidence": confidence,
                "review_required": confidence < 0.55 or vad_engine != "silero",
                "probabilities": probabilities,
                "speech_overlap": _round(overlap),
                "features": measured,
            }
        )
        start_sample += hop_samples

    denominator = max(analyzed_seconds, 1e-9)
    summary_probabilities = {
        key: _round(value / denominator) for key, value in totals.items()
    }
    return {
        "schema_version": SEGMENT_SCHEMA_VERSION,
        "source": {
            "path": str(resolved),
            "sha256": file_sha256(resolved),
            "duration_seconds": _round(duration, 6),
        },
        "analysis": {
            "sample_rate": SAMPLE_RATE,
            "segment_seconds": segment_seconds,
            "hop_seconds": hop_seconds,
            "vad": {
                "engine": vad_engine,
                "version": silero_version() if vad_engine == "silero" else "nexpt-1",
                "reliable_speech_timestamps": vad_engine == "silero",
                "intervals": intervals,
            },
            "classifier": {
                "engine": "nexpt-spectral-heuristic-v1",
                "trained_model": False,
                "contract": (
                    "Probabilities are routing signals for review, not ground-truth source labels."
                ),
            },
        },
        "summary": {
            "mean_probabilities": summary_probabilities,
            "dominant_seconds": {
                key: _round(value, 3) for key, value in dominant.items()
            },
            "segment_count": len(segments),
            "analyzed_seconds": _round(analyzed_seconds, 6),
            "manual_review_required": vad_engine != "silero"
            or any(item["review_required"] for item in segments),
        },
        "segments": segments,
    }

#!/usr/bin/env python3
"""Eine Audio-Referenz in ein reproduzierbares, samplefreies Klangprofil uebersetzen.

Das Skript akzeptiert jedes von ffmpeg lesbare Audio- oder Videoformat. Es
speichert keine Ausschnitte der Quelle. Stattdessen misst es Tempo, Raster,
Groove, Dynamik, Stereobreite, Frequenzbalance, Anschlaege und Klangfamilien.
Dieses JSON ist die einzige Eingabe fuer ``reference_sound.py`` und
``music_reference.py``.

    python3 render/reference_analyzer.py referenz.m4a --bpm 118 --downbeat 0

Ausgabe: ``out/analysis/reference-profile.json``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy import signal

from audio_common import FFMPEG, OUT, SR, write_manifest


SCHEMA_VERSION = 1
HOP = 256
N_FFT = 2048
BANDS = (
    ("sub", 20.0, 80.0),
    ("bass", 80.0, 250.0),
    ("low_mid", 250.0, 800.0),
    ("mid", 800.0, 2500.0),
    ("presence", 2500.0, 6000.0),
    ("air", 6000.0, 18_000.0),
)


def _finite(value: float, fallback: float = 0.0) -> float:
    return float(value) if np.isfinite(value) else float(fallback)


def _round(value: float, digits: int = 4) -> float:
    return round(_finite(value), digits)


def _percentiles(values: Iterable[float], digits: int = 4) -> dict:
    data = np.asarray(list(values), dtype=np.float64)
    data = data[np.isfinite(data)]
    if not len(data):
        return {"p10": 0.0, "median": 0.0, "p90": 0.0}
    p10, median, p90 = np.percentile(data, (10, 50, 90))
    return {"p10": _round(p10, digits), "median": _round(median, digits),
            "p90": _round(p90, digits)}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ffprobe_binary() -> str | None:
    direct = shutil.which("ffprobe")
    if direct:
        return direct
    candidate = Path(FFMPEG).with_name("ffprobe") if FFMPEG else None
    return str(candidate) if candidate and candidate.exists() else None


def probe_media(path: Path) -> dict:
    ffprobe = _ffprobe_binary()
    if not ffprobe:
        return {}
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "a:0",
        "-show_entries",
        "format=duration,size,bit_rate,format_name:stream=codec_name,sample_rate,channels,channel_layout,bit_rate",
        "-of", "json", str(path),
    ]
    try:
        data = json.loads(subprocess.check_output(cmd, text=True))
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        return {}
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    return {
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "channel_layout": stream.get("channel_layout"),
        "bit_rate": int(stream.get("bit_rate") or fmt.get("bit_rate") or 0),
        "container": fmt.get("format_name"),
        "duration_seconds": _round(float(fmt.get("duration") or 0.0), 6),
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
    }


def decode_audio(path: Path, sample_rate: int = SR) -> np.ndarray:
    if not FFMPEG:
        raise RuntimeError("ffmpeg wurde nicht gefunden")
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vn", "-f", "f32le", "-acodec", "pcm_f32le",
        "-ar", str(sample_rate), "-ac", "2", "pipe:1",
    ]
    raw = subprocess.check_output(cmd)
    audio = np.frombuffer(raw, dtype="<f4")
    if len(audio) < 4 or len(audio) % 2:
        raise ValueError(f"{path} enthaelt kein dekodierbares Stereo-Audiosignal")
    return audio.reshape(-1, 2).copy()


def measure_ebu(path: Path) -> dict:
    """EBU-R128-Werte von ffmpeg lesen; bei alten Builds leer zurueckgeben."""
    cmd = [
        FFMPEG, "-hide_banner", "-nostats", "-i", str(path),
        "-filter_complex", "ebur128=peak=true", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              text=True, check=False)
    except OSError:
        return {}
    text = proc.stderr
    integrated = re.findall(r"\bI:\s*(-?\d+(?:\.\d+)?)\s+LUFS", text)
    lra = re.findall(r"\bLRA:\s*(-?\d+(?:\.\d+)?)\s+LU", text)
    peaks = re.findall(r"\bPeak:\s*(-?\d+(?:\.\d+)?)\s+dBFS", text)
    result = {}
    if integrated:
        result["integrated_lufs"] = float(integrated[-1])
    if lra:
        result["loudness_range_lu"] = float(lra[-1])
    if peaks:
        result["true_peak_dbtp"] = float(peaks[-1])
    return result


def _band_shares(power: np.ndarray, frequencies: np.ndarray) -> list[float]:
    shares = []
    total = float(power[(frequencies >= 20) & (frequencies < 18_000)].sum()) + 1e-20
    for _, low, high in BANDS:
        shares.append(float(power[(frequencies >= low) & (frequencies < high)].sum()) / total)
    return shares


def global_spectrum(mono: np.ndarray) -> dict:
    frequencies, power = signal.welch(
        mono, fs=SR, window="hann", nperseg=8192, noverlap=4096,
        detrend=False, scaling="spectrum",
    )
    shares = _band_shares(power, frequencies)
    centroid = float((power * frequencies).sum() / (power.sum() + 1e-20))
    cumulative = np.cumsum(power)
    roll_index = int(np.searchsorted(cumulative, cumulative[-1] * 0.85))
    return {
        "bands": {name: _round(value, 5) for (name, _, _), value in zip(BANDS, shares)},
        "centroid_hz": _round(centroid, 1),
        "rolloff_85_hz": _round(frequencies[min(roll_index, len(frequencies)-1)], 1),
    }


def spectral_flux(mono: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    frequencies, times, spectrum = signal.stft(
        mono, fs=SR, window="hann", nperseg=N_FFT,
        noverlap=N_FFT-HOP, boundary=None, padded=False,
    )
    keep = (frequencies >= 30) & (frequencies <= 18_000)
    magnitude = np.abs(spectrum[keep]).astype(np.float32, copy=False)
    compressed = np.log1p(magnitude * 80.0)
    flux = np.maximum(0.0, np.diff(compressed, axis=1)).sum(axis=0)
    frame_times = times[1:]
    del spectrum, magnitude, compressed

    flux = signal.medfilt(flux, 5)
    baseline_width = min(len(flux)//2*2-1, 201)
    baseline_width = max(3, baseline_width)
    baseline = signal.medfilt(flux, baseline_width)
    novelty = np.maximum(0.0, flux-baseline).astype(np.float64)
    return novelty, frame_times, SR/HOP


def detect_onsets(novelty: np.ndarray, frame_times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    positive = novelty[novelty > 0]
    if not len(positive):
        return np.array([], dtype=float), np.array([], dtype=float)
    prominence = max(float(np.percentile(positive, 58)), float(np.max(positive))*0.015)
    distance = max(1, int(round(0.045 * SR/HOP)))
    peaks, props = signal.find_peaks(novelty, distance=distance, prominence=prominence)
    if len(peaks) < 8:
        prominence = max(float(np.percentile(positive, 42)), float(np.max(positive))*0.008)
        peaks, props = signal.find_peaks(novelty, distance=distance, prominence=prominence)
    strengths = np.asarray(props.get("prominences", novelty[peaks]), dtype=np.float64)
    return frame_times[peaks], strengths


def _grid_error(onsets: np.ndarray, bpm: float, weights: np.ndarray | None = None) -> tuple[float, float]:
    if not len(onsets):
        return 0.0, 1.0
    step = 60.0/bpm/4.0
    phases = np.linspace(0.0, step, 384, endpoint=False)
    if weights is None or len(weights) != len(onsets):
        weights = np.ones(len(onsets))
    weights = np.maximum(weights, 1e-9)
    weights = weights/weights.sum()
    scores = []
    for phase in phases:
        distance = np.abs(((onsets-phase+step/2) % step)-step/2)
        scores.append(float(np.sum(np.minimum(distance, 0.045)*weights)))
    index = int(np.argmin(scores))
    return float(phases[index]), float(scores[index])


def estimate_tempo(novelty: np.ndarray, fps: float, onsets: np.ndarray,
                   strengths: np.ndarray) -> tuple[float, float, list[dict]]:
    if len(novelty) < int(fps*4):
        return 118.0, 0.0, []
    envelope = novelty-np.mean(novelty)
    autocorrelation = signal.fftconvolve(envelope, envelope[::-1], mode="full")[len(envelope)-1:]
    normalizer = float(autocorrelation[0]) + 1e-20
    low_lag = max(1, int(fps*60/180))
    high_lag = min(len(autocorrelation)-1, int(fps*60/60))
    peaks, _ = signal.find_peaks(autocorrelation[low_lag:high_lag+1], distance=2)
    candidates = []
    for peak in peaks:
        lag_index = low_lag+int(peak)
        lag = float(lag_index)
        # Parabolische Interpolation beseitigt die grobe BPM-Stufung des
        # Analyse-Hops (bei 118 BPM sonst 118.42 statt 118.00).
        if 1 <= lag_index < len(autocorrelation)-1:
            left, center, right = (float(autocorrelation[lag_index-1]),
                                   float(autocorrelation[lag_index]),
                                   float(autocorrelation[lag_index+1]))
            denominator = left-2*center+right
            if abs(denominator) > 1e-20:
                lag += float(np.clip(.5*(left-right)/denominator, -.5, .5))
        bpm = 60.0*fps/lag
        periodicity = max(0.0, float(autocorrelation[lag_index]/normalizer))
        phase, alignment_error = _grid_error(onsets, bpm, strengths)
        alignment = math.exp(-alignment_error/0.018)
        # Werbemusik liegt normalerweise nicht im Halbtempo. Der kleine
        # Mittellagenbonus loest 59/118-Ambiguitaeten, ohne 80 oder 160 BPM
        # grundsaetzlich auszuschliessen.
        range_weight = 1.0 if 88 <= bpm <= 150 else 0.90
        score = range_weight*(0.58*periodicity + 0.42*alignment)
        candidates.append({"bpm": bpm, "periodicity": periodicity,
                           "grid_phase": phase, "grid_error": alignment_error,
                           "score": score})
    if not candidates:
        return 118.0, 0.0, []
    candidates.sort(key=lambda row: row["score"], reverse=True)
    best = candidates[0]
    confidence = min(1.0, best["score"]/(candidates[1]["score"]+1e-9)-0.85) \
        if len(candidates) > 1 else min(1.0, best["score"])
    public = [{k: _round(row[k], 4) for k in ("bpm", "periodicity", "grid_error", "score")}
              for row in candidates[:8]]
    return float(best["bpm"]), max(0.0, float(confidence)), public


def _decay_seconds(segment: np.ndarray) -> float:
    if len(segment) < 8:
        return 0.0
    width = max(8, int(round(0.005*SR)))
    energy = signal.fftconvolve(segment*segment, np.ones(width)/width, mode="same")
    envelope = np.sqrt(np.maximum(energy, 0.0)+1e-20)
    search = min(len(envelope), int(0.10*SR))
    peak_index = int(np.argmax(envelope[:search]))
    peak = float(envelope[peak_index])
    if peak <= 1e-8:
        return 0.0
    below = envelope[peak_index:] <= peak*0.25
    run = max(1, int(0.010*SR))
    if len(below) >= run:
        stable = np.convolve(below.astype(np.int16), np.ones(run, dtype=np.int16), mode="valid")
        hits = np.flatnonzero(stable >= run)
        if len(hits):
            return float(hits[0]/SR)
    return float((len(envelope)-peak_index)/SR)


def describe_event(stereo: np.ndarray, start: float, end: float) -> dict | None:
    begin = max(0, int(round((start-0.004)*SR)))
    finish = min(len(stereo), int(round(end*SR)))
    if finish-begin < int(0.025*SR):
        return None
    sample = stereo[begin:finish]
    mono = sample.mean(axis=1).astype(np.float64)
    analysis_length = min(len(mono), int(0.35*SR))
    frame = mono[:analysis_length]
    n_fft = max(2048, 1 << int(math.ceil(math.log2(max(32, len(frame))))))
    n_fft = min(n_fft, 32768)
    spectrum = np.abs(np.fft.rfft(frame*np.hanning(len(frame)), n=n_fft))**2
    frequencies = np.fft.rfftfreq(n_fft, 1/SR)
    valid = (frequencies >= 20) & (frequencies < 18_000)
    total = float(spectrum[valid].sum()) + 1e-20
    shares = _band_shares(spectrum, frequencies)
    centroid = float((spectrum[valid]*frequencies[valid]).sum()/total)
    cumulative = np.cumsum(spectrum[valid])
    valid_frequencies = frequencies[valid]
    roll_index = int(np.searchsorted(cumulative, cumulative[-1]*0.85))
    rolloff = float(valid_frequencies[min(roll_index, len(valid_frequencies)-1)])
    positive = spectrum[valid]+1e-24
    flatness = float(np.exp(np.mean(np.log(positive)))/(np.mean(positive)+1e-24))
    dominant_mask = (frequencies >= 35) & (frequencies <= 8000)
    dominant_values = spectrum[dominant_mask]
    dominant_frequency = float(frequencies[dominant_mask][int(np.argmax(dominant_values))]) \
        if len(dominant_values) else 0.0

    left_rms = float(np.sqrt(np.mean(sample[:, 0].astype(np.float64)**2)))+1e-12
    right_rms = float(np.sqrt(np.mean(sample[:, 1].astype(np.float64)**2)))+1e-12
    mid = sample.mean(axis=1).astype(np.float64)
    side = (sample[:, 0]-sample[:, 1]).astype(np.float64)*0.5
    side_mid = 20*np.log10((np.sqrt(np.mean(side*side))+1e-12) /
                           (np.sqrt(np.mean(mid*mid))+1e-12))
    peak = float(np.max(np.abs(sample)))+1e-12
    rms = float(np.sqrt(np.mean(sample.astype(np.float64)**2)))+1e-12
    return {
        "centroid_hz": _round(centroid, 1),
        "rolloff_85_hz": _round(rolloff, 1),
        "dominant_hz": _round(dominant_frequency, 1),
        "flatness": _round(flatness, 5),
        "decay_seconds": _round(_decay_seconds(mono), 4),
        "peak_dbfs": _round(20*np.log10(peak), 2),
        "rms_dbfs": _round(20*np.log10(rms), 2),
        "pan": _round(right_rms/(left_rms+right_rms), 4),
        "side_mid_db": _round(side_mid, 2),
        "bands": [_round(value, 5) for value in shares],
    }


def semantic_family(event: dict) -> str:
    sub, bass, low_mid, mid, presence, air = event["bands"]
    low = sub+bass
    central = low_mid+mid+presence
    centroid = event["centroid_hz"]
    flatness = event["flatness"]
    decay = event["decay_seconds"]
    if low >= 0.58 and centroid < 900:
        return "sub"
    if flatness < 0.055 and central >= 0.42 and event["dominant_hz"] < 2600:
        return "tonal"
    if centroid < 2700 and central >= 0.45:
        return "body"
    if air >= 0.45 or centroid >= 6500:
        return "air" if decay >= 0.10 else "tick"
    if flatness >= 0.22:
        return "noise"
    return "click"


def aggregate_families(events: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event["family"]].append(event)
    result = {}
    for name, rows in sorted(grouped.items()):
        band_matrix = np.asarray([row["bands"] for row in rows], dtype=float)
        positions = [0]*16
        for row in rows:
            positions[int(row["grid_position"]) % 16] += 1
        result[name] = {
            "event_count": len(rows),
            "share": _round(len(rows)/max(1, len(events)), 5),
            "centroid_hz": _percentiles((row["centroid_hz"] for row in rows), 1),
            "dominant_hz": _percentiles((row["dominant_hz"] for row in rows), 1),
            "decay_seconds": _percentiles((row["decay_seconds"] for row in rows), 4),
            "flatness": _percentiles((row["flatness"] for row in rows), 5),
            "peak_dbfs": _percentiles((row["peak_dbfs"] for row in rows), 2),
            "pan": _percentiles((row["pan"] for row in rows), 4),
            "side_mid_db": _percentiles((row["side_mid_db"] for row in rows), 2),
            "bands_median": {band_name: _round(value, 5)
                             for (band_name, _, _), value in zip(BANDS, np.median(band_matrix, axis=0))},
            "grid_position_counts": positions,
        }
    return result


def build_groove(events: list[dict], bars: int) -> dict:
    positions = []
    for position in range(16):
        rows = [row for row in events if row["grid_position"] == position]
        offsets = [row["grid_offset_ms"] for row in rows]
        strengths = [row["strength"] for row in rows]
        positions.append({
            "position": position,
            "event_count": len(rows),
            "events_per_bar": _round(len(rows)/max(1, bars), 4),
            "offset_ms": _percentiles(offsets, 2),
            "strength": _percentiles(strengths, 4),
        })
    all_offsets = [row["grid_offset_ms"] for row in events]
    return {
        "positions": positions,
        "offset_ms": _percentiles(all_offsets, 2),
        "events_per_bar": _round(len(events)/max(1, bars), 4),
        "note": ("Angriffskanten und Spielversatz sind gemeinsam gemessen. "
                 "Der Generator uebernimmt nur ihre Verteilung, nie die Ereignisfolge."),
    }


def build_arrangement(stereo: np.ndarray, events: list[dict], bpm: float,
                      downbeat: float) -> dict:
    bar_duration = 240.0/bpm
    duration = len(stereo)/SR
    bars = max(1, int(round(max(0.0, duration-downbeat)/bar_duration)))
    bar_rows = []
    for bar in range(bars):
        start = downbeat+bar*bar_duration
        end = min(duration, start+bar_duration)
        a = max(0, int(round(start*SR)))
        b = min(len(stereo), int(round(end*SR)))
        part = stereo[a:b]
        rms = float(np.sqrt(np.mean(part.astype(np.float64)**2)))+1e-12 if len(part) else 1e-12
        in_bar = [row for row in events if start <= row["time"] < end]
        bar_rows.append({
            "bar": bar+1,
            "start_seconds": _round(start, 4),
            "rms_dbfs": _round(20*np.log10(rms), 2),
            "event_count": len(in_bar),
            "mean_strength": _round(np.mean([row["strength"] for row in in_bar]), 4)
            if in_bar else 0.0,
        })

    blocks = []
    for start in range(0, bars, 4):
        rows = bar_rows[start:min(bars, start+4)]
        blocks.append({
            "start_bar": start+1,
            "end_bar": start+len(rows),
            "rms_dbfs": _round(10*np.log10(np.mean([10**(row["rms_dbfs"]/10) for row in rows])+1e-20), 2),
            "events_per_bar": _round(np.mean([row["event_count"] for row in rows]), 3),
        })
    energies = np.asarray([row["rms_dbfs"] for row in blocks], dtype=float)
    if len(energies):
        q20, q50, q80 = np.percentile(energies, (20, 50, 80))
        for row in blocks:
            value = row["rms_dbfs"]
            row["role"] = "break" if value <= q20 else \
                ("sparse" if value <= q50 else ("groove" if value <= q80 else "peak"))
    return {"bars": bars, "bar_duration_seconds": _round(bar_duration, 6),
            "bar_profiles": bar_rows, "four_bar_blocks": blocks}


def analyze_reference(path: Path, bpm_hint: float | None = None,
                      downbeat_hint: float | None = None,
                      include_events: bool = True,
                      ebu: bool = True) -> dict:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    stereo = decode_audio(path)
    duration = len(stereo)/SR
    mono = stereo.mean(axis=1).astype(np.float32)
    novelty, frame_times, fps = spectral_flux(mono)
    onset_times, onset_strengths = detect_onsets(novelty, frame_times)

    if bpm_hint is None:
        bpm, tempo_confidence, tempo_candidates = estimate_tempo(
            novelty, fps, onset_times, onset_strengths)
    else:
        bpm = float(bpm_hint)
        tempo_confidence = 1.0
        tempo_candidates = [{"bpm": _round(bpm, 4), "source": "cli_hint"}]
    if not 30 <= bpm <= 300:
        raise ValueError("BPM muss zwischen 30 und 300 liegen")

    phase, phase_error = _grid_error(onset_times, bpm, onset_strengths)
    bar_duration = 240.0/bpm
    exact_bars = duration/bar_duration
    if downbeat_hint is not None:
        downbeat = float(downbeat_hint)
        downbeat_source = "cli_hint"
    elif abs(exact_bars-round(exact_bars)) <= 0.035:
        downbeat = 0.0
        downbeat_source = "duration_matches_full_bars"
    else:
        downbeat = phase
        downbeat_source = "onset_grid_phase"

    events = []
    for index, (onset, raw_strength) in enumerate(zip(onset_times, onset_strengths)):
        next_onset = onset_times[index+1] if index+1 < len(onset_times) else onset+0.75
        end = min(duration, onset+0.85, max(onset+0.030, next_onset-0.003))
        description = describe_event(stereo, float(onset), float(end))
        if description is None:
            continue
        step = 60.0/bpm/4.0
        grid_index = int(round((onset-downbeat)/step))
        grid_time = downbeat+grid_index*step
        description.update({
            "time": _round(onset, 5),
            "raw_strength": float(raw_strength),
            "grid_index": grid_index,
            "grid_position": grid_index % 16,
            "grid_offset_ms": _round((onset-grid_time)*1000.0, 2),
        })
        description["family"] = semantic_family(description)
        events.append(description)

    if events:
        values = np.asarray([20*np.log10(max(row["raw_strength"], 1e-12)) for row in events])
        low, high = np.percentile(values, (4, 98))
        for row, value in zip(events, values):
            row["strength"] = _round(np.clip((value-low)/max(1e-9, high-low), 0.04, 1.0), 4)
            del row["raw_strength"]

    arrangement = build_arrangement(stereo, events, bpm, downbeat)
    bars = arrangement["bars"]
    left = stereo[:, 0].astype(np.float64)
    right = stereo[:, 1].astype(np.float64)
    mid = (left+right)*0.5
    side = (left-right)*0.5
    peak = float(np.max(np.abs(stereo)))+1e-12
    rms = float(np.sqrt(np.mean(stereo.astype(np.float64)**2)))+1e-12
    side_mid_db = 20*np.log10((np.sqrt(np.mean(side*side))+1e-12) /
                              (np.sqrt(np.mean(mid*mid))+1e-12))
    media = probe_media(path)
    sha256 = file_sha256(path)
    mix = {
        "sample_peak_dbfs": _round(20*np.log10(peak), 2),
        "rms_dbfs": _round(20*np.log10(rms), 2),
        "crest_db": _round(20*np.log10(peak/rms), 2),
        "left_right_correlation": _round(np.corrcoef(left, right)[0, 1], 5),
        "side_mid_db": _round(side_mid_db, 2),
        **global_spectrum(mono),
    }
    if ebu:
        mix.update(measure_ebu(path))

    families = aggregate_families(events)
    profile = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "file_name": path.name,
            "sha256": sha256,
            "duration_seconds_decoded": _round(duration, 6),
            **media,
        },
        "tempo": {
            "bpm": _round(bpm, 5),
            "confidence": _round(tempo_confidence, 4),
            "candidates": tempo_candidates,
            "sixteenth_seconds": _round(60.0/bpm/4.0, 7),
            "grid_phase_seconds": _round(phase, 6),
            "grid_fit_error_seconds": _round(phase_error, 6),
            "downbeat_seconds": _round(downbeat, 6),
            "downbeat_source": downbeat_source,
        },
        "mix": mix,
        "groove": build_groove(events, bars),
        "sound_families": families,
        "arrangement": arrangement,
        "generation_targets": {
            "events_per_bar": _round(len(events)/max(1, bars), 4),
            "family_shares": {name: row["share"] for name, row in families.items()},
            "bands": mix["bands"],
            "side_mid_db": mix["side_mid_db"],
            "loudness_range_lu": mix.get("loudness_range_lu"),
        },
        "method": {
            "sample_rate": SR,
            "fft_size": N_FFT,
            "hop_size": HOP,
            "event_count": len(events),
            "principle": ("Nur statistische und akustische Deskriptoren. Keine Quell-Samples, "
                          "keine Wellenform und keine Ereignisfolge werden fuer die Erzeugung kopiert."),
            "limits": ("Aus einem fertigen Stereo-Mix lassen sich Original-Samples, MIDI, "
                       "Plugin-Einstellungen und ueberlagerte Einzelspuren nicht exakt rekonstruieren."),
        },
    }
    if include_events:
        profile["events"] = events
    return profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Audio- oder Videodatei")
    parser.add_argument("--output", type=Path,
                        default=OUT/"analysis"/"reference-profile.json")
    parser.add_argument("--bpm", type=float, help="bekanntes Tempo; sonst automatische Schaetzung")
    parser.add_argument("--downbeat", type=float,
                        help="Zeit der ersten Eins in Sekunden; sonst automatische Annahme")
    parser.add_argument("--without-events", action="store_true",
                        help="Einzelereignisse nicht im JSON speichern")
    parser.add_argument("--without-ebu", action="store_true",
                        help="langsamere EBU-R128-Messung ueberspringen")
    parser.add_argument("--print", action="store_true", dest="print_report")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    profile = analyze_reference(
        args.source, bpm_hint=args.bpm, downbeat_hint=args.downbeat,
        include_events=not args.without_events, ebu=not args.without_ebu,
    )
    write_manifest(args.output, profile)
    source = profile["source"]
    tempo = profile["tempo"]
    print(f"{args.output} · {source['duration_seconds_decoded']:.3f}s · "
          f"{tempo['bpm']:.3f} BPM · {profile['method']['event_count']} Anschlaege · "
          f"{len(profile['sound_families'])} Klangfamilien")
    if args.print_report:
        print("\nKlangfamilien:")
        for name, row in profile["sound_families"].items():
            print(f"  {name:<8} {row['event_count']:4d} · Schwerpunkt "
                  f"{row['centroid_hz']['median']:7.0f} Hz · Abkling "
                  f"{row['decay_seconds']['median']*1000:5.0f} ms")
        mix = profile["mix"]
        print(f"\nStereo Side/Mid {mix['side_mid_db']:+.1f} dB · "
              f"RMS {mix['rms_dbfs']:+.1f} dBFS · Peak {mix['sample_peak_dbfs']:+.1f} dBFS")


if __name__ == "__main__":
    main()

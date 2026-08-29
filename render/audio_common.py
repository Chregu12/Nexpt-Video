#!/usr/bin/env python3
"""Gemeinsame DSP-Helfer fuer die eigenstaendige NEXPT-Audiospur.

Nur NumPy, SciPy und ffmpeg werden benoetigt.  Musik und Soundeffekte teilen
hier technische Funktionen, aber weder Samples noch Klanggeneratoren. Dadurch
bleiben die beiden Stems inhaltlich und lizenzrechtlich unabhaengig.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt


SR = 48_000
BPM = 118.0
BEAT = 60.0 / BPM
BAR = BEAT * 4.0
SIXTEENTH = BEAT / 4.0

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "out"

# Dieselbe Suchreihenfolge wie im uebrigen Repo (siehe render/musik.py): erst
# die Umgebungsvariable, dann der PATH, zuletzt das mit imageio-ffmpeg
# ausgelieferte Binary. In dieser Umgebung liegt ffmpeg NICHT im PATH — mit
# shutil.which() allein bricht jeder Lauf mit „ffmpeg wurde nicht gefunden" ab.
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"


def timing() -> tuple[dict, float]:
    cfg = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
    total = max(float(s["start"]) + float(s["dur"]) for s in cfg["scenes"])
    return cfg, total


def cue_sheet() -> dict:
    path = OUT / "analysis" / "cue_sheet.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} fehlt; zuerst `python3 render/cuesheet.py` ausfuehren")
    return json.loads(path.read_text(encoding="utf-8"))


def mono_filter(x: np.ndarray, kind: str, cutoff, order: int = 4) -> np.ndarray:
    """Stabiler Butterworth-Filter fuer kurze synthetische Klangbausteine."""
    wn = np.asarray(cutoff, dtype=float) / (SR / 2.0)
    sos = butter(order, wn, btype=kind, output="sos")
    return sosfilt(sos, np.asarray(x, dtype=np.float64)).astype(np.float32)


def lowpass(x: np.ndarray, hz: float, order: int = 4) -> np.ndarray:
    return mono_filter(x, "lowpass", hz, order)


def highpass(x: np.ndarray, hz: float, order: int = 4) -> np.ndarray:
    return mono_filter(x, "highpass", hz, order)


def bandpass(x: np.ndarray, lo: float, hi: float, order: int = 3) -> np.ndarray:
    return mono_filter(x, "bandpass", (lo, hi), order)


def constant_power_pan(pan: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
    p = np.clip(pan, 0.0, 1.0)
    return np.cos(p * np.pi / 2.0), np.sin(p * np.pi / 2.0)


def place(stereo: np.ndarray, mono: np.ndarray, at: float, gain: float = 1.0,
          pan: float = 0.5) -> None:
    """Mono-Klang mit Constant-Power-Panning in einen Stereo-Puffer setzen."""
    start = int(round(at * SR))
    source_start = max(0, -start)
    start = max(0, start)
    count = min(len(mono) - source_start, len(stereo) - start)
    if count <= 0:
        return
    left, right = constant_power_pan(float(pan))
    part = mono[source_start:source_start + count] * float(gain)
    stereo[start:start + count, 0] += part * left
    stereo[start:start + count, 1] += part * right


def place_moving(stereo: np.ndarray, mono: np.ndarray, at: float, gain: float,
                 pan_from: float, pan_to: float) -> None:
    """Klang mit echter Pegelbewegung pannen; keine Gegenphase/Mono-Probleme."""
    start = int(round(at * SR))
    source_start = max(0, -start)
    start = max(0, start)
    count = min(len(mono) - source_start, len(stereo) - start)
    if count <= 0:
        return
    part = mono[source_start:source_start + count] * float(gain)
    pans = np.linspace(pan_from, pan_to, count, dtype=np.float32)
    left, right = constant_power_pan(pans)
    stereo[start:start + count, 0] += part * left
    stereo[start:start + count, 1] += part * right


def add_short_room(stereo: np.ndarray, amount: float = 0.08) -> np.ndarray:
    """Kurzer, mono-kompatibler Raum aus diskreten Early Reflections."""
    dry = stereo.copy()
    taps = ((0.031, 0.52, -0.06), (0.047, 0.38, 0.07),
            (0.073, 0.25, -0.11), (0.109, 0.16, 0.12))
    for delay, level, cross in taps:
        d = int(round(delay * SR))
        if d >= len(stereo):
            continue
        stereo[d:, 0] += dry[:-d, 0] * amount * level
        stereo[d:, 1] += dry[:-d, 1] * amount * level
        stereo[d:, 0] += dry[:-d, 1] * amount * level * cross
        stereo[d:, 1] += dry[:-d, 0] * amount * level * cross
    return stereo


def apply_dip(envelope: np.ndarray, start: float, duration: float, target: float,
              fade_in: float = 0.10, fade_out: float = 0.18) -> None:
    """Multiplikative Lautstaerkeabsenkung mit weichen Cosinus-Rampen."""
    a = max(0, int(round((start - fade_in) * SR)))
    b = max(a, int(round(start * SR)))
    c = min(len(envelope), int(round((start + duration) * SR)))
    d = min(len(envelope), int(round((start + duration + fade_out) * SR)))
    if b > a:
        u = np.linspace(0.0, 1.0, b - a, endpoint=False)
        envelope[a:b] = np.minimum(envelope[a:b], 1.0 - (1.0 - target) * (0.5 - 0.5*np.cos(np.pi*u)))
    if c > b:
        envelope[b:c] = np.minimum(envelope[b:c], target)
    if d > c:
        u = np.linspace(0.0, 1.0, d - c, endpoint=False)
        envelope[c:d] = np.minimum(envelope[c:d], target + (1.0-target) * (0.5 - 0.5*np.cos(np.pi*u)))


def soft_limit(stereo: np.ndarray, drive: float = 1.15) -> np.ndarray:
    return (np.tanh(stereo * drive) / np.tanh(drive)).astype(np.float32)


def peak_normalize(stereo: np.ndarray, peak_db: float, only_down: bool = False) -> tuple[np.ndarray, float]:
    peak = float(np.max(np.abs(stereo))) or 1.0
    wanted = 10.0 ** (peak_db / 20.0)
    factor = wanted / peak
    if only_down:
        factor = min(1.0, factor)
    return (stereo * factor).astype(np.float32), factor


def audio_stats(stereo: np.ndarray) -> dict:
    peak = float(np.max(np.abs(stereo))) + 1e-12
    rms = float(np.sqrt(np.mean(np.square(stereo, dtype=np.float64)))) + 1e-12
    mid = (stereo[:, 0] + stereo[:, 1]) * 0.5
    side = (stereo[:, 0] - stereo[:, 1]) * 0.5
    return {
        "peak_dbfs": round(20*np.log10(peak), 2),
        "rms_dbfs": round(20*np.log10(rms), 2),
        "side_mid_rms": round(float(np.sqrt(np.mean(side**2)) / (np.sqrt(np.mean(mid**2)) + 1e-12)), 3),
    }


def write_pcm24(path: Path, stereo: np.ndarray) -> None:
    """24-Bit-PCM-WAV via ffmpeg schreiben; float stays internal until encode."""
    if not (FFMPEG and (Path(FFMPEG).exists() or shutil.which(FFMPEG))):
        raise RuntimeError(
            "ffmpeg wurde nicht gefunden — ins PATH legen oder FFMPEG=<pfad> setzen")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.ascontiguousarray(np.clip(stereo, -1.0, 1.0), dtype="<f4")
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
        "-c:a", "pcm_s24le", str(path),
    ], input=data.tobytes(), check=True)


def write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

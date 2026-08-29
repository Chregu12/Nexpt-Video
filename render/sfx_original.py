#!/usr/bin/env python3
"""Eigenstaendiges Sounddesign aus dem bestehenden Cue Sheet.

Die Effekte werden vollstaendig synthetisiert und verwenden weder Musik-
Samples noch die Referenzfilme. Drei Substems plus ein SFX-Master erlauben
spaeteres Mischen in Final Cut/Logic ohne die Musik neu zu rendern.

    python3 render/sfx_original.py

Ausgaben:
    out/sfx-impacts.wav
    out/sfx-motion.wav
    out/sfx-ui.wav
    out/sfx-original.wav
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache

import numpy as np

from audio_common import (
    SR, OUT, apply_dip, audio_stats, bandpass, cue_sheet, highpass,
    peak_normalize, place, place_moving, timing, write_manifest, write_pcm24,
)


SEED = 260829
rng = np.random.default_rng(SEED)
_, TOTAL = timing()
N = int(round((TOTAL + 1.0) * SR))
stems = {
    "impacts": np.zeros((N, 2), dtype=np.float32),
    "motion": np.zeros((N, 2), dtype=np.float32),
    "ui": np.zeros((N, 2), dtype=np.float32),
}


def noise(seed: int, n: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def shape(t: np.ndarray, attack: float, decay: float) -> np.ndarray:
    return np.minimum(1.0, t/max(attack, 1e-5)) * np.exp(-t/decay)


@lru_cache(maxsize=None)
def impact(variant: int, intensity_bin: int) -> np.ndarray:
    intensity = .45 + .11*intensity_bin
    duration = .82 + variant*.07
    t = np.arange(int(duration*SR), dtype=np.float64)/SR
    f = 43 + (55 + variant*7)*np.exp(-t*26.0)
    phase = 2*np.pi*np.cumsum(f)/SR
    sub = np.sin(phase)*np.exp(-t*(5.1 + variant*.25))
    sub += .17*np.sin(2.03*phase + .4)*np.exp(-t*9.5)
    raw = noise(11000 + variant*43 + intensity_bin, len(t))
    body = bandpass(raw, 110, 1100 + variant*120, 3)*np.exp(-t*11.0)
    crack = bandpass(raw, 1200, 7600, 2)*np.exp(-t*85.0)
    modes = (np.sin(2*np.pi*(137+variant*9)*t)*np.exp(-t*13.0) +
             .45*np.sin(2*np.pi*(286+variant*17)*t + .3)*np.exp(-t*19.0))
    y = .63*sub + .31*body + .08*crack + .17*modes
    return np.asarray(y*intensity, dtype=np.float32)


def whoosh(duration: float, variant: int, intensity: float, dark: bool = False) -> np.ndarray:
    duration = float(np.clip(duration, .16, 1.25))
    n = int(duration*SR)
    t = np.arange(n, dtype=np.float64)/SR
    u = np.linspace(0.0, 1.0, n)
    raw = noise(12000 + variant*71 + n, n)
    low = bandpass(raw, 120 if dark else 220, 1250 if dark else 2200, 3)
    high = bandpass(raw, 900, 5200 if dark else 9800, 2)
    travel = low*(1.0-u) + high*(.22 + .78*u)
    amplitude = np.sin(np.pi*u)**1.35
    flutter = .84 + .16*np.sin(2*np.pi*(23+variant*2)*t + variant)
    tone = np.sin(2*np.pi*np.cumsum(70 + 55*u)/SR)*amplitude*.08
    return np.asarray((travel*amplitude*flutter*.29 + tone)*intensity, dtype=np.float32)


def marker(duration: float, variant: int, intensity: float) -> np.ndarray:
    duration = float(np.clip(duration, .13, 1.2))
    n = int(duration*SR)
    t = np.arange(n, dtype=np.float64)/SR
    u = np.linspace(0.0, 1.0, n)
    raw = noise(13000 + variant*59 + n, n)
    friction = bandpass(raw, 650 + variant*90, 5200 + variant*350, 3)
    grains = .65 + .21*np.sin(2*np.pi*(64+variant*9)*t) + .14*np.sin(2*np.pi*117*t+.7)
    envelope = np.sin(np.pi*np.clip(u, 0, 1))**.45
    knock = np.sin(2*np.pi*(380+variant*25)*t)*np.exp(-t*72.0)*.10
    return np.asarray((friction*grains*envelope*.20 + knock)*intensity, dtype=np.float32)


@lru_cache(maxsize=None)
def click(variant: int, intensity_bin: int, bright: bool) -> np.ndarray:
    intensity = .40 + intensity_bin*.09
    t = np.arange(int((.105 + variant*.008)*SR), dtype=np.float64)/SR
    base = (620 if not bright else 1320)*(1 + variant*.035)
    ratios = (1.0, 1.83, 3.17, 4.64)
    y = np.zeros_like(t)
    for i, ratio in enumerate(ratios):
        y += (1/(1+i*.78))*np.sin(2*np.pi*base*ratio*t + i*.37)*np.exp(-t*(42+i*28))
    raw = highpass(noise(14000 + variant*31 + intensity_bin + int(bright)*200, len(t)), 4200, 2)
    y += raw*np.exp(-t*155.0)*(.035 if not bright else .065)
    return np.asarray(y*intensity*.38, dtype=np.float32)


def flutter(duration: float, variant: int, intensity: float) -> np.ndarray:
    duration = float(np.clip(duration, .32, 2.6))
    n = int(duration*SR)
    t = np.arange(n, dtype=np.float64)/SR
    u = np.linspace(0.0, 1.0, n)
    raw = bandpass(noise(15000 + variant*67 + n, n), 350, 7200, 3)
    gate = np.maximum(0.0, np.sin(2*np.pi*(7.5+variant*.7)*t))**2
    envelope = np.sin(np.pi*u)**.7
    return np.asarray(raw*(.30 + .70*gate)*envelope*.16*intensity, dtype=np.float32)


data = cue_sheet()
cues = sorted(data["cues"], key=lambda c: float(c["t"]))
halts = [(float(c["t"]), float(c.get("dauer", 0.0)), c["szene"])
         for c in cues if c["art"] == "halt"]


def inside_halt(t: float) -> bool:
    return any(start-.04 <= t <= start+duration+.04 for start, duration, _ in halts)


selected: list[dict] = []
last = {"impact": -99.0, "motion": -99.0, "marker": -99.0, "ui": -99.0}
motion_arts = {"marker", "unterstrich", "wortflut", "karte", "pfeile",
               "livekorrektur", "strich", "stapel"}
ui_arts = {"kritzel", "raster", "zeile", "ebene"}

for cue in cues:
    art = cue["art"]
    t = float(cue["t"])
    strength = float(cue.get("staerke", .5))
    if art == "halt" or inside_halt(t):
        continue

    if art == "bgwechsel":
        if t-last["impact"] >= .65:
            selected.append({**cue, "stem": "impacts", "design": "impact", "gain": .62 + .30*strength})
            last["impact"] = t
        continue

    if art == "schnitt":
        # Nicht jeder Schnitt braucht einen Schlag. Starke Kapitelwechsel und
        # laengere unvertone Abstaende bleiben; der Rest wird von Musik getragen.
        if (strength >= .90 or t-last["impact"] >= 7.5) and t-last["impact"] >= 1.2:
            selected.append({**cue, "stem": "impacts", "design": "impact", "gain": .38 + .30*strength})
            last["impact"] = t
        continue

    if art in motion_arts:
        minimum = 2.30 if art == "marker" else .85
        force = art in {"wortflut", "karte", "pfeile", "livekorrektur", "strich", "stapel"}
        if force or t-last["motion"] >= minimum:
            design = "marker" if art in {"marker", "unterstrich", "strich"} else \
                     ("flutter" if art in {"wortflut", "stapel"} else "whoosh")
            selected.append({**cue, "stem": "motion", "design": design, "gain": .30 + .42*strength})
            last["motion"] = t
            if art == "marker": last["marker"] = t
        continue

    if art in ui_arts:
        minimum = .22 if art == "raster" else .58
        if t-last["ui"] >= minimum:
            selected.append({**cue, "stem": "ui", "design": "click", "gain": .25 + .38*strength})
            last["ui"] = t


for index, cue in enumerate(selected):
    t = float(cue["t"])
    strength = float(cue.get("staerke", .5))
    gain = float(cue["gain"])
    x = .5 + (float(cue.get("x", .5))-.5)*.62
    design = cue["design"]
    variant = index % 4

    if design == "impact":
        sound = impact(variant, min(4, max(0, int(round(strength*4)))))
        place(stems["impacts"], sound, t, gain, x)
        # Nur grosse Hintergrundwechsel erhalten einen kurzen musikalisch freien Anlauf.
        if cue["art"] == "bgwechsel" and strength >= .8:
            lead = whoosh(.32, variant, .34, dark=True)
            place_moving(stems["motion"], lead, t-len(lead)/SR, gain*.45,
                         max(.18, x-.18), min(.82, x+.18))
    elif design == "marker":
        duration = float(cue.get("dauer") or .24)
        sound = marker(duration, variant, gain)
        place_moving(stems["motion"], sound, t, 1.0,
                     max(.20, x-.13), min(.80, x+.13))
    elif design == "whoosh":
        duration = float(cue.get("dauer") or .34)
        sound = whoosh(duration, variant, gain, dark=False)
        place_moving(stems["motion"], sound, t, 1.0,
                     max(.18, x-.18), min(.82, x+.18))
        terminal = click(variant, 2, False)
        place(stems["ui"], terminal, t+duration*.92, gain*.42, min(.80, x+.12))
    elif design == "flutter":
        duration = float(cue.get("dauer") or (.70 if cue["art"] == "stapel" else 1.2))
        sound = flutter(duration, variant, gain)
        place_moving(stems["motion"], sound, t, 1.0, .39, .61)
    elif design == "click":
        bright = cue["art"] == "raster"
        sound = click(variant, min(4, max(0, int(round(strength*4)))), bright)
        place(stems["ui"], sound, t, gain, x)


# Absolute Ruhe an den als "halt" markierten Stellen, auch fuer auslaufende Tails.
silence = np.ones(N, dtype=np.float32)
for start, duration, _ in halts:
    apply_dip(silence, start, max(.25, duration), 0.0, .055, .10)
for stem in stems.values():
    stem *= silence[:, None]
    for channel in range(2):
        stem[:, channel] = highpass(stem[:, channel], 24.0, 2)

master = stems["impacts"] + stems["motion"] + stems["ui"]
master, scale = peak_normalize(master, -4.0)
for name in stems:
    stems[name] *= scale

files = {
    "impacts": OUT / "sfx-impacts.wav",
    "motion": OUT / "sfx-motion.wav",
    "ui": OUT / "sfx-ui.wav",
    "master": OUT / "sfx-original.wav",
}
for name, path in files.items():
    write_pcm24(path, master if name == "master" else stems[name])

manifest = {
    "files": {k: v.name for k, v in files.items()},
    "sample_rate": SR,
    "bit_depth": 24,
    "duration_seconds": round(N/SR, 3),
    "seed": SEED,
    "source": "Original procedural sound design; no music samples or reference audio",
    "input_cues": len(cues),
    "selected_cues": len(selected),
    "selected_by_art": dict(Counter(c["art"] for c in selected)),
    "selected_by_stem": dict(Counter(c["stem"] for c in selected)),
    "halt_regions": [{"time": t, "duration": d, "scene": s} for t,d,s in halts],
    "normalization_scale": round(scale, 5),
    "stats": {"master": audio_stats(master), **{k: audio_stats(v) for k,v in stems.items()}},
    "events": [{k: c[k] for k in ("t", "szene", "art", "stem", "design", "gain")} for c in selected],
}
write_manifest(OUT / "analysis" / "sfx-original.json", manifest)
print(f"{files['master']} · {len(selected)} von {len(cues)} Cues")
print(Counter(c["art"] for c in selected))
print(manifest["stats"])

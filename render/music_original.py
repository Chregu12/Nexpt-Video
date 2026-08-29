#!/usr/bin/env python3
"""Originale, samplefreie Musik fuer den unveraenderten 68-Takt-Film.

Die alte Pipeline verlaengert einen 16-Takt-Loop. Diese Fassung schreibt eine
durchgehende 68-Takt-Partitur mit Abschnittsbogen, 4-Takt-Phrasen, Variationen,
Fill-ins und korreliertem Microtiming. Es wird keinerlei Audio aus dem Apple-
Referenzfilm oder aus einer Musikbibliothek verwendet.

    python3 render/music_original.py

Ausgabe: out/music-original.wav (48 kHz, Stereo, 24-Bit PCM)
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from audio_common import (
    SR, BAR, SIXTEENTH, OUT, add_short_room, apply_dip, audio_stats,
    bandpass, cue_sheet, highpass, lowpass, peak_normalize, place,
    soft_limit, timing, write_manifest, write_pcm24,
)


SEED = 260828
rng = np.random.default_rng(SEED)
_, TOTAL = timing()
TAIL = 1.0
N = int(round((TOTAL + TAIL) * SR))
mix = np.zeros((N, 2), dtype=np.float32)
events: list[dict] = []


def env(t: np.ndarray, decay: float, attack: float = 0.0015) -> np.ndarray:
    a = np.minimum(1.0, t / max(attack, 1e-5))
    return a * np.exp(-t / decay)


def local_noise(seed: int, n: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


@lru_cache(maxsize=None)
def kick(variant: int, level: int) -> np.ndarray:
    duration = 0.44 + 0.018 * variant
    t = np.arange(int(duration*SR), dtype=np.float64) / SR
    strength = 0.72 + level*0.09
    f = 43.0 + (78.0 + 8*variant) * np.exp(-t*31.0)
    phase = 2*np.pi*np.cumsum(f) / SR
    body = np.sin(phase) * np.exp(-t*(8.3 - level*0.45))
    second = np.sin(phase*1.99 + 0.4) * np.exp(-t*15.0) * 0.12
    click = highpass(local_noise(1000 + variant*17 + level, len(t)), 2400, 2)
    click *= np.exp(-t*125.0) * (0.035 + 0.012*level)
    return np.asarray((body + second + click) * strength, dtype=np.float32)


@lru_cache(maxsize=None)
def snare(variant: int, level: int) -> np.ndarray:
    t = np.arange(int(0.31*SR), dtype=np.float64) / SR
    raw = local_noise(2000 + variant*29 + level, len(t))
    wires = bandpass(raw, 900 + variant*80, 12_000, 3)
    wires *= (0.78*np.exp(-t*(17.0 + variant)) + 0.22*np.exp(-t*43.0))
    body = (np.sin(2*np.pi*(188 + variant*7)*t) * np.exp(-t*19.0) +
            0.36*np.sin(2*np.pi*(326 + variant*11)*t + .3) * np.exp(-t*27.0))
    attack = highpass(raw, 5000, 2) * np.exp(-t*150.0) * 0.20
    return np.asarray((0.57*wires + 0.34*body + attack) * (0.62 + level*0.09), dtype=np.float32)


@lru_cache(maxsize=None)
def wood(kind: int, variant: int, level: int) -> np.ndarray:
    duration = 0.16 if kind == 0 else 0.11
    t = np.arange(int(duration*SR), dtype=np.float64) / SR
    base = (930 if kind == 0 else 2150) * (1.0 + (variant-1.5)*0.012)
    ratios = (1.0, 1.72, 2.63, 4.11) if kind == 0 else (1.0, 1.89, 3.08, 4.72)
    amps = (1.0, .48, .27, .13)
    y = np.zeros_like(t)
    for i, (ratio, amp) in enumerate(zip(ratios, amps)):
        y += amp*np.sin(2*np.pi*base*ratio*t + variant*.37*i) * np.exp(-t*(31 + i*18))
    tick = highpass(local_noise(3000 + kind*100 + variant*13 + level, len(t)), 4500, 2)
    y += tick*np.exp(-t*180.0)*0.05
    return np.asarray(y * (0.34 + level*0.055), dtype=np.float32)


@lru_cache(maxsize=None)
def shaker(variant: int, level: int) -> np.ndarray:
    t = np.arange(int(0.105*SR), dtype=np.float64) / SR
    raw = highpass(local_noise(4000 + variant*19 + level, len(t)), 5700 + variant*180, 3)
    modulation = 0.72 + 0.28*np.sin(2*np.pi*(92 + variant*7)*t + variant)
    return np.asarray(raw * modulation * env(t, 0.025 + level*.003, .0005) * (0.09 + level*.014), dtype=np.float32)


@lru_cache(maxsize=None)
def tom(freq: int, variant: int, level: int) -> np.ndarray:
    t = np.arange(int(0.48*SR), dtype=np.float64) / SR
    f = freq*(1.0 + .22*np.exp(-t*22.0))
    phase = 2*np.pi*np.cumsum(f)/SR
    membrane = np.sin(phase)*np.exp(-t*(7.4 + variant*.4))
    membrane += .22*np.sin(phase*1.59 + .7)*np.exp(-t*12.0)
    slap = bandpass(local_noise(5000 + freq + variant*31 + level, len(t)), 450, 5000, 2)
    slap *= np.exp(-t*95.0)*0.12
    return np.asarray((membrane + slap) * (0.43 + level*.06), dtype=np.float32)


@lru_cache(maxsize=None)
def mallet(midi: int, variant: int, level: int) -> np.ndarray:
    duration = 0.62
    t = np.arange(int(duration*SR), dtype=np.float64) / SR
    f0 = 440.0 * 2.0**((midi - 69)/12.0)
    ratios = (1.0, 2.01, 3.93, 5.36, 6.82)
    amps = (1.0, .33, .20, .09, .055)
    y = np.zeros_like(t)
    for i, (ratio, amp) in enumerate(zip(ratios, amps)):
        decay = 0.20/(1 + i*.42) + level*.008
        y += amp*np.sin(2*np.pi*f0*ratio*t + variant*.21*i) * env(t, decay, .0007)
    knock = bandpass(local_noise(6000 + midi*11 + variant*23 + level, len(t)), 700, 6500, 2)
    y += knock*np.exp(-t*115.0)*0.055
    return np.asarray(y * (0.28 + level*.045), dtype=np.float32)


@lru_cache(maxsize=None)
def bass_note(midi: int, variant: int, level: int) -> np.ndarray:
    t = np.arange(int(0.57*SR), dtype=np.float64) / SR
    f0 = 440.0 * 2.0**((midi - 69)/12.0)
    f = f0*(1.0 + .07*np.exp(-t*18.0))
    phase = 2*np.pi*np.cumsum(f)/SR
    y = np.sin(phase)*np.exp(-t*5.4)
    y += .18*np.sin(2*phase + .2)*np.exp(-t*8.5)
    return np.asarray(y*(0.24 + level*.035), dtype=np.float32)


@lru_cache(maxsize=None)
def cymbal(variant: int, level: int) -> np.ndarray:
    t = np.arange(int(1.45*SR), dtype=np.float64) / SR
    raw = local_noise(7000 + variant*37 + level, len(t))
    hi = highpass(raw, 4200 + variant*250, 3)
    mid = bandpass(raw, 900, 4600, 2)
    shimmer = 0.77*hi*np.exp(-t*2.45) + 0.23*mid*np.exp(-t*4.1)
    return np.asarray(shimmer*env(t, 0.65, .001)*(0.10 + level*.014), dtype=np.float32)


SECTIONS = [
    (0, 4, "intro", .18, .30),
    (4, 7, "promise", .42, .55),
    (7, 9, "pullback", .10, .16),
    (9, 19, "groove-a", .48, .72),
    (19, 21, "breath", .28, .40),
    (21, 27, "build-a", .55, .84),
    (27, 29, "silence", .00, .02),
    (29, 35, "reset", .34, .62),
    (35, 42, "build-b", .58, .88),
    (42, 49, "climax", .88, 1.00),
    (49, 51, "drop", .06, .11),
    (51, 58, "groove-b", .44, .76),
    (58, 59, "silence", .00, .01),
    (59, 67, "finale", .62, 1.00),
    (67, 68, "final-hit", 1.00, 1.00),
]


def section(bar: int) -> tuple[str, float]:
    for start, end, name, lo, hi in SECTIONS:
        if start <= bar < end:
            u = 0.0 if end-start <= 1 else (bar-start)/(end-start-1)
            return name, lo + (hi-lo)*u
    raise ValueError(bar)


# Phrase-level push/pull: geglaettete Bar-Abweichung statt unabhaengigem Zufall.
drift = rng.normal(0.0, .0025, 72)
drift = np.convolve(drift, np.array([.20, .60, .20]), mode="same")
step_shape = np.array([0.0, .002, -.001, .004, 0.0, .003, -.001, .005,
                       0.0, .002, -.001, .004, 0.0, .003, -.001, .006])
instrument_lag = {"kick": -.002, "snare": .005, "wood": .001,
                  "shaker": .003, "tom": .002, "mallet": .000, "bass": -.003,
                  "cymbal": .000}


def hit_time(bar: int, step: int, instrument: str, jitter: float = .0012) -> float:
    return (bar*BAR + step*SIXTEENTH + drift[bar] + step_shape[step] +
            instrument_lag[instrument] + rng.normal(0.0, jitter))


def add(instrument: str, bar: int, step: int, gain: float, pan: float = .5,
        pitch: int = 0, level: int = 2) -> None:
    variant = int((bar*7 + step*3 + level) % 4)
    if instrument == "kick": sound = kick(variant, level)
    elif instrument == "snare": sound = snare(variant, level)
    elif instrument == "wood": sound = wood(pitch, variant, level)
    elif instrument == "shaker": sound = shaker(variant, level)
    elif instrument == "tom": sound = tom(pitch, variant, level)
    elif instrument == "mallet": sound = mallet(pitch, variant, level)
    elif instrument == "bass": sound = bass_note(pitch, variant, level)
    elif instrument == "cymbal": sound = cymbal(variant, level)
    else: raise ValueError(instrument)
    when = hit_time(bar, step, instrument, .0007 if instrument in {"kick", "mallet"} else .0015)
    place(mix, sound, when, gain, pan)
    events.append({"bar": bar+1, "step": step, "time": round(when, 4),
                   "instrument": instrument, "gain": round(gain, 3), "pitch": pitch})


root_cycle = (38, 38, 41, 36, 38, 45, 41, 36)  # D2, D2, F2, C2, ...
mallet_offsets = (12, 19, 15, 22, 19, 24, 22, 15)
kick_patterns = (
    (0, 10), (0, 7, 12), (0, 6, 11), (0, 9, 14),
    (0, 5, 10, 13), (0, 7, 10), (0, 3, 8, 12), (0, 6, 12, 15),
)

for bar in range(68):
    name, energy = section(bar)
    phrase = bar % 4
    root = root_cycle[(bar//4) % len(root_cycle)]

    if name == "final-hit":
        add("kick", bar, 0, .95, .50, level=4)
        add("tom", bar, 0, .72, .44, pitch=82, level=4)
        add("tom", bar, 0, .62, .58, pitch=123, level=4)
        add("mallet", bar, 0, .56, .52, pitch=62, level=4)
        add("cymbal", bar, 0, .42, .54, level=4)
        continue
    if energy < .03:
        continue

    # Intro und Ruecknahmen: Holz und vereinzelte tonale Anschlaege.
    if name in {"intro", "pullback", "drop"}:
        steps = (0, 8, 12) if phrase % 2 else (0, 4, 11)
        for i, step in enumerate(steps):
            add("wood", bar, step, (.32 + .16*energy)*(1.0 if i == 0 else .72),
                .36 + .28*((bar+i)%2), pitch=1 if i == 0 else 0, level=1)
        if name != "pullback" and phrase in {1, 3}:
            add("mallet", bar, 10, .20 + energy*.15, .55,
                pitch=root + mallet_offsets[(bar+phrase)%8], level=1)
        continue

    # Grundgroove. Pattern wird pro Takt transformiert; kein fester Loop.
    pattern = list(kick_patterns[(bar + bar//4) % len(kick_patterns)])
    if energy < .52: pattern = pattern[:2]
    for i, step in enumerate(pattern):
        accent = 1.0 if step == 0 else (.78 if i == 1 else .62)
        add("kick", bar, step, (0.42 + .42*energy)*accent, .50, level=min(4, 1+int(energy*4)))

    backbeats = (4, 12) if name not in {"breath", "reset"} else ((12,) if phrase % 2 else (4,))
    for i, step in enumerate(backbeats):
        add("snare", bar, step, (.30 + .39*energy)*(1.0 if step == 12 else .86),
            .46 + .08*i, level=min(4, 1+int(energy*4)))

    wood_steps = ((2, 6, 9, 14), (3, 7, 10, 15), (2, 5, 11, 14), (1, 6, 9, 13))[phrase]
    keep = max(2, int(round(len(wood_steps)*(0.52 + energy*.55))))
    for i, step in enumerate(wood_steps[:keep]):
        add("wood", bar, step, (.18 + .23*energy)*(1.0 if i == 0 else .75),
            .34 + .32*((i+bar)%3)/2, pitch=(i+phrase)%2, level=1+int(energy*3))

    shaker_steps = range(1, 16, 2) if energy > .69 else range(2, 16, 4)
    for i, step in enumerate(shaker_steps):
        velocity = (.10 + .12*energy)*(1.0 if step in {3, 7, 11, 15} else .72)
        add("shaker", bar, step, velocity, .65 if i % 2 else .35, level=1+int(energy*3))

    # Tonale Holznoten bilden eine 4-Takt-Antwort, keine durchlaufende Melodie.
    melodic_steps = ((3, 11), (6, 14), (2, 9), (7, 13))[phrase]
    for i, step in enumerate(melodic_steps if energy > .38 else melodic_steps[:1]):
        pitch = root + mallet_offsets[(bar*2+i) % len(mallet_offsets)]
        add("mallet", bar, step, .20 + .26*energy, .39 + .22*i,
            pitch=pitch, level=1+int(energy*3))

    if energy > .58:
        add("bass", bar, 0, .27 + .22*energy, .50, pitch=root, level=1+int(energy*3))
    if energy > .77 and phrase == 3:
        for i, step in enumerate((12, 13, 14, 15)):
            add("tom", bar, step, (.24 + .30*energy)*(0.70 + i*.10),
                .34 + i*.11, pitch=(104, 123, 146, 174)[i], level=2+int(energy*2))
    if name in {"climax", "finale"} and phrase == 0:
        add("cymbal", bar, 0, .15 + .14*energy, .54, level=2+int(energy*2))


# Die im Cue Sheet markierten Sprech-/Haltemomente erhalten musikalischen Raum.
gain = np.ones(N, dtype=np.float32)
halts = [c for c in cue_sheet()["cues"] if c["art"] == "halt"]
for cue in halts:
    duration = max(.35, float(cue.get("dauer", .5)))
    target = .10 if duration > 1.2 else .28
    apply_dip(gain, float(cue["t"]), duration, target, .11, .20)
mix *= gain[:, None]

mix = add_short_room(mix, .065)
# Subsonischen Offset der oszillatorbasierten Klangerzeuger entfernen.
for channel in range(2):
    mix[:, channel] = highpass(mix[:, channel], 25.0, 2)
mix = soft_limit(mix, 1.12)
mix, scale = peak_normalize(mix, -3.0)

target = OUT / "music-original.wav"
write_pcm24(target, mix)
stats = audio_stats(mix)
manifest = {
    "file": target.name,
    "sample_rate": SR,
    "bit_depth": 24,
    "duration_seconds": round(len(mix)/SR, 3),
    "bpm": 118.0,
    "bars": 68,
    "seed": SEED,
    "source": "Original procedural score; no external samples or reference audio",
    "sections": [{"start_bar": a+1, "end_bar": b, "name": n,
                  "energy_from": lo, "energy_to": hi} for a,b,n,lo,hi in SECTIONS],
    "event_count": len(events),
    "halt_ducks": [{"time": c["t"], "duration": c.get("dauer", 0), "scene": c["szene"]} for c in halts],
    "normalization_scale": round(scale, 5),
    "stats": stats,
}
write_manifest(OUT / "analysis" / "music-original.json", manifest)
print(f"{target} · {len(events)} Noten/Ereignisse · {TOTAL:.3f}s + {TAIL:.1f}s tail")
print(stats)

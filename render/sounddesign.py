#!/usr/bin/env python3
"""
Musikbett und Effekte aus timing.json — nachgebaut nach der Messung des Referenzfilms.

WAS DIE MESSUNG ERGAB (apple.wav, 75.8s, gemessen nicht vermutet):

  Effekte:  An 15 Bildschnitten faellt die Energie im Median auf 0.80x (Sub),
            0.50x (Mitten), 0.52x (Hoehen) — sie STEIGT also nicht. Nur 2 von 15
            Schnitten tragen einen echten Anschlag, und beide liegen auf
            B-Roll-Schnitten, also Originalton. Der Film hat KEIN Sounddesign
            auf den Bildereignissen.
  Rhythmus: Sub-Band-Periodizitaet 0.355 bei 182 BPM (= Sprachsilben),
            Hochband 0.062 — kein Hut, kein Kick, KEIN SCHLAGZEUG.
  Bett:     In den leisesten Fenstern (-41 dB) steht ein Dauerton bei
            156-160 Hz (Es3), dazu 124 Hz (H2) und 52 Hz (Gis1).
            Also eine getragene FLAECHE, kein Puls.
  Balance:  Sub 57 dB, Bass 59, Tiefmitten 55, Mitten 47, Hoehen 39, Luft 30.
            Stark bassbetont, steiler Abfall nach oben.
  Schluss:  Bei 68.0s absolute digitale Stille. Kein Ausklang.

Daraus folgt dieser Aufbau: eine leise, getragene Flaeche, die je Akt die
Tonart wechselt, ohne Puls und ohne Percussion. Effekte nur als seltene
Akzente, per --sfx steuerbar.

    python3 sounddesign.py                -> out/music.wav, out/sfx.wav
    python3 sounddesign.py --sfx none     ganz ohne Effekte (Apples Fassung)
    python3 sounddesign.py --sfx full     die alte, dichte Fassung zum Vergleich
"""
import json, os, shutil, subprocess, sys, wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
arg = lambda k, d: next((sys.argv[i+1] for i, a in enumerate(sys.argv) if a == k), d)

SR   = 48000
SFX_MODE = arg("--sfx", "sparse")          # none | sparse | full
cfg  = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
TOT  = max(s["start"] + s["dur"] for s in cfg["scenes"])
N    = int((TOT + 0.5) * SR)
rng  = np.random.default_rng(7)

HALT = {"05_aside", "11c_trick", "12_nein", "23_ui", "03_moment"}

def place(buf, sig, t, gain=1.0):
    i = int(t * SR)
    if i < 0 or i >= len(buf): return
    k = min(len(sig), len(buf) - i)
    buf[i:i+k] += sig[:k] * gain

def lowpass(x, fc):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1/SR)
    X *= 1.0 / (1.0 + (f / fc) ** 3)        # sanfte 18 dB/Okt-Neigung
    return np.fft.irfft(X, len(x))

# ── Das Bett ──────────────────────────────────────────────────────────────
# Gemessen: Es3 (156 Hz) als Dauerton, H2 (124), Gis1 (52). Daraus eine
# getragene Flaeche in dieser Lage, je Akt ein anderer Grundton.
ROOTS = [77.8, 77.8, 61.7, 82.4, 65.4, 77.8, 87.3, 61.7, 58.3, 65.4, 77.8]   # Es/H/E/C/…
acts, music = [], np.zeros(N)
for s in cfg["scenes"]:
    a = s["act"]
    if not acts or acts[-1][0] != a: acts.append([a, s["start"], 0])
    acts[-1][2] = s["start"] + s["dur"]

for i, (_, a, b) in enumerate(acts):
    i0, i1 = int(a*SR), min(N, int(b*SR))
    n = i1 - i0
    if n < 100: continue
    t = np.arange(n)/SR
    f = ROOTS[i % len(ROOTS)]
    # Grundton, Quinte, Oktave, leichte Duodezime — warm, ohne Schaerfe
    v = (np.sin(2*np.pi*f*t)*0.60 + np.sin(2*np.pi*f*1.4983*t)*0.26
         + np.sin(2*np.pi*f*2*t)*0.16 + np.sin(2*np.pi*f*0.5*t)*0.42
         + np.sin(2*np.pi*f*3*t)*0.05)
    # langsames Atmen, damit die Flaeche nicht steht
    v *= 1.0 + 0.14*np.sin(2*np.pi*t/7.3 + i)
    ramp = np.clip(np.minimum(t, n/SR - t) / 1.6, 0, 1) ** 1.5      # weiche Kanten
    schwung = 0.55 + 0.45 * (i / max(1, len(acts)-1))               # baut ueber den Film auf
    music[i0:i1] += v * ramp * schwung

music = lowpass(music, 900)                # gemessene Neigung: oben steil ab
music /= (np.max(np.abs(music)) or 1)

# An den Halte-Beats zieht das Bett zurueck — dort ist die Stille das Ereignis.
duck = np.ones(N)
for s in cfg["scenes"]:
    if s["id"] not in HALT: continue
    i0, i1 = int(s["start"]*SR), min(N, int((s["start"]+s["dur"])*SR))
    duck[i0:i1] = 0.22
kern = np.ones(int(0.25*SR)) / int(0.25*SR)
music *= np.convolve(duck, kern, mode="same")
music[int(TOT*SR):] = 0                    # harter Schluss wie im Referenzfilm

# ── Effekte: nur wenige Akzente ───────────────────────────────────────────
sfx = np.zeros(N)
def env(n, a, d, p=2.0):
    at = np.linspace(0, 1, max(1, int(a*SR)))
    dc = np.linspace(1, 0, max(1, n-len(at))) ** p
    return np.concatenate([at, dc])[:n]

def impact(dur=0.9):                       # tiefer Schwung, kein Schlag
    n = int(dur*SR); t = np.arange(n)/SR
    return (np.sin(2*np.pi*(44 + 26*np.exp(-t*9))*t) * env(n, 0.05, dur, 2.4))

def swell(dur=0.7):                        # Rauschanstieg, endet im Nichts
    n = int(dur*SR)
    x = rng.standard_normal(n)
    X = np.fft.rfft(x); f = np.fft.rfftfreq(n, 1/SR)
    X *= np.clip(1 - np.abs(f-1400)/3200, 0, 1)
    return np.fft.irfft(X, n) * (np.linspace(0, 1, n) ** 2)

if SFX_MODE != "none":
    scn = {s["id"]: s for s in cfg["scenes"]}
    # Genau drei Akzente — an den drei Momenten, die den Film tragen.
    if "12_nein" in scn:
        place(sfx, impact(1.1), scn["12_nein"]["start"], 0.55)
    if "22c_keine" in scn:
        st = [l for l in scn["22c_keine"]["layers"] if l["type"] == "strike"]
        if st: place(sfx, swell(0.8), scn["22c_keine"]["start"] + st[0]["t"] - 0.55, 0.42)
    if "15_element" in scn:
        c = [l for l in scn["15_element"]["layers"] if l["type"] == "card"]
        if c:
            n = int(0.05*SR); t = np.arange(n)/SR
            klick = np.sin(2*np.pi*900*t) * env(n, 0.0008, 0.05, 3.5)
            place(sfx, klick, scn["15_element"]["start"] + c[0]["swapAt"], 0.20)

def wav(path, x, peak):
    x = np.nan_to_num(x)
    m = np.max(np.abs(x)) or 1.0
    x = x / m * peak
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())

wav(OUT / "music.wav", music, 0.62)
wav(OUT / "sfx.wav",   sfx,   0.55 if SFX_MODE != "none" else 0.0)
print(f"out/music.wav (Flaeche, kein Puls) · out/sfx.wav (Modus: {SFX_MODE})   {TOT:.1f}s")

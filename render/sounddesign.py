#!/usr/bin/env python3
"""
Musikbett und Sounddesign aus timing.json.

Beides wird aus denselben Daten erzeugt wie das Bild — jeder Marker-Strich,
jeder Hintergrundwechsel, jeder Chunk bekommt sein Geräusch exakt auf dem
Frame, auf dem er im Bild passiert. Das ist der halbe Effekt des
Referenzfilms und von Hand kaum zu treffen.

    python3 sounddesign.py              -> out/music.wav, out/sfx.wav, out/mix.wav
    python3 sounddesign.py --no-music   nur Effekte
    python3 sounddesign.py --bpm 116

Temp-Track, kein Endprodukt: für den Film gehört eine echte Komposition
gekauft. Aber er sitzt auf dem Bild und zeigt, wie der Film klingen soll.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
arg = lambda k, d: next((sys.argv[i+1] for i, a in enumerate(sys.argv) if a == k), d)

SR   = 48000
BPM  = float(arg("--bpm", "112"))
cfg  = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
TOT  = max(s["start"] + s["dur"] for s in cfg["scenes"])
N    = int((TOT + 1.0) * SR)
rng  = np.random.default_rng(7)                      # fest, damit Läufe identisch sind

# Diese Beats leben von Stille — dort wird alles weggezogen.
HALT = {"05_aside", "11c_trick", "12_nein", "23_ui", "03_moment"}

def env(n, a=0.002, d=0.1, p=1.8):
    """Anschlag und Abfall — kurz und trocken, nie weich."""
    at = np.linspace(0, 1, max(1, int(a*SR)))
    dc = np.linspace(1, 0, max(1, n - len(at))) ** p
    return np.concatenate([at, dc])[:n]

def place(buf, sig, t, gain=1.0):
    i = int(t * SR)
    if i < 0 or i >= len(buf): return
    k = min(len(sig), len(buf) - i)
    buf[i:i+k] += sig[:k] * gain

def noise(n): return rng.standard_normal(n)

def bp(x, lo, hi):
    """Einfacher Bandpass über FFT — reicht für Sounddesign."""
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1/SR)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))

# ── Effekte ────────────────────────────────────────────────────────────────
def sfx_thump(dur=0.20):                 # Hintergrundwechsel: tiefer Schlag + Klick
    n = int(dur*SR); t = np.arange(n)/SR
    body = np.sin(2*np.pi*(58 + 40*np.exp(-t*38))*t) * env(n, 0.001, dur, 2.6)
    click = bp(noise(int(0.004*SR)), 1800, 9000) * env(int(0.004*SR), 0.0004, 0.004, 1.2)
    out = np.zeros(n); out[:len(body)] += body; out[:len(click)] += click*0.45
    return out

def sfx_pen(dur=0.30):                   # Marker-Strich: rauer Zug über Papier
    n = int(dur*SR)
    s = bp(noise(n), 900, 5200) * env(n, 0.008, dur, 1.35)
    s *= np.linspace(0.55, 1.0, n)       # nimmt zum Ende hin zu, wie ein echter Zug
    return s

def sfx_tick(dur=0.012):                 # Chunk erscheint: winziger Anschlag
    n = int(dur*SR)
    return bp(noise(n), 2600, 11000) * env(n, 0.0004, dur, 1.1)

def sfx_whoosh(dur=0.42):                # Strich quer durchs Raster
    n = int(dur*SR); t = np.arange(n)/SR
    x = noise(n) * env(n, 0.02, dur, 1.5)
    X = np.fft.rfft(x); f = np.fft.rfftfreq(n, 1/SR)
    X *= np.clip(1 - np.abs(f - 2400)/5200, 0, 1)    # betonter Mittenbereich
    return np.fft.irfft(X, n)

def sfx_click(dur=0.05):                 # Checkbox, Etikettwechsel
    n = int(dur*SR); t = np.arange(n)/SR
    return (np.sin(2*np.pi*1250*t) * env(n, 0.0006, dur, 3.0) * 0.6
            + bp(noise(n), 1500, 7000) * env(n, 0.0004, 0.012, 1.4) * 0.5)

# ── Effektspur aus dem Drehbuch ───────────────────────────────────────────
sfx = np.zeros(N)
JIT = [0.55, 1.0, 0.72, 1.5, 0.85, 1.25, 0.6, 1.1]     # identisch zu film.html
def chunk_count(text):
    n = 0
    for w in text.split(): n += 2 if len(w) >= 8 else 1
    return n

for s in cfg["scenes"]:
    t0, quiet = s["start"], s["id"] in HALT
    g = 0.30 if quiet else 1.0
    for f in s.get("bgFlips", []) + ([s["bgFlip"]] if s.get("bgFlip") else []):
        place(sfx, sfx_thump(), t0 + f["t"], 0.52*g)
    for l in s.get("layers", []):
        lt, ty = t0 + l.get("t", 0), l["type"]
        if ty == "text" and l.get("mode") == "words":
            step, acc = l.get("step", 0.115), 0.0
            for i in range(chunk_count(l["text"])):
                place(sfx, sfx_tick(), lt + acc, 0.20*g)
                acc += step * JIT[i % len(JIT)]
        elif ty == "text":
            place(sfx, sfx_tick(), lt, 0.24*g)
        elif ty == "markerText":
            place(sfx, sfx_pen(l.get("draw", 0.3)), lt, 0.42*g)
        elif ty in ("underline", "doodle"):
            place(sfx, sfx_pen(l.get("draw", 0.3)*0.9), lt, 0.34*g)
        elif ty == "strike":
            place(sfx, sfx_whoosh(), lt, 0.75)
        elif ty == "checkbox":
            place(sfx, sfx_click(), lt + (l["check"] - l.get("t", 0)), 0.55)
        elif ty == "card":
            place(sfx, sfx_click(), t0 + l["swapAt"], 0.70)   # der eine Klick beim Moduswechsel
        elif ty == "grid":
            for k in range(26):                                # Raster wuchert hörbar
                place(sfx, sfx_tick(0.008), lt + l["grow"]*(k/26)**1.7, 0.10 + 0.012*k)
        elif ty == "pile":
            for k in range(len(l["files"])):
                place(sfx, sfx_click(0.04), lt + k*l.get("step", .42), 0.30 + 0.06*k)
        elif ty == "sunburst":
            place(sfx, sfx_pen(0.22), lt, 0.40)
        elif ty == "liveEdit":
            place(sfx, sfx_pen(0.34), lt, 0.50)
        elif ty == "levels":
            for k in range(len(l["items"])):
                place(sfx, sfx_click(0.045), lt + k*l["step"], 0.34)

# ── Musikbett ─────────────────────────────────────────────────────────────
music = np.zeros(N)
if "--no-music" not in sys.argv:
    beat = 60.0 / BPM
    # eine Tonart je Akt — der Film baut sich in Schichten auf, ohne Drop
    ROOTS = [55.00, 55.00, 61.74, 65.41, 73.42, 65.41, 73.42, 82.41, 58.27, 65.41]
    acts  = []
    for s in cfg["scenes"]:
        a = s["act"]
        if not acts or acts[-1][0] != a: acts.append([a, s["start"], 0])
        acts[-1][2] = s["start"] + s["dur"]
    def root_at(t):
        for i, (_, a, b) in enumerate(acts):
            if a <= t < b: return ROOTS[i % len(ROOTS)], i / max(1, len(acts)-1)
        return ROOTS[-1], 1.0

    tt = np.arange(N) / SR
    # Fläche: Grundton plus Quinte, sehr leise, wächst über den Film
    pad = np.zeros(N)
    for i, (_, a, b) in enumerate(acts):
        i0, i1 = int(a*SR), min(N, int(b*SR))
        seg = np.arange(i1-i0)/SR
        f = ROOTS[i % len(ROOTS)]
        v = (np.sin(2*np.pi*f*seg) * 0.55 + np.sin(2*np.pi*f*1.5*seg) * 0.30
             + np.sin(2*np.pi*f*2*seg) * 0.18)
        ramp = np.minimum(np.minimum(seg, (i1-i0)/SR - seg) / 0.5, 1.0)   # weiche Kanten
        pad[i0:i1] += v * ramp * (0.16 + 0.10 * i/max(1, len(acts)-1))
    # Puls: Sub auf 1 und 3, Hut auf den Achteln — treibend, ohne Drop
    k = 0; t = 0.0
    while t < TOT:
        f, prog = root_at(t)
        if k % 2 == 0:
            n = int(0.16*SR); s_ = np.arange(n)/SR
            place(music, np.sin(2*np.pi*f*0.5*s_) * env(n, 0.002, 0.16, 2.2), t, 0.34)
        n = int(0.03*SR)
        place(music, bp(noise(n), 5000, 13000) * env(n, 0.0005, 0.03, 1.6),
              t + beat/2, 0.05 + 0.05*prog)
        t += beat; k += 1
    music += pad
    # An den Halte-Beats zieht die Musik zurueck — die Stille ist dort das Ereignis
    duck = np.ones(N)
    for s in cfg["scenes"]:
        if s["id"] not in HALT: continue
        i0, i1 = int(s["start"]*SR), min(N, int((s["start"]+s["dur"])*SR))
        f = np.linspace(0, 1, i1-i0)
        duck[i0:i1] = np.minimum(duck[i0:i1], 0.18 + 0.5*np.abs(f-0.5))
    kern = np.ones(int(0.12*SR)) / int(0.12*SR)
    music *= np.convolve(duck, kern, mode="same")

def wav(path, x, peak=0.86):
    x = np.nan_to_num(x)
    m = np.max(np.abs(x)) or 1.0
    x = np.tanh(x / m * 1.4) * peak
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())

wav(OUT / "sfx.wav",   sfx)
wav(OUT / "music.wav", music)
wav(OUT / "mix.wav",   music * 0.42 + sfx * 0.95)
print(f"out/music.wav · out/sfx.wav · out/mix.wav   ({TOT:.1f}s, {BPM:.0f} BPM)")

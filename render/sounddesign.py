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
    python3 sounddesign.py --drums        Schlagzeug auf die Einblendungen
    python3 sounddesign.py --drums --bpm 118

SCHLAGZEUG: Der Referenzfilm hat keins - nach HPSS-Trennung liegt die
Regelmaessigkeit der Anschlaege bei 0.00 (420 Anschlaege, mittlerer Abstand
0.159s, Streuung 0.166s: das sind Konsonanten). --drums ist deshalb kein
Nachbau, sondern eine eigene Entscheidung. Die Schlaege sitzen nicht auf
einem Raster, sondern auf den BILDEREIGNISSEN aus timing.json - Kick auf
jeden Hintergrundwechsel, Snare auf jeden Marker, Hut auf jeden Text-Chunk.
Das Schlagzeug spielt also die Schrift.
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

def bp(x, lo, hi):
    """Bandpass ueber FFT — reicht fuer Sounddesign."""
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1/SR)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))

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

# ── Melodieinstrument ────────────────────────────────────────────────────
# Ein angeschlagenes Instrument (marimbaartig: schneller Anschlag, kurzer
# Nachklang, wenige Obertoene). Es spielt eine ruhige Figur ueber der Flaeche,
# nicht ein Muster auf dem Bild - das macht die Schlagzeugspur.
BPM_M = 100.0
def anschlag(f0, dur=0.9, amp=1.0):
    n=int(dur*SR); t=np.arange(n)/SR
    e=np.exp(-t*4.2)                                  # kurzer, weicher Nachklang
    v=(np.sin(2*np.pi*f0*t)*1.00
       + np.sin(2*np.pi*f0*2*t)*0.30*np.exp(-t*8)     # Obertoene klingen frueher ab
       + np.sin(2*np.pi*f0*3.01*t)*0.12*np.exp(-t*14))
    an=np.minimum(1, t/0.004)                         # klarer Anschlag
    return v*e*an*amp

# Eine Figur je Akt: Grundton, Quinte, Oktave, Terz — ruhig, ohne Virtuositaet
FIGUR = [0, 7, 12, 3, 7, 0, 10, 7]
schlag = 60.0/BPM_M
for i,(_, a, b) in enumerate(acts):
    f0 = ROOTS[i % len(ROOTS)] * 2                    # eine Oktave ueber der Flaeche
    t = a + 0.25
    k = 0
    while t < b - 0.4:
        halbton = FIGUR[k % len(FIGUR)]
        # jeder zweite Anschlag leiser, das gibt der Figur einen Atem
        amp = 0.13 if k % 2 == 0 else 0.07
        place(music, anschlag(f0 * 2**(halbton/12), 0.9, amp), t)
        t += schlag * (2.0 if k % 4 != 3 else 3.0)    # halb so dicht, Luft dazwischen
        k += 1

# ── Bass auf die Eins ────────────────────────────────────────────────────
for i,(_, a, b) in enumerate(acts):
    f0 = ROOTS[i % len(ROOTS)] / 2
    t = a + 0.25
    while t < b - 0.3:
        n=int(0.55*SR); tt=np.arange(n)/SR
        place(music, np.sin(2*np.pi*f0*tt)*np.exp(-tt*3.0)*np.minimum(1,tt/0.008), t, 0.11)
        t += schlag*2

music = lowpass(music, 2600)               # Instrument braucht mehr Luft als die Flaeche allein
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

# ── Drumline-Percussion ──────────────────────────────────────────────────
# Referenz: „Rhythm Mischief" (Cold Storage Percussion Unit), ~118 BPM —
# Drumline-Snare, Toms, Rim Clicks, kurze gedaempfte Schlaege, mit
# Free-Jazz-Freiheit. Genau diese Freiheit hat meinen frueheren Test
# scheitern lassen: er verlangte Regelmaessigkeit und haette damit auch
# einen echten Schlagzeuger durchfallen lassen.
#
# Hier laeuft eine Groove-Ebene auf 118 BPM, und die AKZENTE sitzen auf
# den Bildereignissen aus timing.json. Der Groove traegt, das Bild fuehrt.
drums = np.zeros(N)
if "--drums" in sys.argv:
    BPM = float(arg("--bpm", "118")); BEAT = 60.0/BPM; S16 = BEAT/4

    def snare(dur=0.115, hell=1.0, amp=1.0):
        """Marching Snare: trocken, hell, sehr kurz."""
        n=int(dur*SR); t=np.arange(n)/SR
        k = bp(rng.standard_normal(n), 320, 9000*hell) * np.exp(-t*46)
        k += bp(rng.standard_normal(n), 2600, 11000) * np.exp(-t*95) * 0.55   # Teppich
        k += np.sin(2*np.pi*205*t) * np.exp(-t*60) * 0.22                     # Kessel
        return k * np.minimum(1, t/0.0006) * amp

    def buzz(dur=0.30, amp=0.55):
        """Wirbel: viele Schlaege, abnehmend."""
        n=int(dur*SR); out=np.zeros(n); t=0.0; a=1.0
        while t < dur-0.03:
            h=snare(0.045, 1.0, a); k=int(t*SR)
            out[k:k+len(h)] += h[:max(0,len(out)-k)]
            t += 0.021 + rng.random()*0.006; a *= 0.90
        return out*amp

    def tom(f0=118, dur=0.24, amp=1.0):
        n=int(dur*SR); t=np.arange(n)/SR
        v = np.sin(2*np.pi*(f0*np.exp(-t*7)+f0*0.62)*t) * np.exp(-t*13)
        v += bp(rng.standard_normal(n), 200, 2600) * np.exp(-t*55) * 0.30
        return v * np.minimum(1, t/0.001) * amp

    def rim(dur=0.055, amp=1.0):
        """Das Klack-Klack: Stock auf Rand."""
        n=int(dur*SR); t=np.arange(n)/SR
        v = bp(rng.standard_normal(n), 1500, 7000) * np.exp(-t*130)
        v += np.sin(2*np.pi*1680*t) * np.exp(-t*110) * 0.45
        return v * np.minimum(1, t/0.0004) * amp

    def gedaempft(dur=0.07, amp=1.0):
        """Kurzer, stark gedaempfter Schlag."""
        n=int(dur*SR); t=np.arange(n)/SR
        return bp(rng.standard_normal(n), 500, 4200) * np.exp(-t*80) * np.minimum(1,t/0.0006) * amp

    # Groove: 16tel-Raster, Drumline-Muster mit Synkopen und Geisternoten.
    # 16 Positionen je Takt. S=Snare, g=Geisternote, r=Rim, t=Tom, .=Pause
    # Zehn Muster statt vier, dazu leere und sehr duenne Takte. Gemessen war
    # meine erste Fassung mit Staerke 0.665 viel metronomischer als das Original
    # (0.104) - Free Jazz heisst, dass das Muster bricht.
    MUSTER = [
      # Fast die Haelfte der Takte ist leer oder fast leer. Genau das meint
      # „negative space": der Groove setzt aus und kommt wieder.
      "..g.S..g..r.S.g.",  "................",  "....S.......S...",
      "..g.S.tg..r.S...",  "................",  "..r.........r...",
      "S..gr.g.S...r...",  "................",  "....S...........",
      "..g.S..g..r.....",  "t...............",  "................",
      "..r.S..t....S...",  "................",  "......r.........",
      "....S..g........",  "................",  "..g.S..g..r.S.tt",
    ]
    ende = TOT
    takt = 0; t = 0.0
    folge = [int(rng.integers(0, len(MUSTER))) for _ in range(400)]   # fest, nicht zufaellig je Lauf
    stille_bis = -1.0
    while t < ende:
        if t < stille_bis:                      # bewusster Aussetzer
            t += BEAT*4; takt += 1; continue
        if rng.random() < 0.16:                 # gelegentlich ganz aufhoeren
            stille_bis = t + BEAT*4*(1 if rng.random()<0.6 else 2)
        m = MUSTER[folge[takt % len(folge)]]
        for i16, z in enumerate(m):
            tt = t + i16*S16
            if tt >= ende: break
            still = any(sc["id"] in HALT and sc["start"] <= tt < sc["start"]+sc["dur"]
                        for sc in cfg["scenes"])
            if still: continue
            # Versatz und Anschlagstaerke schwanken — ein Schlagzeuger spielt
            # nie zweimal gleich. Ohne das klingt es wie ein Drumcomputer.
            swing = (S16*0.16 if i16 % 2 else 0.0) + (rng.random()-0.5)*0.012
            dyn   = 0.72 + rng.random()*0.5
            if   z=="S": place(drums, snare(0.115,1.0,1.0), tt+swing, 0.52*dyn)
            elif z=="g": place(drums, snare(0.075,0.8,0.34), tt+swing, 0.30*dyn)
            elif z=="r": place(drums, rim(), tt+swing, 0.42*dyn)
            elif z=="t": place(drums, tom(118+rng.random()*22), tt+swing, 0.40*dyn)
        t += BEAT*4; takt += 1

    # Akzente auf die Bildereignisse — hier fuehrt das Bild den Groove.
    for s_ in cfg["scenes"]:
        t0 = s_["start"]
        if s_["id"] in HALT: continue
        place(drums, tom(96, 0.30), t0, 0.62)                    # jeder Szenenanfang
        for f in s_.get("bgFlips", []):
            place(drums, snare(0.13,1.0,1.0), t0+f["t"], 0.72)   # Hintergrundwechsel
        for l in s_.get("layers", []):
            lt, ty = t0 + l.get("t", 0), l["type"]
            if ty == "markerText":
                place(drums, rim(0.06,1.0), lt + l.get("draw",0.3)*0.5, 0.55)
            elif ty == "levels":
                for k in range(len(l["items"])):
                    place(drums, gedaempft(), lt+k*l["step"], 0.48)
            elif ty == "pile":
                for k in range(len(l["files"])):
                    place(drums, snare(0.10,0.9,0.7), lt+k*l.get("step",.42), 0.30+0.10*k)
            elif ty == "card" and l.get("swapAt") is not None:
                place(drums, tom(88, 0.36), t0+l["swapAt"], 0.95)
            elif ty == "strike":
                place(drums, buzz(0.34,0.8), lt-0.30, 0.85)      # Wirbel in den Strich hinein
                place(drums, snare(0.15,1.0,1.0), lt+0.10, 0.95)
            elif ty == "grid":
                for k in range(14):
                    place(drums, rim(0.04, 0.6), lt+l["grow"]*(k/14)**1.7, 0.16+0.03*k)

def wav(path, x, peak):
    x = np.nan_to_num(x)
    m = np.max(np.abs(x)) or 1.0
    x = x / m * peak
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())

wav(OUT / "music.wav", music, 0.62)
if "--drums" in sys.argv:
    wav(OUT / "drums.wav", drums, 0.80)
    print(f"out/drums.wav — Schlaege auf den Bildereignissen")
wav(OUT / "sfx.wav",   sfx,   0.55 if SFX_MODE != "none" else 0.0)
print(f"out/music.wav (Flaeche, kein Puls) · out/sfx.wav (Modus: {SFX_MODE})   {TOT:.1f}s")

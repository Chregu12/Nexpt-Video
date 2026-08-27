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

# ── Kein Bett ─────────────────────────────────────────────────────────────
# Hier stand bis eben eine getragene Flaeche: Grundton, Quinte, Oktave, je Akt
# eine andere Tonart. Sie ist raus, und zwar gemessen begruendet:
#
#   Apple                  119 BPM (Staerke 0.13) · Stille 13%
#   NEXPT Percussion        66 BPM (Staerke 0.01) · Stille 76%
#   NEXPT Grundierung      155 BPM (Staerke 0.76) · Stille  6%   <- die Flaeche
#
# Die Flaeche hat den Gesamtmix auf 147 BPM gezogen, obwohl die Percussion auf
# 118 laeuft. Ihr Atmen (7.3s), die Akt-Rampen und das Ducking ergaben zusammen
# genau die Periodizitaet, die im Mix als eigenes Tempo gelesen wurde. Das
# `music *= 0.16` half nicht: `wav()` normalisiert danach ohnehin auf Peak 0.62.
#
# Dazu die Vorgabe selbst: keine Pads, keine Synth-Akkorde, keine Flaechen,
# kein melodisches Leadinstrument. „Percussion Sound Design statt Song."
# Also traegt die Percussion allein — und das Tiefe kommt aus der
# Marschtrommel, nicht aus einem Sinus.
music = np.zeros(N)
acts = []
for s in cfg["scenes"]:
    a = s["act"]
    if not acts or acts[-1][0] != a: acts.append([a, s["start"], 0])
    acts[-1][2] = s["start"] + s["dur"]

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

    def bassdrum(dur=0.34, f0=64, amp=1.0):
        """Marschtrommel: tief, trocken, kurzer Beater-Klick obendrauf.
        Traegt den Bassbereich, den vorher die Flaeche gefuellt hat —
        gemessen liegt der Referenzfilm bei Sub 57 dB / Bass 59 dB, also
        stark tiefbetont. Eine Trommel ist kein Pad: sie schlaegt und ist weg."""
        n=int(dur*SR); t=np.arange(n)/SR
        v = np.sin(2*np.pi*(f0*1.9*np.exp(-t*24) + f0)*t) * np.exp(-t*9.5)
        v += bp(rng.standard_normal(n), 900, 4500) * np.exp(-t*140) * 0.16   # Beater
        return v * np.minimum(1, t/0.0008) * amp

    def gedaempft(dur=0.07, amp=1.0):
        """Kurzer, stark gedaempfter Schlag."""
        n=int(dur*SR); t=np.arange(n)/SR
        return bp(rng.standard_normal(n), 500, 4200) * np.exp(-t*80) * np.minimum(1,t/0.0006) * amp

    # Percussion Sound Design statt Song: Text erscheint -> tak.
    # Bewegung -> rrrat-tak. Pause -> Stille. Der Groove traegt darunter
    # durch — an den Halte-Beats setzt er komplett aus.
    # 16 Positionen je Takt. B=Marschtrommel, S=Snare, g=Geisternote,
    # r=Rim, t=Tom, .=Pause
    # Zehn Muster statt vier, dazu leere und sehr duenne Takte. Gemessen war
    # meine erste Fassung mit Staerke 0.665 viel metronomischer als das Original
    # (0.104) - Free Jazz heisst, dass das Muster bricht.
    MUSTER = [
      # Gemessen an der Referenz: Apple liest 117 BPM bei Puls-Staerke 0.18.
      # Der Grund ist banal — dort sitzt auf JEDER Viertel ein hoerbarer
      # Schlag, Trommel und Snare im Wechsel, und alles andere ist Fuellung.
      # Meine erste Fassung war zu metronomisch (0.665), die zweite hatte gar
      # keinen Puls mehr (0.02), weil ich die Viertel selbst weggelassen habe.
      # Also: Viertel stehen (0, 4, 8, 12), dazwischen wird frei gespielt,
      # und drei von achtzehn Takten schweigen ganz.
      "B.g.S.g.B.r.S.g.",  "BrgrS.g.BrgrS.gg",  "B...S..gB.r.S.tg",
      "B.g.S.tgB.r.S.g.",  "................",  "B.r.S.r.B.r.S.r.",
      "B.ggS...B.g.S..g",  "B.g.S.g.B...S.tt",  "B..gS.g.BrggS.g.",
      "B.g.S..gB.r.S.g.",  "Btg.S.g.B.r.S.tg",  "................",
      "B.g.S.r.B.g.S.r.",  "B.g.S.ggB.r.S.g.",  "BrgrS.ggBrgrS.g.",
      "B.g.S..tB.r.S...",  "................",  "B.g.S..gB.r.S.tt",
    ]
    ende = TOT
    takt = 0; t = 0.0
    folge = [int(rng.integers(0, len(MUSTER))) for _ in range(400)]   # fest, nicht zufaellig je Lauf
    stille_bis = -1.0
    while t < ende:
        if t < stille_bis:                      # bewusster Aussetzer
            t += BEAT*4; takt += 1; continue
        if rng.random() < 0.12:                 # seltener Aussetzer, nie zwei Takte
            stille_bis = t + BEAT*4
        m = MUSTER[folge[takt % len(folge)]]
        for i16, z in enumerate(m):
            tt = t + i16*S16
            if tt >= ende: break
            still = any(sc["id"] in HALT and sc["start"] <= tt < sc["start"]+sc["dur"]
                        for sc in cfg["scenes"])
            if still: continue
            # Versatz und Anschlagstaerke schwanken — ein Schlagzeuger spielt
            # nie zweimal gleich. Ohne das klingt es wie ein Drumcomputer.
            viertel = (i16 % 4 == 0)
            swing = (0.0 if viertel else S16*0.16 if i16 % 2 else 0.0) \
                    + (rng.random()-0.5)*(0.004 if viertel else 0.012)
            dyn   = 0.72 + rng.random()*0.5
            if   z=="B": place(drums, bassdrum(), tt+swing, 0.34*dyn)
            elif z=="S": place(drums, snare(0.115,1.0,1.0), tt+swing, 0.30*dyn)
            elif z=="g": place(drums, snare(0.075,0.8,0.34), tt+swing, 0.30*dyn)
            elif z=="r": place(drums, rim(), tt+swing, 0.16*dyn)
            elif z=="t": place(drums, tom(118+rng.random()*22), tt+swing, 0.24*dyn)
        t += BEAT*4; takt += 1

    # Jeder Aktwechsel bekommt die Marschtrommel. Vorher machte das die
    # Lautstaerkerampe der Flaeche; jetzt macht es ein Schlag.
    for _a, _st, _en in acts:
        if any(sc["id"] in HALT and sc["start"] <= _st < sc["start"]+sc["dur"]
               for sc in cfg["scenes"]): continue
        place(drums, bassdrum(0.42, 58), _st, 0.85)

    # Akzente auf die Bildereignisse — hier fuehrt das Bild den Groove.
    for s_ in cfg["scenes"]:
        t0 = s_["start"]
        if s_["id"] in HALT: continue
        place(drums, tom(96, 0.30), t0, 0.62)                    # jeder Szenenanfang
        for f in s_.get("bgFlips", []):
            place(drums, snare(0.13,1.0,1.0), t0+f["t"], 0.72)   # Hintergrundwechsel
        JIT=[0.55,1.0,0.72,1.5,0.85,1.25,0.6,1.1]      # identisch zu film.html
        for l in s_.get("layers", []):
            lt, ty = t0 + l.get("t", 0), l["type"]
            if ty == "text" and l.get("mode") == "words":
                # „Text erscheint -> tak": Holzklick je Chunk, erster betont
                st_, acc = l.get("step", 0.145), 0.0
                n_ = sum(2 if len(w)>=8 else 1 for w in l["text"].split())
                for k in range(n_):
                    if k and l.get("lastDelay") and k == n_-1: acc += l["lastDelay"]
                    place(drums, rim(0.045, 1.0), lt+acc, 0.42 if k==0 else 0.20)
                    acc += st_ * JIT[k % len(JIT)]
            elif ty == "markerText":
                # „Bewegung -> rrrat-tak": kurzer Wirbel in den Schlag hinein
                place(drums, buzz(0.16, 0.55), lt, 0.50)
                place(drums, snare(0.11,1.0,1.0), lt + l.get("draw",0.3)*0.62, 0.62)
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

# ── Raum ─────────────────────────────────────────────────────────────────
# Trockene Einzelschlaege ergaben 52% digitale Stille zwischen den Anschlaegen
# (Referenzfilm: 12%). Der Unterschied ist kein Arrangement, sondern der Raum:
# eine Trommel in einem Saal klingt aus. Also eine kurze, dichte Fahne — kein
# Hall als Effekt, sondern damit die Schlaege nicht im Vakuum stehen.
if "--drums" in sys.argv:
    _n  = int(0.34*SR); _t = np.arange(_n)/SR
    _ir = rng.standard_normal(_n) * np.exp(-_t*11.0)
    _ir = bp(_ir, 180, 7000); _ir[:int(0.004*SR)] = 0        # ohne Direktschall
    _ir /= (np.max(np.abs(_ir)) or 1)
    drums = drums + np.convolve(drums, _ir, mode="full")[:len(drums)] * 0.028

def wav(path, x, peak):
    x = np.nan_to_num(x)
    m = np.max(np.abs(x)) or 1.0
    x = x / m * peak
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())

wav(OUT / "music.wav", music, 0.0)      # still: die Percussion traegt allein
if "--drums" in sys.argv:
    wav(OUT / "drums.wav", drums, 0.80)
    print(f"out/drums.wav — Schlaege auf den Bildereignissen")
wav(OUT / "sfx.wav",   sfx,   0.55 if SFX_MODE != "none" else 0.0)
print(f"out/music.wav (still, kein Bett) · out/sfx.wav (Modus: {SFX_MODE})   {TOT:.1f}s")

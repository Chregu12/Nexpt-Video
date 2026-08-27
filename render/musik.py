#!/usr/bin/env python3
"""
Den lizenzierten Musiktrack auf den Film schneiden.

    python3 musik.py                     out/_musik/rhythm-mischief.m4a
    python3 musik.py <datei.wav|m4a>     anderer Track
    python3 musik.py --raster            nur messen, nichts schreiben

Der Track liegt NICHT im Repo. `out/_musik/` ist in .gitignore, weil die
Lizenz beim Lizenznehmer liegt und nicht am Repository haengt. Wer den Film
neu baut, legt seine eigene lizenzierte Kopie dorthin.

GEMESSEN am gelieferten Track (nicht angenommen):

    Tempo          118.00 BPM  — exakt, per Kammfilter ueber 108-128 BPM
    Erster Schlag  0.222 s     — Downbeat auf Zaehlzeit 1
    Takt           2.0339 s    — 89 volle Takte, danach Ausklang
    Laenge         183.05 s    — der Film ist 135.44 s, es muessen also
                                 rund 48 s raus

Die Abschnitte des Tracks (Pegel je Takt, Bruch bei > 3 dB Sprung):

    Takt  0- 2   0.2- 6.3 s  -19.4 dB   Intro, duenn
    Takt  3-23   6.3-49.0 s  -13.4 dB   Hauptgroove
    Takt 24-26  49.0-55.1 s  -21.8 dB   Breakdown, fast weg
    Takt 27-38  55.1-79.5 s  -15.9 dB   Wiederaufbau
    Takt 39-47  79.5-97.9 s   -7.5 dB   Hochpunkt
    Takt 48-50  97.9-104.0 s -21.5 dB   Absturz
    Takt 51-73 104.0-150.7 s -12.5 dB   zweiter Hauptteil
    Takt 74-88 150.7-181.2 s  -9.3 dB   Schlussaufbau

Und hier wird es interessant: dieser Verlauf passt fast ohne Zutun auf die
Dramaturgie des Films, weil beide denselben Wechsel aus Spannung und
Aufloesung haben.

    Track-Breakdown  49.0-55.1 s   Film  51.7  „(das ist der Trick)"
                                   Film  53.3  „Vier Sichtweisen. Ein Chaos?"
    Track-Hochpunkt  79.5-97.9 s   Film  83.7  „100% verbunden."
                                   Film  91.5  „Sehen es alle. SOFORT."
    Track-Absturz    97.9-104.0 s  Film  98.2  „Aber Struktur ist noch
                                                keine Uebersicht. ALLEIN"

Der Absturz des Tracks liegt 0.4 s vor dem Einwand des Films. Das ist Zufall,
aber ein brauchbarer: der Schnitt muss dort gar nichts tun.

Deshalb laeuft der Track bis Takt 58 ungeschnitten durch. Erst danach wird
gekuerzt — von Takt 58 auf Takt 81, also mitten im zweiten Hauptteil in den
Schlussaufbau hinein. Der Schnitt liegt auf einer Takt-Eins und faellt mit
25_seht zusammen („Du siehst, was du brauchst."), 0.12 s daneben. Ab dort
traegt der Schlussaufbau des Tracks das Versprechen bis zum Ende.
"""
import json, os, shutil, subprocess, sys, wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
SR  = 48000
cfg = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
TOT = max(s["start"] + s["dur"] for s in cfg["scenes"])
HALT = {"05_aside", "11c_trick", "12_nein", "23_ui", "03_moment"}

quelle = next((a for a in sys.argv[1:] if not a.startswith("--")),
              str(OUT / "_musik" / "rhythm-mischief.m4a"))
if not Path(quelle).exists():
    print(f"{quelle} fehlt.\n"
          f"Die lizenzierte Kopie des Tracks nach out/_musik/ legen — sie liegt\n"
          f"absichtlich nicht im Repo.")
    sys.exit(1)


def laden(pfad, sr=SR, stereo=True):
    roh = subprocess.run([FFMPEG, "-v", "quiet", "-i", pfad, "-ac", "2" if stereo else "1",
                          "-ar", str(sr), "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(roh, "<f4").astype(np.float64)
    return x.reshape(-1, 2) if stereo else x


def raster(pfad):
    """Tempo und ersten Downbeat messen. 78 BPM waere die Unterschwingung —
    deshalb wird der Suchbereich auf 108-128 BPM gelegt und das Raster
    anschliessend gegen die vier Zaehlzeiten geprueft."""
    x = laden(pfad, 22050, stereo=False)
    H, W, sr = 128, 1024, 22050
    n = 1 + (len(x) - W) // H
    S = np.abs(np.fft.rfft(np.lib.stride_tricks.as_strided(
        x, (n, W), (x.strides[0]*H, x.strides[0])) * np.hanning(W), axis=1))
    flux = np.maximum(0, np.diff(S, axis=0)).sum(1); fps = sr / H
    f = (flux - flux.mean()) / (flux.std() or 1)
    bestes = None
    for bpm in np.arange(108, 128.01, 0.01):
        beat = 60 / bpm
        for off in np.arange(0, beat, 0.006):
            idx = ((np.arange(off, len(f)/fps, beat)) * fps).astype(int)
            idx = idx[idx < len(f)]
            v = f[idx].mean()
            if bestes is None or v > bestes[0]: bestes = (v, bpm, off)
    _, bpm, off = bestes
    beat, bar = 60/bpm, 240/bpm
    zaehl = []
    for p in range(4):
        idx = ((np.arange(off + p*beat, len(f)/fps, bar)) * fps).astype(int)
        idx = idx[idx < len(f)]
        zaehl.append(f[idx].mean())
    return bpm, off + int(np.argmax(zaehl))*beat, bar


BPM, DB0, BAR = raster(quelle)
print(f"gemessen: {BPM:.2f} BPM · erster Takt {DB0:.3f}s · Takt {BAR:.4f}s")
if "--raster" in sys.argv:
    sys.exit(0)

# ── Der Schnitt ───────────────────────────────────────────────────────────
# (von Takt, bis Takt) — beide Kanten liegen auf einer Takt-Eins, damit die
# Naht im Puls verschwindet. Der zweite Teil laeuft bis ans Dateiende, damit
# der Ausklang des Tracks erhalten bleibt.
SCHNITT = [(0, 58), (81, None)]

roh  = laden(quelle)
ende = lambda b: len(roh)/SR if b is None else DB0 + b*BAR
teile, gesamt = [], 0.0
for a, b in SCHNITT:
    i0, i1 = int((DB0 + a*BAR)*SR), int(min(ende(b), len(roh)/SR)*SR)
    teile.append(roh[i0:i1]); gesamt += (i1-i0)/SR
    print(f"  Takt {a:>3} - {'Ende' if b is None else b:>4}   "
          f"{DB0+a*BAR:6.2f}-{min(ende(b), len(roh)/SR):6.2f}s   {(i1-i0)/SR:5.2f}s")

# Naht: 24 ms gleichleistungs-Blende gegen das Knacken. Kuerzer als ein
# Sechzehntel (127 ms), der Schnitt bleibt also hoerbar auf der Eins.
N = int((TOT + 0.5) * SR)
musik = np.zeros((N, 2))
pos, blende = 0, int(0.024*SR)
for k, t in enumerate(teile):
    m = min(len(t), N - pos)
    if m <= 0: break
    stueck = t[:m].copy()
    if k and pos >= blende:
        rampe = np.sqrt(np.linspace(0, 1, blende))[:, None]
        musik[pos:pos+blende] *= np.sqrt(np.linspace(1, 0, blende))[:, None]
        stueck[:blende] *= rampe
    musik[pos:pos+m] += stueck
    pos += m

print(f"  Summe {gesamt:.2f}s, Film {TOT:.2f}s "
      f"-> {'Stille am Schluss' if gesamt < TOT else 'am Schluss beschnitten'}: "
      f"{abs(TOT-gesamt):.2f}s")

# ── Halte-Beats ───────────────────────────────────────────────────────────
# Fuenf Stellen im Film leben davon, dass nichts passiert. Drei davon deckt
# der Track selbst ab (11c_trick und 12_nein liegen im Breakdown), zwei nicht:
# 03_moment und 05_aside liegen mitten im Hauptgroove, 23_ui im zweiten
# Hauptteil. Dort zieht die Musik zurueck.
duck = np.ones(N)
for s in cfg["scenes"]:
    if s["id"] not in HALT: continue
    i0, i1 = int(s["start"]*SR), min(N, int((s["start"]+s["dur"])*SR))
    duck[i0:i1] = 0.28
kern = np.ones(int(0.22*SR)) / int(0.22*SR)
musik *= np.convolve(duck, kern, mode="same")[:, None]

# Harter Schluss wie im Referenzfilm, mit 0.3 s Blende statt Abriss.
aus = int(TOT*SR)
fade = int(0.30*SR)
if aus - fade > 0:
    musik[aus-fade:aus] *= np.linspace(1, 0, fade)[:, None]
musik[aus:] = 0

ziel = OUT / "music.wav"
m = np.max(np.abs(musik)) or 1.0
musik = musik / m * 0.89
with wave.open(str(ziel), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(musik, -1, 1) * 32767).astype("<i2").tobytes())
print(f"{ziel} — {TOT:.1f}s, stereo")

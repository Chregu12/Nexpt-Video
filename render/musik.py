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
Schlussaufbau hinein. Ab dort traegt der Schlussaufbau das Versprechen bis
zum Ende.

Dazu kommt ein gemessener Versatz je Teil, damit die Anschlaege des Tracks
oefter mit unseren Bildereignissen zusammenfallen — die Begruendung dafuer
steht unten bei SCHNITT, samt der Messung, warum dabei nicht mehr
herauskommt.
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
# (von Takt, bis Takt, Versatz in Sekunden).
#
# WARUM DER VERSATZ JETZT NULL IST:
#
# Der Wunsch war, dass die Musik zur Schriftanimation passt. Erste Messung am
# Referenzfilm — und das Ergebnis ging gegen meine Erwartung: Apples Schrift
# sitzt NICHT auf dem Takt. 145 Bildereignisse gegen das 118er Raster,
# drei Aufloesungen, jedes Mal exakt Zufallsniveau:
#
#     Viertel      Raster 508 ms · 24% innerhalb 60 ms   (Zufall 24%)
#     Achtel       Raster 254 ms · 48% innerhalb 60 ms   (Zufall 47%)
#     Sechzehntel  Raster 127 ms · 91% innerhalb 60 ms   (Zufall 94%)
#
# Was dort den Eindruck von Synchronitaet macht, ist nur die gemeinsame
# Atemfrequenz: Apples Bild wechselt im Mittel alle 0.52 s, ein Beat dauert
# 0.51 s.
#
# Die Musik zu verschieben brachte entsprechend wenig — gemessen 19% statt
# 12% Zufallsniveau, mehr war bei festem Tempo gegen einen auf die Stimme
# geschnittenen Film nicht zu holen. Deshalb liegt jetzt der FILM auf dem
# Raster: takt.py rastert die Szenendauern auf Achtel und die grossen
# Ereignisse auf Sechzehntel, alles bei 118.00 BPM ab Filmzeit 0.000.
#
# Damit braucht die Musik keinen Versatz mehr. Der erste Downbeat des Tracks
# (0.222 s) faellt auf den Filmanfang, und von da an teilen Film und Musik ein
# einziges Raster. Der Film ist 68 Takte lang, genau.
#
# DER SCHNITT: Takte 0-58 laufen durch, dann weiter ab Takt 80 bis zum
# Dateiende. 22 Takte fallen weg, der Rest passt auf die 68. Die Naht liegt
# bei 117.97 s und damit auf einer Takt-Eins, ein Viertel vor dem Halte-Beat
# 23_ui. Der zweite Teil bringt den Schlussaufbau des Tracks auf die letzten
# 20 Sekunden — also auf „Du siehst, was du brauchst" bis „NEXPT ist dein
# Partner fuer deine Prozesse".
#
# Und die Dramaturgie passt weiterhin ohne Zutun (Filmzeit = Trackzeit - 0.222):
#
#     Breakdown   48.8- 54.9 s   „(das ist der Trick)"          53.6 s
#     Hochpunkt   79.3- 97.6 s   „100% verbunden."              85.4 s
#                                „Sehen es alle. SOFORT."       93.3 s
#     Absturz     97.6-103.7 s   „...noch keine Uebersicht."   100.2 s
SCHNITT = [(0, 58, 0.0), (80, None, 0.0)]

roh  = laden(quelle)
ende = lambda b: len(roh)/SR if b is None else DB0 + b*BAR
N = int((TOT + 0.5) * SR)
musik = np.zeros((N, 2))

# Die Teile werden nacheinander gesetzt; der Versatz jedes Teils verschiebt
# seinen Beginn gegen die Filmzeit. Ein negativer Versatz laesst den Anfang
# des Tracks weg, ein positiver laesst Stille davor stehen.
pos_s, blende = 0.0, int(0.024*SR)
for k, (a, b, versatz) in enumerate(SCHNITT):
    t0, t1 = DB0 + a*BAR, min(ende(b), len(roh)/SR)
    beginn = pos_s + versatz
    i0, i1 = int(t0*SR), int(t1*SR)
    stueck = roh[i0:i1].copy()
    ziel_i = int(beginn*SR)
    if ziel_i < 0:                      # Musik faengt vor dem Film an: vorne kappen
        stueck = stueck[-ziel_i:]; ziel_i = 0
    m = min(len(stueck), N - ziel_i)
    if m <= 0: break
    stueck = stueck[:m]
    if k and ziel_i >= blende:
        rampe = np.sqrt(np.linspace(0, 1, blende))[:, None]
        musik[ziel_i:ziel_i+blende] *= np.sqrt(np.linspace(1, 0, blende))[:, None]
        stueck[:blende] *= rampe
    musik[ziel_i:ziel_i+m] += stueck
    print(f"  Takt {a:>3} - {'Ende' if b is None else b:>4}   {t0:6.2f}-{t1:6.2f}s   "
          f"Versatz {versatz*1000:+5.0f}ms  ->  Film {beginn:6.2f}-{beginn+(t1-t0):6.2f}s")
    pos_s = beginn + (t1 - t0)
print(f"  Musik endet bei {pos_s:.2f}s, Film bei {TOT:.2f}s")

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

# ── Die Anschlaege in Filmzeit hinterlegen ────────────────────────────────
# takt.py zieht die grossen Bildereignisse auf diese Zeiten. Gemessen wird auf
# dem ROHEN Track, nicht auf dieser Datei — hier ist schon geduckt und
# geblendet, das verschiebt die Flanken.
def anschlaege(x, sr=22050):
    H, W = 64, 1024
    n = 1 + (len(x) - W) // H
    S = np.abs(np.fft.rfft(np.lib.stride_tricks.as_strided(
        x, (n, W), (x.strides[0]*H, x.strides[0])) * np.hanning(W), axis=1))
    fl = np.maximum(0, np.diff(S, axis=0)).sum(1); fps = sr/H
    f = (fl - fl.mean()) / (fl.std() or 1)
    sw = np.percentile(f, 88)
    roh = [i for i in range(1, len(f)-1) if f[i] > sw and f[i] >= f[i-1] and f[i] > f[i+1]]
    idx, st = [], []
    for i in roh:
        if idx and (i-idx[-1])/fps < 0.045:
            if f[i] > st[-1]: idx[-1], st[-1] = i, f[i]
        else: idx.append(i); st.append(f[i])
    t, v = np.array(idx)/fps, np.array(st)
    return t[v >= np.percentile(v, 75)]

mono = laden(quelle, 22050, stereo=False)
roh_t = anschlaege(mono)
in_film, lauf = [], 0.0
for a, b, versatz in SCHNITT:
    t0, t1 = DB0 + a*BAR, min(ende(b), len(roh)/SR)
    beginn = lauf + versatz
    for x in roh_t:
        if t0 <= x < t1:
            ft = beginn + (x - t0)
            if 0 <= ft < TOT: in_film.append(round(float(ft), 4))
    lauf = beginn + (t1 - t0)
in_film.sort()
(OUT / "_musik" / "anschlaege.json").write_text(
    json.dumps({"bpm": BPM, "beat": round(60/BPM, 6), "tot": TOT,
                "anschlaege": in_film}, indent=1), encoding="utf-8")
print(f"  {len(in_film)} starke Anschlaege in Filmzeit -> out/_musik/anschlaege.json")

ziel = OUT / "music.wav"
m = np.max(np.abs(musik)) or 1.0
musik = musik / m * 0.89
with wave.open(str(ziel), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(musik, -1, 1) * 32767).astype("<i2").tobytes())
print(f"{ziel} — {TOT:.1f}s, stereo")

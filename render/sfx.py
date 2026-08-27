#!/usr/bin/env python3
"""
Sounddesign aus dem Cue Sheet: Whooshes, Clicks, Impacts, Riser.

    python3 cuesheet.py && python3 sfx.py     -> out/sfx.wav (stereo)
    python3 sfx.py --nur schnitt,marker       nur diese Arten
    python3 sfx.py --pegel 0.8                lauter oder leiser

WOHER DAS KOMMT

Bisher hatte der Film drei Effekte auf 2:18 — weil der Referenzfilm (Apple)
gemessen KEIN Sounddesign auf den Bildereignissen hat: an 15 Schnitten faellt
die Energie im Median auf 0.80x (Sub), 0.50x (Mitten), 0.52x (Hoehen), sie
steigt also nicht.

Die neue Referenz ist eine andere Schule: Music-to-Picture plus Sounddesign
statt Musik daruntergelegt. Beides ist richtig, es sind zwei Handschriften —
diese Datei baut die zweite.

SELBST NACHGEMESSEN am gelieferten Samsung-Film (78.3 s), und an einer
Stelle kommt etwas anderes heraus als in der Vorlage:

    Onsets            285 = 3.64/s      (Vorlage: 172 = 2.20/s)
    harte Schnitte    10, alle 7.8 s    (Vorlage: 13)
    Schnitt -> Akzent  4 von 10 im Fenster, Median +84 ms
                                        (Vorlage: alle 13 innerhalb 120 ms)
    Bewegung -> Akzent 19 von 30, Median +15 ms
                                        (Vorlage: 90% innerhalb 100 ms)

Die Zaehlungen haengen an der Schwelle des Detektors, da sind beide Werte
vertretbar. Der Befund darunter ist es nicht: die Referenz vertont vor allem
BEWEGUNG — dort sitzt der Akzent mit +15 ms praktisch auf dem Bild. Der
Schnitt bekommt seltener einen, und dann traege dahinter (+84 ms). Meine
erste Fassung hatte genau das umgekehrt gewichtet.

Weiter gemessen, und danach sind die Klaenge gebaut:

    Klangfarbe der 57 staerksten Akzente, je Band gegen das Sub:
      Sub 0.0 · Bass -3.3 · Tiefmitten -10.4 · Mitten -16.6 ·
      Hoehen -26.8 · Luft -29.3 dB
    Abklingzeit bis -20 dB   Median 649 ms (Quartile 419/870)
    Akzentspitze ueber dem laufenden Bett   +11 dB
    Lautheit des Films       -13.6 LUFS, LRA 7.7, Spitze +0.4 dBFS
                             (Apple dagegen -17.7 / 4.3)

DIE EBENEN

    impact   Schnitt, Hintergrundwechsel, fallende Datei
             Tiefer Koerper mit Tonhoehenabfall, Mittenschlag, winziger Klick.
    whoosh   Marker, Unterstrich, Pfeile, Wortflut
             Rauschen mit wanderndem Band. Faehrt der Marker im Bild von
             links nach rechts, faehrt der Whoosh im Stereobild mit.
    click    Zeilenanfang, Etikettwechsel, Kritzel
             Kurz, aber MIT Koerper — ein reiner Hochtonklick saesse genau in
             dem Band, das die Referenz 27 dB zurueckhaelt.
    tick     Rasteraufbau — dieselbe Familie, leiser und ansteigend.
    riser    Rueckwaerts anmutender Anlauf VOR einem Ereignis, endet exakt
             auf dem Schlag.

WAS BEWUSST NICHT VERTONT WIRD

Die Halte-Beats. Dort steht im Cue Sheet `stille`, und das ist eine Anweisung
wie jede andere: „(das ist der Trick)", „NEIN.", „(auch nicht im UI)" leben
davon, dass nichts passiert. Und von den 157 Text-Chunks bekommt nur der
erste je Zeile einen Klick — alle zu vertonen waere Geprassel.
"""
import json, os, shutil, sys, wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
SR   = 48000
rng  = np.random.default_rng(11)
arg  = lambda k, d: next((sys.argv[i+1] for i, a in enumerate(sys.argv) if a == k), d)
PEGEL = float(arg("--pegel", "1.0"))
NUR   = set(x.strip() for x in arg("--nur", "").split(",") if x.strip())

pfad = OUT / "analysis" / "cue_sheet.json"
if not pfad.exists():
    print("out/analysis/cue_sheet.json fehlt — erst `python3 cuesheet.py`.")
    sys.exit(1)
daten = json.loads(pfad.read_text(encoding="utf-8"))
TOT   = daten["film"]["laenge"]
N     = int((TOT + 1.0) * SR)
mix   = np.zeros((N, 2))


def bp(x, lo, hi):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1/SR)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))


def setzen(sig, t, x=0.5, gain=1.0):
    """Legt ein Mono-Signal an die Stelle t, gleichleistungs-panoramiert.
    x=0 ganz links, 1 ganz rechts — aber nie haerter als 70/30, sonst faellt
    der Effekt aus dem Bild statt es zu begleiten."""
    i = int(t * SR)
    if i < 0 or i >= N: return
    k = min(len(sig), N - i)
    xx = 0.5 + (np.clip(x, 0, 1) - 0.5) * 0.8
    l, r = np.cos(xx * np.pi/2), np.sin(xx * np.pi/2)
    mix[i:i+k, 0] += sig[:k] * gain * l
    mix[i:i+k, 1] += sig[:k] * gain * r


def huell(n, an, ab, p=2.0):
    a = np.linspace(0, 1, max(1, int(an*SR)))
    d = np.linspace(1, 0, max(1, n - len(a))) ** p
    return np.concatenate([a, d])[:n]


def impact(staerke=1.0, dauer=0.85):
    """Tiefer Koerper mit Tonhoehenabfall, darueber ein Koerperschlag und ein
    winziger Anschlag. Gemessen an der Referenz: die Akzente klingen bis -20 dB
    im Median 649 ms aus (Quartile 419/870) — meine erste Fassung war mit
    400 ms deutlich zu kurz und klang deshalb nach Klopfen statt nach Wucht."""
    n = int(dauer*SR); t = np.arange(n)/SR
    f0 = 44 + 14*staerke
    v  = np.sin(2*np.pi*(f0*2.4*np.exp(-t*22) + f0)*t) * np.exp(-t*3.4)      # Sub, traegt
    v += np.sin(2*np.pi*(f0*3.1*np.exp(-t*30) + f0*2)*t) * np.exp(-t*7.0) * 0.45
    v += bp(rng.standard_normal(n), 120, 700) * np.exp(-t*16) * 0.22         # Koerper
    v += bp(rng.standard_normal(n), 1800, 12000) * np.exp(-t*110) * 0.10     # Anschlag
    return v * np.minimum(1, t/0.0008) * staerke


def whoosh(dauer=0.30, staerke=1.0, richtung=1):
    """Rauschen mit wanderndem Band. Das Band liegt bewusst TIEF: gemessen
    haelt die Referenz die Hoehen 27 dB und die Luft 29 dB unter dem Sub.
    Ein heller Zisch-Whoosh waere in dieser Handschrift ein Fremdkoerper."""
    n = max(int(dauer*SR), int(0.12*SR)); t = np.arange(n)/SR; u = t/t[-1]
    x = rng.standard_normal(n)
    X = np.fft.rfft(x); f = np.fft.rfftfreq(n, 1/SR)
    X[(f < 160) | (f > 12000)] = 0
    X *= 1.0 / (1.0 + (f/2600)**1.0)
    x = np.fft.irfft(X, n)
    mitte = 420 * (u if richtung > 0 else 1-u) + 240
    x = x * (0.5 + 0.5*np.sin(2*np.pi*np.cumsum(mitte)/SR))
    x += np.sin(2*np.pi*(60 + 40*u)*t) * 0.25 * np.sin(np.pi*u)     # Luftdruck darunter
    return x * (np.sin(np.pi*u) ** 1.25) * staerke


def click(staerke=1.0):
    """Nicht nur ein Klick, sondern ein Klick MIT Koerper — sonst sitzt er in
    dem Band, das die Referenz am staerksten zurueckhaelt."""
    n = int(0.22*SR); t = np.arange(n)/SR
    v  = np.sin(2*np.pi*(150*np.exp(-t*40) + 96)*t) * np.exp(-t*17) * 0.9
    v += bp(rng.standard_normal(n), 500, 2400) * np.exp(-t*70) * 0.30
    v += bp(rng.standard_normal(n), 2600, 11000) * np.exp(-t*170) * 0.20
    return v * np.minimum(1, t/0.0005) * staerke


def tick(staerke=1.0, hoehe=1.0):
    n = int(0.10*SR); t = np.arange(n)/SR
    v  = np.sin(2*np.pi*(230*hoehe*np.exp(-t*50) + 150*hoehe)*t) * np.exp(-t*34) * 0.7
    v += bp(rng.standard_normal(n), 900*hoehe, 10000) * np.exp(-t*130) * 0.34
    return v * np.minimum(1, t/0.0004) * staerke


def riser(dauer=0.55, staerke=1.0):
    """Anlauf, der auf dem Schlag endet. Band und Pegel steigen, dann Schluss.
    Wird VOR den Zeitpunkt gesetzt, nicht darauf."""
    n = int(dauer*SR); t = np.arange(n)/SR; u = t/t[-1]
    x = rng.standard_normal(n)
    X = np.fft.rfft(x); f = np.fft.rfftfreq(n, 1/SR)
    X[(f < 120) | (f > 8000)] = 0
    x = np.fft.irfft(X, n)
    x = x * (0.2 + 0.8*u**2)
    x += np.sin(2*np.pi*np.cumsum(70 + 420*u**2)/SR) * 0.35 * u**2
    return x * (u ** 1.5) * staerke


# ── Die Cues abarbeiten ───────────────────────────────────────────────────
# Die Pegel sind bewusst gestaffelt: ein Schnitt darf mehr als ein
# Zeilenanfang, sonst klingt alles gleich wichtig und damit nichts.
# Gemessen an der Referenz — und hier weicht meine Messung von der
# gelieferten ab, mit Folgen fuer das Design:
#
#   Schnitte:  4 von 10 bekommen einen Akzent im Fenster, Median +84 ms
#   Bewegung:  19 von 30 der staerksten, Median +15 ms
#
# Die Referenz vertont also vor allem BEWEGUNG, nicht den Schnitt — und wo
# sie den Schnitt vertont, sitzt der Akzent traege dahinter. Meine erste
# Fassung hatte es umgekehrt (Schnitt 0.52, Marker 0.26). Hier ist es
# gedreht: der Markerstrich, der durchs Bild faehrt, ist das Ereignis.
PEGELN = {"schnitt": 0.30, "bgwechsel": 0.34, "strich": 0.95, "strich-anlauf": 0.45,
          "marker": 0.58, "unterstrich": 0.34, "strahlen": 0.55, "pfeile": 0.62,
          "wortflut": 0.30, "karte": 0.62, "livekorrektur": 0.55, "kritzel": 0.20,
          "zeile": 0.20, "ebene": 0.26, "raster": 0.14, "stapel": 0.55}
# Der Whoosh hat seine Spitze in der MITTE (sin-Fenster), nicht am Anfang.
# Setzt man ihn auf den Cue, liegt der hoerbare Akzent eine halbe Strichdauer
# zu spaet — gemessen kam die Effektspur so auf +86 ms Median gegen das Cue
# Sheet, bei einem Ziel von +15 ms. Er startet deshalb frueher und faehrt in
# den Cue hinein, statt nach ihm anzufangen.
VORLAUF = 0.42        # Anteil der Dauer, um den ein Whoosh vorgezogen wird

# Die gemessenen +84 ms der Referenz an ihren Schnitten habe ich zuerst
# nachgebaut. Das war ein Missverstaendnis: dort gehoert der Akzent nicht zum
# Schnitt, sondern zur Bewegung DANACH. Ein nachhinkender Schnitt-Impact
# klingt nur nach schlechtem Timing.
gezaehlt = {}
for c in daten["cues"]:
    art, s_, t, x = c["art"], c["staerke"], c["t"], c.get("x", 0.5)
    if art == "halt": continue
    if NUR and art not in NUR: continue
    g = PEGELN.get(art, 0.20) * s_ * PEGEL
    gezaehlt[art] = gezaehlt.get(art, 0) + 1

    if art in ("schnitt", "bgwechsel"):
        setzen(impact(s_, 0.90 if art == "schnitt" else 0.75), t, 0.5, g)
    elif art == "stapel":
        setzen(impact(s_ * 0.8, 0.55), t, x, g)
    elif art == "strich":
        d_ = max(c["dauer"], 0.22)
        setzen(whoosh(d_, 1.0, +1), t - d_*VORLAUF, 0.5, g * 0.8)
        setzen(impact(1.0, 1.05), t + c["dauer"] * 0.75, 0.5, g)
    elif art == "strich-anlauf":
        setzen(riser(max(c["dauer"], 0.30), s_), t, 0.5, g)
    elif art in ("marker", "unterstrich", "strahlen", "pfeile", "wortflut"):
        # Faehrt links im Bild, klingt links: das Panorama folgt dem Strich.
        d_ = max(c["dauer"], 0.16)
        setzen(whoosh(d_, s_, +1 if x >= 0.5 else -1), t - d_*VORLAUF, x, g)
    elif art in ("zeile", "karte", "kritzel", "ebene", "livekorrektur"):
        setzen(click(s_), t, x, g)
        if art == "livekorrektur":
            setzen(riser(0.35, 0.6), t - 0.35, x, g * 0.5)
    elif art == "raster":
        setzen(tick(s_, 0.85 + 0.5*s_), t, x, g)

# ── Angleichen an die gemessene Referenz ──────────────────────────────────
# Erst von Hand geneigt — und danebengelegen: die Effektspur kam auf Mitten
# -38 dB gegen die -17 dB der Referenz und auf Luft -92 gegen -29. Also viel
# zu dunkel, weil ich die Neigung ohne Gegenprobe eingestellt hatte.
#
# Jetzt rechnet sich die Entzerrung selbst aus: die Baender der gebauten Spur
# werden gemessen, gegen die Referenzkurve gehalten und die Differenz als
# Filter angewandt. Begrenzt auf +-10 dB — wo eine Spur in einem Band gar
# nichts hat, soll nicht das Rauschen hochgezogen werden.
#
# ZIEL: die 57 staerksten Akzente des Referenzfilms, je Band gegen das Sub.
ZIEL = [(20, 80, 0.0), (80, 250, -3.3), (250, 800, -10.4),
        (800, 2500, -16.6), (2500, 6000, -26.8), (6000, 11000, -29.3)]

def messen(x):
    mono = x.mean(axis=1)
    S = np.abs(np.fft.rfft(mono)); f = np.fft.rfftfreq(len(mono), 1/SR)
    return np.array([np.sqrt((S[(f >= lo) & (f < hi)]**2).mean() + 1e-16)
                     for lo, hi, _ in ZIEL])

def angleichen(x, runden=2):
    for _ in range(runden):
        ist  = 20*np.log10(messen(x) / (messen(x)[0] or 1e-16))
        soll = np.array([z for _, _, z in ZIEL])
        korr = np.clip(soll - ist, -10, 10)
        mitten = np.array([np.sqrt(lo*hi) for lo, hi, _ in ZIEL])
        f = np.fft.rfftfreq(len(x), 1/SR)
        g = 10 ** (np.interp(np.log(np.maximum(f, 1)), np.log(mitten), korr) / 20)
        x = np.fft.irfft(np.fft.rfft(x, axis=0) * g[:, None], len(x), axis=0)
    return x

mix = angleichen(mix)
ist = 20*np.log10(messen(mix) / messen(mix)[0])
print("Baender nach dem Angleichen (Ziel in Klammern):")
for (lo, hi, z), v in zip(ZIEL, ist):
    print(f"   {lo:5d}-{hi:5d} Hz  {v:6.1f} dB  ({z:+.1f})")

# Kein Normalisieren auf Vollaussteuerung: die Effektspur soll UNTER der
# Musik liegen und nur an den Akzenten darueber. Gemessen steht ein Akzent
# der Referenz +11 dB ueber ihrem laufenden Bett; das stellt mischen.sh ein.
spitze = np.max(np.abs(mix)) or 1.0
mix = mix / spitze * 0.80
with wave.open(str(OUT / "sfx.wav"), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())

n = sum(gezaehlt.values())
print(f"out/sfx.wav · {n} Effekte auf {TOT:.1f}s = {n/TOT:.2f}/s · stereo")
for a, k in sorted(gezaehlt.items(), key=lambda x: -x[1]):
    print(f"   {k:4d}  {a}")

#!/usr/bin/env python3
"""
Sounddesign aus dem Cue Sheet: Whooshes, Clicks, Impacts, Riser.

Gebaut aus ECHTEN Aufnahmen — den Schlaegen des eigenen Musikloops, die
render/proben.py herausschneidet. Sinus kommt nur noch dort vor, wo die
Aufnahme nichts hat: als Fundament unter den Impacts, weil die Quelle
gemessen keinen Ton unter 988 Hz enthaelt.

    python3 proben.py && python3 cuesheet.py && python3 sfx.py -> out/sfx.wav
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
             Echte Trommel, zwei Oktaven tiefer, plus Sinus als Fundament.
    whoosh   Marker, Unterstrich, Pfeile, Wortflut
             Rueckwaerts gespielter, gedehnter Schlag. Faehrt der Marker im
             Bild von links nach rechts, faehrt der Whoosh im Stereobild mit.
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


def spitze(sig):
    """Wo liegt die hoerbare Spitze des Klangs? Ueber eine 5-ms-Huellkurve,
    nicht ueber den Rohwert — ein einzelner Ausreisser ist nicht das, was
    das Ohr als Schlag hoert."""
    F = max(1, int(0.005*SR))
    e = np.sqrt(np.convolve(sig**2, np.ones(F)/F, mode="same"))
    return int(np.argmax(e))


def setzen(sig, t, x=0.5, gain=1.0, auf_cue=True):
    """Legt ein Mono-Signal so, dass seine SPITZE auf t liegt — nicht sein
    Anfang. Das ist der Unterschied zwischen „der Effekt beginnt beim Bild"
    und „der Effekt trifft das Bild".

    Vorher stand hier ein fester Vorlauf von 42% der Dauer. Das passte zum
    Sinusfenster der synthetischen Fassung; die echten Aufnahmen haben ihre
    Spitze woanders, und prompt lag die Effektspur wieder 32 ms zu spaet.
    Jetzt misst sich jeder Klang selbst aus.

    x=0 ganz links, 1 ganz rechts — aber nie haerter als 70/30, sonst faellt
    der Effekt aus dem Bild statt es zu begleiten."""
    i = int(t * SR) - (spitze(sig) if auf_cue else 0)
    if i < 0 or i >= N: return
    k = min(len(sig), N - i)
    if k <= 0: return
    xx = 0.5 + (np.clip(x, 0, 1) - 0.5) * 0.8
    l, r = np.cos(xx * np.pi/2), np.sin(xx * np.pi/2)
    mix[i:i+k, 0] += sig[:k] * gain * l
    mix[i:i+k, 1] += sig[:k] * gain * r


# ── Die Klangpalette: echte Aufnahmen ─────────────────────────────────────
# Der Einwand war richtig — Sinus plus gefiltertes Rauschen klingt nach
# Roboter, weil es einer ist. Alles Perkussive kommt jetzt aus echten
# Schlaegen, geschnitten aus dem eigenen Musikloop (render/proben.py).
#
# Damit klingt es nicht nur echt, sondern PASSEND: es sind dieselben
# Instrumente wie in der Musik, derselbe Raum, dieselbe Aufnahme.
#
# Was der Loop nicht hergibt, ist eine tiefe Trommel — gemessen liegt sein
# tiefster Schwerpunkt bei 988 Hz. Die Impacts entstehen deshalb wie in
# jedem Tonstudio: eine echte Aufnahme wird tief transponiert (das gibt die
# Textur) und ein Sinus darunter gelegt (der gibt das Fundament, das die
# Aufnahme nicht hat). Whooshes und Riser sind rueckwaerts gespielte und
# gedehnte Schlaege — auch das ist gaengige Praxis und kein Syntheseklang.
PROBEN = OUT / "_proben"
if not (PROBEN / "palette.json").exists():
    print("out/_proben/ fehlt — erst `python3 proben.py`.")
    sys.exit(1)
_pal = json.loads((PROBEN / "palette.json").read_text(encoding="utf-8"))["proben"]

def _lies(name):
    with wave.open(str(PROBEN / name), "rb") as w:
        d = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
    return d

PALETTE = {k: [_lies(n) for n in v] for k, v in _pal.items()}
_zaehler = {}

def probe(art, i=None):
    """Reihum durch die Varianten — ein Schlagzeuger trifft nie zweimal
    identisch, und viermal derselbe Klick waere sofort als Kopie hoerbar."""
    v = PALETTE[art]
    if i is None:
        i = _zaehler.get(art, 0); _zaehler[art] = i + 1
    return v[i % len(v)].copy()


def transponieren(x, faktor):
    """Wie ein Sampler: langsamer abgespielt heisst tiefer UND laenger.
    faktor 0.25 = zwei Oktaven tiefer, vierfache Laenge."""
    n = int(len(x) / faktor)
    return np.interp(np.linspace(0, len(x)-1, n), np.arange(len(x)), x)


def rueckwaerts(x):
    return x[::-1].copy()


def impact(staerke=1.0, dauer=0.85):
    """Echte Trommel, zwei Oktaven tiefer, plus ein Sinus als Fundament.
    Genau so werden Impacts im Studio gebaut — die Aufnahme bringt die
    Textur, der Sinus das, was das Mikrofon nicht hatte.
    Gemessen an der Referenz klingen die Akzente bis -20 dB im Median 649 ms
    aus (Quartile 419/870); meine erste Fassung war mit 400 ms zu kurz."""
    n = int(dauer*SR); t = np.arange(n)/SR
    v = np.zeros(n)
    koerper = transponieren(probe("snare"), 0.22)       # echte Aufnahme, tief
    k = min(len(koerper), n)
    v[:k] += koerper[:k] * np.exp(-t[:k]*4.2)
    f0 = 44 + 14*staerke
    v += np.sin(2*np.pi*(f0*2.4*np.exp(-t*22) + f0)*t) * np.exp(-t*3.4) * 0.85
    anschlag = probe("klick")                            # echter Transient obenauf
    k = min(len(anschlag), n)
    v[:k] += anschlag[:k] * 0.22
    return v / (np.max(np.abs(v)) or 1) * staerke


def whoosh(dauer=0.30, staerke=1.0, richtung=1):
    """Ein rueckwaerts gespielter, gedehnter Schlag — daraus macht man
    Whooshes wirklich. Das Band liegt tief: gemessen haelt die Referenz die
    Hoehen 27 dB und die Luft 29 dB unter dem Sub."""
    n = max(int(dauer*SR), int(0.12*SR))
    roh_ = transponieren(probe("snare"), 0.30)
    if richtung > 0: roh_ = rueckwaerts(roh_)            # zieht heran
    v = np.interp(np.linspace(0, len(roh_)-1, n), np.arange(len(roh_)), roh_)
    u = np.arange(n)/max(1, n-1)
    X = np.fft.rfft(v); f = np.fft.rfftfreq(n, 1/SR)
    X[(f < 140) | (f > 12000)] = 0
    v = np.fft.irfft(X, n)
    v *= (np.sin(np.pi*u) ** 1.15)
    v += np.sin(2*np.pi*(60 + 40*u)*np.arange(n)/SR) * 0.20 * np.sin(np.pi*u)
    return v / (np.max(np.abs(v)) or 1) * staerke


def click(staerke=1.0):
    """Echter Stockschlag aus dem Loop, mit etwas Tiefe darunter — ein
    reiner Hochtonklick saesse in dem Band, das die Referenz 27 dB
    zurueckhaelt."""
    v = probe("klick")
    n = len(v); t = np.arange(n)/SR
    v = v + np.sin(2*np.pi*(150*np.exp(-t*40) + 96)*t) * np.exp(-t*19) * 0.30
    return v / (np.max(np.abs(v)) or 1) * staerke


def tick(staerke=1.0, hoehe=1.0):
    """Echter Rim, je Spalte etwas hoeher transponiert."""
    v = transponieren(probe("tick"), np.clip(hoehe, 0.7, 1.5))
    return v / (np.max(np.abs(v)) or 1) * staerke * 0.9


def riser(dauer=0.55, staerke=1.0):
    """Mehrere rueckwaerts gespielte Schlaege, immer dichter — der Anlauf
    endet auf dem Schlag, nicht darauf."""
    n = int(dauer*SR)
    v = np.zeros(n)
    t = 0.0; abstand = dauer * 0.42
    while t < dauer - 0.02:
        h = rueckwaerts(transponieren(probe("tick"), 0.55))
        i = int(t*SR); k = min(len(h), n - i)
        if k > 0: v[i:i+k] += h[:k] * (0.25 + 0.75*(t/dauer))
        t += abstand; abstand = max(0.035, abstand*0.62)
    u = np.arange(n)/max(1, n-1)
    schwung = transponieren(probe("snare"), 0.18)
    k = min(len(schwung), n)
    v[:k] += rueckwaerts(schwung[:k]) * 0.5
    v *= u ** 1.3
    return v / (np.max(np.abs(v)) or 1) * staerke


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
# Jeder Klang wird auf seine eigene Spitze ausgerichtet (siehe setzen()),
# nicht auf seinen Anfang. Ein Whoosh faehrt damit in den Cue hinein statt
# nach ihm anzufangen. Nur die Riser nicht — die sollen ja auf dem Schlag
# ENDEN.
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
        setzen(whoosh(max(c["dauer"], 0.22), 1.0, +1), t, 0.5, g * 0.8)
        setzen(impact(1.0, 1.05), t + c["dauer"] * 0.75, 0.5, g)
    elif art == "strich-anlauf":
        setzen(riser(max(c["dauer"], 0.30), s_), t, 0.5, g, auf_cue=False)
    elif art in ("marker", "unterstrich", "strahlen", "pfeile", "wortflut"):
        # Faehrt links im Bild, klingt links: das Panorama folgt dem Strich.
        setzen(whoosh(max(c["dauer"], 0.16), s_, +1 if x >= 0.5 else -1), t, x, g)
    elif art in ("zeile", "karte", "kritzel", "ebene", "livekorrektur"):
        setzen(click(s_), t, x, g)
        if art == "livekorrektur":
            setzen(riser(0.35, 0.6), t - 0.35, x, g * 0.5, auf_cue=False)
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

def angleichen(x, runden=4):
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

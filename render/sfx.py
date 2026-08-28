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


def breit(sig, mass):
    """Erhoeht die Stereobreite ueber eine kurze Laufzeitdifferenz zwischen
    den Kanälen. Gemessen liegt das Seite/Mitte-Verhaeltnis der Referenz bei
    0.14-0.16, ihr breitester Kapitel-Uebergang aber bei 0.92 — Uebergaenge
    sind dort hoerbar weiter als der laufende Groove."""
    d = int(np.clip(mass, 0, 1) * 0.012 * SR)
    if d < 1: return sig, sig
    # Blende zwischen Mono und voller Gegenphase. Die erste Fassung hat den
    # rechten Kanal ganz invertiert — das ist das Aeusserste und hat die
    # Effektspur auf Seite/Mitte 0.33 getrieben, gegen 0.14-0.16 der Referenz.
    m = float(np.clip(mass, 0, 1))
    l = np.concatenate([sig, np.zeros(d)])
    spaet = np.concatenate([np.zeros(d), sig])
    r = (1 - m) * l + m * (-spaet)
    return l, r


def setzen(sig, t, x=0.5, gain=1.0, auf_cue=True, weite=0.0):
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
    if weite > 0:
        sl, sr = breit(sig, weite)
        k = min(len(sl), N - i)
        mix[i:i+k, 0] += sl[:k] * gain * l
        mix[i:i+k, 1] += sr[:k] * gain * r
        return
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


# ── Angleichen, je Kategorie einzeln ──────────────────────────────────────
# Die gelieferte Analyse des Referenzfilms misst nicht einen Klang, sondern
# JEDE der 54 Cues einzeln — Schwerpunkt, Bandanteile, Stereobreite, Spitze.
# Damit laesst sich jeder Effekttyp fuer sich kalibrieren statt alle ueber
# eine gemeinsame Kurve.
#
#   Kategorie      Schwerpunkt   tief  mitte  hoch   Seite/Mitte  Spitze
#   Impact              398 Hz    0.73  0.23   0.01     0.141     -2.6 dB
#   Click               527 Hz    0.53  0.41   0.02     0.163     -4.2 dB
#   Whoosh              807 Hz    0.50  0.28   0.05     0.164     -5.6 dB
#   Stinger             246 Hz    0.90  0.09   0.02     0.130     -2.5 dB
#
# „tief" ist < 250 Hz, „mitte" 250-4000, „hoch" > 4000 — die Bandgrenzen der
# Quellanalyse. Die Impacts sind also mit 73% Tiefenanteil noch tiefer, als
# ich sie gebaut hatte, und die Whooshes mit 807 Hz Schwerpunkt deutlich
# dunkler als ein ueblicher Zisch-Whoosh.
ZIELE = {
    "impact":  {"tief": 0.73, "mitte": 0.23, "hoch": 0.01, "spitze": -2.6},
    "click":   {"tief": 0.53, "mitte": 0.41, "hoch": 0.02, "spitze": -4.2},
    "whoosh":  {"tief": 0.50, "mitte": 0.28, "hoch": 0.05, "spitze": -5.6},
    "stinger": {"tief": 0.90, "mitte": 0.09, "hoch": 0.02, "spitze": -2.5},
}
BAENDER = [(20, 250, "tief"), (250, 4000, "mitte"), (4000, 16000, "hoch")]

def anteile(x):
    S = np.abs(np.fft.rfft(x)); f = np.fft.rfftfreq(len(x), 1/SR)
    e = np.array([(S[(f >= lo) & (f < hi)]**2).sum() for lo, hi, _ in BAENDER])
    return e / (e.sum() + 1e-16)

def formen(x, kat, runden=8):
    """Zieht einen einzelnen Klang auf die Bandverteilung seiner Kategorie.

    Der Filter ist stueckweise konstant je Band, nicht zwischen den
    Bandmitten interpoliert. Der erste Anlauf tat Letzteres, und damit blieb
    ein Klang mit Energie knapp oberhalb von 250 Hz praktisch in der
    Tiefenkorrektur haengen: Click kam auf 0.78 Tiefenanteil statt 0.53,
    Whoosh auf 0.82 statt 0.50.

    Begrenzt auf +-3 dB je Runde — wo ein Klang in einem Band gar nichts hat,
    soll nicht das Rauschen hochgezogen werden."""
    ziel = np.array([ZIELE[kat][n] for _, _, n in BAENDER])
    f = np.fft.rfftfreq(len(x), 1/SR)
    # Zugehoerigkeit je Frequenz zu ihrem Band, an den Kanten weich
    zug = []
    for lo, hi, _ in BAENDER:
        w = np.clip((np.log(np.maximum(f, 1)) - np.log(max(lo, 1))) / 0.35, 0, 1) * \
            np.clip((np.log(hi) - np.log(np.maximum(f, 1))) / 0.35, 0, 1)
        zug.append(w)
    zug = np.array(zug); zug /= (zug.sum(axis=0) + 1e-12)
    for _ in range(runden):
        ist = anteile(x)
        korr = np.clip(10 * np.log10((ziel + 1e-6) / (ist + 1e-6)), -3, 3)
        g = 10 ** ((zug * korr[:, None]).sum(axis=0) / 20)
        x = np.fft.irfft(np.fft.rfft(x) * g, len(x))
    return x / (np.max(np.abs(x)) or 1)


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
    return formen(v, "impact") * staerke


def whoosh(dauer=0.30, staerke=1.0, richtung=1):
    """Ein rueckwaerts gespielter, gedehnter Schlag — daraus macht man
    Whooshes wirklich. Das Band liegt tief: gemessen haelt die Referenz die
    Hoehen 27 dB und die Luft 29 dB unter dem Sub."""
    n = max(int(dauer*SR), int(0.12*SR))
    roh_ = transponieren(probe("snare"), 0.48)
    if richtung > 0: roh_ = rueckwaerts(roh_)            # zieht heran
    v = np.interp(np.linspace(0, len(roh_)-1, n), np.arange(len(roh_)), roh_)
    u = np.arange(n)/max(1, n-1)
    X = np.fft.rfft(v); f = np.fft.rfftfreq(n, 1/SR)
    X[(f < 140) | (f > 12000)] = 0
    v = np.fft.irfft(X, n)
    v *= (np.sin(np.pi*u) ** 1.15)
    v += np.sin(2*np.pi*(60 + 40*u)*np.arange(n)/SR) * 0.20 * np.sin(np.pi*u)
    return formen(v, "whoosh") * staerke


def click(staerke=1.0):
    """Echter Stockschlag aus dem Loop, mit etwas Tiefe darunter — ein
    reiner Hochtonklick saesse in dem Band, das die Referenz 27 dB
    zurueckhaelt."""
    v = probe("klick")
    n = len(v); t = np.arange(n)/SR
    v = v + np.sin(2*np.pi*(150*np.exp(-t*40) + 96)*t) * np.exp(-t*19) * 0.30
    return formen(v, "click") * staerke


def tick(staerke=1.0, hoehe=1.0):
    """Echter Rim, je Spalte etwas hoeher transponiert."""
    v = transponieren(probe("tick"), np.clip(hoehe, 0.7, 1.5))
    return formen(v, "click") * staerke * 0.9


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
    schwung = transponieren(probe("snare"), 0.32)
    k = min(len(schwung), n)
    v[:k] += rueckwaerts(schwung[:k]) * 0.5
    v *= u ** 1.3
    return formen(v, "whoosh") * staerke


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
# Die Pegel folgen der gemessenen Spitze je Kategorie: Impact -2.6 dB,
# Click -4.2, Whoosh -5.6. Ein Impact darf also am lautesten sein — was sich
# NICHT widerspricht mit dem anderen Befund, dass die Referenz vor allem
# BEWEGUNG vertont: Bewegung bekommt haeufiger einen Effekt, ein Aufprall
# bekommt einen lauteren.
LAUT = {"impact": 1.00, "click": 0.62, "whoosh": 0.52, "stinger": 1.02}
PEGELN = {"schnitt": 0.40, "bgwechsel": 0.44, "strich": 0.95, "strich-anlauf": 0.40,
          "marker": 0.52, "unterstrich": 0.30, "strahlen": 0.50, "pfeile": 0.58,
          "wortflut": 0.28, "karte": 0.58, "livekorrektur": 0.50, "kritzel": 0.18,
          "zeile": 0.20, "ebene": 0.24, "raster": 0.13, "stapel": 0.52}

# VERBUND-CUES. Die Referenz setzt bei wichtigen Bewegungen keinen einzelnen
# Effekt, sondern eine kleine Folge — im gelieferten Cue Sheet nachweisbar:
#
#     5.78s kurzer Whoosh   -> 6.30s Bass-/Body-Hit          (+520 ms)
#    18.92s heller Whoosh   -> 19.19s mittlerer Tap          (+270 ms)
#    19.97s Body-Impact     -> 20.23s Nachakzent             (+260 ms)
#    71.88s Final-Impact    -> 72.26s Endcard-Hit -> 72.65s Stinger
#
# Also: Whoosh kuendigt die Bewegung an, Body-Hit gibt ihr Masse am Zielpunkt,
# ein kleiner Nachakzent bestaetigt das Einrasten. Die Abstaende liegen bei
# rund einem Achtel (0.254 s bei 118 BPM) — hier ebenso, damit die Folge im
# Raster bleibt.
ACHTEL = 60.0 / 118.0 / 2
VERBUND = {"strich", "karte", "pfeile", "livekorrektur", "strahlen"}

# Der breite Uebergang, sparsam. Gemessen liegt das Seite/Mitte-Verhaeltnis
# der Referenz bei 0.14-0.16, und genau EIN Kapitelwechsel liegt bei 0.92.
# Mein erster Anlauf gab ihn allen zehn Aktwechseln — die Effektspur kam
# damit auf 0.330 statt 0.16, also durchgehend zu weit. Jetzt bekommen ihn
# nur die Aktwechsel, an denen auch der Hintergrund kippt: der haerteste
# sichtbare Bruch im Film.
import json as _json
_cfg = _json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
AKTWECHSEL = set()
_vor = None
for _s in _cfg["scenes"]:
    if _vor is not None and _s["act"] != _vor["act"] and _s.get("bg") != _vor.get("bg"):
        AKTWECHSEL.add(round(_s["start"], 3))
    _vor = _s

gezaehlt = {}
for c in daten["cues"]:
    art, s_, t, x = c["art"], c["staerke"], c["t"], c.get("x", 0.5)
    if art == "halt": continue
    if NUR and art not in NUR: continue
    g = PEGELN.get(art, 0.20) * s_ * PEGEL
    gezaehlt[art] = gezaehlt.get(art, 0) + 1
    # Nur die wirklich grossen Bewegungen bekommen die Dreierfolge. Mit den
    # Markern dazu waren es 34 Verbunde und der Film kam auf 1.29 Effekte je
    # Sekunde — die Referenz liegt bei 0.74 und lebt vom Leerraum.
    verbund = art in VERBUND

    if art in ("schnitt", "bgwechsel"):
        setzen(impact(s_, 0.90 if art == "schnitt" else 0.75), t, 0.5, g * LAUT["impact"],
               weite=0.5 if round(t, 3) in AKTWECHSEL else 0.0)
        if round(t, 3) in AKTWECHSEL:
            # Der breite Kapitel-Uebergang: heller und weiter als der Groove.
            setzen(whoosh(0.55, 0.9, +1), t - ACHTEL, 0.5, g * LAUT["whoosh"] * 1.3, weite=0.62)
            gezaehlt["uebergang"] = gezaehlt.get("uebergang", 0) + 1
    elif art == "stapel":
        setzen(impact(s_ * 0.8, 0.55), t, x, g * LAUT["impact"])
    elif art == "strich":
        setzen(whoosh(max(c["dauer"], 0.22), 1.0, +1), t, 0.5, g * LAUT["whoosh"])
        setzen(impact(1.0, 1.05), t + c["dauer"] * 0.75, 0.5, g * LAUT["impact"])
    elif art == "strich-anlauf":
        setzen(riser(max(c["dauer"], 0.30), s_), t, 0.5, g * LAUT["whoosh"], auf_cue=False)
    elif art in ("marker", "unterstrich", "strahlen", "pfeile", "wortflut"):
        # Faehrt links im Bild, klingt links: das Panorama folgt dem Strich.
        setzen(whoosh(max(c["dauer"], 0.16), s_, +1 if x >= 0.5 else -1), t, x,
               g * LAUT["whoosh"])
    elif art in ("zeile", "karte", "kritzel", "ebene", "livekorrektur"):
        setzen(click(s_), t, x, g * LAUT["click"])
        if art == "livekorrektur":
            setzen(riser(0.35, 0.6), t - 0.35, x, g * LAUT["whoosh"], auf_cue=False)
    elif art == "raster":
        setzen(tick(s_, 0.85 + 0.5*s_), t, x, g * LAUT["click"])

    # Der Verbund: Masse am Zielpunkt, dann der Nachakzent ein Achtel spaeter.
    if verbund:
        setzen(impact(s_ * 0.75, 0.60), t + max(c["dauer"], ACHTEL), x,
               g * LAUT["impact"] * 0.55)
        setzen(click(s_ * 0.5), t + max(c["dauer"], ACHTEL) + ACHTEL, x,
               g * LAUT["click"] * 0.45)
        gezaehlt["verbund"] = gezaehlt.get("verbund", 0) + 1

# Kein Normalisieren auf Vollaussteuerung: die Effektspur soll UNTER der
# Musik liegen und nur an den Akzenten darueber. mischen.sh stellt den Rest.
hoechster = np.max(np.abs(mix)) or 1.0
mix = mix / hoechster * 0.80
with wave.open(str(OUT / "sfx.wav"), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())

n = sum(gezaehlt.values())
print(f"out/sfx.wav · {n} Effekte auf {TOT:.1f}s = {n/TOT:.2f}/s · stereo")
for a, k in sorted(gezaehlt.items(), key=lambda x: -x[1]):
    print(f"   {k:4d}  {a}")

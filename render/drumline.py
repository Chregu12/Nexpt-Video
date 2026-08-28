#!/usr/bin/env python3
"""
Die Partitur mit echten Trommeln spielen.

    python3 partitur.py && python3 drumline.py   -> out/drumline.wav
    python3 drumline.py --trocken                ohne Raum
    python3 drumline.py --starr                  ohne menschliches Timing (Vergleich)

DREI QUELLEN, EINE SPUR

    out/analysis/partitur.json   WAS gespielt wird (render/partitur.py)
    out/analysis/groove.json     WIE es ein Mensch spielt (render/groove.py)
    out/_vcsl/                   WOMIT — echte Aufnahmen, CC0 (render/vcsl.py)

Das ist der Unterschied zur bisherigen Fassung: dort wurden Klaenge
synthetisiert und auf Bildereignisse gesetzt. Hier wird eine Partitur von
echten Trommeln gespielt, und das Spielgefuehl stammt aus 3408 Takten
echter Schlagzeugaufnahmen.

WAS „MENSCHLICH" HIER HEISST

Nicht Zufallswackeln. Gemessen am Groove MIDI Dataset spielen Schlagzeuger
systematisch VOR dem Raster, und zwar je Position verschieden:

    Snare    Position  0    4    8   12      -6.3  -9.5  -7.4 -10.6 ms
    Hi-Hat                                  -15.9 -25.4 -22.2 -18.0 ms

Und die Anschlagstaerke folgt der Position, nicht dem Zufall: die Snare
steht auf 4 und 12 bei 1.00, auf den ungeraden Positionen bei 0.32 — das
sind die Geisternoten. Beides kommt aus der Messung; je Anschlag kommt nur
noch die gemessene Streuung als Schwankung dazu.

Dazu Round Robin und Velocity Layers aus der Bibliothek: derselbe Schlag
klingt nie zweimal gleich, weil es verschiedene Aufnahmen sind.
"""
import json, os, shutil, subprocess, sys, wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
SR   = 48000
rng  = np.random.default_rng(23)
TROCKEN = "--trocken" in sys.argv
STARR   = "--starr" in sys.argv

for p, hinweis in ((OUT/"analysis"/"partitur.json", "python3 partitur.py"),
                   (OUT/"analysis"/"groove.json",   "python3 groove.py"),
                   (OUT/"_vcsl"/"katalog.json",     "python3 vcsl.py")):
    if not p.exists(): print(f"{p} fehlt — erst `{hinweis}`."); sys.exit(1)

part   = json.loads((OUT/"analysis"/"partitur.json").read_text(encoding="utf-8"))
groove = json.loads((OUT/"analysis"/"groove.json").read_text(encoding="utf-8"))["profil"]
kat    = json.loads((OUT/"_vcsl"/"katalog.json").read_text(encoding="utf-8"))["artikulationen"]

BPM  = part["bpm"]; S16 = 60.0/BPM/4
TOT  = part["takte"] * S16 * 16
N    = int((TOT + 2.0) * SR)
spur = np.zeros((N, 2))


def lies(rel):
    """Die Bibliothek mischt Formate: 52 Dateien sind 16 bit, 32 sind 24 bit,
    alle stereo mit 44100 Hz. Wer stur `<i2` liest, bekommt bei den 24ern
    Zahlensalat — und weil die Laenge dann nicht mehr durch zwei teilbar ist,
    faellt es beim Umformen auf, nicht beim Hoeren."""
    with wave.open(str(OUT/"_vcsl"/rel), "rb") as f:
        roh = f.readframes(f.getnframes())
        kan, breite, rate = f.getnchannels(), f.getsampwidth(), f.getframerate()
    if breite == 2:
        d = np.frombuffer(roh, "<i2").astype(np.float64) / 32768
    elif breite == 3:
        a = np.frombuffer(roh, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = a[:, 0] | (a[:, 1] << 8) | (a[:, 2] << 16)
        d = np.where(v & 0x800000, v - (1 << 24), v).astype(np.float64) / 8388608
    elif breite == 4:
        d = np.frombuffer(roh, "<i4").astype(np.float64) / 2147483648
    else:
        d = np.frombuffer(roh, "<i2").astype(np.float64) / 32768
    if kan == 2: d = d.reshape(-1, 2).mean(axis=1)
    if rate != SR:
        n = int(len(d) * SR / rate)
        d = np.interp(np.linspace(0, len(d)-1, n), np.arange(len(d)), d)
    return d

# ── Die Besetzung ─────────────────────────────────────────────────────────
# Links das Instrument der Partitur, rechts die Artikulation der Bibliothek.
# `gruppe` sagt, welches Groove-Profil gilt; `laut` ist der Grundpegel.
# Die Pegel sind nicht an der Referenz ausgerichtet, und das mit Absicht.
# Gemessen hat sie 78% ihrer Energie unter 250 Hz — aber aus einem Bass, nicht
# aus einer Trommel; eine grosse Trommel kommt dort gar nicht vor. Unsere
# Partitur ist eine Drumline MIT grosser Trommel, das ist ein anderes Stueck.
#
# Der erste Anlauf hatte sie auf 1.00, und damit lag die ganze Spur bei 0.86
# tief gegen 0.14 Mitte: die Stoecke, die Snare und die Toms waren rechnerisch
# nicht mehr vorhanden. Jetzt traegt die Trommel die Eins, ohne alles andere
# zuzudecken — das Tiefe fuers Bild liefert ohnehin die Effektspur.
BESETZUNG = {
 "trommel": ("BDrumNew_hit",           "trommel", 0.42),
 "snare":   ("RopeSnare_hi_sn_Main",   "snare",   0.86),
 "geist":   ("RopeSnare_low_ns_Main",  "snare",   0.38),
 "rim":     ("RopeSnare_sidestick_Main","rim",    0.62),
 "stock":   ("RopeSnare_stick_Main",   "hut",     0.78),
 "tomh":    ("TomH_HitM",              "tom",     0.58),
 "toml":    ("TomL_HitM",              "tom",     0.52),
 "wirbel":  ("TomL_RollM",             "snare",   0.62),
}
PROBEN, zaehler = {}, {}
for inst, (art, _, _) in BESETZUNG.items():
    v = kat.get(art)
    if not v: print(f"  Artikulation {art} fehlt"); continue
    PROBEN[inst] = [(x["stufe"], lies(x["datei"])) for x in v]

def anschlag(inst, staerke):
    """Waehlt Anschlagstaerke und Round Robin — echte Aufnahmen, keine
    Lautstaerkeregelung eines einzigen Samples. Eine leise Trommel klingt
    anders als eine leise gedrehte laute."""
    v = PROBEN.get(inst)
    if not v: return None
    stufen = sorted({s for s, _ in v})
    ziel = stufen[min(len(stufen)-1, int(np.clip(staerke, 0, 0.999) * len(stufen)))]
    kand = [w for s, w in v if s == ziel]
    i = zaehler.get((inst, ziel), 0); zaehler[(inst, ziel)] = i + 1
    return kand[i % len(kand)]

def gefuehl(gruppe, pos):
    """Versatz und Staerke, wie sie an dieser Position gemessen wurden."""
    z = groove.get(gruppe, [None]*16)[pos % 16]
    if z is None:
        nachbar = [x for x in groove.get(gruppe, []) if x]
        if not nachbar: return 0.0, 0.5, 0.0, 0.1
        z = nachbar[len(nachbar)//2]
    return (z["versatz_ms"]/1000, z["staerke"],
            z["streuung_ms"]/1000, z["staerke_streuung"])

def setzen(sig, t, gain, x=0.5):
    i = int(t*SR)
    if i < 0 or i >= N: return
    k = min(len(sig), N-i)
    if k <= 0: return
    l, r = np.cos(x*np.pi/2), np.sin(x*np.pi/2)
    spur[i:i+k, 0] += sig[:k]*gain*l
    spur[i:i+k, 1] += sig[:k]*gain*r

# Die Trommeln stehen im Bild, wie sie in einer Reihe stuenden.
PANORAMA = {"trommel": 0.50, "snare": 0.48, "geist": 0.48, "rim": 0.44,
            "stock": 0.58, "tomh": 0.62, "toml": 0.38, "wirbel": 0.40}

gesetzt = 0
for n in part["noten"]:
    inst = n["inst"]
    besetzung = BESETZUNG.get(inst)
    if not besetzung: continue
    _, gruppe, grund = besetzung
    versatz, staerke, streu_t, streu_v = gefuehl(gruppe, n["pos"])
    if STARR: versatz, streu_t, streu_v = 0.0, 0.0, 0.0

    # Bringt die Note ihre eigene Staerke und ihren eigenen Versatz mit, dann
    # stammt sie aus einer abgehoerten Vorlage (render/abhoeren.py) — und bei
    # einem Eins-zu-eins-Nachbau gilt DEREN Timing, nicht ein fremdes aus den
    # Groove-Daten. Sonst kommt beides aus der Messung echter Schlagzeuger.
    if "staerke" in n:
        v = float(np.clip(n["staerke"] * (1.10 if n.get("akzent") else 1.0), 0.04, 1.0))
        t = (n["takt"]*16 + n["pos"]) * S16 + (0.0 if STARR else n.get("versatz", 0.0))
        # Bei einem Nachbau traegt die Note die Dynamik der Vorlage schon in
        # sich. Zusaetzlich die eigenen Instrumentenpegel daraufzulegen wuerde
        # sie verbiegen: die Stoecke standen damit 5 dB unter der Snare und
        # verschwanden hinter ihr — von 256 Rasterfeldern der Vorlage waren
        # danach 61 nicht mehr zu hoeren. Deshalb hier ein flacher Pegel.
        grund = 0.62
    else:
        v = staerke * (1.20 if n.get("akzent") else 0.92)
        v = float(np.clip(v + rng.normal(0, streu_v*0.6), 0.05, 1.0))
        t = (n["takt"]*16 + n["pos"]) * S16 + versatz + rng.normal(0, streu_t*0.7)

    if n.get("flam"):
        # Vorschlag: leiser, rund 26 ms davor, andere Hand — also anderes RR.
        t -= 0.026; v *= 0.55

    sig = anschlag(inst, v)
    if sig is None: continue
    if "abkling" in n:
        # Auf die gemessene Laenge kuerzen, mit einer Ausblende ueber das
        # letzte Drittel — hart abgeschnitten knackt es.
        laenge = max(int(n["abkling"] * SR * 1.8), int(0.02*SR))
        if laenge < len(sig):
            sig = sig[:laenge].copy()
            aus = max(1, laenge//3)
            sig[-aus:] *= np.linspace(1, 0, aus) ** 1.4
    setzen(sig, t, grund * v, PANORAMA.get(inst, 0.5))
    gesetzt += 1

# ── Der Raum ──────────────────────────────────────────────────────────────
# Die Samples sind in einem Proberaum mit SM57 nah abgenommen. Ein wenig
# Raum bindet die Trommeln zusammen, viel davon nimmt der Referenz-
# handschrift die Trockenheit — deshalb sehr sparsam.
# Bei einem Nachbau bleibt der Raum weg. Die Vorlage ist knochentrocken, und
# gemessen kostet die Fahne genau das, was den Nachbau von ihr trennt: mit
# Raum waren 202 von 256 Rasterfeldern wiederzufinden, ohne 219. Die Fahne
# deckt die leisen Stockschlaege zu.
NACHBAU = any("staerke" in n for n in part["noten"])
if not TROCKEN and not NACHBAU:
    n_ = int(0.28*SR); t_ = np.arange(n_)/SR
    ir = rng.standard_normal(n_) * np.exp(-t_*13.0)
    X = np.fft.rfft(ir); f = np.fft.rfftfreq(n_, 1/SR)
    X[(f < 200) | (f > 6000)] = 0
    ir = np.fft.irfft(X, n_); ir[:int(0.005*SR)] = 0
    ir /= (np.max(np.abs(ir)) or 1)
    for k in range(2):
        spur[:, k] += np.convolve(spur[:, k], ir, mode="full")[:N] * 0.035

# ── Die fehlende Luft ─────────────────────────────────────────────────────
# Gemessen hat die Referenz 4% ihrer Energie zwischen 4 und 10 kHz und 16%
# darueber. Die Bibliothek hat dort fast nichts: die Rope-Snare kommt auf
# 0.003, die grosse Trommel auf 0.000 — sie sind mit SM57 im Proberaum nah
# abgenommen, und das ist ein dunkles Mikrofon. Nur der Stock traegt Hoehen
# (0.393). Deshalb steht er lauter, und darueber liegt ein sanftes Regal.
# Es hebt nur an, was da ist; erfinden kann es nichts.
X = np.fft.rfft(spur, axis=0); f = np.fft.rfftfreq(len(spur), 1/SR)[:, None]
X *= 1.0 + 2.6 / (1.0 + (6000/np.maximum(f, 1))**2)
spur = np.fft.irfft(X, len(spur), axis=0)

# ── Die Dynamik der Vorlage ───────────────────────────────────────────────
# Gemessen: die Vorlage hat 22.7 dB zwischen dem 20. und 99. Perzentil ihrer
# Huellkurve, der Nachbau kam auf 48.6 — mehr als das Doppelte. Echte
# Trommeln sind eben dynamischer als ein fertig gemasterter Loop.
#
# Die Folge war hoerbar und messbar: von 256 Rasterfeldern der Vorlage waren
# 59 im Nachbau nicht mehr zu finden, und es waren genau die leisen
# (Staerke-Median 0.13 gegen 0.86 aller Noten). Sie standen in der Partitur,
# sie wurden gespielt — sie gingen nur unter.
#
# Deshalb hier eine Huellkurven-Kompression auf das gemessene Mass. Kein
# Kompressor mit Attack und Release, sondern eine Kennlinie auf der
# Huellkurve: leise Stellen kommen hoch, laute bleiben.
if any("staerke" in n for n in part["noten"]):
    ZIEL_DB = 22.7
    for k in range(2):
        kanal = spur[:, k]
        F = max(1, int(0.010*SR))
        e = np.sqrt(np.convolve(kanal**2, np.ones(F)/F, mode="same")) + 1e-9
        laut = e[e > 1e-5]
        if len(laut) < 100: continue
        ist_db = 20*np.log10(np.percentile(laut, 99)/np.percentile(laut, 20))
        if ist_db <= ZIEL_DB: continue
        # Kennlinie: alles unter dem 99. Perzentil wird um den Faktor
        # ZIEL/IST in Dezibel zusammengezogen.
        bezug = np.percentile(laut, 99)
        db = 20*np.log10(e/bezug)
        neu = db * (ZIEL_DB/ist_db)
        spur[:, k] = kanal * 10**((neu - db)/20)

hoch = np.max(np.abs(spur)) or 1.0
spur = spur / hoch * 0.89
ziel = OUT / "drumline.wav"
with wave.open(str(ziel), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(spur, -1, 1)*32767).astype("<i2").tobytes())

print(f"{ziel} · {gesetzt} Anschlaege auf {TOT:.1f}s · {len(PROBEN)} Instrumente"
      f"{' · starr' if STARR else ''}{' · trocken' if TROCKEN else ''}")
for inst in BESETZUNG:
    if inst in PROBEN:
        st = len({s for s, _ in PROBEN[inst]})
        print(f"   {inst:<9}{BESETZUNG[inst][0]:<26}{st} Stufen, "
              f"{len(PROBEN[inst])} Aufnahmen")

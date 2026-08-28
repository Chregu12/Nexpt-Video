#!/usr/bin/env python3
"""
Die Referenz abhoeren und Note fuer Note aufschreiben.

    python3 abhoeren.py                  -> out/analysis/partitur.json
    python3 abhoeren.py <quelle.mp3>     andere Vorlage
    python3 abhoeren.py --bericht        nur zeigen, was gehoert wurde

WAS HIER PASSIERT UND WARUM

Die erste Partitur war eine eigene Komposition — bewusst KEINE
Rekonstruktion. Der Wunsch ist ein anderer: die Vorlage eins zu eins
nachbauen. Das geht, und es ist auch sauber, weil die Vorlage dem
Lizenznehmer selbst gehoert.

„Eins zu eins" heisst hier: jeder Anschlag der Vorlage wird gehoert,
eingeordnet und mit seiner gemessenen Position, Staerke und Abweichung
aufgeschrieben. Gespielt wird er dann von echten Trommeln
(render/drumline.py) statt von der Quelle. Gleiche Noten, anderes
Instrument.

WIE EINGEORDNET WIRD

Je Anschlag werden Klangschwerpunkt, Bandaufteilung und Abklingzeit
gemessen. Daraus ergibt sich die Familie:

    unter 2 kHz            Fell, tief    -> Snare oder Tom
    2 bis 4.5 kHz          Rand          -> Rim Click
    ueber 4.5 kHz, kurz    Stock         -> Stock auf Fell
    ueber 4.5 kHz, lang    Teppich       -> Snare mit Teppich

Die Grenzen stehen nicht willkuerlich: sie liegen in den Luecken der
gemessenen Verteilung, nicht mittendrin. `--bericht` zeigt sie.

WAS DIE VORLAGE NICHT HAT: eine tiefe Trommel. Gemessen liegt ihr tiefster
Schwerpunkt bei 988 Hz. Es wird deshalb auch keine geschrieben — eins zu
eins heisst auch, nichts dazuzuerfinden.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
SR   = 48000
ZIEL = OUT / "analysis" / "partitur.json"

quelle = next((a for a in sys.argv[1:] if not a.startswith("--")),
              str(OUT / "_musik" / "apple-style-118.mp3"))
if not Path(quelle).exists():
    print(f"{quelle} fehlt."); sys.exit(1)

roh = subprocess.run([FFMPEG, "-v", "quiet", "-i", quelle, "-ac", "1", "-ar", str(SR),
                      "-f", "f32le", "-"], capture_output=True).stdout
y = np.frombuffer(roh, "<f4").astype(np.float64)

# ── Raster der Vorlage ────────────────────────────────────────────────────
# Gemessen: 118.01 BPM, erster Downbeat 0.480 s, 16 Takte, danach Stille.
# Das Ziel ist das Filmraster mit exakt 118.00 — die Noten werden also auf
# das Raster des FILMS geschrieben, nicht auf das der Vorlage.
BPM_QUELLE, DB0 = 118.01, 0.480
BPM_ZIEL = 118.00
S16_Q = 60/BPM_QUELLE/4
S16_Z = 60/BPM_ZIEL/4
TAKTE_QUELLE = 16

# ── Anschlaege finden ─────────────────────────────────────────────────────
H, W = 64, 2048
n = 1 + (len(y) - W) // H
S = np.abs(np.fft.rfft(np.lib.stride_tricks.as_strided(
    y, (n, W), (y.strides[0]*H, y.strides[0])) * np.hanning(W), axis=1))
flux = np.maximum(0, np.diff(S, axis=0)).sum(1); fps = SR / H
f = (flux - flux.mean()) / (flux.std() or 1)
schwelle = np.percentile(f, 82)
roh_ons = []
for i in range(1, len(f)-1):
    if f[i] > schwelle and f[i] >= f[i-1] and f[i] > f[i+1]:
        t = i/fps
        if roh_ons and t - roh_ons[-1][0] < 0.045:
            if f[i] > roh_ons[-1][1]: roh_ons[-1] = (t, f[i])
        else: roh_ons.append((t, f[i]))

# ── Je Anschlag: Klangfarbe, Staerke, Abklingzeit ─────────────────────────
F = max(1, int(0.005*SR))
huell = np.sqrt(np.convolve(y**2, np.ones(F)/F, mode="same"))
schlaege = []
for k, (t, _) in enumerate(roh_ons):
    if t < DB0 - 0.02: continue
    i0 = int(t*SR)
    bis = int((roh_ons[k+1][0] if k+1 < len(roh_ons) else t+0.5)*SR)
    seg = y[i0:min(len(y), i0+int(0.05*SR))]
    if len(seg) < 600: continue
    Sp = np.abs(np.fft.rfft(seg*np.hanning(len(seg)))); fr = np.fft.rfftfreq(len(seg), 1/SR)
    zentrum = float((Sp*fr).sum()/(Sp.sum()+1e-12))
    B = [(20, 250), (250, 2000), (2000, 6000), (6000, 20000)]
    e = np.array([(Sp[(fr >= lo) & (fr < hi)]**2).sum() for lo, hi in B]); e /= (e.sum()+1e-16)
    sp = float(huell[i0:i0+int(0.02*SR)].max())
    h = huell[i0:min(len(huell), bis)]
    unter = np.where(h < sp*0.25)[0]
    ab = float(unter[0]/SR) if len(unter) else float(len(h)/SR)
    k16 = (t - DB0)/S16_Q
    pos = int(round(k16))
    if abs(k16 - pos) > 0.42: continue
    schlaege.append({"t": t, "zentrum": zentrum, "bander": e.tolist(), "spitze": sp,
                     "abkling": ab, "takt": (pos//16) % TAKTE_QUELLE, "pos": pos % 16,
                     "versatz": (k16 - pos)*S16_Q})

if not schlaege: print("nichts gehoert."); sys.exit(1)
# Staerke in Dezibel, nicht linear. Linear normiert bekamen 99 der 164
# Anschlaege den Wert 0.01 — ein einziger lauter Schlag hatte alles andere
# plattgedrueckt, und die Stockebene waere unhoerbar geblieben. Das Ohr hoert
# aber logarithmisch: von der leisesten bis zur lautesten Stelle sind es hier
# rund 40 dB, und die werden auf 0..1 gelegt.
db = np.array([20*np.log10(max(s["spitze"], 1e-6)) for s in schlaege])
oben, unten = np.percentile(db, 98), np.percentile(db, 4)
for s, d in zip(schlaege, db):
    s["staerke"] = float(np.clip((d - unten)/max(1e-6, oben - unten), 0.04, 1.0))

# ── Einordnen ─────────────────────────────────────────────────────────────
# Die Grenzen liegen in den Luecken der gemessenen Verteilung.
z = np.array([s["zentrum"] for s in schlaege])
def familie(s):
    c, ab = s["zentrum"], s["abkling"]
    if c < 2000:   return "fell"
    if c < 4500:   return "rand"
    return "teppich" if ab > 0.085 else "stock"
for s in schlaege: s["familie"] = familie(s)

# Vom Klang zum Instrument der Bibliothek. Die Vorlage hat keine tiefe
# Trommel, also wird auch keine geschrieben.
NACH_INST = {"fell": "snare", "rand": "rim", "stock": "stock", "teppich": "geist"}
noten = []
for s in schlaege:
    inst = NACH_INST[s["familie"]]
    # Laute Anschlaege der Teppich-Familie sind volle Snare-Schlaege, leise
    # sind Geisternoten — dieselbe Trommel, andere Haerte.
    if inst == "geist" and s["staerke"] > 0.62: inst = "snare"
    noten.append({"takt": s["takt"], "pos": s["pos"], "inst": inst,
                  "akzent": s["staerke"] > 0.62,
                  "staerke": round(s["staerke"], 3),
                  "versatz": round(s["versatz"], 4),
                  # Die Abklingzeit gehoert zum Nachbau wie die Position. Die
                  # Vorlage ist knochentrocken — ihre Stockschlaege sind nach
                  # 2 ms vorbei, die Raender nach 68 ms. Die Bibliothek liefert
                  # dagegen Aufnahmen von 1 bis 2.5 Sekunden. Wer die stehen
                  # laesst, deckt mit dem Ausklang den naechsten Schlag zu und
                  # bekommt etwas ganz anderes als die Vorlage.
                  "abkling": round(s["abkling"], 4),
                  "quelle_hz": int(s["zentrum"])})

if "--bericht" in sys.argv:
    print(f"{len(schlaege)} Anschlaege auf {TAKTE_QUELLE} Takten\n")
    print(f"{'Familie':<10}{'n':>4}{'Schwerpunkt':>14}{'Abkling':>10}{'Staerke':>9}  -> Instrument")
    for fam in ("fell", "rand", "stock", "teppich"):
        v = [s for s in schlaege if s["familie"] == fam]
        if not v: continue
        print(f"{fam:<10}{len(v):4d}{np.median([x['zentrum'] for x in v]):11.0f} Hz"
              f"{np.median([x['abkling'] for x in v])*1000:8.0f} ms"
              f"{np.median([x['staerke'] for x in v]):9.2f}  -> {NACH_INST[fam]}")
    print(f"\nVersatz zum Raster: Median {np.median([s['versatz'] for s in schlaege])*1000:+.1f} ms, "
          f"Streuung {np.std([s['versatz'] for s in schlaege])*1000:.1f} ms")
    print("\nBelegung je Sechzehntelposition:")
    for takt in range(TAKTE_QUELLE):
        zeile = ["."]*16
        for s in schlaege:
            if s["takt"] == takt:
                zeile[s["pos"]] = {"fell": "S", "rand": "r", "stock": "x",
                                   "teppich": "g"}[s["familie"]]
        print(f"  {takt+1:3d}  {''.join(zeile)}")
    sys.exit(0)

# ── Auf die Filmlaenge legen ──────────────────────────────────────────────
# Der Film ist 68 Takte, die Vorlage 16. Sie laeuft also 4x durch und bricht
# im 5. Durchlauf ab — genauso, wie sie es als Loop tut. Nur die drei
# Halte-Beats bleiben leer: dort will der Film Stille.
TAKTE_FILM = 68
STILL = {27, 28, 58}
alle = []
for takt in range(TAKTE_FILM):
    if takt in STILL: continue
    for n_ in noten:
        if n_["takt"] != takt % TAKTE_QUELLE: continue
        m = dict(n_); m["takt"] = takt
        alle.append(m)
alle.sort(key=lambda n: (n["takt"], n["pos"]))

ZIEL.parent.mkdir(parents=True, exist_ok=True)
ZIEL.write_text(json.dumps(
    {"bpm": BPM_ZIEL, "takte": TAKTE_FILM, "sechzehntel": round(S16_Z, 6),
     "herkunft": {"quelle": Path(quelle).name, "bpm": BPM_QUELLE, "downbeat": DB0,
                  "takte": TAKTE_QUELLE, "anschlaege": len(schlaege)},
     "hinweis": ("Abgehoert, nicht komponiert. `staerke` und `versatz` stammen aus "
                 "der Vorlage, nicht aus den Groove-Daten — bei einem Eins-zu-eins-"
                 "Nachbau spielt ihr eigenes Timing, nicht ein fremdes."),
     "noten": alle}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

von = {}
for n_ in alle: von[n_["inst"]] = von.get(n_["inst"], 0) + 1
print(f"out/analysis/partitur.json · {len(schlaege)} Anschlaege gehoert, "
      f"auf {TAKTE_FILM} Takte gelegt = {len(alle)} Noten")
for i, k in sorted(von.items(), key=lambda x: -x[1]): print(f"   {k:4d}  {i}")

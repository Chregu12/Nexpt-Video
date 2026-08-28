#!/usr/bin/env python3
"""
Menschliches Spielgefuehl aus echten Schlagzeugaufnahmen ziehen.

    python3 groove.py            -> out/analysis/groove.json
    python3 groove.py --laden    erst das Datenset holen (3.3 MB)

WAS HIER PASSIERT

Das Groove MIDI Dataset (Magenta) enthaelt 1150 Aufnahmen echter
Schlagzeuger auf E-Drums, mit Anschlagstaerke und exakter Zeit. Daraus wird
nicht Musik entnommen, sondern das GEFUEHL: wie weit ein Mensch je
Sechzehntelposition vom Raster abweicht und wie stark er dort anschlaegt.

Der Unterschied zum ueblichen „Humanize" ist gross. Zufaelliges Wackeln
verteilt sich symmetrisch um Null. Ein Schlagzeuger tut das nicht — er
spielt die Eins anders als die Vier, Geisternoten anders als Akzente, und
seine Abweichung hat je Position ein eigenes Vorzeichen und eine eigene
Streuung. Genau das steht danach in out/analysis/groove.json.

AUSGEWAEHLT werden nur Aufnahmen im 4/4 zwischen 108 und 128 BPM — das
Tempofenster des Films — und darin die Stile, die einer trockenen
Werbe-Perkussion am naechsten kommen. Jazz und Latin bleiben draussen: ihr
Swing wuerde das Raster verschieben, auf dem der Film sitzt.

DIE MIDI-NOTEN sind General-MIDI-Schlagzeug:
    36 Bass Drum · 38 Snare · 37 Sidestick · 40 Snare Rand
    41/43/45/47/48/50 Toms · 42/44/46 HiHat · 49/51/57/59 Becken
"""
import json, os, subprocess, sys, zipfile
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
OUT  = ROOT.parent / "out"
DATEN = OUT / "_groove" / "groove"
ZIEL  = OUT / "analysis" / "groove.json"
URL   = "https://storage.googleapis.com/magentadata/datasets/groove/groove-v1.0.0-midionly.zip"

if "--laden" in sys.argv or not DATEN.exists():
    (OUT / "_groove").mkdir(parents=True, exist_ok=True)
    zp = OUT / "_groove" / "groove-midi.zip"
    if not DATEN.exists():
        print(f"hole {URL} …")
        subprocess.run(["curl", "-sSL", "-o", str(zp), URL], check=True)
        with zipfile.ZipFile(zp) as z: z.extractall(OUT / "_groove")
        zp.unlink()
        print("geladen.")

try:
    import pretty_midi
except ImportError:
    print("pretty_midi fehlt:  pip install pretty_midi"); sys.exit(1)

import csv
rows = list(csv.DictReader(open(DATEN / "info.csv")))

# Kein Jazz, kein Latin: deren Swing verschoebe das Raster, auf dem der Film
# sitzt. Gesucht ist gerade gespielte, trockene Perkussion.
STILE = ("rock", "funk", "punk", "pop", "soul", "hiphop", "country", "gospel")
gewaehlt = [r for r in rows
            if r.get("bpm") and 108 <= float(r["bpm"]) <= 128
            and r.get("time_signature") == "4-4"
            and r["style"].split("/")[0] in STILE]
print(f"{len(gewaehlt)} von {len(rows)} Aufnahmen: 4/4, 108-128 BPM, "
      f"{'/'.join(STILE[:4])}…")

GRUPPE = {36: "trommel", 38: "snare", 40: "snare", 37: "rim",
          41: "tom", 43: "tom", 45: "tom", 47: "tom", 48: "tom", 50: "tom",
          42: "hut", 44: "hut", 46: "hut"}

# Je Sechzehntelposition im Takt (0..15) und je Gruppe: Abweichung und Staerke
abw = defaultdict(list)      # (gruppe, pos) -> Abweichungen in Sechzehnteln
vel = defaultdict(list)      # (gruppe, pos) -> Anschlagstaerken 0..1
haeuf = defaultdict(int)     # (gruppe, pos) -> wie oft ueberhaupt gespielt
takte = 0

for r in gewaehlt:
    p = DATEN / r["midi_filename"]
    if not p.exists(): continue
    try: pm = pretty_midi.PrettyMIDI(str(p))
    except Exception: continue
    bpm = float(r["bpm"]); s16 = 60.0 / bpm / 4
    for inst in pm.instruments:
        if not inst.is_drum: continue
        for n in inst.notes:
            g = GRUPPE.get(n.pitch)
            if not g: continue
            k = n.start / s16
            pos = int(round(k)) % 16
            d = k - round(k)
            if abs(d) > 0.5: continue
            abw[(g, pos)].append(d)
            vel[(g, pos)].append(n.velocity / 127)
            haeuf[(g, pos)] += 1
    takte += pm.get_end_time() / (60.0 / bpm * 4)

profil = {}
for g in ("trommel", "snare", "rim", "tom", "hut"):
    zeilen = []
    for pos in range(16):
        a = abw.get((g, pos), []); v = vel.get((g, pos), [])
        if len(a) < 30:
            zeilen.append(None); continue
        zeilen.append({
            "n": len(a),
            "versatz_ms": round(float(np.median(a)) * (60/118/4) * 1000, 2),
            "streuung_ms": round(float(np.std(a)) * (60/118/4) * 1000, 2),
            "staerke": round(float(np.median(v)), 3),
            "staerke_streuung": round(float(np.std(v)), 3),
            "je_takt": round(haeuf[(g, pos)] / max(1, takte), 3),
        })
    profil[g] = zeilen

ZIEL.parent.mkdir(parents=True, exist_ok=True)
ZIEL.write_text(json.dumps(
    {"quelle": "Groove MIDI Dataset (Magenta), Lizenz CC BY 4.0",
     "aufnahmen": len(gewaehlt), "takte": round(takte),
     "hinweis": ("Je Instrumentengruppe und Sechzehntelposition: der mediane "
                 "Versatz zum Raster in Millisekunden bei 118 BPM, seine Streuung, "
                 "die mediane Anschlagstaerke 0..1 und wie oft die Position je "
                 "Takt ueberhaupt gespielt wird. `null` heisst: zu wenige Daten."),
     "profil": profil}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

print(f"{takte:.0f} Takte ausgewertet\n")
print(f"{'':10}" + "".join(f"{p:>7}" for p in range(16)))
for g in ("trommel", "snare", "rim", "hut"):
    z = profil[g]
    print(f"{g:<10}" + "".join(f"{(x['versatz_ms'] if x else 0):>+7.1f}" for x in z) + "  ms Versatz")
    print(f"{'':10}" + "".join(f"{(x['staerke'] if x else 0):>7.2f}" for x in z) + "  Staerke")
print(f"\n{ZIEL} geschrieben")

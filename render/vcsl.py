#!/usr/bin/env python3
"""
Echte Trommeln holen: Versilian Community Sample Library (CC0).

    python3 vcsl.py            -> out/_vcsl/  (rund 73 MB)
    python3 vcsl.py --bericht  zeigen, was da ist

WARUM DIESE BIBLIOTHEK

Das Sounddesign kam bis hierher aus den Schlaegen des eigenen Musikloops.
Die sind echt und passen zur Musik, aber der Loop hat gemessen keinen Ton
unter 988 Hz — keine tiefe Trommel. Unter den Impacts lag deshalb ein Sinus
als Fundament, und das war die letzte Synthese in der ganzen Spur.

Die VCSL schliesst genau diese Luecke:

    Bass Drum           157-523 Hz Schwerpunkt, 4 Anschlagstaerken x 2 RR
    Snare, Rope Tension  eine echte Marschtrommel, 8 Varianten je Artikulation
    Sidestick / Stick    3663 / 4027 Hz — echte Rim Clicks
    Tom hoch und tief    mit Anschlagstaerken

LIZENZ: CC0 1.0 Universal, also gemeinfrei. Kommerziell nutzbar, ohne
Namensnennung, ohne Weitergabepflicht. Aufgenommen von Versilian Studios in
einem Proberaum mit SM57-Mikrofonen.

Die Dateien liegen NICHT im Repo (73 MB, und sie sind mit einem Befehl
wieder da). `out/_vcsl/` steht in .gitignore.

DIE BENENNUNG der Quelle traegt alles, was ein Sampler braucht:

    RopeSnare_hi_sn_Main_vl3_rr2.wav
                        ^^^^ ^^^^
                        |    Round Robin: dieselbe Stelle, anderer Schlag
                        Velocity Layer: vl1 leise bis vl4 laut

Das ist genau die Humanisierung, die eine Vorgabe verlangt hat — nicht
zufaelliges Wackeln an einem einzigen Sample, sondern verschiedene echte
Aufnahmen je Anschlagstaerke und im Wechsel.
"""
import json, os, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
ZIEL = OUT / "_vcsl"
REPO = "https://github.com/sgossner/VCSL.git"

# Nur was gebraucht wird — die ganze Bibliothek ist ein Vielfaches davon.
ORDNER = [
    "Membranophones/Struck Membranophones/Snare Drum, Rope Tension",
    "Membranophones/Struck Membranophones/Bass Drum 1",
    "Membranophones/Struck Membranophones/Tom 1",
    "Membranophones/Struck Membranophones/Tom 2",
]

def lauf(*a, **kw):
    return subprocess.run(a, check=True, capture_output=True, text=True, **kw)

if "--bericht" not in sys.argv:
    if (ZIEL / ".git").exists():
        print(f"{ZIEL} ist schon da.")
    else:
        ZIEL.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(ZIEL, ignore_errors=True)
        print(f"hole {REPO} …")
        lauf("git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
             REPO, str(ZIEL))
        lauf("git", "sparse-checkout", "init", "--cone", cwd=ZIEL)
        lauf("git", "sparse-checkout", "set", *ORDNER, cwd=ZIEL)
        lauf("git", "checkout", "master", cwd=ZIEL)
        print("geladen.")

if not ZIEL.exists():
    print("out/_vcsl/ fehlt."); sys.exit(1)

# ── Katalog schreiben ─────────────────────────────────────────────────────
# Je Artikulation die Dateien nach Anschlagstaerke (vl) und Round Robin (rr).
# Die Bass Drum benennt ihre Staerken als v2/v3/v5/v7 statt vl1..vl4 — beide
# Formen werden gelesen und auf 1..n normiert.
kat = {}
for p in sorted(ZIEL.rglob("*.wav")):
    n = p.name
    m = re.search(r"_(?:vl|v)(\d+)_rr(\d+)", n)
    if m:
        art = n[:m.start()]; vl, rr = int(m.group(1)), int(m.group(2))
    else:
        art = re.sub(r"\.wav$", "", n); vl, rr = 1, 1
    kat.setdefault(art, []).append({"datei": str(p.relative_to(ZIEL)), "vl": vl, "rr": rr})

for art, v in kat.items():
    stufen = sorted({x["vl"] for x in v})
    for x in v: x["stufe"] = stufen.index(x["vl"]) + 1
    v.sort(key=lambda x: (x["stufe"], x["rr"]))

(ZIEL / "katalog.json").write_text(json.dumps(
    {"quelle": REPO, "lizenz": "CC0 1.0 Universal",
     "hinweis": ("Echte Aufnahmen, gemeinfrei. `stufe` ist die auf 1..n normierte "
                 "Anschlagstaerke, `rr` der Round Robin."),
     "artikulationen": kat}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

print(f"\n{len(kat)} Artikulationen, {sum(len(v) for v in kat.values())} Dateien")
print(f"{'Artikulation':<34}{'Stufen':>8}{'RR':>5}")
for art, v in sorted(kat.items()):
    if len(v) < 2: continue
    print(f"{art[:33]:<34}{len({x['stufe'] for x in v}):8d}{len({x['rr'] for x in v}):5d}")
print(f"\nout/_vcsl/katalog.json geschrieben")

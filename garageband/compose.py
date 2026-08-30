#!/usr/bin/env python3
"""Aus unseren Messdaten eine Partitur im Score-Spec der Bridge schreiben.

    python3 garageband/compose.py                 -> garageband/scores/nexpt-work-68.json
    python3 garageband/compose.py --midi          zusaetzlich MIDI ueber die Bridge
    python3 garageband/compose.py --bericht       nur die Takttabelle zeigen

WARUM DIESER UMWEG UEBERHAUPT

Dreimal wurde hier Perkussion selbst erzeugt, dreimal klang sie nach Roboter —
Sinus plus gefiltertes Rauschen ist eben ein Roboter, egal wie gut die Noten
sitzen. Die Grenze lag nie bei der Komposition, sondern beim Klangerzeuger.

GarageBand hat echte, aufgenommene Drum Kits. Die Bridge kann GarageBand
fernsteuern. Damit verschiebt sich die Aufgabe an die Stelle, an der wir
tatsaechlich etwas koennen: WAS gespielt wird, mit welcher Anschlagstaerke und
wie weit neben dem Raster. Der Klang kommt aus echten Aufnahmen — von uns
kommt die Partitur.

WAS HIER LAEUFT UND WAS NICHT

Dieses Skript ist reines Python und laeuft ueberall. Es schreibt eine
JSON-Partitur; MIDI daraus erzeugt die Bridge, ebenfalls plattformunabhaengig.

Die letzten Schritte — GarageBand oeffnen, ein Kit waehlen, WAV exportieren —
gehen NUR auf einem Mac mit installiertem GarageBand. Die Bridge steuert die
echte App ueber AppleScript und die Bedienungshilfen; unter Linux gibt es
nichts, was sie fernsteuern koennte. Siehe garageband/README.md.

WORAUS DIE PARTITUR ENTSTEHT — alles gemessen, nichts geraten

  render/timing.json          68 Takte bei 118.00 BPM, die Szenengrenzen
  render/bogen.py  BOGEN      25 Abschnitte mit Energie 0..1, jede Grenze
                              an einer Szene abgelesen
  out/analysis/groove.json    Groove MIDI Dataset (Magenta, CC BY 4.0):
                              220 Aufnahmen, 3408 Takte echter Schlagzeuger.
                              Je Instrument und Sechzehntel der mediane
                              Versatz zum Raster in ms, seine Streuung, die
                              mediane Anschlagstaerke und wie oft die
                              Position ueberhaupt gespielt wird.

Der Versatz ist der Punkt, an dem eine Maschine sich verraet. Gemessen spielt
ein Mensch die Hi-Hat auf der Eins 15.9 ms VOR dem Raster und auf der Drei
22.2 ms davor — nicht zufaellig verwackelt, sondern systematisch vorne. Genau
diese Tabelle wird hier angewandt, statt Rauschen auf die Zeiten zu addieren.
"""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "render"))
from bogen import BOGEN                                    # noqa: E402

BPM = 118.0
BRIDGE = ROOT / "tools" / "garageband-llm-bridge" / "garageband_cli.py"
ZIEL = Path(__file__).resolve().parent / "scores" / "nexpt-work-68.json"

groove = json.loads((ROOT / "out" / "analysis" / "groove.json").read_text(encoding="utf-8"))
PROFIL = groove["profil"]
cfg = json.loads((ROOT / "render" / "timing.json").read_text(encoding="utf-8"))
TOT = max(s["start"] + s["dur"] for s in cfg["scenes"])
TAKTE = int(round(TOT / (240.0 / BPM)))


def energie(takt):
    """Energie dieses Takts aus dem Bogen — dieselbe Tabelle, die auch die
    Lautstaerke des Original-Loops formt. So erzaehlen beide dasselbe."""
    e = BOGEN[0][1]
    for ab, wert, _ in BOGEN:
        if takt >= ab: e = wert
        else: break
    return e


def abschnitt(takt):
    name = BOGEN[0][2]
    for ab, _, n in BOGEN:
        if takt >= ab: name = n
        else: break
    return name


def versatz_beats(gruppe, pos):
    """Menschlicher Versatz dieser Position, in Vierteln statt Millisekunden.
    Fehlt die Position im Profil (zu wenige Daten), bleibt sie auf dem Raster —
    lieber gerade als erfunden."""
    eintrag = PROFIL.get(gruppe, [None]*16)[pos]
    if not eintrag: return 0.0
    return eintrag["versatz_ms"] / 1000.0 * (BPM / 60.0)


# Die mediane Staerke JE GRUPPE. Sie dient als Bezugspunkt, damit die Messung
# die Dynamik innerhalb einer Gruppe bestimmt und nicht das Verhaeltnis
# zwischen den Gruppen: sonst setzt jede Gruppe ihren eigenen Pegel, und die
# Bassdrum landet 43 Punkte unter der Snare, obwohl sie in der Vorlage
# gemessen 78% der Energie traegt.
BEZUG = {g: (sorted(x["staerke"] for x in v if x)[len([x for x in v if x])//2]
             if any(v) else 0.5)
         for g, v in PROFIL.items()}


def staerke(gruppe, pos, e, grund):
    """Anschlagstaerke 1..127. `grund` setzt den Pegel der Gruppe, die Messung
    die Abstufung innerhalb der Gruppe, die Energie den Bogen darueber."""
    eintrag = PROFIL.get(gruppe, [None]*16)[pos]
    rel = (eintrag["staerke"] / BEZUG.get(gruppe, 0.5)) if eintrag else 1.0
    rel = min(1.20, max(0.55, rel))
    v = grund * rel * (0.52 + 0.48 * e)
    return int(max(1, min(127, round(v * 127))))


def note(drum, takt, pos, gruppe, e, grund):
    start = takt * 4.0 + pos * 0.25 + versatz_beats(gruppe, pos)
    return {"drum": drum, "start": round(max(0.0, start), 5), "duration": 0.25,
            "velocity": staerke(gruppe, pos, e, grund)}


# Die Kickmuster wechseln je Takt, damit kein Loop entsteht. Die Position 0
# ist immer dabei — der Bass auf der Eins traegt in der Vorlage gemessen 78%
# der Energie.
KICK = [(0, 10), (0, 7, 12), (0, 6, 11), (0, 9, 14),
        (0, 5, 10, 13), (0, 7, 10), (0, 3, 8, 12), (0, 6, 12, 15)]

noten, zeilen = [], []
for takt in range(TAKTE):
    e = energie(takt)
    phrase = takt % 4
    gespielt = 0

    if e >= 0.05:
        muster = KICK[(takt + takt // 4) % len(KICK)]
        if e < 0.50: muster = muster[:2]
        for pos in muster:
            noten.append(note("kick", takt, pos, "trommel", e, 0.80)); gespielt += 1

    if e >= 0.30:
        for pos in ((4, 12) if e >= 0.45 else ((12,) if phrase % 2 else (4,))):
            noten.append(note("snare", takt, pos, "snare", e, 0.74)); gespielt += 1

    if e >= 0.35:
        schritt = 2 if e < 0.72 else 1
        for pos in range(0, 16, schritt):
            noten.append(note("closed_hat", takt, pos, "hut", e, 0.38)); gespielt += 1

    # Rim nur sparsam — im gemessenen Profil steht er auf 6 von 16 Positionen
    # und dort mit 0.01 bis 0.02 Anschlaegen je Takt. Das ist ein Farbtupfer,
    # kein Element; wer ihn durchlaufen laesst, hat das Profil nicht gelesen.
    if e >= 0.55 and phrase in (1, 3):
        for pos in (6, 14):
            if PROFIL["rim"][pos]:
                noten.append(note("rim", takt, pos, "rim", e, 0.44)); gespielt += 1

    # Tom-Fill am Ende der Vierergruppe, nur wenn ohnehin viel los ist.
    if e >= 0.75 and phrase == 3:
        for pos, drum in ((12, "high_tom"), (13, "mid_tom"), (14, "low_tom"), (15, "low_tom")):
            noten.append(note(drum, takt, pos, "tom", e, 0.66)); gespielt += 1

    # Crash auf die Eins, wenn ein Abschnitt neu beginnt und lauter wird.
    if takt > 0 and abschnitt(takt) != abschnitt(takt-1) and e > energie(takt-1) + 0.15:
        noten.append(note("crash", takt, 0, "trommel", e, 0.62)); gespielt += 1

    zeilen.append((takt, e, gespielt, abschnitt(takt)))

noten.sort(key=lambda n: n["start"])

if "--bericht" in sys.argv:
    print(f"{TAKTE} Takte bei {BPM} BPM · {len(noten)} Anschlaege")
    print(f"{'Takt':>5}{'Zeit':>9}{'Energie':>9}{'Noten':>7}  Abschnitt")
    letzter = None
    for takt, e, n, name in zeilen:
        marke = "  " if name == letzter else "> "
        print(f"{takt:5d}{takt*240/BPM:8.2f}s{e:9.2f}{n:7d}  {marke}{name}")
        letzter = name
    sys.exit(0)

spec = {
    "format": "garageband_score_spec_v1",
    "title": "NEXPT Work — Keynote 68 Takte",
    "bpm": int(BPM),
    "time_signature": "4/4",
    "parts": [{
        "name": "NEXPT Percussion",
        "is_percussion": True,
        "channel": 10,
        "mix": {"volume": "82%", "pan": "center", "reverb": 0.12},
        "notes": noten,
    }],
}
ZIEL.parent.mkdir(parents=True, exist_ok=True)
ZIEL.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

v = sorted(n["velocity"] for n in noten)
print(f"{ZIEL.relative_to(ROOT)} — {TAKTE} Takte, {len(noten)} Anschlaege")
print(f"  Anschlagstaerke {v[0]} bis {v[-1]}, Median {v[len(v)//2]}")
print(f"  Energie {min(z[1] for z in zeilen):.2f} bis {max(z[1] for z in zeilen):.2f}")

if not BRIDGE.exists():
    print(f"  Hinweis: {BRIDGE.relative_to(ROOT)} fehlt — "
          f"`git submodule update --init` holt die Bridge.")
    sys.exit(0)

pr = subprocess.run([sys.executable, str(BRIDGE), "--pretty", "score-spec-validate",
                     "--file", str(ZIEL)], capture_output=True, text=True)
ok = '"ok": true' in pr.stdout
print(f"  Bridge-Pruefung: {'bestanden' if ok else 'FEHLGESCHLAGEN'}")
if not ok:
    print(pr.stdout[-800:] or pr.stderr[-800:]); sys.exit(1)

if "--midi" in sys.argv:
    mid = ZIEL.with_suffix(".mid")
    subprocess.run([sys.executable, str(BRIDGE), "score-spec-to-midi",
                    "--file", str(ZIEL), "--output", str(mid)],
                   capture_output=True, text=True)
    if mid.exists():
        print(f"  {mid.relative_to(ROOT)} — {mid.stat().st_size} Bytes")

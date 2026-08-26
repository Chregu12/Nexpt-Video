#!/usr/bin/env python3
"""
Prüft timing.json auf die Fehler, die man im Standbild nicht sieht.

    python3 pruefen.py            nur melden
    python3 pruefen.py --fix      Löcher schliessen und Szenenanfänge ziehen

Drei Prüfungen:
  1. LEERE FRAMES  — eine Zeile verschwindet, bevor die nächste kommt. Im Lauf
     ein sichtbarer Aussetzer, im Standbild unsichtbar.
  2. STILLSTAND    — Löcher ohne jedes Ereignis. Fünf Beats duerfen still stehen,
     dort ist die Stille die Pointe; alle anderen nicht.
  3. TEMPO         — Ereignisse je Sekunde gegen den Referenzfilm.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG  = ROOT / "timing.json"
cfg  = json.loads(CFG.read_text(encoding="utf-8"))
FPS  = cfg["meta"]["fps"]
FIX  = "--fix" in sys.argv

# Diese Beats leben davon, dass nichts passiert.
HALT = {"05_aside", "11c_trick", "12_nein", "23_ui", "03_moment"}

def empty_frames():
    bad = []
    for s in cfg["scenes"]:
        for f in range(int(s["dur"] * FPS)):
            t = f / FPS
            TRAEGT = {"text", "role", "card", "pile", "levels", "broll",
                      "grid", "markerText", "url", "checkbox", "wordFlood", "liveEdit"}
            sicht = [l for l in s.get("layers", [])
                     if t >= l.get("t", 0) and (l.get("out") is None or t < l["out"])]
            # Unterstrich, Doodle, Strahlenkranz allein sind kein Inhalt.
            if not [l for l in sicht if l["type"] in TRAEGT]:
                bad.append((s["id"], round(t, 2)))
    return bad

def close_gaps():
    fixed = 0
    for s in cfg["scenes"]:
        L = s.get("layers", [])
        if not L: continue
        first = min(l.get("t", 0) for l in L)
        if first > 0:
            for l in L:
                if abs(l.get("t", 0) - first) < 1e-9: l["t"] = 0.0; fixed += 1
        for l in L:
            if l.get("out") is None: continue
            if any(x is not l and x.get("t", 0) <= l["out"] - 1e-9
                   and (x.get("out") is None or x["out"] > l["out"] + 1e-9) for x in L):
                continue
            later = [x.get("t", 0) for x in L if x is not l and x.get("t", 0) > l["out"] - 1e-9]
            if later: l["out"] = round(min(later), 3); fixed += 1
            elif l["out"] < s["dur"] - 1e-9: l["out"] = None; fixed += 1
    return fixed

def events(s):
    """Alle sichtbaren Ereignisse einer Szene — inklusive der einzelnen
    Wörter eines Wort-für-Wort-Aufbaus, die sonst unterschlagen würden."""
    ev = [f["t"] for f in s.get("bgFlips", [])]
    if s.get("bgFlip"): ev.append(s["bgFlip"]["t"])
    for l in s.get("layers", []):
        t0 = l.get("t", 0); ev.append(t0)
        if l["type"] == "text" and l.get("mode") == "words":
            step = l.get("step", 0.19); n = len(l["text"].split())
            ev += [t0 + k*step for k in range(1, n)]
        elif l["type"] == "wordFlood":
            ev += [t0 + k*(l["dur"]/len(l["words"])) for k in range(1, len(l["words"]))]
        elif l["type"] == "levels":
            ev += [t0 + k*l["step"] for k in range(1, len(l["items"]))]
        elif l["type"] == "pile":
            ev += [t0 + k*l.get("step", .42) for k in range(1, len(l["files"]))]
        elif l["type"] == "role":
            pass
    return sorted(e for e in ev if e <= s["dur"] + 1e-6)

def stillstand():
    out = []
    for s in cfg["scenes"]:
        if s["id"] in HALT: continue
        ev = events(s)
        if not ev: continue
        gap = max([b - a for a, b in zip(ev, ev[1:])] + [s["dur"] - ev[-1]])
        if gap > 1.6: out.append((s["id"], round(gap, 1)))
    return out

print("1 · LEERE FRAMES")
bad = empty_frames()
if bad and FIX:
    n = close_gaps()
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    bad = empty_frames()
    print(f"    {n} Löcher geschlossen · verbleibend {len(bad)}")
elif bad:
    ids = sorted({b[0] for b in bad})
    print(f"    ⚠ {len(bad)} leere Frames in {len(ids)} Szenen: {', '.join(ids[:6])}"
          f"{' …' if len(ids) > 6 else ''}   → --fix")
else:
    print("    ✓ keine")

print("\n2 · STILLSTAND")
st = stillstand()
if st:
    print(f"    ⚠ {len(st)} Szene(n) mit Loch > 1.6 s:")
    for sid, g in st: print(f"        {sid:<18} {g}s")
    print("      Marker, Unterstrich oder Doodle setzen — oder in HALT aufnehmen,")
    print("      falls die Stille dort Absicht ist.")
else:
    print("    ✓ keine (ausser den fünf gewollten Halten)")

print("\n3 · TEMPO")
tot = max(s["start"] + s["dur"] for s in cfg["scenes"])
ev  = sum(len(events(s)) for s in cfg["scenes"])
cuts = sum(1 + len(s.get("bgFlips", [])) for s in cfg["scenes"])
print(f"    Länge {int(tot//60)}:{tot%60:04.1f} · {ev} Ereignisse = alle {tot/ev:.2f}s"
      f"   (Referenz 0.46s)")
print(f"    {cuts} harte Schnitte = alle {tot/cuts:.2f}s   (Referenz 2.52s)")
print("\n    Massgeblich ist der gerenderte Film:")
print('    ffmpeg -i out/NEXPT-Keynote-ANIMATIC.mp4 -filter:v "select=\'gt(scene,0.02)\',showinfo" \\')
print("      -f null - 2>&1 | grep -c pts_time")

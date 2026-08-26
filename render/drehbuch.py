#!/usr/bin/env python3
"""
Erzeugt den Drehbuch-Abschnitt des Konzepts aus timing.json.

Damit koennen Dokument und Film nicht auseinanderlaufen: die Zeiten im
Drehbuch sind immer die, die auch gerendert werden.

    python3 drehbuch.py            -> schreibt Abschnitt 4 in KEYNOTE-FILM-KONZEPT.md
    python3 drehbuch.py --print    -> nur ausgeben
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
cfg  = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
mm   = lambda x: f"{int(x//60)}:{x%60:04.1f}"

BG = {"light": "HELL", "dark": "SCHWARZ", "accent": "AKZENT"}
out, act = [], None
for s in cfg["scenes"]:
    a = re.sub(r"^\d+\s+", "", s["act"])
    if a != act:
        act = a
        out.append(f"\n━━━ {act.upper()} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    vo = (s.get("vo") or "").strip()
    flips = "".join(f" → {BG[f['to']]}" for f in s.get("bgFlips", []))
    out.append(f"{mm(s['start']):>7}  [{BG[s['bg']]}{flips}]  ({s['dur']:.1f}s · {s['id']})")
    if vo and not vo.startswith("("):
        for line in vo.split(". "):
            line = line.strip().rstrip(".")
            if line: out.append(f"         {line}.")
    elif vo:
        out.append(f"         {vo}")
    # sichtbare Marker-Ereignisse mit auflisten — sie tragen die halbe Aussage
    for l in s.get("layers", []):
        if l["type"] == "markerText":
            out.append(f"         └ MARKER  {l['text']}   (+{l['t']:.1f}s)")
        elif l["type"] in ("grid", "strike", "pile", "card", "liveEdit", "wordFlood", "sunburst", "levels"):
            out.append(f"         └ {l['type'].upper()}   (+{l.get('t',0):.1f}s)")

body = "\n".join(out)
tot  = max(s["start"] + s["dur"] for s in cfg["scenes"])
words = sum(len((s.get("vo") or "").split()) for s in cfg["scenes"]
            if not (s.get("vo") or "").startswith("("))

sec = f"""## 4. Drehbuch

> **Automatisch erzeugt aus `render/timing.json`** — Dokument und gerenderter Film können
> nicht auseinanderlaufen. Neu erzeugen mit `python3 render/drehbuch.py`.
>
> **Regie:** Eine Stimme, wach, trocken, leicht amüsiert — **kein Werbeduktus, kein Pathos.**
> Schweizer Hochdeutsch, „ss" statt „ß". `^` = Caret-Einfügung des grünen Markers.

**{mm(tot)} · {len(cfg['scenes'])} Szenen · {words} Wörter · {words/(tot/60):.0f} Wörter/Minute**

```
{body}
```
"""
if "--print" in sys.argv:
    print(sec)
else:
    p = ROOT.parent / "KEYNOTE-FILM-KONZEPT.md"
    t = p.read_text(encoding="utf-8")
    i, j = t.index("## 4. Drehbuch"), t.index("### 4.1 ")
    p.write_text(t[:i] + sec + "\n" + t[j:], encoding="utf-8")
    print(f"Abschnitt 4 neu geschrieben · {mm(tot)} · {len(cfg['scenes'])} Szenen")

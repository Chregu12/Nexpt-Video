#!/usr/bin/env python3
"""
Das Cue Sheet: jeder Hit Point des Films, exakt, zum Komponieren.

    python3 cuesheet.py            -> out/analysis/cue_sheet.json
    python3 cuesheet.py --print    -> Liste auf der Konsole

WARUM NICHT AUS DEM VIDEO GEMESSEN:

Der Vorschlag lautete Videoanalyse -> Schnitte erkennen -> Cue Sheet. Fuer
einen fremden Film ist das der einzige Weg. Fuer diesen nicht: `timing.json`
IST das Cue Sheet. Dort steht auf die Millisekunde, wann welche Zeile kommt,
wann der Marker faehrt und wann der Hintergrund kippt — authored, nicht aus
Pixeln geschaetzt.

Der Unterschied ist nicht akademisch. Meine Pixelmessung am Referenzfilm fand
145 Ereignisse; die Autorenliste unseres Films kennt 230 und weiss zu jedem,
WAS passiert. Eine Schnitterkennung haette „Bewegung bei 84.2 s" gemeldet.
Hier steht „markerText VERBUNDEN, faehrt 0.24 s, Szene 17_hundert".

WAS DRINSTEHT

Je Ereignis: Zeit in Sekunden, Position als Takt.Zaehlzeit (118.00 BPM),
Szene, Art, Staerke 0..1 und der vorgeschlagene Klang. Die Staerke ist keine
Schaetzung, sondern folgt der Art des Ereignisses und seiner Groesse im Bild.

    schnitt     Szenenwechsel                  -> impact
    bgwechsel   Hintergrund kippt               -> impact
    marker      Markerstrich faehrt durchs Bild -> whoosh
    strich      Durchstreichen                  -> whoosh + impact
    karte       Etikettwechsel PROJEKT->BETRIEB -> click
    raster      Tabellenraster baut sich auf    -> ticks, aufsteigend
    pfeile      Pfeile fahren zusammen          -> whoosh
    stapel      Dateien fallen aufeinander      -> impacts, aufsteigend
    zeile       erste Silbe einer neuen Zeile   -> click
    halt        Halte-Beat: hier NICHTS          -> Stille

Die Halte-Beats stehen als eigene Eintraege drin, weil sie fuer die Musik
genauso eine Anweisung sind wie ein Schlag: dort gehoert eine Pause hin.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT  = ROOT.parent / "out" / "analysis"
BPM  = 118.00
BEAT = 60.0 / BPM
BAR  = BEAT * 4
HALT = {"05_aside", "11c_trick", "12_nein", "23_ui", "03_moment"}
JIT  = [0.55, 1.0, 0.72, 1.5, 0.85, 1.25, 0.6, 1.1]      # identisch zu film.html

cfg = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
TOT = sum(s["dur"] for s in cfg["scenes"])


def takt(t):
    n = t / BAR
    return f"{int(n)+1}.{(t % BAR) / BEAT + 1:.2f}"


cues = []
def cue(t, szene, art, staerke, klang, text="", dauer=0.0, x=0.5):
    """x ist die Position im Bild, 0 links bis 1 rechts. Ein Marker, der von
    links nach rechts faehrt, soll auch von links nach rechts zu hoeren sein —
    genau das meint Samsungs „Whoosh fuer Drehungen und Kamerafahrten"."""
    if t < 0 or t > TOT: return
    cues.append({"t": round(t, 4), "takt": takt(t), "szene": szene, "art": art,
                 "staerke": round(staerke, 2), "klang": klang,
                 "dauer": round(dauer, 3), "x": round(x, 3), "text": text})


for i, s in enumerate(cfg["scenes"]):
    t0, sid = s["start"], s["id"]

    if sid in HALT:
        # Ein Halte-Beat ist eine Anweisung, keine Luecke: hier hoert man die
        # Stille, und ein Effekt darin waere ein Fehler.
        cue(t0, sid, "halt", 1.0, "stille",
            " ".join(l.get("text", "") for l in s.get("layers", [])).strip(),
            dauer=s["dur"])
        continue

    # Der Szenenwechsel ist der haerteste Punkt im Film — bei Samsung bekommt
    # jeder der 13 Schnitte innerhalb von 120 ms einen Akzent.
    if i:
        cue(t0, sid, "schnitt", 0.9 if s.get("bg") != cfg["scenes"][i-1].get("bg") else 0.7,
            "impact", s.get("vo", "")[:60])

    for f in s.get("bgFlips", []):
        cue(t0 + f["t"], sid, "bgwechsel", 0.85, "impact", f"-> {f['to']}")

    for l in s.get("layers", []):
        lt, ty = t0 + l.get("t", 0), l["type"]
        if ty == "markerText":
            cue(lt, sid, "marker", 0.8, "whoosh", l.get("text", ""),
                dauer=l.get("draw", 0.24), x=l.get("x", 0.5))
        elif ty == "strike":
            cue(lt - 0.30, sid, "strich-anlauf", 0.5, "riser", "", dauer=0.30)
            cue(lt, sid, "strich", 1.0, "whoosh+impact", "", dauer=l.get("draw", 0.3))
        elif ty == "underline":
            cue(lt, sid, "unterstrich", 0.5, "whoosh", "", dauer=l.get("draw", 0.28),
                x=l.get("x", 0.5))
        elif ty == "sunburst":
            cue(lt, sid, "strahlen", 0.7, "whoosh", "", dauer=l.get("draw", 0.3))
        elif ty == "doodle":
            cue(lt, sid, "kritzel", 0.4, "click", l.get("shape", ""),
                dauer=l.get("draw", 0.3), x=l.get("x", 0.5))
        elif ty == "card" and l.get("swapAt") is not None:
            cue(t0 + l["swapAt"], sid, "karte", 0.9, "click",
                f"{l.get('label','')} -> {l.get('swapTo','')}")
        elif ty == "grid":
            n = 14
            for k in range(n):
                cue(lt + l.get("grow", 1.0) * (k/n) ** 1.7, sid, "raster",
                    0.25 + 0.5*k/n, "tick", f"Spalte {k+1}", x=0.15 + 0.7*k/n)
        elif ty == "pile":
            for k, f_ in enumerate(l.get("files", [])):
                cue(lt + k * l.get("step", 0.42), sid, "stapel",
                    0.45 + 0.12*k, "impact", f_, x=l.get("x", 0.5))
        elif ty == "levels":
            for k, it in enumerate(l.get("items", [])):
                cue(lt + k * l.get("step", 0.5), sid, "ebene", 0.5, "click", str(it))
        elif ty == "arrows":
            cue(lt, sid, "pfeile", 0.8, "whoosh", "", dauer=l.get("dur", 1.0))
        elif ty == "liveEdit":
            cue(lt, sid, "livekorrektur", 0.75, "click+riser", l.get("new", ""),
                dauer=l.get("draw", 0.4))
        elif ty == "wordFlood":
            cue(lt, sid, "wortflut", 0.6, "whoosh", "", dauer=l.get("dur", 2.6))
        elif ty == "text" and l.get("mode") == "words":
            # NUR die erste Silbe einer Zeile. Alle 157 Chunks zu vertonen
            # waere Geprassel: Samsung setzt Effekte auf Schnitte und die
            # 30 staerksten Bewegungen, nicht auf jede Regung.
            cue(lt, sid, "zeile", 0.45, "click", l.get("text", "")[:48], x=l.get("x", 0.5))
        elif ty == "text":
            cue(lt, sid, "zeile", 0.4, "click", l.get("text", "")[:48])

cues.sort(key=lambda c: c["t"])

# Wo drei Cues innerhalb von 80 ms liegen, bleibt der staerkste. Sonst
# stapeln sich Effekte zu Matsch — genau das, was Samsung vermeidet, indem
# die Musik dort Platz macht.
gefiltert = []
for c in cues:
    if gefiltert and c["t"] - gefiltert[-1]["t"] < 0.08 and c["art"] != "halt":
        if c["staerke"] > gefiltert[-1]["staerke"]: gefiltert[-1] = c
        continue
    gefiltert.append(c)

daten = {
    "film": {"laenge": round(TOT, 3), "bpm": BPM, "beat": round(BEAT, 6),
             "takt": round(BAR, 6), "takte": round(TOT / BAR, 3), "fps": cfg["meta"]["fps"]},
    "hinweis": ("Zeiten in Sekunden ab Filmanfang. `takt` ist Takt.Zaehlzeit bei "
                "118.00 BPM, 4/4, Takt 1 beginnt bei 0.000 s. `staerke` 0..1 ist "
                "die Wucht des Bildereignisses, nicht die Lautstaerke. `x` ist die "
                "Position im Bild, 0 links bis 1 rechts."),
    "cues": gefiltert,
}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "cue_sheet.json").write_text(json.dumps(daten, ensure_ascii=False, indent=1) + "\n",
                                    encoding="utf-8")

von_art = {}
for c in gefiltert: von_art[c["art"]] = von_art.get(c["art"], 0) + 1
print(f"out/analysis/cue_sheet.json · {len(gefiltert)} Cues auf {TOT:.1f}s "
      f"= {len(gefiltert)/TOT:.2f}/s   (Samsung gemessen: 2.20/s inkl. Musik)")
for a, n in sorted(von_art.items(), key=lambda x: -x[1]):
    print(f"   {n:4d}  {a}")

if "--print" in sys.argv:
    print(f"\n{'Zeit':>8} {'Takt':>9}  {'Szene':<15}{'Art':<14}{'Klang':<14}St.  Text")
    for c in gefiltert:
        print(f"{c['t']:8.3f} {c['takt']:>9}  {c['szene']:<15}{c['art']:<14}"
              f"{c['klang']:<14}{c['staerke']:.2f}  {c['text'][:40]}")

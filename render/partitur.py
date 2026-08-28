#!/usr/bin/env python3
"""
Die Partitur: 68 Takte Drumline, geschrieben auf die Dramaturgie des Films.

    python3 partitur.py            -> out/analysis/partitur.json
    python3 partitur.py --print    Notenbild auf der Konsole

WAS DAS IST UND WAS NICHT

Das hier ist Komposition als Noten, nicht als Klang. Was daraus wird,
entscheidet render/drumline.py mit echten Aufnahmen — hier stehen nur
Anschlaege: welches Instrument, auf welcher Sechzehntelposition, wie stark.

Es ist ausdruecklich KEINE Rekonstruktion der Referenz. Deren Muster wurde
gemessen, um den Idiom zu treffen, nicht um es zu kopieren:

    Referenz: 15 von 16 Positionen belegt · 43% der Schlaege auf
    Sechzehnteln, 32% auf Vierteln · Schwerpunkt auf Position 12,
    danach 0 und 8 · Klangfarbe 4-11 kHz, also Stoecke und Raender

Also: sechzehntelbasiert, synkopiert, dicht besetzt, hell. Die Motive
darunter sind eigene.

DIE SPRACHE

Je Takt eine Zeile aus 16 Zeichen, je Instrument eine Zeile.

    B  grosse Trommel        S  Snare, voller Schlag
    g  Snare, Geisternote    r  Rim Click (Sidestick)
    x  Stock auf Fell        h  Tom hoch       l  Tom tief
    W  Wirbel                .  nichts

Grossbuchstaben sind Akzente, Kleinbuchstaben die Fuellung. Die genauen
Anschlagstaerken und der Versatz kommen aus den Groove-Daten, nicht aus
diesen Zeichen — sie sagen nur, WAS gespielt wird.

DER AUFBAU folgt dem Film Takt fuer Takt. Die Halte-Beats sind Pausen in der
Partitur, keine ausgeblendete Musik: bei „(das ist der Trick)", „NEIN." und
„(auch nicht im UI)" steht nichts.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ZIEL = ROOT.parent / "out" / "analysis" / "partitur.json"
BPM  = 118.00
TAKTE = 68

# ── Die Motive ────────────────────────────────────────────────────────────
# Ein Motiv ist ein Takt. Call-and-Response entsteht daraus, dass Motive
# paarweise gedacht sind: das zweite antwortet dem ersten, statt es zu
# wiederholen.
#          Position  0   4   8   12
M = {
 # Intro: nur Stoecke, sehr duenn. Der Puls ist da, das Stueck noch nicht.
 "intro_a":  "x...x.......x...",
 "intro_b":  "x...x.....x.x..x",
 "intro_c":  "x.x.x...x.x.x.xx",

 # Hauptmotiv: die Frage. Trommel auf 1, Snare auf 3, Geisternoten dazwischen.
 "haupt_a":  "B.gxS..g.xr.S.gx",
 # Die Antwort: dieselbe Kontur, aber sie endet offen statt geschlossen.
 "haupt_b":  "BxgxS..gx.r.S.rr",
 "haupt_c":  "B.grSxg.Bxr.S.gx",
 "haupt_d":  "B.gxS.grBxr.S.x.",

 # Duenne Fassung fuer Textflaechen: die Viertel bleiben, der Rest geht.
 "duenn_a":  "B...S.......S...",
 "duenn_b":  "B..xS....xr.S..x",
 "duenn_c":  "....S.......S..r",

 # Aufbau: Toms kommen dazu, die Dichte steigt.
 "bau_a":    "B.gxS.g.Bxl.S.hx",
 "bau_b":    "B.glSxghBxl.S.hh",
 "bau_c":    "BlghS.ghBlghS.hh",

 # Hochpunkt: voll, mit Wirbel als Anlauf.
 "hoch_a":   "B.gxS.gxB.gxS.gx",
 "hoch_b":   "BxgxSxgxBxgxSxgx",
 "hoch_c":   "B.g.S..gW...S.hh",
 "hoch_d":   "BlghSlghBlghSlgh",

 # Absturz: fast nichts, ein einzelner Rim je Takt.
 "sturz_a":  "............r...",
 "sturz_b":  "r...............",

 # Schluss: baut auf und endet hart auf der Eins.
 "ende_a":   "B.gxS..gx.r.S.gx",
 "ende_b":   "Bxg.Sxg.Bxg.Sxgx",
 "ende_c":   "BxgxSxgxBxgxSxhh",
 "ende_d":   "BlghSlghBlghWWWW",
 "ende_e":   "B...............",
}

# ── Der Ablauf ────────────────────────────────────────────────────────────
# Je Filmtakt ein Motiv oder None (Pause). Die Szenen dahinter stehen als
# Kommentar, damit sich beides zusammen lesen laesst.
ABLAUF = [
 # 0-3 · „Wir sind Raphael und Christian Heusser." · „damit du arbeiten kannst"
 "intro_a", "intro_b", "intro_a", "intro_c",
 # 4-6 · „Und wir haben ein Versprechen." — das Stueck setzt ein
 "haupt_a", "haupt_b", "haupt_a",
 # 7-8 · „Moment. Nein." — zieht zurueck
 "duenn_a", "duenn_c",
 # 9-10 · „Arbeite so, wie DU willst."
 "haupt_c", "haupt_b",
 # 11 · „(ja, auch du in der Buchhaltung)"
 "duenn_b",
 # 12-18 · Sprints, Phasen, Tickets, Fristen · Softwareteam, Baustelle, Betrieb
 "haupt_a", "haupt_b", "haupt_c", "haupt_d", "haupt_a", "haupt_b", "bau_a",
 # 19-20 · „Wir nennen es, wie ihr es nennt."
 "haupt_c", "haupt_d",
 # 21-26 · Die Leute · Etappe/Ticket/Frist — baut auf, wird dann duenn
 "bau_a", "bau_b", "bau_a", "bau_c", "bau_b", "duenn_c",
 # 27-28 · „(das ist der Trick)" · „Ein Chaos?" · „NEIN." — STILLE
 None, None,
 # 29-34 · „Oben ist eure Sprache. Unten ist EIN Standard." — duenn zurueck
 "duenn_a", "duenn_b", "haupt_a", "haupt_b", "haupt_c", "bau_a",
 # 35-41 · Uebergang Projekt -> Betrieb
 "bau_a", "bau_b", "haupt_c", "bau_a", "bau_b", "bau_c", "hoch_a",
 # 42-48 · „100% verbunden." · „Sehen es alle. SOFORT." — HOCHPUNKT
 "hoch_a", "hoch_b", "hoch_c", "hoch_b", "hoch_a", "hoch_d", "hoch_b",
 # 49-50 · „Aber Struktur ist noch keine Uebersicht. ALLEIN" — ABSTURZ
 "sturz_a", "sturz_b",
 # 51-57 · Tabelle · Dateistapel · „Bei uns gibt es keine."
 "duenn_a", "duenn_b", "haupt_a", "haupt_b", "bau_a", "bau_b", "bau_c",
 # 58 · „(auch nicht im UI)" — STILLE
 None,
 # 59-67 · „Du siehst, was du brauchst." bis „NEXPT ist dein Partner"
 "ende_a", "ende_b", "ende_a", "ende_c", "ende_b", "ende_c", "ende_d",
 "ende_c", "ende_e",
]
assert len(ABLAUF) == TAKTE, f"{len(ABLAUF)} Takte statt {TAKTE}"

ZEICHEN = {"B": ("trommel", True), "S": ("snare", True), "g": ("geist", False),
           "r": ("rim", False), "x": ("stock", False), "h": ("tomh", False),
           "l": ("toml", False), "W": ("wirbel", True)}

noten = []
for takt, name in enumerate(ABLAUF):
    if name is None: continue
    muster = M[name]
    for pos, z in enumerate(muster):
        if z == ".": continue
        inst, akzent = ZEICHEN[z]
        noten.append({"takt": takt, "pos": pos, "inst": inst, "akzent": akzent,
                      "motiv": name})

# Flams: vor jeder betonten Snare am Anfang einer Phrase ein Vorschlag. Ein
# Schlagzeuger setzt sie dort, wo eine Linie neu ansetzt — hier am ersten
# Takt jedes Abschnitts.
abschnitt_start = set()
letzt = None
for i, n in enumerate(ABLAUF):
    art = None if n is None else n.split("_")[0]
    if art != letzt: abschnitt_start.add(i)
    letzt = art
flams = 0
for n in list(noten):
    if n["inst"] == "snare" and n["takt"] in abschnitt_start and n["pos"] == 4:
        noten.append({"takt": n["takt"], "pos": 4, "inst": "snare", "akzent": False,
                      "flam": True, "motiv": n["motiv"]})
        flams += 1

noten.sort(key=lambda n: (n["takt"], n["pos"], n["inst"]))
ZIEL.parent.mkdir(parents=True, exist_ok=True)
ZIEL.write_text(json.dumps(
    {"bpm": BPM, "takte": TAKTE, "sechzehntel": round(60/BPM/4, 6),
     "hinweis": ("Noten, kein Klang. `takt` 0..67, `pos` 0..15 im Takt. "
                 "Anschlagstaerke und Versatz kommen aus out/analysis/groove.json, "
                 "die Klaenge aus out/_vcsl/."),
     "ablauf": ABLAUF, "motive": M, "noten": noten}, ensure_ascii=False, indent=1) + "\n",
    encoding="utf-8")

von_inst = {}
for n in noten: von_inst[n["inst"]] = von_inst.get(n["inst"], 0) + 1
still = sum(1 for a in ABLAUF if a is None)
print(f"out/analysis/partitur.json · {len(noten)} Anschlaege auf {TAKTE} Takten "
      f"= {len(noten)/TAKTE:.1f} je Takt · {still} Takte Stille · {flams} Flams")
for i, k in sorted(von_inst.items(), key=lambda x: -x[1]):
    print(f"   {k:4d}  {i}")

if "--print" in sys.argv:
    print()
    for takt, name in enumerate(ABLAUF):
        m = M[name] if name else "                "
        print(f"  {takt+1:3d}  {m}  {name or '— Stille'}")

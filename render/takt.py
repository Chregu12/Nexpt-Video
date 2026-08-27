#!/usr/bin/env python3
"""
timing.json auf das Musikraster legen.

    python3 takt.py --probe     zeigen, was sich aendern wuerde
    python3 takt.py             timing.json schreiben (Kopie als .vor-takt)

Nebenbei repariert das hier einen Versatz, der laenger drin war: ab 09_flut
lag jeder `start` genau 2.00 s vor seiner kumulierten Position. Das Bild
entsteht aus den DAUERN (gemessen 137.51 s), der Ton aus den START-Zeiten
(135.44 s) — ab 0:36 lief die Stimme dem Bild zwei Sekunden voraus. Weil
hier nicht mehr `start`, sondern die DAUER gerastert wird und die Startzeiten
als laufende Summe daraus entstehen, kann das nicht wiederkehren.

WARUM DAS UND NICHT DIE MUSIK:

Der Wunsch war, dass die Musik zur Schriftanimation passt. Ich habe zuerst
den Referenzfilm daraufhin vermessen, und das Ergebnis war eindeutig — und
gegen meine Erwartung. Apples Schrift sitzt NICHT auf dem Takt:

    145 Bildereignisse gegen das 118er Raster, drei Aufloesungen:
      Viertel      Raster 508 ms · 24% innerhalb 60 ms   (Zufall 24%)
      Achtel       Raster 254 ms · 48% innerhalb 60 ms   (Zufall 47%)
      Sechzehntel  Raster 127 ms · 91% innerhalb 60 ms   (Zufall 94%)

Jeder Wert liegt exakt auf Zufallsniveau. Auch die Abstaende zwischen den
Bildereignissen haeufen sich nicht auf Vielfachen des Beats. Was den Eindruck
von Synchronitaet macht, ist nur die gemeinsame Atemfrequenz: Apples Bild
wechselt im Mittel alle 0.52 s, ein Beat dauert 0.51 s.

Die Musik allein zu verschieben bringt entsprechend wenig. Gemessen an der
fertigen Datei: 19% unserer grossen Bildereignisse fallen auf einen starken
Anschlag, gegen 12% Zufallsniveau. Das ist die Decke bei festem Tempo gegen
einen auf die Stimme geschnittenen Film.

Das Werkzeug, das wirklich greift, ist dieses hier: den FILM auf das Raster
legen. Und es kostet fast nichts —

    30 Szenenanfaenge auf Achtel:  Median 73 ms Verschiebung, max 118 ms
    Summe aller Verschiebungen:    2.0 s auf 135 s Film

118 ms sind dreieinhalb Frames. Einzeln sieht das niemand; zusammen sitzt
danach jeder Szenenanfang auf einem Achtel und jedes grosse Ereignis
innerhalb der Szene auf einem Sechzehntel.

DAS RASTER liegt bei 118.00 BPM ab Filmzeit 0.000 — Beat 0.5085 s, Achtel
0.2542 s, Sechzehntel 0.1271 s. musik.py setzt den Track dazu passend mit
Versatz 0 an, der erste Downbeat des Tracks (0.222 s) faellt also auf
Filmanfang. Film und Musik teilen danach ein einziges Raster.

NICHT gerastert werden die Text-Chunks. Ihre Abstaende (step * JIT) sind das
Handschriftliche an der Animation und aus dem Referenzfilm abgemessen; sie
auf Zweiunddreissigstel zu zwingen wuerde die Schrift zum Metronom machen.
Gerastert wird, was als Ereignis wahrgenommen wird: Szenenanfang,
Hintergrundwechsel, Marker, Strich, Etikettwechsel.
"""
import json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BPM  = 118.00
BEAT = 60.0 / BPM
ACHTEL, SECHZEHNTEL = BEAT/2, BEAT/4

cfg = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
probe = "--probe" in sys.argv

def raste(t, g):
    return round(round(t / g) * g, 4)

def letztes_ereignis(sz):
    """Wann in der Szene passiert zuletzt etwas? Darunter darf die Dauer
    nicht rutschen, sonst wird der letzte Einblender abgeschnitten."""
    spaet = 0.0
    for f in sz.get("bgFlips", []): spaet = max(spaet, f["t"])
    for l in sz.get("layers", []):
        t = l.get("t", 0.0)
        if l["type"] == "text" and l.get("mode") == "words":
            n = sum(2 if len(w) >= 8 else 1 for w in l["text"].split())
            t += n * l.get("step", 0.145) * 0.95 + (l.get("lastDelay") or 0)
        if l["type"] == "card" and l.get("swapAt") is not None:
            t = max(t, l["swapAt"])
        for feld in ("draw", "dur", "grow"):
            if isinstance(l.get(feld), (int, float)): t += l[feld]
        if l["type"] in ("levels", "pile"):
            t += len(l.get("items") or l.get("files") or []) * l.get("step", 0.42)
        spaet = max(spaet, t)
    return spaet

# ── Erst der Versatz, dann das Raster ─────────────────────────────────────
# Vorgefunden: ab 09_flut liegt jeder `start` genau 2.00 s vor seiner
# kumulierten Position. Das Bild wird aus den DAUERN aneinandergehaengt
# (137.51 s gemessen), der Ton aus den START-Zeiten gebaut (135.44 s) — ab
# 0:36 lief die Stimme dem Bild also zwei Sekunden voraus. Ursache: 08_broll
# wurde beim Ersetzen des B-Roll-Platzhalters von 4.0 auf 6.0 s verlaengert,
# ohne die nachfolgenden Startzeiten mitzuziehen.
#
# Deshalb wird hier nicht mehr `start` gerastert, sondern die DAUER. Die
# Startzeiten ergeben sich danach als laufende Summe und koennen gar nicht
# mehr auseinanderlaufen. Weil jede Dauer auf einem Achtel liegt, liegt auch
# jeder Szenenanfang auf einem Achtel.
alt_start = [s["start"] for s in cfg["scenes"]]
alt_dur   = [s["dur"] for s in cfg["scenes"]]
TOT_ALT   = max(s["start"] + s["dur"] for s in cfg["scenes"])
KUM_ALT   = sum(alt_dur)

neu_dur = []
for sz in cfg["scenes"]:
    noetig = letztes_ereignis(sz) + 0.30
    d = raste(sz["dur"], ACHTEL)
    while d < max(0.5, min(noetig, sz["dur"])):     # nie unter den Inhalt rutschen
        d = round(d + ACHTEL, 4)
    neu_dur.append(d)
# Der Film soll auf einem vollen Takt enden, damit die Musik nicht mitten in
# einer Phrase ausgeblendet wird. Fehlender Rest geht an die Schlussszene —
# dort steht ohnehin die Zeile, die am laengsten stehen darf.
TAKT = BEAT * 4
lauf = sum(neu_dur)
rest = round((-lauf) % TAKT, 4)
if rest > 0.01:
    neu_dur[-1] = round(neu_dur[-1] + rest, 4)
neu_start, lauf = [], 0.0
for d in neu_dur:
    neu_start.append(round(lauf, 4)); lauf = round(lauf + d, 4)
TOT_NEU = round(lauf, 4)

print(f"Raster {BPM:.2f} BPM ab 0.000s · Achtel {ACHTEL:.4f}s · Sechzehntel {SECHZEHNTEL:.4f}s")
print(f"\nvorgefundener Versatz Bild/Ton: {KUM_ALT - TOT_ALT:+.2f}s "
      f"(Bild {KUM_ALT:.2f}s, Ton {TOT_ALT:.2f}s)")
print(f"\n{'Szene':<16}{'start alt':>10}{'start neu':>10}{'Δ ms':>7}"
      f"{'Dauer alt':>10}{'Dauer neu':>10}{'Δ ms':>7}")
verschub = []
for i, sz in enumerate(cfg["scenes"]):
    ds = (neu_start[i] - alt_start[i]) * 1000
    dd = (neu_dur[i] - alt_dur[i]) * 1000
    verschub.append(abs(dd))
    print(f"{sz['id']:<16}{alt_start[i]:10.2f}{neu_start[i]:10.2f}{ds:+7.0f}"
          f"{alt_dur[i]:10.2f}{neu_dur[i]:10.2f}{dd:+7.0f}")

# ── Grosse Ereignisse innerhalb der Szene auf Sechzehntel ─────────────────
# Die Zeiten sind relativ zum Szenenanfang. Weil der Anfang auf einem Achtel
# liegt, sitzt ein Sechzehntel-Versatz danach absolut auf einem Sechzehntel.
GROSS = {"markerText": ["t"], "strike": ["t"], "card": ["t", "swapAt"],
         "underline": ["t"], "sunburst": ["t"], "liveEdit": ["t"],
         "doodle": ["t"], "grid": ["t"]}
# `out` wandert mit — aber NUR bei den Typen, deren `t` auch gerastert wird.
# Zwei Anlaeufe, zwei Loecher: laesst man `out` stehen, verschwindet in
# 08_broll eine Karte bei 3.90, waehrend die naechste erst bei 3.9407 kommt.
# Rastert man `out` ueberall, reisst dasselbe Loch bei den Textzeilen auf,
# deren `t` absichtlich ungerastert bleibt. Beides sind zwei leere Frames:
# im Standbild unsichtbar, im Lauf ein Flackern.
n_lay = 0
for s in cfg["scenes"]:
    for f in s.get("bgFlips", []):
        f["t"] = raste(f["t"], SECHZEHNTEL); n_lay += 1
    for l in s.get("layers", []):
        if l.get("out") is not None and l["type"] in GROSS:
            l["out"] = raste(l["out"], SECHZEHNTEL); n_lay += 1
        for feld in GROSS.get(l["type"], []):
            if l.get(feld) is None: continue
            l[feld] = raste(l[feld], SECHZEHNTEL); n_lay += 1

for i, sz in enumerate(cfg["scenes"]):
    sz["start"] = neu_start[i]
    sz["dur"]   = neu_dur[i]

print(f"\n{len(cfg['scenes'])} Dauern auf Achtel · {n_lay} grosse Ereignisse auf Sechzehntel")
print(f"Median-Aenderung der Dauer {sorted(verschub)[len(verschub)//2]:.0f} ms · "
      f"max {max(verschub):.0f} ms")
print(f"Laenge {TOT_ALT:.2f}s (Ton) / {KUM_ALT:.2f}s (Bild)  ->  {TOT_NEU:.2f}s, "
      f"beides gleich ({TOT_NEU/BEAT:.0f} Beats, {TOT_NEU/(BEAT*4):.2f} Takte)")

# ── Auf die tatsaechlichen Anschlaege ziehen ──────────────────────────────
# Das Raster allein reicht nicht. Gemessen am Track: von 272 Vierteln tragen
# nur 36% einen starken Anschlag, von 1088 Sechzehnteln nur 16% — der Track
# lebt vom Leerraum. Ein Ereignis auf einem Sechzehntel, das der Schlagzeuger
# nicht spielt, faellt also mit nichts zusammen.
#
# Deshalb dieser zweite Durchgang: jedes grosse Ereignis wird auf den
# naechsten STARKEN Anschlag gezogen, wenn einer innerhalb eines Sechzehntels
# liegt. Die Anschlagszeiten kommen aus musik.py (out/_musik/anschlaege.json),
# gemessen am rohen Track und auf Filmzeit umgerechnet.
#
# Szenenanfaenge koennen nicht einzeln wandern — sie sind die Summe der
# Dauern. Sie werden deshalb als Grenze verschoben: geht der Anfang von Szene
# i um ein Sechzehntel vor, wird Szene i-1 um ein Sechzehntel kuerzer und
# Szene i um eines laenger. Die Gesamtlaenge bleibt damit auf 68 Takten.
def naechster(ziel, liste, spanne):
    if not liste: return ziel
    k = min(liste, key=lambda x: abs(x - ziel))
    return k if abs(k - ziel) <= spanne else ziel

anschlagsdatei = ROOT.parent / "out" / "_musik" / "anschlaege.json"
n_zug, n_grenze = 0, 0
if anschlagsdatei.exists():
    schlaege = json.loads(anschlagsdatei.read_text(encoding="utf-8"))["anschlaege"]
    spanne = SECHZEHNTEL + 0.005

    # 1) Szenengrenzen. Hier ist die Spanne ein ACHTEL statt ein Sechzehntel:
    #    gemessen liegen die meisten Grenzen genau 252 ms neben einem Anschlag,
    #    also ein Achtel — mit der engeren Spanne waere keine einzige gewandert.
    #    Ein Achtel entspricht dem Raster, auf dem die Dauern ohnehin liegen.
    for i in range(1, len(cfg["scenes"])):
        ziel = naechster(neu_start[i], schlaege, ACHTEL + 0.005)
        d = round(ziel - neu_start[i], 4)
        if abs(d) < 0.004: continue
        vor, jetzt = neu_dur[i-1] + d, neu_dur[i] - d
        if vor < max(0.5, letztes_ereignis(cfg["scenes"][i-1]) + 0.20): continue
        if jetzt < max(0.5, letztes_ereignis(cfg["scenes"][i]) + 0.20): continue
        neu_dur[i-1], neu_dur[i] = round(vor, 4), round(jetzt, 4)
        neu_start[i] = round(ziel, 4); n_grenze += 1

    # 2) Ereignisse innerhalb der Szene — relativ zum (evtl. verschobenen) Anfang.
    #    `out` wandert um denselben Betrag mit, damit keine Luecke aufreisst.
    for i, sz in enumerate(cfg["scenes"]):
        a = neu_start[i]
        for f in sz.get("bgFlips", []):
            d = naechster(a + f["t"], schlaege, spanne) - (a + f["t"])
            if abs(d) >= 0.004: f["t"] = round(f["t"] + d, 4); n_zug += 1
        for l in sz.get("layers", []):
            if l["type"] not in GROSS: continue
            d = naechster(a + l["t"], schlaege, spanne) - (a + l["t"])
            if abs(d) < 0.004: continue
            l["t"] = round(l["t"] + d, 4)
            if l.get("out") is not None: l["out"] = round(l["out"] + d, 4)
            if l.get("swapAt") is not None: l["swapAt"] = round(l["swapAt"] + d, 4)
            n_zug += 1

    for i, sz in enumerate(cfg["scenes"]):
        sz["start"], sz["dur"] = neu_start[i], neu_dur[i]
    print(f"\nauf echte Anschlaege gezogen: {n_grenze} Szenengrenzen, {n_zug} Ereignisse")
    print(f"Laenge weiterhin {sum(neu_dur):.2f}s ({sum(neu_dur)/(BEAT*4):.2f} Takte)")
else:
    print("\nout/_musik/anschlaege.json fehlt — nur Raster, keine Anschlaege. "
          "Erst `python3 musik.py` laufen lassen.")

# ── Luecken schliessen ────────────────────────────────────────────────────
# Verschobene `t` koennen eine Uebergabe aufreissen: Zeile A verschwindet bei
# 3.90, Zeile B kommt erst bei 3.94 — zwei leere Frames. Wo das passiert,
# bleibt die vorige Zeile stehen, bis die naechste da ist.
TRAEGT = {"text", "role", "card", "pile", "levels", "broll", "grid",
          "markerText", "url", "checkbox", "wordFlood", "liveEdit"}
n_luecke = 0
for sz in cfg["scenes"]:
    tr = sorted([l for l in sz.get("layers", []) if l["type"] in TRAEGT],
                key=lambda l: l.get("t", 0))
    for j, l in enumerate(tr):
        if l.get("out") is None: continue
        spaeter = [x.get("t", 0) for x in tr[j+1:] if x.get("t", 0) >= l["out"] - 0.001]
        if not spaeter: continue
        naechste = min(spaeter)
        if naechste > l["out"] + 0.001:
            l["out"] = round(naechste, 4); n_luecke += 1
if n_luecke: print(f"{n_luecke} Uebergabe(n) geschlossen")

if probe:
    print("\n--probe: nichts geschrieben.")
    sys.exit(0)

sich = ROOT / "timing.json.vor-takt"
if not sich.exists():
    shutil.copy(ROOT / "timing.json", sich)
    print(f"\nKopie des alten Stands: {sich.name}")
(ROOT / "timing.json").write_text(
    json.dumps(cfg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("timing.json geschrieben — Clips muessen neu gerendert werden.")

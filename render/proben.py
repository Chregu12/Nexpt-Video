#!/usr/bin/env python3
"""
Echte Schlaege aus dem Musikloop schneiden — die Klangpalette fuers Sounddesign.

    python3 proben.py                 -> out/_proben/*.wav + palette.json
    python3 proben.py <quelle>        andere Quelle
    python3 proben.py --bericht       nur zeigen, was gefunden wurde

WARUM AUS DEM LOOP UND NICHT AUS EINER LIBRARY

Der Einwand war richtig: Sinus plus gefiltertes Rauschen klingt nach Roboter,
weil es einer ist. Fuer echte Aufnahmen gibt es drei Wege, und zwei davon
sind hier zu.

  Freesound  braucht ein API-Token (401 ohne). Mit Token und CC0-Filter waere
             es der sauberste Weg — die Lizenz steht dann je Datei fest.
  archive.org  erreichbar, aber der CC0-Bestand ist Grillenzirpen, Kuechen-
             wecker und etliche als „public domain" fehldeklarierte
             Kauf-Libraries. Fuer einen kommerziellen Messefilm nicht
             brauchbar, und zwar nicht wegen der Qualitaet.
  Der eigene Loop  ist echte Perkussion, gehoert dem Lizenznehmer, und die
             Schlaege passen per Konstruktion zur Musik — es sind dieselben
             Instrumente.

Also der dritte Weg. Was der Loop NICHT hergibt, steht unten.

WAS DRIN IST UND WAS FEHLT

Gemessen an der Quelle: 126 Schlaege, Schwerpunkt 988-11678 Hz, Median
4785 Hz. Es sind Stoecke, Rims und Snares — und KEINE tiefe Trommel: der
tiefste Schwerpunkt liegt bei 988 Hz. Impacts, Whooshes und Riser lassen sich
daraus nicht schneiden, die kommen weiter aus der Synthese (dann aber modal,
siehe sfx.py). Klicks, Ticks und die perkussiven Akzente kommen ab jetzt aus
echten Aufnahmen.

Ausgewaehlt wird nach SAUBERKEIT: je groesser der Abstand zum naechsten
Schlag, desto weniger blutet der Nachbar hinein. Ein Schlag mit 400 ms Luft
dahinter ist als Probe brauchbar, einer mit 60 ms nicht.
"""
import json, os, shutil, subprocess, sys, wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
ZIEL = OUT / "_proben"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
SR = 48000

quelle = next((a for a in sys.argv[1:] if not a.startswith("--")),
              str(OUT / "_musik" / "apple-style-118.mp3"))
if not Path(quelle).exists():
    print(f"{quelle} fehlt."); sys.exit(1)


def laden(pfad, mono=True):
    roh = subprocess.run([FFMPEG, "-v", "quiet", "-i", pfad, "-ac", "1" if mono else "2",
                          "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(roh, "<f4").astype(np.float64)
    return x if mono else x.reshape(-1, 2)


y = laden(quelle)
H, W = 256, 2048
n = 1 + (len(y) - W) // H
S = np.abs(np.fft.rfft(np.lib.stride_tricks.as_strided(
    y, (n, W), (y.strides[0]*H, y.strides[0])) * np.hanning(W), axis=1))
fl = np.maximum(0, np.diff(S, axis=0)).sum(1); fps = SR / H
f = (fl - fl.mean()) / (fl.std() or 1)
schwelle = np.percentile(f, 85)
roh = [i for i in range(1, len(f)-1) if f[i] > schwelle and f[i] >= f[i-1] and f[i] > f[i+1]]
ons = []
for i in roh:
    t = i / fps
    if ons and t - ons[-1] < 0.06: continue
    ons.append(t)

# Je Schlag: Schwerpunkt, Spitze, Luft bis zum naechsten
schlaege = []
for k, t in enumerate(ons):
    i0 = int(t * SR)
    luft = (ons[k+1] - t) if k + 1 < len(ons) else 0.9
    i1 = min(len(y), i0 + int(min(luft, 0.9) * SR))
    seg = y[i0:i1]
    if len(seg) < 1200: continue
    fenster = int(min(0.06 * SR, len(seg)))
    Sp = np.abs(np.fft.rfft(seg[:fenster] * np.hanning(fenster)))
    fr = np.fft.rfftfreq(fenster, 1/SR)
    schlaege.append({"t": t, "zentrum": float((Sp*fr).sum() / (Sp.sum() + 1e-12)),
                     "spitze": float(np.abs(seg[:int(0.02*SR)]).max()), "luft": float(luft)})

KLASSEN = [("tick",  0,    2600, 0.16),      # Stock, Rim — kurz und hell
           ("klick", 2600, 5200, 0.20),      # Klack mit etwas Koerper
           ("snare", 5200, 99999, 0.32)]     # breitbandig, mit Teppich

def schreiben(pfad, x):
    x = np.nan_to_num(x)
    m = np.max(np.abs(x)) or 1.0
    x = x / m * 0.92
    with wave.open(str(pfad), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())

ZIEL.mkdir(parents=True, exist_ok=True)
for alt in ZIEL.glob("*.wav"): alt.unlink()
palette, bericht = {}, []
for name, lo, hi, laenge in KLASSEN:
    kand = [s for s in schlaege if lo <= s["zentrum"] < hi]
    # Sauberkeit vor Lautstaerke: erst die mit der meisten Luft dahinter.
    kand.sort(key=lambda s: (-min(s["luft"], 0.45), -s["spitze"]))
    gewaehlt = kand[:4]
    for j, s in enumerate(gewaehlt):
        i0 = int(s["t"] * SR)
        nutz = min(laenge, max(0.07, s["luft"] * 0.92))
        i1 = min(len(y), i0 + int(nutz * SR))
        seg = y[i0:i1].copy()
        # 4 ms Einblende gegen den Knack am Schnitt, Ausblende ueber das
        # letzte Viertel, damit der Nachbar nicht als Abriss stehenbleibt.
        ein = int(0.004 * SR)
        seg[:ein] *= np.linspace(0, 1, ein)
        aus = max(1, len(seg)//4)
        seg[-aus:] *= np.linspace(1, 0, aus) ** 1.5
        datei = ZIEL / f"{name}{j+1}.wav"
        schreiben(datei, seg)
        palette.setdefault(name, []).append(datei.name)
        bericht.append((name, j+1, s["t"], s["zentrum"], s["luft"], nutz))

(ZIEL / "palette.json").write_text(json.dumps(
    {"quelle": Path(quelle).name, "sr": SR, "proben": palette,
     "hinweis": ("Echte Schlaege aus dem eigenen Musikloop. Keine tiefe Trommel "
                 "enthalten — der tiefste Schwerpunkt der Quelle liegt bei 988 Hz.")},
    ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

print(f"{len(schlaege)} Schlaege in {Path(quelle).name} · {sum(len(v) for v in palette.values())} "
      f"Proben nach out/_proben/")
print(f"{'Probe':<10}{'bei':>8}{'Schwerpunkt':>13}{'Luft':>8}{'Laenge':>8}")
for name, j, t, z, luft, nutz in bericht:
    print(f"{name}{j:<9}{t:8.2f}s{z:11.0f} Hz{luft*1000:7.0f}ms{nutz*1000:7.0f}ms")

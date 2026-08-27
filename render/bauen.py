#!/usr/bin/env python3
"""
Baut den Film zusammen — aber erst, wenn wirklich alles fertig ist.

Drei Fehler sind mir beim Zusammenbau mehrfach passiert; alle drei faengt
dieses Skript ab:
  1. Zusammenbau gestartet, waehrend der Render noch lief -> halb geschriebene
     Clips landeten im Film.
  2. Clips gestrichener Szenen lagen noch im Ordner und liefen mit.
  3. Clips waren zwar vollstaendig, aber aelter als timing.json - die
     Dauerpruefung greift dort nicht, weil sich nur Farben geaendert hatten.

    python3 bauen.py            pruefen und bauen
    python3 bauen.py --check    nur pruefen
"""
import json, os, re, subprocess, sys, glob
from pathlib import Path

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
FF = os.environ.get("FFMPEG") or \
     "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
cfg = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
src_mtime = (ROOT / "timing.json").stat().st_mtime
film_mtime = (ROOT / "film.html").stat().st_mtime
neuer_als = max(src_mtime, film_mtime)

fehler = []
if subprocess.run(["pgrep", "-f", "render.py"], capture_output=True).returncode == 0:
    fehler.append("Ein Render laeuft noch — Zusammenbau abgebrochen.")

soll = {s["id"] for s in cfg["scenes"]}
ist  = {Path(p).stem for p in glob.glob(str(OUT / "scenes" / "*.mov"))}
for x in ist - soll:
    fehler.append(f"{x}.mov gehoert zu keiner Szene mehr (gestrichen?)")

for s in cfg["scenes"]:
    p = OUT / "scenes" / f"{s['id']}.mov"
    if not p.exists():
        fehler.append(f"{s['id']}: Clip fehlt"); continue
    if p.stat().st_mtime < neuer_als - 1:
        fehler.append(f"{s['id']}: Clip aelter als die Quelle — nicht neu gerendert")
    r = subprocess.run([FF, "-hide_banner", "-i", str(p)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r)
    if not m:
        fehler.append(f"{s['id']}: Datei defekt"); continue
    got = int(m[1])*3600 + int(m[2])*60 + float(m[3])
    if abs(got - s["dur"]) > 0.15:
        fehler.append(f"{s['id']}: {got:.2f}s statt {s['dur']:.2f}s")

if fehler:
    print(f"{len(fehler)} Problem(e) — nicht gebaut:")
    for f in fehler[:12]: print("   ", f)
    sys.exit(1)
print(f"✓ {len(soll)} Clips vollstaendig, aktuell und in Solldauer")
if "--check" in sys.argv: sys.exit(0)

liste = OUT / "concat.txt"
liste.write_text("".join(f"file 'scenes/{s['id']}.mov'\n" for s in cfg["scenes"]), encoding="utf-8")
V = OUT / "NEXPT-Keynote-ANIMATIC.mp4"
subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
    "-i", str(liste), "-vf",
    "scale=in_range=tv:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709",
    "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
    "-movflags", "+faststart", str(V)], check=True, cwd=OUT)
liste.unlink()
subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(V),
    "-i", str(OUT/"ton-final.wav"), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
    "-shortest", "-movflags", "+faststart",
    str(OUT/"NEXPT-Keynote-ANIMATIC-SCRATCH.mp4")], check=True)
tot = max(s["start"]+s["dur"] for s in cfg["scenes"])
print(f"✓ gebaut: {int(tot//60)}:{tot%60:04.1f}")

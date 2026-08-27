#!/usr/bin/env python3
"""
NEXPT Keynote — Renderer.

Rendert timing.json deterministisch zu ProRes-Clips fuer Final Cut Pro.
Pro Szene ein Clip, damit sich in FCP jede Szene einzeln auf die
aufgenommene Off-Stimme schieben laesst.

    python3 render.py                 # alle Szenen
    python3 render.py 15 22           # nur diese Szenen (Nummer oder id-Fragment)
    python3 render.py --stills        # nur je ein Standbild pro Szene (schnell)
    python3 render.py --alpha         # ProRes 4444 mit Alpha statt 422 HQ
"""
import hashlib, json, os, subprocess, sys, shutil
from pathlib import Path

def fingerabdruck(scene, film_html):
    """Ein Clip ist genau dann aktuell, wenn Szenendefinition UND Renderer
    unveraendert sind. Ein Zeitstempelvergleich gegen timing.json wuerde bei
    jeder Aenderung an EINER Szene alle 30 Clips als veraltet melden."""
    roh = json.dumps(scene, sort_keys=True, ensure_ascii=False) + film_html
    return hashlib.sha256(roh.encode()).hexdigest()[:16]

def stempel_lesen(pfad):
    try: return json.loads(pfad.read_text(encoding="utf-8"))
    except Exception: return {}

ROOT = Path(__file__).resolve().parent
OUT  = ROOT.parent / "out"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
         "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"

cfg    = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
FPS    = cfg["meta"]["fps"]; W = cfg["meta"]["width"]; H = cfg["meta"]["height"]
PAL    = cfg["palette"]

args    = [a for a in sys.argv[1:] if not a.startswith("--")]
STILLS  = "--stills" in sys.argv
ALPHA   = "--alpha"  in sys.argv
scenes  = [s for s in cfg["scenes"]
           if not args or any(a in s["id"] or a == s["id"].split("_")[0] for a in args)]

OUT.mkdir(exist_ok=True); (OUT / "scenes").mkdir(exist_ok=True); (OUT / "stills").mkdir(exist_ok=True)
FILM_HTML = (ROOT / "film.html").read_text(encoding="utf-8")
STEMPEL   = OUT / "scenes" / "stempel.json"
stempel   = stempel_lesen(STEMPEL)

from playwright.sync_api import sync_playwright

def encode(frames_dir, dst, dur):
    # prores_ks profile 3 = 422 HQ, 4 = 4444 (mit Alpha); FCP importiert beides nativ
    prof, pix = ("4", "yuva444p10le") if ALPHA else ("3", "yuv422p10le")
    # Ohne explizite Matrix rechnet swscale RGB->YUV nach bt601, taggt aber bt709:
    # der Akzent #00D759 kam als #00BA56 heraus. Gemessen, nicht vermutet.
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-framerate", str(FPS), "-i", str(frames_dir / "f_%05d.png"),
        "-vf", "scale=in_range=full:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709",
        "-c:v", "prores_ks", "-profile:v", prof, "-pix_fmt", pix,
        "-vendor", "apl0", "-colorspace", "bt709", "-color_primaries", "bt709",
        "-color_trc", "bt709", str(dst)], check=True)

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME, args=[
        "--no-sandbox", "--force-color-profile=srgb",
        "--disable-lcd-text", "--font-render-hinting=none",
        "--hide-scrollbars", "--disable-gpu"])
    pg = br.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    pg.goto((ROOT / "film.html").as_uri())
    pg.wait_for_timeout(700)            # Schriften laden

    for s in scenes:
        pg.evaluate("([sc,pal])=>window.setup(sc,pal)", [s, PAL])
        if STILLS:
            pg.evaluate("t=>window.renderAt(t)", s["dur"] * 0.72)
            pg.screenshot(path=str(OUT / "stills" / f"{s['id']}.png"))
            print(f"  still  {s['id']}"); continue

        tmp = OUT / "_frames" / s["id"]
        if tmp.exists(): shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        n = int(round(s["dur"] * FPS))
        for i in range(n):
            pg.evaluate("t=>window.renderAt(t)", i / FPS)
            pg.screenshot(path=str(tmp / f"f_{i+1:05d}.png"))
        dst = OUT / "scenes" / f"{s['id']}.mov"
        encode(tmp, dst, s["dur"])
        shutil.rmtree(tmp)
        stempel[s["id"]] = fingerabdruck(s, FILM_HTML)
        STEMPEL.write_text(json.dumps(stempel, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"  ✓ {s['id']:<18} {s['dur']:>4.1f}s  {n:>3} frames  "
              f"{dst.stat().st_size/1e6:>5.1f} MB")
    br.close()

if not STILLS:
    shutil.rmtree(OUT / "_frames", ignore_errors=True)
print("\nfertig →", OUT)

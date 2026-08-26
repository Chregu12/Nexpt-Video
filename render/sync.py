#!/usr/bin/env python3
"""
Zieht die Animation auf die AUFGENOMMENE Stimme.

Das ist der Ersatz für stundenlanges Schieben in Final Cut. Zwei Wege:

  python3 sync.py vo.wav               Sprachpausen messen und Szenen darauf legen
  python3 sync.py vo.wav --gap 0.4     Mindestpause selbst vorgeben statt suchen lassen
  python3 sync.py Projekt.fcpxml       zurücklesen, wie du in FCP geschoben hast
  python3 sync.py vo.wav --fit         nur global auf die Gesamtlänge dehnen (Notnagel)
  ... --dry                            nur zeigen, timing.json nicht schreiben

Danach `python3 render.py` — jede Animation sitzt frame-genau auf der echten Stimme.
Der FCPXML-Weg ist der massgebliche: du hörst, code rechnet nach.
"""
import json, os, re, shutil, subprocess, sys
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
CFG  = ROOT / "timing.json"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"

src   = Path(sys.argv[1]) if len(sys.argv) > 1 else None
DRY   = "--dry" in sys.argv
FIT   = "--fit" in sys.argv
if not src or not src.exists(): sys.exit(__doc__)

cfg    = json.loads(CFG.read_text(encoding="utf-8"))
scenes = cfg["scenes"]
FPS    = cfg["meta"]["fps"]
snap   = lambda t: round(t * FPS) / FPS          # auf Frames rasten, sonst driftet es

def audio_len(p):
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(p)],
                         capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h)*3600 + int(m)*60 + float(s)

def find_threshold(p, want):
    """Sucht die Pausenschwelle, die genau `want` Sprachbloecke ergibt.
    Bevorzugt wird der breiteste stabile Bereich — der ist gegen Atmer robust."""
    grid, hits = [], {}
    for noise in ("-30dB", "-33dB", "-36dB", "-40dB"):
        for g in [round(0.16 + i*0.02, 2) for i in range(45)]:
            n = len(speech_segments(p, noise, g)[0])
            grid.append((noise, g, n))
            if n == want: hits.setdefault(noise, []).append(g)
    if not hits:
        near = min(grid, key=lambda r: (abs(r[2]-want), -r[1]))
        return None, near
    noise, gs = max(hits.items(), key=lambda kv: len(kv[1]))   # laengstes Plateau
    return (noise, gs[len(gs)//2]), None

def speech_segments(p, noise="-32dB", mind=0.20):
    """Sprachblöcke = alles zwischen den Pausen."""
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(p),
        "-af", f"silencedetect=noise={noise}:d={mind}", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.\-]+)", out)]
    ends   = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    dur, segs, cur = audio_len(p), [], 0.0 if not ends or ends[0] > 0.05 else ends.pop(0)
    for i, s0 in enumerate(starts):
        if s0 - cur > 0.12: segs.append((cur, s0))
        cur = ends[i] if i < len(ends) else dur
    if dur - cur > 0.12: segs.append((cur, dur))
    return segs, dur

def apply(new_starts, new_durs):
    for sc, st, du in zip(scenes, new_starts, new_durs):
        old = sc["start"]
        sc["start"], sc["dur"] = snap(st), snap(du)
        # Layer-Zeiten sind relativ zur Szene — sie wandern automatisch mit.
        # Nur wenn die Szene kürzer wird, Layer hinter dem Ende hereinholen:
        for l in sc.get("layers", []):
            if l.get("t", 0) > sc["dur"] - 0.1:
                l["t"] = max(0.0, snap(sc["dur"] - 0.35))

# ---------------------------------------------------------------- FCPXML zurücklesen
if src.suffix.lower() == ".fcpxml":
    def secs(v):
        v = v.rstrip("s")
        return eval(v) if "/" in v else float(v)          # "9000/3000s" -> 3.0
    root = ET.fromstring(src.read_text(encoding="utf-8").split("\n", 2)[-1])
    clips = [(c.get("name"), secs(c.get("offset", "0s")), secs(c.get("duration")))
             for c in root.iter("asset-clip")]
    by_id = {n: (o, d) for n, o, d in clips}
    miss  = [s["id"] for s in scenes if s["id"] not in by_id]
    if miss: sys.exit(f"Im FCPXML fehlen: {', '.join(miss)}")
    st = [by_id[s["id"]][0] for s in scenes]
    du = [by_id[s["id"]][1] for s in scenes]
    print(f"FCPXML gelesen · {len(clips)} Clips · neue Gesamtlänge {max(a+b for a,b in zip(st,du)):.2f}s")
    apply(st, du)

# ---------------------------------------------------------------- Audio vermessen
else:
    def sentences(v):
        return [x for x in re.split(r"(?<=[.!?])\s+", (v or "").strip()) if x]
    voiced = [i for i, s in enumerate(scenes)
              if (s.get("vo") or "").strip() and not s["vo"].startswith("(")]
    # Wieviele Sprechpausen sind zu erwarten? Eine je Satz, nicht je Szene.
    sent_of = {i: len(sentences(scenes[i]["vo"])) for i in voiced}
    n_sent  = sum(sent_of.values())
    gap = next((float(sys.argv[i+1]) for i, a in enumerate(sys.argv) if a == "--gap"), None)
    if gap is not None:
        segs, dur = speech_segments(src, mind=gap)
        print(f"{src.name}: {dur:.2f}s · Pausenschwelle {gap}s vorgegeben · "
              f"{len(segs)} Sprachblöcke · {len(voiced)} Szenen mit Text")
    else:
        found, near = find_threshold(src, n_sent)
        if found:
            noise, gap = found
            segs, dur = speech_segments(src, noise, gap)
            print(f"{src.name}: {dur:.2f}s · Schwelle automatisch gefunden "
                  f"({noise}, Pause ≥ {gap}s) · {len(segs)} Blöcke = {n_sent} Sätze "
                  f"in {len(voiced)} Szenen ✓")
        else:
            noise, gap, n = near
            segs, dur = speech_segments(src, noise, gap)
            print(f"{src.name}: {dur:.2f}s · keine Schwelle trifft {n_sent} Sätze genau; "
                  f"beste Näherung {n} Blöcke bei {noise}/{gap}s")

    if FIT or len(segs) != n_sent:
        if not FIT:
            print(f"  ⚠ Blöcke ({len(segs)}) ≠ Sätze ({n_sent}).")
            print("    Ursache ist fast immer eine Pause mitten in einem Satz oder zwei")
            print("    Sätze ohne Pause dazwischen. Entweder Schwelle anpassen, oder")
            print("    in FCP schieben und den FCPXML-Weg nehmen — der ist massgeblich.")
            print("    Ersatzweise jetzt: global auf die Gesamtlänge dehnen (--fit).")
        k   = dur / max(s["start"] + s["dur"] for s in scenes)
        st  = [s["start"] * k for s in scenes]
        du  = [s["dur"] * k for s in scenes]
        print(f"  → global gedehnt, Faktor {k:.3f}")
        apply(st, du)
    else:
        # jede gesprochene Szene beginnt kurz vor ihrem Sprachblock —
        # das Bild ist immer minimal vor der Stimme da, nie danach
        LEAD, st, du = 0.12, [0.0] * len(scenes), [0.0] * len(scenes)
        k = 0
        for i in voiced:                       # Szene startet an ihrem ersten Satz
            st[i] = max(0.0, segs[k][0] - LEAD)
            k += sent_of[i]
        for i in range(len(scenes)):                       # stumme Szenen einpassen
            if st[i] == 0.0 and i > 0: st[i] = None
        last = 0.0
        for i, v in enumerate(st):
            if v is None:
                nxt = next((x for x in st[i+1:] if x), dur)
                st[i] = last + (nxt - last) * 0.5
            last = st[i]
        for i in range(len(scenes)):
            du[i] = (st[i+1] if i+1 < len(scenes) else dur) - st[i]
        print(f"  → {len(voiced)} Szenen auf ihre Satzblöcke gelegt, Vorlauf {LEAD}s")
        odd = [(scenes[i]["id"], scenes[i]["dur"], du[i]) for i in range(len(scenes))
               if scenes[i]["dur"] > 0 and not 0.45 <= du[i]/scenes[i]["dur"] <= 2.4]
        if odd:
            print(f"  ⚠ {len(odd)} Szene(n) weichen stark vom Plan ab — bitte prüfen:")
            for sid, a, b in odd:
                print(f"      {sid:<18} geplant {a:>5.2f}s  →  gemessen {b:>5.2f}s")
            print("    Meist eine ungeplante Pause oder ein verschluckter Satz.")
            print("    Im Zweifel in FCP schieben und den FCPXML-Weg nehmen.")
        apply(st, du)

tot = max(s["start"] + s["dur"] for s in scenes)
print(f"\nNeue Gesamtlänge: {tot:.2f}s")
for s in scenes[:4] + scenes[-2:]:
    print(f"  {s['id']:<18} {s['start']:>6.2f}s  +{s['dur']:.2f}s")
if DRY:
    print("\n--dry: timing.json unverändert.")
else:
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\ntiming.json geschrieben → jetzt `python3 render.py`")

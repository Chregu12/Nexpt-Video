#!/usr/bin/env python3
"""
Zieht die Animation auf die AUFGENOMMENE Stimme.

Das ist der Ersatz für stundenlanges Schieben in Final Cut. Zwei Wege:

  python3 sync.py vo.wav               Wort-Zeitstempel per Whisper, Text abgleichen  (bester Audio-Weg)
  python3 sync.py vo.wav --model de    deutsch feinabgestimmt (Standard, falls vorhanden)
  python3 sync.py vo.wav --model ch    Schweizerdeutsch
  python3 sync.py vo.wav --model small generisch, klein, ohne Zusatzmodell
  python3 sync.py vo.wav --silence     nur Sprachpausen messen (ohne Whisper)
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

# ---------------------------------------------------------------- Whisper: Text abgleichen
def whisper_align(path, scenes):
    """Whisper hoert zu und gibt Wort-Zeitstempel. Wir gleichen den erkannten
    Wortstrom gegen das Drehbuch ab — dann steht fest, wo jede Szene beginnt,
    unabhaengig davon, wo der Sprecher Luft geholt hat."""
    from faster_whisper import WhisperModel
    import difflib
    # Kurzformen auf die lokal konvertierten Modelle; sonst der Name direkt.
    ALIAS = {"de":   ("asr/whisper-de-turbo",  "whisper-large-v3-turbo-german"),
             "de-l": ("asr/whisper-de-large",  "whisper-large-v3-german"),
             "ch":   ("asr/whisper-ch",        "flix-swissgerman-full")}
    want = next((sys.argv[i+1] for i, a in enumerate(sys.argv) if a == "--model"), None)
    if want is None:                      # ohne Angabe: deutsches Modell, sonst small
        want = "de" if (ROOT / ALIAS["de"][0]).exists() else "small"
    if want in ALIAS:
        mdir, label = ALIAS[want]
        if not (ROOT / mdir).exists():
            print(f"  {label} nicht vorhanden — sh asr/get-modelle.sh {want}")
            print("  weiche auf 'small' aus")
            size, label = "small", "small (generisch)"
        else:
            size = str(ROOT / mdir)
    else:
        size, label = want, want
    print(f"Whisper ({label}, CPU) hoert zu …")
    model = WhisperModel(size, device="cpu", compute_type="int8")
    segs, _ = model.transcribe(str(path), language="de",
                               word_timestamps=True, vad_filter=True)
    heard = [(w.word, w.start, w.end) for sg in segs for w in sg.words]
    norm  = lambda w: re.sub(r"[^a-z0-9\u00e4\u00f6\u00fc\u00df]", "", w.lower())

    want, bounds = [], []                       # Drehbuchwoerter + Szenengrenzen
    for i, sc in enumerate(scenes):
        vo = (sc.get("vo") or "").strip()
        if not vo or vo.startswith("("): continue
        bounds.append((i, len(want)))
        want += [norm(w) for w in vo.split() if norm(w)]

    got = [norm(w) for w, _, _ in heard]
    sm  = difflib.SequenceMatcher(a=want, b=got, autojunk=False)
    # Drehbuch-Index -> gehoerter Index, ueber die uebereinstimmenden Bloecke
    m2h = {}
    for a0, b0, n in sm.get_matching_blocks():
        for k in range(n): m2h[a0 + k] = b0 + k
    ratio = len(m2h) / max(1, len(want))
    print(f"  {len(heard)} Woerter gehoert · {len(want)} im Drehbuch · "
          f"{ratio:.0%} zugeordnet")
    if ratio < 0.55:
        print("  \u26a0 Zu wenig Deckung. Anderes Modell (--model medium) oder --silence.")
        return None

    def when(idx):                              # naechste gesicherte Zuordnung ab idx
        for k in range(idx, len(want)):
            if k in m2h: return heard[m2h[k]][1]
        return None
    starts, dur = {}, audio_len(path)
    for i, wi in bounds:
        t = when(wi)
        if t is not None: starts[i] = t
    return starts, dur, ratio

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
    if "--silence" not in sys.argv:
        try:
            r = whisper_align(src, scenes)
        except Exception as e:
            print(f"Whisper nicht verfuegbar ({type(e).__name__}: {e}) — messe Pausen"); r = None
        if r:
            starts, dur, _ = r
            LEAD = 0.12
            st = [None] * len(scenes)
            for i, t in starts.items(): st[i] = max(0.0, t - LEAD)
            if st[0] is None: st[0] = 0.0
            last = 0.0                                   # stumme Szenen mittig einpassen
            for i in range(len(scenes)):
                if st[i] is None:
                    nxt = next((x for x in st[i+1:] if x is not None), dur)
                    st[i] = last + (nxt - last) * 0.5
                st[i] = max(st[i], last + 1/FPS)         # streng monoton
                last = st[i]
            du = [(st[i+1] if i+1 < len(scenes) else dur) - st[i] for i in range(len(scenes))]
            print(f"  \u2192 {len(starts)} Szenen \u00fcber den Text verankert, Vorlauf {LEAD}s")
            odd = [(scenes[i]["id"], scenes[i]["dur"], du[i]) for i in range(len(scenes))
                   if scenes[i]["dur"] > 0 and not 0.45 <= du[i]/scenes[i]["dur"] <= 2.4]
            if odd:
                print(f"  \u26a0 {len(odd)} Szene(n) weichen stark vom Plan ab:")
                for sid, a, b in odd:
                    print(f"      {sid:<18} geplant {a:>5.2f}s  \u2192  gemessen {b:>5.2f}s")
            apply(st, du)
            tot = max(x["start"] + x["dur"] for x in scenes)
            print(f"\nNeue Gesamtl\u00e4nge: {tot:.2f}s")
            for x in scenes[:4] + scenes[-2:]:
                print(f"  {x['id']:<18} {x['start']:>6.2f}s  +{x['dur']:.2f}s")
            if DRY: print("\n--dry: timing.json unver\u00e4ndert.")
            else:
                CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
                print("\ntiming.json geschrieben \u2192 jetzt `python3 render.py`")
            sys.exit(0)

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

#!/usr/bin/env python3
"""
Scratch-Stimme aus timing.json.

Eine Wegwerf-Tonspur, um das Timing zu prüfen — nicht für den Film. Der Sprecher
muss ein Mensch sein: „Moment. Nein." lebt von trockenem Timing, das keine
Synthese trifft. Aber diese Spur macht in zwei Minuten hörbar und messbar,
welche Zeile zu lang ist.

    python3 scratchvo.py                       -> out/scratch-vo.wav
    python3 scratchvo.py --voice kerstin       andere Stimme
    python3 scratchvo.py --rate 1.08           langsamer (>1) / schneller (<1)
    python3 scratchvo.py --engine espeak       ohne Piper-Modelle
    python3 scratchvo.py --autofit             zu kurze Szenen in timing.json verlängern

Am Schluss steht der Bericht: geplant gegen gesprochen, je Szene.
"""
import json, os, re, shutil, subprocess, sys, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
arg = lambda k, d: next((sys.argv[i+1] for i, a in enumerate(sys.argv) if a == k), d)
VOICE, RATE, ENGINE = arg("--voice", "thorsten"), float(arg("--rate", "1.0")), arg("--engine", "piper")
AUTOFIT = "--autofit" in sys.argv

cfg = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
tmp = OUT / "_vo"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)

voice = None
if ENGINE == "piper":
    try:
        from piper import PiperVoice, SynthesisConfig
        m = next(ROOT.glob(f"voices/de_DE-{VOICE}-*.onnx"))
        voice = PiperVoice.load(str(m))
        syn = SynthesisConfig(length_scale=RATE)
        print(f"Piper · {m.stem} · Tempo {RATE}")
    except Exception as e:
        print(f"Piper nicht verfügbar ({e}) — espeak-ng als Rückfall"); ENGINE = "espeak"
if ENGINE != "piper":
    print(f"espeak-ng · Tempo {RATE}")

def say(text, dst):
    if voice:
        with wave.open(str(dst), "wb") as w: voice.synthesize_wav(text, w, syn)
    else:
        subprocess.run(["espeak-ng", "-v", "de", "-s", str(int(158/RATE)),
                        "-p", "38", "-a", "150", "-w", str(dst), text], check=True)
    with wave.open(str(dst)) as w: return w.getnframes() / w.getframerate()

parts, report, total = [], [], max(s["start"] + s["dur"] for s in cfg["scenes"])
for i, s in enumerate(cfg["scenes"]):
    vo = (s.get("vo") or "").strip()
    if not vo or vo.startswith("("): continue
    w = tmp / f"{i:02d}.wav"
    spoken = say(vo, w)
    parts.append((s["start"], w))
    report.append((s["id"], s["dur"], spoken))

inputs, filt = [], []
for n, (start, w) in enumerate(parts):
    inputs += ["-i", str(w)]
    filt.append(f"[{n}:a]aresample=48000,adelay={int(start*1000)}|{int(start*1000)}[d{n}]")
filt.append("".join(f"[d{n}]" for n in range(len(parts))) +
            f"amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{total},"
            f"loudnorm=I=-17:TP=-1.9:LRA=5,alimiter=limit=0.92[out]")
subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *inputs,
                "-filter_complex", ";".join(filt), "-map", "[out]",
                "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1",
                str(OUT / "scratch-vo.wav")], check=True)
shutil.rmtree(tmp)

print(f"\nout/scratch-vo.wav · {len(parts)} Zeilen · {total:.1f}s\n")
print(f"{'Szene':<18}{'geplant':>9}{'gesprochen':>12}   Befund")
over = 0
for sid, plan, spoken in report:
    d = spoken - plan
    if   d >  0.35: flag, over = f"⚠ {d:+.2f}s  zu lang", over + 1
    elif d < -0.80: flag = f"  {d:+.2f}s  viel Luft"
    else:           flag = f"  {d:+.2f}s"
    print(f"{sid:<18}{plan:>8.2f}s{spoken:>11.2f}s   {flag}")
print(f"\n{over} Zeile(n) passen nicht in ihre Szene — dort kürzen, nicht langsamer sprechen.")

if AUTOFIT and over:
    # Nur verlängern, nie kürzen: „viel Luft" ist oft Absicht — dort läuft
    # nach dem Satz noch eine Animation (Unterstrich, Stufen, Vokabelflut).
    HEAD, need = 0.35, {sid: sp - pl + 0.35 for sid, pl, sp in report if sp - pl > 0.35}
    fps = cfg["meta"]["fps"]; snap = lambda t: round(t * fps) / fps
    t = 0.0
    for sc in cfg["scenes"]:
        sc["start"] = snap(t)
        if sc["id"] in need: sc["dur"] = snap(sc["dur"] + need[sc["id"]])
        t += sc["dur"]
    (ROOT / "timing.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n--autofit: {len(need)} Szene(n) verlängert, Gesamtlänge {t:.2f}s")
    for sid, add in need.items(): print(f"    {sid:<18} +{add:.2f}s")
    print("timing.json geschrieben → `python3 render.py` und `python3 scratchvo.py`")

#!/usr/bin/env python3
"""
Scratch-Stimme aus timing.json — eine Wegwerf-Tonspur zum Prüfen des Timings.

Nicht für den Film: espeak-ng klingt wie ein Roboter. Aber sie liegt auf den
geplanten Zeiten und macht sofort hörbar, wo der Text zu lang ist. Genau dafür
sprechen Regie und Copywriter sonst eine Scratch-Spur selbst ein.

    python3 scratchvo.py        -> out/scratch-vo.wav
"""
import json, subprocess, shutil, os, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
cfg = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
tmp = OUT / "_vo"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)

parts, total = [], max(s["start"] + s["dur"] for s in cfg["scenes"])
for i, s in enumerate(cfg["scenes"]):
    vo = (s.get("vo") or "").strip()
    if not vo or vo.startswith("("): continue
    w = tmp / f"{i:02d}.wav"
    subprocess.run(["espeak-ng", "-v", "de", "-s", "158", "-p", "38", "-a", "150",
                    "-w", str(w), vo], check=True)
    parts.append((s["start"], w))

# jede Zeile an ihren geplanten Szenenbeginn legen — Stille dazwischen bleibt Stille
inputs, filt = [], []
for n, (start, w) in enumerate(parts):
    inputs += ["-i", str(w)]
    filt.append(f"[{n}:a]aresample=48000,adelay={int(start*1000)}|{int(start*1000)}[d{n}]")
mix = "".join(f"[d{n}]" for n in range(len(parts)))
filt.append(f"{mix}amix=inputs={len(parts)}:normalize=0,"
            f"apad,atrim=0:{total},alimiter=limit=0.9[out]")
subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *inputs,
                "-filter_complex", ";".join(filt), "-map", "[out]",
                "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1",
                str(OUT / "scratch-vo.wav")], check=True)
shutil.rmtree(tmp)
print(f"out/scratch-vo.wav  ·  {len(parts)} Zeilen  ·  {total:.1f}s")

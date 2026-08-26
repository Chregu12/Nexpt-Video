#!/usr/bin/env python3
"""
Scratch-Stimme mit XTTS-v2 — Alternative zu Piper.

    python3 -m venv --system-site-packages .venv-xtts
    .venv-xtts/bin/pip install "transformers==4.46.3" coqui-tts
    COQUI_TOS_AGREED=1 .venv-xtts/bin/python render/xttsvo.py

XTTS braucht ein eigenes venv mit aelterem transformers — es ist mit der
Whisper-Toolchain (transformers 5.x) nicht vertraeglich.

LIZENZ: XTTS-v2 steht unter der Coqui Public Model License und ist
NICHT fuer kommerzielle Nutzung freigegeben. Als internes Timing-Muster
brauchbar, fuer den Messefilm nicht. Piper (scratchvo.py) ist frei.

Voice Cloning: --ref stimme.wav klont eine Referenzstimme. Nur mit
Einwilligung der sprechenden Person verwenden.
"""
import json, os, subprocess, shutil, sys, wave
from pathlib import Path
import warnings; warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
arg = lambda k, d=None: next((sys.argv[i+1] for i, a in enumerate(sys.argv) if a == k), d)
SPK, REF = arg("--speaker", "Damien Black"), arg("--ref")

from TTS.api import TTS
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False)
names = tts.synthesizer.tts_model.speaker_manager.speaker_names
if not REF and SPK not in names:
    print("Stimme unbekannt. Verfuegbar:", ", ".join(names)); sys.exit(1)

cfg = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
tmp = OUT / "_xtts"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
TOT = max(s["start"] + s["dur"] for s in cfg["scenes"])

parts, report = [], []
for i, s in enumerate(cfg["scenes"]):
    vo = (s.get("vo") or "").strip()
    if not vo or vo.startswith("("): continue
    w = tmp / f"{i:02d}.wav"
    kw = {"speaker_wav": REF} if REF else {"speaker": SPK}
    tts.tts_to_file(text=vo, language="de", file_path=str(w), **kw)
    with wave.open(str(w)) as f: spoken = f.getnframes() / f.getframerate()
    parts.append((s["start"], w)); report.append((s["id"], s["dur"], spoken))
    print(f"  {s['id']:<18} {spoken:5.2f}s / {s['dur']:5.2f}s geplant", flush=True)

inputs, filt = [], []
for n, (start, w) in enumerate(parts):
    inputs += ["-i", str(w)]
    filt.append(f"[{n}:a]aresample=48000,adelay={int(start*1000)}|{int(start*1000)}[d{n}]")
filt.append("".join(f"[d{n}]" for n in range(len(parts))) +
            f"amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{TOT},"
            f"loudnorm=I=-17:TP=-1.9:LRA=5,alimiter=limit=0.92[out]")
subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *inputs,
                "-filter_complex", ";".join(filt), "-map", "[out]",
                "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1",
                str(OUT / "scratch-vo-xtts.wav")], check=True)
shutil.rmtree(tmp)
over = sum(1 for _, p, sp in report if sp - p > 0.35)
print(f"\nout/scratch-vo-xtts.wav · {len(parts)} Zeilen · Stimme: {REF or SPK}")
print(f"{over} Zeile(n) passen nicht in ihre Szene.")

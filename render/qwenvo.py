#!/usr/bin/env python3
"""
Scratch-Stimme über Qwen3-TTS — via den offiziellen HuggingFace-Space.

Lokal laeuft Qwen3-TTS hier nicht: weder transformers 5.16 noch git main
kennen den Modelltyp `qwen3_tts`. Ueber den Space geht es, auf GPU.

    export HF_TOKEN=hf_...            # ohne Token reicht die Quote fuer EINEN Aufruf
    python3 qwenvo.py                 # fester Sprecher, ueber alle Zeilen gleich
    python3 qwenvo.py --speaker Dylan
    python3 qwenvo.py --design        # Stimme aus einer Beschreibung statt Sprecherliste
    python3 qwenvo.py --size 0.6B
    python3 qwenvo.py --ref meine-stimme.wav [--reftext ../out/referenztext.txt]
                                      # eigene Stimme klonen

Qwen3-TTS steht unter Apache 2.0 und darf kommerziell verwendet werden.
Klonen NUR mit Einwilligung der sprechenden Person. Der Klon-Endpunkt
braucht neben dem Ton den EXAKTEN Wortlaut der Referenz (--reftext);
darum ist out/referenztext.txt aus dem Drehbuch gebaut.

HINWEIS: Das schickt den Drehbuchtext an einen oeffentlichen Dienst.

--design erzeugt die Stimme je Aufruf neu — sie kann zwischen den Zeilen
abweichen. Fuer eine durchgehende Sprecherstimme den festen Sprecher nehmen.
"""
import json, os, shutil, subprocess, sys, time, wave
from pathlib import Path
import warnings; warnings.filterwarnings("ignore")
from gradio_client import Client, handle_file

ROOT = Path(__file__).resolve().parent; OUT = ROOT.parent / "out"
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
arg = lambda k, d=None: next((sys.argv[i+1] for i, a in enumerate(sys.argv) if a == k), d)

SPEAKER = arg("--speaker", "Eric")
REF     = arg("--ref")
REFTXT  = arg("--reftext", str((Path(__file__).resolve().parent.parent / "out" / "referenztext.txt")))
SIZE    = arg("--size", "1.7B")
DESIGN  = "--design" in sys.argv
TOKEN   = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")

# Regieanweisung aus dem Konzept — dieselbe, die auch im Drehbuch steht.
INSTRUCT = ("Trocken, wach, leicht amuesiert. Kein Werbeton, kein Pathos. "
            "Zuegig sprechen, Pausen bewusst setzen.")
DESCRIBE = ("A dry, awake male voice with a hint of amusement. Understated and "
            "confident, never salesy, no advertising tone. Brisk pace with "
            "deliberate pauses.")

ref_text = None
if REF:
    if not Path(REF).exists(): sys.exit(f"Referenzaufnahme nicht gefunden: {REF}")
    t = Path(REFTXT)
    if not t.exists(): sys.exit(f"Referenztext nicht gefunden: {REFTXT}")
    # Kopfzeilen der Textdatei wegwerfen — der Endpunkt will nur den Wortlaut
    body = [l for l in t.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith(("REFERENZTEXT", "=", "So sprechen", "Kein Werbeton", "Punkte sind"))]
    ref_text = " ".join(body).strip()
    print(f"Klon aus {REF}\n  Referenztext: {len(ref_text.split())} Woerter")

if not TOKEN:
    print("Kein HF_TOKEN gesetzt — die anonyme Quote reicht fuer etwa einen Aufruf.")
    print("Kostenloses Token: https://huggingface.co/settings/tokens\n")

cfg = json.loads((ROOT / "timing.json").read_text(encoding="utf-8"))
TOT = max(s["start"] + s["dur"] for s in cfg["scenes"])
tmp = OUT / "_qwen"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
client = Client("Qwen/Qwen3-TTS", hf_token=TOKEN, verbose=False)

def say(text, dst, tries=4):
    for k in range(tries):
        try:
            if REF:
                r = client.predict(ref_audio=handle_file(REF), ref_text=ref_text,
                                   target_text=text, language="German",
                                   use_xvector_only=False, model_size=SIZE,
                                   api_name="/generate_voice_clone")
            elif DESIGN:
                r = client.predict(text=text, language="German",
                                   voice_description=DESCRIBE,
                                   api_name="/generate_voice_design")
            else:
                r = client.predict(text=text, language="German", speaker=SPEAKER,
                                   instruct=INSTRUCT, model_size=SIZE,
                                   api_name="/generate_custom_voice")
            src = r[0] if isinstance(r, (list, tuple)) else r
            shutil.copy(src, dst); return True
        except Exception as e:
            msg = str(e)
            if "quota" in msg.lower():
                wait = 45 * (k + 1)
                print(f"      Quote erschoepft, warte {wait}s …", flush=True)
                time.sleep(wait)
            else:
                print(f"      Fehler: {type(e).__name__} {msg[:130]}"); return False
    return False

parts, report, failed = [], [], []
for i, s in enumerate(cfg["scenes"]):
    vo = (s.get("vo") or "").strip()
    if not vo or vo.startswith("("): continue
    w = tmp / f"{i:02d}.wav"
    if not say(vo, w): failed.append(s["id"]); continue
    with wave.open(str(w)) as f: spoken = f.getnframes() / f.getframerate()
    parts.append((s["start"], w)); report.append((s["id"], s["dur"], spoken))
    print(f"  {s['id']:<18} {spoken:5.2f}s / {s['dur']:5.2f}s geplant", flush=True)

if failed:
    print(f"\n{len(failed)} Zeile(n) fehlgeschlagen: {', '.join(failed)}")
    if not parts: sys.exit("Nichts erzeugt — vermutlich fehlt HF_TOKEN.")

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
                str(OUT / ("vo-klon.wav" if REF else "scratch-vo-qwen.wav"))], check=True)
shutil.rmtree(tmp)
over = sum(1 for _, p, sp in report if sp - p > 0.35)
print(f"\nout/{'vo-klon.wav' if REF else 'scratch-vo-qwen.wav'} · {len(parts)} Zeilen · "
      f"{'Klon: ' + Path(REF).name if REF else ('Beschreibung' if DESIGN else SPEAKER + ' / ' + SIZE)}")
print(f"{over} Zeile(n) passen nicht in ihre Szene.")

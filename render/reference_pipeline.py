#!/usr/bin/env python3
"""Kompletter Referenz-zu-NEXPT-Audiopfad mit einem Befehl.

    python3 render/reference_pipeline.py "Rhythm Mischief.m4a" \
        --bpm 118 --downbeat 0 --preview

Die Referenzdatei wird nur vom Analyzer gelesen und weder kopiert noch in ein
Ausgabeverzeichnis geschrieben. Fuer die Musik koennen echte CC0-Drums oder
die prozedurale Rueckfall-Engine verwendet werden. Musik und SFX bleiben
getrennte Stems.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OUT = REPO/"out"


def run(command: list[str], env: dict | None = None) -> None:
    printable = " ".join(f'"{part}"' if " " in part else part for part in command)
    print(f"\n> {printable}", flush=True)
    subprocess.run(command, cwd=REPO, env=env, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="lokale Audio- oder Videoreferenz")
    parser.add_argument("--bpm", type=float, help="bekanntes Referenztempo")
    parser.add_argument("--downbeat", type=float, help="erste Eins der Referenz in Sekunden")
    parser.add_argument("--target-bpm", type=float, help="Tempo der neuen Musik; Standard Filmtempo")
    parser.add_argument("--profile", type=Path,
                        default=OUT/"analysis"/"reference-profile.json")
    parser.add_argument("--kit-output", type=Path, default=OUT/"reference-kit")
    parser.add_argument("--music-output", type=Path, default=OUT/"music-reference.wav")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--sound-source", choices=("auto", "samples", "procedural"),
                        default="auto",
                        help="auto nutzt VCSL, wenn die Bibliothek vorhanden ist")
    parser.add_argument("--drum-library", type=Path, default=OUT/"_vcsl")
    parser.add_argument("--download-drums", action="store_true",
                        help="CC0-VCSL-Auswahl vor dem Rendern laden/aktualisieren")
    parser.add_argument("--skip-kit", action="store_true")
    parser.add_argument("--skip-compare", action="store_true")
    parser.add_argument("--skip-sfx", action="store_true")
    parser.add_argument("--preview", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    if not source.exists():
        raise SystemExit(f"{source} fehlt")
    python = sys.executable

    analyzer = [python, str(ROOT/"reference_analyzer.py"), str(source),
                "--output", str(args.profile)]
    if args.bpm is not None:
        analyzer += ["--bpm", str(args.bpm)]
    if args.downbeat is not None:
        analyzer += ["--downbeat", str(args.downbeat)]
    run(analyzer)

    run([python, str(ROOT/"cuesheet.py")])
    if args.download_drums:
        run([python, str(ROOT/"vcsl.py")])
    if not args.skip_kit:
        synth = [python, str(ROOT/"reference_synth.py"),
                 "--profile", str(args.profile), "--output", str(args.kit_output),
                 "--sound-source", args.sound_source,
                 "--drum-library", str(args.drum_library)]
        if args.seed is not None:
            synth += ["--seed", str(args.seed)]
        run(synth)

    music = [python, str(ROOT/"music_reference.py"),
             "--profile", str(args.profile), "--output", str(args.music_output),
             "--sound-source", args.sound_source,
             "--drum-library", str(args.drum_library)]
    if args.target_bpm is not None:
        music += ["--target-bpm", str(args.target_bpm)]
    if args.seed is not None:
        music += ["--seed", str(args.seed)]
    run(music)

    if not args.skip_compare:
        compare = [python, str(ROOT/"reference_compare.py"), str(args.music_output),
                   "--profile", str(args.profile)]
        if args.target_bpm is not None:
            compare += ["--bpm", str(args.target_bpm)]
        run(compare)

    if not args.skip_sfx:
        run([python, str(ROOT/"sfx_original.py")])

    if args.preview:
        env = os.environ.copy()
        env.update({
            "MUSIC": str(args.music_output),
            "PREVIEW_WAV": "out/reference-audio-preview.wav",
            "PREVIEW_M4A": "out/reference-audio-preview.m4a",
            "PREVIEW_VIDEO": "out/NEXPT-REFERENCE-AUDIO-PREVIEW.mp4",
        })
        run(["sh", str(ROOT/"audio_preview.sh")], env=env)

    print("\nFertig:")
    print(f"  Profil: {args.profile}")
    print(f"  Musik:  {args.music_output}")
    if not args.skip_compare:
        print(f"  Messung: {OUT/'analysis'/'reference-match.json'}")
    if not args.skip_sfx:
        print(f"  SFX:    {OUT/'sfx-original.wav'}")


if __name__ == "__main__":
    main()

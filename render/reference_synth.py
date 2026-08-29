#!/usr/bin/env python3
"""Aus einem Referenzprofil ein neues, mehrstufiges Percussion-Kit rendern.

    python3 render/reference_synth.py
    python3 render/reference_synth.py --profile out/analysis/mein-profil.json

Die WAV-Dateien sind neu synthetisiert. Sie enthalten keine Ausschnitte der
Referenz und koennen deshalb getrennt von der Referenzdatei archiviert werden.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from audio_common import OUT, SR, audio_stats, peak_normalize, write_manifest, write_pcm24
from reference_sound import ReferenceSoundFactory, load_profile


VELOCITIES = (("soft", .42), ("medium", .70), ("hard", .96))
ROLES = ("low", "body", "tonal", "detail")


def render_kit(profile: dict, destination: Path, variants: int = 4,
               seed: int | None = None) -> dict:
    factory = ReferenceSoundFactory(profile, seed=seed)
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    for role in ROLES:
        for variant in range(max(1, variants)):
            for velocity_name, velocity in VELOCITIES:
                mono = factory.render(role, variant, velocity)
                # Samples bleiben mono-kompatibel. Die eigentliche Position
                # entsteht erst in music_reference.py aus dem Videokontext.
                stereo = np.column_stack((mono, mono)).astype(np.float32)
                stereo, scale = peak_normalize(stereo, -3.0)
                name = f"{role}-v{variant+1:02d}-{velocity_name}.wav"
                path = destination/name
                write_pcm24(path, stereo)
                files.append({
                    "file": name,
                    "role": role,
                    "measured_family": factory.role_family[role],
                    "variant": variant+1,
                    "velocity": velocity_name,
                    "duration_seconds": round(len(mono)/SR, 4),
                    "normalization_scale": round(scale, 5),
                    "stats": audio_stats(stereo),
                })
    manifest = {
        **factory.describe(),
        "sample_rate": SR,
        "bit_depth": 24,
        "variant_count_per_role": max(1, variants),
        "velocity_layers": [name for name, _ in VELOCITIES],
        "files": files,
    }
    write_manifest(destination/"kit.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path,
                        default=OUT/"analysis"/"reference-profile.json")
    parser.add_argument("--output", type=Path, default=OUT/"reference-kit")
    parser.add_argument("--variants", type=int, default=4)
    parser.add_argument("--seed", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    profile = load_profile(args.profile)
    manifest = render_kit(profile, args.output, args.variants, args.seed)
    print(f"{args.output} · {len(manifest['files'])} neue Samples · "
          f"Rollen {manifest['role_to_measured_family']}")


if __name__ == "__main__":
    main()

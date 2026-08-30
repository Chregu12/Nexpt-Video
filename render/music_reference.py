#!/usr/bin/env python3
"""Eigenstaendige Musik aus Referenz-Deskriptoren und dem NEXPT-Cue-Sheet.

Die Komposition verwendet weder Quell-Audio noch dessen Ereignisfolge. Das
Referenzprofil steuert Klangfarbe, Dichte, Microtiming, Dynamik und Breite;
``timing.json`` und das Cue Sheet steuern Aufbau, Pausen und Platz fuer SFX.

    python3 render/music_reference.py

Ausgaben:
    out/music-reference.wav
    out/music-reference-low.wav
    out/music-reference-body.wav
    out/music-reference-tonal.wav
    out/music-reference-detail.wav
    out/analysis/music-reference.json
"""
from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

from audio_common import (
    OUT, SR, add_short_room, apply_dip, audio_stats, cue_sheet, highpass,
    peak_normalize, place, soft_limit, timing, write_manifest, write_pcm24,
)
from reference_arrangement import SECTIONS, plan_reference_events
from reference_drums import DEFAULT_LIBRARY, create_sound_factory, match_mix_bands
from reference_sound import ReferenceSoundFactory, load_profile, profile_seed


def compose(profile: dict, total_seconds: float, bars: int, target_bpm: float,
            cues: list[dict] | None = None, seed: int | None = None,
            tail: float = 1.0, sound_factory=None
            ) -> tuple[dict[str, np.ndarray], np.ndarray, list[dict], dict]:
    plan = plan_reference_events(
        profile, total_seconds, bars, target_bpm, cues=cues, seed=seed)
    actual_seed = plan.seed
    factory = sound_factory or ReferenceSoundFactory(profile, seed=actual_seed)
    length = int(round((total_seconds+tail)*SR))
    stems = {name: np.zeros((length, 2), dtype=np.float32)
             for name in ("low", "body", "tonal", "detail")}
    events = [dict(event) for event in plan.events]
    pitch_ratios = plan.pitch_ratios

    @lru_cache(maxsize=768)
    def cached_sound(role: str, variant: int, level: int, pitch_index: int) -> np.ndarray:
        velocities = (.34, .52, .72, .94)
        ratio = pitch_ratios[pitch_index % len(pitch_ratios)] if role == "tonal" else 1.0
        return factory.render(role, variant, velocities[level], ratio)

    for event in events:
        sound = cached_sound(
            event["role"], event["variant"], event["sound_level"],
            event["pitch_variant"],
        )
        place(
            stems[event["stem"]], sound, event["time"], event["gain"],
            event["pan"],
        )

    # Halte-Beats werden nicht nur bei der Notenerzeugung vermieden. Auch
    # Ausklaenge bereits gestarteter Instrumente muessen dort verschwinden.
    envelope = np.ones(length, dtype=np.float32)
    for region in plan.halt_regions:
        apply_dip(envelope, region["time"], region["duration"], 0.0, .055, .11)

    # Starke Bild-/SFX-Cues oeffnen kurz Platz, statt mit einem weiteren
    # musikalischen Akzent um Aufmerksamkeit zu kaempfen.
    for cue in plan.cue_ducks:
        moment = float(cue["time"])
        apply_dip(envelope, max(0.0, moment-.025), .11, .70, .045, .11)

    for stem in stems.values():
        stem *= envelope[:, None]
    stems["body"] = add_short_room(stems["body"], .050)
    stems["tonal"] = add_short_room(stems["tonal"], .042)
    stems["detail"] = add_short_room(stems["detail"], .032)
    for channel in range(2):
        stems["low"][:, channel] = highpass(stems["low"][:, channel], 24.0, 2)
        stems["body"][:, channel] = highpass(stems["body"][:, channel], 38.0, 2)
        stems["tonal"][:, channel] = highpass(stems["tonal"][:, channel], 55.0, 2)
        stems["detail"][:, channel] = highpass(stems["detail"][:, channel], 95.0, 2)

    # Die Referenz liefert die Familienanteile. Sie werden in einem sicheren
    # Bereich auf die vier musikalischen Rollen uebertragen, damit ein
    # basslastiger Full-Mix nicht erneut alle Mitten verschluckt.
    family_shares = profile.get("generation_targets", {}).get("family_shares", {})
    low_share = float(family_shares.get(factory.role_family["low"], .25))
    detail_share = float(family_shares.get(factory.role_family["detail"], .18))
    role_gain = {
        "low": float(np.clip(1.08+low_share*.16, 1.10, 1.16)),
        "body": 1.15,
        "tonal": 1.35,
        "detail": float(np.clip(2.30+detail_share*2.0, 2.30, 2.52)),
    }
    for name in stems:
        stems[name] *= role_gain[name]

    master = stems["low"]+stems["body"]+stems["tonal"]+stems["detail"]
    factory_description = factory.describe()
    master_band_eq = {"applied": False}
    if factory_description.get("engine") == "real-drum-samples":
        master, master_band_eq = match_mix_bands(master, profile["mix"]["bands"])
    # Die Referenz ist ein fertig gemasterter Percussion-Track. Ohne
    # Sanfte Bus-Saettigung verbindet die Einzelschlaege. Der alte Drive 3.2
    # zerdrueckte die Transienten und liess die Summe synthetisch wirken.
    master = soft_limit(master, 3.00)
    master, scale = peak_normalize(master, -3.0)
    for name in stems:
        stems[name] *= scale
    stem_safety_scale = {}
    for name, audio in stems.items():
        stems[name], safety = peak_normalize(audio, -1.0, only_down=True)
        stem_safety_scale[name] = round(safety, 6)
    context = {
        **plan.context(),
        "tail_seconds": tail,
        "role_gain": role_gain,
        "normalization_scale": round(scale, 6),
        "stem_safety_scale": stem_safety_scale,
        "factory": factory_description,
        "master_band_eq": master_band_eq,
    }
    return stems, master, events, context


def render_music(profile: dict, output: Path, manifest_path: Path,
                 bars: int | None = None, target_bpm: float | None = None,
                 seed: int | None = None, write_stems: bool = True,
                 use_cues: bool = True, sound_source: str = "auto",
                 drum_library: Path | str = DEFAULT_LIBRARY) -> dict:
    cfg, film_total = timing()
    cue_data = cue_sheet() if use_cues else {"cues": [], "film": {}}
    bpm = float(target_bpm or cue_data.get("film", {}).get("bpm") or
                profile["tempo"]["bpm"])
    if bars is None:
        bars = int(round(film_total/(240.0/bpm)))
        total_seconds = film_total
    else:
        total_seconds = bars*(240.0/bpm)
    actual_seed = profile_seed(profile, 118) if seed is None else int(seed)
    factory = create_sound_factory(
        profile, sound_source=sound_source, library=drum_library, seed=actual_seed)
    stems, master, events, context = compose(
        profile, total_seconds, bars, bpm, cue_data.get("cues", []),
        seed=actual_seed, sound_factory=factory)

    output.parent.mkdir(parents=True, exist_ok=True)
    write_pcm24(output, master)
    files = {"master": output.name}
    if write_stems:
        for name, audio in stems.items():
            path = output.with_name(f"{output.stem}-{name}{output.suffix}")
            write_pcm24(path, audio)
            files[name] = path.name

    manifest = {
        "files": files,
        "sample_rate": SR,
        "bit_depth": 24,
        "duration_seconds": round(len(master)/SR, 3),
        "reference_profile": {
            "source_file_name": profile["source"].get("file_name"),
            "source_sha256": profile["source"].get("sha256"),
            "profile_schema_version": profile.get("schema_version"),
        },
        "source": (
            "Neue profilgesteuerte Musik aus echten CC0-Drum-Aufnahmen. "
            "Keine Audiodaten und keine Ereignisfolge der Referenz verwendet."
            if context["factory"].get("engine") == "real-drum-samples" else
            "Neue profilgesteuerte Synthese. Keine Quell-Samples und keine "
            "Ereignisfolge der Referenz verwendet."
        ),
        "composition": context,
        "sections": [{"start_bar": a+1, "end_bar": b, "name": name,
                      "energy_from": low, "energy_to": high}
                     for a, b, name, low, high in SECTIONS] if bars == 68 else [],
        "event_count": len(events),
        "events_by_role": dict(Counter(row["role"] for row in events)),
        "stats": {"master": audio_stats(master),
                  **{name: audio_stats(audio) for name, audio in stems.items()}},
        "events": events,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path,
                        default=OUT/"analysis"/"reference-profile.json")
    parser.add_argument("--output", type=Path, default=OUT/"music-reference.wav")
    parser.add_argument("--manifest", type=Path,
                        default=OUT/"analysis"/"music-reference.json")
    parser.add_argument("--target-bpm", type=float)
    parser.add_argument("--bars", type=int, help="Test-/Kurzfassung; Standard ist der Film")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--sound-source", choices=("auto", "samples", "procedural"),
                        default="auto",
                        help="auto nutzt echte Drums, wenn render/vcsl.py geladen wurde")
    parser.add_argument("--drum-library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--no-stems", action="store_true")
    parser.add_argument("--without-cues", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    profile = load_profile(args.profile)
    manifest = render_music(
        profile, args.output, args.manifest, bars=args.bars,
        target_bpm=args.target_bpm, seed=args.seed,
        write_stems=not args.no_stems, use_cues=not args.without_cues,
        sound_source=args.sound_source, drum_library=args.drum_library,
    )
    print(f"{args.output} · {manifest['event_count']} neue Ereignisse · "
          f"{manifest['duration_seconds']:.3f}s")
    print(manifest["stats"])


if __name__ == "__main__":
    main()

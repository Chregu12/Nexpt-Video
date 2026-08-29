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
from reference_sound import ReferenceSoundFactory, load_profile, profile_seed


# Derselbe dramaturgische Bogen wie im Film, aber die Ereignisse und Klaenge
# werden neu aus dem Profil erzeugt. Ein Wert unter .03 bedeutet echte Pause.
SECTIONS = (
    (0, 4, "intro", .16, .28),
    (4, 7, "promise", .38, .54),
    (7, 9, "pullback", .08, .15),
    (9, 19, "groove-a", .43, .68),
    (19, 21, "breath", .24, .36),
    (21, 27, "build-a", .50, .79),
    (27, 29, "silence", .00, .01),
    (29, 35, "reset", .29, .56),
    (35, 42, "build-b", .54, .84),
    (42, 49, "climax", .82, 1.00),
    (49, 51, "drop", .05, .10),
    (51, 58, "groove-b", .40, .72),
    (58, 59, "silence", .00, .01),
    (59, 67, "finale", .58, 1.00),
    (67, 68, "final-hit", 1.00, 1.00),
)


def section_at(bar: int, bars: int) -> tuple[str, float]:
    if bars == 68:
        for start, end, name, low, high in SECTIONS:
            if start <= bar < end:
                position = 0.0 if end-start <= 1 else (bar-start)/(end-start-1)
                return name, low+(high-low)*position
    # Kurze Test- und Exportvarianten erhalten einen einfachen eigenen Bogen.
    position = bar/max(1, bars-1)
    energy = .22+.58*np.sin(np.pi*position)**1.2
    return "short-form", float(energy)


def choose_positions(rng: np.random.Generator, count: int, weights: np.ndarray,
                     mandatory: tuple[int, ...] = ()) -> list[int]:
    count = int(np.clip(count, 0, 16))
    chosen = list(dict.fromkeys(position % 16 for position in mandatory))[:count]
    remaining = count-len(chosen)
    if remaining <= 0:
        return sorted(chosen)
    available = np.array([position for position in range(16) if position not in chosen])
    probabilities = weights[available].astype(float)
    probabilities /= probabilities.sum()
    selected = rng.choice(available, size=min(remaining, len(available)),
                          replace=False, p=probabilities)
    return sorted(chosen+[int(value) for value in selected])


def inside_regions(moment: float, regions: list[tuple[float, float]], margin: float = 0.0) -> bool:
    return any(start-margin <= moment <= start+duration+margin for start, duration in regions)


def near_strong_cue(moment: float, cues: list[dict], distance: float = .065) -> bool:
    return any(abs(moment-float(cue["t"])) <= distance for cue in cues)


def compose(profile: dict, total_seconds: float, bars: int, target_bpm: float,
            cues: list[dict] | None = None, seed: int | None = None,
            tail: float = 1.0) -> tuple[dict[str, np.ndarray], np.ndarray, list[dict], dict]:
    cues = sorted(cues or [], key=lambda row: float(row["t"]))
    halts = [(float(row["t"]), max(.20, float(row.get("dauer", .4))))
             for row in cues if row.get("art") == "halt"]
    strong = [row for row in cues if row.get("art") != "halt" and
              float(row.get("staerke", 0.0)) >= .82]
    actual_seed = profile_seed(profile, 118) if seed is None else int(seed)
    rng = np.random.default_rng(actual_seed)
    factory = ReferenceSoundFactory(profile, seed=actual_seed)

    beat = 60.0/target_bpm
    sixteenth = beat/4.0
    bar_duration = beat*4.0
    length = int(round((total_seconds+tail)*SR))
    stems = {name: np.zeros((length, 2), dtype=np.float32)
             for name in ("low", "body", "detail")}
    events: list[dict] = []

    measured_density = float(profile.get("generation_targets", {}).get("events_per_bar", 7.0))
    density = float(np.clip(measured_density, 4.0, 12.0))
    width_ratio = 10**(float(profile["mix"].get("side_mid_db", -15.0))/20.0)
    body_width = float(np.clip(.14+width_ratio*.60, .18, .32))
    detail_width = float(np.clip(.17+width_ratio*.60, .22, .34))
    role_weights = {role: factory.position_weights(role)
                    for role in ("low", "body", "tonal", "detail")}

    @lru_cache(maxsize=192)
    def cached_sound(role: str, variant: int, level: int, pitch_index: int) -> np.ndarray:
        velocities = (.34, .52, .72, .94)
        ratios = (1.0, 2**(3/12), 2**(5/12), 2**(7/12))
        return factory.render(role, variant, velocities[level], ratios[pitch_index])

    def add_event(role: str, stem_name: str, bar: int, position: int,
                  energy: float, phrase: int, pitch_index: int = 0,
                  forced_gain: float = 1.0) -> None:
        grid_time = bar*bar_duration+position*sixteenth
        offset, spread, measured_strength = factory.groove(position)
        # Die systematische Referenzbewegung bleibt, wird aber abgeschwaecht;
        # die neue Aufnahme erhaelt eine eigene korrelierte Phrase-Drift.
        phrase_drift = (phrase-1.5)*.0011
        human = np.clip(offset*.68+rng.normal(0.0, spread*.22)+phrase_drift, -.028, .028)
        moment = grid_time+human
        if moment < 0 or moment > total_seconds or inside_regions(moment, halts, .045):
            return
        cue_collision = near_strong_cue(moment, strong)
        if role == "detail" and cue_collision:
            return
        velocity = np.clip((.28+.62*measured_strength)*(.58+.52*energy), .12, 1.0)
        gain = float(velocity*forced_gain*(.72 if cue_collision else 1.0))
        level = min(3, max(0, int(velocity*4)))
        variant = int((bar*5+position*3+phrase+pitch_index) % 4)
        sound = cached_sound(role, variant, level, pitch_index)

        if role == "low":
            pan = .5
        else:
            sign = -1.0 if (bar+position+variant) % 2 else 1.0
            spread_pan = detail_width if role == "detail" else body_width
            pan = float(np.clip(.5+sign*spread_pan*(.45+.45*rng.random()), .06, .94))
        place(stems[stem_name], sound, moment, gain, pan)
        events.append({
            "bar": bar+1, "position": position, "time": round(moment, 4),
            "role": role, "stem": stem_name, "gain": round(gain, 3),
            "pan": round(pan, 3), "grid_offset_ms": round(human*1000, 2),
            "pitch_variant": pitch_index,
        })

    for bar in range(bars):
        section, energy = section_at(bar, bars)
        phrase = bar % 4
        if energy < .025:
            continue
        if section == "final-hit":
            add_event("low", "low", bar, 0, 1.0, phrase, forced_gain=1.15)
            add_event("body", "body", bar, 0, 1.0, phrase, forced_gain=1.05)
            add_event("tonal", "body", bar, 0, 1.0, phrase, 0, .92)
            add_event("detail", "detail", bar, 0, 1.0, phrase, forced_gain=.72)
            continue

        target = max(1, int(round(density*(.42+.70*energy))))
        low_count = 0 if energy < .12 else max(1, int(round(target*(.16+.06*energy))))
        body_count = max(1, int(round(target*(.30+.05*energy))))
        tonal_count = 0 if energy < .20 else max(1, int(round(target*(.18+.04*energy))))
        detail_count = max(0, target-low_count-body_count-tonal_count)

        low_mandatory = (0,) if energy >= .34 or phrase == 0 else ()
        body_mandatory = (12,) if energy >= .64 and phrase in {1, 3} else ()
        low_positions = choose_positions(rng, low_count, role_weights["low"], low_mandatory)
        body_positions = choose_positions(rng, body_count, np.roll(role_weights["body"], phrase),
                                          body_mandatory)
        tonal_positions = choose_positions(rng, tonal_count,
                                           np.roll(role_weights["tonal"], (phrase*3) % 16))
        detail_positions = choose_positions(rng, detail_count,
                                            np.roll(role_weights["detail"], bar % 3))

        for position in low_positions:
            add_event("low", "low", bar, position, energy, phrase,
                      pitch_index=0)
        for position in body_positions:
            add_event("body", "body", bar, position, energy, phrase)
        for index, position in enumerate(tonal_positions):
            # Vier eigene Tonhoehen, als kurze perkussive Antwort. Es wird
            # keine Tonfolge der Referenz gelesen oder wiederholt.
            pitch_index = (bar+phrase+index*2) % 4
            add_event("tonal", "body", bar, position, energy, phrase, pitch_index, .72)
        for position in detail_positions:
            add_event("detail", "detail", bar, position, energy, phrase,
                      forced_gain=.68+.18*energy)

    # Halte-Beats werden nicht nur bei der Notenerzeugung vermieden. Auch
    # Ausklaenge bereits gestarteter Instrumente muessen dort verschwinden.
    envelope = np.ones(length, dtype=np.float32)
    for start, duration in halts:
        apply_dip(envelope, start, duration, 0.0, .055, .11)

    # Starke Bild-/SFX-Cues oeffnen kurz Platz, statt mit einem weiteren
    # musikalischen Akzent um Aufmerksamkeit zu kaempfen.
    cue_ducks = []
    last = -99.0
    for cue in strong:
        moment = float(cue["t"])
        if moment-last < .42 or inside_regions(moment, halts):
            continue
        apply_dip(envelope, max(0.0, moment-.025), .11, .70, .045, .11)
        cue_ducks.append({"time": round(moment, 4), "art": cue.get("art"),
                          "scene": cue.get("szene")})
        last = moment

    for stem in stems.values():
        stem *= envelope[:, None]
    stems["body"] = add_short_room(stems["body"], .050)
    stems["detail"] = add_short_room(stems["detail"], .032)
    for channel in range(2):
        stems["low"][:, channel] = highpass(stems["low"][:, channel], 24.0, 2)
        stems["body"][:, channel] = highpass(stems["body"][:, channel], 38.0, 2)
        stems["detail"][:, channel] = highpass(stems["detail"][:, channel], 95.0, 2)

    # Die Referenz liefert die Familienanteile. Sie werden in einem sicheren
    # Bereich auf die drei musikalischen Rollen uebertragen, damit ein
    # basslastiger Full-Mix nicht erneut alle Mitten verschluckt.
    family_shares = profile.get("generation_targets", {}).get("family_shares", {})
    low_share = float(family_shares.get(factory.role_family["low"], .25))
    detail_share = float(family_shares.get(factory.role_family["detail"], .18))
    role_gain = {
        "low": float(np.clip(1.05+low_share*.25, 1.08, 1.18)),
        "body": 1.00,
        "detail": float(np.clip(1.78+detail_share*1.60, 1.80, 1.98)),
    }
    for name in stems:
        stems[name] *= role_gain[name]

    master = stems["low"]+stems["body"]+stems["detail"]
    # Die Referenz ist ein fertig gemasterter Percussion-Track. Ohne
    # Bus-Saettigung haetten die neuen Einzelschlaege rund 24 dB Crest-Faktor
    # und waeren trotz korrektem Peak zu leise. Drive 3.2 bringt die
    # Transienten in den gemessenen Bereich, ohne die Abschnittsdynamik zu
    # nivellieren.
    master = soft_limit(master, 3.20)
    master, scale = peak_normalize(master, -3.0)
    for name in stems:
        stems[name] *= scale
    context = {
        "seed": actual_seed,
        "target_bpm": target_bpm,
        "bars": bars,
        "tail_seconds": tail,
        "cue_ducks": cue_ducks,
        "halt_regions": [{"time": round(start, 4), "duration": round(duration, 4)}
                         for start, duration in halts],
        "role_gain": role_gain,
        "normalization_scale": round(scale, 6),
        "factory": factory.describe(),
    }
    return stems, master, events, context


def render_music(profile: dict, output: Path, manifest_path: Path,
                 bars: int | None = None, target_bpm: float | None = None,
                 seed: int | None = None, write_stems: bool = True,
                 use_cues: bool = True) -> dict:
    cfg, film_total = timing()
    cue_data = cue_sheet() if use_cues else {"cues": [], "film": {}}
    bpm = float(target_bpm or cue_data.get("film", {}).get("bpm") or
                profile["tempo"]["bpm"])
    if bars is None:
        bars = int(round(film_total/(240.0/bpm)))
        total_seconds = film_total
    else:
        total_seconds = bars*(240.0/bpm)
    stems, master, events, context = compose(
        profile, total_seconds, bars, bpm, cue_data.get("cues", []), seed=seed)

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
        "source": ("Neue profilgesteuerte Synthese. Keine Quell-Samples und keine "
                   "Ereignisfolge der Referenz verwendet."),
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
    )
    print(f"{args.output} · {manifest['event_count']} neue Ereignisse · "
          f"{manifest['duration_seconds']:.3f}s")
    print(manifest["stats"])


if __name__ == "__main__":
    main()

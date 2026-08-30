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
from reference_rhythm import LearnedRhythmGenerator
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


def section_context_at(bar: int, bars: int) -> tuple[str, float, int]:
    if bars == 68:
        for start, end, name, low, high in SECTIONS:
            if start <= bar < end:
                position = 0.0 if end-start <= 1 else (bar-start)/(end-start-1)
                return name, low+(high-low)*position, start
    # Kurze Test- und Exportvarianten erhalten einen einfachen eigenen Bogen.
    position = bar/max(1, bars-1)
    energy = .22+.58*np.sin(np.pi*position)**1.2
    return "short-form", float(energy), 0


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
    rhythm = LearnedRhythmGenerator(profile, seed=actual_seed)

    beat = 60.0/target_bpm
    sixteenth = beat/4.0
    bar_duration = beat*4.0
    length = int(round((total_seconds+tail)*SR))
    stems = {name: np.zeros((length, 2), dtype=np.float32)
             for name in ("low", "body", "tonal", "detail")}
    events: list[dict] = []

    width_ratio = 10**(float(profile["mix"].get("side_mid_db", -15.0))/20.0)
    body_width = float(np.clip(.20+width_ratio*.85, .28, .42))
    detail_width = float(np.clip(.24+width_ratio*.85, .32, .46))
    pitch_ratios = rhythm.pitch_ratios()

    @lru_cache(maxsize=768)
    def cached_sound(role: str, variant: int, level: int, pitch_index: int) -> np.ndarray:
        velocities = (.34, .52, .72, .94)
        ratio = pitch_ratios[pitch_index % len(pitch_ratios)] if role == "tonal" else 1.0
        return factory.render(role, variant, velocities[level], ratio)

    def add_event(role: str, stem_name: str, bar: int, position: int,
                  energy: float, phrase: int, pitch_index: int = 0,
                  forced_gain: float = 1.0) -> None:
        grid_time = bar*bar_duration+position*sixteenth
        offset, spread, measured_strength = rhythm.performance(role, bar, position)
        # Die gelernte systematische Bewegung bleibt erhalten; eine kleine
        # korrelierte Phrase-Drift verhindert starres Quantisieren.
        phrase_drift = (phrase-1.5)*.0011
        human = np.clip(offset*.82+rng.normal(0.0, spread*.18)+phrase_drift, -.028, .028)
        moment = grid_time+human
        if moment < 0 or moment > total_seconds or inside_regions(moment, halts, .045):
            return
        cue_collision = near_strong_cue(moment, strong)
        if role == "detail" and cue_collision:
            return
        velocity = np.clip((.28+.62*measured_strength)*(.58+.52*energy), .12, 1.0)
        gain = float(velocity*forced_gain*(.72 if cue_collision else 1.0))
        level = min(3, max(0, int(velocity*4)))
        variant = int((bar*5+position*3+phrase+pitch_index) % 12)
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
        section, energy, section_start = section_context_at(bar, bars)
        section_bar = bar-section_start
        phrase = bar % 4
        if energy < .025:
            continue
        if section == "final-hit":
            add_event("low", "low", bar, 0, 1.0, phrase, forced_gain=1.15)
            add_event("body", "body", bar, 0, 1.0, phrase, forced_gain=1.05)
            add_event("tonal", "tonal", bar, 0, 1.0, phrase, 0, .92)
            add_event("detail", "detail", bar, 0, 1.0, phrase, forced_gain=.72)
            continue

        # Ein Motivkern wird pro Abschnitt gelernt und nach vier Takten mit
        # kleinen Variationen wiederholt. Dadurch entsteht dieselbe Art von
        # Groove-Kohärenz wie in der Referenz, aber keine kopierte Sequenz.
        occupied: set[int] = set()
        low_positions = rhythm.positions(
            "low", bar, section, section_bar, energy, occupied)
        occupied.update(low_positions)
        tonal_positions = rhythm.positions(
            "tonal", bar, section, section_bar, energy, occupied)
        occupied.update(tonal_positions)
        body_positions = rhythm.positions(
            "body", bar, section, section_bar, energy, occupied)
        occupied.update(body_positions)
        detail_positions = rhythm.positions(
            "detail", bar, section, section_bar, energy, occupied)

        for position in low_positions:
            add_event("low", "low", bar, position, energy, phrase,
                      pitch_index=0)
        for position in body_positions:
            add_event("body", "body", bar, position, energy, phrase)
        for index, position in enumerate(tonal_positions):
            # Die Tonklassenabstaende stammen aus einer gewichteten Sprache,
            # nicht aus der Tonfolge der Referenz.
            pitch_index = (bar+phrase+index*2) % len(pitch_ratios)
            add_event("tonal", "tonal", bar, position, energy, phrase, pitch_index, .72)
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
        "seed": actual_seed,
        "target_bpm": target_bpm,
        "bars": bars,
        "tail_seconds": tail,
        "cue_ducks": cue_ducks,
        "halt_regions": [{"time": round(start, 4), "duration": round(duration, 4)}
                         for start, duration in halts],
        "role_gain": role_gain,
        "normalization_scale": round(scale, 6),
        "stem_safety_scale": stem_safety_scale,
        "factory": factory.describe(),
        "rhythm": {
            "source_events_per_bar": rhythm.model.get("events_per_bar"),
            "source_four_bar_repeat_jaccard": rhythm.model.get("four_bar_repeat_jaccard"),
            "tonal_pitch_ratios": [round(value, 6) for value in pitch_ratios],
            "principle": ("Neu generierte Vier-Takt-Motive mit kontrollierten Variationen; "
                          "keine Referenzsequenz kopiert."),
        },
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

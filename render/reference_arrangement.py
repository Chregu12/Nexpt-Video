#!/usr/bin/env python3
"""Pure event planning shared by the local renderer and GarageBand export.

This module deliberately produces no sound.  It turns a reference profile,
the NEXPT dramatic arc and the cue sheet into a new sequence of musical
events.  Both :mod:`music_reference` and ``garageband/compose.py`` consume
that sequence, so a listening preview and the GarageBand score cannot drift
into two different compositions.

The input profile contains statistical descriptors only.  No source sample,
stem, waveform or original event sequence is copied into the plan.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from reference_rhythm import LearnedRhythmGenerator
from reference_sound import profile_seed


ROLES = ("low", "body", "tonal", "detail")

# One musical arc for every renderer.  Values below .025 are real rests.
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


@dataclass(frozen=True)
class ArrangementPlan:
    events: tuple[dict, ...]
    seed: int
    bpm: float
    bars: int
    halt_regions: tuple[dict, ...]
    cue_ducks: tuple[dict, ...]
    pitch_ratios: tuple[float, ...]
    source_events_per_bar: float | None
    source_four_bar_repeat_jaccard: float | None

    def context(self) -> dict:
        return {
            "seed": self.seed,
            "target_bpm": self.bpm,
            "bars": self.bars,
            "cue_ducks": list(self.cue_ducks),
            "halt_regions": list(self.halt_regions),
            "rhythm": {
                "source_events_per_bar": self.source_events_per_bar,
                "source_four_bar_repeat_jaccard": self.source_four_bar_repeat_jaccard,
                "tonal_pitch_ratios": [round(value, 6) for value in self.pitch_ratios],
                "principle": (
                    "Neu generierte Vier-Takt-Motive mit kontrollierten Variationen; "
                    "keine Referenzsequenz kopiert."
                ),
            },
        }


def section_context_at(bar: int, bars: int) -> tuple[str, float, int]:
    if bars == 68:
        for start, end, name, low, high in SECTIONS:
            if start <= bar < end:
                position = 0.0 if end-start <= 1 else (bar-start)/(end-start-1)
                return name, low+(high-low)*position, start
    # Short tests and alternate edits receive a self-contained arc.
    position = bar/max(1, bars-1)
    energy = .22+.58*np.sin(np.pi*position)**1.2
    return "short-form", float(energy), 0


def inside_regions(moment: float, regions: list[tuple[float, float]],
                   margin: float = 0.0) -> bool:
    return any(start-margin <= moment <= start+duration+margin
               for start, duration in regions)


def near_strong_cue(moment: float, cues: list[dict], distance: float = .065) -> bool:
    return any(abs(moment-float(cue["t"])) <= distance for cue in cues)


def plan_reference_events(
    profile: dict,
    total_seconds: float,
    bars: int,
    target_bpm: float,
    cues: list[dict] | None = None,
    seed: int | None = None,
) -> ArrangementPlan:
    """Create a deterministic, original performance plan from descriptors."""
    if bars <= 0:
        raise ValueError("bars must be positive")
    if not 20 <= float(target_bpm) <= 300:
        raise ValueError("target_bpm must be between 20 and 300")

    cues = sorted(cues or [], key=lambda row: float(row["t"]))
    halts = [(float(row["t"]), max(.20, float(row.get("dauer", .4))))
             for row in cues if row.get("art") == "halt"]
    strong = [row for row in cues if row.get("art") != "halt" and
              float(row.get("staerke", 0.0)) >= .82]
    actual_seed = profile_seed(profile, 118) if seed is None else int(seed)
    rng = np.random.default_rng(actual_seed)
    rhythm = LearnedRhythmGenerator(profile, seed=actual_seed)

    beat = 60.0/target_bpm
    sixteenth = beat/4.0
    bar_duration = beat*4.0
    pitch_ratios = rhythm.pitch_ratios()
    events: list[dict] = []

    def add_event(role: str, bar: int, position: int, energy: float,
                  phrase: int, section: str, pitch_index: int = 0,
                  forced_gain: float = 1.0) -> None:
        grid_time = bar*bar_duration+position*sixteenth
        offset, spread, measured_strength = rhythm.performance(role, bar, position)
        phrase_drift = (phrase-1.5)*.0011
        human = float(np.clip(
            offset*.82+rng.normal(0.0, spread*.18)+phrase_drift,
            -.028, .028,
        ))
        moment = grid_time+human
        if moment < 0 or moment > total_seconds or inside_regions(moment, halts, .045):
            return
        cue_collision = near_strong_cue(moment, strong)
        if role == "detail" and cue_collision:
            return
        performance_velocity = float(np.clip(
            (.28+.62*measured_strength)*(.58+.52*energy), .12, 1.0))
        gain = float(performance_velocity*forced_gain*(.72 if cue_collision else 1.0))
        sound_level = min(3, max(0, int(performance_velocity*4)))
        variant = int((bar*5+position*3+phrase+pitch_index) % 12)

        if role == "low":
            pan = .5
        else:
            width_ratio = 10**(float(profile.get("mix", {}).get(
                "side_mid_db", -15.0))/20.0)
            body_width = float(np.clip(.20+width_ratio*.85, .28, .42))
            detail_width = float(np.clip(.24+width_ratio*.85, .32, .46))
            sign = -1.0 if (bar+position+variant) % 2 else 1.0
            spread_pan = detail_width if role == "detail" else body_width
            pan = float(np.clip(
                .5+sign*spread_pan*(.45+.45*rng.random()), .06, .94))

        events.append({
            "bar": bar+1,
            "bar_index": bar,
            "position": position,
            "time": round(moment, 5),
            "grid_time": round(grid_time, 5),
            "role": role,
            "stem": role,
            "section": section,
            "energy": round(float(energy), 4),
            "performance_velocity": round(performance_velocity, 5),
            "gain": round(gain, 5),
            "pan": round(pan, 5),
            "grid_offset_ms": round(human*1000, 3),
            "pitch_variant": pitch_index,
            "variant": variant,
            "sound_level": sound_level,
            "cue_ducked": cue_collision,
        })

    for bar in range(bars):
        section, energy, section_start = section_context_at(bar, bars)
        section_bar = bar-section_start
        phrase = bar % 4
        if energy < .025:
            continue
        if section == "final-hit":
            add_event("low", bar, 0, 1.0, phrase, section,
                      forced_gain=1.15)
            add_event("body", bar, 0, 1.0, phrase, section,
                      forced_gain=1.05)
            add_event("tonal", bar, 0, 1.0, phrase, section, 0, .92)
            add_event("detail", bar, 0, 1.0, phrase, section,
                      forced_gain=.72)
            continue

        # A shared occupied set keeps the four roles readable.  The final hit
        # above is intentionally layered and is the sole exception.
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
            add_event("low", bar, position, energy, phrase, section)
        for position in body_positions:
            add_event("body", bar, position, energy, phrase, section)
        for index, position in enumerate(tonal_positions):
            pitch_index = (bar+phrase+index*2) % len(pitch_ratios)
            add_event("tonal", bar, position, energy, phrase, section,
                      pitch_index, .72)
        for position in detail_positions:
            add_event("detail", bar, position, energy, phrase, section,
                      forced_gain=.68+.18*energy)

    cue_ducks: list[dict] = []
    last = -99.0
    for cue in strong:
        moment = float(cue["t"])
        if moment-last < .42 or inside_regions(moment, halts):
            continue
        cue_ducks.append({
            "time": round(moment, 4),
            "art": cue.get("art"),
            "scene": cue.get("szene"),
        })
        last = moment

    return ArrangementPlan(
        events=tuple(events),
        seed=actual_seed,
        bpm=float(target_bpm),
        bars=int(bars),
        halt_regions=tuple(
            {"time": round(start, 4), "duration": round(duration, 4)}
            for start, duration in halts
        ),
        cue_ducks=tuple(cue_ducks),
        pitch_ratios=tuple(pitch_ratios),
        source_events_per_bar=rhythm.model.get("events_per_bar"),
        source_four_bar_repeat_jaccard=rhythm.model.get(
            "four_bar_repeat_jaccard"),
    )

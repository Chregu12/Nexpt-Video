#!/usr/bin/env python3
"""Rhythmische Grammatik aus Referenzereignissen lernen und neu ausspielen.

Das Modell speichert keine Audioausschnitte und keine komplette Ereignisfolge.
Es verdichtet die Referenz auf Rollen, Vier-Takt-Phasen, Schrittwahrscheinlich-
keiten, Akzente und Microtiming. Der Generator baut daraus wiederholbare neue
Motive mit kontrollierten Variationen statt jeden Takt neu auszuwuerfeln.
"""
from __future__ import annotations

import hashlib
from collections import Counter

import numpy as np


ROLES = ("low", "body", "tonal", "detail")
FAMILY_TO_ROLE = {
    "sub": "low",
    "bass": "low",
    "body": "body",
    "click": "body",
    "tonal": "tonal",
    "tick": "detail",
    "air": "detail",
    "noise": "detail",
}


def family_role(family: str) -> str:
    return FAMILY_TO_ROLE.get(str(family), "detail")


def _percentiles(values: list[float], fallback: float = 0.0) -> dict:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return {"p10": round(fallback, 4), "median": round(fallback, 4),
                "p90": round(fallback, 4)}
    p10, median, p90 = np.percentile(finite, (10, 50, 90))
    return {"p10": round(float(p10), 4), "median": round(float(median), 4),
            "p90": round(float(p90), 4)}


def _lag_jaccard(pattern: np.ndarray, lag: int) -> float:
    if len(pattern) <= lag:
        return 0.0
    scores = []
    active = pattern > 0
    for first, second in zip(active[:-lag], active[lag:]):
        union = int(np.logical_or(first, second).sum())
        intersection = int(np.logical_and(first, second).sum())
        scores.append(intersection/union if union else 1.0)
    return float(np.mean(scores)) if scores else 0.0


def _pitch_language(events: list[dict]) -> dict:
    """Robuste Tonklassenintervalle statt einer Referenzmelodie speichern."""
    weighted: Counter[int] = Counter()
    for event in events:
        if family_role(event.get("family", "")) != "tonal":
            continue
        frequency = float(event.get("dominant_hz", 0.0))
        strength = float(event.get("strength", 0.0))
        if not 180.0 <= frequency <= 4200.0 or strength < 0.12:
            continue
        midi = int(round(69+12*np.log2(frequency/440.0)))
        weighted[midi] += max(1, int(round(strength*10)))
    if not weighted:
        return {"root_midi": 60, "intervals_semitones": [0, 3, 5, 7],
                "pitch_ratios": [1.0, 1.189207, 1.33484, 1.498307]}

    root = weighted.most_common(1)[0][0]
    intervals: Counter[int] = Counter()
    for midi, weight in weighted.items():
        interval = (midi-root) % 12
        if interval > 6:
            interval -= 12
        intervals[interval] += weight
    chosen = [0]
    for interval, _ in intervals.most_common():
        if interval not in chosen:
            chosen.append(int(interval))
        if len(chosen) == 5:
            break
    fallbacks = (3, 5, 7, -2)
    for interval in fallbacks:
        if len(chosen) == 5:
            break
        if interval not in chosen:
            chosen.append(interval)
    return {
        "root_midi": int(root),
        "intervals_semitones": chosen,
        "pitch_ratios": [round(float(2**(interval/12)), 6) for interval in chosen],
        "principle": "Nur gewichtete Tonklassenintervalle; keine Tonfolge der Referenz.",
    }


def build_rhythm_model(events: list[dict], bars: int) -> dict:
    """Rollen- und phasenbezogene Rhythmusstatistik fuer vier Takte bauen."""
    bars = max(1, int(bars))
    role_index = {role: index for index, role in enumerate(ROLES)}
    activation = np.zeros((bars, len(ROLES), 16), dtype=np.float32)
    strength = np.zeros_like(activation)
    offsets: dict[tuple[int, int, int], list[float]] = {}

    for event in events:
        grid_index = int(event.get("grid_index", -1))
        bar = grid_index//16
        if not 0 <= bar < bars:
            continue
        position = grid_index % 16
        role = family_role(event.get("family", ""))
        index = role_index[role]
        value = float(np.clip(event.get("strength", 0.5), 0.04, 1.0))
        activation[bar, index, position] = 1.0
        strength[bar, index, position] = max(strength[bar, index, position], value)
        offsets.setdefault((bar % 4, index, position), []).append(
            float(event.get("grid_offset_ms", 0.0)))

    phase_bar_counts = [sum(1 for bar in range(bars) if bar % 4 == phase)
                        for phase in range(4)]
    role_rows = {}
    for index, role in enumerate(ROLES):
        global_probability = activation[:, index].mean(axis=0)
        active_strengths = strength[:, index][strength[:, index] > 0]
        role_default_strength = float(np.median(active_strengths)) \
            if len(active_strengths) else 0.55
        phase_probability = []
        phase_strength = []
        phase_offset = []
        phase_spread = []
        for phase in range(4):
            rows = np.arange(phase, bars, 4)
            count = max(1, phase_bar_counts[phase])
            hits = activation[rows, index].sum(axis=0) if len(rows) else np.zeros(16)
            # Zwei virtuelle Beobachtungen mit globalem Prior stabilisieren
            # seltene Rollen, ohne ihre charakteristischen Positionen zu glatten.
            probability = (hits+2.0*global_probability)/(count+2.0)
            medians = []
            offset_rows = []
            spread_rows = []
            for position in range(16):
                values = strength[rows, index, position]
                values = values[values > 0]
                medians.append(float(np.median(values)) if len(values)
                               else role_default_strength)
                timing = offsets.get((phase, index, position), [])
                stats = _percentiles(timing, 0.0)
                offset_rows.append(stats["median"])
                spread_rows.append(max(1.0, (stats["p90"]-stats["p10"])/2.563))
            phase_probability.append([round(float(value), 5) for value in probability])
            phase_strength.append([round(float(value), 4) for value in medians])
            phase_offset.append([round(float(value), 3) for value in offset_rows])
            phase_spread.append([round(float(value), 3) for value in spread_rows])

        role_rows[role] = {
            "events_per_bar": round(float(activation[:, index].sum()/bars), 4),
            "step_probability": [round(float(value), 5)
                                 for value in global_probability],
            "phase_probability": phase_probability,
            "phase_strength": phase_strength,
            "phase_offset_ms": phase_offset,
            "phase_spread_ms": phase_spread,
        }

    return {
        "roles": role_rows,
        "four_bar_repeat_jaccard": round(_lag_jaccard(activation, 4), 4),
        "adjacent_bar_jaccard": round(_lag_jaccard(activation, 1), 4),
        "tonal_language": _pitch_language(events),
        "events_per_bar": round(float(activation.sum()/bars), 4),
        "method": ("Vier-Takt-Phasen, Rollenwahrscheinlichkeiten, Akzente und "
                   "Microtiming; keine komplette Ereignisfolge gespeichert."),
    }


def legacy_rhythm_model(profile: dict) -> dict:
    """Alte Profile ohne rhythm_model weiterhin sinnvoll abspielen."""
    families = profile.get("sound_families", {})
    bars = max(1, int(profile.get("arrangement", {}).get("bars", 1)))
    roles = {}
    for role in ROLES:
        names = [name for name in families if family_role(name) == role]
        counts = np.zeros(16, dtype=float)
        event_count = 0
        for name in names:
            row = families[name]
            values = np.asarray(row.get("grid_position_counts", [0]*16), dtype=float)
            if len(values) == 16:
                counts += values
            event_count += int(row.get("event_count", 0))
        probability = np.clip(counts/bars, 0.0, 1.0)
        if not np.any(probability):
            probability[:] = 0.02
        roles[role] = {
            "events_per_bar": round(event_count/bars, 4),
            "step_probability": probability.tolist(),
            "phase_probability": [probability.tolist() for _ in range(4)],
            "phase_strength": [[0.58]*16 for _ in range(4)],
            "phase_offset_ms": [[0.0]*16 for _ in range(4)],
            "phase_spread_ms": [[4.0]*16 for _ in range(4)],
        }
    return {
        "roles": roles,
        "four_bar_repeat_jaccard": 0.3,
        "adjacent_bar_jaccard": 0.3,
        "tonal_language": {"root_midi": 60, "intervals_semitones": [0, 3, 5, 7],
                           "pitch_ratios": [1.0, 1.189207, 1.33484, 1.498307]},
        "events_per_bar": sum(row["events_per_bar"] for row in roles.values()),
        "method": "Kompatibilitaetsmodell aus altem Profil.",
    }


class LearnedRhythmGenerator:
    """Neue, wiederholbare Motive aus der verdichteten Rhythmusgrammatik."""

    ROLE_ENERGY = {
        "low": (0.52, 0.84),
        "body": (0.48, 0.78),
        "tonal": (0.54, 0.88),
        "detail": (0.12, 1.05),
    }

    def __init__(self, profile: dict, seed: int):
        self.model = profile.get("rhythm_model") or legacy_rhythm_model(profile)
        self.seed = int(seed)
        self._motifs: dict[tuple, list[int]] = {}

    def pitch_ratios(self) -> tuple[float, ...]:
        values = self.model.get("tonal_language", {}).get("pitch_ratios") or \
            [1.0, 1.189207, 1.33484, 1.498307]
        clean = [float(np.clip(value, 0.70, 1.55)) for value in values]
        return tuple(clean[:5]) or (1.0,)

    def target_count(self, role: str, energy: float,
                     context: tuple[object, ...] | None = None) -> int:
        density = float(self.model["roles"][role].get("events_per_bar", 0.0))
        base, slope = self.ROLE_ENERGY[role]
        expected = density*(base+slope*float(np.clip(energy, 0.0, 1.0)))
        whole = int(np.floor(expected))
        fraction = expected-whole
        # Deterministische stochastische Rundung verhindert systematische
        # Unterdichte bei Rollen mit weniger als einem Ereignis pro Takt.
        if context is None:
            rounded_up = fraction >= .5
        else:
            rounded_up = self._rng("round", role, *context).random() < fraction
        return int(np.clip(whole+int(rounded_up), 0, 16))

    def _rng(self, *parts: object) -> np.random.Generator:
        token = ":".join(str(part) for part in (self.seed, *parts))
        value = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "little")
        return np.random.default_rng(value)

    @staticmethod
    def _weighted_positions(rng: np.random.Generator, count: int,
                            weights: np.ndarray, forbidden: set[int] | None = None) -> list[int]:
        forbidden = forbidden or set()
        available = np.asarray([position for position in range(16)
                                if position not in forbidden], dtype=int)
        count = min(max(0, int(count)), len(available))
        if count == 0:
            return []
        values = np.maximum(weights[available], 1e-5)
        # Gumbel-Top-k: gewichtete Auswahl ohne Zuruecklegen und ohne die
        # flache Zufallsverteilung des alten Generators.
        score = np.log(values)-np.log(-np.log(np.clip(rng.random(len(values)), 1e-9, 1-1e-9)))
        chosen = available[np.argpartition(score, -count)[-count:]]
        return sorted(int(value) for value in chosen)

    def positions(self, role: str, bar: int, section: str, section_bar: int,
                  energy: float, forbidden: set[int] | None = None) -> list[int]:
        forbidden = forbidden or set()
        phase = bar % 4
        group = section_bar//8
        repeated_phrase = (section_bar//4) % 2 == 1
        row = self.model["roles"][role]
        weights = np.asarray(row["phase_probability"][phase], dtype=float)
        weights = np.maximum(weights, np.asarray(row["step_probability"], dtype=float)*0.22)
        count = self.target_count(role, energy, (section, bar))
        key = (section, group, role, phase)
        if key not in self._motifs:
            self._motifs[key] = self._weighted_positions(
                self._rng("motif", *key), count, weights)
        base = [position for position in self._motifs[key]
                if position not in forbidden]

        # Die zweite Vier-Takt-Phrase wiederholt das Motiv weitgehend. Nur
        # Schlusspositionen erhalten eine kleine, deterministische Variation.
        if repeated_phrase and base:
            rng = self._rng("variation", section, group, role, phase)
            variation_chance = {"low": .16, "body": .20, "tonal": .24, "detail": .28}[role]
            if rng.random() < variation_chance:
                removable = sorted(base, key=lambda position: weights[position])
                kept = set(base)
                removed = removable[0]
                kept.remove(removed)
                replacement = self._weighted_positions(
                    rng, 1, weights, kept.union(forbidden))
                base = sorted(kept.union(replacement))

        # Bei ansteigender Energie darf ein neues Ereignis hinzukommen; bei
        # einem Rueckzug wird das schwächste entfernt. Der Motivkern bleibt.
        if len(base) > count:
            base = sorted(base, key=lambda position: weights[position], reverse=True)[:count]
        elif len(base) < count:
            additions = self._weighted_positions(
                self._rng("fill", section, group, role, bar), count-len(base),
                weights, set(base).union(forbidden))
            base = sorted(set(base).union(additions))
        return sorted(base)

    def performance(self, role: str, bar: int, position: int) -> tuple[float, float, float]:
        phase = bar % 4
        row = self.model["roles"][role]
        strength = float(row["phase_strength"][phase][position])
        offset = float(row["phase_offset_ms"][phase][position])/1000.0
        spread = float(row["phase_spread_ms"][phase][position])/1000.0
        return (float(np.clip(offset, -.035, .035)),
                float(np.clip(spread, .001, .022)),
                float(np.clip(strength, .08, 1.0)))

#!/usr/bin/env python3
"""Prozedurale Klanggeneratoren, deren Parameter aus einem Referenzprofil kommen.

Dieses Modul liest nur ``reference-profile.json``. Es kennt und oeffnet die
urspruengliche Audiodatei nicht. Damit ist technisch erzwungen, dass neue
Wellenformen entstehen statt unbemerkt Samples aus der Referenz zu kopieren.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from audio_common import SR, bandpass, highpass


ROLE_FALLBACKS = {
    "low": ("sub", "body", "tonal"),
    "body": ("body", "tonal", "click", "sub"),
    "tonal": ("tonal", "body", "click"),
    "detail": ("tick", "air", "click", "noise", "tonal"),
}


def load_profile(path: Path | str) -> dict:
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(profile.get("schema_version", 0)) != 1:
        raise ValueError("Unbekannte Version des Referenzprofils")
    for key in ("source", "tempo", "mix", "sound_families", "groove"):
        if key not in profile:
            raise ValueError(f"Referenzprofil ohne `{key}`")
    return profile


def profile_seed(profile: dict, extra: int = 0) -> int:
    fingerprint = str(profile.get("source", {}).get("sha256", "reference"))
    digest = hashlib.sha256(f"{fingerprint}:{extra}".encode()).digest()
    return int.from_bytes(digest[:8], "little") & 0x7FFF_FFFF


def _median(row: dict, key: str, fallback: float) -> float:
    value = row.get(key, {})
    if isinstance(value, dict):
        value = value.get("median", fallback)
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(fallback)
    return result if np.isfinite(result) else float(fallback)


def _envelope(t: np.ndarray, decay: float, attack: float) -> np.ndarray:
    attack_shape = np.minimum(1.0, t/max(attack, 1e-5))
    return attack_shape*np.exp(-t/max(decay, 0.004))


class ReferenceSoundFactory:
    """Erzeugt ein neues Instrumentarium aus gemessenen Deskriptoren."""

    def __init__(self, profile: dict, seed: int | None = None):
        self.profile = profile
        self.families = profile["sound_families"]
        self.seed = profile_seed(profile) if seed is None else int(seed)
        self.role_family = {role: self._select_family(role) for role in ROLE_FALLBACKS}

    def _select_family(self, role: str) -> str:
        for candidate in ROLE_FALLBACKS[role]:
            if candidate in self.families:
                return candidate
        if not self.families:
            raise ValueError("Das Referenzprofil enthaelt keine Klangfamilien")
        rows = list(self.families.items())
        if role == "low":
            return min(rows, key=lambda item: _median(item[1], "centroid_hz", 1000))[0]
        if role == "detail":
            return max(rows, key=lambda item: _median(item[1], "centroid_hz", 1000))[0]
        target = 1800 if role == "body" else 900
        return min(rows, key=lambda item: abs(_median(item[1], "centroid_hz", target)-target))[0]

    def family(self, role: str) -> dict:
        return self.families[self.role_family[role]]

    def position_weights(self, role: str) -> np.ndarray:
        row = self.family(role)
        counts = np.asarray(row.get("grid_position_counts", [1]*16), dtype=float)
        if len(counts) != 16 or not np.any(counts > 0):
            counts = np.ones(16)
        # Laplace-Glattung: eine Referenzpause bleibt weniger wahrscheinlich,
        # wird aber nicht zum Verbot fuer die neue Komposition.
        weights = counts+max(0.35, float(np.mean(counts))*0.08)
        if role == "low":
            weights[[0, 8]] *= (1.65, 1.25)
        elif role == "detail":
            weights[1::2] *= 1.18
        return weights/weights.sum()

    def role_share(self, role: str) -> float:
        if role == "body":
            names = {self.role_family["body"], self.role_family["tonal"]}
        else:
            names = {self.role_family[role]}
        return float(sum(self.families[name].get("share", 0.0) for name in names))

    def groove(self, position: int) -> tuple[float, float, float]:
        row = self.profile["groove"].get("positions", [])[position % 16]
        offset = _median(row, "offset_ms", 0.0)/1000.0
        offset_range = row.get("offset_ms", {})
        spread = max(0.001, (float(offset_range.get("p90", 4.0))-
                             float(offset_range.get("p10", -4.0)))/2.563/1000.0)
        strength = _median(row, "strength", 0.58)
        return float(np.clip(offset, -0.035, 0.035)), float(np.clip(spread, .001, .025)), \
            float(np.clip(strength, .08, 1.0))

    def _rng(self, role: str, variant: int, velocity: float, pitch_ratio: float) -> np.random.Generator:
        token = f"{self.seed}:{role}:{variant}:{velocity:.3f}:{pitch_ratio:.5f}"
        seed = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "little")
        return np.random.default_rng(seed)

    def render(self, role: str, variant: int = 0, velocity: float = 0.75,
               pitch_ratio: float = 1.0) -> np.ndarray:
        if role not in ROLE_FALLBACKS:
            raise ValueError(f"Unbekannte Klangrolle: {role}")
        velocity = float(np.clip(velocity, 0.05, 1.0))
        pitch_ratio = float(np.clip(pitch_ratio, 0.5, 2.0))
        rng = self._rng(role, variant, velocity, pitch_ratio)
        row = self.family(role)
        if role == "low":
            sound = self._low(row, rng, variant, velocity, pitch_ratio)
        elif role == "body":
            sound = self._body(row, rng, variant, velocity, pitch_ratio)
        elif role == "tonal":
            sound = self._tonal(row, rng, variant, velocity, pitch_ratio)
        else:
            sound = self._detail(row, rng, variant, velocity, pitch_ratio)
        sound = np.nan_to_num(sound).astype(np.float32)
        peak = float(np.max(np.abs(sound))) or 1.0
        # Velocity beeinflusst nicht nur den Pegel, sondern schon Attack,
        # Obertoene und Rauschanteil in den Generatoren.
        return sound/peak*(0.30+0.62*velocity)

    def _low(self, row: dict, rng: np.random.Generator, variant: int,
             velocity: float, pitch_ratio: float) -> np.ndarray:
        dominant = np.clip(_median(row, "dominant_hz", 75.0), 42.0, 145.0)*pitch_ratio
        decay = np.clip(_median(row, "decay_seconds", .20), .10, .65)*(0.88+.12*velocity)
        duration = max(.28, min(1.0, decay*3.8))
        t = np.arange(int(duration*SR), dtype=np.float64)/SR
        start_ratio = 1.38+0.10*(variant % 3)+0.10*velocity
        frequency = dominant*(1.0+(start_ratio-1.0)*np.exp(-t*(22+variant*2)))
        phase = 2*np.pi*np.cumsum(frequency)/SR
        body = np.sin(phase)*np.exp(-t/max(decay, .02))
        body += (0.08+0.10*velocity)*np.sin(2.01*phase+.19*variant)*np.exp(-t/(decay*.58))
        click = highpass(rng.standard_normal(len(t)).astype(np.float32), 2200+variant*350, 2)
        click *= np.exp(-t*(105+20*velocity))*(.018+.035*velocity)
        return np.asarray(body+click, dtype=np.float32)

    def _body(self, row: dict, rng: np.random.Generator, variant: int,
              velocity: float, pitch_ratio: float) -> np.ndarray:
        centroid = np.clip(_median(row, "centroid_hz", 1800.0), 350.0, 6500.0)
        # Die Body-Rolle traegt bewusst den Bereich unterhalb der tonalen
        # Rolle. Beide koennen aus derselben gemessenen Familie stammen, sind
        # im neuen Kit aber zwei verschiedene Instrumente.
        base = np.clip(max(_median(row, "dominant_hz", 680.0), centroid*.28),
                       160.0, 1500.0)*pitch_ratio
        decay = np.clip(_median(row, "decay_seconds", .12), .045, .42)
        duration = max(.16, min(.72, decay*4.4))
        t = np.arange(int(duration*SR), dtype=np.float64)/SR
        ratios = (1.0, 1.57+variant*.025, 2.31, 3.86+variant*.04)
        amplitudes = (1.0, .43, .24, .11)
        sound = np.zeros_like(t)
        for index, (ratio, amplitude) in enumerate(zip(ratios, amplitudes)):
            sound += amplitude*np.sin(2*np.pi*base*ratio*t+variant*.29*index) \
                *_envelope(t, decay/(1+index*.38), .0007+.0002*index)
        low = max(90.0, min(centroid*.28, 2800.0))
        high = max(low+180.0, min(18_000.0, centroid*(2.3+.25*velocity)))
        texture = bandpass(rng.standard_normal(len(t)).astype(np.float32), low, high, 2)
        sound += texture*np.exp(-t/(decay*.55))*(.06+.12*velocity)
        return np.asarray(sound, dtype=np.float32)

    def _tonal(self, row: dict, rng: np.random.Generator, variant: int,
               velocity: float, pitch_ratio: float) -> np.ndarray:
        centroid = np.clip(_median(row, "centroid_hz", 1800.0), 350.0, 6500.0)
        base = np.clip(max(_median(row, "dominant_hz", 620.0), centroid*.50),
                       140.0, 2200.0)*pitch_ratio
        decay = np.clip(_median(row, "decay_seconds", .16), .07, .62)
        duration = max(.30, min(1.10, decay*5.0))
        t = np.arange(int(duration*SR), dtype=np.float64)/SR
        inharmonic = 1.0+variant*.004
        ratios = (1.0, 2.01*inharmonic, 3.92*inharmonic, 5.38*inharmonic, 6.81*inharmonic)
        amplitudes = (1.0, .32, .18, .085, .045)
        sound = np.zeros_like(t)
        for index, (ratio, amplitude) in enumerate(zip(ratios, amplitudes)):
            sound += amplitude*np.sin(2*np.pi*base*ratio*t+index*.31*variant) \
                *_envelope(t, decay/(1+index*.31), .0005)
        knock_low = max(180.0, min(base*.65, 2500.0))
        knock_high = min(11_000.0, max(knock_low+300.0, base*5.0))
        knock = bandpass(rng.standard_normal(len(t)).astype(np.float32),
                         knock_low, knock_high, 2)
        sound += knock*np.exp(-t*95.0)*(.025+.055*velocity)
        return np.asarray(sound, dtype=np.float32)

    def _detail(self, row: dict, rng: np.random.Generator, variant: int,
                velocity: float, pitch_ratio: float) -> np.ndarray:
        centroid = np.clip(_median(row, "centroid_hz", 7000.0), 2600.0, 13_500.0)
        decay = np.clip(_median(row, "decay_seconds", .06), .018, .22)
        duration = max(.07, min(.48, decay*4.0))
        t = np.arange(int(duration*SR), dtype=np.float64)/SR
        raw = rng.standard_normal(len(t)).astype(np.float32)
        cutoff = np.clip(centroid*(.48+.04*variant), 1400.0, 11_500.0)
        air_noise = highpass(raw, float(cutoff), 3)
        presence_low = float(np.clip(centroid*.27, 1800.0, 4200.0))
        presence_high = float(np.clip(centroid*.90, presence_low+600.0, 7200.0))
        presence_noise = bandpass(raw, presence_low, presence_high, 2)
        envelope = _envelope(t, decay, .00025+.00015*(variant % 3))
        modulation = .78+.22*np.sin(2*np.pi*(73+variant*11)*t+variant)
        sound = (.40*air_noise+.74*presence_noise)*envelope*modulation
        if self.role_family["detail"] in {"click", "tonal"}:
            frequency = np.clip(_median(row, "dominant_hz", 3200.0), 900.0, 7800.0)*pitch_ratio
            sound += np.sin(2*np.pi*frequency*t+variant*.4)*np.exp(-t/(decay*.42))*.18
        # Der Filter kann bei sehr kurzen Impulsen DC erzeugen.
        return highpass(np.asarray(sound, dtype=np.float32), 80.0, 2)

    def describe(self) -> dict:
        return {
            "profile_source_sha256": self.profile["source"].get("sha256"),
            "seed": self.seed,
            "role_to_measured_family": self.role_family,
            "principle": ("Neue Oszillatoren, Rauschquellen, Resonatoren und Huellkurven; "
                          "keine Audiodaten aus der Referenz."),
        }

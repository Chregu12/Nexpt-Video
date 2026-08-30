#!/usr/bin/env python3
"""Sample-basierte Klangquelle fuer die profilgesteuerte Referenzmusik.

Die Engine verwendet ausschliesslich echte CC0-Aufnahmen aus VCSL. Das
Referenz-Audio wird weder geoeffnet noch geschnitten. Seine Analyse steuert
nur Auswahl, Stimmung, Abklingzeit und breite spektrale Bearbeitung.
"""
from __future__ import annotations

import json
import math
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly, welch

from audio_common import OUT, SR, highpass
from reference_sound import ReferenceSoundFactory, _median, profile_seed


DEFAULT_LIBRARY = OUT/"_vcsl"

# Mehrere echte Instrumente pro Rolle verhindern den alten "ein Sample fuer
# alles"-Klang. Die Reihenfolge ist Teil des reproduzierbaren Instruments.
ROLE_PALETTES = {
    "low": (
        "BDrumNew_hit",
    ),
    "body": (
        "Snare2_stick",
        "Snare2_taps",
        "Clap",
        "wood_click",
    ),
    "tonal": (
        "Darbuka_2_hit",
        "Claves1_Hit",
        "BongoH_Hit1",
        "Snare2_taps",
        "Darbuka_2_hit",
    ),
    "detail": (
        "HiHat_HitC",
        "HiHat_Close",
        "HiHat_HitO",
        "HiHat_HitLoose",
    ),
}

# Leise Parallelanschlaege stammen ebenfalls aus der Bibliothek. Sie geben
# der tiefen Trommel einen echten Beater und den tonalen Trommeln den kurzen
# Holzanteil, den das Referenzprofil beschreibt.
LAYER_PALETTES = {
    "low": ("Cajon_hit1",),
    "body": ("HiHat_Close", "HiHat_HitC"),
    "tonal": ("Snare2_taps", "Snare2_stick", "Clap", "Claves2_Hit"),
}

ROLE_DOMINANT_RANGES = {
    "low": (35.0, 190.0),
    "body": (650.0, 7200.0),
    "tonal": (120.0, 1900.0),
    "detail": (2200.0, 13_000.0),
}

ROLE_TUNING_LIMITS = {
    "low": (.90, 1.16),
    "body": (.84, 1.24),
    "tonal": (.74, 1.36),
    "detail": (.84, 1.24),
}

ROLE_HIGHPASS = {"low": 24.0, "body": 72.0, "tonal": 72.0, "detail": 145.0}
ROLE_TRANSIENT = {
    "low": (420.0, .34),
    "body": (1500.0, .27),
    "tonal": (850.0, .22),
    "detail": (3200.0, .10),
}
ROLE_DURATION_LIMITS = {
    "low": (.30, .68),
    "body": (.09, .30),
    "tonal": (.12, .40),
    "detail": (.08, .34),
}
ROLE_LAYER_LEVEL = {"low": .28, "body": .11, "tonal": .30}
ROLE_LAYER_HIGHPASS = {"low": 180.0, "body": 4300.0, "tonal": 760.0}

BAND_NAMES = ("sub", "bass", "low_mid", "mid", "presence", "air")
BAND_EDGES = ((20, 80), (80, 250), (250, 800),
              (800, 2500), (2500, 6000), (6000, 18_000))
BAND_CENTERS = np.asarray([math.sqrt(a*b) for a, b in BAND_EDGES])


def read_wav_mono(path: Path) -> np.ndarray:
    """PCM-WAV (8/16/24/32 Bit, mono/stereo) als 48-kHz-Mono lesen."""
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    if width == 1:
        audio = (np.frombuffer(raw, np.uint8).astype(np.float64)-128.0)/128.0
    elif width == 2:
        audio = np.frombuffer(raw, "<i2").astype(np.float64)/32768.0
    elif width == 3:
        bytes3 = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        values = bytes3[:, 0] | (bytes3[:, 1] << 8) | (bytes3[:, 2] << 16)
        signed = np.where(values & 0x800000, values-(1 << 24), values)
        audio = signed.astype(np.float64)/8388608.0
    elif width == 4:
        audio = np.frombuffer(raw, "<i4").astype(np.float64)/2147483648.0
    else:
        raise ValueError(f"Nicht unterstuetzte PCM-Breite {width}: {path}")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SR:
        divisor = math.gcd(rate, SR)
        audio = resample_poly(audio, SR//divisor, rate//divisor)
    return np.nan_to_num(audio).astype(np.float32)


def trim_recording(audio: np.ndarray) -> np.ndarray:
    """Vorlauf und unnoetige Raumstille entfernen, Attack aber behalten."""
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) == 0:
        return audio
    audio = audio-float(np.mean(audio))
    window = max(1, int(.0015*SR))
    energy = np.convolve(np.abs(audio), np.ones(window)/window, mode="same")
    maximum = float(np.max(energy))
    if maximum <= 1e-8:
        return np.zeros(64, dtype=np.float32)
    onset_candidates = np.flatnonzero(energy >= maximum*.035)
    onset = max(0, int(onset_candidates[0])-int(.003*SR))
    audio = audio[onset:onset+int(2.5*SR)]
    peak = float(np.max(np.abs(audio))) or 1.0
    return (audio/peak).astype(np.float32)


def pitch_recording(audio: np.ndarray, ratio: float) -> np.ndarray:
    """Percussion durch Abspielgeschwindigkeit stimmen (Sampler-Verhalten)."""
    ratio = float(np.clip(ratio, .55, 1.65))
    if abs(ratio-1.0) < 1e-4:
        return audio.copy()
    count = max(64, int(round(len(audio)/ratio)))
    positions = np.arange(count, dtype=np.float64)*ratio
    return np.interp(positions, np.arange(len(audio)), audio,
                     left=0.0, right=0.0).astype(np.float32)


def dominant_frequency(audio: np.ndarray, low: float, high: float) -> float:
    count = min(len(audio), int(.24*SR))
    if count < 128:
        return math.sqrt(low*high)
    segment = np.asarray(audio[:count], dtype=np.float64)*np.hanning(count)
    power = np.abs(np.fft.rfft(segment))**2
    frequencies = np.fft.rfftfreq(count, 1/SR)
    mask = (frequencies >= low) & (frequencies <= high)
    if not np.any(mask) or float(power[mask].sum()) <= 1e-16:
        return math.sqrt(low*high)
    indexes = np.flatnonzero(mask)
    return float(frequencies[indexes[int(np.argmax(power[mask]))]])


def fit_duration(audio: np.ndarray, role: str, decay: float) -> np.ndarray:
    minimum, maximum = ROLE_DURATION_LIMITS[role]
    wanted = float(np.clip(decay*4.15, minimum, maximum))
    count = min(len(audio), max(128, int(round(wanted*SR))))
    result = audio[:count].copy()
    fade = min(count, max(int(.012*SR), int(count*.28)))
    if fade:
        phase = np.linspace(0.0, np.pi/2, fade)
        result[-fade:] *= np.cos(phase)**1.7
    return result


def spectral_match(audio: np.ndarray, targets: dict, strength: float = .48) -> np.ndarray:
    """Sechs breite Profilbaender angleichen; keine neue Schallquelle addieren."""
    if len(audio) < 128:
        return audio
    windowed = np.asarray(audio, dtype=np.float64)*np.hanning(len(audio))
    spectrum = np.fft.rfft(windowed)
    power = np.abs(spectrum)**2
    frequencies = np.fft.rfftfreq(len(audio), 1/SR)
    current = np.asarray([
        power[(frequencies >= low) & (frequencies < high)].sum()
        for low, high in BAND_EDGES
    ], dtype=np.float64)
    target = np.asarray([float(targets.get(name, 0.0)) for name in BAND_NAMES])
    if current.sum() <= 1e-20 or target.sum() <= 1e-20:
        return audio
    current /= current.sum()
    target /= target.sum()
    gain_db = 10.0*np.log10((target+2e-5)/(current+2e-5))*float(strength)
    gain_db = np.clip(gain_db, -8.0, 12.0)
    safe_frequency = np.maximum(frequencies, BAND_CENTERS[0])
    curve_db = np.interp(np.log(safe_frequency), np.log(BAND_CENTERS), gain_db,
                         left=gain_db[0], right=gain_db[-1])
    transformed = np.fft.rfft(np.asarray(audio, dtype=np.float64))
    transformed *= 10**(curve_db/20.0)
    return np.fft.irfft(transformed, len(audio)).astype(np.float32)


def match_mix_bands(stereo: np.ndarray, targets: dict, strength: float = .62,
                    max_gain_db: float = 4.5) -> tuple[np.ndarray, dict]:
    """Breite Master-EQ-Kurve aus der Referenzbalance, ohne Quell-Audio.

    Die Messung nutzt Welch-Fenster, die Bearbeitung eine glatte, fuer beide
    Kanaele identische Kurve. Dadurch bleiben Panorama und Mono-Kompatibilitaet
    erhalten. Der begrenzte Regelbereich verhindert ein starres Matchen eines
    fertigen Masters auf einzelne rohe Trommeln.
    """
    mono = np.asarray(stereo, dtype=np.float32).mean(axis=1)
    frequencies, power = welch(
        mono, fs=SR, window="hann", nperseg=min(8192, len(mono)),
        noverlap=min(4096, max(0, len(mono)//2-1)),
        detrend=False, scaling="spectrum",
    )
    current = np.asarray([
        power[(frequencies >= low) & (frequencies < high)].sum()
        for low, high in BAND_EDGES
    ], dtype=np.float64)
    target = np.asarray([float(targets.get(name, 0.0)) for name in BAND_NAMES])
    if current.sum() <= 1e-20 or target.sum() <= 1e-20:
        return np.asarray(stereo, dtype=np.float32), {"applied": False}
    current /= current.sum()
    target /= target.sum()
    gain_db = 10.0*np.log10((target+1e-6)/(current+1e-6))*float(strength)
    gain_db = np.clip(gain_db, -abs(max_gain_db), abs(max_gain_db))
    transform_frequencies = np.fft.rfftfreq(len(stereo), 1/SR)
    safe_frequency = np.maximum(transform_frequencies, BAND_CENTERS[0])
    curve_db = np.interp(np.log(safe_frequency), np.log(BAND_CENTERS), gain_db,
                         left=gain_db[0], right=gain_db[-1])
    multiplier = 10**(curve_db/20.0)
    result = np.empty_like(stereo, dtype=np.float32)
    for channel in range(2):
        transformed = np.fft.rfft(np.asarray(stereo[:, channel], dtype=np.float64))
        transformed *= multiplier
        result[:, channel] = np.fft.irfft(transformed, len(stereo)).astype(np.float32)
    return result, {
        "applied": True,
        "strength": round(float(strength), 3),
        "max_gain_db": round(float(max_gain_db), 2),
        "bands_before": {name: round(float(value), 5)
                         for name, value in zip(BAND_NAMES, current)},
        "bands_target": {name: round(float(value), 5)
                         for name, value in zip(BAND_NAMES, target)},
        "gain_db": {name: round(float(value), 3)
                    for name, value in zip(BAND_NAMES, gain_db)},
    }


class ReferenceDrumFactory:
    """Echte Aufnahmen als profilgesteuertes, mehrstufiges Percussion-Kit."""

    def __init__(self, profile: dict, library: Path | str = DEFAULT_LIBRARY,
                 seed: int | None = None):
        self.profile = profile
        self.library = Path(library)
        self.seed = profile_seed(profile) if seed is None else int(seed)
        catalog_path = self.library/"katalog.json"
        if not catalog_path.exists():
            raise FileNotFoundError(
                f"{catalog_path} fehlt; zuerst `python3 render/vcsl.py` ausfuehren")
        self.catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.articulations = self.catalog.get("artikulationen", {})
        self.role_family = ReferenceSoundFactory(profile, seed=self.seed).role_family
        self.palettes = {
            role: tuple(name for name in names if name in self.articulations)
            for role, names in ROLE_PALETTES.items()
        }
        missing = [role for role, names in self.palettes.items() if not names]
        if missing:
            raise ValueError(
                f"Drum-Bibliothek ohne Artikulationen fuer: {', '.join(missing)}")
        self.layers = {
            role: tuple(name for name in names if name in self.articulations)
            for role, names in LAYER_PALETTES.items()
        }

    @staticmethod
    def available(library: Path | str = DEFAULT_LIBRARY) -> bool:
        return (Path(library)/"katalog.json").exists()

    @lru_cache(maxsize=384)
    def _recording(self, relative: str) -> np.ndarray:
        return trim_recording(read_wav_mono(self.library/relative))

    def _entry(self, articulation: str, velocity: float, variant: int) -> dict:
        rows = self.articulations[articulation]
        stages = sorted({int(row.get("stufe", 1)) for row in rows})
        stage_index = int(np.clip(
            np.floor(float(velocity)*(len(stages)-1)+.5), 0, len(stages)-1))
        candidates = [row for row in rows
                      if int(row.get("stufe", 1)) == stages[stage_index]]
        return candidates[int(variant) % len(candidates)]

    def _pick(self, role: str, velocity: float, variant: int,
              layer: bool = False) -> tuple[str, np.ndarray]:
        palette = self.layers.get(role, ()) if layer else self.palettes[role]
        articulation = palette[int(variant) % len(palette)]
        entry = self._entry(articulation, velocity,
                            int(variant)//max(1, len(palette)))
        return articulation, self._recording(str(entry["datei"])).copy()

    def _prepare(self, audio: np.ndarray, role: str, requested_pitch: float) -> np.ndarray:
        family = self.profile["sound_families"][self.role_family[role]]
        low, high = ROLE_DOMINANT_RANGES[role]
        source_dominant = dominant_frequency(audio, low, high)
        fallback = {"low": 70.0, "body": 2800.0,
                    "tonal": 650.0, "detail": 4500.0}[role]
        target_dominant = float(np.clip(
            _median(family, "dominant_hz", fallback), low, high))
        lower, upper = ROLE_TUNING_LIMITS[role]
        base_ratio = float(np.clip(target_dominant/max(source_dominant, 1.0),
                                   lower, upper))
        musical_ratio = float(np.clip(requested_pitch, .82, 1.28)) \
            if role == "tonal" else 1.0
        audio = pitch_recording(audio, base_ratio*musical_ratio)
        audio = highpass(audio, ROLE_HIGHPASS[role], 2)
        cutoff, amount = ROLE_TRANSIENT[role]
        time = np.arange(len(audio), dtype=np.float32)/SR
        transient = highpass(audio, cutoff, 2)*np.exp(-time/.024)
        audio = audio+transient*amount
        decay = _median(family, "decay_seconds", .10)
        return fit_duration(audio, role, decay)

    def render(self, role: str, variant: int = 0, velocity: float = .75,
               pitch_ratio: float = 1.0) -> np.ndarray:
        if role not in ROLE_PALETTES:
            raise ValueError(f"Unbekannte Klangrolle: {role}")
        velocity = float(np.clip(velocity, .05, 1.0))
        _, primary = self._pick(role, velocity, int(variant))
        sound = self._prepare(primary, role, pitch_ratio)

        if self.layers.get(role):
            _, layer = self._pick(role, velocity, int(variant)+3, layer=True)
            layer = self._prepare(layer, role, pitch_ratio)
            layer = highpass(layer, ROLE_LAYER_HIGHPASS[role], 2)
            layer_peak = float(np.max(np.abs(layer))) or 1.0
            layer = layer/layer_peak
            count = max(len(sound), len(layer))
            combined = np.zeros(count, dtype=np.float32)
            combined[:len(sound)] += sound
            delay = min(int(.0015*SR)*(int(variant) % 3), max(0, count-1))
            layer_count = min(len(layer), count-delay)
            combined[delay:delay+layer_count] += \
                layer[:layer_count]*ROLE_LAYER_LEVEL[role]
            sound = combined

        family = self.profile["sound_families"][self.role_family[role]]
        match_strength = {"low": .66, "body": .66,
                          "tonal": .74, "detail": .58}[role]
        sound = spectral_match(
            sound, family.get("bands_median", {}), strength=match_strength)
        sound = highpass(sound, ROLE_HIGHPASS[role], 2)
        sound = np.nan_to_num(sound).astype(np.float32)
        peak = float(np.max(np.abs(sound))) or 1.0
        return sound/peak*(.29+.63*velocity)

    def describe(self) -> dict:
        return {
            "engine": "real-drum-samples",
            "library": "Versilian Community Sample Library (VCSL)",
            "library_source": self.catalog.get("quelle"),
            "library_license": self.catalog.get("lizenz"),
            "seed": self.seed,
            "role_to_measured_family": self.role_family,
            "role_palettes": {role: list(names) for role, names in self.palettes.items()},
            "parallel_layers": {role: list(names) for role, names in self.layers.items()
                                if names},
            "recording_count": sum(
                len(self.articulations[name])
                for name in {
                    item
                    for group in (self.palettes, self.layers)
                    for names in group.values()
                    for item in names
                }
            ),
            "principle": (
                "Echte CC0-Aufnahmen mit Velocity-Layern und Round Robins; "
                "profilgesteuert gestimmt, gekuerzt und breitbandig geformt. "
                "Keine Audiodaten aus der Referenz und keine Oszillatoren."
            ),
        }


def create_sound_factory(profile: dict, sound_source: str = "auto",
                         library: Path | str = DEFAULT_LIBRARY,
                         seed: int | None = None):
    """Sample-Engine waehlen, bei ``auto`` reproduzierbar zurueckfallen."""
    if sound_source not in {"auto", "samples", "procedural"}:
        raise ValueError(f"Unbekannte Klangquelle: {sound_source}")
    if sound_source == "procedural":
        return ReferenceSoundFactory(profile, seed=seed)
    if ReferenceDrumFactory.available(library):
        try:
            return ReferenceDrumFactory(profile, library=library, seed=seed)
        except (FileNotFoundError, ValueError):
            if sound_source == "samples":
                raise
    if sound_source == "samples":
        raise FileNotFoundError(
            f"{Path(library)/'katalog.json'} fehlt; zuerst "
            "`python3 render/vcsl.py` ausfuehren")
    return ReferenceSoundFactory(profile, seed=seed)

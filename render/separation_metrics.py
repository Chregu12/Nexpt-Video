"""Label-aware waveform metrics for aligned, known music/dialogue/SFX stems.

SI-SDR follows the scalar projection in Le Roux et al. (2019), Eq. 5:
https://arxiv.org/abs/1811.02508 . We additionally retain gain-sensitive SNR.
No permutation, delay fitting, filtering or audio normalization is performed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import numpy as np


ROLES = ("music", "dialogue", "sfx")
METRIC_VERSION = "nexpt-known-stems-v1"
DB_LIMIT = 120.0
SILENCE_RMS = 1e-5


@dataclass(frozen=True)
class Gates:
    minimum_snr_db: float = 10.0
    minimum_si_sdr_improvement_db: float = 3.0
    maximum_silent_rms: float = 1e-4
    maximum_mix_residual_ratio: float = .1

    def validate(self) -> None:
        for key, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f"{key} muss eine endliche Zahl sein")
        if not -DB_LIMIT <= self.minimum_snr_db <= DB_LIMIT:
            raise ValueError("minimum_snr_db ausserhalb des Messbereichs")
        if not 0 <= self.minimum_si_sdr_improvement_db <= DB_LIMIT:
            raise ValueError("minimum_si_sdr_improvement_db muss zwischen 0 und 120 liegen")
        if not 0 <= self.maximum_silent_rms <= 1 or not 0 <= self.maximum_mix_residual_ratio <= 1:
            raise ValueError("Silent-/Mix-Grenzwerte muessen zwischen 0 und 1 liegen")


def _audio(value: np.ndarray) -> np.ndarray:
    samples = np.asarray(value, dtype=np.float64)
    if samples.ndim == 1:
        samples = samples[:, None]
    if (samples.ndim != 2 or samples.shape[1] not in (1, 2) or not samples.size
            or not np.isfinite(samples).all() or np.max(np.abs(samples)) > 1e6):
        raise ValueError("Leere, nicht-endliche oder ungueltige Audiodaten")
    return samples


def rms(value: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(value))))


def _db(numerator: float, denominator: float) -> float:
    # JSON stays finite. The exact-zero estimate of an active reference is
    # deliberately NOT rewarded by the undefined 0/0 SI-SDR limit.
    if numerator <= 0:
        return -DB_LIMIT
    if denominator <= 0:
        return DB_LIMIT
    return float(np.clip(10 * (math.log10(numerator) - math.log10(denominator)), -DB_LIMIT, DB_LIMIT))


def _scores(reference: np.ndarray, estimate: np.ndarray) -> dict[str, float | None]:
    snr = _db(float(np.sum(reference ** 2)), float(np.sum((reference - estimate) ** 2)))
    # Remove DC per channel, then one common projection over all channels.
    # Unlike downmixing to mono, this retains stereo balance and phase errors.
    target = reference - reference.mean(axis=0, keepdims=True)
    predicted = estimate - estimate.mean(axis=0, keepdims=True)
    target_power = float(np.sum(target ** 2))
    if rms(target) <= SILENCE_RMS:
        return {"snr_db": snr, "si_sdr_db": None, "projection_gain": None}
    gain = float(np.sum(target * predicted)) / target_power
    projected = gain * target
    return {"snr_db": snr,
            "si_sdr_db": _db(float(np.sum(projected ** 2)), float(np.sum((predicted - projected) ** 2))),
            "projection_gain": gain}


def stem_metrics(reference: np.ndarray, estimate: np.ndarray, mixture: np.ndarray,
                 sample_rate: int, gates: Gates) -> dict[str, Any]:
    gates.validate()
    reference, estimate, mixture = map(_audio, (reference, estimate, mixture))
    if reference.shape != estimate.shape or reference.shape != mixture.shape:
        raise ValueError("Referenz, Schaetzung und Mix muessen samplegenau ausgerichtet sein")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("Ungueltige Samplerate")
    active = rms(reference) > SILENCE_RMS
    baseline = _scores(reference, mixture) if active else None
    scores = _scores(reference, estimate) if active else None
    window = max(1, round(sample_rate * .25))
    silent_levels = [rms(estimate[start:start + window])
                     for start in range(0, len(reference), window)
                     if rms(reference[start:start + window]) <= SILENCE_RMS]
    silent_max = max(silent_levels) if silent_levels else None
    findings = []
    improvement = None
    required_si_sdr = None
    if active:
        if scores["snr_db"] < gates.minimum_snr_db:
            findings.append("waveform_snr_below_threshold")
        if scores["si_sdr_db"] is None or baseline["si_sdr_db"] is None:
            findings.append("si_sdr_not_assessable")
        else:
            improvement = scores["si_sdr_db"] - baseline["si_sdr_db"]
            # A source already perfectly isolated in the mixture cannot
            # improve beyond the explicitly documented numerical score cap.
            required_si_sdr = min(DB_LIMIT, baseline["si_sdr_db"] + gates.minimum_si_sdr_improvement_db)
            if scores["si_sdr_db"] < required_si_sdr:
                findings.append("no_sufficient_improvement_over_mix")
    if silent_max is not None and silent_max > gates.maximum_silent_rms:
        findings.append("energy_in_reference_silence")
    return {
        "reference_active": active, "reference_rms": rms(reference),
        "estimate_rms": rms(estimate), "estimate_peak": float(np.max(np.abs(estimate))),
        "scores": scores, "mixture_baseline": baseline,
        "si_sdr_improvement_db": improvement, "required_si_sdr_db": required_si_sdr,
        "silence": {"window_seconds": .25, "reference_silence_rms": SILENCE_RMS,
                    "window_count": len(silent_levels), "maximum_estimate_rms": silent_max},
        "numerical_gate_passed": not findings, "findings": findings,
    }


def source_projection(references: dict[str, np.ndarray], estimates: dict[str, np.ndarray]) -> dict[str, Any]:
    """Linear contamination diagnostic; NOT a perceptual leakage percentage."""
    active = [role for role in ROLES if rms(references[role]) > SILENCE_RMS]
    if not active:
        return {"available": False, "reason": "no_active_references"}
    columns = [references[role].reshape(-1) for role in active]
    matrix = np.column_stack(columns)
    norms = np.linalg.norm(matrix, axis=0)
    normalized = matrix / norms
    gram = normalized.T @ normalized
    condition = float(np.linalg.cond(gram))
    if not math.isfinite(condition) or condition > 1e6:
        return {"available": False, "reason": "correlated_or_dependent_references"}
    predictions = np.column_stack([estimates[role].reshape(-1) for role in ROLES])
    # Only a 3x3 system; reference audio is never modified to improve scores.
    coefficients = np.linalg.solve(gram, normalized.T @ predictions) / norms[:, None]
    return {"available": True, "condition_number": condition,
            "coefficients_by_estimated_role": {
                predicted: {reference: float(coefficients[i, j]) for i, reference in enumerate(active)}
                for j, predicted in enumerate(ROLES)},
            "interpretation": "Linear source coefficients; not perceptual leakage or SIR/SAR."}


def evaluate_arrays(mixture: np.ndarray, references: dict[str, np.ndarray],
                    estimates: dict[str, np.ndarray], sample_rate: int,
                    gates: Gates | None = None) -> dict[str, Any]:
    gates = gates or Gates()
    gates.validate()
    if set(references) != set(ROLES) or set(estimates) != set(ROLES):
        raise ValueError("Exakt music, dialogue und sfx muessen vorhanden sein")
    mixture = _audio(mixture)
    references = {role: _audio(references[role]) for role in ROLES}
    estimates = {role: _audio(estimates[role]) for role in ROLES}
    if any(array.shape != mixture.shape for array in (*references.values(), *estimates.values())):
        raise ValueError("Sampleraster/Kanaele stimmen nicht ueberein; kein automatisches Alignment")
    mix_rms = rms(mixture)
    if mix_rms <= SILENCE_RMS:
        raise ValueError("Stummer Mix ist kein aussagekraeftiger Benchmark")
    reference_residual = rms(mixture - sum(references.values())) / mix_rms
    if reference_residual > 1e-6:
        raise ValueError("Referenzspuren rekonstruieren den deklarierten Mix nicht")
    rows = {role: stem_metrics(references[role], estimates[role], mixture, sample_rate, gates)
            for role in ROLES}
    residual = rms(mixture - sum(estimates.values())) / mix_rms
    mix_passed = residual <= gates.maximum_mix_residual_ratio
    return {"roles": rows,
            "mix_consistency": {"residual_ratio": residual, "passed": mix_passed},
            "source_projection": source_projection(references, estimates),
            "numerical_gate_passed": mix_passed and all(row["numerical_gate_passed"] for row in rows.values()),
            "listening_review_required": True, "perceptual_quality_verified": False}

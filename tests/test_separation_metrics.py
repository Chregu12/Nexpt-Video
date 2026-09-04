from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

from separation_metrics import Gates, ROLES, evaluate_arrays, stem_metrics


def signals():
    times = np.arange(8_000) / 8_000
    return {role: np.column_stack((.1 * np.sin(2 * np.pi * frequency * times),
                                   .08 * np.sin(2 * np.pi * frequency * times + .4)))
            for role, frequency in zip(ROLES, (113, 251, 379))}


class KnownStemMetricsTests(unittest.TestCase):
    def setUp(self):
        self.truth = signals()
        self.mix = sum(self.truth.values())

    def evaluate(self, estimates, truth=None, mixture=None):
        return evaluate_arrays(self.mix if mixture is None else mixture,
                               self.truth if truth is None else truth, estimates, 8_000)

    def test_oracle_scores_and_diagonal_source_projection(self):
        result = self.evaluate(self.truth)
        self.assertTrue(result["numerical_gate_passed"])
        self.assertFalse(result["perceptual_quality_verified"])
        self.assertTrue(result["listening_review_required"])
        for role in ROLES:
            self.assertEqual(result["roles"][role]["scores"]["snr_db"], 120)
            for source, value in result["source_projection"]["coefficients_by_estimated_role"][role].items():
                self.assertAlmostEqual(value, 1 if role == source else 0, places=10)

    def test_analytic_snr_and_si_sdr_for_orthogonal_interference(self):
        reference = self.truth["music"]
        estimate = reference + .5 * self.truth["dialogue"]
        result = stem_metrics(reference, estimate, self.mix, 8_000, Gates())
        self.assertAlmostEqual(result["scores"]["snr_db"], 20 * np.log10(2), places=8)
        self.assertAlmostEqual(result["scores"]["si_sdr_db"], 20 * np.log10(2), places=8)
        self.assertAlmostEqual(result["scores"]["projection_gain"], 1, places=8)

    def test_swapped_roles_fail_even_when_sum_is_perfect(self):
        predicted = {**self.truth, "music": self.truth["dialogue"], "dialogue": self.truth["music"]}
        result = self.evaluate(predicted)
        self.assertTrue(result["mix_consistency"]["passed"])
        self.assertFalse(result["numerical_gate_passed"])
        self.assertAlmostEqual(result["source_projection"]["coefficients_by_estimated_role"]["music"]["dialogue"], 1)

    def test_equal_split_is_not_a_separator_despite_perfect_sum(self):
        result = self.evaluate({role: self.mix / 3 for role in ROLES})
        self.assertTrue(result["mix_consistency"]["passed"])
        self.assertFalse(result["numerical_gate_passed"])
        for role in ROLES:
            self.assertAlmostEqual(result["roles"][role]["si_sdr_improvement_db"], 0, places=8)

    def test_gain_error_is_not_hidden_by_scale_invariant_score(self):
        result = self.evaluate({role: self.truth[role] * .2 for role in ROLES})
        self.assertFalse(result["numerical_gate_passed"])
        self.assertGreater(result["roles"]["music"]["scores"]["si_sdr_db"], 110)
        self.assertLess(result["roles"]["music"]["scores"]["snr_db"], 2)

    def test_polarity_error_is_not_hidden(self):
        result = self.evaluate({role: -self.truth[role] for role in ROLES})
        self.assertFalse(result["numerical_gate_passed"])
        self.assertAlmostEqual(result["roles"]["music"]["scores"]["projection_gain"], -1)

    def test_silent_estimate_of_active_source_is_worst_si_sdr(self):
        result = self.evaluate({role: np.zeros_like(self.mix) for role in ROLES})
        self.assertEqual(result["roles"]["music"]["scores"]["si_sdr_db"], -120)
        self.assertEqual(result["roles"]["music"]["scores"]["snr_db"], 0)
        self.assertFalse(result["numerical_gate_passed"])

    def test_silent_references_use_absolute_energy_not_infinite_sdr(self):
        truth = {**self.truth, "dialogue": self.mix * 0}
        result = self.evaluate(truth, truth=truth, mixture=sum(truth.values()))
        dialogue = result["roles"]["dialogue"]
        self.assertFalse(dialogue["reference_active"])
        self.assertIsNone(dialogue["scores"])
        self.assertTrue(dialogue["numerical_gate_passed"])
        json.dumps(result, allow_nan=False)

    def test_hallucinated_dialogue_fails_even_with_correct_sum(self):
        truth = {**self.truth, "dialogue": self.mix * 0}
        estimates = {**truth, "dialogue": self.truth["music"] * .1, "music": self.truth["music"] * .9}
        result = self.evaluate(estimates, truth=truth, mixture=sum(truth.values()))
        self.assertTrue(result["mix_consistency"]["passed"])
        self.assertIn("energy_in_reference_silence", result["roles"]["dialogue"]["findings"])

    def test_silent_windows_are_checked_inside_an_active_reference(self):
        reference = self.truth["music"].copy()
        reference[:4_000] = 0
        estimate = reference.copy()
        estimate[:4_000] = .002
        result = stem_metrics(reference, estimate, reference + self.truth["sfx"], 8_000, Gates())
        self.assertTrue(result["reference_active"])
        self.assertEqual(result["silence"]["window_count"], 2)
        self.assertFalse(result["numerical_gate_passed"])

    def test_single_active_source_has_no_impossible_improvement_requirement(self):
        truth = {"music": self.truth["music"], "dialogue": self.mix * 0, "sfx": self.mix * 0}
        result = self.evaluate(truth, truth=truth, mixture=truth["music"])
        self.assertTrue(result["numerical_gate_passed"])
        self.assertEqual(result["roles"]["music"]["si_sdr_improvement_db"], 0)

    def test_dependent_references_disable_projection_diagnostic(self):
        truth = {**self.truth, "dialogue": self.truth["music"] * 2}
        result = self.evaluate(truth, truth=truth, mixture=sum(truth.values()))
        self.assertFalse(result["source_projection"]["available"])

    def test_dc_only_reference_does_not_get_a_fake_si_sdr(self):
        reference = np.ones_like(self.mix) * .1
        result = stem_metrics(reference, reference, reference, 8_000, Gates())
        self.assertIsNone(result["scores"]["si_sdr_db"])
        self.assertFalse(result["numerical_gate_passed"])

    def test_delays_and_stereo_errors_are_not_automatically_corrected(self):
        for estimate in (np.roll(self.truth["music"], 417, axis=0), self.truth["music"][:, ::-1]):
            with self.subTest(kind="shift-or-stereo"):
                result = stem_metrics(self.truth["music"], estimate, self.mix, 8_000, Gates())
                self.assertLess(result["scores"]["snr_db"], 50)

    def test_mismatched_lengths_channels_or_roles_are_rejected(self):
        for change in (self.truth["music"][:-1], self.truth["music"][:, :1]):
            with self.subTest(shape=change.shape), self.assertRaises(ValueError):
                self.evaluate({**self.truth, "music": change})
        with self.assertRaises(ValueError):
            self.evaluate({"music": self.truth["music"]})

    def test_nan_infinity_and_empty_audio_are_rejected(self):
        for samples in (np.array([]), np.array([np.nan]), np.array([np.inf]), np.ones(8_000) * 1e100):
            with self.subTest(shape=samples.shape), self.assertRaises(ValueError):
                self.evaluate({**self.truth, "music": samples})

    def test_invalid_mixture_or_silence_is_not_a_benchmark(self):
        with self.assertRaisesRegex(ValueError, "rekonstruieren"):
            self.evaluate(self.truth, mixture=self.mix * .9)
        with self.assertRaisesRegex(ValueError, "Stummer Mix"):
            self.evaluate({role: self.mix * 0 for role in ROLES},
                           truth={role: self.mix * 0 for role in ROLES}, mixture=self.mix * 0)

    def test_gate_limits_are_explicit_and_finite(self):
        for options in ({"minimum_snr_db": float("nan")}, {"maximum_silent_rms": float("inf")},
                        {"minimum_snr_db": True}, {"minimum_snr_db": "10"},
                        {"maximum_mix_residual_ratio": -1}, {"minimum_si_sdr_improvement_db": -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                Gates(**options).validate()


if __name__ == "__main__":
    unittest.main()

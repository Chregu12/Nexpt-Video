from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

import separation_benchmark as benchmark
from separation_benchmark_fixtures import control_estimates, diagnostic_corpus
from separation_metrics import Gates, ROLES


class CorpusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.destination = self.root / "corpus"
        times = np.arange(8_000) / 8_000
        for role, frequency in zip(ROLES, (113, 251, 379)):
            value = (.1 * np.sin(2 * np.pi * frequency * times)).astype(np.float32)
            wavfile.write(self.root / f"{role}.wav", 8_000, np.column_stack((value, value)))
        self.spec = {"schema_version": 1, "cases": [{
            "id": "test", "reference_kind": "synthetic-diagnostic",
            "stems": {role: {"path": f"{role}.wav", "license": "test fixture",
                              "attribution": "generated sine"} for role in ROLES}}]}
        self.spec_path = self.root / "spec.json"

    def build(self, spec=None):
        self.spec_path.write_text(json.dumps(self.spec if spec is None else spec))
        return benchmark.build_corpus(self.spec_path, self.destination)

    def assert_unpublished(self):
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob(".separation-benchmark-*")))

    def test_build_is_portable_preserves_sources_and_rechecks_hashes(self):
        before = {role: (self.root / f"{role}.wav").read_bytes() for role in ROLES}
        result = self.build()
        self.assertEqual(result, benchmark.load_corpus(self.destination / "corpus.json"))
        for role in ROLES:
            self.assertEqual(before[role], (self.root / f"{role}.wav").read_bytes())
        moved = self.root / "moved"
        shutil.move(self.destination, moved)
        self.assertEqual(result["corpus_id"], benchmark.load_corpus(moved / "corpus.json")["corpus_id"])

    def test_null_role_is_explicit_silence(self):
        self.spec["cases"][0]["stems"]["dialogue"] = None
        result = self.build()
        _, samples = wavfile.read(self.destination / result["cases"][0]["stems"]["dialogue"]["path"])
        self.assertEqual(np.max(np.abs(samples)), 0)
        self.assertTrue(result["cases"][0]["provenance"]["dialogue"]["declared_absent"])

    def test_shared_gain_does_not_independently_normalize_stems(self):
        self.spec["cases"][0]["mix_gain"] = .5
        self.build()
        _, source = wavfile.read(self.root / "music.wav")
        _, reference = wavfile.read(self.destination / "cases/test/music.wav")
        np.testing.assert_array_equal(reference, source * .5)

    def test_clipping_is_rejected_without_changing_originals(self):
        self.spec["cases"][0]["stems"] = {role: self.spec["cases"][0]["stems"]["music"] for role in ROLES}
        wavfile.write(self.root / "music.wav", 8_000, np.ones((8_000, 2), dtype=np.float32) * .4)
        with self.assertRaisesRegex(benchmark.BenchmarkError, "0 dBFS"):
            self.build()
        self.assert_unpublished()

    def test_mismatched_rates_lengths_and_channels_are_rejected(self):
        for rate, shape in ((16_000, (16_000, 2)), (8_000, (8_001, 2)), (8_000, (8_000,))):
            wavfile.write(self.root / "sfx.wav", rate, np.zeros(shape, dtype=np.float32))
            with self.subTest(rate=rate, shape=shape), self.assertRaises(benchmark.BenchmarkError):
                self.build()
            self.assert_unpublished()

    def test_empty_or_too_long_cases_are_rejected(self):
        for frames in (0, 7_999, 31 * 8_000):
            wavfile.write(self.root / "music.wav", 8_000, np.zeros((frames, 2), dtype=np.float32))
            with self.subTest(frames=frames), self.assertRaises(benchmark.BenchmarkError):
                self.build()
            self.assert_unpublished()

    def test_invalid_specs_and_duplicate_ids_do_not_publish(self):
        original = copy.deepcopy(self.spec)
        invalid = [[], {}, {**original, "cases": []}, {**original, "cases": original["cases"] * 2},
                   {**original, "cases": [None]}]
        for identifier in ("../escape", "bad/id", "", "UPPER"):
            invalid.append({**original, "cases": [{**original["cases"][0], "id": identifier}]})
        for spec in invalid:
            with self.subTest(spec=spec), self.assertRaises(benchmark.BenchmarkError):
                self.build(spec)
            self.assert_unpublished()

    def test_missing_license_estimated_truth_and_invalid_gain_are_rejected(self):
        original = copy.deepcopy(self.spec)
        for change in ({"reference_kind": "estimated-stems"}, {"reference_kind": []},
                       {"mix_gain": float("nan")}, {"mix_gain": True}, {"mix_gain": 0},
                       {"stems": {role: None for role in ROLES}},
                       {"stems": {**original["cases"][0]["stems"], "music": {"path": "music.wav"}}}):
            with self.subTest(change=change), self.assertRaises(benchmark.BenchmarkError):
                self.build({**original, "cases": [{**original["cases"][0], **change}]})
            self.assert_unpublished()

    def test_existing_output_is_never_overwritten(self):
        self.destination.mkdir()
        keep = self.destination / "keep.txt"
        keep.write_text("keep")
        with self.assertRaisesRegex(benchmark.BenchmarkError, "existiert bereits"):
            self.build()
        self.assertEqual(keep.read_text(), "keep")

    def test_mutated_reference_or_manifest_is_rejected(self):
        corpus = self.build()
        path = self.destination / "cases/test/music.wav"
        original = path.read_bytes()
        path.write_bytes(original + b"changed")
        with self.assertRaisesRegex(benchmark.BenchmarkError, "Hash"):
            benchmark.load_corpus(self.destination / "corpus.json")
        path.write_bytes(original)
        corpus["cases"][0]["reference_kind"] = "isolated-recordings"
        (self.destination / "corpus.json").write_text(json.dumps(corpus))
        with self.assertRaisesRegex(benchmark.BenchmarkError, "Identitaet"):
            benchmark.load_corpus(self.destination / "corpus.json")

    def test_corpus_references_cannot_escape_bundle(self):
        corpus = self.build()
        for value in (str(self.root / "music.wav"), "../music.wav"):
            modified = copy.deepcopy(corpus)
            modified["cases"][0]["stems"]["music"]["path"] = value
            modified["corpus_id"] = benchmark._digest({k: v for k, v in modified.items() if k != "corpus_id"})
            (self.destination / "corpus.json").write_text(json.dumps(modified))
            with self.subTest(value=value), self.assertRaisesRegex(benchmark.BenchmarkError, "innerhalb"):
                benchmark.load_corpus(self.destination / "corpus.json")

    def test_deterministic_fixture_corpus_has_identical_identity(self):
        left = diagnostic_corpus(self.root / "left")
        right = diagnostic_corpus(self.root / "right")
        self.assertEqual(left, right)
        self.assertTrue(all(case["reference_kind"] == "synthetic-diagnostic" for case in left["cases"]))


class BenchmarkEvaluationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.corpus_dir = self.root / "corpus"
        self.corpus = diagnostic_corpus(self.corpus_dir)
        self.corpus_path = self.corpus_dir / "corpus.json"
        self.estimates = self.root / "estimates"
        control_estimates(self.corpus_dir, self.corpus, self.estimates, "oracle")

    def evaluate(self, name="result", gates=None):
        return benchmark.evaluate_corpus(self.corpus_path, self.estimates, self.root / name, name=name, gates=gates)

    def test_per_role_metrics_are_recorded_without_quality_claim(self):
        result = self.evaluate()
        self.assertEqual(result["summary"]["total_cases"], 3)
        self.assertTrue(result["summary"]["numerical_gate_passed"])
        self.assertFalse(result["perceptual_quality_verified"])
        self.assertEqual(result["candidate"]["kind"], "external-unverified")
        self.assertEqual(result["summary"]["roles"]["dialogue"]["silent_cases"], 2)
        self.assertEqual(result["summary"]["roles"]["dialogue"]["median_worst_silent_window_rms"], 0)
        self.assertEqual(result["report_id"], benchmark._digest({k: v for k, v in result.items() if k != "report_id"}))

    def test_missing_stem_keeps_failed_case_and_denominator(self):
        (self.estimates / "overlap/sfx.wav").unlink()
        result = self.evaluate()
        self.assertEqual(result["summary"]["failed_cases"], 1)
        self.assertEqual(result["summary"]["total_cases"], 3)
        self.assertFalse(result["summary"]["numerical_gate_passed"])
        self.assertEqual(result["cases"][0]["status"], "failed")

    def test_wrong_rate_short_nonfinite_and_corrupt_estimates_are_failures(self):
        path = self.estimates / "overlap/music.wav"
        before = path.read_bytes()
        for rate, array in ((48_000, np.zeros((88_200, 2))), (44_100, np.zeros((44_100, 2))),
                             (44_100, np.full((88_200, 2), np.nan))):
            wavfile.write(path, rate, array.astype(np.float32))
            with self.subTest(rate=rate, frames=len(array)):
                result = self.evaluate(f"result-{rate}-{len(array)}-{np.isfinite(array).all()}")
                self.assertEqual(result["summary"]["failed_cases"], 1)
        path.write_bytes(b"not a WAV")
        self.assertEqual(self.evaluate("corrupt")["summary"]["failed_cases"], 1)
        path.write_bytes(before)

    def test_reference_changes_mid_evaluation_invalidate_whole_run(self):
        original = benchmark.evaluate_arrays

        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            if not getattr(mutate, "changed", False):
                path = self.corpus_dir / "cases/overlap/music.wav"
                path.write_bytes(path.read_bytes() + b"concurrent edit")
                mutate.changed = True
            return result

        with mock.patch.object(benchmark, "evaluate_arrays", side_effect=mutate):
            with self.assertRaises(benchmark.BenchmarkError):
                self.evaluate()
        self.assertFalse((self.root / "result").exists())
        self.assertFalse(list(self.root.glob(".separation-benchmark-*")))

    def test_paired_comparison_and_incomplete_cases(self):
        self.evaluate("left")
        self.evaluate("right")
        paths = [self.root / label / "report.json" for label in ("left", "right")]
        result = benchmark.compare_reports(paths)
        self.assertTrue(result["complete"])
        self.assertIsNone(result["overall_winner"])
        self.assertEqual(result["pairs"][0]["right_minus_left"]["music"]["snr_db_delta"], 0)
        self.assertEqual(result["pairs"][0]["right_minus_left"]["dialogue"]["silent_window_rms_delta"], 0)
        (self.estimates / "overlap/music.wav").unlink()
        self.evaluate("missing")
        result = benchmark.compare_reports([paths[0], self.root / "missing/report.json"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["incomplete_cases"], ["overlap"])

    def test_silent_role_comparison_reports_energy_instead_of_fake_sdr(self):
        self.evaluate("oracle")
        leakage = self.root / "leakage"
        control_estimates(self.corpus_dir, self.corpus, leakage, "silence-leak")
        benchmark.evaluate_corpus(self.corpus_path, leakage, self.root / "leak-report")
        comparison = benchmark.compare_reports([self.root / "leak-report/report.json", self.root / "oracle/report.json"])
        row = next(item for item in comparison["pairs"] if item["id"] == "music-only")
        dialogue = row["right_minus_left"]["dialogue"]
        self.assertIsNone(dialogue["snr_db_delta"])
        self.assertLess(dialogue["silent_window_rms_delta"], 0)
        self.assertFalse(dialogue["left_gate_passed"])
        self.assertTrue(dialogue["right_gate_passed"])

    def test_different_gates_corpora_versions_or_tampered_reports_cannot_compare(self):
        original = self.evaluate("left")
        left_path = self.root / "left/report.json"
        self.evaluate("other-gates", Gates(minimum_snr_db=15))
        with self.assertRaisesRegex(benchmark.BenchmarkError, "gate_profile"):
            benchmark.compare_reports([left_path, self.root / "other-gates/report.json"])
        right_path = self.root / "right.json"
        for field in ("corpus_id", "metric_version", "metric_implementation_sha256", "benchmark_implementation_sha256"):
            changed = {k: v for k, v in original.items() if k != "report_id"}
            changed[field] = "different"
            right_path.write_text(json.dumps(benchmark._seal(changed)))
            with self.subTest(field=field), self.assertRaisesRegex(benchmark.BenchmarkError, field):
                benchmark.compare_reports([left_path, right_path])
        right_path.write_text(json.dumps({**original, "corpus_id": "tampered"}))
        with self.assertRaisesRegex(benchmark.BenchmarkError, "veraenderter"):
            benchmark.compare_reports([left_path, right_path])


if __name__ == "__main__":
    unittest.main()

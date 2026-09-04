"""CLI integration and real ffmpeg; CDX is explicitly a test double here."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

from cdx_fixtures import make_cdx_fixture
from separation_benchmark_fixtures import diagnostic_corpus


class BenchmarkCLITests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, "render/separation_benchmark.py", *map(str, args)],
                              cwd=ROOT, text=True, capture_output=True, timeout=60)

    def test_self_test_exposes_false_positives_of_sum_only_and_preserves_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bundle with spaces"
            result = self.cli("self-test", "--output-dir", destination)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["self_test_passed"])
            self.assertFalse(report["model_inference_executed"])
            self.assertFalse(report["perceptual_quality_verified"])
            for label in ("swapped", "equal-split", "silence-leak"):
                self.assertTrue(report["controls"][label]["all_sums_passed"])
                self.assertFalse(report["controls"][label]["observed_gate_passed"])
            before = (destination / "self-test.json").read_bytes()
            repeat = self.cli("self-test", "--output-dir", destination)
            self.assertEqual(repeat.returncode, 1)
            self.assertEqual((destination / "self-test.json").read_bytes(), before)
            self.assertFalse(list(Path(directory).glob(".separation-benchmark-*")))

    def test_evaluate_strict_and_paired_compare_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self.cli("self-test", "--output-dir", root / "controls").returncode, 0)
            corpus = root / "controls/corpus/corpus.json"
            for label, expected in (("oracle", 0), ("swapped", 2)):
                result = self.cli("evaluate", corpus, "--estimates-dir", root / f"controls/controls/{label}/estimates",
                                  "--output-dir", root / label, "--name", label, "--strict")
                self.assertEqual(result.returncode, expected, result.stderr)
            comparison = self.cli("compare", root / "swapped/report.json", root / "oracle/report.json",
                                   "--output-dir", root / "comparison")
            self.assertEqual(comparison.returncode, 0, comparison.stderr)
            self.assertTrue(json.loads(comparison.stdout)["complete"])

    def test_real_cdx_cli_contract_can_pass_sum_but_fail_known_stems(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, config = make_cdx_fixture(root)
            diagnostic_corpus(root / "corpus")
            result = self.cli("run-cdx", root / "corpus/corpus.json", "--cdx-config", config,
                              "--output-dir", root / "result", "--timeout", "20", "--strict")
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["failed_cases"], 0)
            self.assertFalse(report["summary"]["numerical_gate_passed"])
            self.assertEqual(len(report["candidate"]["attempts"]), 3)
            self.assertTrue(all(row["metrics"]["mix_consistency"]["passed"] for row in report["cases"]))
            self.assertFalse(report["perceptual_quality_verified"])
            for row in report["cases"]:
                for stem in row["estimates"].values():
                    self.assertTrue((root / "result/estimates" / stem["path"]).is_file())
            self.assertFalse(list(root.glob(".separation-benchmark-*")))

    def test_failed_inference_keeps_every_case_in_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, config = make_cdx_fixture(root, "fail")
            diagnostic_corpus(root / "corpus")
            result = self.cli("run-cdx", root / "corpus/corpus.json", "--cdx-config", config,
                              "--output-dir", root / "result")
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["total_cases"], 3)
            self.assertEqual(report["summary"]["failed_cases"], 3)
            self.assertTrue(all("fixture inference failed" in row["error"] for row in report["cases"]))
            self.assertIsNone(report["summary"]["roles"]["music"]["median_snr_db"])

    def test_missing_model_configuration_fails_without_creating_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diagnostic_corpus(root / "corpus")
            result = self.cli("run-cdx", root / "corpus/corpus.json", "--cdx-config", root / "absent.json",
                              "--output-dir", root / "result")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse((root / "result").exists())
            self.assertEqual(json.loads(result.stdout)["status"], "failed")

    def test_opted_in_live_test_without_requirements_fails_instead_of_skipping(self):
        environment = {**os.environ, "NEXPT_RUN_KNOWN_STEMS_LIVE": "1", "NEXPT_CDX_CONFIG": "",
                       "NEXPT_KNOWN_STEM_CORPUS": ""}
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                                 "-p", "test_separation_benchmark_live.py", "-v"],
                                cwd=ROOT, env=environment, text=True, capture_output=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set NEXPT_CDX_CONFIG", result.stderr)
        self.assertNotIn("skipped", result.stderr)


if __name__ == "__main__":
    unittest.main()

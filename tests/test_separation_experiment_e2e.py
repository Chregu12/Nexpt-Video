"""Process/CLI/FFmpeg integration; runtime readiness and CDX models are doubles."""
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

from experiment_fixtures import make_experiment_fixture


class ExperimentCLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.corpus, self.config = make_experiment_fixture(self.root, case_count=1)
        self.output = self.root / "experiment with spaces"

    def cli(self, *args, fixture=False):
        script = "tests/experiment_fixtures.py" if fixture else "render/separation_benchmark.py"
        environment = {**os.environ, "NEXPT_CDX_CONFIG": "", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        return subprocess.run([sys.executable, script, *map(str, args)], cwd=ROOT, env=environment,
                              capture_output=True, text=True, timeout=90)

    def run_ab(self, *extra):
        return self.cli("run-ab", self.corpus, "--cdx-config", self.config, "--output-dir", self.output, *extra, fixture=True)

    def test_real_preflight_blocks_missing_runtime_without_creating_fake_results(self):
        result = self.cli("run-ab", self.corpus, "--cdx-config", self.root / "missing.json", "--output-dir", self.output)
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["model_inference_executed"])
        self.assertFalse(self.output.exists())

    def test_partial_cli_resume_runs_remaining_profiles_and_keeps_original_report(self):
        first = self.run_ab("--repeats", "2", "--max-new-runs", "1")
        self.assertEqual(first.returncode, 2, first.stdout + first.stderr)
        partial = json.loads(first.stdout)
        self.assertEqual(partial["completed_runs"], 1)
        self.assertEqual(partial["pending_case_attempts"], 3)
        path = self.output / "runs/trial-01-standard/report.json"
        before = path.read_bytes()
        resumed = self.run_ab("--repeats", "2", "--resume")
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        report = json.loads(resumed.stdout)
        self.assertEqual(report["completed_runs"], 4)
        self.assertEqual(report["evaluated_case_attempts"], 4)
        self.assertFalse(report["perceptual_quality_verified"])
        self.assertIsNone(report["overall_winner"])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(report["pairs"]), 2)
        self.assertTrue((self.output / "runs/trial-02-high/completion.json").is_file())
        self.assertFalse(list((self.output / "runs").glob(".separation-benchmark-*")))

    def test_strict_cli_keeps_complete_but_bad_quality_measurements(self):
        result = self.run_ab("--repeats", "1", "--strict")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "complete")
        self.assertFalse(report["numerical_gate_passed"])
        self.assertEqual(report["failed_case_attempts"], [])
        self.assertTrue((self.output / "runs/trial-01-high/report.json").is_file())
        self.assertEqual(self.cli("summarize-ab", self.output, "--strict").returncode, 2)

    def test_failed_model_processes_are_not_dropped_or_retried(self):
        failed_root = self.root / "failed-model"
        failed_root.mkdir()
        self.corpus, self.config = make_experiment_fixture(failed_root, mode="fail", case_count=1)
        result = self.run_ab("--repeats", "1")
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["completed_runs"], 2)
        self.assertEqual(report["evaluated_case_attempts"], 0)
        self.assertEqual(len(report["failed_case_attempts"]), 2)
        self.assertEqual(report["pending_jobs"], [])
        repeated = self.run_ab("--repeats", "1", "--resume")
        self.assertEqual(repeated.returncode, 2, repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout), report)

    def test_offline_summary_needs_no_model_config_or_original_source(self):
        initial = self.run_ab("--repeats", "1")
        self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
        self.config.unlink()
        self.corpus.rename(self.corpus.with_suffix(".saved"))
        summary = self.cli("summarize-ab", self.output)
        self.assertEqual(summary.returncode, 0, summary.stdout + summary.stderr)
        self.assertEqual(json.loads(initial.stdout), json.loads(summary.stdout))

    def test_corrupt_saved_audio_fails_cli_without_overwriting_evidence(self):
        self.assertEqual(self.run_ab("--repeats", "1", "--max-new-runs", "1").returncode, 2)
        path = self.output / "runs/trial-01-standard/estimates/overlap/music.wav"
        tampered = path.read_bytes() + b"changed"
        path.write_bytes(tampered)
        result = self.cli("summarize-ab", self.output)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")
        self.assertEqual(path.read_bytes(), tampered)
        self.assertFalse((self.output / "runs/trial-01-high").exists())


if __name__ == "__main__":
    unittest.main()

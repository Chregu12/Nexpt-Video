"""CLI/process tests for blind review; CDX remains an explicit fixture."""
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


class ListeningCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.corpus, self.config = make_experiment_fixture(self.root, case_count=1)
        self.experiment = self.root / "experiment with spaces"
        self.kit = self.root / "blind kit with spaces"
        result = self.fixture("run-ab", self.corpus, "--cdx-config", self.config,
                              "--output-dir", self.experiment, "--repeats", "1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def process(self, script, *args):
        environment = {**os.environ, "NEXPT_CDX_CONFIG": "", "OPENBLAS_NUM_THREADS": "1",
                       "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        return subprocess.run([sys.executable, script, *map(str, args)], cwd=ROOT,
                              env=environment, capture_output=True, text=True, timeout=90)

    def fixture(self, *args):
        return self.process("tests/experiment_fixtures.py", *args)

    def cli(self, *args):
        return self.process("render/separation_listening.py", *args)

    def build(self):
        return self.cli("build", self.experiment, self.corpus,
                        "--output-dir", self.kit)

    def completed_review(self):
        review = json.loads((self.kit / "public/review-template.json").read_text())
        key = json.loads((self.kit / "private/key.json").read_text())
        mappings = {row["id"]: row["candidates"] for row in key["mappings"]}
        review["reviewer_id"] = "cli-reviewer"
        review["playback"] = {"device": "headphones", "environment": "quiet"}
        for row in review["items"]:
            labels = {candidate["quality"]: label
                      for label, candidate in mappings[row["id"]].items()}
            row["preference"] = labels["high"]
            row["confidence"] = 5
            for criterion in row["ratings"]["A"]:
                row["ratings"][labels["high"]][criterion] = 5
                row["ratings"][labels["standard"]][criterion] = 2
        path = self.root / "completed review.json"
        path.write_text(json.dumps(review))
        return path

    def test_build_cli_outputs_shareable_blind_package_without_running_a_model(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["items"], 3)
        self.assertFalse(report["model_inference_executed"])
        self.assertTrue((self.kit / "public/README.md").is_file())
        self.assertTrue((self.kit / "private/key.json").is_file())
        public_metadata = "\n".join(path.read_text()
                                    for path in (self.kit / "public").glob("*.json"))
        self.assertNotIn('"standard"', public_metadata)
        self.assertNotIn('"high"', public_metadata)

    def test_completed_review_cli_is_unblinded_saved_and_remains_non_decisive(self):
        self.assertEqual(self.build().returncode, 0)
        review = self.completed_review()
        output = self.root / "listening summary"
        result = self.cli("summarize", self.kit, review,
                          "--experiment", self.experiment, "--corpus", self.corpus,
                          "--output-dir", output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["overall"]["preference_counts"]["high"], 3)
        self.assertEqual(report["overall"]["high_minus_standard"]["artifact_free"]["median"], 3)
        self.assertFalse(report["perceptual_quality_verified"])
        self.assertIsNone(report["overall_winner"])
        self.assertEqual(report, json.loads((output / "listening-summary.json").read_text()))

    def test_unfilled_template_is_a_failure_and_publishes_no_summary(self):
        self.assertEqual(self.build().returncode, 0)
        output = self.root / "invalid summary"
        result = self.cli("summarize", self.kit,
                          self.kit / "public/review-template.json",
                          "--experiment", self.experiment, "--corpus", self.corpus,
                          "--output-dir", output)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")
        self.assertFalse(output.exists())

    def test_incomplete_experiment_cannot_be_packaged_by_cli(self):
        work = self.root / "partial"
        work.mkdir()
        corpus, config = make_experiment_fixture(work, case_count=1)
        experiment = work / "experiment"
        partial = self.fixture("run-ab", corpus, "--cdx-config", config,
                               "--output-dir", experiment, "--repeats", "2",
                               "--max-new-runs", "1")
        self.assertEqual(partial.returncode, 2, partial.stdout + partial.stderr)
        destination = work / "kit"
        result = self.cli("build", experiment, corpus, "--output-dir", destination)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("vollstaendigen", json.loads(result.stdout)["error"])
        self.assertFalse(destination.exists())

    def test_tampered_candidate_fails_before_unblinding_or_writing_output(self):
        self.assertEqual(self.build().returncode, 0)
        review = self.completed_review()
        candidate = self.kit / "public/audio/items/item-0001/A.wav"
        candidate.write_bytes(candidate.read_bytes() + b"tampered")
        output = self.root / "tampered summary"
        result = self.cli("summarize", self.kit, review,
                          "--experiment", self.experiment, "--corpus", self.corpus,
                          "--output-dir", output)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")
        self.assertFalse(output.exists())

    def test_summary_output_inside_immutable_kit_is_refused(self):
        self.assertEqual(self.build().returncode, 0)
        review = self.completed_review()
        result = self.cli("summarize", self.kit, review,
                          "--experiment", self.experiment, "--corpus", self.corpus,
                          "--output-dir", self.kit / "summary")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("unveraenderliche", json.loads(result.stdout)["error"])
        self.assertEqual({path.name for path in self.kit.iterdir()}, {"public", "private"})


if __name__ == "__main__":
    unittest.main()

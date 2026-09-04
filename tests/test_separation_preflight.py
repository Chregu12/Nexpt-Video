"""Readiness contracts; all model runtimes and 'recording' labels are test doubles."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

from cinematic_separation import CDX_CHECKPOINTS, CdxSeparator, sha256
from cdx_fixtures import make_cdx_fixture
from separation_benchmark import BenchmarkError, _digest
from separation_benchmark_fixtures import diagnostic_corpus
import separation_preflight as checks


class PreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.corpus_dir = self.root / "corpus"
        self.corpus = diagnostic_corpus(self.corpus_dir)
        self.corpus_path = self.corpus_dir / "corpus.json"
        # Move the first transient into the active dialogue region so this
        # fixture exercises the preflight's simultaneous-overlap requirement.
        overlap = self.corpus["cases"][0]
        sfx_path = self.corpus_dir / overlap["stems"]["sfx"]["path"]
        rate, sfx = wavfile.read(sfx_path)
        sfx = np.roll(sfx, rate // 2, axis=0)
        wavfile.write(sfx_path, rate, sfx)
        overlap["stems"]["sfx"]["sha256"] = sha256(sfx_path)
        arrays = []
        for role in ("music", "dialogue", "sfx"):
            _, audio = wavfile.read(self.corpus_dir / overlap["stems"][role]["path"])
            arrays.append(audio)
        mix_path = self.corpus_dir / overlap["mix"]["path"]
        wavfile.write(mix_path, rate, sum(arrays))
        overlap["mix"]["sha256"] = sha256(mix_path)
        # Author declarations can only be checked structurally. These are still
        # generated unit fixtures, never actual-recording acoustic evidence.
        for case in self.corpus["cases"]:
            case["reference_kind"] = "isolated-recordings"
        self.save_corpus()
        self.repo, self.config = make_cdx_fixture(self.root)
        self.settings = json.loads(self.config.read_text())
        self.settings.update({"runner": "safe-pytorch", "runtime_lock": "a" * 64})
        self.save_config()
        self.runtime = {"fingerprint": "a" * 64, "dependencies_ready": True, "missing_or_broken": [],
                        "cuda_available": False, "restricted_checkpoint_loader": True, "runtime_verified": False}
        self.probe = self.enterContext(mock.patch.object(checks, "probe_runtime", return_value=self.runtime))
        self.separate = self.enterContext(mock.patch.object(CdxSeparator, "separate", side_effect=AssertionError("Preflight must not infer")))

    def save_corpus(self):
        self.corpus["corpus_id"] = _digest({k: v for k, v in self.corpus.items() if k != "corpus_id"})
        self.corpus_path.write_text(json.dumps(self.corpus))

    def save_config(self):
        self.config.write_text(json.dumps(self.settings))

    def check(self, **kwargs):
        return checks.preflight(self.corpus_path, config=self.config, **kwargs)

    def codes(self, report):
        return {row["code"] for row in report["blockers"]}

    def test_ready_checks_both_profiles_without_claiming_inference_or_quality(self):
        report = self.check()
        self.assertTrue(report["ready_for_run"])
        self.assertTrue(report["reference_ready"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(set(report["profiles"]), {"standard", "high"})
        self.assertEqual(report["coverage"]["music_only_cases"], 1)
        self.assertEqual(report["coverage"]["music_sfx_without_dialogue_cases"], 1)
        self.assertEqual(report["coverage"]["three_role_overlap_cases"], 1)
        self.assertEqual(report["coverage"]["active_case_counts"], {"music": 3, "dialogue": 1, "sfx": 2})
        self.assertFalse(report["runtime_verified"])
        self.assertFalse(report["model_inference_executed"])
        self.assertFalse(report["perceptual_quality_verified"])
        self.assertFalse(report["coverage"]["source_labels_verified"])
        self.assertEqual(report["report_id"], _digest({k: v for k, v in report.items() if k != "report_id"}))
        self.probe.assert_called_once_with(sys.executable)
        self.separate.assert_not_called()

    def test_synthetic_corpus_is_blocked_despite_complete_energy_coverage(self):
        self.corpus["cases"][0]["reference_kind"] = "synthetic-diagnostic"
        self.save_corpus()
        report = self.check()
        self.assertFalse(report["ready_for_run"])
        self.assertFalse(report["reference_ready"])
        self.assertIn("diagnostic_references", self.codes(report))

    def test_music_only_corpus_does_not_claim_dialogue_or_sfx_coverage(self):
        self.corpus["cases"] = [x for x in self.corpus["cases"] if x["id"] == "music-only"]
        self.save_corpus()
        report = self.check()
        self.assertEqual(report["coverage"]["total_cases"], 1)
        self.assertEqual(report["coverage"]["active_case_counts"]["dialogue"], 0)
        self.assertIn("three_role_overlap_cases", self.codes(report))
        self.assertIn("music_sfx_without_dialogue_cases", self.codes(report))
        self.assertNotIn("music_only_cases", self.codes(report))

    def test_absent_music_only_negative_control_is_reported(self):
        self.corpus["cases"] = [x for x in self.corpus["cases"] if x["id"] != "music-only"]
        self.save_corpus()
        self.assertIn("music_only_cases", self.codes(self.check()))

    def test_mono_corpus_needs_explicit_stereo_preparation(self):
        for case in self.corpus["cases"]:
            case["channels"] = 1
            for entry in (case["mix"], *case["stems"].values()):
                path = self.corpus_dir / entry["path"]
                rate, audio = wavfile.read(path)
                wavfile.write(path, rate, audio[:, 0])
                entry["sha256"] = sha256(path)
        self.save_corpus()
        self.assertIn("stereo_required", self.codes(self.check()))

    def test_bad_corpus_still_reports_backend_status(self):
        self.corpus_path.write_text("broken")
        report = self.check()
        self.assertIn("invalid_corpus", self.codes(report))
        self.assertTrue(report["profiles"]["standard"]["ready"])
        self.assertFalse(report["reference_ready"])
        self.corpus_path.unlink()
        self.assertIn("invalid_corpus", self.codes(self.check()))

    def test_missing_config_and_env_config_are_explicit(self):
        with mock.patch.dict(os.environ, {"NEXPT_CDX_CONFIG": ""}):
            report = checks.preflight(self.corpus_path)
            self.assertEqual(len(report["blockers"]), 2)
            self.assertIn("backend_unavailable", self.codes(report))
        with mock.patch.dict(os.environ, {"NEXPT_CDX_CONFIG": str(self.config)}):
            self.assertTrue(checks.preflight(self.corpus_path)["ready_for_run"])

    def test_standard_ready_does_not_hide_missing_high_checkpoint(self):
        (self.repo / "models" / CDX_CHECKPOINTS[1]).unlink()
        report = self.check()
        self.assertTrue(report["profiles"]["standard"]["ready"])
        self.assertFalse(report["profiles"]["high"]["ready"])
        self.assertFalse(report["ready_for_run"])
        self.assertTrue(self.check(profiles=("standard",))["ready_for_run"])

    def test_unsafe_legacy_runner_is_not_probed_or_executed(self):
        self.settings.pop("runner")
        self.save_config()
        self.assertIn("safe_runner_required", self.codes(self.check()))
        self.probe.assert_not_called()
        self.separate.assert_not_called()

    def test_broken_imports_loader_and_cuda_are_reported_separately(self):
        self.runtime.update({"dependencies_ready": False, "missing_or_broken": ["torch"],
                             "restricted_checkpoint_loader": False})
        codes = self.codes(self.check(device="cuda"))
        self.assertTrue({"runtime_dependencies", "restricted_loader_required", "cuda_unavailable"} <= codes)

    def test_runtime_lock_mismatch_blocks_and_absence_warns(self):
        self.settings["runtime_lock"] = "b" * 64
        self.save_config()
        self.assertIn("runtime_lock_mismatch", self.codes(self.check()))
        del self.settings["runtime_lock"]
        self.save_config()
        report = self.check()
        self.assertTrue(report["ready_for_run"])
        self.assertEqual({row["code"] for row in report["warnings"]}, {"runtime_not_locked"})

    def test_probe_exception_is_not_successful_skip(self):
        self.probe.side_effect = RuntimeError("runtime probe timeout")
        report = self.check()
        self.assertFalse(report["ready_for_run"])
        self.assertIn("backend_unavailable", self.codes(report))

    def test_source_changes_during_runtime_probe_invalidate_readiness(self):
        def changed(_):
            path = self.corpus_dir / "cases/overlap/music.wav"
            path.write_bytes(path.read_bytes() + b"change")
            return self.runtime
        self.probe.side_effect = changed
        report = self.check()
        self.assertIn("corpus_changed", self.codes(report))
        self.assertFalse(report["reference_ready"])

    def test_config_changes_during_probe_invalidate_affected_profile(self):
        def changed(_):
            self.settings["checkpoint_license"] = "changed metadata"
            self.save_config()
            return self.runtime
        self.probe.side_effect = changed
        report = self.check()
        self.assertIn("backend_changed", self.codes(report))
        self.assertFalse(report["profiles"]["standard"]["ready"])

    def test_missing_decoder_and_invalid_profile_options(self):
        with mock.patch.object(checks, "executable", return_value=None):
            report = self.check()
        self.assertTrue({"missing_ffmpeg", "missing_ffprobe"} <= self.codes(report))
        for options in ({"profiles": ()}, {"profiles": ("standard", "standard")},
                        {"profiles": ("bad",)}, {"device": "mps"}):
            with self.subTest(options=options), self.assertRaises(BenchmarkError):
                self.check(**options)

    def test_disabled_restricted_loading_is_a_preflight_blocker(self):
        with mock.patch.dict(os.environ, {"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "YES"}):
            report = self.check()
        self.assertFalse(report["ready_for_run"])
        self.assertIn("unsafe_loader_environment", self.codes(report))
        self.separate.assert_not_called()


if __name__ == "__main__":
    unittest.main()

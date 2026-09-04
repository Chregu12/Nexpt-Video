"""Real ffmpeg/CLI contracts with a deterministic CDX stand-in, not live ML."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

import cdx_runtime as runtime
from cinematic_separation import cdx_status
from music_separation import SeparationError
from video_music import VideoMusicError
from cdx_fixtures import make_cdx_fixture
from test_cdx_runtime import ready_probe


class SmokeContractE2ETests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repo, self.config = make_cdx_fixture(self.root)
        self.source = self.root / "source with spaces.wav"
        times = np.arange(3 * 48_000) / 48_000
        tone = (.1 * np.sin(2 * np.pi * 440 * times)).astype(np.float32)
        wavfile.write(self.source, 48_000, np.column_stack((tone, tone)))
        self.destination = self.root / "smoke bundle"
        patcher = mock.patch.object(runtime, "probe_runtime", return_value=ready_probe())
        self.probe = patcher.start()
        self.addCleanup(patcher.stop)

    def smoke(self, **kwargs):
        return runtime.smoke_test(self.source, config=self.config,
                                  output_dir=self.destination, seconds=1, **kwargs)

    def assert_not_published(self):
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob(".cdx-smoke-*")))

    def test_transactional_bundle_and_relocated_receipt_verify(self):
        before = self.source.read_bytes()
        result = self.smoke(start_seconds=1)
        receipt = self.destination / "smoke-result.json"
        self.assertEqual(result, json.loads(receipt.read_text()))
        self.assertTrue(result["runtime_verified"])
        self.assertFalse(result["model_accuracy_verified"])
        self.assertFalse(result["runtime"]["runtime_verified"])
        self.assertEqual(result["source"]["actual_seconds"], 1)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertTrue(runtime.verify_receipt(receipt, config=self.config)["runtime_verified"])
        for entry in result["artifacts"].values():
            self.assertTrue(Path(entry["path"]).is_file())
            self.assertTrue(Path(entry["path"]).is_relative_to(self.destination))
        manifest = json.loads((self.destination / "demixing/manifest.json").read_text())
        self.assertNotIn(".cdx-smoke-", json.dumps(result))
        self.assertNotIn(".cdx-smoke-", json.dumps(manifest))
        self.assertEqual(manifest["source"]["path"], str(self.destination / "source-excerpt.wav"))
        self.assertFalse(cdx_status(self.config)["runtime_verified"])
        self.assertTrue(cdx_status(self.config, receipt=receipt)["runtime_verified"])

    def test_rerun_preserves_all_existing_outputs(self):
        self.smoke()
        before = {p.relative_to(self.destination): p.read_bytes()
                  for p in self.destination.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(SeparationError, "existiert bereits"):
            self.smoke()
        self.assertEqual(before, {p.relative_to(self.destination): p.read_bytes()
                                 for p in self.destination.rglob("*") if p.is_file()})

    def test_changed_source_config_output_or_integration_invalidates_receipt(self):
        result = self.smoke()
        receipt = self.destination / "smoke-result.json"
        for path in (self.source, self.config, Path(result["artifacts"]["music"]["path"]),
                     Path(result["artifacts"]["decomposition_manifest"]["path"])):
            previous = path.read_bytes()
            path.write_bytes(previous + b"changed")
            with self.subTest(path=path):
                self.assertFalse(runtime.verify_receipt(receipt, config=self.config)["runtime_verified"])
            path.write_bytes(previous)
        with mock.patch.object(runtime, "_integration_identity", return_value={"changed": "hash"}):
            result = runtime.verify_receipt(receipt, config=self.config)
            self.assertFalse(result["runtime_verified"])
            self.assertIn("Integrationscode", result["reason"])

    def test_runtime_profile_and_device_must_still_match(self):
        self.smoke()
        receipt = self.destination / "smoke-result.json"
        for options in ({"quality": "high"}, {"device": "cuda"}):
            with self.subTest(options=options):
                self.assertFalse(runtime.verify_receipt(receipt, config=self.config, **options)["runtime_verified"])
        self.probe.return_value = {**ready_probe(), "fingerprint": "b" * 64}
        self.assertFalse(runtime.verify_receipt(receipt, config=self.config)["runtime_verified"])

    def test_forged_success_flags_missing_artifacts_and_malformed_json_are_rejected(self):
        original = self.smoke()
        receipt = self.destination / "smoke-result.json"
        missing = copy.deepcopy(original)
        del missing["artifacts"]["sfx"]
        for payload in ([], {}, {**original, "runtime_verified": False},
                        {**original, "model_accuracy_verified": True},
                        {**original, "mix_consistency": {"passed": False}}, missing):
            receipt.write_text(json.dumps(payload))
            with self.subTest(payload_type=type(payload)):
                self.assertFalse(runtime.verify_receipt(receipt, config=self.config)["runtime_verified"])
        receipt.write_text("not json")
        self.assertFalse(runtime.verify_receipt(receipt, config=self.config)["runtime_verified"])

    def test_missing_dependencies_and_cuda_fail_before_processing(self):
        for report, options in (({**ready_probe(), "dependencies_ready": False, "missing_or_broken": ["torch"]}, {}),
                                (ready_probe(), {"device": "cuda"})):
            self.probe.return_value = report
            with self.subTest(options=options), mock.patch("video_music._extract_wav") as extract:
                with self.assertRaises(SeparationError):
                    self.smoke(**options)
                extract.assert_not_called()
                self.assert_not_published()

    def test_runtime_changes_during_inference_publish_no_receipt(self):
        self.probe.side_effect = [ready_probe(), {**ready_probe(), "fingerprint": "b" * 64}]
        with self.assertRaisesRegex(SeparationError, "Runtime hat sich"):
            self.smoke()
        self.assert_not_published()

    def test_source_changes_during_inference_publish_no_receipt(self):
        from audio_decomposition import decompose

        def change_source(*args, **kwargs):
            report = decompose(*args, **kwargs)
            self.source.write_bytes(self.source.read_bytes() + b"concurrent change")
            return report

        with mock.patch("audio_decomposition.decompose", side_effect=change_source):
            with self.assertRaisesRegex(SeparationError, "Quelle hat sich"):
                self.smoke()
        self.assert_not_published()

    def test_model_failure_timeout_and_consistency_failure_publish_nothing(self):
        for error in ("inference failed", "Zeitlimit", "Mix-Consistency-Gate"):
            with self.subTest(error=error), mock.patch("cinematic_separation._run", side_effect=SeparationError(error)):
                with self.assertRaisesRegex(VideoMusicError, error):
                    self.smoke()
                self.assert_not_published()

    def test_bad_ranges_fail_early_and_too_short_excerpt_cleans_stage(self):
        for options in ({"seconds": .5}, {"seconds": 31}, {"seconds": float("nan")},
                        {"start_seconds": -1}, {"timeout": 0}, {"timeout": 3601},
                        {"audio_stream": -1}, {"maximum_residual_ratio": float("nan")}):
            with self.subTest(options=options), self.assertRaises(SeparationError):
                runtime.smoke_test(self.source, config=self.config, output_dir=self.destination, **options)
            self.assert_not_published()
        with self.assertRaisesRegex(SeparationError, "zu kurz"):
            self.smoke(start_seconds=2.5)
        self.assert_not_published()

    def test_cli_failure_returns_json_and_nonzero_without_false_ready(self):
        result = subprocess.run([sys.executable, "render/cdx_runtime.py", "verify",
                                 str(self.root / "missing.json"), "--cdx-config", str(self.config)],
                                cwd=ROOT, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["runtime_verified"])


if __name__ == "__main__":
    unittest.main()

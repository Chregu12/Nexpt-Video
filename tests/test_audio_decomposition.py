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

from audio_decomposition import check_stem_consistency, decompose
from cinematic_separation import CdxSeparator, CDX_CHECKPOINTS, cdx_status
from music_separation import SeparationError, _validated_wav
from video_music import VideoMusicError, build_parser
from cdx_fixtures import make_cdx_fixture


class StemConsistencyTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, dict[str, Path]]:
        mix = root / "mix.wav"
        source = np.ones((100, 2), dtype=np.float32) * .25
        wavfile.write(mix, 48_000, source)
        stems = {role: root / f"{role}.wav" for role in ("music", "dialogue", "sfx")}
        for role, gain in zip(stems, (.5, .3, .2)):
            wavfile.write(stems[role], 48_000, source * gain)
        return mix, stems

    def test_exact_sum_does_not_claim_perceptual_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            mix, stems = self.fixture(Path(directory))
            report = check_stem_consistency(mix, stems)
        self.assertTrue(report["passed"])
        self.assertLess(report["residual_to_mix_rms_ratio"], 1e-6)
        self.assertFalse(report["perceptual_separation_verified"])
        self.assertFalse(report["residual_redistributed"])

    def test_leaky_sum_fails_without_changing_any_stem(self):
        with tempfile.TemporaryDirectory() as directory:
            mix, stems = self.fixture(Path(directory))
            wavfile.write(stems["sfx"], 48_000, np.zeros((100, 2), dtype=np.float32))
            before = {role: path.read_bytes() for role, path in stems.items()}
            report = check_stem_consistency(mix, stems)
            self.assertEqual(before, {role: path.read_bytes() for role, path in stems.items()})
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["residual_to_mix_rms_ratio"], .2, places=6)

    def test_misaligned_stems_are_rejected(self):
        for rate, shape in ((44_100, (100, 2)), (48_000, (99, 2)), (48_000, (100,))):
            with self.subTest(rate=rate, shape=shape), tempfile.TemporaryDirectory() as directory:
                mix, stems = self.fixture(Path(directory))
                wavfile.write(stems["sfx"], rate, np.zeros(shape, dtype=np.float32))
                with self.assertRaisesRegex(SeparationError, "stimmen nicht"):
                    check_stem_consistency(mix, stems)

    def test_missing_role_and_invalid_thresholds_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            mix, stems = self.fixture(Path(directory))
            with self.assertRaisesRegex(SeparationError, "braucht music"):
                check_stem_consistency(mix, {"music": stems["music"]})
            for threshold in (-1, 2, float("nan"), float("inf")):
                with self.subTest(threshold=threshold), self.assertRaises(SeparationError):
                    check_stem_consistency(mix, stems, maximum_residual_ratio=threshold)

    def test_pcm_scaling_and_silence_are_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            mix, stems = self.fixture(Path(directory))
            wavfile.write(mix, 48_000, np.full((100, 2), 8192, dtype=np.int16))
            self.assertTrue(check_stem_consistency(mix, stems)["passed"])
            for path in (mix, *stems.values()):
                wavfile.write(path, 48_000, np.zeros((100, 2), dtype=np.int16))
            self.assertEqual(check_stem_consistency(mix, stems)["residual_to_mix_rms_ratio"], 0)

    def test_nan_infinity_empty_and_non_wav_outputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.wav"
            for values in (np.array([np.nan]), np.array([np.inf]), np.array([])):
                wavfile.write(path, 48_000, values.astype(np.float32))
                with self.assertRaises(SeparationError):
                    _validated_wav(path, "fixture")
            path.write_bytes(b"not audio" * 20)
            with self.assertRaisesRegex(SeparationError, "lesbare WAV"):
                _validated_wav(path, "fixture")


class CdxBackendTests(unittest.TestCase):
    def test_missing_config_is_honest_in_doctor(self):
        with mock.patch.dict(os.environ, {"NEXPT_CDX_CONFIG": "/no-such-cdx.json"}):
            status = cdx_status()
        self.assertFalse(status["configured"])
        self.assertFalse(status["runtime_verified"])

    def test_hash_and_revision_fail_before_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, config = make_cdx_fixture(root)
            separator = CdxSeparator(config)
            separator.ensure_ready()
            checkpoint = repo / "models" / CDX_CHECKPOINTS[0]
            checkpoint.write_bytes(b"changed")
            with mock.patch("cinematic_separation._run") as run:
                with self.assertRaisesRegex(SeparationError, "SHA-256 stimmt nicht"):
                    separator.separate(root / "source.wav", root / "out")
                run.assert_not_called()
            (repo / "inference.py").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(SeparationError, "revision"):
                separator.ensure_ready()

    def test_high_needs_all_three_weights_and_no_mps_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            repo, config = make_cdx_fixture(Path(directory))
            (repo / "models" / CDX_CHECKPOINTS[-1]).unlink()
            CdxSeparator(config).ensure_ready()
            with self.assertRaisesRegex(SeparationError, "Checkpoint"):
                CdxSeparator(config, quality="high").ensure_ready()
            with self.assertRaisesRegex(SeparationError, "nicht mps"):
                CdxSeparator(config, device="mps").ensure_ready()

    def test_invalid_config_schema_and_hash_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, config = make_cdx_fixture(Path(directory))
            original = json.loads(config.read_text())
            for payload in ([], {**original, "schema_version": 99},
                            {**original, "revision": "main"},
                            {**original, "python": "python3"},
                            {**original, "checkpoint_sha256": {}},
                            {**original, "checkpoint_license": ""}):
                config.write_text(json.dumps(payload), encoding="utf-8")
                with self.subTest(payload=payload), self.assertRaises(SeparationError):
                    CdxSeparator(config).ensure_ready()

    def test_existing_output_directory_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.wav"
            source.write_bytes(b"source")
            destination = root / "existing"
            destination.mkdir()
            (destination / "music.wav").write_bytes(b"keep")
            with mock.patch.object(CdxSeparator, "ensure_ready") as ready:
                with self.assertRaisesRegex(VideoMusicError, "existiert bereits"):
                    decompose(source, output_dir=destination)
                ready.assert_not_called()
            self.assertEqual((destination / "music.wav").read_bytes(), b"keep")

    def test_decompose_cli_exposes_explicit_gates(self):
        args = build_parser().parse_args([
            "decompose", "video.mp4", "--cdx-config", "cdx.json",
            "--quality", "high", "--strict", "--maximum-residual-ratio", "0.05"])
        self.assertEqual(args.cdx_config, Path("cdx.json"))
        self.assertTrue(args.strict)
        self.assertEqual(args.maximum_residual_ratio, .05)


if __name__ == "__main__":
    unittest.main()

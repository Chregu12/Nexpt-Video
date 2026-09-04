"""Real CLI/ffmpeg/filesystem tests; the heavyweight CDX model is a stand-in."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

from cinematic_separation import CDX_CHECKPOINTS
from cdx_fixtures import make_cdx_fixture


class DecompositionE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("ffmpeg and ffprobe required")

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT,
                              text=True, capture_output=True, timeout=40, env=env)

    def fixture_video(self, root):
        wav = root / "reference.wav"
        rate = 48_000
        times = np.arange(2 * rate) / rate
        audio = (.15 * np.sin(2 * np.pi * 220 * times)).astype(np.float32)
        # Decaying attacks provide a deterministic score for the downstream
        # fast GarageBand pipeline; this is not a quality benchmark.
        for index in range(8):
            start = int(index * .25 * rate)
            samples = np.arange(int(.07 * rate)) / rate
            audio[start:start + len(samples)] += (.4 * np.exp(-samples * 65)
                                                  * np.sin(2 * np.pi * 120 * samples))
        wavfile.write(wav, rate, np.column_stack((audio, audio)))
        video = root / "film with spaces.mkv"
        process = subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=2", "-i", str(wav),
            "-map", "0:v", "-map", "1:a", "-c:v", "mpeg4", "-c:a", "pcm_f32le",
            "-shortest", str(video)], capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        return video

    def test_video_to_three_stems_manifest_and_garageband_score(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, config = make_cdx_fixture(root)
            video = self.fixture_video(root)
            original_hash = hashlib.sha256(video.read_bytes()).hexdigest()
            destination = root / "separated film"
            result = self.run_cli(
                "render/video_music.py", "decompose", video, "--cdx-config", config,
                "--output-dir", destination, "--strict", "--quality", "high",
                "--vad", "heuristic")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report, json.loads((destination / "manifest.json").read_text()))
            self.assertEqual(set(report["outputs"]), {"soundtrack", "music", "dialogue", "sfx"})
            self.assertEqual(report["processing"]["task"], "cinematic")
            self.assertEqual(len(report["processing"]["provenance"]["checkpoint_sha256"]), 3)
            self.assertTrue(report["mix_consistency"]["passed"])
            self.assertTrue(report["quality_gate"]["listening_review_required"])
            self.assertEqual(report["status"], "review_required")
            self.assertFalse(report["one_to_one_music_stem_claim"])
            self.assertEqual(original_hash, hashlib.sha256(video.read_bytes()).hexdigest())
            for output in report["outputs"].values():
                path = Path(output["path"])
                self.assertEqual(path.parent, destination)
                self.assertEqual(output["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertTrue(Path(report["segment_analysis"]["path"]).is_file())
            command = report["next_commands"]["prepare_editable_garageband"]
            self.assertEqual(command[2], str(destination / "music.wav"))
            self.assertFalse(any(root.glob(".decomposition-*")))

            project = root / "garageband"
            workflow = self.run_cli(
                "garageband/workflow.py", destination / "music.wav", "--project-dir", project,
                "--quality", "fast", "--separate", "off", "--content", "percussion",
                "--pitch-engine", "off", "--instrument-engine", "off", "--bpm", "120")
            self.assertEqual(workflow.returncode, 0, workflow.stderr)
            self.assertEqual((project / "score.mid").read_bytes()[:4], b"MThd")
            transcription = json.loads((project / "analysis" / "transcription-report.json").read_text())
            self.assertEqual(transcription["outputs"]["reference_audio"], str(destination / "music.wav"))

    def test_invalid_model_outputs_publish_nothing_and_keep_source(self):
        for mode in ("missing", "nan", "short", "fail", "residual"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, config = make_cdx_fixture(root, mode)
                video = self.fixture_video(root)
                before = video.read_bytes()
                destination = root / "result"
                result = self.run_cli(
                    "render/video_music.py", "decompose", video, "--cdx-config", config,
                    "--output-dir", destination, "--strict")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(destination.exists(), result.stderr)
                self.assertFalse(any(root.glob(".decomposition-*")))
                self.assertEqual(video.read_bytes(), before)

    def test_bad_consistency_without_strict_still_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, config = make_cdx_fixture(root, "residual")
            video = self.fixture_video(root)
            result = self.run_cli(
                "render/video_music.py", "decompose", video, "--cdx-config", config,
                "--output-dir", root / "result")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report["quality_gate"]["technical_passed"])
            self.assertEqual(report["status"], "review_required")

    def test_setup_records_hashes_and_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _ = make_cdx_fixture(root)
            config = root / "recorded.json"
            command = ["render/cinematic_separation.py", "--repository", repo,
                       "--checkpoint-license", "test-fixture-only", "--output", config]
            result = self.run_cli(*command)
            self.assertEqual(result.returncode, 0, result.stderr)
            recorded = json.loads(config.read_text())
            self.assertEqual(set(recorded["checkpoint_sha256"]), set(CDX_CHECKPOINTS))
            self.assertEqual(recorded["runner"], "safe-pytorch")
            before = config.read_bytes()
            result = self.run_cli(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config.read_bytes(), before)
            env = {**os.environ, "NEXPT_CDX_CONFIG": str(config)}
            doctor = self.run_cli("render/video_music.py", "doctor", env=env)
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            status = json.loads(doctor.stdout)["cinematic_demixing"]
            self.assertTrue(status["configured"])
            self.assertFalse(status["runtime_verified"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VideoMusicE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("ffmpeg and ffprobe are required")

    def run_python(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def make_video(self, path: Path) -> None:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:r=10:d=0.8",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=0.8",
                "-shortest",
                "-c:v",
                "mpeg4",
                "-c:a",
                "aac",
                str(path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def make_segment_video(self, path: Path) -> None:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:r=10:d=3",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=1",
                "-f",
                "lavfi",
                "-i",
                (
                    "aevalsrc=0.18*sin(2*PI*180*t)*(0.55+0.45*sin(2*PI*4*t)):"
                    "s=48000:d=1"
                ),
                "-f",
                "lavfi",
                "-i",
                "anoisesrc=color=white:amplitude=0.15:sample_rate=48000:duration=1",
                "-filter_complex",
                "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
                "-map",
                "0:v",
                "-map",
                "[a]",
                "-shortest",
                "-c:v",
                "mpeg4",
                "-c:a",
                "aac",
                str(path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_doctor_and_verified_soundtrack_extraction(self) -> None:
        doctor = self.run_python("render/video_music.py", "doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        capabilities = json.loads(doctor.stdout)
        self.assertTrue(capabilities["ready"]["soundtrack"])
        self.assertIn("not an original studio stem", capabilities["contracts"]["music"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "video.mp4"
            output = root / "soundtrack.wav"
            manifest = root / "soundtrack.manifest.json"
            self.make_video(source)
            extracted = self.run_python(
                "render/video_music.py",
                "extract",
                str(source),
                "--mode",
                "soundtrack",
                "--output",
                str(output),
                "--manifest",
                str(manifest),
                "--analyze",
                "--bpm",
                "120",
                "--downbeat",
                "0",
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            result = json.loads(extracted.stdout)
            stored = json.loads(manifest.read_text(encoding="utf-8"))
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result, stored)
            self.assertEqual(result["output"]["sha256"], digest)
            self.assertEqual(result["output"]["media"]["audio_streams"][0]["codec"], "pcm_s24le")
            self.assertEqual(result["output"]["media"]["audio_streams"][0]["sample_rate"], 48_000)
            self.assertFalse(result["one_to_one_music_stem_claim"])
            self.assertEqual(result["analysis"]["bpm"], 120.0)
            self.assertTrue(Path(result["analysis"]["path"]).is_file())
            self.assertTrue(Path(result["segment_analysis"]["path"]).is_file())
            self.assertEqual(result["quality_gate"]["status"], "passed")
            self.assertTrue(output.is_file())

            repeated = self.run_python(
                "render/video_music.py",
                "extract",
                str(source),
                "--output",
                str(output),
                "--manifest",
                str(manifest),
            )
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("existiert bereits", repeated.stderr)

    def test_synthetic_music_speech_like_and_sfx_map_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "segments.mp4"
            output = root / "segments.wav"
            manifest = root / "segments.manifest.json"
            segment_map = root / "segments.map.json"
            self.make_segment_video(source)
            extracted = self.run_python(
                "render/video_music.py",
                "extract",
                str(source),
                "--mode",
                "soundtrack",
                "--output",
                str(output),
                "--manifest",
                str(manifest),
                "--segment-output",
                str(segment_map),
                "--segment-seconds",
                "1",
                "--segment-hop",
                "1",
                "--vad",
                "heuristic",
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            result = json.loads(extracted.stdout)
            segments = json.loads(segment_map.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(segments["summary"]["segment_count"], 3)
        self.assertEqual(segments["analysis"]["vad"]["engine"], "heuristic")
        self.assertTrue(segments["summary"]["manual_review_required"])
        self.assertIn("music", [item["label"] for item in segments["segments"]])
        self.assertIn("sfx", [item["label"] for item in segments["segments"]])
        for segment in segments["segments"]:
            self.assertAlmostEqual(
                sum(segment["probabilities"].values()), 1.0, places=3
            )

    def test_explicit_high_quality_fallback_is_never_reported_as_passed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "video.mp4"
            self.make_video(source)
            extracted = self.run_python(
                "render/video_music.py",
                "extract",
                str(source),
                "--quality",
                "high",
                "--vad",
                "heuristic",
                "--output",
                str(root / "output.wav"),
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            result = json.loads(extracted.stdout)
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["quality_gate"]["status"], "review_required")

    def test_local_roformer_adapter_contract_runs_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "video.mp4"
            output = root / "music.wav"
            adapter = root / "roformer-adapter"
            adapter.write_text(
                """#!/usr/bin/env python3
import argparse
from pathlib import Path
import shutil

parser = argparse.ArgumentParser()
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
args.output_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(args.input, args.output_dir / "instrumental.wav")
""",
                encoding="utf-8",
            )
            adapter.chmod(0o755)
            self.make_video(source)
            extracted = self.run_python(
                "render/video_music.py",
                "extract",
                str(source),
                "--mode",
                "music",
                "--separator",
                "roformer",
                "--roformer-command",
                str(adapter),
                "--vad",
                "heuristic",
                "--output",
                str(output),
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            result = json.loads(extracted.stdout)

        self.assertEqual(result["processing"]["engine"], "roformer")
        self.assertEqual(result["processing"]["requested_separator"], "roformer")
        self.assertEqual(result["processing"]["stem"], "no_vocals")
        self.assertTrue(result["output"]["sha256"])


if __name__ == "__main__":
    unittest.main()

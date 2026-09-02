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


if __name__ == "__main__":
    unittest.main()

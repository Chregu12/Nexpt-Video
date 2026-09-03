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


ROOT = Path(__file__).resolve().parents[1]


class VideoMusicE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("ffmpeg and ffprobe are required")

    def run_python(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
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

    def make_multi_audio_video(self, path: Path) -> None:
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
                "color=c=black:s=64x64:r=10:d=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:sample_rate=48000:duration=1",
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-map",
                "2:a",
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

    def make_roformer_adapter(
        self,
        path: Path,
        *,
        provenance: bool = False,
        fail: bool = False,
    ) -> None:
        lines = [
            "#!/usr/bin/env python3",
            "import argparse",
            "import json",
            "from pathlib import Path",
            "import shutil",
            "import sys",
            "parser = argparse.ArgumentParser()",
            'parser.add_argument("--input", type=Path, required=True)',
            'parser.add_argument("--output-dir", type=Path, required=True)',
            "args = parser.parse_args()",
        ]
        if fail:
            lines.extend(
                [
                    'print("adapter failed", file=sys.stderr)',
                    "raise SystemExit(7)",
                ]
            )
        else:
            lines.extend(
                [
                    "args.output_dir.mkdir(parents=True, exist_ok=True)",
                    'shutil.copy2(args.input, args.output_dir / "instrumental.wav")',
                ]
            )
            if provenance:
                payload = {
                    "model": "test-roformer",
                    "version": "1.0",
                    "checkpoint_sha256": "a" * 64,
                    "license": "MIT",
                }
                lines.extend(
                    [
                        f"provenance = {payload!r}",
                        "(args.output_dir / 'provenance.json').write_text(",
                        "    json.dumps(provenance), encoding='utf-8'",
                        ")",
                    ]
                )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o755)

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

            segment_path = Path(result["segment_analysis"]["path"])
            manifest.write_text("broken", encoding="utf-8")
            segment_path.write_text("broken", encoding="utf-8")
            overwritten = self.run_python(
                "render/video_music.py",
                "extract",
                str(source),
                "--mode",
                "soundtrack",
                "--output",
                str(output),
                "--manifest",
                str(manifest),
                "--vad",
                "heuristic",
                "--overwrite",
            )
            self.assertEqual(overwritten.returncode, 0, overwritten.stderr)
            replaced = json.loads(manifest.read_text(encoding="utf-8"))
            replaced_segments = json.loads(segment_path.read_text(encoding="utf-8"))
            self.assertEqual(replaced["output"]["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertGreater(replaced_segments["summary"]["segment_count"], 0)

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
            self.make_roformer_adapter(adapter)
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

    def test_verified_high_quality_roformer_and_silero_run_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "video.mp4"
            output = root / "music-high.wav"
            adapter = root / "roformer-adapter"
            fake_modules = root / "fake-modules"
            fake_modules.mkdir()
            (fake_modules / "silero_vad.py").write_text(
                """def load_silero_vad():
    return object()

def read_audio(path, sampling_rate=16000):
    return [0.0]

def get_speech_timestamps(waveform, model, sampling_rate=16000, return_seconds=False):
    return []
""",
                encoding="utf-8",
            )
            self.make_roformer_adapter(adapter, provenance=True)
            self.make_video(source)
            environment = os.environ.copy()
            existing_pythonpath = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = (
                str(fake_modules)
                if not existing_pythonpath
                else f"{fake_modules}{os.pathsep}{existing_pythonpath}"
            )
            environment["NEXPT_ROFORMER_COMMAND"] = str(adapter)

            doctor = self.run_python(
                "render/video_music.py", "doctor", env=environment
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            capabilities = json.loads(doctor.stdout)
            self.assertTrue(capabilities["speech_detection"]["silero"]["available"])
            self.assertTrue(capabilities["ready"]["high_music_roformer_reviewable"])

            extracted = self.run_python(
                "render/video_music.py",
                "extract",
                str(source),
                "--mode",
                "music",
                "--quality",
                "high",
                "--separator",
                "auto",
                "--vad",
                "auto",
                "--output",
                str(output),
                env=environment,
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            result = json.loads(extracted.stdout)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["processing"]["engine"], "roformer")
        self.assertEqual(result["processing"]["model"], "test-roformer")
        self.assertEqual(result["quality_gate"]["status"], "passed")
        self.assertTrue(all(check["passed"] for check in result["quality_gate"]["checks"]))
        self.assertEqual(result["segment_analysis"]["vad"]["engine"], "silero")

    def test_second_audio_stream_is_selected_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "multi-audio.mp4"
            output = root / "selected.wav"
            self.make_multi_audio_video(source)
            extracted = self.run_python(
                "render/video_music.py",
                "extract",
                str(source),
                "--mode",
                "soundtrack",
                "--audio-stream",
                "1",
                "--vad",
                "off",
                "--segment-seconds",
                "1",
                "--segment-hop",
                "1",
                "--output",
                str(output),
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            result = json.loads(extracted.stdout)
            segment_map = json.loads(
                Path(result["segment_analysis"]["path"]).read_text(encoding="utf-8")
            )

        self.assertEqual(len(result["source"]["media"]["audio_streams"]), 2)
        self.assertEqual(result["source"]["selected_audio_stream"], 1)
        centroid = segment_map["segments"][0]["features"]["spectral_centroid_hz"]
        self.assertAlmostEqual(centroid, 880.0, delta=25.0)
        self.assertLessEqual(
            segment_map["segments"][0]["probabilities"]["speech"], 0.10
        )

    def test_failing_separator_leaves_no_declared_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "video.mp4"
            output = root / "music.wav"
            adapter = root / "failing-adapter"
            self.make_video(source)
            self.make_roformer_adapter(adapter, fail=True)
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

            self.assertNotEqual(extracted.returncode, 0)
            self.assertIn("adapter failed", extracted.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".manifest.json").exists())
            self.assertFalse(output.with_suffix(".segments.json").exists())
            self.assertEqual(list(root.glob(".music.work-*")), [])


if __name__ == "__main__":
    unittest.main()

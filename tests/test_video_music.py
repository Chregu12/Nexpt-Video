from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

import video_music  # noqa: E402


class VideoMusicUnitTests(unittest.TestCase):
    def test_default_outputs_are_local_and_mode_specific(self) -> None:
        source = Path("Eine Musik (Final)!.mp4")
        soundtrack = video_music.default_output(source, "soundtrack")
        music = video_music.default_output(source, "music")
        self.assertEqual(soundtrack.parent, ROOT / "out" / "video-music")
        self.assertEqual(soundtrack.name, "Eine-Musik-Final-soundtrack.wav")
        self.assertEqual(music.name, "Eine-Musik-Final-music-estimate.wav")

    def test_probe_reports_audio_ordinals_and_video_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.mp4"
            source.write_bytes(b"fixture")
            payload = {
                "format": {
                    "duration": "2.5",
                    "size": "7",
                    "bit_rate": "1024",
                    "format_name": "mov,mp4",
                },
                "streams": [
                    {"index": 0, "codec_type": "video", "codec_name": "h264"},
                    {
                        "index": 2,
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "48000",
                        "channels": 2,
                    },
                    {
                        "index": 3,
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "44100",
                        "channels": 1,
                    },
                ],
            }
            completed = SimpleNamespace(
                returncode=0, stdout=json.dumps(payload), stderr=""
            )
            with mock.patch.object(video_music, "executable", return_value="ffprobe"):
                with mock.patch.object(video_music.subprocess, "run", return_value=completed):
                    report = video_music.probe_media(source)
        self.assertEqual(report["video_stream_count"], 1)
        self.assertEqual([row["ordinal"] for row in report["audio_streams"]], [0, 1])
        self.assertEqual([row["index"] for row in report["audio_streams"]], [2, 3])

    def test_existing_output_is_rejected_before_ffmpeg_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            output = root / "existing.wav"
            source.write_bytes(b"source")
            output.write_bytes(b"existing")
            with mock.patch.object(video_music, "probe_media") as probe:
                with self.assertRaisesRegex(video_music.VideoMusicError, "existiert bereits"):
                    video_music._extract_wav(source, output)
            probe.assert_not_called()

    def test_music_mode_fails_honestly_without_demucs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            output = root / "music.wav"
            source.write_bytes(b"source")
            with mock.patch.object(video_music, "demucs_available", return_value=False):
                with self.assertRaisesRegex(video_music.VideoMusicError, "braucht Demucs"):
                    video_music._isolate_music(
                        source,
                        output,
                        audio_stream=0,
                        sample_rate=48_000,
                        model="htdemucs",
                        device="cpu",
                        overwrite=False,
                    )
            self.assertFalse(output.exists())

    def test_generated_artifacts_must_use_distinct_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"source")
            same_json = Path(directory) / "result.json"
            with self.assertRaisesRegex(
                video_music.VideoMusicError, "muessen verschiedene Dateien sein"
            ):
                video_music.extract(
                    source,
                    output=Path(directory) / "result.wav",
                    manifest=same_json,
                    analyze=True,
                    profile_output=same_json,
                )

    def test_next_steps_keep_reconstruction_distinct_from_exact_audio(self) -> None:
        output = Path("/tmp/reference.wav")
        profile = Path("/tmp/reference-profile.json")
        commands = video_music._next_commands(output, profile)
        self.assertIn("render/reference_analyzer.py", commands["analyze_reference"])
        self.assertIn("garageband/workflow.py", commands["prepare_editable_garageband"])
        self.assertIn("--prepare-dry-run", commands["prepare_editable_garageband"])


if __name__ == "__main__":
    unittest.main()

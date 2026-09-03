from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

import audio_segmentation  # noqa: E402


class AudioSegmentationUnitTests(unittest.TestCase):
    def test_interval_overlap_merges_overlapping_ranges(self) -> None:
        overlap = audio_segmentation.interval_overlap(
            0.0,
            2.0,
            [
                {"start": 0.25, "end": 1.0},
                {"start": 0.75, "end": 1.5},
                {"start": 3.0, "end": 4.0},
            ],
        )
        self.assertAlmostEqual(overlap, 0.625)

    def test_known_music_speech_and_sfx_segments_are_routed(self) -> None:
        sample_rate = audio_segmentation.SAMPLE_RATE
        time = np.arange(sample_rate, dtype=np.float64) / sample_rate
        tone = np.column_stack([0.2 * np.sin(2 * np.pi * 440 * time)] * 2).astype(
            np.float32
        )
        impulse = np.zeros((sample_rate, 2), dtype=np.float32)
        for position in (1_000, 12_000, 25_000, 39_000):
            impulse[position : position + 30] = (
                0.9 * np.hanning(30)[:, None]
            )
        audio = np.concatenate([tone, tone, impulse])

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.wav"
            source.write_bytes(b"fixture")
            with mock.patch.object(
                audio_segmentation, "decode_audio", return_value=audio
            ), mock.patch.object(
                audio_segmentation,
                "_silero_intervals",
                return_value=[{"start": 1.05, "end": 1.95}],
            ), mock.patch.object(
                audio_segmentation, "silero_available", return_value=True
            ), mock.patch.object(
                audio_segmentation, "silero_version", return_value="test"
            ), mock.patch.object(
                audio_segmentation, "file_sha256", return_value="abc"
            ):
                report = audio_segmentation.analyze_segments(
                    source,
                    vad="silero",
                    segment_seconds=1.0,
                    hop_seconds=1.0,
                )

        self.assertEqual(
            [segment["label"] for segment in report["segments"]],
            ["music", "speech", "sfx"],
        )
        self.assertTrue(report["analysis"]["vad"]["reliable_speech_timestamps"])
        self.assertEqual(report["summary"]["segment_count"], 3)
        for segment in report["segments"]:
            self.assertAlmostEqual(sum(segment["probabilities"].values()), 1.0, places=3)

    def test_silero_request_fails_instead_of_silent_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.wav"
            source.write_bytes(b"fixture")
            with mock.patch.object(
                audio_segmentation, "silero_available", return_value=False
            ):
                with self.assertRaisesRegex(
                    audio_segmentation.SegmentationError, "Silero VAD fehlt"
                ):
                    audio_segmentation.analyze_segments(source, vad="silero")

    def test_quiet_segment_is_labelled_silence(self) -> None:
        features = audio_segmentation._features(
            np.zeros((audio_segmentation.SAMPLE_RATE, 2), dtype=np.float32)
        )
        probabilities = audio_segmentation._probabilities(
            features, speech_overlap=0.0, vad_engine="heuristic"
        )
        self.assertEqual(max(probabilities, key=probabilities.get), "silence")

    def test_decode_failure_is_reported_as_segmentation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "broken.wav"
            source.write_bytes(b"broken")
            with mock.patch.object(
                audio_segmentation,
                "decode_audio",
                side_effect=subprocess.CalledProcessError(1, ["ffmpeg"]),
            ):
                with self.assertRaisesRegex(
                    audio_segmentation.SegmentationError,
                    "konnte Audio nicht dekodieren",
                ):
                    audio_segmentation.analyze_segments(source, vad="heuristic")


if __name__ == "__main__":
    unittest.main()

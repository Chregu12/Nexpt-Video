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
    @staticmethod
    def tone(seconds: float = 1.0, frequency: float = 440.0) -> np.ndarray:
        sample_count = round(audio_segmentation.SAMPLE_RATE * seconds)
        time = np.arange(sample_count, dtype=np.float64) / audio_segmentation.SAMPLE_RATE
        mono = 0.2 * np.sin(2 * np.pi * frequency * time)
        return np.column_stack([mono, mono]).astype(np.float32)

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

    def test_interval_overlap_handles_empty_and_zero_length_windows(self) -> None:
        self.assertEqual(audio_segmentation.interval_overlap(2.0, 2.0, []), 0.0)
        self.assertEqual(
            audio_segmentation.interval_overlap(
                0.0, 1.0, [{"start": 2.0, "end": 3.0}]
            ),
            0.0,
        )

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

    def test_auto_vad_falls_back_to_heuristic_and_marks_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.wav"
            source.write_bytes(b"fixture")
            with mock.patch.object(
                audio_segmentation, "silero_available", return_value=False
            ), mock.patch.object(
                audio_segmentation, "decode_audio", return_value=self.tone(0.5)
            ), mock.patch.object(
                audio_segmentation, "file_sha256", return_value="abc"
            ):
                report = audio_segmentation.analyze_segments(source, vad="auto")

        self.assertEqual(report["analysis"]["vad"]["engine"], "heuristic")
        self.assertFalse(
            report["analysis"]["vad"]["reliable_speech_timestamps"]
        )
        self.assertTrue(report["summary"]["manual_review_required"])

    def test_auto_vad_uses_silero_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.wav"
            source.write_bytes(b"fixture")
            with mock.patch.object(
                audio_segmentation, "silero_available", return_value=True
            ), mock.patch.object(
                audio_segmentation, "_silero_intervals", return_value=[]
            ), mock.patch.object(
                audio_segmentation, "silero_version", return_value="test"
            ), mock.patch.object(
                audio_segmentation, "decode_audio", return_value=self.tone(0.5)
            ), mock.patch.object(
                audio_segmentation, "file_sha256", return_value="abc"
            ):
                report = audio_segmentation.analyze_segments(source, vad="auto")

        self.assertEqual(report["analysis"]["vad"]["engine"], "silero")
        self.assertFalse(report["summary"]["manual_review_required"])

    def test_vad_off_caps_speech_probability(self) -> None:
        features = audio_segmentation._features(self.tone())
        probabilities = audio_segmentation._probabilities(
            features,
            speech_overlap=1.0,
            vad_engine="off",
        )
        self.assertLessEqual(probabilities["speech"], 0.10)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0, places=3)

    def test_encoder_padding_tail_does_not_create_tiny_segment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.wav"
            source.write_bytes(b"fixture")
            with mock.patch.object(
                audio_segmentation, "decode_audio", return_value=self.tone(1.05)
            ), mock.patch.object(
                audio_segmentation, "file_sha256", return_value="abc"
            ):
                report = audio_segmentation.analyze_segments(
                    source,
                    vad="heuristic",
                    segment_seconds=1.0,
                    hop_seconds=1.0,
                )

        self.assertEqual(report["summary"]["segment_count"], 1)
        self.assertEqual(report["summary"]["analyzed_seconds"], 1.0)

    def test_invalid_source_and_window_parameters_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            audio_segmentation.SegmentationError, "Audiodatei fehlt"
        ):
            audio_segmentation.analyze_segments(Path("/missing/audio.wav"))

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.wav"
            source.write_bytes(b"fixture")
            cases = (
                ({"vad": "unknown"}, "VAD-Engine"),
                ({"segment_seconds": 0.1}, "segment_seconds"),
                (
                    {"segment_seconds": 0.5, "hop_seconds": 0.75},
                    "hop_seconds",
                ),
            )
            for arguments, message in cases:
                with self.subTest(arguments=arguments):
                    with self.assertRaisesRegex(
                        audio_segmentation.SegmentationError, message
                    ):
                        audio_segmentation.analyze_segments(source, **arguments)

    def test_short_frame_features_remain_finite(self) -> None:
        features = audio_segmentation._features(np.zeros((4, 2), dtype=np.float32))
        self.assertEqual(features["spectral_centroid_hz"], 0.0)
        self.assertTrue(all(np.isfinite(value) for value in features.values()))


if __name__ == "__main__":
    unittest.main()

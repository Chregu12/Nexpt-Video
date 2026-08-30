"""Tests for exported-audio metadata inspection."""

from __future__ import annotations

import math
import wave

import pytest

from garageband_bridge import core


def test_audio_info_reads_wave_metadata(tmp_path):
    path = tmp_path / "tone.wav"
    sample_rate = 44100
    frame_count = sample_rate // 2
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00\x00\x00" * frame_count)

    info = core.audio_info(str(path))

    assert info["format"] == "WAVE"
    assert info["nonempty"] is True
    assert info["channels"] == 2
    assert info["sample_rate"] == sample_rate
    assert info["sample_width_bits"] == 16
    assert info["frame_count"] == frame_count
    assert math.isclose(info["duration_seconds"], 0.5, abs_tol=0.001)
    assert info["verification"]["has_audio_frames"] is True
    assert info["verification"]["has_duration"] is True


def test_audio_info_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.wav"
    path.write_bytes(b"")

    with pytest.raises(core.GarageBandError, match="empty"):
        core.audio_info(str(path))

"""Tests for export-format normalization (pure, no GarageBand)."""

from __future__ import annotations

from pathlib import Path

import pytest

from garageband_bridge import core


@pytest.mark.parametrize(
    "name,path,expected",
    [
        ("wav", "x.bin", "WAVE"),
        ("WAV", "x.bin", "WAVE"),
        ("mp3", "x.bin", "MP3"),
        ("aac", "x.bin", "AAC"),
        ("aiff", "x.bin", "AIFF"),
        (None, "song.mp3", "MP3"),
        (None, "song.m4a", "AAC"),
        (None, "song.aac", "AAC"),
        (None, "song.aif", "AIFF"),
        (None, "song.aiff", "AIFF"),
        (None, "song.wav", "WAVE"),
        (None, "song.unknownext", "WAVE"),  # default fallback
    ],
)
def test_normalize_export_format(name, path, expected):
    assert core._normalize_export_format(name, Path(path)) == expected


def test_unknown_explicit_format_rejected():
    with pytest.raises(core.GarageBandError):
        core._normalize_export_format("flac", Path("x.wav"))


def test_export_output_path_corrects_suffix():
    resolved, fmt = core._export_output_path("song", "WAVE")
    assert fmt == "WAVE"
    assert resolved.suffix == ".wav"


def test_export_output_path_preserves_aiff_long_suffix():
    # .aiff is a valid AIFF suffix and must not be rewritten to .aif.
    resolved, fmt = core._export_output_path("song.aiff", "AIFF")
    assert fmt == "AIFF"
    assert resolved.suffix == ".aiff"


def test_export_output_path_infers_from_suffix():
    resolved, fmt = core._export_output_path("track.mp3", None)
    assert fmt == "MP3"
    assert resolved.suffix == ".mp3"

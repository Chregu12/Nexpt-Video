"""Round-trip tests: the MIDI we write parses back to the counts we expect.

This exercises both the writer (tab_midi) and the independent reader
(core.midi_info / _parse_midi_track_summary), so a regression in either
side is caught.
"""

from __future__ import annotations

import pytest

from garageband_bridge import core, tab_midi


SIMPLE_TAB = """e|--0--2--3--|
B|--1--3--0--|
G|--0--2--0--|
D|--2--0--0--|
A|--3-----2--|
E|--------3--|"""

MUTED_TAB = """e|-x-x-|
B|-----|
G|-----|
D|-----|
A|-----|
E|-----|"""


def test_single_track_roundtrip(tmp_path):
    out = tmp_path / "riff.mid"
    written = tab_midi.tab_to_midi(SIMPLE_TAB, out, bpm=120)
    info = core.midi_info(str(out))

    assert info["header"] == "MThd"
    assert info["format"] == 1
    assert info["division"] == tab_midi.TICKS_PER_BEAT
    # Conductor track + one guitar track.
    assert info["tracks"] == 2
    assert info["track_chunks"] == 2
    # Guitar plays on MIDI channel 1 (zero-based 0). Every note we wrote is read back.
    assert info["note_on_by_channel"] == {"1": written["notes"]}
    assert info["note_on_count"] == written["notes"]


def test_arrangement_uses_distinct_channels(tmp_path):
    out = tmp_path / "arr.mid"
    written = tab_midi.tab_to_arranged_midi(
        SIMPLE_TAB, out, include_bass=True, include_drums=True, style="rock"
    )
    info = core.midi_info(str(out))

    assert info["tracks"] == 4
    channels = info["note_on_by_channel"]
    # Guitar -> ch1, bass -> ch2, drums -> ch10 (the GM percussion channel).
    assert channels.get("1") == written["notes"]
    assert channels.get("2", 0) > 0
    assert channels.get("10", 0) > 0
    assert info["note_on_count"] == sum(channels.values())


def test_muted_x_roundtrip_short_low_velocity(tmp_path):
    out = tmp_path / "muted.mid"
    written = tab_midi.tab_to_midi(MUTED_TAB, out, velocity=92)
    info = core.midi_info(str(out))

    assert written["muted_notes"] == 2
    assert info["note_on_by_channel"] == {"1": 2}
    assert info["velocity_by_channel"]["1"]["max"] == 54
    assert info["note_length_by_channel"]["1"]["max_ticks"] == 60


def test_arrangement_bass_skips_muted_only_onsets(tmp_path):
    out = tmp_path / "muted-arr.mid"
    written = tab_midi.tab_to_arranged_midi(MUTED_TAB, out, include_bass=True, include_drums=True)
    info = core.midi_info(str(out))

    assert written["muted_notes"] == 2
    assert info["note_on_by_channel"].get("1") == 2
    assert info["note_on_by_channel"].get("2", 0) == 0
    assert info["note_on_by_channel"].get("10", 0) > 0


def test_track_names_are_recovered(tmp_path):
    out = tmp_path / "named.mid"
    tab_midi.tab_to_arranged_midi(SIMPLE_TAB, out, title="My Song")
    names = core.midi_info(str(out))["track_names"]
    assert any("Guitar" in n for n in names)
    assert any("Bass" in n for n in names)
    assert any("Drums" in n for n in names)


def test_midi_info_rejects_non_midi(tmp_path):
    bogus = tmp_path / "not.mid"
    bogus.write_bytes(b"this is not a midi file")
    with pytest.raises(core.GarageBandError):
        core.midi_info(str(bogus))


@pytest.mark.parametrize("value", [0, 1, 127, 128, 255, 4096, 0x0FFFFFFF])
def test_var_len_codec_roundtrip(value):
    encoded = tab_midi._var_len(value)
    decoded, offset = core._read_midi_var_len(encoded, 0)
    assert decoded == value
    assert offset == len(encoded)

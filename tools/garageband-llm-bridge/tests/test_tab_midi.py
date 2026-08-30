"""Tests for the deterministic guitar-tab to MIDI logic.

None of these touch GarageBand, Swift, or the network.
"""

from __future__ import annotations

import pytest

from garageband_bridge import tab_midi


SIMPLE_TAB = """e|--0--2--3--|
B|--1--3--0--|
G|--0--2--0--|
D|--2--0--0--|
A|--3-----2--|
E|--------3--|"""

OPEN_STRINGS_TAB = """e|-0-|
B|-0-|
G|-0-|
D|-0-|
A|-0-|
E|-0-|"""


def test_open_strings_map_to_standard_tuning():
    notes = tab_midi.parse_guitar_tab(OPEN_STRINGS_TAB)
    midis = sorted(note.midi for note in notes)
    # Standard tuning open strings: E2 A2 D3 G3 B3 E4.
    assert midis == [40, 45, 50, 55, 59, 64]


def test_fret_offsets_add_to_string_pitch():
    notes = tab_midi.parse_guitar_tab(SIMPLE_TAB)
    by_string = {(n.string, n.fret): n.midi for n in notes}
    # low E open = 40, so fret 3 on low E = 43.
    assert by_string[("E", 3)] == 43
    # high e (E4 = 64), fret 2 = 66.
    assert by_string[("e", 2)] == 66


def test_capo_text_transposes_parsed_tab():
    tab = "Capo 2\n" + OPEN_STRINGS_TAB
    notes = tab_midi.parse_guitar_tab(tab)
    midis = sorted(note.midi for note in notes)
    assert midis == [42, 47, 52, 57, 61, 66]


def test_explicit_capo_overrides_detected_text():
    tab = "Capo 4\n" + OPEN_STRINGS_TAB
    notes = tab_midi.parse_guitar_tab(tab, capo=0)
    midis = sorted(note.midi for note in notes)
    assert midis == [40, 45, 50, 55, 59, 64]


def test_detect_capo_supports_common_tab_phrases():
    assert tab_midi.detect_capo("capo on 3rd fret") == 3
    assert tab_midi.detect_capo("Capo: second fret") == 2
    assert tab_midi.detect_capo("No capo") == 0


def test_detect_bpm_supports_common_tab_phrases():
    assert tab_midi.detect_bpm("BPM 140") == 140
    assert tab_midi.detect_bpm("Tempo: 92") == 92
    assert tab_midi.detect_bpm("♩ = 118") == 118
    assert tab_midi.detect_bpm("tempo 900") is None


def test_drop_d_tuning_lowers_low_e_string():
    tab = "Drop D tuning\n" + OPEN_STRINGS_TAB
    notes = tab_midi.parse_guitar_tab(tab)
    midis = sorted(note.midi for note in notes)
    assert midis == [38, 45, 50, 55, 59, 64]


def test_explicit_tuning_overrides_detected_text():
    tab = "Drop D tuning\n" + OPEN_STRINGS_TAB
    notes = tab_midi.parse_guitar_tab(tab, tuning="standard")
    midis = sorted(note.midi for note in notes)
    assert midis == [40, 45, 50, 55, 59, 64]


def test_detect_tuning_supports_common_tab_phrases():
    assert tab_midi.detect_tuning("Drop D tuning") == "drop d"
    assert tab_midi.detect_tuning("Tuning: DADGBE") == "D A D G B E"
    assert tab_midi.detect_tuning("Tuning: Eb Ab Db Gb Bb Eb") == "Eb Ab Db Gb Bb Eb"


def test_custom_tab_line_labels_imply_tuning_by_string_order():
    tab = """D|-0-|
A|-0-|
G|-0-|
D|-0-|
A|-0-|
D|-0-|"""

    notes = tab_midi.parse_guitar_tab(tab)

    assert tab_midi.detect_tuning(tab) == "D A D G A D"
    assert sorted(note.midi for note in notes) == [38, 45, 50, 55, 57, 62]
    assert [note.string for note in sorted(notes, key=lambda note: note.midi)] == ["D", "A", "D", "G", "A", "D"]


def test_custom_tab_line_labels_support_accidentals():
    tab = """D|-0-|
A|-0-|
F#|-0-|
D|-0-|
A|-0-|
D|-0-|"""

    notes = tab_midi.parse_guitar_tab(tab)

    assert tab_midi.detect_tuning(tab) == "D A D F# A D"
    assert sorted(note.midi for note in notes) == [38, 45, 50, 54, 57, 62]


def test_two_digit_frets_parse_as_single_note():
    tab = """e|--12--10--|
B|--13--10--|
G|--12--9---|
D|----------|
A|----------|
E|----------|"""
    notes = tab_midi.parse_guitar_tab(tab)
    e_midis = sorted(n.midi for n in notes if n.string == "e")
    # 64 + 12 = 76, 64 + 10 = 74. A '1' and '2' read separately would give 65/66.
    assert e_midis == [74, 76]
    # No accidental single-digit splits: every parsed fret is two digits here.
    assert all(n.fret >= 9 for n in notes)


def test_internal_measure_bars_do_not_shift_timing():
    plain = """e|-0--2-|
B|------|
G|------|
D|------|
A|------|
E|------|"""
    barred = """e|-0--|2-|
B|----|--|
G|----|--|
D|----|--|
A|----|--|
E|----|--|"""

    plain_notes = tab_midi.parse_guitar_tab(plain)
    barred_notes = tab_midi.parse_guitar_tab(barred)

    assert [(note.fret, note.column, note.tick) for note in barred_notes] == [
        (note.fret, note.column, note.tick) for note in plain_notes
    ]


def test_internal_measure_bars_do_not_extend_section_length(tmp_path):
    plain = """e|0---|
B|----|
G|----|
D|----|
A|----|
E|----|"""
    barred = """e|0-|--|
B|--|--|
G|--|--|
D|--|--|
A|--|--|
E|--|--|"""

    plain_result = tab_midi.tab_to_midi(plain, tmp_path / "plain.mid")
    barred_result = tab_midi.tab_to_midi(barred, tmp_path / "barred.mid")

    assert barred_result["last_tick"] == plain_result["last_tick"]


def test_hammer_pull_slide_symbols_do_not_add_timing_columns():
    connected = """e|-5h7p5/7\\5-|
B|-----------|
G|-----------|
D|-----------|
A|-----------|
E|-----------|"""
    spaced = """e|-5-7-5-7-5-|
B|-----------|
G|-----------|
D|-----------|
A|-----------|
E|-----------|"""

    connected_notes = tab_midi.parse_guitar_tab(connected)
    spaced_notes = tab_midi.parse_guitar_tab(spaced)

    assert [note.tick for note in connected_notes] == [120, 240, 360, 480, 600]
    assert [note.tick for note in spaced_notes] == [120, 360, 600, 840, 1080]


def test_bend_release_vibrato_symbols_do_not_add_timing_columns():
    tab = """e|-7b9r7~-|
B|--------|
G|--------|
D|--------|
A|--------|
E|--------|"""

    notes = tab_midi.parse_guitar_tab(tab)

    assert [(note.fret, note.tick) for note in notes] == [(7, 120), (9, 240), (7, 360)]


def test_muted_x_preserves_rhythmic_strums(tmp_path):
    tab = """e|-x-x-|
B|-----|
G|-----|
D|-----|
A|-----|
E|-----|"""

    result = tab_midi.tab_to_midi(tab, tmp_path / "muted.mid", velocity=90)

    assert result["notes"] == 2
    assert result["muted_notes"] == 2
    assert [(note["tick"], note["duration"], note["fret"], note["muted"]) for note in result["preview"]] == [
        (120, 60, -1, True),
        (360, 60, -1, True),
    ]


def test_empty_tab_raises():
    with pytest.raises(ValueError):
        tab_midi.parse_guitar_tab("")


def test_non_tab_text_raises():
    with pytest.raises(ValueError):
        tab_midi.parse_guitar_tab("this is just prose, not a tab at all")


def test_tab_to_midi_summary_shape(tmp_path):
    out = tmp_path / "riff.mid"
    result = tab_midi.tab_to_midi("BPM 110\nCapo 1\nDrop D tuning\n" + SIMPLE_TAB, out)
    assert result["notes"] == 15
    assert result["bpm"] == 110
    assert result["capo"] == 1
    assert result["tuning"] == "drop d"
    assert result["string_pitches"]["E"] == 38
    assert result["first_tick"] >= 0
    assert result["last_tick"] > result["first_tick"]
    assert out.exists() and out.read_bytes()[:4] == b"MThd"
    assert len(result["preview"]) == 15


def test_explicit_bpm_overrides_detected_text(tmp_path):
    result = tab_midi.tab_to_midi("BPM 140\n" + SIMPLE_TAB, tmp_path / "override.mid", bpm=96)
    assert result["bpm"] == 96


@pytest.mark.parametrize("bpm", [10, 0, 400])
def test_bpm_out_of_range_rejected(tmp_path, bpm):
    with pytest.raises(ValueError):
        tab_midi.tab_to_midi(SIMPLE_TAB, tmp_path / "x.mid", bpm=bpm)


def test_program_out_of_range_rejected(tmp_path):
    notes = tab_midi.parse_guitar_tab(SIMPLE_TAB)
    with pytest.raises(ValueError):
        tab_midi.write_midi(notes, tmp_path / "x.mid", program=200)


# --- Arrangement ----------------------------------------------------------


def test_arrangement_track_count_full(tmp_path):
    result = tab_midi.tab_to_arranged_midi(
        SIMPLE_TAB, tmp_path / "full.mid", include_bass=True, include_drums=True
    )
    # Conductor + guitar + bass + drums.
    assert result["tracks"] == 4


def test_arrangement_track_count_guitar_only(tmp_path):
    result = tab_midi.tab_to_arranged_midi(
        SIMPLE_TAB, tmp_path / "guitar.mid", include_bass=False, include_drums=False
    )
    assert result["tracks"] == 2


def test_style_auto_normalizes_to_rock(tmp_path):
    result = tab_midi.tab_to_arranged_midi(SIMPLE_TAB, tmp_path / "a.mid", style="auto")
    assert result["style"] == "rock"


def test_style_case_insensitive(tmp_path):
    result = tab_midi.tab_to_arranged_midi(SIMPLE_TAB, tmp_path / "p.mid", style="POP")
    assert result["style"] == "pop"


def test_invalid_style_raises(tmp_path):
    with pytest.raises(ValueError):
        tab_midi.tab_to_arranged_midi(SIMPLE_TAB, tmp_path / "n.mid", style="nonsense")


def test_repeat_count_multiplies_notes(tmp_path):
    once = tab_midi.tab_to_arranged_midi(SIMPLE_TAB, tmp_path / "1.mid", repeat_count=1)
    twice = tab_midi.tab_to_arranged_midi(SIMPLE_TAB, tmp_path / "2.mid", repeat_count=3)
    assert twice["source_notes"] == once["source_notes"]
    assert twice["notes"] == 3 * once["source_notes"]
    assert twice["repeat_count"] == 3
    # Repeats extend the timeline.
    assert twice["last_tick"] > once["last_tick"]


def test_repeat_count_is_clamped(tmp_path):
    result = tab_midi.tab_to_arranged_midi(SIMPLE_TAB, tmp_path / "c.mid", repeat_count=999)
    assert result["repeat_count"] == 32


@pytest.mark.parametrize("style", sorted(tab_midi.ARRANGEMENT_STYLES))
def test_every_supported_style_writes_a_file(tmp_path, style):
    out = tmp_path / f"{style}.mid"
    tab_midi.tab_to_arranged_midi(SIMPLE_TAB, out, style=style)
    assert out.exists() and out.read_bytes()[:4] == b"MThd"

"""Tests for the pure OCR-text-to-tab repair logic in image_tab.

These only exercise extract_tab_text, which is plain text in / text out.
Vision OCR (Swift) and image download are not invoked.
"""

from __future__ import annotations

import pytest

from garageband_bridge import image_tab, tab_midi


CLEAN_OCR = """e|--0--2--3--|
B|--1--3--0--|
G|--0--2--0--|
D|--2--0--0--|
A|--3-----2--|
E|--------3--|"""


def test_clean_ocr_returns_six_parseable_lines():
    tab_text = image_tab.extract_tab_text(CLEAN_OCR)
    lines = tab_text.splitlines()
    assert len(lines) == 6
    # The repaired block must parse with the normal tab parser.
    notes = tab_midi.parse_guitar_tab(tab_text)
    assert len(notes) > 0


def test_image_to_tab_reports_detected_capo(monkeypatch, tmp_path):
    image_path = tmp_path / "tab.png"
    image_path.write_bytes(b"not a real image; OCR is mocked")
    monkeypatch.setattr(image_tab, "recognize_text", lambda path: "BPM 136\nCapo 2\nTuning: DADGBE\n" + CLEAN_OCR)

    result = image_tab.image_to_tab_text(image_path)

    assert result["capo"] == 2
    assert result["tuning"] == "D A D G B E"
    assert result["bpm"] == 136
    assert result["notes"] == len(tab_midi.parse_guitar_tab(result["tab_text"], capo=2, tuning="D A D G B E"))


def test_extract_tab_text_accepts_custom_tuning_line_labels():
    custom = """D|-0-|
A|-0-|
F#|-0-|
D|-0-|
A|-0-|
D|-0-|"""

    tab_text = image_tab.extract_tab_text(custom)

    assert tab_text.splitlines()[2].startswith("F#|")
    assert tab_midi.detect_tuning(tab_text) == "D A D F# A D"
    assert len(tab_midi.parse_guitar_tab(tab_text)) == 6


def test_lines_without_leading_bars_are_repaired():
    # A common OCR failure mode: the leading "|" is dropped and columns
    # become spaces. The extractor should still recover six labeled lines.
    messy = "e 0 2 3\nB 1 3 0\nG 0 2 0\nD 2 0 0\nA 3   2\nE     3"
    tab_text = image_tab.extract_tab_text(messy)
    lines = tab_text.splitlines()
    assert len(lines) == 6
    assert all(line[0] in "eEABGD" and "|" in line for line in lines)
    # And it still parses to notes.
    assert len(tab_midi.parse_guitar_tab(tab_text)) > 0


def test_letter_l_and_capital_i_become_bars():
    # Vision frequently reads the "|" separator as capital 'I' or lowercase 'l'.
    # extract_tab_text normalizes both back to "|" so the lines still parse.
    text = "\n".join(
        ["eI-0-I", "Bl-0-l", "GI-0-I", "Dl-0-l", "AI-0-I", "El-0-l"]
    )
    tab_text = image_tab.extract_tab_text(text)
    lines = tab_text.splitlines()
    assert len(lines) == 6
    assert all("|" in line and "I" not in line and "l" not in line for line in lines)
    assert len(tab_midi.parse_guitar_tab(tab_text)) == 6


def test_ordered_lines_recover_label_ocr_failures():
    # Vision can read the high-e label as 0 and the G label as 6 while also
    # dropping the separator. The fallback keeps the standard tab line order.
    text = """0-0--2--3--2--0-
B--1--3--0--3--1--
6-0--2--0--2--0--
D-2--0--0--0--2--
A-3-----2-----3--|
E------3--------"""
    tab_text = image_tab.extract_tab_text(text)
    lines = tab_text.splitlines()
    assert [line.split("|", 1)[0] for line in lines] == ["e", "B", "G", "D", "A", "E"]
    assert len(tab_midi.parse_guitar_tab(tab_text)) > 0


def test_extra_lines_are_trimmed_to_full_groups_of_six():
    # Seven candidate lines should be trimmed back to a clean multiple of six.
    seven = CLEAN_OCR + "\nG|--5--5--5--|"
    tab_text = image_tab.extract_tab_text(seven)
    assert len(tab_text.splitlines()) == 6


def test_insufficient_lines_raise():
    with pytest.raises(ValueError):
        image_tab.extract_tab_text("just a caption\nand another line of prose")

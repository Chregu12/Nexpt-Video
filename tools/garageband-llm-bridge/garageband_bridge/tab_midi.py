"""Guitar-tab to MIDI helpers for GarageBand imports."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TICKS_PER_BEAT = 480
DEFAULT_PROGRAM = 25  # Acoustic guitar (steel), General MIDI program number 26 as zero-based value.
BASS_PROGRAM = 33  # Electric bass (finger), General MIDI program number 34 as zero-based value.
DRUM_CHANNEL = 9  # MIDI channel 10, zero-based.
ARRANGEMENT_STYLES = {"auto", "rock", "pop", "blues", "metal", "folk"}
MAX_CAPO = 24
TAB_STRING_ORDER_HIGH_TO_LOW = ("e", "B", "G", "D", "A", "E")
TAB_STRING_ORDER_LOW_TO_HIGH = tuple(reversed(TAB_STRING_ORDER_HIGH_TO_LOW))
STRING_PITCHES = {
    "e": 64,  # high E4
    "B": 59,
    "G": 55,
    "D": 50,
    "A": 45,
    "E": 40,  # low E2
}
NOTE_CLASS = {
    "C": 0,
    "B#": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "FB": 4,
    "E#": 5,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
    "CB": 11,
}
TUNING_PRESETS = {
    "standard": "E A D G B E",
    "drop d": "D A D G B E",
    "half step down": "Eb Ab Db Gb Bb Eb",
    "whole step down": "D G C F A D",
}
TUNING_NOTE_RE = re.compile(r"[A-Ga-g](?:[#b♯♭])?")
TAB_LINE_RE = re.compile(r"^\s*([A-Ga-g](?:[#b♯♭])?)\s*[\|:](.+)$")
NON_TIMING_TAB_CHARS = set("|hHpPbBrR/\\~")
MUTED_FRET = -1
MUTED_VELOCITY_DROP = 38
MUTED_DURATION_TICKS = 60


@dataclass(frozen=True)
class TabNote:
    string: str
    fret: int
    midi: int
    column: int
    tick: int
    duration: int
    muted: bool = False


ORDINAL_CAPO_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
}


def _normalize_capo(capo: int | None) -> int:
    if capo is None:
        return 0
    value = int(capo)
    if not 0 <= value <= MAX_CAPO:
        raise ValueError(f"Capo must be between 0 and {MAX_CAPO}.")
    return value


def detect_capo(tab_text: str) -> int:
    """Detect common capo notes from tab text or OCR output."""
    text = tab_text.casefold()
    if re.search(r"\b(no|without)\s+capo\b|\bcapo\s*[:=-]?\s*(none|no|0)\b", text):
        return 0
    number_match = re.search(
        r"\bcapo\b(?:\s+(?:on|at|fret))?\s*[:=-]?\s*(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?(?:\s+fret)?",
        text,
    )
    if number_match:
        return _normalize_capo(int(number_match.group(1)))
    word_match = re.search(
        r"\bcapo\b(?:\s+(?:on|at|fret))?\s*[:=-]?\s*(?:the\s+)?("
        + "|".join(ORDINAL_CAPO_WORDS)
        + r")(?:\s+fret)?",
        text,
    )
    if word_match:
        return ORDINAL_CAPO_WORDS[word_match.group(1)]
    return 0


def _normalize_bpm(bpm: int | float | str | None) -> int | None:
    if bpm is None:
        return None
    value = int(round(float(bpm)))
    if not 20 <= value <= 300:
        raise ValueError("BPM must be between 20 and 300.")
    return value


def detect_bpm(tab_text: str) -> int | None:
    """Detect common BPM/tempo notes from tab text or OCR output."""
    patterns = [
        r"\b(?:bpm|tempo)\b\s*[:=]?\s*(\d{2,3})\b",
        r"\b(\d{2,3})\s*(?:bpm|beats\s+per\s+minute)\b",
        r"[♩♪q]\s*=\s*(\d{2,3})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, tab_text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return _normalize_bpm(match.group(1))
        except ValueError:
            continue
    return None


def _effective_bpm(tab_text: str, bpm: int | float | str | None) -> int:
    return _normalize_bpm(bpm) or detect_bpm(tab_text) or 120


def _normalize_note_name(note: str) -> str:
    normalized = note.strip().replace("♯", "#").replace("♭", "b")
    if not normalized:
        raise ValueError("Tuning note cannot be empty.")
    letter = normalized[0].upper()
    accidental = normalized[1:].replace("B", "b")
    return f"{letter}{accidental}".upper()


def _display_note_name(note: str) -> str:
    normalized = _normalize_note_name(note)
    if len(normalized) == 1:
        return normalized
    return normalized[0] + normalized[1:].replace("B", "b")


def _tab_display_label(note: str) -> str:
    if note.strip() == "e":
        return "e"
    return _display_note_name(note)


def _pitch_near(note: str, reference_midi: int) -> int:
    normalized = _normalize_note_name(note)
    if normalized not in NOTE_CLASS:
        raise ValueError(f"Unsupported tuning note: {note!r}")
    pitch_class = NOTE_CLASS[normalized]
    octave_base = 12 * (reference_midi // 12) + pitch_class
    candidates = [octave_base - 12, octave_base, octave_base + 12]
    return max(0, min(127, min(candidates, key=lambda pitch: abs(pitch - reference_midi))))


def detect_tuning(tab_text: str) -> str | None:
    """Detect common guitar tuning notes from tab text or OCR output."""
    lowered = tab_text.casefold()
    if re.search(r"\bdrop\s*d\b", lowered):
        return "drop d"
    if re.search(r"\bhalf[-\s]?step\s+down\b|\beb\s+tuning\b|\be\s*flat\s+tuning\b", lowered):
        return "half step down"
    if re.search(r"\bwhole[-\s]?step\s+down\b|\bfull[-\s]?step\s+down\b", lowered):
        return "whole step down"

    for raw in tab_text.splitlines():
        line = raw.strip()
        if not re.search(r"\b(tuning|tuned)\b", line, flags=re.IGNORECASE):
            continue
        candidate = re.sub(r"^.*?\b(?:tuning|tuned)\b\s*(?:to|is|:|=|-)?\s*", "", line, flags=re.IGNORECASE)
        if re.search(r"\bstandard\b", candidate, flags=re.IGNORECASE):
            return "standard"
        notes = TUNING_NOTE_RE.findall(candidate)
        if len(notes) >= 6:
            return " ".join(notes[:6])

    line_labels = [label for label, _ in _raw_tab_lines(tab_text)]
    if len(line_labels) >= 6:
        high_to_low = [_display_note_name(label) for label in line_labels[:6]]
        if high_to_low != ["E", "B", "G", "D", "A", "E"]:
            return " ".join(reversed(high_to_low))
    return None


def _tuning_notes(tuning: str | None) -> tuple[str, str]:
    if tuning is None:
        return "standard", TUNING_PRESETS["standard"]
    normalized = tuning.strip()
    preset = TUNING_PRESETS.get(normalized.casefold())
    if preset:
        return normalized.casefold(), preset
    notes = TUNING_NOTE_RE.findall(normalized)
    if len(notes) != 6:
        raise ValueError("Tuning must be a preset such as 'drop d' or six notes such as 'D A D G B E'.")
    return " ".join(notes), " ".join(notes)


def _tuning_pitches(tuning: str | None) -> tuple[dict[str, int], str]:
    name, notes_text = _tuning_notes(tuning)
    notes_low_to_high = TUNING_NOTE_RE.findall(notes_text)
    if len(notes_low_to_high) != 6:
        raise ValueError("Tuning must resolve to six notes.")
    pitches: dict[str, int] = {}
    for label, note in zip(TAB_STRING_ORDER_LOW_TO_HIGH, notes_low_to_high):
        pitches[label] = _pitch_near(note, STRING_PITCHES[label])
    return pitches, name


def _effective_tuning(tab_text: str, tuning: str | None) -> tuple[dict[str, int], str]:
    return _tuning_pitches(detect_tuning(tab_text) if tuning is None else tuning)


def _var_len(value: int) -> bytes:
    if value < 0:
        raise ValueError("MIDI variable-length value cannot be negative")
    buffer = value & 0x7F
    value >>= 7
    while value:
        buffer <<= 8
        buffer |= ((value & 0x7F) | 0x80)
        value >>= 7
    out = bytearray()
    while True:
        out.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(out)


def _chunk(name: bytes, data: bytes) -> bytes:
    return name + struct.pack(">I", len(data)) + data


def _meta(delta: int, kind: int, data: bytes) -> bytes:
    return _var_len(delta) + b"\xff" + bytes([kind]) + _var_len(len(data)) + data


def _midi_event(delta: int, payload: bytes) -> bytes:
    return _var_len(delta) + payload


def _track_from_events(track_name: str, events: list[tuple[int, int, bytes]]) -> bytes:
    data = bytearray()
    data += _meta(0, 0x03, track_name.encode("utf-8")[:127])
    last_tick = 0
    for tick, _, payload in sorted(events, key=lambda item: (item[0], item[1], item[2])):
        data += _midi_event(tick - last_tick, payload)
        last_tick = tick
    data += _meta(0, 0x2F, b"")
    return bytes(data)


def _conductor_track(bpm: int) -> bytes:
    tempo = int(60_000_000 / bpm)
    conductor = bytearray()
    conductor += _meta(0, 0x03, b"Tempo")
    conductor += _meta(0, 0x51, tempo.to_bytes(3, "big"))
    conductor += _meta(0, 0x58, bytes([4, 2, 24, 8]))
    conductor += _meta(0, 0x2F, b"")
    return bytes(conductor)


def _raw_tab_lines(tab_text: str) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for raw in tab_text.splitlines():
        match = TAB_LINE_RE.match(raw.rstrip())
        if not match:
            continue
        label, body = match.groups()
        lines.append((label, body.rstrip()))
    return lines


def _parse_tab_lines(tab_text: str) -> list[tuple[str, str, str]]:
    parsed: list[tuple[str, str, str]] = []
    raw_lines = _raw_tab_lines(tab_text)
    for section in [raw_lines[i : i + 6] for i in range(0, len(raw_lines), 6)]:
        if len(section) < 6:
            continue
        for string_key, (display_label, body) in zip(TAB_STRING_ORDER_HIGH_TO_LOW, section):
            parsed.append((string_key, _tab_display_label(display_label), body))
    return parsed


def _timed_body_columns(body: str) -> int:
    return sum(1 for char in body if char not in NON_TIMING_TAB_CHARS)


def _line_notes(
    string_key: str,
    display_label: str,
    body: str,
    ticks_per_column: int,
    string_pitches: dict[str, int],
) -> list[tuple[int, int, str, int, bool]]:
    base = string_pitches[string_key]
    notes: list[tuple[int, int, str, int, bool]] = []
    i = 0
    column = 0
    while i < len(body):
        char = body[i]
        if char in NON_TIMING_TAB_CHARS:
            i += 1
            continue
        if char in {"x", "X"}:
            notes.append((column * ticks_per_column, base, display_label, MUTED_FRET, True))
            i += 1
            column += 1
            continue
        if char.isdigit():
            start = column
            token = char
            i += 1
            column += 1
            while i < len(body) and body[i].isdigit():
                token += body[i]
                i += 1
                column += 1
            fret = int(token)
            midi = base + fret
            if 0 <= midi <= 127:
                notes.append((start * ticks_per_column, midi, display_label, fret, False))
            continue
        column += 1
        i += 1
    return notes


def parse_guitar_tab(
    tab_text: str,
    *,
    ticks_per_column: int = 120,
    sustain_columns: int = 2,
    capo: int | None = None,
    tuning: str | None = None,
) -> list[TabNote]:
    """Parse common six-line ASCII guitar tab into timed MIDI notes."""
    effective_capo = detect_capo(tab_text) if capo is None else _normalize_capo(capo)
    string_pitches, _ = _effective_tuning(tab_text, tuning)
    tab_lines = _parse_tab_lines(tab_text)
    if len(tab_lines) < 6:
        raise ValueError("Expected at least six labeled guitar-tab lines like e|, B|, G|, D|, A|, E|.")

    sections = [tab_lines[i : i + 6] for i in range(0, len(tab_lines), 6)]
    notes: list[TabNote] = []
    tick_offset = 0
    default_duration = max(ticks_per_column, sustain_columns * ticks_per_column)

    for section in sections:
        if len(section) < 6:
            continue
        raw_events: list[tuple[int, int, str, int, bool]] = []
        max_tick = 0
        for string_key, display_label, body in section:
            line_events = _line_notes(string_key, display_label, body, ticks_per_column, string_pitches)
            raw_events.extend(
                (tick, min(127, midi + effective_capo), string_label, fret, muted)
                for tick, midi, string_label, fret, muted in line_events
            )
            if body:
                max_tick = max(max_tick, _timed_body_columns(body) * ticks_per_column)
        if not raw_events:
            tick_offset += max_tick + TICKS_PER_BEAT
            continue

        onset_ticks = sorted({tick for tick, _, _, _, _ in raw_events})
        next_by_tick = {
            tick: onset_ticks[index + 1] if index + 1 < len(onset_ticks) else tick + default_duration
            for index, tick in enumerate(onset_ticks)
        }
        for tick, midi, label, fret, muted in raw_events:
            next_tick = next_by_tick[tick]
            duration = max(ticks_per_column, min(default_duration, next_tick - tick))
            notes.append(
                TabNote(
                    string=label,
                    fret=fret,
                    midi=midi,
                    column=tick // ticks_per_column,
                    tick=tick_offset + tick,
                    duration=duration,
                    muted=muted,
                )
            )
        tick_offset += max(max_tick, max(t for t, _, _, _, _ in raw_events) + default_duration)

    notes.sort(key=lambda note: (note.tick, note.midi))
    if not notes:
        raise ValueError("No fretted notes were found in the tab text.")
    return notes


def _note_velocity(note: TabNote, velocity: int) -> int:
    if note.muted:
        return max(1, min(127, velocity - MUTED_VELOCITY_DROP))
    return velocity


def _note_duration(note: TabNote) -> int:
    if note.muted:
        return max(1, min(note.duration, MUTED_DURATION_TICKS))
    return note.duration


def write_midi(
    notes: list[TabNote],
    output_path: str | Path,
    *,
    bpm: int = 120,
    track_name: str = "GarageBand Bridge Tab",
    program: int = DEFAULT_PROGRAM,
    velocity: int = 92,
) -> Path:
    """Write a Standard MIDI File that GarageBand can import."""
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not 20 <= bpm <= 300:
        raise ValueError("BPM must be between 20 and 300.")
    if not 0 <= program <= 127:
        raise ValueError("Program must be a zero-based General MIDI value from 0 to 127.")
    velocity = max(1, min(127, velocity))

    events: list[tuple[int, int, bytes]] = [(0, 0, bytes([0xC0, program]))]
    for note in notes:
        note_velocity = _note_velocity(note, velocity)
        note_duration = _note_duration(note)
        events.append((note.tick, 1, bytes([0x90, note.midi, note_velocity])))
        events.append((note.tick + note_duration, 0, bytes([0x80, note.midi, 0])))

    header = b"MThd" + struct.pack(">IHHH", 6, 1, 2, TICKS_PER_BEAT)
    output.write_bytes(header + _chunk(b"MTrk", _conductor_track(bpm)) + _chunk(b"MTrk", _track_from_events(track_name, events)))
    return output


def _bass_pitch_for_group(group: list[TabNote]) -> int:
    root = min(note.midi for note in group)
    while root > 52:
        root -= 12
    while root < 28:
        root += 12
    return root


def _normalize_style(style: str) -> str:
    normalized = (style or "auto").strip().lower().replace("_", "-")
    if normalized == "auto":
        return "rock"
    if normalized not in ARRANGEMENT_STYLES:
        supported = ", ".join(sorted(ARRANGEMENT_STYLES))
        raise ValueError(f"Unsupported arrangement style {style!r}. Supported styles: {supported}.")
    return normalized


def _repeat_notes(notes: list[TabNote], repeat_count: int) -> list[TabNote]:
    repeat_count = max(1, min(32, int(repeat_count)))
    if repeat_count == 1:
        return list(notes)
    span = max(note.tick + note.duration for note in notes)
    bar = TICKS_PER_BEAT * 4
    section_span = max(bar, ((span + bar - 1) // bar) * bar)
    repeated: list[TabNote] = []
    for repeat_index in range(repeat_count):
        offset = repeat_index * section_span
        for note in notes:
            repeated.append(
                TabNote(
                    string=note.string,
                    fret=note.fret,
                    midi=note.midi,
                    column=note.column,
                    tick=note.tick + offset,
                    duration=note.duration,
                    muted=note.muted,
                )
            )
    return repeated


def _drum_hits_for_step(style: str, tick: int, step: int, velocity: int) -> list[tuple[int, int]]:
    beat = (tick // TICKS_PER_BEAT) % 4
    half_step = (tick // step) % 2
    hits: list[tuple[int, int]] = []

    if style == "folk":
        if tick % TICKS_PER_BEAT == 0:
            hits.append((36, 64 if beat in {0, 2} else 56))
        hits.append((42, 42))
        return hits

    if style == "pop":
        if tick % TICKS_PER_BEAT == 0:
            hits.append((36, 86 if beat in {0, 2} else 70))
            if beat in {1, 3}:
                hits.append((38, 90))
        hits.append((42, 54 if half_step == 0 else 46))
        return hits

    if style == "blues":
        if tick % TICKS_PER_BEAT == 0:
            hits.append((36, 78 if beat in {0, 2} else 66))
            if beat in {1, 3}:
                hits.append((38, 78))
        if half_step == 0:
            hits.append((42, 48))
        return hits

    if style == "metal":
        hits.append((36, 102 if half_step == 0 else 92))
        if tick % TICKS_PER_BEAT == 0 and beat in {1, 3}:
            hits.append((38, 100))
        hits.append((42, 68))
        return hits

    # rock
    if tick % TICKS_PER_BEAT == 0:
        hits.append((36, 92 if beat in {0, 2} else 78))
        if beat in {1, 3}:
            hits.append((38, 86))
    hits.append((42, 58))
    return hits


def write_arranged_midi(
    notes: list[TabNote],
    output_path: str | Path,
    *,
    bpm: int = 120,
    title: str = "GarageBand Bridge Arrangement",
    guitar_program: int = DEFAULT_PROGRAM,
    bass_program: int = BASS_PROGRAM,
    include_bass: bool = True,
    include_drums: bool = True,
    style: str = "rock",
    repeat_count: int = 1,
    velocity: int = 92,
) -> Path:
    """Write a simple GarageBand-friendly guitar/bass/drums arrangement MIDI."""
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not 20 <= bpm <= 300:
        raise ValueError("BPM must be between 20 and 300.")
    velocity = max(1, min(127, velocity))
    style = _normalize_style(style)
    notes = _repeat_notes(notes, repeat_count)

    guitar_events: list[tuple[int, int, bytes]] = [(0, 0, bytes([0xC0, guitar_program]))]
    for note in notes:
        note_velocity = _note_velocity(note, velocity)
        note_duration = _note_duration(note)
        guitar_events.append((note.tick, 1, bytes([0x90, note.midi, note_velocity])))
        guitar_events.append((note.tick + note_duration, 0, bytes([0x80, note.midi, 0])))

    tracks = [_chunk(b"MTrk", _conductor_track(bpm))]
    tracks.append(_chunk(b"MTrk", _track_from_events(f"{title} - Guitar", guitar_events)))

    grouped: dict[int, list[TabNote]] = {}
    for note in notes:
        grouped.setdefault(note.tick, []).append(note)
    onset_ticks = sorted(grouped)
    last_tick = max(note.tick + note.duration for note in notes)

    bass_notes = 0
    if include_bass and onset_ticks:
        bass_events: list[tuple[int, int, bytes]] = [(0, 0, bytes([0xC1, bass_program]))]
        for index, tick in enumerate(onset_ticks):
            pitched_notes = [note for note in grouped[tick] if not note.muted]
            if not pitched_notes:
                continue
            next_tick = onset_ticks[index + 1] if index + 1 < len(onset_ticks) else tick + TICKS_PER_BEAT
            duration = max(TICKS_PER_BEAT // 2, min(TICKS_PER_BEAT, next_tick - tick))
            pitch = _bass_pitch_for_group(pitched_notes)
            bass_events.append((tick, 1, bytes([0x91, pitch, max(55, velocity - 12)])))
            bass_events.append((tick + duration, 0, bytes([0x81, pitch, 0])))
            bass_notes += 1
        tracks.append(_chunk(b"MTrk", _track_from_events(f"{title} - Bass", bass_events)))

    drum_hits = 0
    if include_drums:
        drum_events: list[tuple[int, int, bytes]] = []
        step = TICKS_PER_BEAT // 2
        end_tick = max(TICKS_PER_BEAT * 4, ((last_tick // step) + 2) * step)
        tick = 0
        while tick <= end_tick:
            for order, (pitch, drum_velocity) in enumerate(_drum_hits_for_step(style, tick, step, velocity)):
                drum_events.append((tick, order + 1, bytes([0x99, pitch, max(1, min(127, drum_velocity))])))
                drum_events.append((tick + 60, 0, bytes([0x89, pitch, 0])))
                drum_hits += 1
            tick += step
        tracks.append(_chunk(b"MTrk", _track_from_events(f"{title} - {style.title()} Drums", drum_events)))

    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), TICKS_PER_BEAT)
    output.write_bytes(header + b"".join(tracks))
    return output


def tab_to_midi(
    tab_text: str,
    output_path: str | Path,
    *,
    bpm: int | None = None,
    ticks_per_column: int = 120,
    sustain_columns: int = 2,
    track_name: str = "GarageBand Bridge Tab",
    program: int = DEFAULT_PROGRAM,
    velocity: int = 92,
    capo: int | None = None,
    tuning: str | None = None,
) -> dict[str, Any]:
    effective_bpm = _effective_bpm(tab_text, bpm)
    effective_capo = detect_capo(tab_text) if capo is None else _normalize_capo(capo)
    string_pitches, effective_tuning = _effective_tuning(tab_text, tuning)
    notes = parse_guitar_tab(
        tab_text,
        ticks_per_column=ticks_per_column,
        sustain_columns=sustain_columns,
        capo=effective_capo,
        tuning=effective_tuning,
    )
    output = write_midi(
        notes,
        output_path,
        bpm=effective_bpm,
        track_name=track_name,
        program=program,
        velocity=velocity,
    )
    return {
        "path": str(output),
        "bpm": effective_bpm,
        "notes": len(notes),
        "muted_notes": sum(1 for note in notes if note.muted),
        "first_tick": notes[0].tick,
        "last_tick": max(note.tick + note.duration for note in notes),
        "track_name": track_name,
        "program": program,
        "capo": effective_capo,
        "tuning": effective_tuning,
        "string_pitches": string_pitches,
        "preview": [
            {
                "tick": note.tick,
                "duration": _note_duration(note),
                "string": note.string,
                "fret": note.fret,
                "midi": note.midi,
                "muted": note.muted,
            }
            for note in notes[:16]
        ],
    }


def tab_to_arranged_midi(
    tab_text: str,
    output_path: str | Path,
    *,
    bpm: int | None = None,
    ticks_per_column: int = 120,
    sustain_columns: int = 2,
    title: str = "GarageBand Bridge Arrangement",
    include_bass: bool = True,
    include_drums: bool = True,
    style: str = "rock",
    repeat_count: int = 1,
    velocity: int = 92,
    capo: int | None = None,
    tuning: str | None = None,
) -> dict[str, Any]:
    effective_bpm = _effective_bpm(tab_text, bpm)
    effective_capo = detect_capo(tab_text) if capo is None else _normalize_capo(capo)
    string_pitches, effective_tuning = _effective_tuning(tab_text, tuning)
    notes = parse_guitar_tab(
        tab_text,
        ticks_per_column=ticks_per_column,
        sustain_columns=sustain_columns,
        capo=effective_capo,
        tuning=effective_tuning,
    )
    original_note_count = len(notes)
    normalized_style = _normalize_style(style)
    output = write_arranged_midi(
        notes,
        output_path,
        bpm=effective_bpm,
        title=title,
        include_bass=include_bass,
        include_drums=include_drums,
        style=normalized_style,
        repeat_count=repeat_count,
        velocity=velocity,
    )
    arranged_notes = _repeat_notes(notes, repeat_count)
    return {
        "path": str(output),
        "bpm": effective_bpm,
        "notes": len(arranged_notes),
        "source_notes": original_note_count,
        "muted_notes": sum(1 for note in arranged_notes if note.muted),
        "first_tick": arranged_notes[0].tick,
        "last_tick": max(note.tick + note.duration for note in arranged_notes),
        "title": title,
        "tracks": 2 + int(include_bass) + int(include_drums),
        "include_bass": include_bass,
        "include_drums": include_drums,
        "style": normalized_style,
        "repeat_count": max(1, min(32, int(repeat_count))),
        "capo": effective_capo,
        "tuning": effective_tuning,
        "string_pitches": string_pitches,
        "preview": [
            {
                "tick": note.tick,
                "duration": _note_duration(note),
                "string": note.string,
                "fret": note.fret,
                "midi": note.midi,
                "muted": note.muted,
            }
            for note in arranged_notes[:16]
        ],
    }

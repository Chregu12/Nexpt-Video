"""MusicXML full-score to MIDI helpers for GarageBand imports."""

from __future__ import annotations

import copy
import re
import struct
import zipfile
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from garageband_bridge import tab_midi


STEP_TO_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
PERCUSSION_CHANNEL = 9
DEFAULT_VELOCITY = 88
DEFAULT_PROGRAM = 0
DYNAMIC_VELOCITIES = {
    "ppp": 28,
    "pp": 40,
    "p": 52,
    "mp": 64,
    "mf": 82,
    "f": 100,
    "ff": 112,
    "fff": 124,
    "sfz": 118,
    "sf": 112,
    "fp": 96,
}
MIX_CC = {
    "volume": 7,
    "pan": 10,
    "reverb": 91,
    "chorus": 93,
}
GRACE_NOTE_TICKS = tab_midi.TICKS_PER_BEAT // 8
HARMONY_PROGRAM = 0
HARMONY_VELOCITY = 68
ARTICULATION_ALIASES = {
    "staccato": "staccato",
    "stacc": "staccato",
    ".": "staccato",
    "tenuto": "tenuto",
    "legato": "legato",
    "accent": "accent",
    ">": "accent",
    "marcato": "marcato",
    "^": "marcato",
}
ARTICULATION_DURATION_FACTORS = {
    "staccato": 0.5,
    "tenuto": 1.0,
    "legato": 1.08,
    "accent": 0.9,
    "marcato": 0.85,
}
ARTICULATION_VELOCITY_OFFSETS = {
    "accent": 16,
    "marcato": 22,
}
MAJOR_KEY_FIFTHS = {
    "Cb": -7,
    "Gb": -6,
    "Db": -5,
    "Ab": -4,
    "Eb": -3,
    "Bb": -2,
    "F": -1,
    "C": 0,
    "G": 1,
    "D": 2,
    "A": 3,
    "E": 4,
    "B": 5,
    "F#": 6,
    "C#": 7,
}
MINOR_KEY_FIFTHS = {
    "Ab": -7,
    "Eb": -6,
    "Bb": -5,
    "F": -4,
    "C": -3,
    "G": -2,
    "D": -1,
    "A": 0,
    "E": 1,
    "B": 2,
    "F#": 3,
    "C#": 4,
    "G#": 5,
    "D#": 6,
    "A#": 7,
}
PROGRAM_KEYWORDS: list[tuple[tuple[str, ...], int]] = [
    (("piano", "keyboard", "keys"), 0),
    (("organ",), 19),
    (("electric guitar", "distortion"), 29),
    (("guitar",), 25),
    (("bassoon",), 70),
    (("contrabass", "double bass"), 43),
    (("electric bass", "bass guitar", "bass"), 33),
    (("violin",), 40),
    (("viola",), 41),
    (("cello",), 42),
    (("trumpet",), 56),
    (("trombone",), 57),
    (("tuba",), 58),
    (("horn",), 60),
    (("sax", "saxophone"), 65),
    (("oboe",), 68),
    (("clarinet",), 71),
    (("flute",), 73),
    (("synth",), 80),
    (("voice", "vocal", "choir"), 52),
]
PERCUSSION_KEYWORDS = ("drum", "percussion", "kit", "snare", "kick", "cymbal")
DURATION_ALIASES = {
    "whole": 4,
    "w": 4,
    "half": 2,
    "h": 2,
    "quarter": 1,
    "q": 1,
    "eighth": Fraction(1, 2),
    "e": Fraction(1, 2),
    "sixteenth": Fraction(1, 4),
    "s": Fraction(1, 4),
}
HARMONY_KIND_INTERVALS = {
    "major": (0, 4, 7),
    "minor": (0, 3, 7),
    "augmented": (0, 4, 8),
    "diminished": (0, 3, 6),
    "dominant": (0, 4, 7, 10),
    "major-seventh": (0, 4, 7, 11),
    "minor-seventh": (0, 3, 7, 10),
    "diminished-seventh": (0, 3, 6, 9),
    "half-diminished": (0, 3, 6, 10),
    "major-minor": (0, 3, 7, 11),
    "suspended-fourth": (0, 5, 7),
    "suspended-second": (0, 2, 7),
    "power": (0, 7),
}
HARMONY_KIND_ALIASES = {
    "": "major",
    "maj": "major",
    "ma": "major",
    "m": "minor",
    "min": "minor",
    "-": "minor",
    "7": "dominant",
    "dom": "dominant",
    "dom7": "dominant",
    "maj7": "major-seventh",
    "ma7": "major-seventh",
    "major7": "major-seventh",
    "m7": "minor-seventh",
    "min7": "minor-seventh",
    "-7": "minor-seventh",
    "dim": "diminished",
    "dim7": "diminished-seventh",
    "o": "diminished",
    "o7": "diminished-seventh",
    "ø": "half-diminished",
    "ø7": "half-diminished",
    "m7b5": "half-diminished",
    "sus": "suspended-fourth",
    "sus4": "suspended-fourth",
    "sus2": "suspended-second",
    "5": "power",
}
DRUM_PITCHES = {
    "kick": 36,
    "bass_drum": 36,
    "bass drum": 36,
    "acoustic_bass_drum": 36,
    "acoustic bass drum": 36,
    "snare": 38,
    "acoustic_snare": 38,
    "acoustic snare": 38,
    "rim": 37,
    "clap": 39,
    "closed_hat": 42,
    "closed hi-hat": 42,
    "closed hihat": 42,
    "hat": 42,
    "hi_hat": 42,
    "hihat": 42,
    "pedal_hat": 44,
    "open_hat": 46,
    "open hi-hat": 46,
    "open hihat": 46,
    "low_tom": 45,
    "low tom": 45,
    "mid_tom": 47,
    "mid tom": 47,
    "high_tom": 50,
    "high tom": 50,
    "crash": 49,
    "crash_cymbal": 49,
    "crash cymbal": 49,
    "ride": 51,
    "ride_cymbal": 51,
    "ride cymbal": 51,
    "cowbell": 56,
}


def score_spec_schema() -> dict[str, Any]:
    """Return the bridge's LLM-facing JSON score spec contract."""
    return {
        "format": "garageband_score_spec_v1",
        "description": "LLM-friendly band score JSON. Times are quarter-note beats; omit note start for sequential notes inside a part.",
        "required_top_level": ["parts"],
        "top_level": {
            "title": "Optional song title.",
            "bpm": "Optional integer tempo, 20-300. Alias: tempo.",
            "tempo_changes": "Optional tempo map. Each item has beat/start/onset and bpm/tempo. Alias: tempo_map.",
            "time_signature": "Optional string like 4/4 or object {'beats': 4, 'beat_type': 4}. Alias: meter.",
            "time_signature_changes": "Optional meter map. Each item has beat/start/onset plus time_signature, meter, or beats/beat_type.",
            "key_signature": "Optional key such as C major, Bb major, E minor, or object {'fifths': -2, 'mode': 'major'}. Alias: key.",
            "parts": "Required non-empty list of instrument parts.",
        },
        "key_signature": {
            "name": "Human-readable key such as C major, Bb major, F# minor, or A minor.",
            "fifths": "Circle-of-fifths value from -7 to 7.",
            "mode": "major or minor.",
        },
        "tempo_change": {
            "beat": "Beat position where the tempo starts. Aliases: start, onset. Default 0.",
            "bpm": "Tempo from this beat onward, 20-300. Alias: tempo.",
        },
        "time_signature_change": {
            "beat": "Beat position where the meter starts. Aliases: start, onset. Default 0.",
            "time_signature": "Meter from this beat onward, such as 3/4 or {'beats': 7, 'beat_type': 8}. Alias: meter.",
        },
        "part": {
            "name": "Part/track name shown in GarageBand.",
            "instrument": "Instrument hint used for General MIDI program mapping, such as electric guitar, bass, piano, trumpet, strings, or drum kit.",
            "program": "Optional zero-based General MIDI program number, 0-127, ignored for percussion.",
            "channel": "Optional one-based MIDI channel, 1-16. Drum parts normally use channel 10.",
            "is_percussion": "Boolean; true lets notes use drum names.",
            "velocity": "Optional default note velocity, 1-127.",
            "dynamic": "Optional default dynamic marking such as pp, p, mp, mf, f, ff, or fff.",
            "mix": "Optional object with volume, pan, reverb, and chorus. These are written as MIDI control changes for GarageBand import.",
            "volume": "Optional shortcut for mix.volume; accepts 0-127, 0.0-1.0, or percent text.",
            "pan": "Optional shortcut for mix.pan; accepts 0-127, -1.0..1.0, or left/center/right.",
            "notes": "Required non-empty list of note objects or compact note strings.",
            "sections": "Optional ordered song sections. Each section has name, optional repeat, optional dynamic, and notes/events/sequence. Use this instead of notes for intro/verse/chorus forms.",
        },
        "mix": {
            "volume": "MIDI CC7 track volume, 0-127, 0.0-1.0, or percent text such as 80%.",
            "pan": "MIDI CC10 pan, 0-127, -1.0 full left through 1.0 full right, or left/center/right.",
            "reverb": "MIDI CC91 effect send, 0-127, 0.0-1.0, or percent text.",
            "chorus": "MIDI CC93 effect send, 0-127, 0.0-1.0, or percent text.",
        },
        "section": {
            "name": "Section marker name such as Intro, Verse, Chorus, Bridge, or Outro.",
            "repeat": "Optional integer repeat count. Alias: repeats. Default 1.",
            "dynamic": "Optional default dynamic for notes inside this section.",
            "articulation": "Optional default articulation for notes inside this section.",
            "notes": "Required non-empty list of note objects or compact note strings for this section.",
        },
        "note_object": {
            "start": "Optional start beat. Aliases: beat, onset. If omitted, notes are sequential.",
            "duration": "Optional duration in beats or aliases whole/half/quarter/eighth/sixteenth. Default 1.",
            "pitch": "Pitch name like C4, F#3, or Bb4.",
            "pitches": "Array of pitch names for chords.",
            "chord": "Pitch array or compact chord text.",
            "drum": "Drum name for percussion parts.",
            "midi": "Integer MIDI note or integer list, 0-127.",
            "rest": "Boolean rest; advances time without sounding.",
            "velocity": "Optional velocity for this event, 1-127.",
            "dynamic": "Optional dynamic marking for this event, overriding the part default.",
            "articulation": "Optional articulation such as staccato, tenuto, legato, accent, or marcato. Alias: articulations.",
        },
        "compact_note": "Examples: C4:1, [C4,E4,G4]:2, rest:1, C5@5:1, kick:1.",
        "pitch_examples": ["C4", "F#3", "Bb4"],
        "key_examples": ["C major", "Bb major", "E minor", {"fifths": -2, "mode": "major"}],
        "drum_names": sorted(DRUM_PITCHES),
        "dynamic_markings": sorted(DYNAMIC_VELOCITIES),
        "articulations": sorted(set(ARTICULATION_ALIASES.values())),
        "duration_aliases": sorted(DURATION_ALIASES),
        "minimal_example": {
            "title": "Tiny Band",
            "bpm": 120,
            "time_signature": "4/4",
            "parts": [
                {
                    "name": "Electric Guitar",
                    "instrument": "electric guitar",
                    "notes": [
                        {"pitch": "E4", "duration": 1},
                        {"pitches": ["E4", "G4", "B4"], "duration": 2},
                    ],
                },
                {
                    "name": "Drum Kit",
                    "is_percussion": True,
                    "notes": [
                        {"drum": "kick", "duration": 1},
                        {"drum": "snare", "duration": 1},
                    ],
                },
            ],
        },
        "section_example": {
            "title": "Section Song",
            "tempo_changes": [{"beat": 0, "bpm": 96}, {"beat": 4, "bpm": 124}, {"beat": 12, "bpm": 132}],
            "time_signature_changes": [{"beat": 0, "time_signature": "4/4"}, {"beat": 12, "time_signature": "6/8"}],
            "parts": [
                {
                    "name": "Piano",
                    "instrument": "piano",
                    "sections": [
                        {"name": "Intro", "notes": ["C4:1", "E4:1", "G4:2"]},
                        {"name": "Verse", "repeat": 2, "dynamic": "mf", "notes": ["C4:1", "D4:1", "E4:2"]},
                        {"name": "Chorus", "dynamic": "f", "notes": ["[C4,E4,G4]:2", "[F4,A4,C5]:2"]},
                    ],
                }
            ],
        },
    }


@dataclass(frozen=True)
class ScoreNote:
    midi: int
    tick: int
    duration: int
    velocity: int = DEFAULT_VELOCITY


@dataclass(frozen=True)
class ScoreControlChange:
    tick: int
    controller: int
    value: int


@dataclass(frozen=True)
class ScoreMix:
    volume: int | None = None
    pan: int | None = None
    reverb: int | None = None
    chorus: int | None = None

    def as_dict(self) -> dict[str, int]:
        return {
            key: value
            for key, value in {
                "volume": self.volume,
                "pan": self.pan,
                "reverb": self.reverb,
                "chorus": self.chorus,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class ScorePartInfo:
    name: str
    program: int | None = None
    channel: int | None = None
    mix: ScoreMix = ScoreMix()
    percussion_map: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ScorePart:
    part_id: str
    name: str
    notes: tuple[ScoreNote, ...]
    program: int | None
    channel: int
    is_percussion: bool = False
    mix: ScoreMix = ScoreMix()
    controls: tuple[ScoreControlChange, ...] = ()


@dataclass(frozen=True)
class ScoreMarker:
    name: str
    tick: int


@dataclass(frozen=True)
class ScoreTempo:
    bpm: int
    tick: int


@dataclass(frozen=True)
class ScoreTimeSignature:
    beats: int
    beat_type: int
    tick: int = 0


@dataclass(frozen=True)
class ScoreKeySignature:
    fifths: int
    mode: str = "major"
    tick: int = 0

    @property
    def name(self) -> str:
        names = MINOR_KEY_FIFTHS if self.mode == "minor" else MAJOR_KEY_FIFTHS
        for name, fifths in names.items():
            if fifths == self.fifths:
                return f"{name} {self.mode}"
        return f"{self.fifths} fifths {self.mode}"


def _strip_namespace(root: ET.Element) -> None:
    for element in root.iter():
        if "}" in element.tag:
            element.tag = element.tag.rsplit("}", 1)[1]


def _timewise_to_partwise(root: ET.Element) -> ET.Element:
    """Convert MusicXML score-timewise into the score-partwise shape parsed below."""
    converted = ET.Element("score-partwise", dict(root.attrib))
    part_ids = [score_part.attrib.get("id", "") for score_part in root.findall("./part-list/score-part")]
    part_ids = [part_id for part_id in part_ids if part_id]
    if not part_ids:
        seen: set[str] = set()
        for part_el in root.findall("./measure/part"):
            part_id = part_el.attrib.get("id", "")
            if part_id and part_id not in seen:
                seen.add(part_id)
                part_ids.append(part_id)
    if not part_ids:
        raise ValueError("score-timewise MusicXML must include at least one part.")

    for child in list(root):
        if child.tag != "measure":
            converted.append(copy.deepcopy(child))

    part_elements = {part_id: ET.SubElement(converted, "part", {"id": part_id}) for part_id in part_ids}
    for measure in root.findall("measure"):
        measure_attrs = dict(measure.attrib)
        shared_children = [child for child in list(measure) if child.tag != "part"]
        parts_by_id = {
            part_el.attrib.get("id", ""): part_el
            for part_el in measure.findall("part")
            if part_el.attrib.get("id", "")
        }
        for part_id, out_part in part_elements.items():
            source_part = parts_by_id.get(part_id)
            if source_part is None:
                continue
            out_measure = ET.SubElement(out_part, "measure", measure_attrs)
            for shared_child in shared_children:
                out_measure.append(copy.deepcopy(shared_child))
            for part_child in list(source_part):
                out_measure.append(copy.deepcopy(part_child))
    return converted


def _read_musicxml(path: str | Path) -> ET.Element:
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise ValueError(f"Score file does not exist: {source}")
    if source.suffix.lower() == ".mxl":
        with zipfile.ZipFile(source) as archive:
            candidates = [
                name for name in archive.namelist()
                if name.lower().endswith((".xml", ".musicxml"))
                and not name.upper().startswith("META-INF/")
            ]
            if not candidates:
                raise ValueError(f"No MusicXML document found inside {source}")
            data = archive.read(candidates[0])
        root = ET.fromstring(data)
    else:
        root = ET.parse(source).getroot()
    _strip_namespace(root)
    if root.tag not in {"score-partwise", "score-timewise"}:
        raise ValueError(f"Expected MusicXML score-partwise or score-timewise, got {root.tag!r}.")
    if root.tag == "score-timewise":
        root = _timewise_to_partwise(root)
    return root


def _text(element: ET.Element | None, default: str = "") -> str:
    if element is None or element.text is None:
        return default
    return element.text.strip()


def _int_text(element: ET.Element | None, default: int = 0) -> int:
    text = _text(element)
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def _clamp_midi(value: int) -> int:
    return max(0, min(127, value))


def _musicxml_volume_to_cc(text: str) -> int | None:
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if 0 <= value <= 100:
        return _clamp_midi(round(value * 127 / 100))
    return _clamp_midi(round(value))


def _musicxml_pan_to_cc(text: str) -> int | None:
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if -180 <= value <= 180:
        return _clamp_midi(round((value + 180) * 127 / 360))
    return _clamp_midi(round(value))


def _drum_text_to_midi(value: str) -> int | None:
    text = value.strip().casefold().replace("-", "_")
    if not text:
        return None
    if text in DRUM_PITCHES:
        return DRUM_PITCHES[text]
    text_with_spaces = text.replace("_", " ")
    if text_with_spaces in DRUM_PITCHES:
        return DRUM_PITCHES[text_with_spaces]
    for keyword, midi in sorted(DRUM_PITCHES.items(), key=lambda item: len(item[0]), reverse=True):
        normalized_keyword = keyword.casefold().replace("-", "_")
        if normalized_keyword in text or normalized_keyword.replace("_", " ") in text_with_spaces:
            return midi
    return None


def _part_infos(root: ET.Element) -> dict[str, ScorePartInfo]:
    infos: dict[str, ScorePartInfo] = {}
    for score_part in root.findall("./part-list/score-part"):
        part_id = score_part.attrib.get("id", "")
        name = _text(score_part.find("part-name")) or _text(score_part.find("part-abbreviation")) or part_id
        if part_id:
            midi_instrument = score_part.find("midi-instrument")
            channel: int | None = None
            program: int | None = None
            mix = ScoreMix()
            percussion_map: dict[str, int] = {}
            for midi_instrument in score_part.findall("midi-instrument"):
                instrument_id = midi_instrument.attrib.get("id", "").casefold()
                midi_unpitched = _int_text(midi_instrument.find("midi-unpitched"), 0)
                if instrument_id and midi_unpitched:
                    percussion_map[instrument_id] = _clamp_midi(midi_unpitched)
            for score_instrument in score_part.findall("score-instrument"):
                instrument_id = score_instrument.attrib.get("id", "").casefold()
                if not instrument_id or instrument_id in percussion_map:
                    continue
                labels = [
                    _text(score_instrument.find("instrument-name")),
                    _text(score_instrument.find("instrument-abbreviation")),
                    _text(score_instrument.find("instrument-sound")),
                ]
                for label in labels:
                    midi = _drum_text_to_midi(label)
                    if midi is not None:
                        percussion_map[instrument_id] = midi
                        break
            if midi_instrument is not None:
                midi_channel = _int_text(midi_instrument.find("midi-channel"), 0)
                if midi_channel:
                    channel = max(1, min(16, midi_channel)) - 1
                midi_program = _int_text(midi_instrument.find("midi-program"), 0)
                if midi_program:
                    program = _clamp_midi(midi_program - 1)
                volume = _musicxml_volume_to_cc(_text(midi_instrument.find("volume")))
                pan = _musicxml_pan_to_cc(_text(midi_instrument.find("pan")))
                mix = ScoreMix(volume=volume, pan=pan)
            infos[part_id] = ScorePartInfo(name=name, program=program, channel=channel, mix=mix, percussion_map=percussion_map)
    return infos


def _is_percussion_name(name: str) -> bool:
    lowered = name.casefold()
    return any(keyword in lowered for keyword in PERCUSSION_KEYWORDS)


def _program_for_name(name: str) -> int:
    lowered = name.casefold()
    for keywords, program in PROGRAM_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return program
    return DEFAULT_PROGRAM


def _next_melodic_channel(used: set[int]) -> int:
    for channel in range(16):
        if channel == PERCUSSION_CHANNEL:
            continue
        if channel not in used:
            used.add(channel)
            return channel
    # MIDI has only 16 channels; if a score has more parts, reuse channel 16.
    return 15


def _pitch_to_midi(pitch: ET.Element) -> int:
    step = _text(pitch.find("step")).upper()
    if step not in STEP_TO_SEMITONE:
        raise ValueError(f"Unsupported pitch step: {step!r}")
    alter = _int_text(pitch.find("alter"), 0)
    octave = _int_text(pitch.find("octave"), 4)
    midi = 12 * (octave + 1) + STEP_TO_SEMITONE[step] + alter
    return max(0, min(127, midi))


def _transpose_to_semitones(transpose: ET.Element | None) -> int:
    if transpose is None:
        return 0
    chromatic = _int_text(transpose.find("chromatic"), 0)
    octave_change = _int_text(transpose.find("octave-change"), 0)
    return chromatic + (12 * octave_change)


def _unpitched_to_midi(note: ET.Element, percussion_map: dict[str, int] | None = None) -> int:
    instrument = note.find("instrument")
    instrument_id = (instrument.attrib.get("id", "") if instrument is not None else "").casefold()
    if percussion_map and instrument_id in percussion_map:
        return percussion_map[instrument_id]
    if "snare" in instrument_id:
        return 38
    if "kick" in instrument_id or "bass" in instrument_id:
        return 36
    if "hat" in instrument_id:
        return 42
    if "crash" in instrument_id or "cymbal" in instrument_id:
        return 49
    unpitched = note.find("unpitched")
    if unpitched is not None:
        step = _text(unpitched.find("display-step")).upper()
        octave = _int_text(unpitched.find("display-octave"), 4)
        if step in STEP_TO_SEMITONE:
            value = 35 + ((octave - 3) * 7) + list(STEP_TO_SEMITONE).index(step)
            return max(35, min(81, value))
    return 38


def _harmony_pitch_class(step_el: ET.Element | None, alter_el: ET.Element | None) -> int | None:
    step = _text(step_el).upper()
    if step not in STEP_TO_SEMITONE:
        return None
    return (STEP_TO_SEMITONE[step] + _int_text(alter_el, 0)) % 12


def _harmony_kind_intervals(kind_el: ET.Element | None) -> tuple[int, ...]:
    if kind_el is None:
        return HARMONY_KIND_INTERVALS["major"]
    raw_values = [
        _text(kind_el),
        kind_el.attrib.get("text", ""),
    ]
    for raw in raw_values:
        text = raw.strip().casefold()
        if not text:
            continue
        normalized = HARMONY_KIND_ALIASES.get(text, text)
        if normalized in HARMONY_KIND_INTERVALS:
            return HARMONY_KIND_INTERVALS[normalized]
    return HARMONY_KIND_INTERVALS["major"]


def _harmony_to_midis(harmony: ET.Element) -> tuple[int, ...]:
    root = harmony.find("root")
    if root is None:
        return ()
    root_pc = _harmony_pitch_class(root.find("root-step"), root.find("root-alter"))
    if root_pc is None:
        return ()
    intervals = _harmony_kind_intervals(harmony.find("kind"))
    notes = [_clamp_midi(60 + root_pc + interval) for interval in intervals]
    bass = harmony.find("bass")
    bass_pc = None if bass is None else _harmony_pitch_class(bass.find("bass-step"), bass.find("bass-alter"))
    bass_note = _clamp_midi(48 + (root_pc if bass_pc is None else bass_pc))
    ordered = [bass_note, *notes]
    deduped: list[int] = []
    for midi in ordered:
        if midi not in deduped:
            deduped.append(midi)
    return tuple(deduped)


def _duration_to_ticks(duration: int, divisions: int) -> int:
    divisions = max(1, divisions)
    return max(1, round(duration * tab_midi.TICKS_PER_BEAT / divisions))


def _beats_to_ticks(value: Any, *, default: Any = 1) -> int:
    raw = default if value is None else value
    if isinstance(raw, (int, float)):
        beats = Fraction(str(raw))
    else:
        text = str(raw).strip().casefold()
        beats = Fraction(DURATION_ALIASES[text]) if text in DURATION_ALIASES else Fraction(text)
    return max(1, round(float(beats) * tab_midi.TICKS_PER_BEAT))


def _beat_position_to_ticks(value: Any, *, default: Any = 0) -> int:
    raw = default if value is None else value
    if isinstance(raw, (int, float)):
        beats = Fraction(str(raw))
    else:
        beats = Fraction(str(raw).strip())
    return max(0, round(float(beats) * tab_midi.TICKS_PER_BEAT))


def _pitch_name_to_midi(value: str) -> int:
    text = value.strip()
    match = re.fullmatch(r"([A-Ga-g])([#b♯♭]?)(-?\d+)", text)
    if not match:
        raise ValueError(f"Unsupported pitch name: {value!r}. Use names like C4, F#3, or Bb4.")
    step, accidental, octave_text = match.groups()
    alter = {"#": 1, "♯": 1, "b": -1, "♭": -1, "": 0}[accidental]
    midi = 12 * (int(octave_text) + 1) + STEP_TO_SEMITONE[step.upper()] + alter
    if not 0 <= midi <= 127:
        raise ValueError(f"Pitch is outside MIDI range: {value!r}.")
    return midi


def _drum_name_to_midi(value: str) -> int:
    midi = _drum_text_to_midi(value)
    if midi is not None:
        return midi
    raise ValueError(f"Unsupported drum name: {value!r}. Supported drums: {', '.join(sorted(DRUM_PITCHES))}.")


def _velocity_from_dynamic(value: Any, *, default: int = DEFAULT_VELOCITY) -> int:
    if value is None or value == "":
        return max(1, min(127, int(default)))
    if isinstance(value, (int, float)):
        return max(1, min(127, int(round(float(value)))))
    text = str(value).strip().casefold()
    if text in DYNAMIC_VELOCITIES:
        return DYNAMIC_VELOCITIES[text]
    try:
        return max(1, min(127, int(round(float(text)))))
    except ValueError as exc:
        raise ValueError(f"Unsupported dynamic marking: {value!r}. Use one of: {', '.join(sorted(DYNAMIC_VELOCITIES))}.") from exc


def _normalize_articulations(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        raw_values = [str(item) for item in value]
    else:
        raw_values = [piece for piece in re.split(r"[,+ ]+", str(value)) if piece]
    articulations: list[str] = []
    for raw in raw_values:
        text = raw.strip().casefold()
        normalized = ARTICULATION_ALIASES.get(text)
        if not normalized:
            raise ValueError(
                f"Unsupported articulation: {raw!r}. Use one of: {', '.join(sorted(set(ARTICULATION_ALIASES.values())))}."
            )
        if normalized not in articulations:
            articulations.append(normalized)
    return articulations


def _apply_articulations(duration: int, velocity: int, articulations: list[str]) -> tuple[int, int]:
    duration_factor = 1.0
    if "legato" in articulations:
        duration_factor = ARTICULATION_DURATION_FACTORS["legato"]
    elif "staccato" in articulations:
        duration_factor = ARTICULATION_DURATION_FACTORS["staccato"]
    elif "marcato" in articulations:
        duration_factor = ARTICULATION_DURATION_FACTORS["marcato"]
    elif "accent" in articulations:
        duration_factor = ARTICULATION_DURATION_FACTORS["accent"]
    elif "tenuto" in articulations:
        duration_factor = ARTICULATION_DURATION_FACTORS["tenuto"]
    velocity_offset = 0
    for articulation in articulations:
        velocity_offset += ARTICULATION_VELOCITY_OFFSETS.get(articulation, 0)
    return (
        max(1, round(duration * duration_factor)),
        max(1, min(127, velocity + velocity_offset)),
    )


def _cc_value(value: Any, *, field: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip().casefold()
        if text.endswith("%"):
            return max(0, min(127, round(float(text[:-1]) * 1.27)))
        value = text
    number = float(value)
    if 0.0 <= number <= 1.0 and not isinstance(value, int):
        number *= 127
    if not 0 <= number <= 127:
        raise ValueError(f"{field} must be between 0 and 127, 0.0 and 1.0, or percent text.")
    return max(0, min(127, round(number)))


def _pan_value(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip().casefold()
        aliases = {
            "left": 0,
            "l": 0,
            "center": 64,
            "centre": 64,
            "c": 64,
            "right": 127,
            "r": 127,
        }
        if text in aliases:
            return aliases[text]
        value = text
    if isinstance(value, float) and -1.0 <= value <= 1.0:
        return max(0, min(127, round((value + 1.0) * 63.5)))
    number = float(value)
    if not 0 <= number <= 127:
        raise ValueError("pan must be between 0 and 127, -1.0 and 1.0, or left/center/right.")
    return max(0, min(127, round(number)))


def _mix_from_part(raw_part: dict[str, Any]) -> ScoreMix:
    raw_mix = raw_part.get("mix")
    mix = raw_mix if isinstance(raw_mix, dict) else {}
    return ScoreMix(
        volume=_cc_value(raw_part.get("volume", mix.get("volume")), field="volume"),
        pan=_pan_value(raw_part.get("pan", mix.get("pan"))),
        reverb=_cc_value(raw_part.get("reverb", mix.get("reverb")), field="reverb"),
        chorus=_cc_value(raw_part.get("chorus", mix.get("chorus")), field="chorus"),
    )


def _validate_bpm(value: Any) -> int:
    bpm = int(round(float(value)))
    if not 20 <= bpm <= 300:
        raise ValueError("BPM must be between 20 and 300.")
    return bpm


def _tempo_changes_from_spec(spec: dict[str, Any], default_bpm: int) -> list[ScoreTempo]:
    raw_changes = spec.get("tempo_changes", spec.get("tempo_map", spec.get("tempos")))
    changes: dict[int, int] = {0: default_bpm}
    if raw_changes is None:
        return [ScoreTempo(bpm=default_bpm, tick=0)]
    if not isinstance(raw_changes, list):
        raise ValueError("tempo_changes must be a list of objects.")
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            raise ValueError("Each tempo change must be an object.")
        bpm_value = raw_change.get("bpm", raw_change.get("tempo"))
        if bpm_value is None:
            raise ValueError("Each tempo change requires bpm or tempo.")
        start_value = raw_change.get("beat", raw_change.get("start", raw_change.get("onset", 0)))
        tick = _beat_position_to_ticks(start_value, default=0)
        changes[tick] = _validate_bpm(bpm_value)
    return [ScoreTempo(bpm=bpm, tick=tick) for tick, bpm in sorted(changes.items())]


def _time_signature_change_summary(time_signature: ScoreTimeSignature) -> dict[str, Any]:
    return {
        "beats": time_signature.beats,
        "beat_type": time_signature.beat_type,
        "tick": time_signature.tick,
        "beat": round(time_signature.tick / tab_midi.TICKS_PER_BEAT, 4),
    }


def _time_signature_changes_from_spec(spec: dict[str, Any], default_beats: int, default_beat_type: int) -> list[ScoreTimeSignature]:
    raw_changes = spec.get("time_signature_changes", spec.get("meter_changes", spec.get("time_signatures")))
    changes: dict[int, tuple[int, int]] = {0: (default_beats, default_beat_type)}
    if raw_changes is None:
        return [ScoreTimeSignature(beats=default_beats, beat_type=default_beat_type, tick=0)]
    if not isinstance(raw_changes, list):
        raise ValueError("time_signature_changes must be a list of objects.")
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            raise ValueError("Each time signature change must be an object.")
        start_value = raw_change.get("beat", raw_change.get("start", raw_change.get("onset", 0)))
        tick = _beat_position_to_ticks(start_value, default=0)
        meter_value = raw_change.get("time_signature", raw_change.get("meter"))
        if meter_value is None:
            meter_value = raw_change
        changes[tick] = _time_signature_from_spec(meter_value)
    return [
        ScoreTimeSignature(beats=beats, beat_type=beat_type, tick=tick)
        for tick, (beats, beat_type) in sorted(changes.items())
    ]


def _normalize_key_name(name: str) -> tuple[str, str]:
    text = name.strip()
    text = text.replace("♭", "b").replace("♯", "#")
    if not text:
        raise ValueError("key_signature cannot be empty.")
    parts = text.split()
    tonic = parts[0].capitalize()
    if len(tonic) > 1:
        tonic = tonic[0].upper() + tonic[1:]
    mode = parts[1].casefold() if len(parts) > 1 else "major"
    if mode in {"maj", "ionian"}:
        mode = "major"
    if mode in {"min", "aeolian"}:
        mode = "minor"
    if mode not in {"major", "minor"}:
        raise ValueError("key_signature mode must be major or minor.")
    return tonic, mode


def _key_signature_from_spec(value: Any) -> ScoreKeySignature | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        if "fifths" in value:
            fifths = int(value["fifths"])
            mode = str(value.get("mode", value.get("tonality", "major"))).casefold()
            if mode in {"maj", "ionian"}:
                mode = "major"
            if mode in {"min", "aeolian"}:
                mode = "minor"
        elif "name" in value:
            tonic, mode = _normalize_key_name(str(value["name"]))
            fifths = (MINOR_KEY_FIFTHS if mode == "minor" else MAJOR_KEY_FIFTHS).get(tonic, 99)
        else:
            raise ValueError("key_signature object requires fifths or name.")
    else:
        tonic, mode = _normalize_key_name(str(value))
        fifths = (MINOR_KEY_FIFTHS if mode == "minor" else MAJOR_KEY_FIFTHS).get(tonic, 99)
    if mode not in {"major", "minor"}:
        raise ValueError("key_signature mode must be major or minor.")
    if not -7 <= fifths <= 7:
        raise ValueError("key_signature fifths must be between -7 and 7.")
    return ScoreKeySignature(fifths=fifths, mode=mode, tick=0)


def _key_signature_from_root(root: ET.Element) -> ScoreKeySignature | None:
    key_el = root.find(".//attributes/key")
    if key_el is None:
        return None
    fifths = _int_text(key_el.find("fifths"), 0)
    mode = (_text(key_el.find("mode"), "major") or "major").casefold()
    if mode not in {"major", "minor"}:
        mode = "minor" if mode in {"aeolian"} else "major"
    if not -7 <= fifths <= 7:
        return None
    return ScoreKeySignature(fifths=fifths, mode=mode, tick=0)


def _direction_dynamic(direction: ET.Element) -> int | None:
    sound = direction.find("sound")
    if sound is not None and sound.attrib.get("dynamics"):
        try:
            return _velocity_from_dynamic(sound.attrib["dynamics"])
        except ValueError:
            pass
    for dynamics in direction.findall(".//dynamics"):
        for child in list(dynamics):
            tag = child.tag.casefold()
            if tag in DYNAMIC_VELOCITIES:
                return DYNAMIC_VELOCITIES[tag]
    return None


def _direction_tempo(direction: ET.Element) -> int | None:
    sound = direction.find("sound")
    if sound is not None and sound.attrib.get("tempo"):
        try:
            value = int(round(float(sound.attrib["tempo"])))
            if 20 <= value <= 300:
                return value
        except ValueError:
            pass
    for per_minute in direction.findall(".//per-minute"):
        value = _int_text(per_minute, 0)
        if 20 <= value <= 300:
            return value
    return None


def _direction_marker_text(direction: ET.Element) -> str | None:
    candidates: list[str] = []
    for tag in ("rehearsal", "words"):
        for element in direction.findall(f".//{tag}"):
            text = _text(element)
            if text:
                candidates.append(text)
    for candidate in candidates:
        cleaned = re.sub(r"\s+", " ", candidate).strip()
        if cleaned:
            return cleaned[:127]
    return None


def _direction_octave_shift(direction: ET.Element) -> int | None:
    octave_shift = direction.find(".//octave-shift")
    if octave_shift is None:
        return None
    shift_type = octave_shift.attrib.get("type", "").casefold()
    if shift_type == "stop":
        return 0
    if shift_type == "continue":
        return None
    try:
        size = int(octave_shift.attrib.get("size", "8"))
    except ValueError:
        size = 8
    octaves = max(1, ((max(8, size) - 1) // 7))
    semitones = 12 * octaves
    if shift_type == "down":
        return -semitones
    if shift_type == "up":
        return semitones
    return None


def _direction_pedal_value(direction: ET.Element) -> int | None:
    pedal = direction.find(".//pedal")
    if pedal is None:
        return None
    pedal_type = pedal.attrib.get("type", "").casefold()
    if pedal_type in {"start", "sustain", "continue", "change"}:
        return 127
    if pedal_type in {"stop", "release", "discontinue", "discontinued"}:
        return 0
    line_value = pedal.attrib.get("line", "").casefold()
    if line_value in {"yes", "true", "1"}:
        return 127
    if line_value in {"no", "false", "0"}:
        return 0
    return None


def _musicxml_note_midi(note: ET.Element, part_info: ScorePartInfo, current_transpose: int, current_octave_shift: int) -> int:
    pitch_el = note.find("pitch")
    if pitch_el is not None:
        return _clamp_midi(_pitch_to_midi(pitch_el) + current_transpose + current_octave_shift)
    if note.find("unpitched") is not None:
        return _unpitched_to_midi(note, part_info.percussion_map)
    return 60


def _append_grace_notes(
    pending_grace_notes: list[ET.Element],
    notes: list[ScoreNote],
    *,
    start_tick: int,
    part_info: ScorePartInfo,
    current_transpose: int,
    current_octave_shift: int,
    current_velocity: int,
) -> None:
    if not pending_grace_notes:
        return
    playable_grace_notes = [note for note in pending_grace_notes if note.find("rest") is None]
    if not playable_grace_notes:
        pending_grace_notes.clear()
        return

    grace_duration = max(1, GRACE_NOTE_TICKS)
    grace_start = max(0, start_tick - (grace_duration * len(playable_grace_notes)))
    grace_velocity = max(1, current_velocity - 12)
    for index, grace_note in enumerate(playable_grace_notes):
        midi = _musicxml_note_midi(grace_note, part_info, current_transpose, current_octave_shift)
        note_duration, note_velocity = _apply_articulations(
            grace_duration,
            grace_velocity,
            _note_articulations(grace_note),
        )
        notes.append(
            ScoreNote(
                midi=midi,
                tick=grace_start + (index * grace_duration),
                duration=max(1, min(grace_duration, note_duration)),
                velocity=note_velocity,
            )
        )
    pending_grace_notes.clear()


def _note_articulations(note: ET.Element) -> list[str]:
    values: list[str] = []
    for articulations in note.findall(".//articulations"):
        for child in list(articulations):
            try:
                values.extend(_normalize_articulations(child.tag))
            except ValueError:
                continue
    return values


def _note_tie_types(note: ET.Element) -> set[str]:
    values: set[str] = set()
    for tie in note.findall("tie"):
        tie_type = tie.attrib.get("type", "").casefold()
        if tie_type in {"start", "stop"}:
            values.add(tie_type)
    for tied in note.findall(".//tied"):
        tie_type = tied.attrib.get("type", "").casefold()
        if tie_type in {"start", "stop"}:
            values.add(tie_type)
    return values


def _time_signature_from_spec(value: Any) -> tuple[int, int]:
    if isinstance(value, dict):
        beats = int(value.get("beats", value.get("numerator", 4)))
        beat_type = int(value.get("beat_type", value.get("denominator", 4)))
    elif value:
        text = str(value).strip()
        if "/" not in text:
            raise ValueError("time_signature must look like '4/4' or {'beats': 4, 'beat_type': 4}.")
        left, right = text.split("/", 1)
        beats, beat_type = int(left), int(right)
    else:
        beats, beat_type = 4, 4
    if beats <= 0 or beat_type <= 0:
        raise ValueError("time_signature values must be positive.")
    return beats, beat_type


def _split_score_token(token: str) -> tuple[list[str], int | None, int]:
    text = token.strip()
    if not text:
        raise ValueError("Empty score token.")
    start_ticks = None
    if "@" in text:
        text, start_text = text.split("@", 1)
        if ":" in start_text:
            start_text, duration_text = start_text.split(":", 1)
        else:
            duration_text = "1"
        start_ticks = _beat_position_to_ticks(start_text, default=0)
    elif ":" in text:
        text, duration_text = text.split(":", 1)
    else:
        duration_text = "1"
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    pitches = [piece.strip() for piece in re.split(r"[,+]", text) if piece.strip()]
    if not pitches:
        raise ValueError(f"Score token has no pitch: {token!r}.")
    return pitches, start_ticks, _beats_to_ticks(duration_text)


def _score_event_to_notes(
    raw: Any,
    cursor_tick: int,
    is_percussion: bool,
    default_velocity: int,
    *,
    base_tick: int = 0,
    default_articulations: list[str] | None = None,
) -> tuple[list[ScoreNote], int]:
    default_articulations = default_articulations or []
    if isinstance(raw, str):
        pitches, explicit_start, duration = _split_score_token(raw)
        start = cursor_tick if explicit_start is None else base_tick + explicit_start
        if len(pitches) == 1 and pitches[0].casefold() in {"rest", "r", "-"}:
            return [], duration if explicit_start is None else max(0, (start + duration) - cursor_tick)
        midis = [_drum_name_to_midi(pitch) if is_percussion else _pitch_name_to_midi(pitch) for pitch in pitches]
        note_duration, note_velocity = _apply_articulations(duration, default_velocity, default_articulations)
        return [ScoreNote(midi=midi, tick=start, duration=note_duration, velocity=note_velocity) for midi in midis], (
            duration if explicit_start is None else max(0, (start + duration) - cursor_tick)
        )

    if not isinstance(raw, dict):
        raise ValueError("Each score note must be an object or compact string token.")
    duration = _beats_to_ticks(raw.get("duration", raw.get("beats", 1)))
    start_value = raw.get("start", raw.get("beat", raw.get("onset")))
    start = cursor_tick if start_value is None else base_tick + _beat_position_to_ticks(start_value, default=0)
    if raw.get("rest") is True or str(raw.get("pitch", "")).casefold() in {"rest", "r"}:
        return [], duration if start_value is None else max(0, (start + duration) - cursor_tick)

    velocity = _velocity_from_dynamic(raw.get("dynamic", raw.get("dynamics", raw.get("velocity"))), default=default_velocity)
    articulations = _normalize_articulations(raw.get("articulation", raw.get("articulations"))) or list(default_articulations)
    note_duration, note_velocity = _apply_articulations(duration, velocity, articulations)
    if "pitches" in raw:
        pitch_values = list(raw["pitches"])
    elif "chord" in raw:
        chord = raw["chord"]
        pitch_values = list(chord) if isinstance(chord, list) else [piece for piece in re.split(r"[,+ ]+", str(chord)) if piece]
    elif "midi" in raw:
        midi_value = raw["midi"]
        pitch_values = list(midi_value) if isinstance(midi_value, list) else [midi_value]
    elif "drum" in raw:
        pitch_values = [raw["drum"]]
    else:
        pitch_values = [raw.get("pitch", raw.get("note"))]

    midis: list[int] = []
    for pitch in pitch_values:
        if pitch is None:
            raise ValueError(f"Score note is missing pitch/drum/midi: {raw!r}")
        if isinstance(pitch, int):
            midis.append(max(0, min(127, pitch)))
        elif str(pitch).strip().isdigit():
            midis.append(max(0, min(127, int(str(pitch).strip()))))
        elif is_percussion and ("drum" in raw or str(pitch).strip().casefold().replace("-", "_") in DRUM_PITCHES):
            midis.append(_drum_name_to_midi(str(pitch)))
        else:
            midis.append(_pitch_name_to_midi(str(pitch)))
    return [ScoreNote(midi=midi, tick=start, duration=note_duration, velocity=note_velocity) for midi in midis], (
        duration if start_value is None else max(0, (start + duration) - cursor_tick)
    )


def _raw_note_list(container: dict[str, Any]) -> Any:
    return container.get("notes", container.get("events", container.get("sequence")))


def _sequence_to_notes(
    raw_notes: list[Any],
    *,
    cursor_tick: int,
    base_tick: int,
    is_percussion: bool,
    default_velocity: int,
    default_articulations: list[str] | None = None,
) -> tuple[list[ScoreNote], int]:
    notes: list[ScoreNote] = []
    cursor = cursor_tick
    for raw_note in raw_notes:
        event_notes, advance = _score_event_to_notes(
            raw_note,
            cursor,
            is_percussion,
            default_velocity,
            base_tick=base_tick,
            default_articulations=default_articulations,
        )
        notes.extend(event_notes)
        cursor += advance
    return notes, cursor


def _tempo_from_root(root: ET.Element, fallback: int = 120) -> int:
    for direction in root.findall(".//direction"):
        tempo = _direction_tempo(direction)
        if tempo is not None:
            return tempo
    for sound in root.findall(".//sound"):
        tempo = sound.attrib.get("tempo")
        if tempo:
            try:
                value = int(round(float(tempo)))
                if 20 <= value <= 300:
                    return value
            except ValueError:
                pass
    for per_minute in root.findall(".//per-minute"):
        value = _int_text(per_minute, 0)
        if 20 <= value <= 300:
            return value
    return fallback


def _time_signature_from_time_element(time_el: ET.Element | None, default: tuple[int, int] = (4, 4)) -> tuple[int, int]:
    if time_el is None:
        return default
    beats = _int_text(time_el.find("beats"), default[0])
    beat_type = _int_text(time_el.find("beat-type"), default[1])
    if beats <= 0 or beat_type <= 0:
        return default
    return beats, beat_type


def _measure_repeat(measure: ET.Element, direction: str) -> ET.Element | None:
    for repeat in measure.findall("./barline/repeat"):
        if repeat.attrib.get("direction") == direction:
            return repeat
    return None


def _measure_style_repeat_count(measure: ET.Element) -> int:
    for measure_repeat in measure.findall("./attributes/measure-style/measure-repeat"):
        repeat_type = measure_repeat.attrib.get("type", "start")
        if repeat_type == "stop":
            continue
        try:
            count = int(_text(measure_repeat, "1") or "1")
        except ValueError:
            count = 1
        return max(1, min(32, count))
    return 0


def _has_measure_style_repeat(measure: ET.Element) -> bool:
    return measure.find("./attributes/measure-style/measure-repeat") is not None


def _has_playback_children(measure: ET.Element) -> bool:
    return any(child.tag in {"note", "backup", "forward"} for child in list(measure))


def _single_measure_repeat_copy(source: ET.Element, target: ET.Element) -> ET.Element:
    copied = _repeat_measure_copy(source, target)
    return copied


def _repeat_measure_copy(source: ET.Element, target: ET.Element | None) -> ET.Element:
    copied = ET.Element("measure", dict(target.attrib if target is not None else source.attrib))
    if target is not None:
        for child in list(target):
            if child.tag == "attributes":
                copied.append(copy.deepcopy(child))
    for child in list(source):
        if child.tag in {"note", "backup", "forward"}:
            copied.append(copy.deepcopy(child))
    return copied


def _expand_measure_style_repeats(measures: list[ET.Element]) -> list[ET.Element]:
    expanded: list[ET.Element] = []
    previous_playback_measure: ET.Element | None = None
    previous_playback_measures: list[ET.Element] = []
    index = 0
    while index < len(measures):
        measure = measures[index]
        repeat_count = _measure_style_repeat_count(measure)
        if repeat_count == 1 and previous_playback_measure is not None and not _has_playback_children(measure):
            repeated = _single_measure_repeat_copy(previous_playback_measure, measure)
            expanded.append(repeated)
            previous_playback_measure = repeated
            previous_playback_measures.append(repeated)
            index += 1
            continue
        if repeat_count > 1 and len(previous_playback_measures) >= repeat_count and not _has_playback_children(measure):
            sources = previous_playback_measures[-repeat_count:]
            targets: list[ET.Element | None] = [measure]
            lookahead = index + 1
            while len(targets) < repeat_count and lookahead < len(measures):
                candidate = measures[lookahead]
                if _has_playback_children(candidate) or not _has_measure_style_repeat(candidate):
                    break
                targets.append(candidate)
                lookahead += 1
            while len(targets) < repeat_count:
                targets.append(None)
            for source, target in zip(sources, targets):
                repeated = _repeat_measure_copy(source, target)
                expanded.append(repeated)
                previous_playback_measure = repeated
                previous_playback_measures.append(repeated)
            index += len([target for target in targets if target is not None])
            continue
        expanded.append(measure)
        if _has_playback_children(measure):
            previous_playback_measure = measure
            previous_playback_measures.append(measure)
        index += 1
    return expanded


def _repeat_play_count(repeat: ET.Element | None) -> int:
    if repeat is None:
        return 1
    try:
        count = int(repeat.attrib.get("times", "2"))
    except ValueError:
        count = 2
    return max(1, min(32, count))


def _measure_ending_numbers(measures: list[ET.Element]) -> list[set[int]]:
    ending_numbers: list[set[int]] = []
    active: set[int] = set()
    for measure in measures:
        measure_numbers = set(active)
        endings = measure.findall("./barline/ending")
        for ending in endings:
            numbers = {int(value) for value in re.findall(r"\d+", ending.attrib.get("number", ""))}
            if not numbers:
                continue
            measure_numbers.update(numbers)
            ending_type = ending.attrib.get("type", "")
            if ending_type == "start":
                active = set(numbers)
        ending_numbers.append(measure_numbers)
        if any(ending.attrib.get("type") in {"stop", "discontinue"} for ending in endings):
            active = set()
    return ending_numbers


def _measure_applies_to_repeat_pass(ending_numbers: set[int], pass_number: int) -> bool:
    return not ending_numbers or pass_number in ending_numbers


def _expanded_musicxml_measures(part_el: ET.Element) -> list[ET.Element]:
    measures = _expand_measure_style_repeats(list(part_el.findall("measure")))
    ending_numbers = _measure_ending_numbers(measures)
    expanded: list[ET.Element] = []
    repeat_start = 0
    current_pass = 1
    for index, measure in enumerate(measures):
        if _measure_repeat(measure, "forward") is not None:
            repeat_start = index
            current_pass = 1
        if _measure_applies_to_repeat_pass(ending_numbers[index], current_pass):
            expanded.append(measure)
        backward = _measure_repeat(measure, "backward")
        if backward is not None:
            play_count = _repeat_play_count(backward)
            for pass_number in range(2, play_count + 1):
                for repeat_index in range(repeat_start, index + 1):
                    if _measure_applies_to_repeat_pass(ending_numbers[repeat_index], pass_number):
                        expanded.append(measures[repeat_index])
            current_pass = play_count
            repeat_start = index + 1
    return expanded


def _musicxml_conductor_events(
    root: ET.Element,
    default_bpm: int,
    default_time_signature: tuple[int, int],
) -> tuple[list[ScoreTempo], list[ScoreMarker], list[ScoreTimeSignature]]:
    part_el = root.find("part")
    if part_el is None:
        beats, beat_type = default_time_signature
        return [ScoreTempo(bpm=default_bpm, tick=0)], [], [ScoreTimeSignature(beats=beats, beat_type=beat_type, tick=0)]

    divisions = 1
    current_tick = 0
    tempo_changes: dict[int, int] = {}
    markers: list[ScoreMarker] = []
    seen_markers: set[tuple[int, str]] = set()
    time_signatures: dict[int, tuple[int, int]] = {}

    for measure in _expanded_musicxml_measures(part_el):
        attributes = measure.find("attributes")
        if attributes is not None:
            time_el = attributes.find("time")
            if time_el is not None:
                time_signatures[current_tick] = _time_signature_from_time_element(time_el, default_time_signature)
            if attributes.find("divisions") is not None:
                divisions = max(1, _int_text(attributes.find("divisions"), divisions))

        for child in list(measure):
            if child.tag == "direction":
                tempo = _direction_tempo(child)
                if tempo is not None:
                    tempo_changes[current_tick] = tempo
                marker_text = _direction_marker_text(child)
                if marker_text:
                    marker_key = (current_tick, marker_text)
                    if marker_key not in seen_markers:
                        markers.append(ScoreMarker(name=marker_text, tick=current_tick))
                        seen_markers.add(marker_key)
                continue
            if child.tag == "backup":
                current_tick = max(0, current_tick - _duration_to_ticks(_int_text(child.find("duration"), 0), divisions))
                continue
            if child.tag == "forward":
                current_tick += _duration_to_ticks(_int_text(child.find("duration"), 0), divisions)
                continue
            if child.tag != "note" or child.find("grace") is not None:
                continue
            if child.find("chord") is None:
                current_tick += _duration_to_ticks(_int_text(child.find("duration"), 0), divisions)

    if 0 not in tempo_changes:
        tempo_changes[0] = default_bpm
    if 0 not in time_signatures:
        time_signatures[0] = default_time_signature
    return (
        [ScoreTempo(bpm=bpm, tick=tick) for tick, bpm in sorted(tempo_changes.items())],
        markers,
        [
            ScoreTimeSignature(beats=beats, beat_type=beat_type, tick=tick)
            for tick, (beats, beat_type) in sorted(time_signatures.items())
        ],
    )


def _time_signature_from_root(root: ET.Element) -> tuple[int, int]:
    return _time_signature_from_time_element(root.find(".//attributes/time"))


def parse_musicxml(path: str | Path, *, bpm: int | None = None) -> dict[str, Any]:
    root = _read_musicxml(path)
    part_infos = _part_infos(root)
    tempo = int(bpm) if bpm is not None else _tempo_from_root(root)
    if not 20 <= tempo <= 300:
        raise ValueError("BPM must be between 20 and 300.")
    beats, beat_type = _time_signature_from_root(root)
    key_signature = _key_signature_from_root(root)
    if bpm is None:
        tempo_changes, markers, time_signature_changes = _musicxml_conductor_events(root, tempo, (beats, beat_type))
    else:
        tempo_changes, markers = [ScoreTempo(bpm=tempo, tick=0)], []
        time_signature_changes = [ScoreTimeSignature(beats=beats, beat_type=beat_type, tick=0)]
    used_channels: set[int] = set()
    parts: list[ScorePart] = []
    harmony_events: list[tuple[int, tuple[int, ...]]] = []
    seen_harmony_events: set[tuple[int, tuple[int, ...]]] = set()
    max_score_tick = 0

    for part_el in root.findall("part"):
        part_id = part_el.attrib.get("id", f"P{len(parts) + 1}")
        part_info = part_infos.get(part_id, ScorePartInfo(name=part_id))
        name = part_info.name
        is_percussion = _is_percussion_name(name) or part_info.channel == PERCUSSION_CHANNEL
        if part_info.channel is not None:
            channel = part_info.channel
            if channel != PERCUSSION_CHANNEL:
                used_channels.add(channel)
        elif is_percussion:
            channel = PERCUSSION_CHANNEL
        else:
            channel = _next_melodic_channel(used_channels)
        if is_percussion:
            program = None
        else:
            program = part_info.program if part_info.program is not None else _program_for_name(name)

        divisions = 1
        current_tick = 0
        last_start = 0
        current_velocity = DEFAULT_VELOCITY
        current_transpose = 0
        current_octave_shift = 0
        notes: list[ScoreNote] = []
        controls: list[ScoreControlChange] = []
        pending_grace_notes: list[ET.Element] = []
        active_ties: dict[int, ScoreNote] = {}

        for measure in _expanded_musicxml_measures(part_el):
            attributes = measure.find("attributes")
            if attributes is not None:
                if attributes.find("divisions") is not None:
                    divisions = max(1, _int_text(attributes.find("divisions"), divisions))
                transpose_el = attributes.find("transpose")
                if transpose_el is not None:
                    current_transpose = _transpose_to_semitones(transpose_el)

            for child in list(measure):
                if child.tag == "direction":
                    dynamic_velocity = _direction_dynamic(child)
                    if dynamic_velocity is not None:
                        current_velocity = dynamic_velocity
                    octave_shift = _direction_octave_shift(child)
                    if octave_shift is not None:
                        current_octave_shift = octave_shift
                    pedal_value = _direction_pedal_value(child)
                    if pedal_value is not None:
                        controls.append(ScoreControlChange(tick=current_tick, controller=64, value=pedal_value))
                    continue
                if child.tag == "harmony":
                    chord_midis = _harmony_to_midis(child)
                    if chord_midis:
                        harmony_key = (current_tick, chord_midis)
                        if harmony_key not in seen_harmony_events:
                            harmony_events.append(harmony_key)
                            seen_harmony_events.add(harmony_key)
                    continue
                if child.tag == "backup":
                    current_tick = max(0, current_tick - _duration_to_ticks(_int_text(child.find("duration"), 0), divisions))
                    continue
                if child.tag == "forward":
                    current_tick += _duration_to_ticks(_int_text(child.find("duration"), 0), divisions)
                    continue
                if child.tag != "note":
                    continue
                if child.find("grace") is not None:
                    pending_grace_notes.append(child)
                    continue

                raw_duration = _int_text(child.find("duration"), 0)
                duration_ticks = _duration_to_ticks(raw_duration, divisions)
                is_chord = child.find("chord") is not None
                start_tick = last_start if is_chord else current_tick
                if not is_chord:
                    last_start = start_tick

                if child.find("rest") is None:
                    _append_grace_notes(
                        pending_grace_notes,
                        notes,
                        start_tick=start_tick,
                        part_info=part_info,
                        current_transpose=current_transpose,
                        current_octave_shift=current_octave_shift,
                        current_velocity=current_velocity,
                    )
                    midi = _musicxml_note_midi(child, part_info, current_transpose, current_octave_shift)
                    note_duration, note_velocity = _apply_articulations(
                        duration_ticks,
                        current_velocity,
                        _note_articulations(child),
                    )
                    tie_types = _note_tie_types(child)
                    tie_duration = duration_ticks if tie_types else note_duration
                    score_note = ScoreNote(midi=midi, tick=start_tick, duration=tie_duration, velocity=note_velocity)
                    if "stop" in tie_types and midi in active_ties:
                        previous = active_ties.pop(midi)
                        score_note = ScoreNote(
                            midi=midi,
                            tick=previous.tick,
                            duration=max(1, (start_tick + tie_duration) - previous.tick),
                            velocity=previous.velocity,
                        )
                        if "start" in tie_types:
                            active_ties[midi] = score_note
                        else:
                            notes.append(score_note)
                    elif "start" in tie_types:
                        if midi in active_ties:
                            notes.append(active_ties.pop(midi))
                        active_ties[midi] = score_note
                    else:
                        notes.append(score_note)

                if not is_chord:
                    current_tick += duration_ticks

        notes.extend(active_ties.values())
        notes.sort(key=lambda note: (note.tick, note.midi))
        max_score_tick = max(max_score_tick, current_tick, *(note.tick + note.duration for note in notes))
        if notes:
            parts.append(
                ScorePart(
                    part_id=part_id,
                    name=name,
                    notes=tuple(notes),
                    program=program,
                    channel=channel,
                    is_percussion=is_percussion,
                    mix=part_info.mix,
                    controls=tuple(controls),
                )
            )

    if harmony_events:
        harmony_events.sort(key=lambda item: (item[0], item[1]))
        song_end_tick = max_score_tick if max_score_tick > harmony_events[-1][0] else harmony_events[-1][0] + (beats * tab_midi.TICKS_PER_BEAT)
        harmony_notes: list[ScoreNote] = []
        for index, (tick, chord_midis) in enumerate(harmony_events):
            next_tick = harmony_events[index + 1][0] if index + 1 < len(harmony_events) else song_end_tick
            duration = max(1, next_tick - tick)
            harmony_notes.extend(
                ScoreNote(midi=midi, tick=tick, duration=duration, velocity=HARMONY_VELOCITY)
                for midi in chord_midis
            )
        if harmony_notes:
            parts.append(
                ScorePart(
                    part_id="HARMONY",
                    name="Generated Chords",
                    notes=tuple(sorted(harmony_notes, key=lambda note: (note.tick, note.midi))),
                    program=HARMONY_PROGRAM,
                    channel=_next_melodic_channel(used_channels),
                    mix=ScoreMix(volume=86, pan=64),
                )
            )

    if not parts:
        raise ValueError("No playable notes were found in the MusicXML score.")
    return {
        "title": _text(root.find("work/work-title")) or _text(root.find("movement-title")) or Path(path).stem,
        "bpm": tempo,
        "time_signature": {"beats": beats, "beat_type": beat_type},
        "key_signature": key_signature,
        "parts": parts,
        "markers": markers,
        "tempo_changes": tempo_changes,
        "time_signature_changes": time_signature_changes,
    }


def parse_score_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Parse an LLM-friendly band score JSON object into internal score parts.

    Expected shape:
      {"title": "...", "bpm": 120, "time_signature": "4/4",
       "parts": [{"name": "Guitar", "notes": [{"pitch": "E4", "duration": 1}]}]}

    Note times and durations are expressed in quarter-note beats.
    """
    if not isinstance(spec, dict):
        raise ValueError("Score spec must be a JSON object.")
    bpm = _validate_bpm(spec.get("bpm", spec.get("tempo", 120)))
    tempo_changes = _tempo_changes_from_spec(spec, bpm)
    beats, beat_type = _time_signature_from_spec(spec.get("time_signature", spec.get("meter", "4/4")))
    time_signature_changes = _time_signature_changes_from_spec(spec, beats, beat_type)
    key_signature = _key_signature_from_spec(spec.get("key_signature", spec.get("key")))
    raw_parts = spec.get("parts", spec.get("tracks"))
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ValueError("Score spec must include a non-empty parts list.")

    used_channels: set[int] = set()
    parsed_parts: list[ScorePart] = []
    markers: list[ScoreMarker] = []
    markers_collected = False
    for index, raw_part in enumerate(raw_parts, start=1):
        if not isinstance(raw_part, dict):
            raise ValueError("Each score part must be an object.")
        name = str(raw_part.get("name") or raw_part.get("part") or raw_part.get("instrument") or f"Part {index}")
        instrument = str(raw_part.get("instrument") or name)
        is_percussion = bool(raw_part.get("is_percussion", False) or raw_part.get("percussion", False) or _is_percussion_name(instrument))
        if raw_part.get("channel") is not None:
            channel = max(1, min(16, int(raw_part["channel"]))) - 1
            if channel != PERCUSSION_CHANNEL:
                used_channels.add(channel)
        elif is_percussion:
            channel = PERCUSSION_CHANNEL
        else:
            channel = _next_melodic_channel(used_channels)

        if is_percussion:
            program = None
        elif raw_part.get("program") is not None:
            program = max(0, min(127, int(raw_part["program"])))
        else:
            program = _program_for_name(instrument)
        mix = _mix_from_part(raw_part)

        default_velocity = _velocity_from_dynamic(
            raw_part.get("dynamic", raw_part.get("dynamics", raw_part.get("velocity"))),
            default=DEFAULT_VELOCITY,
        )
        default_articulations = _normalize_articulations(raw_part.get("articulation", raw_part.get("articulations")))
        cursor_tick = 0
        notes: list[ScoreNote] = []
        raw_sections = raw_part.get("sections")
        if isinstance(raw_sections, list) and raw_sections:
            collect_markers = not markers_collected
            if collect_markers:
                markers_collected = True
            for section_index, raw_section in enumerate(raw_sections, start=1):
                if not isinstance(raw_section, dict):
                    raise ValueError("Each score section must be an object.")
                section_notes = _raw_note_list(raw_section)
                if not isinstance(section_notes, list) or not section_notes:
                    continue
                repeat_count = max(1, min(128, int(raw_section.get("repeat", raw_section.get("repeats", 1)))))
                section_name = str(raw_section.get("name") or raw_section.get("section") or f"Section {section_index}")
                section_velocity = _velocity_from_dynamic(
                    raw_section.get("dynamic", raw_section.get("dynamics", raw_section.get("velocity"))),
                    default=default_velocity,
                )
                section_articulations = (
                    _normalize_articulations(raw_section.get("articulation", raw_section.get("articulations")))
                    or default_articulations
                )
                for repeat_index in range(repeat_count):
                    section_start = cursor_tick
                    if collect_markers:
                        marker_name = section_name if repeat_count == 1 else f"{section_name} {repeat_index + 1}"
                        markers.append(ScoreMarker(name=marker_name, tick=section_start))
                    section_event_notes, cursor_tick = _sequence_to_notes(
                        section_notes,
                        cursor_tick=cursor_tick,
                        base_tick=section_start,
                        is_percussion=is_percussion,
                        default_velocity=section_velocity,
                        default_articulations=section_articulations,
                    )
                    notes.extend(section_event_notes)
        else:
            raw_notes = _raw_note_list(raw_part)
            if not isinstance(raw_notes, list) or not raw_notes:
                continue
            event_notes, cursor_tick = _sequence_to_notes(
                raw_notes,
                cursor_tick=cursor_tick,
                base_tick=0,
                is_percussion=is_percussion,
                default_velocity=default_velocity,
                default_articulations=default_articulations,
            )
            notes.extend(event_notes)
        notes.sort(key=lambda note: (note.tick, note.midi))
        if notes:
            parsed_parts.append(
                ScorePart(
                    part_id=str(raw_part.get("id") or f"P{index}"),
                    name=name,
                    notes=tuple(notes),
                    program=program,
                    channel=channel,
                    is_percussion=is_percussion,
                    mix=mix,
                )
            )

    if not parsed_parts:
        raise ValueError("No playable notes were found in the score spec.")
    return {
        "title": str(spec.get("title") or spec.get("name") or "GarageBand Score Spec"),
        "bpm": bpm,
        "time_signature": {"beats": beats, "beat_type": beat_type},
        "key_signature": key_signature,
        "parts": parsed_parts,
        "markers": markers,
        "tempo_changes": tempo_changes,
        "time_signature_changes": time_signature_changes,
    }


def validate_score_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate a score spec and return the parsed summary without writing MIDI."""
    score = parse_score_spec(spec)
    parts: list[ScorePart] = list(score["parts"])
    markers: list[ScoreMarker] = list(score.get("markers", []))
    tempo_changes: list[ScoreTempo] = list(score.get("tempo_changes", [ScoreTempo(bpm=int(score["bpm"]), tick=0)]))
    time_signature_changes: list[ScoreTimeSignature] = list(
        score.get(
            "time_signature_changes",
            [
                ScoreTimeSignature(
                    beats=int(score.get("time_signature", {}).get("beats", 4)),
                    beat_type=int(score.get("time_signature", {}).get("beat_type", 4)),
                    tick=0,
                )
            ],
        )
    )
    key_signature = score.get("key_signature")
    summaries = []
    for part in parts:
        last_tick = max(note.tick + note.duration for note in part.notes)
        velocities = [note.velocity for note in part.notes]
        summaries.append(
            {
                "part_id": part.part_id,
                "name": part.name,
                "notes": len(part.notes),
                "channel": part.channel + 1,
                "program": part.program,
                "is_percussion": part.is_percussion,
                "first_tick": part.notes[0].tick,
                "last_tick": last_tick,
                "duration_beats": round(last_tick / tab_midi.TICKS_PER_BEAT, 4),
                "velocity": {
                    "min": min(velocities),
                    "max": max(velocities),
                },
                "mix": part.mix.as_dict(),
                "controls": len(part.controls),
            }
        )
    return {
        "ok": True,
        "format": "garageband_score_spec_v1",
        "title": str(score["title"]),
        "bpm": score["bpm"],
        "time_signature": score["time_signature"],
        "time_signature_changes": [_time_signature_change_summary(time_signature) for time_signature in time_signature_changes],
        "key_signature": _key_signature_summary(key_signature),
        "tempo_changes": [
            {
                "bpm": tempo.bpm,
                "tick": tempo.tick,
                "beat": round(tempo.tick / tab_midi.TICKS_PER_BEAT, 4),
            }
            for tempo in tempo_changes
        ],
        "tracks": len(summaries) + 1,
        "parts": summaries,
        "markers": [
            {
                "name": marker.name,
                "tick": marker.tick,
                "beat": round(marker.tick / tab_midi.TICKS_PER_BEAT, 4),
            }
            for marker in markers
        ],
        "note_count": sum(part["notes"] for part in summaries),
        "duration_beats": max(part["duration_beats"] for part in summaries),
    }


def _meta_payload(kind: int, data: bytes) -> bytes:
    return b"\xff" + bytes([kind]) + tab_midi._var_len(len(data)) + data


def _key_signature_summary(key_signature: ScoreKeySignature | None) -> dict[str, Any] | None:
    if key_signature is None:
        return None
    return {
        "name": key_signature.name,
        "fifths": key_signature.fifths,
        "mode": key_signature.mode,
        "tick": key_signature.tick,
        "beat": round(key_signature.tick / tab_midi.TICKS_PER_BEAT, 4),
    }


def _conductor_track(
    bpm: int,
    beats: int,
    beat_type: int,
    markers: list[ScoreMarker] | None = None,
    tempo_changes: list[ScoreTempo] | None = None,
    time_signature_changes: list[ScoreTimeSignature] | None = None,
    key_signature: ScoreKeySignature | None = None,
) -> bytes:
    events: list[tuple[int, int, bytes]] = [
        (0, 0, _meta_payload(0x03, b"Tempo")),
    ]
    time_map = time_signature_changes or [ScoreTimeSignature(beats=beats, beat_type=beat_type, tick=0)]
    if all(time_signature.tick != 0 for time_signature in time_map):
        time_map = [ScoreTimeSignature(beats=beats, beat_type=beat_type, tick=0), *time_map]
    for time_signature in time_map:
        denominator_power = 0
        value = max(1, time_signature.beat_type)
        while value > 1 and value % 2 == 0:
            denominator_power += 1
            value //= 2
        events.append(
            (
                max(0, time_signature.tick),
                2,
                _meta_payload(0x58, bytes([max(1, min(255, time_signature.beats)), denominator_power, 24, 8])),
            )
        )
    tempo_map = tempo_changes or [ScoreTempo(bpm=bpm, tick=0)]
    if all(tempo.tick != 0 for tempo in tempo_map):
        tempo_map = [ScoreTempo(bpm=bpm, tick=0), *tempo_map]
    for tempo in tempo_map:
        micros_per_quarter = int(60_000_000 / tempo.bpm)
        events.append((max(0, tempo.tick), 1, _meta_payload(0x51, micros_per_quarter.to_bytes(3, "big"))))
    if key_signature is not None:
        fifths_byte = key_signature.fifths & 0xFF
        mode_byte = 1 if key_signature.mode == "minor" else 0
        events.append((max(0, key_signature.tick), 2, _meta_payload(0x59, bytes([fifths_byte, mode_byte]))))
    for marker in markers or []:
        name = marker.name.encode("utf-8")[:127]
        events.append((max(0, marker.tick), 3, _meta_payload(0x06, name)))

    conductor = bytearray()
    last_tick = 0
    for tick, _, payload in sorted(events, key=lambda item: (item[0], item[1], item[2])):
        conductor += tab_midi._midi_event(tick - last_tick, payload)
        last_tick = tick
    conductor += tab_midi._meta(0, 0x2F, b"")
    return bytes(conductor)


def write_score_midi(score: dict[str, Any], output_path: str | Path, *, velocity: int = DEFAULT_VELOCITY) -> Path:
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    velocity = max(1, min(127, int(velocity)))
    parts: list[ScorePart] = list(score["parts"])
    beats = int(score.get("time_signature", {}).get("beats", 4))
    beat_type = int(score.get("time_signature", {}).get("beat_type", 4))
    key_signature = score.get("key_signature")
    time_signature_changes = list(
        score.get("time_signature_changes", [ScoreTimeSignature(beats=beats, beat_type=beat_type, tick=0)])
    )
    tracks = [
        tab_midi._chunk(
            b"MTrk",
            _conductor_track(
                int(score["bpm"]),
                beats,
                beat_type,
                list(score.get("markers", [])),
                list(score.get("tempo_changes", [])),
                time_signature_changes,
                key_signature,
            ),
        )
    ]

    for part in parts:
        events: list[tuple[int, int, bytes]] = []
        if part.program is not None:
            events.append((0, 0, bytes([0xC0 | part.channel, part.program])))
        for mix_name, controller in MIX_CC.items():
            value = getattr(part.mix, mix_name)
            if value is not None:
                events.append((0, 1, bytes([0xB0 | part.channel, controller, value])))
        for control in part.controls:
            controller = max(0, min(127, int(control.controller)))
            value = max(0, min(127, int(control.value)))
            events.append((max(0, control.tick), 1, bytes([0xB0 | part.channel, controller, value])))
        for note in part.notes:
            note_velocity = max(1, min(127, note.velocity or velocity))
            events.append((note.tick, 2, bytes([0x90 | part.channel, note.midi, note_velocity])))
            events.append((note.tick + note.duration, 0, bytes([0x80 | part.channel, note.midi, 0])))
        tracks.append(tab_midi._chunk(b"MTrk", tab_midi._track_from_events(part.name, events)))

    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), tab_midi.TICKS_PER_BEAT)
    output.write_bytes(header + b"".join(tracks))
    return output


def musicxml_to_midi(
    score_path: str | Path,
    output_path: str | Path,
    *,
    bpm: int | None = None,
    velocity: int = DEFAULT_VELOCITY,
) -> dict[str, Any]:
    score = parse_musicxml(score_path, bpm=bpm)
    output = write_score_midi(score, output_path, velocity=velocity)
    return _score_result_summary(score, output, source=str(Path(score_path).expanduser().resolve()), supported_input="MusicXML .musicxml/.xml or compressed .mxl score-partwise/score-timewise files")


def score_spec_to_midi(
    spec: dict[str, Any],
    output_path: str | Path,
    *,
    velocity: int = DEFAULT_VELOCITY,
    source: str | None = None,
) -> dict[str, Any]:
    score = parse_score_spec(spec)
    output = write_score_midi(score, output_path, velocity=velocity)
    return _score_result_summary(score, output, source=source, supported_input="LLM-friendly JSON score spec")


def _score_result_summary(
    score: dict[str, Any],
    output: Path,
    *,
    source: str | None,
    supported_input: str,
) -> dict[str, Any]:
    parts: list[ScorePart] = list(score["parts"])
    markers: list[ScoreMarker] = list(score.get("markers", []))
    tempo_changes: list[ScoreTempo] = list(score.get("tempo_changes", [ScoreTempo(bpm=int(score["bpm"]), tick=0)]))
    time_signature_changes: list[ScoreTimeSignature] = list(
        score.get(
            "time_signature_changes",
            [
                ScoreTimeSignature(
                    beats=int(score.get("time_signature", {}).get("beats", 4)),
                    beat_type=int(score.get("time_signature", {}).get("beat_type", 4)),
                    tick=0,
                )
            ],
        )
    )
    key_signature = score.get("key_signature")
    track_summaries = []
    for part in parts:
        last_tick = max(note.tick + note.duration for note in part.notes)
        velocities = [note.velocity for note in part.notes]
        track_summaries.append(
            {
                "part_id": part.part_id,
                "name": part.name,
                "notes": len(part.notes),
                "channel": part.channel + 1,
                "program": part.program,
                "is_percussion": part.is_percussion,
                "first_tick": part.notes[0].tick,
                "last_tick": last_tick,
                "velocity": {
                    "min": min(velocities),
                    "max": max(velocities),
                },
                "mix": part.mix.as_dict(),
                "controls": len(part.controls),
            }
        )
    return {
        "path": str(output),
        "source": source,
        "title": str(score["title"]),
        "bpm": score["bpm"],
        "time_signature": score["time_signature"],
        "time_signature_changes": [_time_signature_change_summary(time_signature) for time_signature in time_signature_changes],
        "key_signature": _key_signature_summary(key_signature),
        "tempo_changes": [
            {
                "bpm": tempo.bpm,
                "tick": tempo.tick,
                "beat": round(tempo.tick / tab_midi.TICKS_PER_BEAT, 4),
            }
            for tempo in tempo_changes
        ],
        "tracks": len(track_summaries) + 1,
        "parts": track_summaries,
        "markers": [
            {
                "name": marker.name,
                "tick": marker.tick,
                "beat": round(marker.tick / tab_midi.TICKS_PER_BEAT, 4),
            }
            for marker in markers
        ],
        "note_count": sum(part["notes"] for part in track_summaries),
        "supported_input": supported_input,
    }


def safe_score_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "garageband-score"

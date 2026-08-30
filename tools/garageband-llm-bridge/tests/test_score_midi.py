"""Tests for MusicXML full-score to multi-track MIDI conversion."""

from __future__ import annotations

import pytest

from garageband_bridge import core, score_midi


BAND_SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <work><work-title>Tiny Band</work-title></work>
  <part-list>
    <score-part id="P1"><part-name>Electric Guitar</part-name></score-part>
    <score-part id="P2"><part-name>Electric Bass</part-name></score-part>
    <score-part id="P3"><part-name>Drum Kit</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction placement="above"><sound tempo="132"/></direction>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>B</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <note><pitch><step>E</step><octave>2</octave></pitch><duration>2</duration><type>half</type></note>
      <note><pitch><step>B</step><octave>1</octave></pitch><duration>2</duration><type>half</type></note>
    </measure>
  </part>
  <part id="P3">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <note>
        <unpitched><display-step>C</display-step><display-octave>4</display-octave></unpitched>
        <duration>1</duration><type>quarter</type>
      </note>
      <note>
        <unpitched><display-step>D</display-step><display-octave>4</display-octave></unpitched>
        <duration>1</duration><type>quarter</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""

TIMEWISE_BAND_SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-timewise version="3.1">
  <work><work-title>Tiny Timewise Band</work-title></work>
  <part-list>
    <score-part id="P1"><part-name>Electric Piano</part-name></score-part>
    <score-part id="P2"><part-name>Electric Bass</part-name></score-part>
  </part-list>
  <measure number="1">
    <part id="P1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction placement="above"><sound tempo="104"/></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </part>
    <part id="P2">
      <attributes><divisions>1</divisions></attributes>
      <note><pitch><step>C</step><octave>2</octave></pitch><duration>2</duration><type>half</type></note>
    </part>
  </measure>
  <measure number="2">
    <part id="P1">
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
    </part>
    <part id="P2">
      <note><pitch><step>G</step><octave>1</octave></pitch><duration>2</duration><type>half</type></note>
    </part>
  </measure>
</score-timewise>
"""

SCORE_SPEC = {
    "title": "Tiny JSON Band",
    "bpm": 132,
    "time_signature": "4/4",
    "parts": [
        {
            "name": "Electric Guitar",
            "instrument": "electric guitar",
            "notes": [
                {"pitch": "E4", "duration": 1},
                {"pitch": "G4", "duration": 1},
                {"pitches": ["E4", "G4", "B4"], "duration": 2},
            ],
        },
        {
            "name": "Electric Bass",
            "instrument": "electric bass",
            "notes": [
                {"pitch": "E2", "duration": 2},
                {"pitch": "B1", "duration": 2},
            ],
        },
        {
            "name": "Drum Kit",
            "is_percussion": True,
            "notes": [
                {"drum": "kick", "duration": 1},
                {"drum": "snare", "duration": 1},
                {"drum": "closed_hat", "duration": 0.5},
                {"drum": "closed_hat", "duration": 0.5},
            ],
        },
    ],
}

SIMPLE_TAB = """e|--0--2--3--|
B|--1--3--0--|
G|--0--2--0--|
D|--2--0--0--|
A|--3-----2--|
E|--------3--|"""


def test_musicxml_to_midi_keeps_band_parts(tmp_path):
    score_path = tmp_path / "band.musicxml"
    midi_path = tmp_path / "band.mid"
    score_path.write_text(BAND_SCORE, encoding="utf-8")

    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert result["title"] == "Tiny Band"
    assert result["bpm"] == 132
    assert result["tracks"] == 4  # conductor + three score parts
    assert result["note_count"] == 7
    assert [part["name"] for part in result["parts"]] == ["Electric Guitar", "Electric Bass", "Drum Kit"]
    assert result["parts"][2]["channel"] == 10
    assert info["track_names"] == ["Tempo", "Electric Guitar", "Electric Bass", "Drum Kit"]
    assert info["note_on_by_channel"]["10"] == 2


def test_musicxml_drum_score_instrument_names_map_unpitched_notes(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1">
      <part-name>Drum Kit</part-name>
      <score-instrument id="P1-I36"><instrument-name>Acoustic Bass Drum</instrument-name></score-instrument>
      <score-instrument id="P1-I38"><instrument-name>Acoustic Snare</instrument-name></score-instrument>
      <score-instrument id="P1-I42"><instrument-name>Closed Hi-Hat</instrument-name></score-instrument>
    </score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <note>
        <instrument id="P1-I36"/>
        <unpitched><display-step>C</display-step><display-octave>4</display-octave></unpitched>
        <duration>1</duration>
      </note>
      <note>
        <instrument id="P1-I38"/>
        <unpitched><display-step>C</display-step><display-octave>4</display-octave></unpitched>
        <duration>1</duration>
      </note>
      <note>
        <instrument id="P1-I42"/>
        <unpitched><display-step>C</display-step><display-octave>4</display-octave></unpitched>
        <duration>1</duration>
      </note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "drum-map.musicxml"
    midi_path = tmp_path / "drum-map.mid"
    score_path.write_text(score, encoding="utf-8")

    parsed = score_midi.parse_musicxml(score_path)
    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert [note.midi for note in parsed["parts"][0].notes] == [36, 38, 42]
    assert result["parts"][0]["channel"] == 10
    assert result["note_count"] == 3
    assert info["note_on_by_channel"] == {"10": 3}


def test_musicxml_drum_midi_unpitched_maps_instrument_ids(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1">
      <part-name>Drum Kit</part-name>
      <score-instrument id="P1-I1"><instrument-name>Drum 1</instrument-name></score-instrument>
      <score-instrument id="P1-I2"><instrument-name>Drum 2</instrument-name></score-instrument>
      <score-instrument id="P1-I3"><instrument-name>Drum 3</instrument-name></score-instrument>
      <midi-instrument id="P1-I1"><midi-channel>10</midi-channel><midi-unpitched>36</midi-unpitched></midi-instrument>
      <midi-instrument id="P1-I2"><midi-unpitched>38</midi-unpitched></midi-instrument>
      <midi-instrument id="P1-I3"><midi-unpitched>42</midi-unpitched></midi-instrument>
    </score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <note>
        <instrument id="P1-I1"/>
        <unpitched><display-step>C</display-step><display-octave>4</display-octave></unpitched>
        <duration>1</duration>
      </note>
      <note>
        <instrument id="P1-I2"/>
        <unpitched><display-step>C</display-step><display-octave>4</display-octave></unpitched>
        <duration>1</duration>
      </note>
      <note>
        <instrument id="P1-I3"/>
        <unpitched><display-step>C</display-step><display-octave>4</display-octave></unpitched>
        <duration>1</duration>
      </note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "drum-midi-unpitched.musicxml"
    midi_path = tmp_path / "drum-midi-unpitched.mid"
    score_path.write_text(score, encoding="utf-8")

    parsed = score_midi.parse_musicxml(score_path)
    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert [note.midi for note in parsed["parts"][0].notes] == [36, 38, 42]
    assert result["parts"][0]["channel"] == 10
    assert result["note_count"] == 3
    assert info["note_on_by_channel"] == {"10": 3}


def test_score_timewise_musicxml_converts_to_multi_track_midi(tmp_path):
    score_path = tmp_path / "timewise.musicxml"
    midi_path = tmp_path / "timewise.mid"
    score_path.write_text(TIMEWISE_BAND_SCORE, encoding="utf-8")

    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert result["title"] == "Tiny Timewise Band"
    assert result["bpm"] == 104
    assert result["tracks"] == 3
    assert result["note_count"] == 5
    assert [part["name"] for part in result["parts"]] == ["Electric Piano", "Electric Bass"]
    assert info["track_names"] == ["Tempo", "Electric Piano", "Electric Bass"]
    assert info["note_on_by_channel"] == {"1": 3, "2": 2}
    assert info["time_signature"] == {"beats": 4, "beat_type": 4, "tick": 0, "beat": 0.0}


def test_core_score_to_midi_can_override_tempo(tmp_path):
    score_path = tmp_path / "band.musicxml"
    midi_path = tmp_path / "override.mid"
    score_path.write_text(BAND_SCORE, encoding="utf-8")

    result = core.create_midi_from_score(str(score_path), str(midi_path), bpm=96, open_in_garageband=False)

    assert result["bpm"] == 96
    assert midi_path.exists()
    assert result["parts"][0]["program"] == 29


def test_program_name_mapping_prefers_specific_instruments():
    assert score_midi._program_for_name("Electric Guitar") == 29
    assert score_midi._program_for_name("Acoustic Guitar") == 25
    assert score_midi._program_for_name("Bassoon") == 70
    assert score_midi._program_for_name("Double Bass") == 43
    assert score_midi._program_for_name("Electric Bass") == 33


def test_musicxml_midi_instrument_metadata_sets_program_channel_and_mix(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1">
      <part-name>Lead Synth</part-name>
      <midi-instrument id="P1-I1">
        <midi-channel>3</midi-channel>
        <midi-program>81</midi-program>
        <volume>80</volume>
        <pan>0</pan>
      </midi-instrument>
    </score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "midi-instrument.musicxml"
    midi_path = tmp_path / "midi-instrument.mid"
    score_path.write_text(score, encoding="utf-8")

    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert result["parts"][0]["channel"] == 3
    assert result["parts"][0]["program"] == 80
    assert result["parts"][0]["mix"] == {"volume": 102, "pan": 64}
    assert info["note_on_by_channel"]["3"] == 1
    assert info["control_changes"]["3"]["volume"][0]["value"] == 102
    assert info["control_changes"]["3"]["pan"][0]["value"] == 64


def test_musicxml_pedal_directions_write_sustain_control_changes(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <direction><direction-type><pedal type="start"/></direction-type></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
      <direction><direction-type><pedal type="stop"/></direction-type></direction>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "pedal.musicxml"
    midi_path = tmp_path / "pedal.mid"
    score_path.write_text(score, encoding="utf-8")

    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert result["parts"][0]["controls"] == 2
    assert info["control_changes"]["1"]["sustain"] == [
        {"tick": 0, "beat": 0.0, "value": 127},
        {"tick": 480, "beat": 1.0, "value": 0},
    ]


def test_musicxml_transpose_uses_sounding_pitch(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Bb Trumpet</part-name></score-part>
    <score-part id="P2"><part-name>Piccolo</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <transpose><chromatic>-2</chromatic></transpose>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <transpose><chromatic>0</chromatic><octave-change>1</octave-change></transpose>
      </attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>1</duration></note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "transposed.musicxml"
    midi_path = tmp_path / "transposed.mid"
    score_path.write_text(score, encoding="utf-8")

    parsed = score_midi.parse_musicxml(score_path)
    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert [note.midi for note in parsed["parts"][0].notes] == [58, 60]
    assert [note.midi for note in parsed["parts"][1].notes] == [84]
    assert result["note_count"] == 3
    assert info["note_on_by_channel"] == {"1": 2, "2": 1}


def test_musicxml_octave_shift_changes_sounding_pitch_until_stop(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <direction><direction-type><octave-shift type="up" size="8"/></direction-type></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
      <direction><direction-type><octave-shift type="stop" size="8"/></direction-type></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
      <direction><direction-type><octave-shift type="down" size="8"/></direction-type></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "octave-shift.musicxml"
    midi_path = tmp_path / "octave-shift.mid"
    score_path.write_text(score, encoding="utf-8")

    parsed = score_midi.parse_musicxml(score_path)
    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert [note.midi for note in parsed["parts"][0].notes] == [72, 60, 48]
    assert result["note_count"] == 3
    assert info["note_on_by_channel"] == {"1": 3}


def test_make_from_score_without_open_skips_garageband(tmp_path):
    score_path = tmp_path / "band.musicxml"
    score_path.write_text(BAND_SCORE, encoding="utf-8")

    result = core.make_from_score(
        score_path=str(score_path),
        output_dir=str(tmp_path / "out"),
        name="tiny band",
        open_in_garageband=False,
    )

    assert result["source"]["kind"] == "musicxml_score"
    assert result["midi"]["note_count"] == 7
    assert result["snapshot"] is None
    assert result["screenshot"] is None


def test_score_spec_to_midi_supports_chords_and_drums(tmp_path):
    midi_path = tmp_path / "score-spec.mid"

    result = score_midi.score_spec_to_midi(SCORE_SPEC, midi_path)
    info = core.midi_info(str(midi_path))

    assert result["title"] == "Tiny JSON Band"
    assert result["tracks"] == 4
    assert result["note_count"] == 11
    assert result["parts"][0]["notes"] == 5
    assert result["parts"][2]["channel"] == 10
    assert info["note_on_by_channel"]["1"] == 5
    assert info["note_on_by_channel"]["10"] == 4


def test_score_spec_schema_is_llm_usable():
    schema = score_midi.score_spec_schema()

    assert schema["format"] == "garageband_score_spec_v1"
    assert "parts" in schema["required_top_level"]
    assert "sections" in schema["part"]
    assert "mix" in schema["part"]
    assert "pan" in schema["mix"]
    assert "tempo_changes" in schema["top_level"]
    assert "time_signature_changes" in schema["top_level"]
    assert "key_signature" in schema["top_level"]
    assert "C4" in schema["pitch_examples"]
    assert "Bb major" in schema["key_examples"]
    assert "kick" in schema["drum_names"]
    assert "mf" in schema["dynamic_markings"]
    assert "staccato" in schema["articulations"]
    assert schema["minimal_example"]["parts"]


def test_validate_score_spec_summarizes_without_writing_midi():
    result = score_midi.validate_score_spec(SCORE_SPEC)

    assert result["ok"] is True
    assert result["title"] == "Tiny JSON Band"
    assert result["tracks"] == 4
    assert result["note_count"] == 11
    assert result["duration_beats"] == 4


def test_validate_score_spec_rejects_bad_pitch():
    broken = {
        "parts": [
            {"name": "Guitar", "notes": [{"pitch": "H4", "duration": 1}]},
        ]
    }

    with pytest.raises(ValueError, match="Unsupported pitch"):
        score_midi.validate_score_spec(broken)


def test_score_spec_compact_tokens(tmp_path):
    spec = {
        "title": "Compact",
        "parts": [
            {"name": "Piano", "notes": ["C4:1", "[E4,G4,B4]:2", "rest:1", "C5@5:1"]},
            {"name": "Drum Kit", "is_percussion": True, "notes": ["kick:1", "snare:1"]},
        ],
    }

    result = score_midi.score_spec_to_midi(spec, tmp_path / "compact.mid")

    assert result["note_count"] == 7
    assert result["parts"][0]["notes"] == 5
    assert result["parts"][1]["channel"] == 10


def test_score_spec_dynamics_write_midi_velocities(tmp_path):
    spec = {
        "title": "Dynamic Band",
        "parts": [
            {
                "name": "Piano",
                "instrument": "piano",
                "dynamic": "p",
                "notes": [
                    {"pitch": "C4", "duration": 1},
                    {"pitch": "D4", "duration": 1, "dynamic": "ff"},
                    {"pitch": "E4", "duration": 1, "velocity": 77},
                ],
            }
        ],
    }

    result = score_midi.score_spec_to_midi(spec, tmp_path / "dynamic.mid")
    info = core.midi_info(str(tmp_path / "dynamic.mid"))

    assert result["parts"][0]["velocity"] == {"min": 52, "max": 112}
    assert info["velocity_by_channel"]["1"]["min"] == 52
    assert info["velocity_by_channel"]["1"]["max"] == 112


def test_score_spec_articulations_shape_lengths_and_velocity(tmp_path):
    spec = {
        "title": "Articulation Band",
        "parts": [
            {
                "name": "Piano",
                "instrument": "piano",
                "notes": [
                    {"pitch": "C4", "duration": 1, "articulation": "staccato"},
                    {"pitch": "D4", "duration": 1, "articulation": "accent"},
                    {"pitch": "E4", "duration": 1, "articulation": "legato"},
                ],
            }
        ],
    }

    score_midi.score_spec_to_midi(spec, tmp_path / "articulation.mid")
    info = core.midi_info(str(tmp_path / "articulation.mid"))

    assert info["note_length_by_channel"]["1"]["min_ticks"] == 240
    assert info["note_length_by_channel"]["1"]["max_ticks"] == 518
    assert info["velocity_by_channel"]["1"]["max"] == 104


def test_score_spec_mix_writes_midi_control_changes(tmp_path):
    spec = {
        "title": "Mixed Band",
        "parts": [
            {
                "name": "Guitar",
                "instrument": "electric guitar",
                "volume": "80%",
                "pan": "left",
                "notes": ["E4:1"],
            },
            {
                "name": "Pad",
                "instrument": "synth",
                "mix": {"volume": 0.5, "pan": 0.75, "reverb": 96, "chorus": "25%"},
                "notes": ["C4:1"],
            },
        ],
    }

    validation = score_midi.validate_score_spec(spec)
    result = score_midi.score_spec_to_midi(spec, tmp_path / "mixed.mid")
    info = core.midi_info(str(tmp_path / "mixed.mid"))

    assert validation["parts"][0]["mix"] == {"volume": 102, "pan": 0}
    assert validation["parts"][1]["mix"] == {"volume": 64, "pan": 111, "reverb": 96, "chorus": 32}
    assert result["parts"][1]["mix"]["pan"] == 111
    assert info["control_changes"]["1"]["volume"][0]["value"] == 102
    assert info["control_changes"]["1"]["pan"][0]["value"] == 0
    assert info["control_changes"]["2"]["volume"][0]["value"] == 64
    assert info["control_changes"]["2"]["pan"][0]["value"] == 111
    assert info["control_changes"]["2"]["reverb"][0]["value"] == 96
    assert info["control_changes"]["2"]["chorus"][0]["value"] == 32


def test_score_spec_tempo_changes_write_conductor_track(tmp_path):
    spec = {
        "title": "Tempo Map",
        "bpm": 96,
        "tempo_changes": [
            {"beat": 0, "bpm": 96},
            {"beat": 4, "bpm": 124},
            {"start": 8, "tempo": 72},
        ],
        "parts": [
            {"name": "Piano", "notes": ["C4:4", "D4:4", "E4:4"]},
        ],
    }

    validation = score_midi.validate_score_spec(spec)
    result = score_midi.score_spec_to_midi(spec, tmp_path / "tempo-map.mid")
    info = core.midi_info(str(tmp_path / "tempo-map.mid"))

    expected = [
        {"bpm": 96, "tick": 0, "beat": 0.0},
        {"bpm": 124, "tick": 1920, "beat": 4.0},
        {"bpm": 72, "tick": 3840, "beat": 8.0},
    ]
    assert validation["tempo_changes"] == expected
    assert result["tempo_changes"] == expected
    assert info["tempo_changes"] == [
        {"bpm": 96.0, "tick": 0, "beat": 0.0},
        {"bpm": 124.0, "tick": 1920, "beat": 4.0},
        {"bpm": 72.0, "tick": 3840, "beat": 8.0},
    ]


def test_score_spec_time_signature_changes_write_conductor_track(tmp_path):
    spec = {
        "title": "Meter Map",
        "time_signature": "4/4",
        "time_signature_changes": [
            {"beat": 0, "time_signature": "4/4"},
            {"beat": 4, "time_signature": "7/8"},
        ],
        "parts": [
            {"name": "Piano", "notes": ["C4:4", "D4:3.5"]},
        ],
    }

    validation = score_midi.validate_score_spec(spec)
    result = score_midi.score_spec_to_midi(spec, tmp_path / "meter-map.mid")
    info = core.midi_info(str(tmp_path / "meter-map.mid"))

    expected = [
        {"beats": 4, "beat_type": 4, "tick": 0, "beat": 0.0},
        {"beats": 7, "beat_type": 8, "tick": 1920, "beat": 4.0},
    ]
    assert validation["time_signature_changes"] == expected
    assert result["time_signature_changes"] == expected
    assert info["time_signatures"] == expected
    assert info["time_signature"] == expected[0]


def test_score_spec_key_signature_writes_conductor_track(tmp_path):
    spec = {
        "title": "Keyed Band",
        "key_signature": "Bb major",
        "parts": [
            {"name": "Piano", "notes": ["Bb3:1", "D4:1", "F4:2"]},
        ],
    }

    validation = score_midi.validate_score_spec(spec)
    result = score_midi.score_spec_to_midi(spec, tmp_path / "keyed.mid")
    info = core.midi_info(str(tmp_path / "keyed.mid"))

    expected = {"name": "Bb major", "fifths": -2, "mode": "major", "tick": 0, "beat": 0.0}
    assert validation["key_signature"] == expected
    assert result["key_signature"] == expected
    assert info["key_signature"] == expected
    assert info["key_signatures"] == [expected]


def test_score_spec_sections_repeat_and_write_markers(tmp_path):
    spec = {
        "title": "Section Song",
        "parts": [
            {
                "name": "Piano",
                "instrument": "piano",
                "sections": [
                    {"name": "Intro", "notes": [{"pitch": "C4", "duration": 1}]},
                    {
                        "name": "Verse",
                        "repeat": 2,
                        "notes": [
                            {"pitch": "D4", "duration": 1},
                            {"pitch": "E4", "duration": 1},
                        ],
                    },
                ],
            }
        ],
    }

    validation = score_midi.validate_score_spec(spec)
    result = score_midi.score_spec_to_midi(spec, tmp_path / "sections.mid")
    info = core.midi_info(str(tmp_path / "sections.mid"))

    assert validation["markers"] == [
        {"name": "Intro", "tick": 0, "beat": 0.0},
        {"name": "Verse 1", "tick": 480, "beat": 1.0},
        {"name": "Verse 2", "tick": 1440, "beat": 3.0},
    ]
    assert result["note_count"] == 5
    assert result["markers"] == validation["markers"]
    assert info["markers"] == validation["markers"]
    assert info["note_on_count"] == 5


def test_musicxml_dynamics_apply_to_following_notes(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <direction><direction-type><dynamics><p/></dynamics></direction-type></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
      <direction><direction-type><dynamics><ff/></dynamics></direction-type></direction>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "dynamic.musicxml"
    midi_path = tmp_path / "dynamic-xml.mid"
    score_path.write_text(score, encoding="utf-8")

    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert result["parts"][0]["velocity"] == {"min": 52, "max": 112}
    assert info["velocity_by_channel"]["1"]["min"] == 52
    assert info["velocity_by_channel"]["1"]["max"] == 112


def test_musicxml_articulations_shape_lengths_and_velocity(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
        <notations><articulations><staccato/></articulations></notations>
      </note>
      <note>
        <pitch><step>D</step><octave>4</octave></pitch><duration>1</duration>
        <notations><articulations><accent/></articulations></notations>
      </note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "articulation.musicxml"
    midi_path = tmp_path / "articulation-xml.mid"
    score_path.write_text(score, encoding="utf-8")

    score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert info["note_length_by_channel"]["1"]["min_ticks"] == 240
    assert info["note_length_by_channel"]["1"]["max_ticks"] == 432
    assert info["velocity_by_channel"]["1"]["max"] == 104


def test_musicxml_grace_notes_become_short_notes_before_main_note(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Flute</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <note><rest/><duration>1</duration></note>
      <note><grace slash="yes"/><pitch><step>C</step><octave>5</octave></pitch><type>eighth</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>1</duration></note>
      <note><pitch><step>E</step><octave>5</octave></pitch><duration>1</duration></note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "grace.musicxml"
    midi_path = tmp_path / "grace.mid"
    score_path.write_text(score, encoding="utf-8")

    parsed = score_midi.parse_musicxml(score_path)
    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert [(note.midi, note.tick, note.duration) for note in parsed["parts"][0].notes] == [
        (72, 420, 60),
        (74, 480, 480),
        (76, 960, 480),
    ]
    assert result["note_count"] == 3
    assert result["parts"][0]["last_tick"] == 1440
    assert info["note_on_by_channel"] == {"1": 3}
    assert info["note_length_by_channel"]["1"]["min_ticks"] == 60
    assert info["note_length_by_channel"]["1"]["max_ticks"] == 480


def test_musicxml_harmony_symbols_generate_chord_accompaniment_track(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Melody</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <harmony>
        <root><root-step>C</root-step></root>
        <kind>major</kind>
      </harmony>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration></note>
      <harmony>
        <root><root-step>G</root-step></root>
        <kind>dominant</kind>
      </harmony>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>2</duration></note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "lead-sheet.musicxml"
    midi_path = tmp_path / "lead-sheet.mid"
    score_path.write_text(score, encoding="utf-8")

    parsed = score_midi.parse_musicxml(score_path)
    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert [part.name for part in parsed["parts"]] == ["Melody", "Generated Chords"]
    assert [(note.midi, note.tick, note.duration) for note in parsed["parts"][1].notes] == [
        (48, 0, 960),
        (60, 0, 960),
        (64, 0, 960),
        (67, 0, 960),
        (55, 960, 960),
        (67, 960, 960),
        (71, 960, 960),
        (74, 960, 960),
        (77, 960, 960),
    ]
    assert result["tracks"] == 3
    assert result["note_count"] == 11
    assert result["parts"][1]["name"] == "Generated Chords"
    assert info["track_names"] == ["Tempo", "Melody", "Generated Chords"]
    assert info["note_on_by_channel"] == {"1": 2, "2": 9}
    assert info["note_length_by_channel"]["2"]["min_ticks"] == 960


def test_musicxml_ties_merge_into_one_sustained_note(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Strings</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration>
        <tie type="start"/>
        <notations><tied type="start"/></notations>
      </note>
    </measure>
    <measure number="2">
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration>
        <tie type="stop"/>
        <notations><tied type="stop"/></notations>
      </note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "tied.musicxml"
    midi_path = tmp_path / "tied.mid"
    score_path.write_text(score, encoding="utf-8")

    parsed = score_midi.parse_musicxml(score_path)
    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert [(note.midi, note.tick, note.duration) for note in parsed["parts"][0].notes] == [(60, 0, 3840)]
    assert result["note_count"] == 1
    assert result["parts"][0]["last_tick"] == 3840
    assert info["note_on_by_channel"] == {"1": 1}
    assert info["note_length_by_channel"]["1"]["max_ticks"] == 3840


def test_musicxml_key_signature_writes_conductor_track(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>1</fifths><mode>minor</mode></key>
      </attributes>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "keyed.musicxml"
    midi_path = tmp_path / "keyed-xml.mid"
    score_path.write_text(score, encoding="utf-8")

    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    expected = {"name": "E minor", "fifths": 1, "mode": "minor", "tick": 0, "beat": 0.0}
    assert result["key_signature"] == expected
    assert info["key_signature"] == expected


def test_musicxml_tempo_changes_and_rehearsal_markers_write_conductor_track(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <direction>
        <direction-type><rehearsal>Intro</rehearsal></direction-type>
        <sound tempo="90"/>
      </direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration></note>
    </measure>
    <measure number="2">
      <direction>
        <direction-type><words>Chorus</words></direction-type>
        <sound tempo="140"/>
      </direction>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration></note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "tempo-markers.musicxml"
    midi_path = tmp_path / "tempo-markers.mid"
    score_path.write_text(score, encoding="utf-8")

    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    expected_tempos = [
        {"bpm": 90, "tick": 0, "beat": 0.0},
        {"bpm": 140, "tick": 1920, "beat": 4.0},
    ]
    expected_markers = [
        {"name": "Intro", "tick": 0, "beat": 0.0},
        {"name": "Chorus", "tick": 1920, "beat": 4.0},
    ]
    assert result["tempo_changes"] == expected_tempos
    assert result["markers"] == expected_markers
    assert info["tempo_changes"] == [
        {"bpm": 90.0, "tick": 0, "beat": 0.0},
        {"bpm": 140.0, "tick": 1920, "beat": 4.0},
    ]
    assert info["markers"] == expected_markers


def test_musicxml_time_signature_changes_write_conductor_track(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration></note>
    </measure>
    <measure number="2">
      <attributes>
        <time><beats>6</beats><beat-type>8</beat-type></time>
      </attributes>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>3</duration></note>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "meter.musicxml"
    midi_path = tmp_path / "meter.mid"
    score_path.write_text(score, encoding="utf-8")

    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    expected = [
        {"beats": 4, "beat_type": 4, "tick": 0, "beat": 0.0},
        {"beats": 6, "beat_type": 8, "tick": 1920, "beat": 4.0},
    ]
    assert result["time_signature_changes"] == expected
    assert info["time_signatures"] == expected


def test_musicxml_simple_repeats_expand_played_measures(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <barline location="left"><repeat direction="forward"/></barline>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
    <measure number="2">
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
      <barline location="right"><repeat direction="backward" times="3"/></barline>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "repeat.musicxml"
    midi_path = tmp_path / "repeat.mid"
    score_path.write_text(score, encoding="utf-8")

    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert result["note_count"] == 6
    assert result["parts"][0]["last_tick"] == 2880
    assert info["note_on_count"] == 6
    assert info["note_length_by_channel"]["1"]["avg_beats"] == 1.0


def test_musicxml_single_measure_repeat_symbol_replays_previous_measure(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
    <measure number="2">
      <attributes>
        <measure-style><measure-repeat type="start">1</measure-repeat></measure-style>
      </attributes>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "measure-repeat.musicxml"
    midi_path = tmp_path / "measure-repeat.mid"
    score_path.write_text(score, encoding="utf-8")

    parsed = score_midi.parse_musicxml(score_path)
    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert [(note.midi, note.tick) for note in parsed["parts"][0].notes] == [
        (60, 0),
        (62, 480),
        (64, 960),
        (65, 1440),
        (60, 1920),
        (62, 2400),
        (64, 2880),
        (65, 3360),
    ]
    assert result["note_count"] == 8
    assert result["parts"][0]["last_tick"] == 3840
    assert info["note_on_count"] == 8


def test_musicxml_two_measure_repeat_symbol_replays_previous_measures(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration></note>
    </measure>
    <measure number="2">
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration></note>
    </measure>
    <measure number="3">
      <attributes>
        <measure-style><measure-repeat type="start">2</measure-repeat></measure-style>
      </attributes>
    </measure>
    <measure number="4">
      <attributes>
        <measure-style><measure-repeat type="stop">2</measure-repeat></measure-style>
      </attributes>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "two-measure-repeat.musicxml"
    midi_path = tmp_path / "two-measure-repeat.mid"
    score_path.write_text(score, encoding="utf-8")

    parsed = score_midi.parse_musicxml(score_path)
    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert [(note.midi, note.tick) for note in parsed["parts"][0].notes] == [
        (60, 0),
        (67, 1920),
        (60, 3840),
        (67, 5760),
    ]
    assert result["note_count"] == 4
    assert result["parts"][0]["last_tick"] == 7680
    assert info["note_on_count"] == 4
    assert info["note_length_by_channel"]["1"]["avg_beats"] == 4.0


def test_musicxml_first_and_second_endings_choose_played_measures(tmp_path):
    score = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <barline location="left"><repeat direction="forward"/></barline>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
    <measure number="2">
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
    <measure number="3">
      <barline location="left"><ending number="1" type="start"/></barline>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note>
      <barline location="right"><ending number="1" type="stop"/><repeat direction="backward"/></barline>
    </measure>
    <measure number="4">
      <barline location="left"><ending number="2" type="start"/></barline>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration></note>
      <barline location="right"><ending number="2" type="stop"/></barline>
    </measure>
  </part>
</score-partwise>
"""
    score_path = tmp_path / "endings.musicxml"
    midi_path = tmp_path / "endings.mid"
    score_path.write_text(score, encoding="utf-8")

    result = score_midi.musicxml_to_midi(score_path, midi_path)
    info = core.midi_info(str(midi_path))

    assert result["note_count"] == 6
    assert result["parts"][0]["last_tick"] == 2880
    assert info["note_on_count"] == 6
    assert info["note_length_by_channel"]["1"]["avg_beats"] == 1.0


def test_make_from_score_spec_without_open_skips_garageband(tmp_path):
    result = core.make_from_score_spec(
        score_spec=SCORE_SPEC,
        output_dir=str(tmp_path / "out"),
        name="json band",
        open_in_garageband=False,
    )

    assert result["source"]["kind"] == "score_spec_json"
    assert result["midi"]["note_count"] == 11
    assert result["snapshot"] is None
    assert result["screenshot"] is None


def test_make_music_routes_score_spec_to_music(tmp_path):
    result = core.make_music(
        score_spec=SCORE_SPEC,
        output_dir=str(tmp_path / "out"),
        name="json band",
        open_in_garageband=False,
    )

    assert result["route"] == "score_spec_json"
    assert result["source"]["kind"] == "score_spec_json"
    assert result["midi"]["note_count"] == 11
    assert result["snapshot"] is None


def test_make_music_routes_musicxml_score_to_music(tmp_path):
    score_path = tmp_path / "band.musicxml"
    score_path.write_text(BAND_SCORE, encoding="utf-8")

    result = core.make_music(
        score_path=str(score_path),
        output_dir=str(tmp_path / "out"),
        name="musicxml band",
        open_in_garageband=False,
    )

    assert result["route"] == "musicxml_score"
    assert result["source"]["kind"] == "musicxml_score"
    assert result["midi"]["note_count"] == 7


def test_make_music_routes_tab_text_to_arranged_music(tmp_path):
    result = core.make_music(
        tab_text=SIMPLE_TAB,
        output_dir=str(tmp_path / "out"),
        name="tab band",
        open_in_garageband=False,
        arrange=True,
    )

    assert result["route"] == "tab_text"
    assert result["source"]["kind"] == "tab_text"
    assert result["arrange"] is True
    assert result["midi"]["tracks"] == 4


def test_make_music_requires_exactly_one_source(tmp_path):
    with pytest.raises(core.GarageBandError, match="exactly one source"):
        core.make_music(output_dir=str(tmp_path / "out"), open_in_garageband=False)

    with pytest.raises(core.GarageBandError, match="exactly one source"):
        core.make_music(
            score_spec=SCORE_SPEC,
            tab_text=SIMPLE_TAB,
            output_dir=str(tmp_path / "out"),
            open_in_garageband=False,
        )

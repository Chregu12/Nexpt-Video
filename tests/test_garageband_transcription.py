from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

import numpy as np


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO/"render"))
sys.path.insert(0, str(REPO/"tools"/"garageband-llm-bridge"))

from garageband.session import load_preset, prepare_plan  # noqa: E402
from garageband.transcribe import (  # noqa: E402
    build_garageband_preset,
    build_transcription_score,
    detect_content,
    normalize_basic_pitch_events,
    split_tonal_notes,
    transcribe_audio,
    transcribe_drum_events,
)
from garageband_bridge.score_midi import validate_score_spec  # noqa: E402


BPM = 120.0
SR = 48_000


def fixture_profile() -> dict:
    events = [
        {
            "time": .103, "family": "sub", "dominant_hz": 72.0,
            "centroid_hz": 310.0, "decay_seconds": .16, "flatness": .004,
            "strength": .92, "peak_dbfs": -2.0, "grid_offset_ms": 3.0,
        },
        {
            "time": .611, "family": "body", "dominant_hz": 820.0,
            "centroid_hz": 1900.0, "decay_seconds": .08, "flatness": .08,
            "strength": .78, "peak_dbfs": -5.0, "grid_offset_ms": 11.0,
        },
        {
            "time": 1.127, "family": "tick", "dominant_hz": 6100.0,
            "centroid_hz": 7400.0, "decay_seconds": .05, "flatness": .11,
            "strength": .55, "peak_dbfs": -9.0, "grid_offset_ms": 2.0,
        },
    ]
    return {
        "schema_version": 1,
        "source": {
            "file_name": "instrumental.m4a", "sha256": "ab"*32,
            "duration_seconds_decoded": 2.137,
        },
        "tempo": {"bpm": BPM, "downbeat_seconds": 0.0},
        "events": events,
        "arrangement": {"bars": 1},
        "generation_targets": {"events_per_bar": 3.0},
    }


def write_percussion_fixture(path: Path, bars: int = 2) -> None:
    bar_seconds = 240/BPM
    audio = np.zeros((int(round(bars*bar_seconds*SR)), 2), dtype=np.float64)
    for bar in range(bars):
        base = int(round(bar*bar_seconds*SR))
        for offset, frequency, decay, amplitude in (
            (0.0, 74.0, 12.0, .72), (.5, 780.0, 32.0, .52),
            (1.0, 74.0, 12.0, .62), (1.5, 1120.0, 38.0, .50),
        ):
            count = int(.24*SR)
            t = np.arange(count)/SR
            hit = np.sin(2*np.pi*frequency*t)*np.exp(-t*decay)*amplitude
            start = base+int(round(offset*SR))
            end = min(len(audio), start+count)
            audio[start:end, 0] += hit[:end-start]
            audio[start:end, 1] += hit[:end-start]
    pcm = (np.clip(audio, -1, 1)*32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(pcm.tobytes())


class GarageBandTranscriptionTest(unittest.TestCase):
    def test_drum_transcription_preserves_absolute_source_times(self) -> None:
        profile = fixture_profile()
        tracks, report = transcribe_drum_events(
            profile, bpm=BPM, isolated=True)
        notes = sorted(
            (note for values in tracks.values() for note in values),
            key=lambda row: row["nexpt_source_time_seconds"],
        )
        self.assertEqual(report["accepted_hits"], 3)
        self.assertEqual(
            [note["nexpt_source_time_seconds"] for note in notes],
            [event["time"] for event in profile["events"]],
        )
        for note in notes:
            self.assertAlmostEqual(
                note["start"]*(60/BPM),
                note["nexpt_source_time_seconds"], places=5)

    def test_score_is_editable_multitrack_and_exact_source_length(self) -> None:
        profile = fixture_profile()
        drums, _ = transcribe_drum_events(profile, bpm=BPM, isolated=True)
        tonal = {
            "bass": [{"start_s": .2, "end_s": .7, "midi": 40, "amplitude": .8}],
            "harmony": [
                {"start_s": .2, "end_s": 1.2, "midi": 60, "amplitude": .6},
                {"start_s": .2, "end_s": 1.2, "midi": 64, "amplitude": .6},
            ],
            "melody": [{"start_s": .2, "end_s": .8, "midi": 72, "amplitude": .7}],
        }
        score, report = build_transcription_score(
            profile, drums, tonal, bpm=BPM, duration_seconds=2.137,
            engines={"separation": {"used": "test"}, "pitch": {"used": "test"}},
            content={"used": "full"},
        )
        validation = validate_score_spec(score)
        self.assertTrue(validation["ok"])
        self.assertEqual(report["tracks"], 6)
        self.assertAlmostEqual(
            validation["duration_beats"]*(60/BPM), 2.137,
            delta=(60/BPM)/480,
        )
        anchors = [
            note for part in score["parts"] for note in part["notes"]
            if note.get("nexpt_timeline_anchor")
        ]
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["midi"], 0)

    def test_basic_pitch_variants_split_into_roles(self) -> None:
        raw = [
            (.0, .5, 43, .8, np.asarray([])),
            {"start_time_s": .5, "end_time_s": 1.0, "pitch_midi": 60,
             "amplitude": .55, "pitch_bends": [0.0, .1]},
            {"start_time": .5, "end_time": 1.0, "midi_pitch": 64,
             "confidence": .65},
            {"start": .5, "end": 1.0, "midi": 72, "velocity": 100},
        ]
        notes = normalize_basic_pitch_events(raw)
        self.assertEqual(len(notes), 4)
        self.assertTrue(any(note["has_pitch_bends"] for note in notes))
        roles = split_tonal_notes(notes)
        self.assertEqual([note["midi"] for note in roles["bass"]], [43])
        self.assertEqual([note["midi"] for note in roles["melody"]], [72])
        self.assertEqual([note["midi"] for note in roles["harmony"]], [60, 64])

    def test_percussion_content_does_not_invent_melodic_tracks(self) -> None:
        profile = fixture_profile()
        detected = detect_content(profile)
        self.assertEqual(detected["detected"], "percussion")

    def test_generated_preset_and_prepare_plan_include_ab_reference(self) -> None:
        profile = fixture_profile()
        drums, _ = transcribe_drum_events(profile, bpm=BPM, isolated=True)
        empty_tonal = {role: [] for role in ("bass", "harmony", "melody")}
        score, _ = build_transcription_score(
            profile, drums, empty_tonal, bpm=BPM, duration_seconds=2.137,
            engines={}, content={"used": "percussion"})
        preset = build_garageband_preset(score)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preset_path = root/"preset.json"
            preset_path.write_text(json.dumps(preset), encoding="utf-8")
            loaded = load_preset(preset_path)
            self.assertEqual(len(loaded["tracks"]), len(score["parts"]))
            plan = prepare_plan(
                root/"score.json", preset_path, root/"project",
                root/"reference.m4a", discard_unsaved=False)
        phases = [step["phase"] for step in plan["steps"]]
        self.assertIn("user_drag_reference", phases)
        self.assertIn("label_and_mute_reference", phases)
        self.assertNotIn("export", phases)
        self.assertIn("Original 1:1", json.dumps(plan, ensure_ascii=False))

    def test_fast_end_to_end_writes_bridge_valid_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/"percussion.wav"
            write_percussion_fixture(source)
            report = transcribe_audio(
                source,
                score_path=root/"score.json", midi_path=root/"score.mid",
                preset_path=root/"preset.json", report_path=root/"report.json",
                profile_path=root/"profile.json", work_dir=root/"work",
                bpm_hint=BPM, downbeat_hint=0.0, quality="fast",
                separation="off", pitch_engine="off", content_mode="percussion",
            )
            for name in ("score.json", "score.mid", "preset.json", "report.json", "profile.json"):
                self.assertTrue((root/name).is_file(), name)
            score = json.loads((root/"score.json").read_text(encoding="utf-8"))
            validation = validate_score_spec(score)
            self.assertTrue(validation["ok"])
            self.assertGreater(report["drums"]["accepted_hits"], 4)
            self.assertFalse(report["quality"]["one_to_one_claim"])
            self.assertEqual(report["outputs"]["reference_audio"], str(source.resolve()))


if __name__ == "__main__":
    unittest.main()

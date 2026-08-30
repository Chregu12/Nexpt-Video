from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO/"render"))
sys.path.insert(0, str(REPO/"tools"/"garageband-llm-bridge"))

from garageband.compose import build_score  # noqa: E402
from garageband.session import load_preset, render_plan  # noqa: E402
from garageband_bridge.score_midi import validate_score_spec  # noqa: E402
from music_reference import compose  # noqa: E402
from reference_arrangement import plan_reference_events  # noqa: E402


BPM = 118.0


def reference_profile() -> dict:
    role_density = {"low": 2.8, "body": 1.8, "tonal": 3.2, "detail": 1.6}
    roles = {}
    for role_index, (role, density) in enumerate(role_density.items()):
        base = [.12]*16
        for position in ((0, 6, 10, 14), (4, 12), (2, 5, 9, 13), (1, 7, 15))[role_index]:
            base[position] = .82
        roles[role] = {
            "events_per_bar": density,
            "step_probability": base,
            "phase_probability": [base[:] for _ in range(4)],
            "phase_strength": [[.48+.08*((position+phase) % 4)
                                for position in range(16)] for phase in range(4)],
            "phase_offset_ms": [[(-7.0 if position % 2 == 0 else 11.0)
                                 for position in range(16)] for _ in range(4)],
            "phase_spread_ms": [[4.0]*16 for _ in range(4)],
        }
    return {
        "schema_version": 1,
        "source": {"file_name": "reference.mp3", "sha256": "ab"*32},
        "tempo": {"bpm": BPM},
        "mix": {"side_mid_db": -14.0, "bands": {}},
        "rhythm_model": {
            "roles": roles,
            "events_per_bar": sum(role_density.values()),
            "four_bar_repeat_jaccard": .42,
            "tonal_language": {
                "root_midi": 60,
                "intervals_semitones": [0, 3, 5, 7],
                "pitch_ratios": [1.0, 1.189207, 1.33484, 1.498307],
            },
        },
    }


class SilentFactory:
    role_family = {role: role for role in ("low", "body", "tonal", "detail")}

    @staticmethod
    def render(role: str, variant: int, velocity: float,
               pitch_ratio: float = 1.0) -> np.ndarray:
        return np.zeros(32, dtype=np.float32)

    @staticmethod
    def describe() -> dict:
        return {"engine": "test-silence"}


class GarageBandPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = reference_profile()

    def test_score_is_deterministic_multitrack_and_bridge_valid(self) -> None:
        seconds = 8*240/BPM
        first, report = build_score(
            self.profile, total_seconds=seconds, bars=8, bpm=BPM, seed=17)
        second, _ = build_score(
            self.profile, total_seconds=seconds, bars=8, bpm=BPM, seed=17)
        self.assertEqual(first, second)
        self.assertEqual(report["tracks"], 4)
        self.assertGreater(report["events"], 25)
        self.assertEqual([part["channel"] for part in first["parts"]], [1, 2, 3, 4])

        validation = validate_score_spec(first)
        self.assertTrue(validation["ok"])
        self.assertEqual([part["channel"] for part in validation["parts"]], [1, 2, 3, 4])
        self.assertAlmostEqual(validation["duration_beats"], 32.0, places=3)

        sounding = [note for part in first["parts"] for note in part["notes"]
                    if not note.get("nexpt_timeline_anchor")]
        self.assertTrue(any(abs(note["start"]*4-round(note["start"]*4)) > .001
                            for note in sounding))
        anchors = [note for part in first["parts"] for note in part["notes"]
                   if note.get("nexpt_timeline_anchor")]
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["midi"], 0)
        self.assertEqual(anchors[0]["velocity"], 1)

    def test_local_preview_and_garageband_share_the_exact_event_plan(self) -> None:
        seconds = 4*240/BPM
        plan = plan_reference_events(
            self.profile, seconds, 4, BPM, cues=[], seed=23)
        _, _, events, context = compose(
            self.profile, seconds, 4, BPM, cues=[], seed=23,
            tail=.05, sound_factory=SilentFactory())
        self.assertEqual(events, [dict(event) for event in plan.events])
        self.assertEqual(context["seed"], plan.seed)

    def test_session_dry_run_is_complete_and_non_mutating(self) -> None:
        preset_path = REPO/"garageband"/"presets"/"recorded-kit.json"
        preset = load_preset(preset_path)
        self.assertEqual(len(preset["tracks"]), 4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            score = root/"score.json"
            score.write_text(json.dumps({"parts": []}), encoding="utf-8")
            plan = render_plan(
                score, preset_path, root/"session", root/"music.wav",
                discard_unsaved=False, overwrite=False,
            )
        phases = [step["phase"] for step in plan["steps"]]
        self.assertEqual(phases.count("select_patch"), 4)
        self.assertEqual(phases[0:3], ["validate", "open", "inspect_tracks"])
        self.assertEqual(phases[-2:], ["verify", "export"])
        self.assertFalse((REPO/"garageband"/"arrangements"/"test").exists())


if __name__ == "__main__":
    unittest.main()

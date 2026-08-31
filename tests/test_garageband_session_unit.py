from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from garageband import session  # noqa: E402


def valid_preset() -> dict:
    return {
        "schema_version": 1,
        "name": "Unit preset",
        "tracks": [
            {
                "part": "Transcribed Piano",
                "fallback_index": 1,
                "patch": {
                    "query": "Piano",
                    "preferred": ["Steinway Grand Piano"],
                    "allow_first": False,
                },
                "volume": "0.7",
                "pan": "0",
            },
            {
                "part": "Transcribed Violin",
                "fallback_index": 2,
                "patch": {
                    "query": "Violin",
                    "preferred": ["Solo Violin"],
                    "allow_first": False,
                },
            },
        ],
        "export": {"format": "WAVE", "timeout_seconds": 90},
    }


class GarageBandSessionUnitTest(unittest.TestCase):
    def write_payload(self, root: Path, payload: object) -> Path:
        path = root/"preset.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_load_preset_accepts_valid_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            loaded = session.load_preset(
                self.write_payload(Path(directory), valid_preset()))
        self.assertEqual(loaded["name"], "Unit preset")
        self.assertEqual(len(loaded["tracks"]), 2)

    def test_load_preset_rejects_missing_and_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(session.SessionError, "does not exist"):
                session.load_preset(root/"missing.json")
            invalid = root/"invalid.json"
            invalid.write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(session.SessionError, "Invalid preset JSON"):
                session.load_preset(invalid)

    def test_load_preset_rejects_invalid_top_level_shapes(self) -> None:
        cases = (
            ([], "JSON object"),
            ({"schema_version": 2, "tracks": [{}]}, "schema_version"),
            ({"schema_version": 1}, "non-empty tracks"),
            ({"schema_version": 1, "tracks": []}, "non-empty tracks"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for payload, message in cases:
                with self.subTest(payload=payload):
                    path = self.write_payload(root, payload)
                    with self.assertRaisesRegex(session.SessionError, message):
                        session.load_preset(path)

    def test_load_preset_rejects_track_contract_violations(self) -> None:
        cases = (
            (["not-an-object"], "track 1 must be an object"),
            ([
                valid_preset()["tracks"][0],
                valid_preset()["tracks"][0],
            ], "unique part"),
            ([{"part": "Piano", "patch": {"preferred": []}}], "patch.query"),
            ([{
                "part": "Piano",
                "patch": {"query": "Piano", "preferred": "Steinway"},
            }], "patch.preferred must be a list"),
            ([{
                "part": "Piano",
                "patch": {"query": "Piano", "preferred": [123]},
            }], "non-empty strings"),
            ([{
                "part": "Piano",
                "patch": {"query": "Piano", "preferred": []},
            }], "preferred patch or allow_first"),
            ([{
                "part": "Piano",
                "patch": {
                    "query": "Piano", "preferred": [], "allow_first": "false",
                },
            }], "allow_first must be Boolean"),
            ([{
                "part": "Piano", "fallback_index": 0,
                "patch": {"query": "Piano", "preferred": ["Piano"]},
            }], "positive integer"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for tracks, message in cases:
                with self.subTest(message=message):
                    path = self.write_payload(root, {
                        "schema_version": 1, "tracks": tracks,
                    })
                    with self.assertRaisesRegex(session.SessionError, message):
                        session.load_preset(path)

    def test_track_index_prefers_unique_name_then_explicit_fallback(self) -> None:
        visible = [
            {"index": 3, "name": "Transcribed Grand Piano"},
            {"index": 7, "name": "Transcribed Violin"},
        ]
        self.assertEqual(session._track_index(
            {"part": "grand piano", "fallback_index": 7}, visible), 3)
        self.assertEqual(session._track_index(
            {"part": "Unknown", "fallback_index": 7}, visible), 7)

        duplicates = [
            {"index": 1, "name": "Transcribed Piano Left"},
            {"index": 2, "name": "Transcribed Piano Right"},
        ]
        self.assertEqual(session._track_index(
            {"part": "Transcribed Piano", "fallback_index": 2}, duplicates), 2)

    def test_track_index_reports_visible_tracks_when_resolution_fails(self) -> None:
        visible = [{"index": 4, "name": "Bass"}, {"index": 6, "name": "Violin"}]
        with self.assertRaisesRegex(session.SessionError, "4: Bass, 6: Violin"):
            session._track_index(
                {"part": "Piano", "fallback_index": 2}, visible)

    def test_choose_patch_prefers_case_insensitive_exact_then_unique_partial(self) -> None:
        results = [
            {"index": 1, "name": "Studio Solo Violin"},
            {"index": 2, "name": "STEINWAY GRAND PIANO"},
        ]
        exact = session._choose_patch({
            "preferred": ["Steinway Grand Piano"], "allow_first": False,
        }, results)
        self.assertEqual(exact["index"], 2)
        partial = session._choose_patch({
            "preferred": ["Solo Violin"], "allow_first": False,
        }, results)
        self.assertEqual(partial["index"], 1)

    def test_choose_patch_never_guesses_an_ambiguous_result_without_opt_in(self) -> None:
        results = [
            {"index": 1, "name": "Solo Violin Bright"},
            {"index": 2, "name": "Solo Violin Warm"},
        ]
        patch_spec = {"preferred": ["Solo Violin"], "allow_first": False}
        with self.assertRaisesRegex(session.SessionError, "No preferred"):
            session._choose_patch(patch_spec, results)
        chosen = session._choose_patch(
            {**patch_spec, "allow_first": True}, results)
        self.assertEqual(chosen["index"], 1)

    def test_bridge_call_normalizes_success_and_failures(self) -> None:
        success = SimpleNamespace(
            returncode=0, stdout='{"ok": true, "data": {"value": 7}}', stderr="")
        with patch.object(session.subprocess, "run", return_value=success):
            self.assertEqual(session.bridge_call("status"), {"value": 7})

        rejected = SimpleNamespace(
            returncode=1, stdout="", stderr='{"ok": false, "error": "denied"}')
        with patch.object(session.subprocess, "run", return_value=rejected):
            with self.assertRaisesRegex(session.SessionError, "denied"):
                session.bridge_call("status")

        malformed = SimpleNamespace(returncode=0, stdout="not-json", stderr="")
        with patch.object(session.subprocess, "run", return_value=malformed):
            with self.assertRaisesRegex(session.SessionError, "not-json"):
                session.bridge_call("status")

    def test_render_plan_carries_explicit_destructive_flags_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preset = self.write_payload(root, valid_preset())
            plan = session.render_plan(
                root/"score.json", preset, root/"project", root/"music.wav",
                discard_unsaved=True, overwrite=True,
            )
        open_step = next(step for step in plan["steps"] if step["phase"] == "open")
        export_step = next(step for step in plan["steps"] if step["phase"] == "export")
        self.assertIn("--discard-unsaved", open_step["command"])
        self.assertIn("--overwrite", export_step["command"])
        self.assertEqual(
            [step["phase"] for step in plan["steps"]].count("select_patch"), 2)


if __name__ == "__main__":
    unittest.main()

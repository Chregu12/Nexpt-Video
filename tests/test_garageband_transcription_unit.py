from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO/"render"))
sys.path.insert(0, str(REPO/"tools"/"garageband-llm-bridge"))

from garageband.instrument_catalog import (  # noqa: E402
    INSTRUMENT_CATALOG as BASE_CATALOG,
    build_patch_inventory,
    load_patch_inventory,
    patch_for_instrument,
)
from garageband.transcribe import (  # noqa: E402
    INSTRUMENT_CATALOG,
    assign_notes_to_instruments,
    canonical_instrument,
    load_instrument_map,
    transcribe_audio,
    validate_instrument_map,
)


class GarageBandTranscriptionUnitTest(unittest.TestCase):
    def test_load_patch_inventory_rejects_missing_invalid_and_wrong_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "existiert nicht"):
                load_patch_inventory(root/"missing.json")

            invalid = root/"invalid.json"
            invalid.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Ungueltiges"):
                load_patch_inventory(invalid)

            wrong_schema = root/"schema.json"
            wrong_schema.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema_version 1"):
                load_patch_inventory(wrong_schema)

    def test_load_patch_inventory_rejects_malformed_patch_maps(self) -> None:
        malformed = (
            ({"schema_version": 1, "by_instrument": []}, "by_instrument"),
            ({"schema_version": 1, "by_family": []}, "by_family"),
            ({
                "schema_version": 1,
                "by_instrument": {
                    "violin": {"query": "Violin", "preferred": "Solo Violin"},
                },
            }, "preferred"),
            ({
                "schema_version": 1,
                "by_family": {
                    "solo_strings": {"query": "", "preferred": ["Solo Violin"]},
                },
            }, "query"),
            ({
                "schema_version": 1,
                "by_instrument": {
                    "unknown": {"query": "X", "preferred": ["X"]},
                },
            }, "unbekannten Schluessel"),
            ({
                "schema_version": 1,
                "by_family": {
                    "unknown": {"query": "X", "preferred": ["X"]},
                },
            }, "unbekannten Schluessel"),
            ({
                "schema_version": 1,
                "by_instrument": {
                    "violin": {
                        "query": "Violin", "preferred": ["Solo Violin"],
                        "allow_first": "false",
                    },
                },
            }, "allow_first"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"inventory.json"
            for payload, message in malformed:
                with self.subTest(message=message):
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        load_patch_inventory(path)

    def test_loaded_inventory_is_annotated_without_mutating_disk_payload(self) -> None:
        payload = {
            "schema_version": 1,
            "by_instrument": {
                "violin": {
                    "query": "Violin", "preferred": ["Solo Violin"],
                    "allow_first": False,
                },
            },
            "by_family": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"inventory.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_patch_inventory(path)
            self.assertEqual(loaded["source_path"], str(path.resolve()))
            self.assertNotIn(
                "source_path", json.loads(path.read_text(encoding="utf-8")))

    def test_patch_selection_returns_defensive_copies_for_every_fallback(self) -> None:
        inventory = {
            "by_instrument": {
                "violin": {
                    "query": "Violin", "preferred": ["Solo Violin"],
                    "allow_first": False,
                },
            },
            "by_family": {
                "piano": {
                    "query": "Piano", "preferred": ["Steinway Grand Piano"],
                    "allow_first": False,
                },
            },
        }
        exact, exact_source = patch_for_instrument("violin", inventory)
        family, family_source = patch_for_instrument("honky_tonk_piano", inventory)
        built_in, built_in_source = patch_for_instrument("flute", inventory)
        self.assertEqual(exact_source, "installed-exact")
        self.assertEqual(family_source, "installed-family-fallback")
        self.assertEqual(built_in_source, "built-in-catalog-no-installed-match")

        exact["preferred"].append("Mutation")
        family["preferred"].append("Mutation")
        built_in["preferred"].append("Mutation")
        self.assertEqual(inventory["by_instrument"]["violin"]["preferred"],
                         ["Solo Violin"])
        self.assertEqual(inventory["by_family"]["piano"]["preferred"],
                         ["Steinway Grand Piano"])
        self.assertNotIn("Mutation", BASE_CATALOG["flute"]["patch"]["preferred"])

    def test_inventory_builder_deduplicates_labels_and_preserves_query_errors(self) -> None:
        inventory = build_patch_inventory([
            {
                "query": "Piano",
                "results": [
                    {"name": "Steinway Grand Piano"},
                    {"name": "Steinway Grand Piano"},
                    {"name": "Library"},
                ],
                "error": "partial accessibility snapshot",
            },
            {
                "query": "",
                "results": [{"name": "Completely Unknown Creative Patch"}],
            },
        ])
        self.assertEqual(inventory["searches"][0]["count"], 1)
        self.assertEqual(
            inventory["searches"][0]["error"], "partial accessibility snapshot")
        self.assertEqual(
            inventory["by_instrument"]["piano"]["preferred"],
            ["Steinway Grand Piano"])
        unknown = next(
            row for row in inventory["patches"]
            if row["name"] == "Completely Unknown Creative Patch")
        self.assertIsNone(unknown["instrument"])

    def test_instrument_map_normalizes_aliases_and_rejects_invalid_contracts(self) -> None:
        normalized = validate_instrument_map({
            "stems": {" Other ": "Violine"},
            "roles": {"MELODY": "Flöte"},
            "default": "Klavier",
        })
        self.assertEqual(normalized["stems"], {"other": "violin"})
        self.assertEqual(normalized["roles"], {"melody": "flute"})
        self.assertEqual(normalized["default"], "piano")

        invalid = (
            (["not-an-object"], "JSON-Objekt"),
            ({"unknown": {}}, "Unbekannte"),
            ({"stems": []}, "stems muss ein Objekt"),
            ({"roles": {"solo": "violin"}}, "Unbekannte Notenrolle"),
            ({"stems": {" ": "violin"}}, "leeren Schluessel"),
            ({"default": "kazoo-from-mars"}, "Unbekanntes Instrument"),
        )
        for payload, message in invalid:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_instrument_map(payload)

    def test_load_instrument_map_reports_file_and_json_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "existiert nicht"):
                load_instrument_map(root/"missing.json")
            invalid = root/"invalid.json"
            invalid.write_text("[] trailing", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Ungueltige"):
                load_instrument_map(invalid)

    def test_channel_limit_merge_is_deterministic_and_keeps_all_notes(self) -> None:
        instruments = [
            "piano", "bright_acoustic_piano", "electric_grand_piano",
            "honky_tonk_piano", "electric_piano", "electric_piano_2",
            "harpsichord", "clavinet", "celesta", "glockenspiel",
            "music_box", "vibraphone",
        ]
        melody = []
        stems = {}
        for index, instrument in enumerate(instruments):
            stem = f"stem-{index}"
            stems[stem] = instrument
            melody.append({
                "start_s": index*.1, "end_s": index*.1+.08,
                "midi": 60+index % 12, "amplitude": .7,
                "source_stem": stem,
            })
        tonal = {"bass": [], "harmony": [], "melody": melody}
        first_tracks, first_report = assign_notes_to_instruments(
            tonal, overrides={"stems": stems})
        second_tracks, second_report = assign_notes_to_instruments(
            tonal, overrides={"stems": stems})
        self.assertEqual(first_tracks, second_tracks)
        self.assertEqual(first_report, second_report)
        self.assertEqual(len(first_tracks), 11)
        self.assertEqual(sum(map(len, first_tracks.values())), len(instruments))
        self.assertEqual(len(first_tracks["piano"]), 2)
        merged = [
            note for notes in first_tracks.values() for note in notes
            if note["nexpt_instrument_source"] == "midi-channel-limit-merge"
        ]
        self.assertEqual(len(merged), 1)
        self.assertEqual(first_report["uncertain_notes"], 1)

    def test_canonical_instrument_keeps_clean_and_overdriven_guitars_distinct(self) -> None:
        self.assertEqual(canonical_instrument("E-Gitarre"), "electric_guitar")
        self.assertEqual(
            canonical_instrument("Electric Guitar Clean"), "electric_guitar")
        self.assertEqual(canonical_instrument("Overdriven Guitar"), "overdriven_guitar")
        self.assertEqual(INSTRUMENT_CATALOG["electric_guitar"]["program"], 27)
        self.assertEqual(INSTRUMENT_CATALOG["overdriven_guitar"]["program"], 29)

    def test_transcribe_audio_rejects_invalid_modes_before_writing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/"source.wav"
            source.write_bytes(b"fixture")
            common = {
                "score_path": root/"score.json",
                "midi_path": root/"score.mid",
                "preset_path": root/"preset.json",
                "report_path": root/"report.json",
                "profile_path": root/"profile.json",
                "work_dir": root/"work",
            }
            with self.assertRaisesRegex(ValueError, "Unknown quality"):
                transcribe_audio(source, quality="ultra", **common)
            with self.assertRaisesRegex(ValueError, "Unknown content mode"):
                transcribe_audio(source, content_mode="voice", **common)
            self.assertFalse(any(path.exists() for path in common.values()))


if __name__ == "__main__":
    unittest.main()

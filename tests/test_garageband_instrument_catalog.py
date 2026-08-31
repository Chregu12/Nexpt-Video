from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO/"render"))
sys.path.insert(0, str(REPO/"tools"/"garageband-llm-bridge"))

from garageband.instrument_catalog import (  # noqa: E402
    FAMILY_DEFINITIONS,
    INSTRUMENT_CATALOG,
    build_patch_inventory,
    catalog_search_queries,
    classification_keys,
    patch_for_instrument,
)
from garageband import session as garageband_session  # noqa: E402
from garageband.transcribe import (  # noqa: E402
    _hierarchical_instrument_scores,
    assign_notes_to_instruments,
    build_garageband_preset,
    canonical_instrument,
)


class GarageBandInstrumentCatalogTest(unittest.TestCase):
    def test_catalog_covers_every_general_midi_program_and_extensions(self) -> None:
        programs = {int(config["program"]) for config in INSTRUMENT_CATALOG.values()}
        self.assertEqual(programs, set(range(128)))
        self.assertGreaterEqual(len(INSTRUMENT_CATALOG), 140)
        self.assertIn("erhu", INSTRUMENT_CATALOG)
        self.assertIn("guzheng", INSTRUMENT_CATALOG)
        self.assertIn("synth_texture", INSTRUMENT_CATALOG)
        self.assertEqual(INSTRUMENT_CATALOG["electric_guitar"]["gm_name"],
                         "Electric Guitar Clean")
        self.assertEqual(INSTRUMENT_CATALOG["electric_guitar"]["program"], 27)
        self.assertIn("overdriven_guitar", INSTRUMENT_CATALOG)
        self.assertFalse(INSTRUMENT_CATALOG["gunshot"]["classify"])
        self.assertNotIn("gunshot", classification_keys())

    def test_display_names_and_german_aliases_are_accepted(self) -> None:
        self.assertEqual(canonical_instrument("Bright Acoustic Piano"), "bright_acoustic_piano")
        self.assertEqual(canonical_instrument("Waldhorn"), "french_horn")
        self.assertEqual(canonical_instrument("Kontrabass"), "contrabass")

    def test_hierarchical_family_probability_corrects_flat_ambiguity(self) -> None:
        scores = _hierarchical_instrument_scores(
            ["piano", "solo_strings"], [.90, .10],
            ["piano", "violin"], [.40, .60],
        )
        self.assertGreater(scores["piano"], scores["violin"])
        self.assertAlmostEqual(sum(scores.values()), 1.0)

    def test_confident_family_survives_ambiguous_fine_variants(self) -> None:
        string_variants = (
            "violin", "viola", "cello", "contrabass", "tremolo_strings",
            "pizzicato_strings", "harp",
        )
        tonal = {
            "bass": [], "harmony": [],
            "melody": [{
                "start_s": 0.0, "end_s": 1.0, "midi": 76,
                "amplitude": .8, "source_stem": "other",
            }],
        }
        segments = [{
            "source_stem": "other", "start_s": 0.0, "end_s": 8.0,
            "scores": {key: .05 for key in string_variants},
            "family_scores": {"solo_strings": .80, "piano": .10},
        }]
        tracks, report = assign_notes_to_instruments(tonal, segments)
        note = next(iter(tracks.values()))[0]
        self.assertEqual(INSTRUMENT_CATALOG[note["nexpt_instrument"]]["family"], "solo_strings")
        self.assertEqual(note["nexpt_instrument_source"], "clap-family-fallback")
        self.assertEqual(report["uncertain_notes"], 1)

    def test_inventory_maps_real_patch_names_and_preserves_family_fallback(self) -> None:
        inventory = build_patch_inventory([
            {
                "query": "",
                "results": [
                    {"name": "Clean Stack"}, {"name": "Completely Unrelated Name"},
                    {"name": "Library"},
                ],
            },
            {
                "query": "Piano",
                "results": [
                    {"name": "Steinway Grand Piano"},
                    {"name": "Bright Acoustic Piano"},
                ],
            },
            {
                "query": "Violin",
                "results": [{"name": "Solo Violin"}],
            },
        ], garageband={"installed": True})
        self.assertEqual(inventory["taxonomy"]["general_midi_programs"], 128)
        self.assertIn("Steinway Grand Piano", inventory["by_instrument"]["piano"]["preferred"])
        self.assertIn("Solo Violin", inventory["by_instrument"]["violin"]["preferred"])
        self.assertIn("Clean Stack", inventory["by_family"]["electric_guitar"]["preferred"])
        unrelated = next(
            row for row in inventory["patches"] if row["name"] == "Completely Unrelated Name")
        self.assertIsNone(unrelated["instrument"])
        patch, source = patch_for_instrument("honky_tonk_piano", inventory)
        self.assertEqual(source, "installed-family-fallback")
        self.assertIn("Steinway Grand Piano", patch["preferred"])

    def test_generated_preset_uses_installed_patch_inventory(self) -> None:
        inventory = build_patch_inventory([{
            "query": "Piano", "results": [{"name": "Steinway Grand Piano"}],
        }])
        score = {"parts": [{
            "name": "Transcribed Piano", "nexpt_role": "harmony",
            "nexpt_instrument": "piano", "nexpt_instrument_confidence": .8,
            "mix": {"volume": .7, "pan": 0}, "notes": [],
        }]}
        preset = build_garageband_preset(score, inventory)
        self.assertEqual(preset["instrument_taxonomy"]["general_midi_programs"], 128)
        self.assertEqual(preset["tracks"][0]["patch_source"], "installed-exact")
        self.assertEqual(
            preset["tracks"][0]["patch"]["preferred"], ["Steinway Grand Piano"])

    def test_inventory_queries_cover_every_family(self) -> None:
        queries = catalog_search_queries()
        self.assertEqual(queries[0], "")
        self.assertIn("Piano", queries)
        self.assertIn("Bass", queries)
        self.assertIn("World", queries)
        self.assertIn("Synthesizer", queries)
        covered_families = {
            config["family"] for config in INSTRUMENT_CATALOG.values()
            if config.get("source_type") == "software_instrument"
        }
        self.assertGreaterEqual(len(covered_families), len(FAMILY_DEFINITIONS)-1)

    def test_mac_inventory_command_writes_reusable_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"installed.json"
            args = SimpleNamespace(
                track_index=1, limit=100, output=output, query=["Piano"],
            )

            def fake_bridge(*command: str) -> dict:
                if command[0] == "status":
                    return {"installed": True, "version": "test"}
                if command[0] == "library-search":
                    return {"results": [{"name": "Steinway Grand Piano"}]}
                return {"selected": 1}

            with patch.object(garageband_session.platform, "system", return_value="Darwin"), \
                    patch.object(garageband_session, "bridge_call", side_effect=fake_bridge):
                inventory = garageband_session.run_inventory(args)
            self.assertTrue(output.is_file())
            self.assertEqual(inventory["garageband"]["version"], "test")
            self.assertIn("piano", inventory["by_instrument"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import numpy as np


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO/"render"))
sys.path.insert(0, str(REPO/"tools"/"garageband-llm-bridge"))

from garageband import session as garageband_session  # noqa: E402
from garageband import transcribe as garageband_transcribe  # noqa: E402
from garageband.instrument_catalog import (  # noqa: E402
    build_patch_inventory,
    load_patch_inventory,
)
from garageband_bridge.score_midi import validate_score_spec  # noqa: E402


BPM = 120.0
SR = 48_000


def write_percussion_fixture(path: Path, bars: int = 2) -> None:
    """Write a deterministic stereo fixture that exercises real DSP analysis."""
    bar_seconds = 240/BPM
    audio = np.zeros((int(round(bars*bar_seconds*SR)), 2), dtype=np.float64)
    for bar in range(bars):
        base = int(round(bar*bar_seconds*SR))
        for offset, frequency, decay, amplitude in (
            (0.0, 72.0, 12.0, .74),
            (.5, 760.0, 32.0, .54),
            (1.0, 72.0, 12.0, .64),
            (1.5, 1220.0, 42.0, .48),
        ):
            count = int(.24*SR)
            time = np.arange(count)/SR
            hit = np.sin(2*np.pi*frequency*time)*np.exp(-time*decay)*amplitude
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


def write_silent_fixture(path: Path, seconds: float = 1.0) -> None:
    pcm = np.zeros((int(round(seconds*SR)), 2), dtype="<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(pcm.tobytes())


def tonal_profile(source: Path) -> dict:
    return {
        "schema_version": 1,
        "source": {
            "file_name": source.name,
            "sha256": "cd"*32,
            "duration_seconds": 4.0,
            "duration_seconds_decoded": 4.0,
        },
        "tempo": {"bpm": BPM, "downbeat_seconds": 0.0},
        "events": [],
        "arrangement": {"bars": 2},
        "generation_targets": {"events_per_bar": 0.0},
    }


def single_track_preset(path: Path, *, preferred: str = "Solo Violin") -> None:
    path.write_text(json.dumps({
        "schema_version": 1,
        "name": "E2E preset",
        "tracks": [{
            "part": "Transcribed Violin",
            "fallback_index": 1,
            "patch": {
                "query": "Violin",
                "preferred": [preferred],
                "allow_first": False,
            },
            "volume": "0.7",
            "pan": "0",
        }],
        "export": {"format": "WAVE", "timeout_seconds": 30},
    }, indent=2), encoding="utf-8")


class GarageBandEndToEndTest(unittest.TestCase):
    maxDiff = None

    def test_cli_audio_to_score_and_prepare_plan(self) -> None:
        """Exercise both public CLIs across process and file boundaries."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/"reference-percussion.wav"
            write_percussion_fixture(source)
            outputs = {
                "score": root/"score.json",
                "midi": root/"score.mid",
                "preset": root/"preset.json",
                "report": root/"report.json",
                "profile": root/"profile.json",
            }
            transcribe = subprocess.run([
                sys.executable, str(REPO/"garageband"/"transcribe.py"),
                str(source), "--quality", "fast", "--content", "percussion",
                "--separate", "off", "--pitch-engine", "off",
                "--instrument-engine", "off", "--bpm", str(BPM),
                "--downbeat", "0", "--output", str(outputs["score"]),
                "--midi", str(outputs["midi"]),
                "--preset-output", str(outputs["preset"]),
                "--report-output", str(outputs["report"]),
                "--profile-output", str(outputs["profile"]),
                "--work-dir", str(root/"work"),
            ], cwd=REPO, capture_output=True, text=True, timeout=60)
            self.assertEqual(
                transcribe.returncode, 0,
                f"stdout:\n{transcribe.stdout}\nstderr:\n{transcribe.stderr}")
            for name, output in outputs.items():
                self.assertTrue(output.is_file(), name)
                self.assertGreater(output.stat().st_size, 0, name)

            score = json.loads(outputs["score"].read_text(encoding="utf-8"))
            preset = json.loads(outputs["preset"].read_text(encoding="utf-8"))
            report = json.loads(outputs["report"].read_text(encoding="utf-8"))
            self.assertTrue(validate_score_spec(score)["ok"])
            self.assertEqual(report["content"]["used"], "percussion")
            self.assertGreater(report["drums"]["accepted_hits"], 4)
            self.assertEqual(len(preset["tracks"]), len(score["parts"]))
            self.assertTrue(all(
                row["patch_source"] == "built-in-drum-catalog"
                for row in preset["tracks"]
            ))
            self.assertEqual(outputs["midi"].read_bytes()[:4], b"MThd")

            bridge = REPO/"tools"/"garageband-llm-bridge"/"garageband_cli.py"
            bridge_validation = subprocess.run([
                sys.executable, str(bridge), "--pretty", "score-spec-validate",
                "--file", str(outputs["score"]),
            ], cwd=REPO, capture_output=True, text=True, timeout=30)
            self.assertEqual(
                bridge_validation.returncode, 0,
                f"stdout:\n{bridge_validation.stdout}\n"
                f"stderr:\n{bridge_validation.stderr}")
            bridge_score = json.loads(bridge_validation.stdout)["data"]
            self.assertTrue(bridge_score["ok"])
            self.assertEqual(bridge_score["note_count"], report["score"]["score_notes"])

            midi_info = subprocess.run([
                sys.executable, str(bridge), "--pretty", "midi-info",
                str(outputs["midi"]),
            ], cwd=REPO, capture_output=True, text=True, timeout=30)
            self.assertEqual(
                midi_info.returncode, 0,
                f"stdout:\n{midi_info.stdout}\nstderr:\n{midi_info.stderr}")
            midi_data = json.loads(midi_info.stdout)["data"]
            self.assertEqual(midi_data["header"], "MThd")
            self.assertGreater(midi_data["note_on_count"], 4)

            prepare = subprocess.run([
                sys.executable, str(REPO/"garageband"/"session.py"),
                "prepare", "--score", str(outputs["score"]),
                "--preset", str(outputs["preset"]),
                "--reference-audio", str(source),
                "--output-dir", str(root/"garageband-project"), "--dry-run",
            ], cwd=REPO, capture_output=True, text=True, timeout=30)
            self.assertEqual(
                prepare.returncode, 0,
                f"stdout:\n{prepare.stdout}\nstderr:\n{prepare.stderr}")
            plan = json.loads(prepare.stdout)
            phases = [step["phase"] for step in plan["steps"]]
            self.assertEqual(plan["reference_audio"], str(source.resolve()))
            self.assertEqual(phases[:3], ["validate", "open", "inspect_tracks"])
            self.assertEqual(phases.count("select_patch"), len(preset["tracks"]))
            self.assertIn("user_drag_reference", phases)
            self.assertIn("label_and_mute_reference", phases)
            self.assertNotIn("export", phases)

    def test_detected_music_uses_inventory_and_applies_exact_patches(self) -> None:
        """Cover analysis orchestration through simulated GarageBand patching."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/"instrumental.wav"
            write_silent_fixture(source)
            inventory_path = root/"installed-patches.json"
            inventory_path.write_text(json.dumps(build_patch_inventory([
                {
                    "query": "Piano",
                    "results": [{"name": "Steinway Grand Piano"}],
                },
                {
                    "query": "Violin",
                    "results": [{"name": "Solo Violin"}],
                },
            ], garageband={"installed": True, "version": "E2E"}), indent=2),
                encoding="utf-8")
            inventory = load_patch_inventory(inventory_path)

            tonal_roles = {
                "bass": [],
                "harmony": [
                    {
                        "start_s": .25, "end_s": 1.5, "midi": 60,
                        "amplitude": .72, "source_stem": "piano",
                        "instrument_hint": "piano",
                    },
                    {
                        "start_s": .25, "end_s": 1.5, "midi": 64,
                        "amplitude": .69, "source_stem": "piano",
                        "instrument_hint": "piano",
                    },
                ],
                "melody": [{
                    "start_s": .5, "end_s": 2.25, "midi": 76,
                    "amplitude": .81, "source_stem": "other",
                }],
            }
            instrument_segments = [
                {
                    "source_stem": "piano", "start_s": 0.0, "end_s": 4.0,
                    "scores": {
                        "honky_tonk_piano": .72,
                        "piano": .20,
                        "electric_piano": .05,
                    },
                    "family_scores": {"piano": .93},
                },
                {
                    "source_stem": "other", "start_s": 0.0, "end_s": 4.0,
                    "scores": {"violin": .78, "flute": .08, "synth_lead": .04},
                    "family_scores": {"solo_strings": .84, "pipes": .08},
                },
            ]
            pitch_report = {
                "requested": "basic-pitch", "used": "basic-pitch",
                "note_events": 3,
                "notes_by_role": {"bass": 0, "harmony": 2, "melody": 1},
                "mean_note_confidence": .82,
                "pitch_bend_events_flattened": 0,
                "details": {},
            }
            classification_report = {
                "requested": "clap", "used": "clap", "segments": 2,
                "taxonomy": {"families": 2, "classifiable_instruments": 129},
            }
            outputs = {
                "score": root/"score.json",
                "midi": root/"score.mid",
                "preset": root/"preset.json",
                "report": root/"report.json",
                "profile": root/"profile.json",
            }
            with patch.object(
                    garageband_transcribe, "analyze_reference",
                    side_effect=lambda *_args, **_kwargs: deepcopy(tonal_profile(source))), \
                    patch.object(
                        garageband_transcribe, "separate_stems",
                        return_value=(
                            {"piano": source, "other": source},
                            {"requested": "demucs", "used": "demucs", "stems": 2},
                        )), \
                    patch.object(
                        garageband_transcribe, "transcribe_tonal_events",
                        return_value=(deepcopy(tonal_roles), pitch_report)), \
                    patch.object(
                        garageband_transcribe, "classify_instrument_segments",
                        return_value=(deepcopy(instrument_segments), classification_report)):
                report = garageband_transcribe.transcribe_audio(
                    source,
                    score_path=outputs["score"], midi_path=outputs["midi"],
                    preset_path=outputs["preset"], report_path=outputs["report"],
                    profile_path=outputs["profile"], work_dir=root/"work",
                    bpm_hint=BPM, downbeat_hint=0.0, quality="high",
                    separation="demucs", pitch_engine="basic-pitch",
                    instrument_engine="clap", garageband_inventory=inventory,
                    content_mode="full",
                )

            score = json.loads(outputs["score"].read_text(encoding="utf-8"))
            preset = json.loads(outputs["preset"].read_text(encoding="utf-8"))
            self.assertTrue(validate_score_spec(score)["ok"])
            melodic_parts = {
                row["nexpt_instrument"]: row for row in score["parts"]
                if row.get("nexpt_instrument")
            }
            self.assertEqual(set(melodic_parts), {"honky_tonk_piano", "violin"})
            self.assertEqual(melodic_parts["honky_tonk_piano"]["program"], 3)
            self.assertEqual(melodic_parts["violin"]["program"], 40)
            self.assertNotIn(10, [row["channel"] for row in melodic_parts.values()])
            preset_by_instrument = {
                row["detected_instrument"]: row for row in preset["tracks"]
            }
            self.assertEqual(
                preset_by_instrument["honky_tonk_piano"]["patch_source"],
                "installed-family-fallback")
            self.assertEqual(
                preset_by_instrument["honky_tonk_piano"]["patch"]["preferred"],
                ["Steinway Grand Piano"])
            self.assertEqual(
                preset_by_instrument["violin"]["patch_source"], "installed-exact")
            self.assertEqual(
                preset_by_instrument["violin"]["patch"]["preferred"],
                ["Solo Violin"])
            self.assertEqual(
                report["outputs"]["garageband_inventory"], str(inventory_path.resolve()))
            self.assertEqual(report["engines"]["instrument"]["used"], "clap")

            calls: list[tuple[str, ...]] = []
            visible_tracks = [
                {"index": index, "name": part["name"]}
                for index, part in enumerate(score["parts"], start=1)
            ]
            patch_results = {
                "Piano": "Steinway Grand Piano",
                "Violin": "Solo Violin",
                "SoCal": "SoCal",
            }

            def fake_bridge(*command: str) -> dict:
                calls.append(command)
                if command[0] == "score-spec-validate":
                    return validate_score_spec(score)
                if command[0] == "make-from-score-spec":
                    return {"opened": True}
                if command[0] == "list-tracks":
                    return {"tracks": visible_tracks}
                if command[0] == "select-track":
                    return {"selected": int(command[2])}
                if command[0] == "library-search":
                    name = patch_results[command[1]]
                    return {"results": [{"index": 1, "name": name}]}
                if command[0] == "library-select":
                    return {"selected": command[1], "index": int(command[3])}
                if command[0] == "set-track":
                    return {"updated": int(command[2])}
                raise AssertionError(f"Unexpected bridge command: {command}")

            with patch.object(
                    garageband_session, "bridge_call", side_effect=fake_bridge):
                prepared = garageband_session._open_and_patch(
                    outputs["score"], outputs["preset"], root/"project",
                    discard_unsaved=False)
            selected = {
                row["part"]: row["patch"] for row in prepared["selected_patches"]
            }
            self.assertEqual(
                selected[melodic_parts["honky_tonk_piano"]["name"]],
                "Steinway Grand Piano")
            self.assertEqual(
                selected[melodic_parts["violin"]["name"]], "Solo Violin")
            self.assertEqual(
                sum(command[0] == "library-select" for command in calls),
                len(score["parts"]))

            plan = garageband_session.prepare_plan(
                outputs["score"], outputs["preset"], root/"project",
                source, discard_unsaved=False)
            phases = [step["phase"] for step in plan["steps"]]
            self.assertIn("label_and_mute_reference", phases)
            self.assertEqual(plan["reference_audio"], str(source.resolve()))

    def test_stale_inventory_never_silently_selects_a_wrong_patch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            score = root/"score.json"
            score.write_text("{}\n", encoding="utf-8")
            preset = root/"preset.json"
            single_track_preset(preset)
            calls: list[tuple[str, ...]] = []

            def fake_bridge(*command: str) -> dict:
                calls.append(command)
                if command[0] == "score-spec-validate":
                    return {"ok": True}
                if command[0] == "make-from-score-spec":
                    return {"opened": True}
                if command[0] == "list-tracks":
                    return {"tracks": [{"index": 1, "name": "Transcribed Violin"}]}
                if command[0] == "select-track":
                    return {"selected": 1}
                if command[0] == "library-search":
                    return {"results": [{"index": 1, "name": "Studio Strings"}]}
                raise AssertionError(f"Unexpected bridge command: {command}")

            with patch.object(
                    garageband_session, "bridge_call", side_effect=fake_bridge):
                with self.assertRaisesRegex(
                        garageband_session.SessionError,
                        "No preferred GarageBand patch was found"):
                    garageband_session._open_and_patch(
                        score, preset, root/"project", discard_unsaved=False)
            self.assertFalse(any(command[0] == "library-select" for command in calls))

    def test_render_rejects_a_verified_but_truncated_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            score = root/"score.json"
            score.write_text("{}\n", encoding="utf-8")
            preset = root/"preset.json"
            single_track_preset(preset)
            args = SimpleNamespace(
                score=score, preset=preset, output_dir=root/"render",
                output=root/"music.wav", discard_unsaved=False,
                overwrite=False, dry_run=False,
            )
            args.output_dir.mkdir()
            opened = {
                "validation": {"ok": True, "duration_beats": 8.0, "bpm": BPM},
                "opened": {"opened": True},
                "tracks_before_patch": {"tracks": []},
                "selected_patches": [],
            }

            def fake_bridge(*command: str) -> dict:
                if command[0] == "screenshot":
                    return {"captured": True}
                if command[0] == "export-song":
                    return {
                        "verified": True,
                        "audio_info": {"duration_seconds": 1.0},
                    }
                raise AssertionError(f"Unexpected bridge command: {command}")

            with patch.object(
                    garageband_session.platform, "system", return_value="Darwin"), \
                    patch.object(
                        garageband_session, "_open_and_patch", return_value=opened), \
                    patch.object(
                        garageband_session, "bridge_call", side_effect=fake_bridge):
                with self.assertRaisesRegex(
                        garageband_session.SessionError, "file is too short"):
                    garageband_session.run_render(args)
            manifest = root/"render"/"session-result.json"
            self.assertTrue(manifest.is_file())
            result = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertFalse(result["ok"])
            self.assertTrue(result["audio_export"]["verified"])
            self.assertFalse(result["duration_verification"]["not_short"])
            self.assertEqual(result["duration_verification"]["expected_score_seconds"], 4.0)
            self.assertEqual(result["duration_verification"]["actual_seconds"], 1.0)


if __name__ == "__main__":
    unittest.main()

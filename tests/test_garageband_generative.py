from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from garageband.generative import (
    UPSTREAM_COMMIT,
    GenerativeMusicError,
    build_garageband_handoff,
    build_generation_plan,
    run_generation,
    status,
)


class GarageBandGenerativeTests(unittest.TestCase):
    def config(self, directory: Path) -> Path:
        ace = directory / "ace-step"
        ace.mkdir()
        config = directory / "config.json"
        config.write_text(
            json.dumps(
                {
                    "ace_step_dir": str(ace),
                    "output_dir": str(directory / "outputs"),
                    "defaults": {
                        "quality": "draft",
                        "format": "wav",
                        "instrumental": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config

    def test_status_reports_pinned_upstream_and_missing_runtime(self):
        result = status()
        self.assertTrue(result["checks"]["vendored_repository"])
        self.assertTrue(result["checks"]["engine"])
        self.assertEqual(result["upstream"]["commit"], UPSTREAM_COMMIT)
        self.assertEqual(result["upstream"]["license"], "MIT")

    def test_plan_defaults_to_instrumental_wav_and_uses_argument_array(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            plan = build_generation_plan(
                {
                    "caption": "-restrained Apple-style percussion; no vocals",
                    "duration": 30,
                },
                config_path=config,
            )
            command = plan["command"]
            self.assertTrue(plan["ready"])
            self.assertTrue(plan["instrumental"])
            self.assertEqual(plan["format"], "wav")
            self.assertIn("--instrumental", command)
            self.assertIn(
                "--caption=-restrained Apple-style percussion; no vocals", command
            )
            self.assertNotIn("sh", command[:1])
            self.assertLess(command.index("--output-dir"), command.index("generate"))

    def test_cover_and_repaint_require_existing_source_and_valid_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            source = root / "reference.wav"
            source.write_bytes(b"RIFF-test")
            cover = build_generation_plan(
                {
                    "action": "cover",
                    "source_audio": str(source),
                    "caption": "minimal cinematic percussion",
                    "cover_strength": 0.3,
                },
                config_path=config,
            )
            self.assertIn(f"--src-audio={source}", cover["command"])
            self.assertIn("--cover-strength", cover["command"])
            with self.assertRaisesRegex(GenerativeMusicError, "greater than"):
                build_generation_plan(
                    {
                        "action": "repaint",
                        "source_audio": str(source),
                        "start": 5,
                        "end": 2,
                    },
                    config_path=config,
                )
            with self.assertRaisesRegex(GenerativeMusicError, "not supported"):
                build_generation_plan(
                    {
                        "action": "extract",
                        "source_audio": str(source),
                        "bpm": 118,
                    },
                    config_path=config,
                )

    def test_request_contract_rejects_typos_and_unsafe_implicit_types(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            with self.assertRaisesRegex(GenerativeMusicError, "unknown.*duraton"):
                build_generation_plan(
                    {"caption": "test", "duraton": 20}, config_path=config
                )
            with self.assertRaisesRegex(
                GenerativeMusicError, "batch must be an integer"
            ):
                build_generation_plan(
                    {"caption": "test", "batch": 1.5}, config_path=config
                )
            with self.assertRaisesRegex(
                GenerativeMusicError, "instrumental must be a boolean"
            ):
                build_generation_plan(
                    {"caption": "test", "instrumental": "false"}, config_path=config
                )

    def test_max_quality_requires_explicit_expensive_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            plan = build_generation_plan(
                {
                    "caption": "test",
                    "quality": "max",
                },
                config_path=config,
            )
            self.assertTrue(
                any("acknowledge_expensive" in warning for warning in plan["warnings"])
            )

            def runner(command, **kwargs):
                raise AssertionError("runner must not be reached")

            with self.assertRaisesRegex(GenerativeMusicError, "acknowledge_expensive"):
                run_generation(
                    {"caption": "test", "quality": "max"},
                    config_path=config,
                    runner=runner,
                )

    def test_run_generation_verifies_output_hash_and_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            generated = root / "outputs" / "candidate.wav"

            def runner(command, **kwargs):
                generated.parent.mkdir(parents=True)
                generated.write_bytes(b"RIFF-generated-candidate")
                payload = {
                    "success": True,
                    "task_type": "text2music",
                    "outputs": [{"path": str(generated), "seed": 42, "index": 1}],
                    "count": 1,
                }
                return subprocess.CompletedProcess(
                    command, 0, json.dumps(payload), "progress"
                )

            result = run_generation(
                {
                    "caption": "precise product-film percussion",
                    "duration": 20,
                    "select_output": 1,
                },
                config_path=config,
                runner=runner,
            )
            output = result["outputs"][0]
            self.assertEqual(result["status"], "generated")
            self.assertEqual(output["bytes"], len(b"RIFF-generated-candidate"))
            self.assertEqual(len(output["sha256"]), 64)
            self.assertEqual(result["selected_audio"], str(generated))
            self.assertFalse(
                result["garageband_handoff"]["reference_import"]["editable_notes"]
            )
            self.assertFalse(
                result["garageband_handoff"]["editable_reconstruction"][
                    "one_to_one_claim"
                ]
            )

    def test_run_generation_rejects_false_success_and_missing_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)

            def no_outputs(command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 0, json.dumps({"success": True, "outputs": []}), ""
                )

            with self.assertRaisesRegex(GenerativeMusicError, "without audio outputs"):
                run_generation(
                    {"caption": "test"}, config_path=config, runner=no_outputs
                )

            def failed(command, **kwargs):
                return subprocess.CompletedProcess(
                    command,
                    1,
                    json.dumps({"success": False, "error": "CUDA unavailable"}),
                    "",
                )

            with self.assertRaisesRegex(GenerativeMusicError, "CUDA unavailable"):
                run_generation({"caption": "test"}, config_path=config, runner=failed)

    def test_handoff_keeps_exact_reference_separate_from_editable_approximation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "candidate.wav"
            audio.write_bytes(b"RIFF")
            handoff = build_garageband_handoff(
                audio,
                project_dir=root / "garageband-project",
                transcription_quality="fast",
            )
            reference = handoff["reference_import"]
            editable = handoff["editable_reconstruction"]
            self.assertEqual(reference["command"][-2:], ["open", str(audio)])
            self.assertIn("--prepare-dry-run", editable["command"])
            self.assertFalse(editable["touches_garageband"])


if __name__ == "__main__":
    unittest.main()

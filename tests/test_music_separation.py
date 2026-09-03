from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

import music_separation  # noqa: E402


class MusicSeparationUnitTests(unittest.TestCase):
    def test_high_quality_demucs_enforces_tested_package_pin(self) -> None:
        separator = music_separation.DemucsSeparator(
            quality="high", model=None, device="cpu"
        )
        with mock.patch.object(
            music_separation, "demucs_version", return_value="4.0.0"
        ):
            with self.assertRaisesRegex(
                music_separation.SeparationError,
                music_separation.DEMUCS_PACKAGE_PIN,
            ):
                separator.ensure_ready()

    def test_high_quality_demucs_uses_finetuned_model_and_validates_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            source.write_bytes(b"x" * 64)
            output_dir = root / "separated"
            observed: list[str] = []

            def fake_run(command: list[str], _label: str) -> None:
                observed.extend(command)
                stem_dir = output_dir / "htdemucs_ft" / "source"
                stem_dir.mkdir(parents=True)
                (stem_dir / "no_vocals.wav").write_bytes(b"n" * 64)
                (stem_dir / "vocals.wav").write_bytes(b"v" * 64)

            separator = music_separation.DemucsSeparator(
                quality="high", model=None, device="cpu"
            )
            with mock.patch.object(
                music_separation,
                "demucs_version",
                return_value=music_separation.DEMUCS_PACKAGE_PIN,
            ), mock.patch.object(music_separation, "_run", side_effect=fake_run):
                result = separator.separate(source, output_dir)

        self.assertEqual(result.model, "htdemucs_ft")
        self.assertEqual(result.backend, "demucs")
        self.assertIn("--two-stems", observed)
        self.assertEqual(sorted(result.stems), ["no_vocals", "vocals"])

    def test_auto_backend_falls_back_to_configured_roformer_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / "roformer-adapter"
            command.write_text("#!/bin/sh\n", encoding="utf-8")
            command.chmod(0o755)
            with mock.patch.object(
                music_separation, "demucs_available", return_value=False
            ):
                selected = music_separation.select_separator(
                    "auto",
                    quality="standard",
                    model=None,
                    device="cpu",
                    roformer=command,
                )
        self.assertIsInstance(selected, music_separation.RoFormerSeparator)

    def test_high_auto_uses_roformer_when_demucs_pin_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / "roformer-adapter"
            command.write_text("#!/bin/sh\n", encoding="utf-8")
            command.chmod(0o755)
            with mock.patch.object(
                music_separation, "demucs_version", return_value="4.0.0"
            ), mock.patch.object(
                music_separation, "demucs_available", return_value=True
            ):
                selected = music_separation.select_separator(
                    "auto",
                    quality="high",
                    model=None,
                    device="cpu",
                    roformer=command,
                )
        self.assertIsInstance(selected, music_separation.RoFormerSeparator)

    def test_roformer_records_valid_checkpoint_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = root / "roformer-adapter"
            command.write_text("#!/bin/sh\n", encoding="utf-8")
            command.chmod(0o755)
            source = root / "source.wav"
            source.write_bytes(b"x" * 64)
            output_dir = root / "result"

            def fake_run(_command: list[str], _label: str) -> None:
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "instrumental.wav").write_bytes(b"i" * 64)
                (output_dir / "provenance.json").write_text(
                    "{\"model\":\"mel-roformer\",\"version\":\"1\","
                    f"\"checkpoint_sha256\":\"{'a' * 64}\",\"license\":\"MIT\"}}",
                    encoding="utf-8",
                )

            separator = music_separation.RoFormerSeparator(command)
            with mock.patch.object(music_separation, "_run", side_effect=fake_run):
                result = separator.separate(source, output_dir)

        self.assertEqual(result.model, "mel-roformer")
        self.assertEqual(result.version, "1")
        self.assertEqual(result.provenance["checkpoint_sha256"], "a" * 64)
        self.assertFalse(result.warnings)

    def test_roformer_contract_requires_exactly_one_instrumental_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = root / "roformer-adapter"
            command.write_text("#!/bin/sh\n", encoding="utf-8")
            command.chmod(0o755)
            source = root / "source.wav"
            source.write_bytes(b"x" * 64)
            output_dir = root / "result"

            def fake_run(_command: list[str], _label: str) -> None:
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "instrumental.wav").write_bytes(b"i" * 64)
                (output_dir / "no_vocals.wav").write_bytes(b"n" * 64)

            separator = music_separation.RoFormerSeparator(command)
            with mock.patch.object(music_separation, "_run", side_effect=fake_run):
                with self.assertRaisesRegex(
                    music_separation.SeparationError, "genau instrumental.wav"
                ):
                    separator.separate(source, output_dir)

    def test_auto_fails_when_no_local_separator_is_ready(self) -> None:
        with mock.patch.object(
            music_separation, "demucs_available", return_value=False
        ), mock.patch.object(
            music_separation, "roformer_command", return_value=None
        ):
            with self.assertRaisesRegex(
                music_separation.SeparationError, "Kein lokaler Musik-Separator"
            ):
                music_separation.select_separator(
                    "auto", quality="standard", model=None, device="cpu"
                )


if __name__ == "__main__":
    unittest.main()

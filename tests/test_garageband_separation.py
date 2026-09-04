from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "render"))

import music_separation as separation
from garageband.transcribe import separate_stems, TranscriptionError


class SharedSeparationTests(unittest.TestCase):
    def test_garageband_delegates_to_shared_backend(self):
        with mock.patch("garageband.transcribe.separate_instrument_stems") as shared:
            shared.return_value = ({"mix": Path("source.wav")}, {"used": "off"})
            separate_stems(Path("source.wav"), Path("work"), mode="off")
        shared.assert_called_once_with(
            Path("source.wav"), Path("work"), backend="off", quality="standard",
            model="htdemucs_6s", device="cpu", roformer=None)

    def test_instrument_task_requests_all_stems_instead_of_two_stems(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "stems"
            observed = []

            def fake_run(command, label):
                observed.extend(command)
                stem_dir = output / "htdemucs_6s" / "input"
                stem_dir.mkdir(parents=True)
                for role in ("drums", "bass", "other", "piano", "guitar", "vocals"):
                    wavfile.write(stem_dir / f"{role}.wav", 44_100,
                                  np.zeros((100, 2), dtype=np.float32))

            backend = separation.DemucsSeparator(
                quality="high", model=None, device="cpu", task="instruments")
            with mock.patch.object(separation, "demucs_version", return_value="4.0.1"), \
                 mock.patch.object(separation, "_run", side_effect=fake_run):
                result = backend.separate(root / "input.wav", output)
        self.assertNotIn("--two-stems", observed)
        self.assertEqual(result.model, "htdemucs_6s")
        self.assertEqual(len(result.stems), 6)
        self.assertEqual(result.manifest()["task"], "instruments")
        self.assertEqual(result.manifest()["stem"], "drums")

    def test_explicit_and_high_failures_never_fall_back(self):
        for backend, quality in (("demucs", "standard"), ("auto", "high")):
            with self.subTest(backend=backend, quality=quality), tempfile.TemporaryDirectory() as directory:
                with mock.patch.object(separation.DemucsSeparator, "separate",
                                       side_effect=separation.SeparationError("fixture failure")), \
                     mock.patch.object(separation, "demucs_available", return_value=True):
                    with self.assertRaisesRegex(TranscriptionError, "fixture failure"):
                        separate_stems(Path("input.wav"), Path(directory), mode=backend, quality=quality)

    def test_auto_standard_fallback_is_declared(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(separation.DemucsSeparator, "separate",
                                   side_effect=separation.SeparationError("fixture failure")), \
                 mock.patch.object(separation, "demucs_available", return_value=True):
                stems, report = separate_stems(Path("input.wav"), Path(directory))
        self.assertEqual(stems, {"mix": Path("input.wav")})
        self.assertFalse(report["isolated_drums"])
        self.assertIn("fallback", report["used"])
        self.assertEqual(report["warnings"], ["fixture failure"])

    def test_roformer_is_only_a_mix_not_isolated_drums(self):
        result = separation.SeparationResult(
            backend="roformer", primary_path=Path("instrumental.wav"), model="test",
            version=None, stems={"no_vocals": Path("instrumental.wav")})
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(separation.RoFormerSeparator, "separate", return_value=result):
                stems, report = separate_stems(Path("input.wav"), Path(directory), mode="roformer")
                with self.assertRaisesRegex(TranscriptionError, "Provenienz"):
                    separate_stems(Path("input.wav"), Path(directory), mode="roformer", quality="high")
        self.assertEqual(stems, {"mix": Path("instrumental.wav")})
        self.assertFalse(report["isolated_drums"])

    def test_keep_work_runs_use_different_stem_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            observed = []
            result = separation.SeparationResult(
                backend="demucs", primary_path=Path("drums.wav"), model="test", version="4.0.1",
                stems={"drums": Path("drums.wav")}, task="instruments", primary_stem="drums")

            def fake_run(source, output):
                observed.append(output)
                return result

            with mock.patch.object(separation.DemucsSeparator, "separate", side_effect=fake_run):
                for _ in range(2):
                    separate_stems(Path("input.wav"), Path(directory), mode="demucs")
            self.assertNotEqual(observed[0], observed[1])


class RoFormerGarageBandE2ETests(unittest.TestCase):
    def test_workflow_uses_estimate_and_rejects_resume_after_adapter_changes(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg required")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original.wav"
            times = np.arange(96_000) / 48_000
            signal = (.1 * np.sin(times * 2 * np.pi * 220)).astype(np.float32)
            wavfile.write(source, 48_000, np.column_stack((signal, signal)))
            before = source.read_bytes()
            adapter = root / "adapter with spaces"
            adapter.write_text(
                f"#!{sys.executable}\n"
                "import argparse\nfrom pathlib import Path\nimport numpy as np\n"
                "from scipy.io import wavfile\n"
                "p=argparse.ArgumentParser()\np.add_argument('--input', type=Path)\n"
                "p.add_argument('--output-dir', type=Path)\na=p.parse_args()\n"
                "rate, audio=wavfile.read(a.input)\n"
                "wavfile.write(a.output_dir/'instrumental.wav', rate, audio*.5)\n",
                encoding="utf-8")
            adapter.chmod(0o755)
            project = root / "project"
            command = [sys.executable, "garageband/workflow.py", str(source),
                       "--project-dir", str(project), "--quality", "fast",
                       "--separate", "roformer", "--roformer-command", str(adapter),
                       "--content", "percussion", "--pitch-engine", "off",
                       "--instrument-engine", "off", "--bpm", "120"]
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((project / "analysis" / "transcription-report.json").read_text())
            self.assertEqual(report["source"]["file_name"], "instrumental.wav")
            self.assertEqual(report["outputs"]["reference_audio"], str(source))
            self.assertEqual(report["engines"]["separation"]["used"], "roformer")
            self.assertFalse(report["engines"]["separation"]["isolated_drums"])
            self.assertEqual(source.read_bytes(), before)
            resumed = subprocess.run(command + ["--resume"], cwd=ROOT, text=True,
                                     capture_output=True, timeout=30)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            adapter.write_text(adapter.read_text() + "# changed\n", encoding="utf-8")
            refused = subprocess.run(command + ["--resume"], cwd=ROOT, text=True,
                                     capture_output=True, timeout=30)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("configuration", refused.stderr.lower())


if __name__ == "__main__":
    unittest.main()

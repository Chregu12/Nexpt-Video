from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "render" / "fcpxml.py"
SYNC = REPO / "render" / "sync.py"
TIMING = REPO / "render" / "timing.json"


def write_wav(path: Path, frames: int = 4_800) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(48_000)
        target.writeframes(b"\0" * frames * 4)


class FcpxmlEndToEndTests(unittest.TestCase):
    def test_cli_audio_export_round_trips_through_sync_without_writing_timing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "Final Cut Package"
            output = package / "NEXPT-Keynote.fcpxml"
            music = package / "Music Stem.wav"
            effects = package / "SFX Stem.wav"
            config = root / "audio.json"
            write_wav(music)
            write_wav(effects)
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tracks": [
                            {
                                "id": "music",
                                "name": "Music Stem",
                                "path": "Final Cut Package/Music Stem.wav",
                                "role": "music.nexpt",
                                "enabled": True,
                            },
                            {
                                "id": "effects",
                                "name": "SFX Stem",
                                "path": "Final Cut Package/SFX Stem.wav",
                                "role": "effects.nexpt",
                                "enabled": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            timing_before = TIMING.read_bytes()
            exported = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--timing",
                    str(TIMING),
                    "--output",
                    str(output),
                    "--audio-config",
                    str(config),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                exported.returncode,
                0,
                f"stdout:\n{exported.stdout}\nstderr:\n{exported.stderr}",
            )
            self.assertIn("30 Clips · 2 Audiospuren", exported.stdout)
            manifest_path = output.with_suffix(".fcpxml.manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["audio"]["music_and_sfx_separate"])
            self.assertFalse(manifest["verification"]["final_cut_import_verified"])
            xml = ET.parse(output).getroot()
            self.assertEqual(len(xml.findall("./resources/asset[@hasAudio='1']")), 2)

            synced = subprocess.run(
                [sys.executable, str(SYNC), str(output), "--dry"],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                synced.returncode,
                0,
                f"stdout:\n{synced.stdout}\nstderr:\n{synced.stderr}",
            )
            self.assertIn("FCPXML gelesen", synced.stdout)
            self.assertIn("30 Clips", synced.stdout)
            self.assertIn("--dry: timing.json unverändert", synced.stdout)
            self.assertEqual(TIMING.read_bytes(), timing_before)

    def test_check_mode_validates_without_creating_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created.fcpxml"
            checked = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--timing",
                    str(TIMING),
                    "--output",
                    str(output),
                    "--check",
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                checked.returncode,
                0,
                f"stdout:\n{checked.stdout}\nstderr:\n{checked.stderr}",
            )
            self.assertIn("geprueft, nichts geschrieben", checked.stdout)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".fcpxml.manifest.json").exists())


if __name__ == "__main__":
    unittest.main()

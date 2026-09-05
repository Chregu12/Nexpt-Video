from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import wave
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "render"))

import fcpxml  # noqa: E402


def write_timing(path: Path, scenes: list[dict] | None = None) -> None:
    payload = {
        "meta": {
            "title": "Test & Timeline",
            "fps": 30,
            "width": 1920,
            "height": 1080,
        },
        "scenes": scenes
        or [
            {
                "id": "scene_one",
                "act": "1 Intro",
                "start": 0.0,
                "dur": 0.5,
                "vo": "Text < sicher",
                "bgFlips": [{"t": 0.2, "to": "dark & calm"}],
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_wav(
    path: Path,
    frames: int,
    *,
    sample_rate: int = 48_000,
    channels: int = 2,
    sample_width: int = 2,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(sample_width)
        target.setframerate(sample_rate)
        target.writeframes(b"\0" * frames * channels * sample_width)


def write_config(path: Path, tracks: list[dict]) -> None:
    path.write_text(
        json.dumps({"schema_version": 1, "tracks": tracks}), encoding="utf-8"
    )


def seconds(value: str) -> Fraction:
    return Fraction(value.removesuffix("s"))


class FcpxmlUnitTests(unittest.TestCase):
    def test_checked_in_config_keeps_music_and_sfx_in_seven_roles(self) -> None:
        config = json.loads(
            (REPO / "render" / "final-cut-audio.json").read_text(encoding="utf-8")
        )
        roles = [track["role"] for track in config["tracks"]]
        self.assertEqual(len(roles), 7)
        self.assertEqual(len(set(roles)), 7)
        self.assertEqual(sum(role.startswith("music.") for role in roles), 4)
        self.assertEqual(sum(role.startswith("effects.") for role in roles), 3)

    def test_video_timeline_is_contiguous_and_keeps_all_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out" / "timeline.fcpxml"
            report = fcpxml.generate_fcpxml(
                REPO / "render" / "timing.json", output
            )
            root = ET.parse(output).getroot()
            manifest = json.loads(
                output.with_suffix(".fcpxml.manifest.json").read_text(encoding="utf-8")
            )

        self.assertEqual(root.get("version"), "1.10")
        self.assertEqual(len(root.findall("./resources/asset[@hasVideo='1']")), 30)
        clips = root.findall("./library/event/project/sequence/spine/asset-clip")
        self.assertEqual(len(clips), 30)
        for current, following in zip(clips, clips[1:]):
            self.assertEqual(
                seconds(current.get("offset", "0s"))
                + seconds(current.get("duration", "0s")),
                seconds(following.get("offset", "0s")),
            )

        timing = json.loads((REPO / "render" / "timing.json").read_text())
        expected_flips = sum(
            len(scene.get("bgFlips", [])) + int("bgFlip" in scene)
            for scene in timing["scenes"]
        )
        flip_markers = [
            marker
            for marker in root.iter("marker")
            if marker.get("value", "").startswith("BG →")
        ]
        self.assertEqual(len(flip_markers), expected_flips)
        self.assertFalse(report["audio"]["configured"])
        self.assertEqual(report["audio"]["track_count"], 0)
        self.assertTrue(manifest["verification"]["xml_well_formed"])
        self.assertFalse(manifest["verification"]["final_cut_import_verified"])

    def test_audio_stems_get_roles_lanes_urls_and_an_audio_tail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root_dir = Path(directory)
            timing = root_dir / "timing.json"
            output = root_dir / "out" / "Project.fcpxml"
            config = root_dir / "audio.json"
            music = output.parent / "Music Low.wav"
            effects = output.parent / "SFX Motion.wav"
            write_timing(timing)
            write_wav(music, 24_000)
            write_wav(effects, 72_000)
            write_config(
                config,
                [
                    {
                        "id": "music-low",
                        "name": "Music Low",
                        "path": "out/Music Low.wav",
                        "role": "music.nexpt-low",
                        "enabled": True,
                    },
                    {
                        "id": "sfx-motion",
                        "name": "SFX Motion",
                        "path": "out/SFX Motion.wav",
                        "role": "effects.nexpt-motion",
                        "enabled": False,
                    },
                ],
            )

            report = fcpxml.generate_fcpxml(timing, output, config)
            xml = ET.parse(output).getroot()
            manifest = json.loads(
                output.with_suffix(".fcpxml.manifest.json").read_text(encoding="utf-8")
            )
            output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()

        assets = xml.findall("./resources/asset[@hasAudio='1']")
        self.assertEqual(len(assets), 2)
        self.assertEqual(
            [asset.find("media-rep").get("src") for asset in assets],
            ["Music%20Low.wav", "SFX%20Motion.wav"],
        )
        first_video = xml.find("./library/event/project/sequence/spine/asset-clip")
        self.assertIsNotNone(first_video)
        connected = first_video.findall("asset-clip")
        self.assertEqual([clip.get("lane") for clip in connected], ["-1", "-2"])
        self.assertEqual(
            [clip.get("audioRole") for clip in connected],
            ["music.nexpt-low", "effects.nexpt-motion"],
        )
        self.assertEqual([clip.get("srcEnable") for clip in connected], ["audio", "audio"])
        self.assertEqual([clip.get("enabled") for clip in connected], ["1", "0"])
        self.assertEqual([asset.get("duration") for asset in assets], ["1/2s", "3/2s"])
        sequence = xml.find("./library/event/project/sequence")
        self.assertEqual(sequence.get("duration"), "3/2s")
        tail = xml.find("./library/event/project/sequence/spine/gap[@name='Audio tail']")
        self.assertIsNotNone(tail)
        self.assertEqual(tail.get("duration"), "1s")
        self.assertEqual(report["audio"]["track_count"], 2)
        self.assertTrue(report["audio"]["music_and_sfx_separate"])
        self.assertEqual(
            manifest["output"]["sha256"],
            output_sha256,
        )
        self.assertNotIn(directory, json.dumps(manifest))

    def test_invalid_config_never_replaces_an_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timing = root / "timing.json"
            output = root / "out" / "keep.fcpxml"
            config = root / "audio.json"
            music = output.parent / "music.wav"
            effects = output.parent / "effects.wav"
            write_timing(timing)
            write_wav(music, 100)
            write_wav(effects, 100)
            output.write_text("KEEP", encoding="utf-8")
            write_config(
                config,
                [
                    {
                        "id": "music",
                        "name": "Music",
                        "path": "out/music.wav",
                        "role": "music.same",
                        "enabled": True,
                    },
                    {
                        "id": "effects",
                        "name": "Effects",
                        "path": "out/effects.wav",
                        "role": "music.same",
                        "enabled": True,
                    },
                ],
            )
            with self.assertRaisesRegex(fcpxml.FcpxmlError, "Doppelte Audio-Rolle"):
                fcpxml.generate_fcpxml(timing, output, config)
            self.assertEqual(output.read_text(encoding="utf-8"), "KEEP")
            self.assertFalse(output.with_suffix(".fcpxml.manifest.json").exists())

    def test_bad_wav_metadata_truncation_and_symlink_are_rejected(self) -> None:
        cases = (
            ("mono", {"channels": 1}, "Stereo"),
            ("wrong-rate", {"sample_rate": 44_100}, "48000 Hz"),
            ("truncated", {}, "abgeschnitten"),
            ("symlink", {}, "Symlink"),
        )
        for case, options, message in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                timing = root / "timing.json"
                output = root / "out" / "project.fcpxml"
                config = root / "audio.json"
                invalid = output.parent / "invalid.wav"
                valid = output.parent / "effects.wav"
                write_timing(timing)
                write_wav(invalid, 100, **options)
                write_wav(valid, 100)
                if case == "truncated":
                    invalid.write_bytes(invalid.read_bytes()[:-2])
                if case == "symlink":
                    real = output.parent / "real.wav"
                    invalid.replace(real)
                    invalid.symlink_to(real.name)
                write_config(
                    config,
                    [
                        {
                            "id": "music",
                            "name": "Music",
                            "path": "out/invalid.wav",
                            "role": "music.main",
                            "enabled": True,
                        },
                        {
                            "id": "effects",
                            "name": "Effects",
                            "path": "out/effects.wav",
                            "role": "effects.main",
                            "enabled": True,
                        },
                    ],
                )
                with self.assertRaisesRegex(fcpxml.FcpxmlError, message):
                    fcpxml.generate_fcpxml(timing, output, config)
                self.assertFalse(output.exists())

    def test_sources_outside_the_output_package_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timing = root / "timing.json"
            output = root / "package" / "project.fcpxml"
            config = root / "audio.json"
            write_timing(timing)
            write_wav(root / "music.wav", 100)
            write_wav(output.parent / "effects.wav", 100)
            write_config(
                config,
                [
                    {
                        "id": "music",
                        "name": "Music",
                        "path": "music.wav",
                        "role": "music.main",
                        "enabled": True,
                    },
                    {
                        "id": "effects",
                        "name": "Effects",
                        "path": "package/effects.wav",
                        "role": "effects.main",
                        "enabled": True,
                    },
                ],
            )
            with self.assertRaisesRegex(fcpxml.FcpxmlError, "portables Paket"):
                fcpxml.generate_fcpxml(timing, output, config)

    def test_changed_input_aborts_after_staging_and_cleans_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timing = root / "timing.json"
            output = root / "out" / "keep.fcpxml"
            write_timing(timing)
            output.parent.mkdir()
            output.write_text("KEEP", encoding="utf-8")
            with mock.patch.object(
                fcpxml,
                "_assert_inputs_unchanged",
                side_effect=[None, fcpxml.FcpxmlError("veraendert")],
            ):
                with self.assertRaisesRegex(fcpxml.FcpxmlError, "veraendert"):
                    fcpxml.generate_fcpxml(timing, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "KEEP")
            self.assertFalse(output.with_suffix(".fcpxml.manifest.json").exists())
            self.assertEqual(list(output.parent.glob(".*.fcpxml.*")), [])


if __name__ == "__main__":
    unittest.main()

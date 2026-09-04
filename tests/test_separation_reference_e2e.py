"""Real FFmpeg/ffprobe and CLI tests on generated signals, not model-quality tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

from separation_benchmark import load_corpus
from separation_metrics import ROLES
from video_music import executable


class ReferenceCLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.spec_path = self.root / "sources with spaces.json"
        self.destination = self.root / "prepared with spaces"
        self.spec = {"schema_version": 1, "kind": "nexpt-reference-import", "sample_rate": 44_100,
                     "cases": [{"id": "example", "reference_kind": "synthetic-diagnostic", "duration_seconds": 2,
                                "mix_gain": .5, "stems": {role: {"path": f"{role}.wav", "license": "test-only",
                                  "attribution": "generated CLI test signal", "start_seconds": .25,
                                  "duration_seconds": 1, "offset_seconds": .5} for role in ROLES}}]}
        self.originals = {}
        for role, rate, channels, frequency in (("music", 44_100, 2, 110), ("dialogue", 16_000, 1, 230),
                                               ("sfx", 48_000, 2, 370)):
            times = np.arange(rate * 3) / rate
            audio = (.1 * np.sin(2 * np.pi * frequency * times)).astype(np.float32)
            if channels == 2:
                audio = np.column_stack((audio, -audio * .5))
            wavfile.write(self.root / f"{role}.wav", rate, audio)
            self.originals[role] = (self.root / f"{role}.wav").read_bytes()

    def cli(self, *args):
        environment = {**os.environ, "NEXPT_CDX_CONFIG": ""}
        return subprocess.run([sys.executable, "render/separation_benchmark.py", *map(str, args)],
                              cwd=ROOT, env=environment, text=True, capture_output=True, timeout=60)

    def prepare(self):
        self.spec_path.write_text(json.dumps(self.spec))
        return self.cli("prepare", self.spec_path, "--output-dir", self.destination)

    def encode(self, *arguments):
        subprocess.run([executable("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", *map(str, arguments)],
                       capture_output=True, check=True, timeout=20)

    def test_real_decoder_resampling_stereo_and_timeline_followed_by_evaluation(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        corpus = load_corpus(self.destination / "corpus.json")
        self.assertEqual(corpus["cases"][0]["frames"], 88_200)
        rate, music = wavfile.read(self.destination / "cases/example/music.wav")
        _, source = wavfile.read(self.root / "music.wav")
        self.assertEqual(rate, 44_100)
        np.testing.assert_array_equal(music[:22_050], 0)
        np.testing.assert_allclose(music[22_050:66_150], source[11_025:55_125] * .5, atol=1e-7, rtol=0)
        np.testing.assert_array_equal(music[66_150:], 0)
        _, dialogue = wavfile.read(self.destination / "cases/example/dialogue.wav")
        np.testing.assert_array_equal(dialogue[:, 0], dialogue[:, 1])
        self.assertAlmostEqual(float(np.max(np.abs(dialogue))), .05, places=3)
        for role in ROLES:
            self.assertEqual((self.root / f"{role}.wav").read_bytes(), self.originals[role])
        # The copied known references are an oracle control, not inferred stems.
        evaluation = self.cli("evaluate", self.destination / "corpus.json", "--estimates-dir", self.destination / "cases",
                              "--name", "oracle-control", "--strict", "--output-dir", self.root / "evaluation")
        self.assertEqual(evaluation.returncode, 0, evaluation.stdout + evaluation.stderr)
        self.assertTrue(json.loads(evaluation.stdout)["summary"]["numerical_gate_passed"])

    def test_mp3_and_m4a_import_provenance_and_short_effect_padding(self):
        self.encode("-i", self.root / "music.wav", "-c:a", "libmp3lame", self.root / "music.mp3")
        self.encode("-i", self.root / "dialogue.wav", "-c:a", "aac", self.root / "dialogue.m4a")
        self.spec["cases"][0]["stems"]["music"]["path"] = "music.mp3"
        self.spec["cases"][0]["stems"]["dialogue"]["path"] = "dialogue.m4a"
        self.spec["cases"][0]["stems"]["sfx"].update({"duration_seconds": .2, "offset_seconds": 1.5})
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        corpus = json.loads(result.stdout)
        audit = corpus["preparation"]["cases"][0]["stems"]
        self.assertEqual(audit["music"]["input_format"]["codec"], "mp3")
        self.assertEqual(audit["dialogue"]["input_format"]["codec"], "aac")
        self.assertEqual(audit["sfx"]["frames"], 8_820)
        _, effect = wavfile.read(self.destination / "cases/example/sfx.wav")
        np.testing.assert_array_equal(effect[:66_150], 0)
        self.assertGreater(float(np.max(np.abs(effect[66_150:74_970]))), .01)
        np.testing.assert_array_equal(effect[74_970:], 0)

    def test_explicit_audio_stream_selection_and_missing_stream(self):
        container = self.root / "two tracks.mp4"
        self.encode("-i", self.root / "music.wav", "-i", self.root / "dialogue.wav", "-map", "0:a", "-map", "1:a",
                    "-c:a", "aac", container)
        self.spec["cases"][0]["stems"]["dialogue"].update({"path": container.name, "audio_stream": 1})
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        audit = json.loads(result.stdout)["preparation"]["cases"][0]["stems"]["dialogue"]
        self.assertEqual(audit["audio_stream"], 1)
        self.assertEqual(audit["input_format"]["channels"], 1)
        self.destination = self.root / "bad-stream"
        self.spec["cases"][0]["stems"]["dialogue"]["audio_stream"] = 2
        failed = self.prepare()
        self.assertEqual(failed.returncode, 1)
        self.assertIn("Audiospur 2 fehlt", json.loads(failed.stdout)["error"])
        self.assertFalse(self.destination.exists())

    def test_excerpt_past_end_fails_without_silent_extension_or_partial_output(self):
        self.spec["cases"][0]["stems"]["sfx"]["start_seconds"] = 2.5
        result = self.prepare()
        self.assertEqual(result.returncode, 1)
        self.assertIn("zu kurz", json.loads(result.stdout)["error"])
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob(".separation-benchmark-*")))

    def test_surround_source_is_not_silently_downmixed(self):
        wavfile.write(self.root / "sfx.wav", 48_000, np.zeros((48_000, 6), dtype=np.float32))
        result = self.prepare()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Surround", json.loads(result.stdout)["error"])
        self.assertFalse(self.destination.exists())

    def test_renamed_playlist_cannot_read_external_references(self):
        # An extension check alone would not prevent demuxer auto-detection.
        (self.root / "sfx.wav").write_text("ffconcat version 1.0\nfile '/not-a-permitted-input.wav'\n")
        result = self.prepare()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.destination.exists())
        self.assertIn("whitelist", json.loads(result.stdout)["error"])

    def test_preflight_is_read_only_and_reports_synthetic_and_missing_model_blockers(self):
        self.assertEqual(self.prepare().returncode, 0)
        before = {p.relative_to(self.destination): p.read_bytes() for p in self.destination.rglob("*") if p.is_file()}
        result = self.cli("preflight", self.destination / "corpus.json", "--output-dir", self.root / "preflight")
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        codes = {row["code"] for row in report["blockers"]}
        self.assertTrue({"diagnostic_references", "backend_unavailable", "music_only_cases"} <= codes)
        self.assertFalse(report["model_inference_executed"])
        self.assertFalse(report["ready_for_run"])
        self.assertEqual(report, json.loads((self.root / "preflight/preflight.json").read_text()))
        self.assertEqual(before, {p.relative_to(self.destination): p.read_bytes() for p in self.destination.rglob("*") if p.is_file()})
        repeated = self.cli("preflight", self.destination / "corpus.json", "--output-dir", self.root / "preflight")
        self.assertEqual(repeated.returncode, 1)
        self.assertEqual(report, json.loads((self.root / "preflight/preflight.json").read_text()))

    def test_missing_corpus_returns_actionable_json_and_no_implicit_files(self):
        result = self.cli("preflight", self.root / "absent/corpus.json", "--quality", "standard")
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn("invalid_corpus", {row["code"] for row in report["blockers"]})
        self.assertEqual(set(report["profiles"]), {"standard"})
        self.assertFalse((self.root / "absent").exists())


if __name__ == "__main__":
    unittest.main()

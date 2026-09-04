"""Source-import unit tests use explicit deterministic decoder stand-ins."""
from __future__ import annotations

import copy
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
sys.path.insert(0, str(ROOT / "render"))

from cinematic_separation import sha256
from separation_benchmark import BenchmarkError, load_corpus
import separation_reference as reference
from separation_metrics import ROLES


class ReferenceImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / "corpus"
        self.spec_path = self.root / "import.json"
        self.originals = {}
        times = np.arange(16_000) / 8_000
        for role, frequency in zip(ROLES, (103, 211, 307)):
            audio = (.1 * np.sin(2 * np.pi * frequency * times)).astype(np.float32)
            wavfile.write(self.root / f"{role}.wav", 8_000, np.column_stack((audio, -audio)))
            self.originals[role] = (self.root / f"{role}.wav").read_bytes()
        self.spec = {"schema_version": 1, "kind": "nexpt-reference-import", "sample_rate": 8_000,
                     "cases": [{"id": "example", "reference_kind": "synthetic-diagnostic", "duration_seconds": 2,
                                "mix_gain": .5, "stems": {role: {"path": f"{role}.wav", "license": "test-only",
                                "attribution": "generated test signal", "duration_seconds": 1,
                                "start_seconds": .25, "offset_seconds": .5} for role in ROLES}}]}
        paths = {name: sys.executable for name in ("ffmpeg", "ffprobe")}
        identities = {name: {"version": "explicit test double", "executable_sha256": sha256(Path(sys.executable))}
                      for name in paths}
        self.toolchain = self.enterContext(mock.patch.object(reference, "_toolchain", return_value=(paths, identities)))
        self.probe = self.enterContext(mock.patch.object(reference, "_probe", return_value={"codec": "test-only", "sample_rate": 8_000, "channels": 2}))
        self.decoder = self.enterContext(mock.patch.object(reference, "_decode", side_effect=self.decode))

    def decode(self, source, *, start_frame, frames, **kwargs):
        _, audio = wavfile.read(source)
        return audio[start_frame:start_frame + frames].copy()

    def prepare(self, spec=None, **kwargs):
        self.spec_path.write_text(json.dumps(self.spec if spec is None else spec))
        return reference.prepare_corpus(self.spec_path, self.output, **kwargs)

    def assert_not_published(self):
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob(".separation-benchmark-*")))

    def test_excerpt_placement_shared_gain_stereo_and_source_bytes(self):
        corpus = self.prepare()
        self.assertEqual(corpus, load_corpus(self.output / "corpus.json"))
        _, prepared = wavfile.read(self.output / "cases/example/music.wav")
        _, source = wavfile.read(self.root / "music.wav")
        np.testing.assert_array_equal(prepared[:4_000], 0)
        np.testing.assert_array_equal(prepared[4_000:12_000], source[2_000:10_000] * .5)
        np.testing.assert_array_equal(prepared[12_000:], 0)
        for role in ROLES:
            self.assertEqual((self.root / f"{role}.wav").read_bytes(), self.originals[role])
        self.assertEqual({p.name for p in self.output.iterdir()}, {"cases", "corpus.json"})

    def test_bound_provenance_is_portable_and_does_not_leak_source_paths(self):
        corpus = self.prepare()
        audit = corpus["preparation"]["cases"][0]["stems"]["music"]
        self.assertEqual(audit["input_sha256"], sha256(self.root / "music.wav"))
        self.assertEqual(audit["start_frame"], 2_000)
        self.assertEqual(audit["leading_silence_frames"], 4_000)
        self.assertEqual(audit["trailing_silence_frames"], 4_000)
        self.assertFalse(corpus["preparation"]["source_labels_verified"])
        self.assertNotIn(str(self.root), json.dumps(corpus))
        moved = self.root / "moved"
        shutil.move(self.output, moved)
        self.assertEqual(load_corpus(moved / "corpus.json"), corpus)
        corpus["preparation"]["cases"][0]["stems"]["music"]["offset_frames"] += 1
        (moved / "corpus.json").write_text(json.dumps(corpus))
        with self.assertRaisesRegex(BenchmarkError, "Identitaet"):
            load_corpus(moved / "corpus.json")

    def test_repeated_import_same_bytes_has_identical_corpus_id(self):
        first = self.prepare()
        self.output = self.root / "second"
        self.assertEqual(first, self.prepare())

    def test_declared_absent_roles_are_explicit_zero_tracks(self):
        self.spec["cases"][0]["stems"]["dialogue"] = None
        corpus = self.prepare()
        _, audio = wavfile.read(self.output / "cases/example/dialogue.wav")
        np.testing.assert_array_equal(audio, 0)
        self.assertTrue(corpus["preparation"]["cases"][0]["stems"]["dialogue"]["declared_absent"])
        self.assertEqual(self.decoder.call_count, 2)

    def test_half_up_frame_rounding_is_declared(self):
        self.assertEqual(reference._frames(.5 / 8_000, 8_000), 1)
        self.assertEqual(reference._frames(1.5 / 8_000, 8_000), 2)

    def test_invalid_spec_types_ids_kinds_rates_and_empty_sources_fail_before_decode(self):
        original = copy.deepcopy(self.spec)
        invalid = [[], {}, {**original, "sample_rate": True}, {**original, "sample_rate": 7_999},
                   {**original, "cases": []}, {**original, "cases": original["cases"] * 21},
                   {**original, "cases": original["cases"] * 2}, {**original, "cases": [None]}]
        for changes in ({"id": "../escape"}, {"reference_kind": "estimated-stems"},
                        {"reference_kind": []}, {"duration_seconds": 0}, {"duration_seconds": 31},
                        {"mix_gain": 0}, {"mix_gain": float("nan")}, {"stems": {r: None for r in ROLES}}):
            invalid.append({**original, "cases": [{**original["cases"][0], **changes}]})
        for spec in invalid:
            with self.subTest(spec=spec), self.assertRaises(BenchmarkError):
                self.prepare(spec)
            self.assert_not_published()
        self.decoder.assert_not_called()

    def test_invalid_excerpt_values_missing_provenance_and_nonlocal_paths_are_rejected(self):
        for changes in ({"start_seconds": -1}, {"start_seconds": float("inf")}, {"offset_seconds": True},
                        {"offset_seconds": 1.5}, {"duration_seconds": 0}, {"duration_seconds": None},
                        {"audio_stream": -1}, {"audio_stream": 1.5}, {"audio_stream": True},
                        {"license": ""}, {"attribution": None}, {"path": "https://example.invalid/source.wav"}):
            spec = copy.deepcopy(self.spec)
            spec["cases"][0]["stems"]["music"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(BenchmarkError):
                self.prepare(spec)
            self.assert_not_published()
        self.decoder.assert_not_called()

    def test_unknown_keys_do_not_silently_ignore_timeline_typos(self):
        for level in ("spec", "case", "stem"):
            spec = copy.deepcopy(self.spec)
            target = spec if level == "spec" else spec["cases"][0] if level == "case" else spec["cases"][0]["stems"]["music"]
            target["offset_second"] = 1
            with self.subTest(level=level), self.assertRaisesRegex(BenchmarkError, "Unbekannte"):
                self.prepare(spec)
            self.assert_not_published()

    def test_decoder_timeout_rolls_back_every_partial_artifact(self):
        self.decoder.side_effect = [self.decode(self.root / "music.wav", start_frame=2_000, frames=8_000),
                                    BenchmarkError("timeout")]
        with self.assertRaisesRegex(BenchmarkError, "timeout"):
            self.prepare()
        self.assert_not_published()

    def test_source_change_during_decode_invalidates_corpus(self):
        def changed(source, **kwargs):
            audio = self.decode(source, **kwargs)
            source.write_bytes(source.read_bytes() + b"changed")
            return audio
        self.decoder.side_effect = changed
        with self.assertRaisesRegex(BenchmarkError, "geaendert"):
            self.prepare()
        self.assert_not_published()

    def test_spec_change_during_decode_invalidates_corpus(self):
        def changed(source, **kwargs):
            self.spec_path.write_text("changed")
            return self.decode(source, **kwargs)
        self.decoder.side_effect = changed
        with self.assertRaisesRegex(BenchmarkError, "geaendert"):
            self.prepare()
        self.assert_not_published()

    def test_silence_and_clipping_are_rejected_without_normalization(self):
        for value in (0, 2):
            self.decoder.return_value = np.full((8_000, 2), value, dtype=np.float32)
            self.decoder.side_effect = None
            with self.subTest(value=value), self.assertRaises(BenchmarkError):
                self.prepare()
            self.assert_not_published()

    def test_existing_destination_and_dangling_symlink_are_preserved(self):
        self.output.mkdir()
        marker = self.output / "keep"
        marker.write_text("keep")
        with self.assertRaises(BenchmarkError):
            self.prepare()
        self.assertEqual(marker.read_text(), "keep")
        self.output = self.root / "link"
        self.output.symlink_to(self.root / "absent", target_is_directory=True)
        with self.assertRaises(BenchmarkError):
            self.prepare()
        self.assertTrue(self.output.is_symlink())
        self.decoder.assert_not_called()

    def test_invalid_decode_timeout_fails_before_subprocesses(self):
        for timeout in (0, -1, 601, float("nan"), True):
            with self.subTest(timeout=timeout), self.assertRaises(BenchmarkError):
                self.prepare(decode_timeout=timeout)
            self.assert_not_published()
        self.toolchain.assert_not_called()


class DecoderContractTests(unittest.TestCase):
    def test_subprocess_timeout_and_failure_become_import_errors(self):
        for effect in (subprocess.TimeoutExpired("ffmpeg", 1), OSError("unavailable")):
            with mock.patch.object(reference.subprocess, "run", side_effect=effect):
                with self.assertRaises(BenchmarkError):
                    reference._run(["ffmpeg"], timeout=1)
        with mock.patch.object(reference.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"", b"decode error")):
            with self.assertRaisesRegex(BenchmarkError, "decode error"):
                reference._run(["ffmpeg"], timeout=1)

    def test_decode_is_bounded_local_and_preserves_mono_amplitude(self):
        raw = np.ones((8, 2), dtype="<f4").tobytes()
        with mock.patch.object(reference, "_run", return_value=raw) as run:
            value = reference._decode(Path("/audio/source with spaces.wav"), stream=1, start_frame=80, frames=8,
                                      rate=8_000, metadata={"channels": 1}, tools={"ffmpeg": "ffmpeg"}, timeout=3)
        np.testing.assert_array_equal(value, 1)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file,pipe")
        self.assertIn("0:a:1", command)
        self.assertIn("pan=stereo|c0=c0|c1=c0", command[command.index("-af") + 1])
        self.assertEqual(run.call_args.kwargs["timeout"], 3)

    def test_short_extra_partial_and_nonfinite_pcm_are_rejected_not_padded(self):
        for raw in (b"", b"x", np.zeros((9, 2), dtype="<f4").tobytes(),
                    np.full((8, 2), np.nan, dtype="<f4").tobytes()):
            with self.subTest(size=len(raw)), mock.patch.object(reference, "_run", return_value=raw):
                with self.assertRaises(BenchmarkError):
                    reference._decode(Path("source.wav"), stream=0, start_frame=0, frames=8, rate=8_000,
                                      metadata={"channels": 2}, tools={"ffmpeg": "ffmpeg"}, timeout=3)


if __name__ == "__main__":
    unittest.main()

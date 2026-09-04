"""Runtime/receipt contracts. Fake probes are not evidence of model accuracy."""
from __future__ import annotations

import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

import cdx_runtime as runtime
import cdx_safe_inference as safe
import cinematic_separation
from cinematic_separation import CDX_CHECKPOINTS, CdxSeparator
from music_separation import SeparationError, _run
from video_music import VideoMusicError, _extract_wav, build_parser
from cdx_fixtures import make_cdx_fixture


def ready_probe():
    return {"dependencies_ready": True, "missing_or_broken": [], "fingerprint": "a" * 64,
            "cuda_available": False, "restricted_checkpoint_loader": True,
            "runtime_verified": False}


def probe_payload():
    return {"python": "3.12.13", "implementation": "CPython", "system": "Test",
            "machine": "test", "cuda_available": False,
            "restricted_checkpoint_loader": True, "packages": [["torch", "2.11.0"]],
            "modules": {name: {"imported": True, "version": "test"}
                        for name in runtime.RUNTIME_MODULES}}


def probe_result(payload):
    return subprocess.CompletedProcess([], 0, "noise\nNEXPT_RUNTIME=" + json.dumps(payload), "")


class RuntimeProbeTests(unittest.TestCase):
    def test_imports_do_not_claim_inference_and_fingerprint_is_stable(self):
        payload = probe_payload()
        with mock.patch.object(runtime.subprocess, "run", return_value=probe_result(payload)) as run:
            first = runtime.probe_runtime(sys.executable)
            second = runtime.probe_runtime(sys.executable)
        self.assertTrue(first["dependencies_ready"])
        self.assertFalse(first["runtime_verified"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(run.call_args.args[0][0], sys.executable)
        self.assertEqual(run.call_args.kwargs["timeout"], 30)

    def test_package_change_invalidates_fingerprint(self):
        one = probe_payload()
        two = {**one, "packages": [["torch", "different"]]}
        with mock.patch.object(runtime.subprocess, "run", side_effect=[probe_result(one), probe_result(two)]):
            self.assertNotEqual(runtime.probe_runtime(sys.executable)["fingerprint"],
                                runtime.probe_runtime(sys.executable)["fingerprint"])

    def test_missing_or_broken_import_is_not_ready(self):
        payload = probe_payload()
        payload["modules"]["torchaudio"] = {"imported": False, "error": "shared library missing"}
        with mock.patch.object(runtime.subprocess, "run", return_value=probe_result(payload)):
            report = runtime.probe_runtime(sys.executable)
        self.assertFalse(report["dependencies_ready"])
        self.assertEqual(report["missing_or_broken"], ["torchaudio"])

    def test_bad_duplicate_and_failed_probe_reports_are_rejected(self):
        for status, stdout in ((0, ""), (0, "NEXPT_RUNTIME=[]"),
                               (0, "NEXPT_RUNTIME={}\nNEXPT_RUNTIME={}"),
                               (0, 'NEXPT_RUNTIME={"modules":{"torch":{"imported":false}}}'),
                               (0, "NEXPT_RUNTIME=not-json"), (1, "NEXPT_RUNTIME={}")):
            result = subprocess.CompletedProcess([], status, stdout, "failure")
            with self.subTest(stdout=stdout), mock.patch.object(runtime.subprocess, "run", return_value=result):
                with self.assertRaises(SeparationError):
                    runtime.probe_runtime(sys.executable)

    def test_missing_interpreter_invalid_timeout_and_process_timeout(self):
        with self.assertRaises(SeparationError):
            runtime.probe_runtime("/no-such-cdx-python")
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(SeparationError):
                runtime.probe_runtime(sys.executable, timeout=timeout)
        with mock.patch.object(runtime.subprocess, "run", side_effect=subprocess.TimeoutExpired("probe", 1)):
            with self.assertRaisesRegex(SeparationError, "Runtime-Probe"):
                runtime.probe_runtime(sys.executable)


class SafeLoaderTests(unittest.TestCase):
    def invoke(self, root, *, unknown=(), high=False, unsafe_env="", missing=False, old=False):
        (root / "inference.py").write_text("# never executed by these tests\n")
        (root / "models").mkdir()
        for name in CDX_CHECKPOINTS[:1] if missing else CDX_CHECKPOINTS:
            (root / "models" / name).write_bytes(b"fixture")
        serialization = mock.MagicMock()
        serialization.get_unsafe_globals_in_checkpoint.return_value = list(unknown)
        torch = types.SimpleNamespace(serialization=serialization, hub=types.SimpleNamespace())
        if old:
            del serialization.get_unsafe_globals_in_checkpoint
        classes = {module: types.SimpleNamespace(**{name: type(name, (), {"__module__": module})})
                   for module, name in safe.ALLOWED_MODEL_CLASSES}
        forwarded = ["--input_audio", "source.wav", "--cpu"] + (["--high_quality"] if high else [])
        with mock.patch.dict(sys.modules, {"torch": torch}), \
                mock.patch.dict(os.environ, {"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": unsafe_env}), \
                mock.patch.object(sys, "path", list(sys.path)), \
                mock.patch.object(sys, "argv", ["runner", "--repository", str(root), *forwarded]), \
                mock.patch.object(safe.importlib, "import_module", side_effect=classes.__getitem__), \
                mock.patch.object(safe.runpy, "run_path") as run:
            safe.main()
            self.assertEqual(os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"], "1")
            self.assertEqual(sys.argv[1:], forwarded)
            run.assert_called_once_with(str(root / "inference.py"), run_name="__main__")
            serialization.safe_globals.assert_called_once()
            with self.assertRaisesRegex(RuntimeError, "Modelldownload ist deaktiviert"):
                torch.hub.download_url_to_file("https://example.invalid/model", "file")
        return serialization

    def test_fixed_allowlist_and_high_profile_check_all_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(Path(directory), high=True,
                                 unknown=["demucs.htdemucs.HTDemucs", "fractions.Fraction"])
            self.assertEqual(result.get_unsafe_globals_in_checkpoint.call_count, 3)

    def test_unknown_pickle_global_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(SystemExit, "Nicht freigegebene"):
                self.invoke(Path(directory), unknown=["untrusted.execute"])

    def test_disabling_safe_loading_is_rejected(self):
        for value in ("1", "YES", "true", "y"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(SystemExit, "Unsichere"):
                    self.invoke(Path(directory), unsafe_env=value)

    def test_missing_high_weight_cannot_trigger_download(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(SystemExit, "kein automatischer Download"):
                self.invoke(Path(directory), high=True, missing=True)

    def test_old_pytorch_is_not_silently_downgraded_to_unsafe(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(SystemExit, "PyTorch >= 2.6"):
                self.invoke(Path(directory), old=True)


class BackendRuntimeTests(unittest.TestCase):
    def test_safe_runner_receives_exact_arguments_and_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, config = make_cdx_fixture(root)
            settings = json.loads(config.read_text())
            config.write_text(json.dumps({**settings, "runner": "safe-pytorch"}))
            source = root / "source with spaces.wav"
            output = root / "out"
            with mock.patch("cinematic_separation._run") as run, \
                    mock.patch("cinematic_separation._validated_wav", side_effect=lambda path, _: path):
                report = CdxSeparator(config, quality="high", timeout=45).separate(source, output)
            command = run.call_args.args[0]
            self.assertEqual(command[:4], [sys.executable, str(ROOT / "render/cdx_safe_inference.py"),
                                          "--repository", str(repo)])
            self.assertIn(str(source), command)
            self.assertIn("--high_quality", command)
            self.assertEqual(run.call_args.kwargs["timeout"], 45)
            self.assertEqual(report.provenance["runner"], "safe-pytorch")

    def test_invalid_runner_lock_and_timeouts_fail_before_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            _, config = make_cdx_fixture(Path(directory))
            settings = json.loads(config.read_text())
            for extra in ({"runner": "unknown"}, {"runner": []},
                          {"runtime_lock": "invalid"}, {"runtime_lock": []}):
                config.write_text(json.dumps({**settings, **extra}))
                with self.subTest(extra=extra), self.assertRaises(SeparationError):
                    CdxSeparator(config).ensure_ready()
            config.write_text(json.dumps(settings))
            for timeout in (0, -1, float("inf"), float("nan")):
                with self.subTest(timeout=timeout), self.assertRaises(SeparationError):
                    CdxSeparator(config, timeout=timeout).ensure_ready()

    def test_locked_runtime_mismatch_fails_before_model_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, config = make_cdx_fixture(root)
            config.write_text(json.dumps({**json.loads(config.read_text()), "runtime_lock": "b" * 64}))
            with mock.patch.object(runtime, "probe_runtime", return_value=ready_probe()), \
                    mock.patch("cinematic_separation._run") as run:
                with self.assertRaisesRegex(SeparationError, "runtime_lock"):
                    CdxSeparator(config).separate(root / "source.wav", root / "out")
                run.assert_not_called()
            self.assertFalse((root / "out").exists())

    def test_runtime_lock_is_checked_again_after_model_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, config = make_cdx_fixture(root)
            config.write_text(json.dumps({**json.loads(config.read_text()), "runtime_lock": "a" * 64}))
            with mock.patch.object(runtime, "probe_runtime", side_effect=[
                    ready_probe(), {**ready_probe(), "fingerprint": "b" * 64}]), \
                    mock.patch("cinematic_separation._run") as run:
                with self.assertRaisesRegex(SeparationError, "waehrend der Inferenz"):
                    CdxSeparator(config).separate(root / "source.wav", root / "out")
                run.assert_called_once()

    def test_registration_locks_runtime_and_refuses_missing_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, _ = make_cdx_fixture(root)
            output = root / "registered.json"
            command = ["register", "--repository", str(repo), "--output", str(output),
                       "--checkpoint-license", "test-fixture-only", "--verify-runtime"]
            with mock.patch.object(sys, "argv", command), mock.patch("sys.stdout", new_callable=io.StringIO), \
                    mock.patch.object(runtime, "probe_runtime", return_value=ready_probe()):
                cinematic_separation.main()
            settings = json.loads(output.read_text())
            self.assertEqual(settings["runner"], "safe-pytorch")
            self.assertEqual(settings["runtime_lock"], "a" * 64)
            missing_output = root / "not-created.json"
            command[4] = str(missing_output)
            broken = {**ready_probe(), "dependencies_ready": False, "missing_or_broken": ["torch"]}
            with mock.patch.object(sys, "argv", command), \
                    mock.patch.object(runtime, "probe_runtime", return_value=broken):
                with self.assertRaisesRegex(SystemExit, "torch"):
                    cinematic_separation.main()
            self.assertFalse(missing_output.exists())

    def test_real_subprocess_timeout_is_reported(self):
        with self.assertRaisesRegex(SeparationError, "Zeitlimit"):
            _run([sys.executable, "-c", "import time; time.sleep(2)"], "test", timeout=.05)

    def test_cli_exposes_explicit_verification_and_timeout(self):
        args = build_parser().parse_args(["doctor", "--cdx-config", "c.json", "--cdx-receipt", "r.json"])
        self.assertEqual(args.cdx_receipt, Path("r.json"))
        self.assertEqual(build_parser().parse_args(["decompose", "a.wav", "--inference-timeout", "45"]).inference_timeout, 45)


class ExcerptTests(unittest.TestCase):
    def test_time_range_preserves_source_and_exact_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            samples = np.repeat(np.array([.1, .2, .3], dtype=np.float32), 48_000)
            wavfile.write(source, 48_000, np.column_stack((samples, samples)))
            before = source.read_bytes()
            output = root / "excerpt.wav"
            _extract_wav(source, output, start_seconds=1, duration_seconds=1, encoding="pcm_f32le")
            rate, clipped = wavfile.read(output)
            self.assertEqual(rate, 48_000)
            self.assertEqual(clipped.shape, (48_000, 2))
            np.testing.assert_allclose(clipped, .2)
            self.assertEqual(source.read_bytes(), before)

    def test_invalid_ranges_do_not_start_ffmpeg(self):
        for options in ({"start_seconds": -1}, {"start_seconds": float("nan")},
                        {"duration_seconds": 0}, {"duration_seconds": float("inf")}):
            with self.subTest(options=options), mock.patch("video_music._run") as run:
                with self.assertRaises(VideoMusicError):
                    _extract_wav(Path("source.wav"), Path("out.wav"), **options)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

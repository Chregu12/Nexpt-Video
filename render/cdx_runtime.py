#!/usr/bin/env python3
"""Inspect a CDX runtime and record a bounded, opt-in real-inference smoke test.

Neither command installs packages, downloads weights, nor operates GarageBand.
A smoke receipt attests technical execution, not perceptual audio quality.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

from cinematic_separation import CdxSeparator, sha256
from music_separation import SeparationError


RUNTIME_MODULES = ("torch", "torchaudio", "demucs", "librosa", "soundfile", "numpy", "scipy")
INTEGRATION_FILES = ("cdx_runtime.py", "cdx_safe_inference.py", "cinematic_separation.py",
                     "audio_decomposition.py", "music_separation.py", "video_music.py")
PROBE_CODE = r'''
import importlib, importlib.metadata, json, platform, sys
modules = {}
for name in ("torch", "torchaudio", "demucs", "librosa", "soundfile", "numpy", "scipy"):
    try:
        module = importlib.import_module(name)
        if name == "librosa":
            getattr(module, "load")  # exercise its lazy dependency imports
        modules[name] = {"imported": True, "version": importlib.metadata.version(name)}
    except Exception as exc:
        modules[name] = {"imported": False, "error": str(exc)[-600:]}
torch = sys.modules.get("torch")
print("NEXPT_RUNTIME=" + json.dumps({
    "python": platform.python_version(), "implementation": platform.python_implementation(),
    "system": platform.system(), "machine": platform.machine(),
    "modules": modules,
    "packages": sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
                       if d.metadata.get("Name")),
    "cuda_available": bool(torch and torch.cuda.is_available()),
    "restricted_checkpoint_loader": bool(torch and hasattr(torch.serialization, "get_unsafe_globals_in_checkpoint")),
}))
'''


def probe_runtime(python: str | Path, *, timeout: float = 30) -> dict[str, Any]:
    interpreter = Path(python).expanduser().absolute()
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise SeparationError(f"CDX-Python fehlt oder ist nicht ausfuehrbar: {interpreter}")
    if not math.isfinite(timeout) or timeout <= 0:
        raise SeparationError("Runtime-Probe braucht ein positives Zeitlimit")
    try:
        result = subprocess.run([str(interpreter), "-c", PROBE_CODE],
                                capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SeparationError(f"CDX-Runtime-Probe fehlgeschlagen: {exc}") from exc
    records = [line.removeprefix("NEXPT_RUNTIME=") for line in result.stdout.splitlines()
               if line.startswith("NEXPT_RUNTIME=")]
    if result.returncode or len(records) != 1:
        raise SeparationError("CDX-Runtime-Probe lieferte keinen eindeutigen Bericht: "
                              + result.stderr[-1200:])
    try:
        payload = json.loads(records[0])
        modules = payload["modules"]
        if not isinstance(modules, dict) or any(
                not isinstance(modules.get(name), dict)
                or type(modules[name].get("imported")) is not bool for name in RUNTIME_MODULES):
            raise ValueError("missing or invalid module import status")
        ready = all(modules[name]["imported"] is True for name in RUNTIME_MODULES)
    except (ValueError, KeyError, TypeError) as exc:
        raise SeparationError("Ungueltiger CDX-Runtime-Bericht") from exc
    identity = {**payload, "executable_sha256": sha256(interpreter)}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return {
        **identity, "interpreter": str(interpreter), "fingerprint": fingerprint,
        "dependencies_ready": ready, "runtime_verified": False,
        "missing_or_broken": [name for name in RUNTIME_MODULES if not modules[name]["imported"]],
        "note": "Imports were exercised, but no model checkpoint was loaded.",
    }


def _relocate(value: Any, old: Path, new: Path) -> Any:
    if isinstance(value, str) and value.startswith(str(old) + os.sep):
        return str(new) + value[len(str(old)):]
    if isinstance(value, dict):
        return {key: _relocate(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_relocate(item, old, new) for item in value]
    return value


def _integration_identity() -> dict[str, str]:
    return {name: sha256(Path(__file__).with_name(name)) for name in INTEGRATION_FILES}


def smoke_test(source: Path, *, config: Path, output_dir: Path,
               start_seconds: float = 0, seconds: float = 5,
               audio_stream: int = 0, quality: str = "standard", device: str = "cpu",
               timeout: float = 600, maximum_residual_ratio: float = .1) -> dict[str, Any]:
    from audio_decomposition import decompose
    from video_music import _extract_wav, _write_json_atomic

    source = source.expanduser().resolve()
    config = config.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not source.is_file():
        raise SeparationError(f"Quelldatei fehlt: {source}")
    if output_dir.exists():
        raise SeparationError(f"Smoke-Test-Ausgabe existiert bereits: {output_dir}")
    if not math.isfinite(seconds) or not 1 <= seconds <= 30:
        raise SeparationError("Ein Smoke-Test muss zwischen 1 und 30 Sekunden lang sein")
    if not math.isfinite(start_seconds) or start_seconds < 0:
        raise SeparationError("Startzeit muss endlich und nicht negativ sein")
    if not math.isfinite(timeout) or not 1 <= timeout <= 3600:
        raise SeparationError("Inferenz-Zeitlimit muss zwischen 1 und 3600 Sekunden liegen")
    if audio_stream < 0:
        raise SeparationError("Audiospur darf nicht negativ sein")
    if not math.isfinite(maximum_residual_ratio) or not 0 <= maximum_residual_ratio <= 1:
        raise SeparationError("maximum_residual_ratio muss zwischen 0 und 1 liegen")
    backend = CdxSeparator(config, quality=quality, device=device, timeout=timeout)
    backend.ensure_ready()
    config_hash = sha256(config)
    original_hash = sha256(source)
    integration = _integration_identity()
    runtime = probe_runtime(backend.settings["python"])
    if not runtime["dependencies_ready"]:
        raise SeparationError("CDX-Runtime fehlt/ist defekt: " + ", ".join(runtime["missing_or_broken"]))
    if device == "cuda" and not runtime["cuda_available"]:
        raise SeparationError("CUDA wurde verlangt, ist aber nicht verfuegbar")
    if backend.settings.get("runner") == "safe-pytorch" and not runtime["restricted_checkpoint_loader"]:
        raise SeparationError("Safe CDX runner braucht PyTorch >= 2.6")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".cdx-smoke-", dir=output_dir.parent) as temporary:
        stage = Path(temporary)
        bundle = stage / "bundle"
        bundle.mkdir()
        excerpt = bundle / "source-excerpt.wav"
        _extract_wav(source, excerpt, audio_stream=audio_stream, sample_rate=44_100,
                     encoding="pcm_f32le", start_seconds=start_seconds, duration_seconds=seconds)
        from scipy.io import wavfile
        excerpt_rate, excerpt_samples = wavfile.read(excerpt)
        actual_seconds = len(excerpt_samples) / excerpt_rate
        if not 1 <= actual_seconds <= seconds + 1 / excerpt_rate:
            raise SeparationError("Audioausschnitt ist zu kurz oder laenger als angefordert")
        decomposition = decompose(
            excerpt, output_dir=bundle / "demixing", quality=quality,
            cdx_config=config, device=device, strict=True,
            maximum_residual_ratio=maximum_residual_ratio, inference_timeout=timeout)
        # No success receipt survives changes to configuration, input or runtime
        # during the test. Wave files are also verified again when reusing it.
        if sha256(config) != config_hash or sha256(source) != original_hash:
            raise SeparationError("Konfiguration oder Quelle hat sich waehrend des Smoke-Tests geaendert")
        if probe_runtime(backend.settings["python"])["fingerprint"] != runtime["fingerprint"]:
            raise SeparationError("CDX-Runtime hat sich waehrend des Smoke-Tests geaendert")
        if _integration_identity() != integration:
            raise SeparationError("NEXPT-Code hat sich waehrend des Smoke-Tests geaendert")
        decomposition = _relocate(decomposition, bundle, output_dir)
        manifest = bundle / "demixing" / "manifest.json"
        _write_json_atomic(manifest, decomposition, overwrite=True)
        receipt = {
            "schema_version": 1, "kind": "cdx-inference-smoke", "status": "passed",
            "runtime_verified": True, "model_accuracy_verified": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "quality": quality, "device": device,
            "config": {"path": str(config), "sha256": config_hash},
            "source": {"path": str(source), "sha256": original_hash,
                       "start_seconds": start_seconds, "requested_seconds": seconds,
                       "actual_seconds": actual_seconds,
                       "audio_stream": audio_stream},
            "runtime": runtime, "integration_sha256": integration,
            "processing": decomposition["processing"],
            "mix_consistency": decomposition["mix_consistency"],
            "artifacts": {
                "excerpt": {"path": str(output_dir / excerpt.name), "sha256": sha256(excerpt)},
                "decomposition_manifest": {"path": str(output_dir / "demixing" / "manifest.json"),
                                           "sha256": sha256(manifest)},
                **decomposition["outputs"],
            },
            "receipt": str(output_dir / "smoke-result.json"),
            "limitations": ["Technical model execution only; listening review remains necessary.",
                            "This is a local integrity receipt, not a signed external attestation."],
        }
        _write_json_atomic(bundle / "smoke-result.json", receipt, overwrite=False)
        if output_dir.exists():
            raise SeparationError("Smoke-Test-Ziel wurde zwischenzeitlich angelegt")
        os.rename(bundle, output_dir)
    return receipt


def verify_receipt(receipt_path: Path, *, config: Path, device: str | None = None,
                   quality: str | None = None) -> dict[str, Any]:
    """Explicitly recheck a local receipt. No global 'ready' cache or auto trust."""
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (receipt.get("schema_version") != 1 or receipt.get("kind") != "cdx-inference-smoke"
                or receipt.get("status") != "passed" or receipt.get("runtime_verified") is not True
                or receipt.get("model_accuracy_verified") is not False
                or receipt["mix_consistency"].get("passed") is not True):
            raise ValueError("kein erfolgreicher technischer Smoke-Test")
        if device is not None and receipt["device"] != device:
            raise ValueError("anderes Inferenz-Geraet")
        if quality is not None and receipt["quality"] != quality:
            raise ValueError("anderes Qualitaetsprofil")
        if receipt["integration_sha256"] != _integration_identity():
            raise ValueError("NEXPT-Integrationscode geaendert")
        if sha256(config) != receipt["config"]["sha256"]:
            raise ValueError("Konfiguration geaendert")
        backend = CdxSeparator(config, device=receipt["device"], quality=receipt["quality"])
        backend.ensure_ready()
        runtime = probe_runtime(backend.settings["python"])
        if not runtime["dependencies_ready"] or runtime["fingerprint"] != receipt["runtime"]["fingerprint"]:
            raise ValueError("Laufzeit geaendert oder nicht mehr funktionsfaehig")
        for artifact in (receipt["source"], *receipt["artifacts"].values()):
            if sha256(Path(artifact["path"])) != artifact["sha256"]:
                raise ValueError("Quelle oder Ergebnisdatei geaendert")
        required = {"excerpt", "decomposition_manifest", "soundtrack", "music", "dialogue", "sfx"}
        if set(receipt["artifacts"]) != required:
            raise ValueError("Artefakte fehlen")
        return {"runtime_verified": True, "model_accuracy_verified": False,
                "device": receipt["device"], "quality": receipt["quality"],
                "receipt": str(receipt_path.resolve()), "created_at": receipt["created_at"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, SeparationError) as exc:
        return {"runtime_verified": False, "model_accuracy_verified": False,
                "reason": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="import packages in the actual model interpreter")
    check.add_argument("--python", type=Path, default=Path(sys.executable))
    check.add_argument("--cdx-config", type=Path)
    smoke = commands.add_parser("smoke", help="explicitly run real inference on a short source excerpt")
    smoke.add_argument("source", type=Path)
    smoke.add_argument("--cdx-config", type=Path, required=True)
    smoke.add_argument("--output-dir", type=Path, required=True)
    smoke.add_argument("--start", type=float, default=0)
    smoke.add_argument("--seconds", type=float, default=5)
    smoke.add_argument("--audio-stream", type=int, default=0)
    smoke.add_argument("--quality", choices=("standard", "high"), default="standard")
    smoke.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    smoke.add_argument("--timeout", type=float, default=600)
    smoke.add_argument("--maximum-residual-ratio", type=float, default=.1)
    verify = commands.add_parser("verify", help="recheck an existing local smoke receipt")
    verify.add_argument("receipt", type=Path)
    verify.add_argument("--cdx-config", type=Path, required=True)
    verify.add_argument("--device", choices=("cpu", "cuda"))
    verify.add_argument("--quality", choices=("standard", "high"))
    args = parser.parse_args()
    try:
        if args.command == "check":
            python = args.python
            if args.cdx_config:
                backend = CdxSeparator(args.cdx_config)
                backend.ensure_ready()
                python = Path(backend.settings["python"])
            result = probe_runtime(python)
            success = result["dependencies_ready"]
        elif args.command == "verify":
            result = verify_receipt(args.receipt, config=args.cdx_config,
                                    device=args.device, quality=args.quality)
            success = result["runtime_verified"]
        else:
            result = smoke_test(args.source, config=args.cdx_config, output_dir=args.output_dir,
                                start_seconds=args.start, seconds=args.seconds,
                                audio_stream=args.audio_stream, quality=args.quality, device=args.device,
                                timeout=args.timeout, maximum_residual_ratio=args.maximum_residual_ratio)
            success = True
    except (RuntimeError, OSError, ValueError) as exc:
        result = {"status": "failed", "runtime_verified": False, "error": str(exc)}
        success = False
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

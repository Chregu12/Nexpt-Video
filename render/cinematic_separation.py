#!/usr/bin/env python3
"""Concrete local MVSEP-CDX23 integration. No models or media are uploaded.

Configuration records a local checkout and checkpoint hashes. The upstream
runner can download missing weights, so NEXPT verifies *every* required weight
before invoking it. Hashes establish local integrity, not model accuracy or
the publisher's authenticity. Only load checkpoints from trusted sources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from music_separation import SeparationError, SeparationResult, _run, _validated_wav


CDX_CONFIG_ENV = "NEXPT_CDX_CONFIG"
CDX_REVISION = "aaa75640d8fd68418948fe4cd2c2d263d042cbb9"
CDX_CHECKPOINTS = (
    "97d170e1-dbb4db15.th", "97d170e1-a778de4a.th", "97d170e1-e41a5468.th",
)
CDX_ROLES = {"music": "music", "dialogue": "dialog", "sfx": "effect"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repository: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *args], capture_output=True,
            text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SeparationError(f"CDX Git-Pruefung fehlgeschlagen: {exc}") from exc
    if result.returncode:
        raise SeparationError("CDX braucht einen lokalen Git-Checkout.")
    return result.stdout.strip()


class CdxSeparator:
    name = "cdx"

    def __init__(self, config: str | Path | None = None, *,
                 quality: str = "standard", device: str = "cpu") -> None:
        value = config or os.environ.get(CDX_CONFIG_ENV)
        self.config_path = Path(value).expanduser().resolve() if value else None
        self.quality = quality
        self.device = device
        self.settings: dict[str, Any] = {}

    def ensure_ready(self, *, verify_hashes: bool = True) -> None:
        if self.quality not in {"standard", "high"}:
            raise SeparationError(f"Unbekannte CDX-Qualitaet: {self.quality}")
        if self.device not in {"cpu", "cuda"}:
            raise SeparationError("CDX23 unterstuetzt cpu/cuda, nicht mps.")
        if self.config_path is None or not self.config_path.is_file():
            raise SeparationError(
                "CDX-Konfiguration fehlt. Setze NEXPT_CDX_CONFIG oder --cdx-config; "
                "siehe render/DECOMPOSITION.md.")
        try:
            settings = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SeparationError("CDX-Konfiguration ist kein gueltiges JSON.") from exc
        required = ("repository", "python", "revision", "checkpoint_license")
        if (not isinstance(settings, dict) or settings.get("schema_version") != 1
                or any(not isinstance(settings.get(key), str) or not settings[key].strip()
                       for key in required)):
            raise SeparationError("CDX-Konfiguration braucht schema_version 1, repository, "
                                  "python, revision und checkpoint_license.")
        repo = Path(settings["repository"]).expanduser()
        python = Path(settings["python"]).expanduser()
        if not repo.is_absolute() or not python.is_absolute():
            raise SeparationError("CDX repository und python muessen absolute Pfade sein.")
        if not (repo / "inference.py").is_file():
            raise SeparationError("CDX inference.py fehlt.")
        if not python.is_file() or not os.access(python, os.X_OK):
            raise SeparationError("Der konfigurierte CDX-Python ist nicht ausfuehrbar.")
        if not re.fullmatch(r"[0-9a-f]{40}", settings["revision"]):
            raise SeparationError("CDX revision muss ein vollstaendiger Git-SHA sein.")
        if (_git(repo, "rev-parse", "HEAD") != settings["revision"]
                or _git(repo, "status", "--porcelain", "--untracked-files=no")):
            raise SeparationError("CDX-Checkout stimmt nicht mit der sauberen revision ueberein.")
        hashes = settings.get("checkpoint_sha256")
        needed = CDX_CHECKPOINTS if self.quality == "high" else CDX_CHECKPOINTS[:1]
        if not isinstance(hashes, dict):
            raise SeparationError("CDX checkpoint_sha256 muss ein Mapping sein.")
        for name in needed:
            expected = hashes.get(name)
            checkpoint = repo / "models" / name
            if (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected)
                    or not checkpoint.is_file() or checkpoint.stat().st_size == 0):
                raise SeparationError(f"CDX-Checkpoint oder SHA-256 fehlt: {name}")
            if verify_hashes and sha256(checkpoint) != expected.lower():
                raise SeparationError(f"CDX-Checkpoint SHA-256 stimmt nicht: {name}")
        self.settings = settings

    def separate(self, source_wav: Path, output_dir: Path) -> SeparationResult:
        self.ensure_ready()
        initial_settings = self.settings
        output_dir.mkdir(parents=True, exist_ok=True)
        if any(output_dir.iterdir()):
            raise SeparationError("CDX-Ausgabeverzeichnis muss leer sein (keine alten Stems).")
        repo = Path(self.settings["repository"])
        command = [self.settings["python"], str(repo / "inference.py"),
                   "--input_audio", str(source_wav.resolve()),
                   "--output_folder", str(output_dir.resolve())]
        if self.device == "cpu":
            command.append("--cpu")
        else:
            # Upstream otherwise silently falls back from CUDA to CPU.
            _run([self.settings["python"], "-c",
                  "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'"],
                 "CDX CUDA-Pruefung")
        if self.quality == "high":
            command.append("--high_quality")
        _run(command, "CDX23 Filmton-Trennung")
        # Keep the provenance truthful if an external process changed either
        # checkout or weights while inference was in progress.
        self.ensure_ready()
        if self.settings != initial_settings:
            raise SeparationError("CDX-Konfiguration wurde waehrend der Inferenz geaendert.")
        stems = {
            role: _validated_wav(output_dir / f"{source_wav.stem}_{suffix}.wav", f"CDX {role}")
            for role, suffix in CDX_ROLES.items()
        }
        needed = CDX_CHECKPOINTS if self.quality == "high" else CDX_CHECKPOINTS[:1]
        provenance = {
            "repository": str(repo), "revision": self.settings["revision"],
            "checkpoint_sha256": {name: sha256(repo / "models" / name) for name in needed},
            "checkpoint_license": self.settings["checkpoint_license"],
            "integrity": "matched locally configured checkpoint hashes",
        }
        warnings = ["Estimated film stems require listening review; music may contain singing."]
        if self.settings["revision"] != CDX_REVISION:
            warnings.append("CDX checkout differs from NEXPT's documented integration revision.")
        return SeparationResult(
            backend=self.name, primary_path=stems["music"],
            model="mvsep-cdx23-dnr", version=self.settings["revision"],
            stems=stems, provenance=provenance, task="cinematic", primary_stem="music",
            warnings=tuple(warnings))


def cdx_status(config: str | Path | None = None) -> dict[str, Any]:
    backend = CdxSeparator(config)
    try:
        backend.ensure_ready(verify_hashes=False)
    except SeparationError as exc:
        return {"configured": False, "runtime_verified": False, "reason": str(exc)}
    return {"configured": True, "runtime_verified": False,
            "config": str(backend.config_path), "revision": backend.settings["revision"],
            "note": "Checkpoint hashes and actual inference are checked at run time."}


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a trusted local CDX checkout and weights")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--checkpoint-license", required=True,
                        help="license for the weights you have reviewed (not inferred from code)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repository.expanduser().resolve()
    try:
        if not (repo / "inference.py").is_file():
            raise SeparationError("CDX inference.py fehlt.")
        if _git(repo, "status", "--porcelain", "--untracked-files=no"):
            raise SeparationError("CDX-Checkout hat uncommittete Aenderungen.")
        hashes = {name: sha256(repo / "models" / name) for name in CDX_CHECKPOINTS
                  if (repo / "models" / name).is_file()}
        if CDX_CHECKPOINTS[0] not in hashes:
            raise SeparationError("Mindestens der Standard-Checkpoint muss lokal vorhanden sein.")
        payload = {
            "schema_version": 1, "repository": str(repo),
            "python": str(args.python.expanduser().absolute()),
            "revision": _git(repo, "rev-parse", "HEAD"),
            "checkpoint_license": args.checkpoint_license,
            "checkpoint_sha256": hashes,
        }
        # Exclusive creation protects an existing config or source file.
        with args.output.expanduser().open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
    except (SeparationError, OSError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(json.dumps({"config": str(args.output.absolute()),
                      "checkpoint_count": len(hashes), "model_accuracy_verified": False}))


if __name__ == "__main__":
    main()

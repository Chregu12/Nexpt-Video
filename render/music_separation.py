#!/usr/bin/env python3
"""Pluggable, auditable music-separation backends for NEXPT.

The module deliberately supports only explicit local backends.  It never
uploads reference audio and it never treats an estimated stem as an original
studio stem.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


DEMUCS_PACKAGE_PIN = "4.0.1"
DEMUCS_MODELS = {
    "standard": "htdemucs",
    "high": "htdemucs_ft",
}
ROFORMER_ENV = "NEXPT_ROFORMER_COMMAND"


class SeparationError(RuntimeError):
    """A requested separator is unavailable or produced invalid output."""


@dataclass(frozen=True)
class SeparationResult:
    """Validated files and provenance produced by one separation backend."""

    backend: str
    primary_path: Path
    model: str
    version: str | None
    stems: dict[str, Path] = field(default_factory=dict)
    provenance: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    task: str = "music"
    primary_stem: str = "no_vocals"

    def manifest(self) -> dict[str, Any]:
        return {
            "engine": self.backend,
            "version": self.version,
            "model": self.model,
            "task": self.task,
            "stem": self.primary_stem,
            "available_stems": sorted(self.stems),
            "provenance": self.provenance,
            "warnings": list(self.warnings),
        }


def _package_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def demucs_available() -> bool:
    return _package_available("demucs")


def demucs_version() -> str | None:
    if not demucs_available():
        return None
    try:
        return importlib.metadata.version("demucs")
    except importlib.metadata.PackageNotFoundError:
        return "installed"


def _resolve_command(command: str | Path | None) -> str | None:
    value = str(command) if command else os.environ.get(ROFORMER_ENV)
    if not value:
        return None
    resolved = shutil.which(value)
    if resolved:
        return resolved
    path = Path(value).expanduser()
    if path.is_file() and os.access(path, os.X_OK):
        return str(path.resolve())
    return None


def roformer_command(command: str | Path | None = None) -> str | None:
    """Return a validated NEXPT RoFormer-adapter command, if configured."""

    return _resolve_command(command)


def backend_status(roformer: str | Path | None = None) -> dict[str, dict[str, Any]]:
    installed = demucs_version()
    adapter = roformer_command(roformer)
    return {
        "demucs": {
            "available": installed is not None,
            "version": installed,
            "required_version_for_high": DEMUCS_PACKAGE_PIN,
            "high_quality_pin_matches": installed == DEMUCS_PACKAGE_PIN,
            "models": dict(DEMUCS_MODELS),
        },
        "roformer": {
            "available": adapter is not None,
            "command": adapter,
            "configuration": ROFORMER_ENV,
            "contract": (
                "Executable accepts --input PATH --output-dir DIR and writes "
                "instrumental.wav or no_vocals.wav. Optional provenance.json "
                "can attest model/checkpoint/license. Model weights are not bundled."
            ),
        },
    }


def _run(command: list[str], label: str, *, timeout: float | None = None) -> None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SeparationError(f"{label} hat das Zeitlimit von {timeout}s ueberschritten.") from exc
    except OSError as exc:
        raise SeparationError(f"{label} konnte nicht gestartet werden: {exc}") from exc
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[-2000:]
        raise SeparationError(
            f"{label} ist fehlgeschlagen: {detail or 'unbekannter Fehler'}"
        )


def _validated_wav(path: Path, label: str) -> Path:
    if not path.is_file() or path.stat().st_size <= 44:
        raise SeparationError(f"{label} fehlt oder ist keine gueltige WAV-Datei: {path}")
    # Checking file size alone accepts corrupt files and model NaNs as audio.
    from scipy.io import wavfile
    import numpy as np

    try:
        rate, samples = wavfile.read(path)
    except (OSError, ValueError, EOFError) as exc:
        raise SeparationError(f"{label} ist keine lesbare WAV-Datei: {path}") from exc
    if (rate <= 0 or samples.size == 0 or samples.ndim not in (1, 2)
            or (samples.ndim == 2 and samples.shape[1] not in (1, 2))
            or not np.isfinite(samples).all()):
        raise SeparationError(f"{label} enthaelt ungueltige Audiodaten: {path}")
    return path.resolve()


class DemucsSeparator:
    name = "demucs"

    def __init__(self, *, quality: str, model: str | None, device: str,
                 task: str = "music") -> None:
        if task not in {"music", "instruments"}:
            raise SeparationError(f"Demucs unterstuetzt diese Aufgabe nicht: {task}")
        self.task = task
        self.quality = quality
        self.model = model or ("htdemucs_6s" if task == "instruments" else DEMUCS_MODELS[quality])
        self.device = device

    def ensure_ready(self) -> None:
        version = demucs_version()
        if version is None:
            raise SeparationError(
                "Der Demucs-Separator fehlt. Installiere "
                "garageband/requirements-transcription.txt."
            )
        if self.quality == "high" and version != DEMUCS_PACKAGE_PIN:
            raise SeparationError(
                "--quality high verlangt die reproduzierbare Demucs-Version "
                f"{DEMUCS_PACKAGE_PIN}; installiert ist {version}."
            )

    def separate(self, source_wav: Path, output_dir: Path) -> SeparationResult:
        self.ensure_ready()
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "demucs",
            "-n",
            self.model,
            "-d",
            self.device,
            "-j",
            "1",
            "--float32",
            "-o",
            str(output_dir),
            str(source_wav),
        ]
        if self.task == "music":
            command[command.index("-o"):command.index("-o")] = ["--two-stems", "vocals"]
        _run(command, "Demucs-Musikisolation")
        primary_stem = "no_vocals" if self.task == "music" else "drums"
        candidates = sorted(output_dir.rglob(f"{primary_stem}.wav"))
        if len(candidates) != 1:
            raise SeparationError(
                f"Demucs muss genau eine {primary_stem}.wav erzeugen; "
                f"gefunden wurden {len(candidates)}."
            )
        primary = _validated_wav(candidates[0], f"Demucs {primary_stem}")
        stems = {primary_stem: primary}
        roles = ("vocals",) if self.task == "music" else ("bass", "other", "vocals", "piano", "guitar")
        for role in roles:
            path = primary.parent / f"{role}.wav"
            required = self.task == "instruments" and (
                role in {"bass", "other", "vocals"} or self.model == "htdemucs_6s")
            if path.is_file() or required:
                stems[role] = _validated_wav(path, f"Demucs {role}")
        warnings: tuple[str, ...] = ()
        version = demucs_version()
        if self.quality != "high" and version != DEMUCS_PACKAGE_PIN:
            warnings = (
                f"Demucs {version} weicht von der getesteten Version "
                f"{DEMUCS_PACKAGE_PIN} ab.",
            )
        return SeparationResult(
            backend=self.name,
            primary_path=primary,
            model=self.model,
            version=version,
            stems=stems,
            warnings=warnings,
            task=self.task,
            primary_stem=primary_stem,
        )


class RoFormerSeparator:
    """Adapter for a user-provided local BS/Mel-RoFormer implementation.

    RoFormer projects expose incompatible Python and command-line APIs.  NEXPT
    therefore defines a tiny stable adapter contract instead of importing an
    arbitrary repository and guessing its model or checkpoint.
    """

    name = "roformer"

    def __init__(self, command: str | Path | None) -> None:
        self.command = roformer_command(command)

    def ensure_ready(self) -> None:
        if not self.command:
            raise SeparationError(
                "Der RoFormer-Adapter fehlt. Setze NEXPT_ROFORMER_COMMAND auf eine "
                "ausfuehrbare Datei mit dem dokumentierten Adaptervertrag."
            )

    def separate(self, source_wav: Path, output_dir: Path) -> SeparationResult:
        self.ensure_ready()
        output_dir.mkdir(parents=True, exist_ok=True)
        _run(
            [
                str(self.command),
                "--input",
                str(source_wav),
                "--output-dir",
                str(output_dir),
            ],
            "RoFormer-Musikisolation",
        )
        candidates = [
            path
            for name in ("instrumental.wav", "no_vocals.wav")
            if (path := output_dir / name).is_file()
        ]
        if len(candidates) != 1:
            raise SeparationError(
                "Der RoFormer-Adapter muss genau instrumental.wav oder "
                "no_vocals.wav in --output-dir schreiben."
            )
        primary = _validated_wav(candidates[0], "RoFormer instrumental")
        stems = {"no_vocals": primary}
        vocals = output_dir / "vocals.wav"
        if vocals.is_file():
            stems["vocals"] = _validated_wav(vocals, "RoFormer vocals")
        provenance_path = output_dir / "provenance.json"
        provenance: dict[str, str] | None = None
        if provenance_path.is_file():
            try:
                raw = json.loads(provenance_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SeparationError(
                    f"RoFormer provenance.json ist ungueltig: {exc}"
                ) from exc
            required = ("model", "version", "checkpoint_sha256", "license")
            if not isinstance(raw, dict) or any(
                not isinstance(raw.get(key), str) or not raw[key].strip()
                for key in required
            ):
                raise SeparationError(
                    "RoFormer provenance.json braucht model, version, "
                    "checkpoint_sha256 und license als nichtleere Strings."
                )
            if not re.fullmatch(r"[0-9a-fA-F]{64}", raw["checkpoint_sha256"]):
                raise SeparationError(
                    "RoFormer checkpoint_sha256 muss ein SHA-256-Hexwert sein."
                )
            provenance = {key: raw[key].strip() for key in required}
        warnings = (
            "Checkpoint, Lizenz und Modellversion sind nicht maschinenlesbar "
            "belegt; fuer high quality ist manuelle Pruefung erforderlich.",
        )
        if provenance is not None:
            warnings = ()
        return SeparationResult(
            backend=self.name,
            primary_path=primary,
            model=provenance["model"] if provenance else "adapter-defined",
            version=provenance["version"] if provenance else None,
            stems=stems,
            provenance=provenance,
            warnings=warnings,
        )


def select_separator(
    backend: str,
    *,
    quality: str,
    model: str | None,
    device: str,
    roformer: str | Path | None = None,
) -> DemucsSeparator | RoFormerSeparator:
    """Resolve one backend without silently changing the requested engine."""

    if quality not in DEMUCS_MODELS:
        raise SeparationError(f"Unbekannte Qualitaet: {quality}")
    if backend == "demucs":
        separator: DemucsSeparator | RoFormerSeparator = DemucsSeparator(
            quality=quality,
            model=model,
            device=device,
        )
    elif backend == "roformer":
        separator = RoFormerSeparator(roformer)
    elif backend == "auto":
        # Demucs is the pinned, tested baseline.  High quality can use the
        # explicit RoFormer adapter when the installed Demucs version misses
        # the pin; checkpoint provenance is evaluated by the quality gate.
        if quality == "high" and demucs_version() == DEMUCS_PACKAGE_PIN:
            separator = DemucsSeparator(quality=quality, model=model, device=device)
        elif quality == "high" and roformer_command(roformer):
            separator = RoFormerSeparator(roformer)
        elif demucs_available():
            separator = DemucsSeparator(quality=quality, model=model, device=device)
        elif roformer_command(roformer):
            separator = RoFormerSeparator(roformer)
        else:
            raise SeparationError(
                "Kein lokaler Musik-Separator ist bereit: Demucs fehlt und kein "
                "RoFormer-Adapter ist konfiguriert."
            )
    else:
        raise SeparationError(f"Unbekannter Separator: {backend}")
    separator.ensure_ready()
    return separator


def separate_instrument_stems(
    source: Path, output_dir: Path, *, backend: str = "auto",
    quality: str = "standard", model: str = "htdemucs_6s",
    device: str = "cpu", roformer: str | Path | None = None,
) -> tuple[dict[str, Path], dict[str, Any]]:
    """Shared GarageBand entry point; no-vocals output is never called drums.

    Only automatic, standard-quality operation may fall back to the input.
    Explicit engine requests and high-quality failures are always errors.
    """
    if backend not in {"auto", "demucs", "roformer", "off"}:
        raise ValueError(f"Unknown stem mode: {backend}")
    if quality not in DEMUCS_MODELS:
        raise SeparationError(f"Unbekannte Qualitaet: {quality}")
    if backend == "off":
        return {"mix": source}, {
            "requested": backend, "used": "off", "isolated_drums": False,
            "temporary_stems": False,
        }
    try:
        if backend == "roformer" or (
                backend == "auto" and not demucs_available() and roformer_command(roformer)):
            selected = RoFormerSeparator(roformer)
        else:
            selected = DemucsSeparator(
                quality=quality, model=model, device=device, task="instruments")
        # A fresh workspace prevents leftovers from a previous run satisfying
        # the output contract, even with GarageBand --keep-work.
        output_dir.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix="stems-", dir=output_dir))
        result = selected.separate(source, run_dir)
        if quality == "high" and result.backend == "roformer" and not result.provenance:
            raise SeparationError("RoFormer high braucht Checkpoint-Provenienz.")
    except SeparationError as exc:
        if backend != "auto" or quality == "high":
            raise
        return {"mix": source}, {
            "requested": backend, "used": "unavailable-dsp-fallback",
            "isolated_drums": False, "temporary_stems": False,
            "warnings": [str(exc)],
        }
    stems = result.stems if result.task == "instruments" else {"mix": result.primary_path}
    return stems, {
        **result.manifest(), "requested": backend, "used": result.backend,
        "device": device, "jobs": 1, "roles": sorted(stems),
        "isolated_drums": "drums" in stems, "temporary_stems": True,
    }

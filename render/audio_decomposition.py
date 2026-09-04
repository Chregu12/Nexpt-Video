#!/usr/bin/env python3
"""Transactional film-audio demixing into music, dialogue and effects.

The residual is *not* relabelled as sound effects. A small reconstruction
residual also does not prove perceptual separation quality: listening review
is always required until independently labelled benchmarks are available.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np
from scipy.io import wavfile

from cinematic_separation import CdxSeparator
from music_separation import SeparationError, _validated_wav


def _float_samples(samples: np.ndarray) -> np.ndarray:
    if samples.dtype.kind == "u":
        return (samples.astype(np.float64) - 128.0) / 128.0
    if samples.dtype.kind == "i":
        return samples.astype(np.float64) / float(2 ** (8 * samples.dtype.itemsize - 1))
    return samples.astype(np.float64)


def check_stem_consistency(mix: Path, stems: dict[str, Path], *,
                           maximum_residual_ratio: float = .1) -> dict[str, Any]:
    """Check aligned WAVs and measure the unfixed source-minus-stem residual."""
    if (not math.isfinite(maximum_residual_ratio)
            or not 0 <= maximum_residual_ratio <= 1):
        raise SeparationError("maximum_residual_ratio muss zwischen 0 und 1 liegen.")
    if set(stems) != {"music", "dialogue", "sfx"}:
        raise SeparationError("Dreispur-Trennung braucht music, dialogue und sfx.")
    rate, source = wavfile.read(_validated_wav(mix, "source mix"))
    source = _float_samples(source)
    remainder = source.copy()
    energies = {}
    for role, path in stems.items():
        stem_rate, samples = wavfile.read(_validated_wav(path, role))
        if stem_rate != rate or samples.shape != source.shape:
            raise SeparationError(f"{role}: Samplerate, Laenge oder Kanaele stimmen nicht mit dem Mix ueberein.")
        values = _float_samples(samples)
        remainder -= values
        energies[role] = round(float(np.sqrt(np.mean(values * values))), 9)
    source_rms = float(np.sqrt(np.mean(source * source)))
    residual_rms = float(np.sqrt(np.mean(remainder * remainder)))
    ratio = residual_rms / max(source_rms, 1e-12)
    return {
        "sample_rate": int(rate), "frames": len(source),
        "channels": 1 if source.ndim == 1 else source.shape[1],
        "source_rms": round(source_rms, 9), "stem_rms": energies,
        "residual_rms": round(residual_rms, 9),
        "residual_to_mix_rms_ratio": round(ratio, 9),
        "maximum_residual_ratio": maximum_residual_ratio,
        "passed": ratio <= maximum_residual_ratio,
        "perceptual_separation_verified": False,
        "residual_redistributed": False,
    }


def decompose(source: Path, *, output_dir: Path | None = None,
              audio_stream: int = 0, sample_rate: int = 48_000,
              quality: str = "standard", cdx_config: Path | None = None,
              device: str = "cpu", maximum_residual_ratio: float = .1,
              strict: bool = False, vad: str = "off",
              inference_timeout: float | None = None) -> dict[str, Any]:
    # Lazy import keeps video_music's extraction helpers reusable without an
    # eager circular import when the CLI dispatches into this module.
    from video_music import (
        OUT, VideoMusicError, _extract_wav, _next_commands, _write_json_atomic,
        file_sha256, probe_media, slugify, _analyze_segments,
    )

    source = source.expanduser().resolve()
    destination = (output_dir or OUT / f"{slugify(source.stem)}-decomposition").expanduser().resolve()
    if not source.is_file():
        raise VideoMusicError(f"Quelldatei fehlt: {source}")
    # A bundle is immutable once published. A rerun needs a new directory;
    # there is no recursive deletion or partial overwrite of user artifacts.
    if destination.exists():
        raise VideoMusicError(f"Ausgabeverzeichnis existiert bereits: {destination}")
    if quality not in {"standard", "high"}:
        raise VideoMusicError(f"Unbekannte Qualitaet: {quality}")
    if audio_stream < 0 or not 8_000 <= sample_rate <= 192_000:
        raise VideoMusicError("Ungueltige Audiospur oder Samplerate")
    if (not math.isfinite(maximum_residual_ratio)
            or not 0 <= maximum_residual_ratio <= 1):
        raise VideoMusicError("--maximum-residual-ratio muss zwischen 0 und 1 liegen")
    if vad not in {"auto", "silero", "heuristic", "off"}:
        raise VideoMusicError(f"Unbekannte VAD-Engine: {vad}")
    backend = CdxSeparator(cdx_config, quality=quality, device=device,
                           timeout=inference_timeout)
    try:
        backend.ensure_ready()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".decomposition-", dir=destination.parent) as temporary:
            work = Path(temporary)
            bundle = work / "bundle"
            bundle.mkdir()
            # CDX23's published inference works at 44.1 kHz. Retain a decoded
            # full mix for A/B and compute integrity on the final sample grid.
            model_mix = work / "source.wav"
            original = probe_media(source)
            source_hash = file_sha256(source)
            _extract_wav(source, model_mix, audio_stream=audio_stream, sample_rate=44_100,
                         encoding="pcm_f32le")
            result = backend.separate(model_mix, work / "separated")
            _extract_wav(model_mix, bundle / "soundtrack.wav", sample_rate=sample_rate,
                         encoding="pcm_f32le")
            stems = {}
            for role in ("music", "dialogue", "sfx"):
                if role not in result.stems:
                    raise SeparationError(f"Separator hat keine {role}-Spur geliefert.")
                stems[role] = bundle / f"{role}.wav"
                _extract_wav(result.stems[role], stems[role], sample_rate=sample_rate,
                             encoding="pcm_f32le")
            consistency = check_stem_consistency(
                bundle / "soundtrack.wav", stems,
                maximum_residual_ratio=maximum_residual_ratio)
            if strict and not consistency["passed"]:
                raise SeparationError(
                    "Dreispur-Trennung verfehlt das Mix-Consistency-Gate: "
                    f"Rest/Mix-RMS={consistency['residual_to_mix_rms_ratio']:.6f}, "
                    f"Grenzwert={maximum_residual_ratio:.6f}.")
            segment_report = None
            if vad != "off":
                segment_report, _ = _analyze_segments(
                    stems["music"], bundle / "music.segments.json", vad=vad,
                    segment_seconds=1.0, segment_hop=.5, overwrite=False)
                segment_report["path"] = str(destination / "music.segments.json")
            outputs = {}
            for role in ("soundtrack", "music", "dialogue", "sfx"):
                path = bundle / f"{role}.wav"
                outputs[role] = {
                    "path": str(destination / path.name), "sha256": file_sha256(path),
                    "size_bytes": path.stat().st_size,
                    "estimated": role != "soundtrack",
                }
            if file_sha256(source) != source_hash:
                raise SeparationError("Quelldatei wurde waehrend der Verarbeitung geaendert.")
            manifest = {
                "schema_version": 1, "mode": "cinematic-decomposition",
                "status": "review_required", "quality": quality,
                "source": {"path": str(source), "sha256": source_hash,
                           "selected_audio_stream": audio_stream, "media": original},
                "outputs": outputs, "processing": result.manifest(),
                "mix_consistency": consistency,
                "segment_analysis": segment_report,
                "quality_gate": {
                    "status": "review_required", "technical_passed": consistency["passed"],
                    "listening_review_required": True,
                    "reason": "Mixture consistency does not measure cross-stem leakage.",
                },
                "limitations": [
                    "Estimated stems, not the original studio multitrack.",
                    "Music may still contain singing; CDX dialogue is not a vocals stem.",
                    "Speech/SFX leakage and separation artefacts require listening review.",
                ],
                "one_to_one_music_stem_claim": False,
                "next_commands": _next_commands(
                    destination / "music.wav", destination / "music.reference-profile.json"),
                "manifest": str(destination / "manifest.json"),
            }
            _write_json_atomic(bundle / "manifest.json", manifest, overwrite=False)
            if destination.exists():
                raise VideoMusicError(f"Ausgabeverzeichnis wurde zwischenzeitlich angelegt: {destination}")
            os.rename(bundle, destination)
        return manifest
    except SeparationError as exc:
        raise VideoMusicError(str(exc)) from exc

#!/usr/bin/env python3
"""Extract a verified soundtrack or an estimated music bed from local media.

The ``soundtrack`` mode decodes one audio stream without changing its musical
content.  It still contains dialogue and sound effects.  The ``music`` mode
uses a selected local separator to estimate a no-vocals mix; that result is
useful as a reference, but it is not the original studio music stem.

Examples::

    python3 render/video_music.py doctor
    python3 render/video_music.py extract film.mp4 --mode soundtrack
    python3 render/video_music.py extract film.mp4 --mode music --quality high --analyze
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from audio_segmentation import (  # type: ignore
    SegmentationError,
    analyze_segments,
    silero_available,
    speech_backend_status,
)
from music_separation import (  # type: ignore
    DEMUCS_PACKAGE_PIN,
    SeparationError,
    backend_status,
    select_separator,
)


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "video-music"
SCHEMA_VERSION = 2
DEFAULT_SAMPLE_RATE = 48_000


class VideoMusicError(RuntimeError):
    """The requested media operation could not be completed safely."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug or "video"


def _project_ffmpeg_fallback() -> str | None:
    try:
        from audio_common import FFMPEG  # type: ignore
    except (ImportError, OSError):
        return None
    return str(FFMPEG) if FFMPEG else None


def executable(name: str, *, required: bool = True) -> str | None:
    configured = os.environ.get(name.upper())
    candidates = [configured, shutil.which(name)]
    if name == "ffmpeg":
        candidates.append(_project_ffmpeg_fallback())
    elif name == "ffprobe":
        ffmpeg = executable("ffmpeg", required=False)
        if ffmpeg:
            candidates.append(str(Path(ffmpeg).with_name("ffprobe")))

    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    if required:
        raise VideoMusicError(
            f"{name} wurde nicht gefunden. Installiere ffmpeg oder setze "
            f"{name.upper()} auf die ausfuehrbare Datei."
        )
    return None


def _run(command: list[str], label: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise VideoMusicError(f"{label} konnte nicht gestartet werden: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise VideoMusicError(f"{label} ist fehlgeschlagen: {detail or 'unbekannter Fehler'}")
    return result


def probe_media(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise VideoMusicError(f"Quelldatei fehlt: {resolved}")
    ffprobe = executable("ffprobe")
    result = _run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration,size,bit_rate,format_name:"
                "stream=index,codec_type,codec_name,sample_rate,channels,"
                "channel_layout,duration,bit_rate"
            ),
            "-of",
            "json",
            str(resolved),
        ],
        "ffprobe",
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VideoMusicError(f"ffprobe lieferte ungueltiges JSON: {exc}") from exc

    streams = payload.get("streams") or []
    audio_streams = []
    for ordinal, stream in enumerate(
        row for row in streams if row.get("codec_type") == "audio"
    ):
        audio_streams.append(
            {
                "ordinal": ordinal,
                "index": int(stream.get("index", ordinal)),
                "codec": stream.get("codec_name"),
                "sample_rate": int(stream.get("sample_rate") or 0),
                "channels": int(stream.get("channels") or 0),
                "channel_layout": stream.get("channel_layout"),
                "duration_seconds": _float_or_zero(stream.get("duration")),
                "bit_rate": int(stream.get("bit_rate") or 0),
            }
        )
    video_streams = [row for row in streams if row.get("codec_type") == "video"]
    media_format = payload.get("format") or {}
    return {
        "container": media_format.get("format_name"),
        "duration_seconds": _float_or_zero(media_format.get("duration")),
        "size_bytes": int(media_format.get("size") or resolved.stat().st_size),
        "bit_rate": int(media_format.get("bit_rate") or 0),
        "audio_streams": audio_streams,
        "video_stream_count": len(video_streams),
    }


def _float_or_zero(value: Any) -> float:
    try:
        return round(float(value or 0.0), 6)
    except (TypeError, ValueError):
        return 0.0


def _validate_output(source: Path, output: Path, *, overwrite: bool) -> None:
    if output.suffix.lower() != ".wav":
        raise VideoMusicError("Die Ausgabe muss eine .wav-Datei sein")
    if source.resolve() == output.resolve():
        raise VideoMusicError("Quelldatei und Ausgabe duerfen nicht identisch sein")
    if output.exists() and not overwrite:
        raise VideoMusicError(
            f"Ausgabe existiert bereits: {output}. Nutze --overwrite nur bewusst."
        )


def _extract_wav(
    source: Path,
    output: Path,
    *,
    audio_stream: int = 0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    overwrite: bool = False,
    encoding: str = "pcm_s24le",
    start_seconds: float = 0.0,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if audio_stream < 0:
        raise VideoMusicError("--audio-stream darf nicht negativ sein")
    if not 8_000 <= sample_rate <= 192_000:
        raise VideoMusicError("--sample-rate muss zwischen 8000 und 192000 liegen")
    if encoding not in {"pcm_s24le", "pcm_f32le"}:
        raise VideoMusicError("Unbekanntes WAV-Encoding")
    if not math.isfinite(start_seconds) or start_seconds < 0:
        raise VideoMusicError("start_seconds muss endlich und nicht negativ sein")
    if duration_seconds is not None and (
            not math.isfinite(duration_seconds) or duration_seconds <= 0):
        raise VideoMusicError("duration_seconds muss endlich und positiv sein")
    _validate_output(source, output, overwrite=overwrite)
    media = probe_media(source)
    if not media["audio_streams"]:
        raise VideoMusicError(f"Die Datei enthaelt keine Audiospur: {source}")
    if audio_stream >= len(media["audio_streams"]):
        raise VideoMusicError(
            f"Audiospur {audio_stream} fehlt; vorhanden sind "
            f"0 bis {len(media['audio_streams']) - 1}"
        )

    ffmpeg = executable("ffmpeg")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp.wav",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        _run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-map",
                f"0:a:{audio_stream}",
                *(["-ss", str(start_seconds)] if start_seconds else []),
                *(["-t", str(duration_seconds)] if duration_seconds is not None else []),
                "-vn",
                "-sn",
                "-dn",
                "-ar",
                str(sample_rate),
                "-ac",
                "2",
                "-c:a",
                encoding,
                str(temporary),
            ],
            "Audio-Extraktion",
        )
        output_probe = probe_media(temporary)
        if not output_probe["audio_streams"] or temporary.stat().st_size <= 44:
            raise VideoMusicError("ffmpeg hat keine gueltige WAV-Ausgabe erzeugt")
        if output.exists() and not overwrite:
            raise VideoMusicError(f"Ausgabe wurde waehrend des Laufs angelegt: {output}")
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return media


def _isolate_music(
    source: Path,
    output: Path,
    *,
    audio_stream: int,
    sample_rate: int,
    model: str | None,
    device: str,
    quality: str = "standard",
    separator: str = "auto",
    roformer_command: str | Path | None = None,
    overwrite: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = output.expanduser().resolve()
    _validate_output(source.expanduser().resolve(), output, overwrite=overwrite)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        selected = select_separator(
            separator,
            quality=quality,
            model=model,
            device=device,
            roformer=roformer_command,
        )
    except SeparationError as exc:
        raise VideoMusicError(str(exc)) from exc
    with tempfile.TemporaryDirectory(
        dir=output.parent, prefix=f".{output.stem}.work-"
    ) as directory:
        work = Path(directory)
        mix = work / "source-mix.wav"
        source_media = _extract_wav(
            source,
            mix,
            audio_stream=audio_stream,
            sample_rate=sample_rate,
            overwrite=False,
        )
        try:
            separated = selected.separate(mix, work / "separated")
        except SeparationError as exc:
            raise VideoMusicError(str(exc)) from exc
        _extract_wav(
            separated.primary_path,
            output,
            audio_stream=0,
            sample_rate=sample_rate,
            overwrite=overwrite,
        )
    processing = separated.manifest()
    processing.update(
        {
            "requested_separator": separator,
            "quality": quality,
            "device": device,
            "jobs": 1,
        }
    )
    return source_media, processing


def _write_json_atomic(path: Path, payload: dict[str, Any], *, overwrite: bool) -> None:
    path = path.expanduser().resolve()
    if path.exists() and not overwrite:
        raise VideoMusicError(
            f"Manifest oder Profil existiert bereits: {path}. Nutze --overwrite nur bewusst."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and not overwrite:
            raise VideoMusicError(f"Datei wurde waehrend des Laufs angelegt: {path}")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def default_output(source: Path, mode: str) -> Path:
    suffix = "soundtrack" if mode == "soundtrack" else "music-estimate"
    return OUT / f"{slugify(source.stem)}-{suffix}.wav"


def default_segment_output(output: Path) -> Path:
    return output.with_suffix(".segments.json")


def _next_commands(output: Path, profile: Path) -> dict[str, list[str]]:
    return {
        "analyze_reference": [
            sys.executable,
            "render/reference_analyzer.py",
            str(output),
            "--output",
            str(profile),
        ],
        "compose_new_music": [
            sys.executable,
            "render/reference_pipeline.py",
            str(output),
            "--preview",
        ],
        "prepare_editable_garageband": [
            sys.executable,
            "garageband/workflow.py",
            str(output),
            "--quality",
            "high",
            "--prepare-dry-run",
        ],
    }


def _analyze(
    output: Path,
    profile_path: Path,
    *,
    bpm: float | None,
    downbeat: float | None,
    overwrite: bool,
) -> dict[str, Any]:
    if profile_path.exists() and not overwrite:
        raise VideoMusicError(f"Analyseprofil existiert bereits: {profile_path}")
    from reference_analyzer import analyze_reference  # type: ignore

    profile = analyze_reference(
        output,
        bpm_hint=bpm,
        downbeat_hint=downbeat,
        include_events=True,
        ebu=True,
    )
    _write_json_atomic(profile_path, profile, overwrite=overwrite)
    return {
        "path": str(profile_path.resolve()),
        "sha256": file_sha256(profile_path.resolve()),
        "bpm": profile.get("tempo", {}).get("bpm"),
        "event_count": profile.get("method", {}).get("event_count"),
    }


def _analyze_segments(
    output: Path,
    segment_path: Path,
    *,
    vad: str,
    segment_seconds: float,
    segment_hop: float,
    overwrite: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = analyze_segments(
            output,
            vad=vad,
            segment_seconds=segment_seconds,
            hop_seconds=segment_hop,
        )
    except SegmentationError as exc:
        raise VideoMusicError(str(exc)) from exc
    _write_json_atomic(segment_path, payload, overwrite=overwrite)
    report = {
        "path": str(segment_path.resolve()),
        "sha256": file_sha256(segment_path.resolve()),
        "vad": payload["analysis"]["vad"],
        "classifier": payload["analysis"]["classifier"],
        "summary": payload["summary"],
    }
    return report, payload


def _quality_gate(
    *,
    quality: str,
    mode: str,
    processing: dict[str, Any],
    segment_summary: dict[str, Any],
    vad_requested: str,
    vad_used: str,
) -> dict[str, Any]:
    checks = [
        {
            "name": "segment_map",
            "passed": True,
            "detail": "music/speech/SFX/silence probabilities were written",
        }
    ]
    high_vad_passed = vad_used == "silero"
    if quality == "high":
        checks.append(
            {
                "name": "trained_speech_detection",
                "passed": high_vad_passed,
                "detail": (
                    "Silero VAD timestamps available"
                    if high_vad_passed
                    else f"explicit lower-confidence VAD selected: {vad_requested}"
                ),
            }
        )
        checks.append(
            {
                "name": "segment_confidence",
                "passed": not bool(segment_summary.get("manual_review_required", True)),
                "detail": (
                    "all segment decisions meet the review threshold"
                    if not segment_summary.get("manual_review_required", True)
                    else "one or more music/speech/SFX decisions require manual review"
                ),
            }
        )
        if mode == "music":
            separator_verified = (
                processing.get("engine") == "demucs"
                and processing.get("version") == DEMUCS_PACKAGE_PIN
            ) or (
                processing.get("engine") == "roformer"
                and bool(processing.get("provenance"))
            )
            checks.append(
                {
                    "name": "separator_provenance",
                    "passed": separator_verified,
                    "detail": (
                        "separator package/checkpoint provenance verified"
                        if separator_verified
                        else "RoFormer checkpoint provenance is missing or unverified"
                    ),
                }
            )
    passed = all(bool(item["passed"]) for item in checks)
    return {
        "requested": quality,
        "status": "passed" if passed else "review_required",
        "checks": checks,
    }


def extract(
    source: Path,
    *,
    mode: str = "soundtrack",
    output: Path | None = None,
    manifest: Path | None = None,
    audio_stream: int = 0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    quality: str = "standard",
    separator: str = "auto",
    demucs_model: str | None = None,
    roformer_command: str | Path | None = None,
    device: str = "cpu",
    vad: str = "auto",
    segment_output: Path | None = None,
    segment_seconds: float = 1.0,
    segment_hop: float = 0.5,
    analyze: bool = False,
    profile_output: Path | None = None,
    bpm: float | None = None,
    downbeat: float | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if mode not in {"soundtrack", "music"}:
        raise VideoMusicError(f"Unbekannter Modus: {mode}")
    if quality not in {"standard", "high"}:
        raise VideoMusicError(f"Unbekannte Qualitaet: {quality}")
    if separator not in {"auto", "demucs", "roformer"}:
        raise VideoMusicError(f"Unbekannter Separator: {separator}")
    if device not in {"cpu", "cuda", "mps"}:
        raise VideoMusicError(f"Unbekanntes Demucs-Geraet: {device}")
    if vad not in {"auto", "silero", "heuristic", "off"}:
        raise VideoMusicError(f"Unbekannte VAD-Engine: {vad}")
    if vad == "silero" and not silero_available():
        raise VideoMusicError(
            "--vad silero wurde verlangt, aber Silero VAD ist nicht installiert."
        )
    if not 0.25 <= segment_seconds <= 10.0:
        raise VideoMusicError("--segment-seconds muss zwischen 0.25 und 10 liegen")
    if not 0.1 <= segment_hop <= segment_seconds:
        raise VideoMusicError(
            "--segment-hop muss zwischen 0.1 und --segment-seconds liegen"
        )
    if quality == "high" and vad == "auto" and not silero_available():
        raise VideoMusicError(
            "--quality high verlangt standardmaessig Silero VAD. Installiere die "
            "optionalen Pakete oder waehle --vad heuristic ausdruecklich und pruefe "
            "die markierten Segmente manuell."
        )

    source = source.expanduser().resolve()
    if not source.is_file():
        raise VideoMusicError(f"Quelldatei fehlt: {source}")
    output = (output or default_output(source, mode)).expanduser().resolve()
    manifest = (manifest or output.with_suffix(".manifest.json")).expanduser().resolve()
    profile_path = (
        profile_output or output.with_suffix(".reference-profile.json")
    ).expanduser().resolve()
    segment_path = (
        segment_output or default_segment_output(output)
    ).expanduser().resolve()
    generated_paths = {
        "Audioausgabe": output,
        "Manifest": manifest,
        "Segmentkarte": segment_path,
    }
    if analyze:
        generated_paths["Analyseprofil"] = profile_path
    for label, path in generated_paths.items():
        if path == source:
            raise VideoMusicError(f"{label} darf nicht die Quelldatei ueberschreiben")
    labels = list(generated_paths)
    for index, left_label in enumerate(labels):
        for right_label in labels[index + 1 :]:
            if generated_paths[left_label] == generated_paths[right_label]:
                raise VideoMusicError(
                    f"{left_label} und {right_label} muessen verschiedene Dateien sein"
                )
    if manifest.exists() and not overwrite:
        raise VideoMusicError(f"Manifest existiert bereits: {manifest}")
    if segment_path.exists() and not overwrite:
        raise VideoMusicError(f"Segmentkarte existiert bereits: {segment_path}")
    if analyze and profile_path.exists() and not overwrite:
        raise VideoMusicError(f"Analyseprofil existiert bereits: {profile_path}")

    source_hash = file_sha256(source)
    if mode == "soundtrack":
        source_media = _extract_wav(
            source,
            output,
            audio_stream=audio_stream,
            sample_rate=sample_rate,
            overwrite=overwrite,
        )
        processing = {
            "engine": "ffmpeg",
            "quality": quality,
            "contract": (
                "Decoded soundtrack with unchanged programme content; WAV encoding is "
                "not a byte-for-byte container copy."
            ),
        }
        limitations = [
            (
                "The soundtrack still contains every audible component: music, dialogue "
                "and sound effects."
            ),
            "This mode does not recover original multitrack stems, MIDI, plug-ins or automation.",
        ]
    else:
        source_media, processing = _isolate_music(
            source,
            output,
            audio_stream=audio_stream,
            sample_rate=sample_rate,
            model=demucs_model,
            device=device,
            quality=quality,
            separator=separator,
            roformer_command=roformer_command,
            overwrite=overwrite,
        )
        processing["contract"] = (
            "Estimated no-vocals mix; useful as a working reference, not the original music stem."
        )
        limitations = [
            "Speech or vocal remnants may remain and musical elements may be attenuated.",
            (
                "Sound effects usually remain because a no-vocals model is not a "
                "music-versus-SFX separator."
            ),
            (
                "Original stems, MIDI, instruments, samples, plug-ins and automation "
                "cannot be recovered exactly."
            ),
        ]

    output_media = probe_media(output)
    segment_analysis, segment_payload = _analyze_segments(
        output,
        segment_path,
        vad=vad,
        segment_seconds=segment_seconds,
        segment_hop=segment_hop,
        overwrite=overwrite,
    )
    quality_gate = _quality_gate(
        quality=quality,
        mode=mode,
        processing=processing,
        segment_summary=segment_payload["summary"],
        vad_requested=vad,
        vad_used=segment_payload["analysis"]["vad"]["engine"],
    )
    analysis = None
    if analyze:
        analysis = _analyze(
            output,
            profile_path,
            bpm=bpm,
            downbeat=downbeat,
            overwrite=overwrite,
        )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "completed" if quality_gate["status"] == "passed" else "review_required"
        ),
        "mode": mode,
        "quality": quality,
        "source": {
            "path": str(source),
            "sha256": source_hash,
            "selected_audio_stream": audio_stream,
            "media": source_media,
        },
        "output": {
            "path": str(output),
            "sha256": file_sha256(output),
            "size_bytes": output.stat().st_size,
            "media": output_media,
        },
        "processing": processing,
        "segment_analysis": segment_analysis,
        "analysis": analysis,
        "quality_gate": quality_gate,
        "limitations": limitations,
        "one_to_one_music_stem_claim": False,
        "next_commands": _next_commands(output, profile_path),
        "manifest": str(manifest),
    }
    _write_json_atomic(manifest, result, overwrite=overwrite)
    return result


def doctor(*, cdx_config: Path | None = None, cdx_receipt: Path | None = None) -> dict[str, Any]:
    from cinematic_separation import cdx_status

    ffmpeg = executable("ffmpeg", required=False)
    ffprobe = executable("ffprobe", required=False)
    separators = backend_status()
    speech = speech_backend_status()
    demucs = separators["demucs"]
    roformer = separators["roformer"]
    base_ready = bool(ffmpeg and ffprobe)
    return {
        "schema_version": SCHEMA_VERSION,
        "ffmpeg": {"available": bool(ffmpeg), "path": ffmpeg},
        "ffprobe": {"available": bool(ffprobe), "path": ffprobe},
        "demucs": demucs,
        "separators": separators,
        "cinematic_demixing": cdx_status(cdx_config, receipt=cdx_receipt),
        "speech_detection": speech,
        "ready": {
            "soundtrack": base_ready,
            "music": base_ready and bool(demucs["available"] or roformer["available"]),
            "high_soundtrack": base_ready and bool(speech["silero"]["available"]),
            "high_music": base_ready
            and bool(speech["silero"]["available"])
            and bool(demucs["available"] and demucs["high_quality_pin_matches"]),
            "high_music_roformer_reviewable": base_ready
            and bool(speech["silero"]["available"])
            and bool(roformer["available"]),
        },
        "contracts": {
            "soundtrack": "complete decoded mix, including dialogue and SFX",
            "music": "estimated no-vocals mix, not an original studio stem",
            "segments": (
                "routing probabilities; trained speech timestamps require Silero VAD"
            ),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser("doctor", help="show local extraction capabilities")
    doctor_parser.add_argument("--cdx-config", type=Path)
    doctor_parser.add_argument("--cdx-receipt", type=Path,
                               help="explicitly recheck a successful local inference receipt")
    demix = subparsers.add_parser(
        "decompose", help="estimate separate music/dialogue/SFX stems with local CDX23")
    demix.add_argument("source", type=Path)
    demix.add_argument("--output-dir", type=Path)
    demix.add_argument("--cdx-config", type=Path)
    demix.add_argument("--audio-stream", type=int, default=0)
    demix.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    demix.add_argument("--quality", choices=("standard", "high"), default="standard")
    demix.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    demix.add_argument("--maximum-residual-ratio", type=float, default=.1)
    demix.add_argument("--inference-timeout", type=float,
                        help="abort CDX inference after this many seconds")
    demix.add_argument("--strict", action="store_true",
                       help="do not publish a bundle failing the mixture-consistency gate")
    demix.add_argument("--vad", choices=("off", "auto", "silero", "heuristic"), default="off")
    extract_parser = subparsers.add_parser(
        "extract", help="extract a soundtrack or estimate a music bed"
    )
    extract_parser.add_argument("source", type=Path, help="local audio or video file")
    extract_parser.add_argument(
        "--mode", choices=("soundtrack", "music"), default="soundtrack"
    )
    extract_parser.add_argument("--output", type=Path)
    extract_parser.add_argument("--manifest", type=Path)
    extract_parser.add_argument("--audio-stream", type=int, default=0)
    extract_parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    extract_parser.add_argument(
        "--quality",
        choices=("standard", "high"),
        default="standard",
        help="high requires pinned separation and trained speech detection by default",
    )
    extract_parser.add_argument(
        "--separator", choices=("auto", "demucs", "roformer"), default="auto"
    )
    extract_parser.add_argument(
        "--demucs-model",
        help="override htdemucs (standard) or htdemucs_ft (high)",
    )
    extract_parser.add_argument(
        "--roformer-command",
        type=Path,
        help="local adapter; alternatively set NEXPT_ROFORMER_COMMAND",
    )
    extract_parser.add_argument("--device", choices=("cpu", "cuda", "mps"), default="cpu")
    extract_parser.add_argument(
        "--vad", choices=("auto", "silero", "heuristic", "off"), default="auto"
    )
    extract_parser.add_argument("--segment-output", type=Path)
    extract_parser.add_argument("--segment-seconds", type=float, default=1.0)
    extract_parser.add_argument("--segment-hop", type=float, default=0.5)
    extract_parser.add_argument("--analyze", action="store_true")
    extract_parser.add_argument("--profile-output", type=Path)
    extract_parser.add_argument("--bpm", type=float)
    extract_parser.add_argument("--downbeat", type=float)
    extract_parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "doctor":
            result = doctor(cdx_config=args.cdx_config, cdx_receipt=args.cdx_receipt)
        elif args.command == "decompose":
            from audio_decomposition import decompose
            result = decompose(
                args.source, output_dir=args.output_dir, cdx_config=args.cdx_config,
                audio_stream=args.audio_stream, sample_rate=args.sample_rate,
                quality=args.quality, device=args.device,
                maximum_residual_ratio=args.maximum_residual_ratio,
                strict=args.strict, vad=args.vad, inference_timeout=args.inference_timeout)
        else:
            result = extract(
                args.source,
                mode=args.mode,
                output=args.output,
                manifest=args.manifest,
                audio_stream=args.audio_stream,
                sample_rate=args.sample_rate,
                quality=args.quality,
                separator=args.separator,
                demucs_model=args.demucs_model,
                roformer_command=args.roformer_command,
                device=args.device,
                vad=args.vad,
                segment_output=args.segment_output,
                segment_seconds=args.segment_seconds,
                segment_hop=args.segment_hop,
                analyze=args.analyze,
                profile_output=args.profile_output,
                bpm=args.bpm,
                downbeat=args.downbeat,
                overwrite=args.overwrite,
            )
    except (VideoMusicError, OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

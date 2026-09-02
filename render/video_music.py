#!/usr/bin/env python3
"""Extract a verified soundtrack or an estimated music bed from local media.

The ``soundtrack`` mode decodes one audio stream without changing its musical
content.  It still contains dialogue and sound effects.  The ``music`` mode
uses Demucs to estimate a no-vocals mix; that result is useful as a reference,
but it is not the original studio music stem.

Examples::

    python3 render/video_music.py doctor
    python3 render/video_music.py extract film.mp4 --mode soundtrack
    python3 render/video_music.py extract film.mp4 --mode music --analyze
"""
from __future__ import annotations

import argparse
import hashlib
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


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "video-music"
SCHEMA_VERSION = 1
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
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if audio_stream < 0:
        raise VideoMusicError("--audio-stream darf nicht negativ sein")
    if not 8_000 <= sample_rate <= 192_000:
        raise VideoMusicError("--sample-rate muss zwischen 8000 und 192000 liegen")
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
                "-vn",
                "-sn",
                "-dn",
                "-ar",
                str(sample_rate),
                "-ac",
                "2",
                "-c:a",
                "pcm_s24le",
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


def demucs_available() -> bool:
    try:
        return importlib.util.find_spec("demucs") is not None
    except (ImportError, ValueError):
        return False


def demucs_version() -> str | None:
    if not demucs_available():
        return None
    try:
        return importlib.metadata.version("demucs")
    except importlib.metadata.PackageNotFoundError:
        return "installed"


def _isolate_music(
    source: Path,
    output: Path,
    *,
    audio_stream: int,
    sample_rate: int,
    model: str,
    device: str,
    overwrite: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not demucs_available():
        raise VideoMusicError(
            "Der Modus 'music' braucht Demucs. Installiere die optionalen Pakete aus "
            "garageband/requirements-transcription.txt oder nutze --mode soundtrack."
        )
    output = output.expanduser().resolve()
    _validate_output(source.expanduser().resolve(), output, overwrite=overwrite)
    output.parent.mkdir(parents=True, exist_ok=True)
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
        demucs_output = work / "demucs"
        _run(
            [
                sys.executable,
                "-m",
                "demucs",
                "-n",
                model,
                "-d",
                device,
                "-j",
                "1",
                "--float32",
                "--two-stems",
                "vocals",
                "-o",
                str(demucs_output),
                str(mix),
            ],
            "Demucs-Musikisolation",
        )
        candidates = sorted(demucs_output.rglob("no_vocals.wav"))
        if not candidates:
            raise VideoMusicError("Demucs hat keine no_vocals.wav erzeugt")
        _extract_wav(
            candidates[0],
            output,
            audio_stream=0,
            sample_rate=sample_rate,
            overwrite=overwrite,
        )
    return source_media, {
        "engine": "demucs",
        "version": demucs_version(),
        "model": model,
        "device": device,
        "jobs": 1,
        "stem": "no_vocals",
    }


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


def extract(
    source: Path,
    *,
    mode: str = "soundtrack",
    output: Path | None = None,
    manifest: Path | None = None,
    audio_stream: int = 0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    demucs_model: str = "htdemucs",
    device: str = "cpu",
    analyze: bool = False,
    profile_output: Path | None = None,
    bpm: float | None = None,
    downbeat: float | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if mode not in {"soundtrack", "music"}:
        raise VideoMusicError(f"Unbekannter Modus: {mode}")
    if device not in {"cpu", "cuda", "mps"}:
        raise VideoMusicError(f"Unbekanntes Demucs-Geraet: {device}")

    source = source.expanduser().resolve()
    if not source.is_file():
        raise VideoMusicError(f"Quelldatei fehlt: {source}")
    output = (output or default_output(source, mode)).expanduser().resolve()
    manifest = (manifest or output.with_suffix(".manifest.json")).expanduser().resolve()
    profile_path = (
        profile_output or output.with_suffix(".reference-profile.json")
    ).expanduser().resolve()
    generated_paths = {"Audioausgabe": output, "Manifest": manifest}
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
        "status": "completed",
        "mode": mode,
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
        "analysis": analysis,
        "limitations": limitations,
        "one_to_one_music_stem_claim": False,
        "next_commands": _next_commands(output, profile_path),
        "manifest": str(manifest),
    }
    _write_json_atomic(manifest, result, overwrite=overwrite)
    return result


def doctor() -> dict[str, Any]:
    ffmpeg = executable("ffmpeg", required=False)
    ffprobe = executable("ffprobe", required=False)
    demucs = demucs_available()
    return {
        "schema_version": SCHEMA_VERSION,
        "ffmpeg": {"available": bool(ffmpeg), "path": ffmpeg},
        "ffprobe": {"available": bool(ffprobe), "path": ffprobe},
        "demucs": {"available": demucs, "version": demucs_version()},
        "ready": {
            "soundtrack": bool(ffmpeg and ffprobe),
            "music": bool(ffmpeg and ffprobe and demucs),
        },
        "contracts": {
            "soundtrack": "complete decoded mix, including dialogue and SFX",
            "music": "estimated no-vocals mix, not an original studio stem",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="show local extraction capabilities")
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
    extract_parser.add_argument("--demucs-model", default="htdemucs")
    extract_parser.add_argument("--device", choices=("cpu", "cuda", "mps"), default="cpu")
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
            result = doctor()
        else:
            result = extract(
                args.source,
                mode=args.mode,
                output=args.output,
                manifest=args.manifest,
                audio_stream=args.audio_stream,
                sample_rate=args.sample_rate,
                demucs_model=args.demucs_model,
                device=args.device,
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

#!/usr/bin/env python3
"""Safe adapter from vendored claude-music/ACE-Step to GarageBand.

The upstream project generates or edits audio.  This module keeps that concern
separate from the existing GarageBand UI bridge and provides an explicit seam:
generate an instrumental candidate, verify the output, then either import the
audio unchanged or run the existing audio-to-editable-tracks workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = ROOT / "tools" / "claude-music"
ENGINE = VENDOR_ROOT / "skills" / "claude-music" / "scripts" / "music_engine.py"
LICENSE = VENDOR_ROOT / "LICENSE"
UPSTREAM_COMMIT = "5aa0173a6b329e059568bef4253e2a62efe8b412"
DEFAULT_CONFIG = ROOT / "garageband" / "ai-music.json"
DEFAULT_OUTPUT = ROOT / "out" / "ai-music"
WORKFLOW = ROOT / "garageband" / "workflow.py"
GARAGEBAND_CLI = ROOT / "tools" / "garageband-llm-bridge" / "garageband_cli.py"

ACTION_NAMES = {"generate", "cover", "repaint", "extract", "lego", "complete"}
QUALITY_NAMES = {"draft", "standard", "high", "max"}
FORMAT_NAMES = {"flac", "wav", "mp3", "wav32", "opus", "aac"}
AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".opus", ".aac", ".m4a", ".ogg"}
REQUEST_KEYS = {
    "action",
    "caption",
    "lyrics",
    "instrumental",
    "quality",
    "format",
    "batch",
    "seed",
    "ace_step_dir",
    "output_dir",
    "source_audio",
    "bpm",
    "key",
    "duration",
    "cover_strength",
    "start",
    "end",
    "timeout_seconds",
    "select_output",
    "acknowledge_expensive",
}


class GenerativeMusicError(RuntimeError):
    """The generative adapter contract could not be completed safely."""


def _load_config(path: str | Path | None = None) -> tuple[dict[str, Any], Path]:
    configured = path or os.environ.get("NEXPT_AI_MUSIC_CONFIG") or DEFAULT_CONFIG
    config_path = Path(configured).expanduser().resolve()
    if not config_path.exists():
        return {}, config_path
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GenerativeMusicError(f"Invalid AI music config JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GenerativeMusicError("AI music config must be a JSON object")
    defaults = payload.get("defaults", {})
    if not isinstance(defaults, dict):
        raise GenerativeMusicError("AI music config defaults must be an object")
    return payload, config_path


def _path(value: Any, label: str, *, must_exist: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise GenerativeMusicError(f"{label} must be a non-empty path")
    result = Path(value).expanduser().resolve()
    if must_exist and not result.exists():
        raise GenerativeMusicError(f"{label} does not exist: {result}")
    return result


def _source_audio(value: Any) -> Path:
    source = _path(value, "source_audio", must_exist=True)
    if not source.is_file() or source.suffix.lower() not in AUDIO_EXTENSIONS:
        raise GenerativeMusicError(
            f"source_audio must be a supported audio file: {source}"
        )
    return source


def _bounded_number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GenerativeMusicError(f"{label} must be a number")
    number = float(value)
    if not minimum <= number <= maximum:
        raise GenerativeMusicError(f"{label} must be between {minimum} and {maximum}")
    return number


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GenerativeMusicError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise GenerativeMusicError(f"{label} must be between {minimum} and {maximum}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def status(config_path: str | Path | None = None) -> dict[str, Any]:
    config, resolved_config = _load_config(config_path)
    ace_value = os.environ.get("NEXPT_ACE_STEP_DIR") or config.get("ace_step_dir")
    ace_dir = None
    if isinstance(ace_value, str) and ace_value and ace_value != "CHANGE_ME":
        ace_dir = Path(ace_value).expanduser().resolve()
    checks = {
        "vendored_repository": VENDOR_ROOT.is_dir(),
        "engine": ENGINE.is_file(),
        "license": LICENSE.is_file(),
        "uv": shutil.which("uv") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "ace_step": bool(ace_dir and ace_dir.is_dir()),
    }
    return {
        "ready": all(
            checks[name]
            for name in ("vendored_repository", "engine", "license", "uv", "ace_step")
        ),
        "checks": checks,
        "upstream": {
            "repository": "https://github.com/AgriciDaniel/claude-music",
            "commit": UPSTREAM_COMMIT,
            "license": "MIT",
            "path": str(VENDOR_ROOT),
        },
        "config_path": str(resolved_config),
        "config_exists": resolved_config.is_file(),
        "ace_step_dir": str(ace_dir) if ace_dir else None,
        "gpu": {
            "nvidia_smi": shutil.which("nvidia-smi") is not None,
            "note": "NVIDIA/CUDA is the supported fast path; CPU generation can be very slow.",
        },
    }


def build_generation_plan(
    request: dict[str, Any],
    *,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise GenerativeMusicError("generation request must be an object")
    unknown = set(request) - REQUEST_KEYS
    if unknown:
        raise GenerativeMusicError(
            f"unknown generation request fields: {sorted(unknown)}"
        )
    config, resolved_config = _load_config(config_path)
    defaults = config.get("defaults", {})
    action = request.get("action", "generate")
    if action not in ACTION_NAMES:
        raise GenerativeMusicError(f"action must be one of {sorted(ACTION_NAMES)}")

    caption = request.get("caption", "")
    lyrics = request.get("lyrics", "")
    if not isinstance(caption, str) or len(caption) > 512:
        raise GenerativeMusicError("caption must be a string of at most 512 characters")
    if not isinstance(lyrics, str) or len(lyrics) > 20_000:
        raise GenerativeMusicError(
            "lyrics must be a string of at most 20,000 characters"
        )
    if action == "generate" and not caption.strip():
        raise GenerativeMusicError("caption is required for generation")

    quality = request.get("quality", defaults.get("quality", "high"))
    audio_format = request.get("format", defaults.get("format", "wav"))
    if quality not in QUALITY_NAMES:
        raise GenerativeMusicError(f"quality must be one of {sorted(QUALITY_NAMES)}")
    if audio_format not in FORMAT_NAMES:
        raise GenerativeMusicError(f"format must be one of {sorted(FORMAT_NAMES)}")
    batch = _integer(request.get("batch", defaults.get("batch", 1)), "batch", 1, 4)
    seed = _integer(request.get("seed", -1), "seed", -1, 2_147_483_647)

    ace_value = (
        request.get("ace_step_dir")
        or os.environ.get("NEXPT_ACE_STEP_DIR")
        or config.get("ace_step_dir")
    )
    ace_dir = None
    if isinstance(ace_value, str) and ace_value and ace_value != "CHANGE_ME":
        ace_dir = Path(ace_value).expanduser().resolve()
    output_value = request.get("output_dir", config.get("output_dir", DEFAULT_OUTPUT))
    output_dir = _path(output_value, "output_dir")
    uv = shutil.which("uv") or "uv"

    command = [
        uv,
        "run",
        "python3",
        str(ENGINE),
        "--ace-step-dir",
        str(ace_dir) if ace_dir else "ACE_STEP_DIR_REQUIRED",
        "--quality",
        quality,
        "--format",
        audio_format,
        "--naming",
        "descriptive",
        "--seed",
        str(seed),
        "--batch",
        str(batch),
        "--output-dir",
        str(output_dir),
        action,
    ]
    source = None
    if action != "generate":
        source = _source_audio(request.get("source_audio"))
        command.append(f"--src-audio={source}")
    if caption:
        command.append(f"--caption={caption}")
    if action in {"generate", "cover", "repaint", "lego", "complete"} and lyrics:
        command.append(f"--lyrics={lyrics}")
    instrumental = request.get("instrumental", defaults.get("instrumental", True))
    if not isinstance(instrumental, bool):
        raise GenerativeMusicError("instrumental must be a boolean")
    if action in {"generate", "cover", "repaint"} and instrumental:
        command.append("--instrumental")
    if "bpm" in request and request["bpm"] is not None:
        if action not in {"generate", "cover", "repaint"}:
            raise GenerativeMusicError(f"bpm is not supported for action {action}")
        bpm = int(_bounded_number(request["bpm"], "bpm", 30, 300))
        command.extend(["--bpm", str(bpm)])
    if "key" in request and request["key"] is not None:
        if action not in {"generate", "cover", "repaint"}:
            raise GenerativeMusicError(f"key is not supported for action {action}")
        key = request["key"]
        if (
            not isinstance(key, str)
            or len(key) > 40
            or any(char in key for char in ";|`\n\r")
        ):
            raise GenerativeMusicError("key contains unsupported characters")
        command.append(f"--key={key}")
    if "duration" in request and request["duration"] is not None:
        if action not in {"generate", "cover", "repaint", "complete"}:
            raise GenerativeMusicError(f"duration is not supported for action {action}")
        duration = _bounded_number(request["duration"], "duration", 10, 600)
        command.extend(["--duration", str(duration)])
    if action == "cover":
        strength = _bounded_number(
            request.get("cover_strength", 0.5), "cover_strength", 0, 1
        )
        command.extend(["--cover-strength", str(strength)])
    if action == "repaint":
        start = _bounded_number(request.get("start", 0), "start", 0, 600)
        end = _bounded_number(request.get("end", 600), "end", 0, 600)
        if end <= start:
            raise GenerativeMusicError("repaint end must be greater than start")
        command.extend(["--start", str(start), "--end", str(end)])

    readiness = status(resolved_config)
    if ace_dir is not None:
        readiness["ace_step_dir"] = str(ace_dir)
        readiness["checks"]["ace_step"] = ace_dir.is_dir()
        readiness["ready"] = all(
            readiness["checks"][name]
            for name in ("vendored_repository", "engine", "license", "uv", "ace_step")
        )
    warnings = []
    if not instrumental:
        warnings.append(
            "Vocals were explicitly enabled; NEXPT's normal GarageBand workflow expects instrumental music."
        )
    if quality == "max" and request.get("acknowledge_expensive") is not True:
        warnings.append(
            "quality=max can take several minutes and requires acknowledge_expensive=true before execution."
        )
    if not readiness["checks"]["ace_step"]:
        warnings.append("Configure ace_step_dir before execution.")
    if not readiness["checks"]["uv"]:
        warnings.append("Install uv before execution.")
    return {
        "version": 1,
        "action": action,
        "instrumental": instrumental,
        "quality": quality,
        "format": audio_format,
        "batch": batch,
        "seed": seed,
        "source_audio": str(source) if source else None,
        "output_dir": str(output_dir),
        "command": command,
        "ready": readiness["ready"],
        "readiness": readiness,
        "warnings": warnings,
        "output_contract": {
            "stdout": "one JSON object",
            "audio_files": "verified existing files with SHA-256",
            "overwrite": False,
        },
    }


def _parse_engine_output(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise GenerativeMusicError(
            "claude-music did not return its documented JSON stdout contract"
        ) from exc
    if not isinstance(payload, dict):
        raise GenerativeMusicError("claude-music result must be a JSON object")
    return payload


def run_generation(
    request: dict[str, Any],
    *,
    config_path: str | Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    plan = build_generation_plan(request, config_path=config_path)
    if not plan["ready"]:
        missing = [name for name, ok in plan["readiness"]["checks"].items() if not ok]
        raise GenerativeMusicError(
            "AI music runtime is not ready: " + ", ".join(missing)
        )
    if plan["quality"] == "max" and request.get("acknowledge_expensive") is not True:
        raise GenerativeMusicError("quality=max requires acknowledge_expensive=true")
    timeout = _integer(request.get("timeout_seconds", 900), "timeout_seconds", 30, 3600)
    result = runner(
        plan["command"],
        cwd=plan["readiness"]["ace_step_dir"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    payload = _parse_engine_output(result.stdout)
    if result.returncode or payload.get("success") is not True:
        message = (
            payload.get("error")
            or result.stderr.strip()
            or f"claude-music exited with {result.returncode}"
        )
        raise GenerativeMusicError(str(message))
    outputs = payload.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise GenerativeMusicError(
            "claude-music reported success without audio outputs"
        )
    verified = []
    for index, output in enumerate(outputs):
        if not isinstance(output, dict) or not isinstance(output.get("path"), str):
            raise GenerativeMusicError(f"claude-music output {index} has no path")
        audio = Path(output["path"]).expanduser().resolve()
        if not audio.is_file() or audio.suffix.lower() not in AUDIO_EXTENSIONS:
            raise GenerativeMusicError(
                f"generated output is not a supported audio file: {audio}"
            )
        verified.append(
            {
                **output,
                "path": str(audio),
                "bytes": audio.stat().st_size,
                "sha256": _sha256(audio),
            }
        )
    selected = _integer(
        request.get("select_output", 1), "select_output", 1, len(verified)
    )
    chosen = Path(verified[selected - 1]["path"])
    return {
        "schema_version": 1,
        "status": "generated",
        "upstream": plan["readiness"]["upstream"],
        "request": {
            key: value for key, value in request.items() if key not in {"lyrics"}
        },
        "outputs": verified,
        "selected_output": selected,
        "selected_audio": str(chosen),
        "engine_result": payload,
        "garageband_handoff": build_garageband_handoff(chosen),
    }


def build_garageband_handoff(
    audio_path: str | Path,
    *,
    project_dir: str | Path | None = None,
    transcription_quality: str = "high",
    live: bool = False,
) -> dict[str, Any]:
    audio = _source_audio(audio_path)
    if transcription_quality not in {"auto", "high", "fast"}:
        raise GenerativeMusicError("transcription_quality must be auto, high or fast")
    project = (
        _path(project_dir, "project_dir")
        if project_dir
        else ROOT / "garageband" / "arrangements" / f"ai-{audio.stem}"
    )
    editable = [
        sys.executable,
        str(WORKFLOW),
        str(audio),
        "--project-dir",
        str(project),
        "--quality",
        transcription_quality,
        "--prepare" if live else "--prepare-dry-run",
    ]
    return {
        "audio": str(audio),
        "reference_import": {
            "description": "Import the generated mix unchanged as a GarageBand audio reference.",
            "command": [sys.executable, str(GARAGEBAND_CLI), "open", str(audio)],
            "editable_notes": False,
        },
        "editable_reconstruction": {
            "description": "Transcribe the generated mix into approximate MIDI/instrument tracks and retain the exact mix as A/B reference.",
            "command": editable,
            "project_dir": str(project),
            "touches_garageband": live,
            "one_to_one_claim": False,
        },
    }


def generate_and_handoff(
    request: dict[str, Any],
    *,
    config_path: str | Path | None = None,
    dry_run: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if dry_run:
        return {
            "dry_run": True,
            "generation": build_generation_plan(request, config_path=config_path),
        }
    generated = run_generation(request, config_path=config_path, runner=runner)
    generated["dry_run"] = False
    return generated


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    plan = sub.add_parser("plan")
    plan.add_argument("request", type=Path, help="generation request JSON")
    generate = sub.add_parser("generate")
    generate.add_argument("request", type=Path, help="generation request JSON")
    handoff = sub.add_parser("handoff")
    handoff.add_argument("audio", type=Path)
    handoff.add_argument("--project-dir", type=Path)
    handoff.add_argument(
        "--transcription-quality", choices=("auto", "high", "fast"), default="high"
    )
    handoff.add_argument("--live", action="store_true")
    return parser.parse_args(argv)


def _request(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerativeMusicError(f"Could not read generation request: {exc}") from exc
    if not isinstance(payload, dict):
        raise GenerativeMusicError("generation request must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "status":
            result = status(args.config)
        elif args.command == "plan":
            result = build_generation_plan(
                _request(args.request), config_path=args.config
            )
        elif args.command == "generate":
            result = run_generation(_request(args.request), config_path=args.config)
        else:
            result = build_garageband_handoff(
                args.audio,
                project_dir=args.project_dir,
                transcription_quality=args.transcription_quality,
                live=args.live,
            )
    except (GenerativeMusicError, OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

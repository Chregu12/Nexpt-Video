#!/usr/bin/env python3
"""Run the complete, safe audio-to-editable-GarageBand workflow.

This is the product-level entry point. It keeps transcription artifacts in one
ignored arrangement directory, protects existing work, records the exact
source/configuration, applies explicit quality gates and can hand the verified
score to :mod:`garageband.session` for a dry-run plan or a real Mac session.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RENDER = ROOT/"render"
if str(RENDER) not in sys.path:
    sys.path.insert(0, str(RENDER))

from garageband.instrument_catalog import load_patch_inventory  # noqa: E402
from garageband.session import (  # noqa: E402
    load_preset,
    load_score,
    prepare_plan,
    run_prepare,
    validate_preset_score,
)
from garageband.transcribe import (  # noqa: E402
    load_instrument_map,
    slugify,
    transcribe_audio,
)
from reference_analyzer import file_sha256  # noqa: E402


class WorkflowError(RuntimeError):
    """The orchestration contract could not be completed safely."""


@dataclass(frozen=True)
class WorkflowPaths:
    project_dir: Path
    score: Path
    midi: Path
    preset: Path
    report: Path
    profile: Path
    session_dir: Path
    manifest: Path


def workflow_paths(source: Path, project_dir: Path | None = None) -> WorkflowPaths:
    slug = slugify(source.stem)
    project = (project_dir or
               ROOT/"garageband"/"arrangements"/f"{slug}-transcription").resolve()
    return WorkflowPaths(
        project_dir=project,
        score=project/"score.json",
        midi=project/"score.mid",
        preset=project/"preset.json",
        report=project/"analysis"/"transcription-report.json",
        profile=project/"analysis"/"reference-profile.json",
        session_dir=project/"garageband-session",
        manifest=project/"workflow-result.json",
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkflowError(f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"Invalid {label} JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise WorkflowError(f"{label} must be a JSON object")
    return payload


def _input_identity(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path.resolve()
    if not resolved.is_file():
        raise WorkflowError(f"Input file does not exist: {resolved}")
    return {"path": str(resolved), "sha256": file_sha256(resolved)}


def assess_quality(
    report: dict[str, Any],
    *,
    minimum_confidence: float = .50,
    maximum_uncertain_share: float = .35,
    require_inventory: bool = False,
) -> dict[str, Any]:
    """Turn transcription diagnostics into explicit preparation gates."""
    if not 0 <= minimum_confidence <= 1:
        raise ValueError("minimum_confidence must be between 0 and 1")
    if not 0 <= maximum_uncertain_share <= 1:
        raise ValueError("maximum_uncertain_share must be between 0 and 1")

    findings: list[dict[str, Any]] = []

    def finding(level: str, code: str, message: str, **values: Any) -> None:
        findings.append({"level": level, "code": code, "message": message, **values})

    score = report.get("score", {})
    sounding_notes = int(score.get("sounding_notes", 0) or 0)
    if sounding_notes <= 0:
        finding("error", "no_sounding_notes",
                "The transcription contains no audible note events.", actual=0)

    quality = report.get("quality", {})
    confidence = float(quality.get("estimated_confidence", 0.0) or 0.0)
    if confidence < minimum_confidence:
        finding(
            "error", "low_overall_confidence",
            "Estimated transcription confidence is below the configured gate.",
            actual=round(confidence, 4), threshold=minimum_confidence,
        )

    instruments = report.get("instruments", {})
    tonal_notes = int(instruments.get("note_events", 0) or 0)
    uncertain_notes = int(instruments.get("uncertain_notes", 0) or 0)
    uncertain_share = uncertain_notes/max(1, tonal_notes)
    if tonal_notes and uncertain_share > maximum_uncertain_share:
        finding(
            "error", "too_many_uncertain_instruments",
            "Too many tonal notes have an uncertain instrument assignment.",
            actual=round(uncertain_share, 4), threshold=maximum_uncertain_share,
            uncertain_notes=uncertain_notes, tonal_notes=tonal_notes,
        )

    content = str(report.get("content", {}).get("used", "unknown"))
    detected = instruments.get("detected", [])
    if content == "full" and tonal_notes <= 0:
        finding(
            "error", "full_music_without_tonal_notes",
            "Full-music mode did not produce editable tonal notes.",
        )
    elif content == "full" and not detected:
        finding(
            "error", "full_music_without_instruments",
            "Full-music mode did not identify any editable instrument track.",
        )

    inventory = report.get("outputs", {}).get("garageband_inventory")
    if require_inventory and not inventory:
        finding(
            "error", "garageband_inventory_required",
            "No installed GarageBand patch inventory was used.",
        )
    elif tonal_notes and not inventory:
        finding(
            "warning", "garageband_inventory_missing",
            "Patch names use built-in defaults; inventory the target Mac for deterministic sounds.",
        )

    pitch_engine = str(report.get("engines", {}).get("pitch", {}).get("used", "unknown"))
    if content == "full" and pitch_engine == "dsp":
        finding(
            "warning", "dsp_pitch_fallback",
            "The DSP pitch fallback is less accurate than Basic Pitch for polyphonic music.",
        )

    errors = [row for row in findings if row["level"] == "error"]
    warnings = [row for row in findings if row["level"] == "warning"]
    return {
        "status": "failed" if errors else ("review" if warnings else "passed"),
        "may_prepare_automatically": not errors,
        "minimum_confidence": minimum_confidence,
        "maximum_uncertain_share": maximum_uncertain_share,
        "require_inventory": require_inventory,
        "metrics": {
            "estimated_confidence": round(confidence, 4),
            "sounding_notes": sounding_notes,
            "tonal_notes": tonal_notes,
            "uncertain_notes": uncertain_notes,
            "uncertain_share": round(uncertain_share, 4) if tonal_notes else 0.0,
        },
        "findings": findings,
    }


def _configuration(
    *,
    quality: str,
    separation: str | None,
    pitch_engine: str | None,
    instrument_engine: str | None,
    content: str,
    bpm: float | None,
    downbeat: float | None,
    demucs_model: str,
    clap_model: str,
    device: str,
    instrument_map: dict[str, Any],
    instrument_map_identity: dict[str, Any] | None,
    inventory_identity: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "quality": quality,
        "separation": separation,
        "pitch_engine": pitch_engine,
        "instrument_engine": instrument_engine,
        "content": content,
        "bpm": bpm,
        "downbeat": downbeat,
        "demucs_model": demucs_model,
        "clap_model": clap_model,
        "device": device,
        "instrument_map": instrument_map,
        "instrument_map_file": instrument_map_identity,
        "garageband_inventory": inventory_identity,
    }


def _validate_artifacts(paths: WorkflowPaths) -> dict[str, Any]:
    score = load_score(paths.score)
    preset = load_preset(paths.preset)
    compatibility = validate_preset_score(preset, score)
    if not paths.midi.is_file() or paths.midi.read_bytes()[:4] != b"MThd":
        raise WorkflowError(f"Generated MIDI is missing or invalid: {paths.midi}")
    report = _read_json(paths.report, "transcription report")
    profile = _read_json(paths.profile, "reference profile")
    files = {}
    for label, path in (
            ("score", paths.score), ("midi", paths.midi),
            ("preset", paths.preset), ("report", paths.report),
            ("profile", paths.profile)):
        files[label] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }
    return {
        "score_preset": compatibility,
        "score_parts": len(score["parts"]),
        "midi_bytes": paths.midi.stat().st_size,
        "report_schema_version": report.get("schema_version"),
        "profile_schema_version": profile.get("schema_version"),
        "files": files,
    }


def _verify_resume_hashes(
    paths: WorkflowPaths,
    manifest: dict[str, Any],
) -> None:
    expected = manifest.get("artifact_verification", {}).get("files")
    if not isinstance(expected, dict):
        raise WorkflowError(
            "Cannot resume: the manifest has no verified artifact hashes; "
            "regenerate with --overwrite")
    actual_paths = {
        "score": paths.score, "midi": paths.midi, "preset": paths.preset,
        "report": paths.report, "profile": paths.profile,
    }
    changed = []
    for label, path in actual_paths.items():
        recorded = expected.get(label, {})
        if (not isinstance(recorded, dict) or
                recorded.get("sha256") != file_sha256(path) or
                recorded.get("bytes") != path.stat().st_size):
            changed.append(label)
    if changed:
        raise WorkflowError(
            "Cannot resume: generated artifacts changed since verification: " +
            ", ".join(changed))


def _run_transcription_staged(
    source: Path,
    paths: WorkflowPaths,
    *,
    bpm: float | None,
    downbeat: float | None,
    quality: str,
    separation: str | None,
    pitch_engine: str | None,
    instrument_engine: str | None,
    instrument_map: dict[str, Any],
    inventory: dict[str, Any] | None,
    content: str,
    demucs_model: str,
    clap_model: str,
    device: str,
    keep_work: bool,
) -> dict[str, Any]:
    paths.project_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
            prefix=".transcription-", dir=paths.project_dir) as temporary:
        stage = Path(temporary)
        stage_paths = WorkflowPaths(
            project_dir=stage,
            score=stage/"score.json",
            midi=stage/"score.mid",
            preset=stage/"preset.json",
            report=stage/"transcription-report.json",
            profile=stage/"reference-profile.json",
            session_dir=stage/"session",
            manifest=stage/"manifest.json",
        )
        if keep_work:
            work_dir = paths.project_dir/"analysis-work"
        else:
            work_dir = stage/"analysis-work"
        report = transcribe_audio(
            source,
            score_path=stage_paths.score,
            midi_path=stage_paths.midi,
            preset_path=stage_paths.preset,
            report_path=stage_paths.report,
            profile_path=stage_paths.profile,
            work_dir=work_dir,
            bpm_hint=bpm,
            downbeat_hint=downbeat,
            quality=quality,
            separation=separation,
            pitch_engine=pitch_engine,
            instrument_engine=instrument_engine,
            instrument_map=instrument_map,
            garageband_inventory=inventory,
            content_mode=content,
            demucs_model=demucs_model,
            clap_model=clap_model,
            device=device,
        )
        load_score(stage_paths.score)
        preset = load_preset(stage_paths.preset)
        validate_preset_score(preset, load_score(stage_paths.score))
        if stage_paths.midi.read_bytes()[:4] != b"MThd":
            raise WorkflowError("Transcription engine produced an invalid MIDI header")

        final_outputs = {
            "profile": str(paths.profile),
            "score": str(paths.score),
            "midi": str(paths.midi),
            "preset": str(paths.preset),
            "garageband_inventory": (
                inventory.get("source_path") if inventory else None),
            "reference_audio": str(source),
            "report": str(paths.report),
        }
        report = {**report, "outputs": final_outputs}
        _write_json_atomic(stage_paths.report, report)

        for staged, final in (
                (stage_paths.score, paths.score),
                (stage_paths.midi, paths.midi),
                (stage_paths.preset, paths.preset),
                (stage_paths.profile, paths.profile),
                (stage_paths.report, paths.report)):
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, final)
    return report


def run_workflow(
    source: Path,
    *,
    project_dir: Path | None = None,
    quality: str = "auto",
    separation: str | None = None,
    pitch_engine: str | None = None,
    instrument_engine: str | None = None,
    instrument_map_path: Path | None = None,
    inventory_path: Path | None = None,
    content: str = "auto",
    bpm: float | None = None,
    downbeat: float | None = None,
    demucs_model: str = "htdemucs_6s",
    clap_model: str = "laion/clap-htsat-unfused",
    device: str = "cpu",
    minimum_confidence: float = .50,
    maximum_uncertain_share: float = .35,
    require_inventory: bool = False,
    resume: bool = False,
    overwrite: bool = False,
    keep_work: bool = False,
    prepare: bool = False,
    prepare_dry_run: bool = False,
    allow_low_confidence: bool = False,
    discard_unsaved: bool = False,
    keep_reference_audible: bool = False,
    no_wait: bool = False,
) -> dict[str, Any]:
    """Transcribe, verify, quality-gate and optionally prepare GarageBand."""
    if resume and overwrite:
        raise WorkflowError("Use either resume or overwrite, not both")
    if prepare and prepare_dry_run:
        raise WorkflowError("Use either prepare or prepare_dry_run, not both")
    if not 0 <= minimum_confidence <= 1:
        raise WorkflowError("minimum_confidence must be between 0 and 1")
    if not 0 <= maximum_uncertain_share <= 1:
        raise WorkflowError("maximum_uncertain_share must be between 0 and 1")
    source = source.resolve()
    if not source.is_file():
        raise WorkflowError(f"Source audio does not exist: {source}")

    paths = workflow_paths(source, project_dir)
    source_identity = _input_identity(source)
    map_identity = _input_identity(instrument_map_path)
    inventory_identity = _input_identity(inventory_path)
    instrument_map = load_instrument_map(instrument_map_path)
    inventory = load_patch_inventory(inventory_path)
    configuration = _configuration(
        quality=quality, separation=separation, pitch_engine=pitch_engine,
        instrument_engine=instrument_engine, content=content, bpm=bpm,
        downbeat=downbeat, demucs_model=demucs_model, clap_model=clap_model,
        device=device, instrument_map=instrument_map,
        instrument_map_identity=map_identity,
        inventory_identity=inventory_identity,
    )
    artifact_paths = [paths.score, paths.midi, paths.preset, paths.report, paths.profile]
    existing_manifest = (
        _read_json(paths.manifest, "workflow manifest")
        if paths.manifest.exists() else None)

    reused = False
    if resume:
        if existing_manifest is None:
            raise WorkflowError(f"Cannot resume without manifest: {paths.manifest}")
        if existing_manifest.get("source") != source_identity:
            raise WorkflowError("Cannot resume: source path or SHA-256 has changed")
        if existing_manifest.get("configuration") != configuration:
            raise WorkflowError("Cannot resume: workflow configuration has changed")
        missing = [str(path) for path in artifact_paths if not path.is_file()]
        if missing:
            raise WorkflowError("Cannot resume; missing artifacts: " + ", ".join(missing))
        _verify_resume_hashes(paths, existing_manifest)
        report = _read_json(paths.report, "transcription report")
        reused = True
    else:
        if (existing_manifest is not None or any(path.exists() for path in artifact_paths)) \
                and not overwrite:
            raise WorkflowError(
                f"Workflow outputs already exist in {paths.project_dir}. "
                "Use --resume to reuse them or --overwrite to regenerate them.")
        running = {
            "schema_version": 1,
            "status": "running",
            "source": source_identity,
            "configuration": configuration,
            "paths": {key: str(value) for key, value in asdict(paths).items()},
            "reference_contract": {
                "exact_audio": "The unchanged source is imported as the A/B reference track.",
                "editable_reconstruction": "MIDI notes and GarageBand patches are an approximation.",
                "one_to_one_reconstruction_claim": False,
            },
        }
        _write_json_atomic(paths.manifest, running)
        try:
            report = _run_transcription_staged(
                source, paths, bpm=bpm, downbeat=downbeat, quality=quality,
                separation=separation, pitch_engine=pitch_engine,
                instrument_engine=instrument_engine,
                instrument_map=instrument_map, inventory=inventory,
                content=content, demucs_model=demucs_model,
                clap_model=clap_model, device=device, keep_work=keep_work,
            )
        except Exception as exc:
            _write_json_atomic(paths.manifest, {
                **running, "status": "failed", "error": str(exc),
            })
            raise

    verification = _validate_artifacts(paths)
    gate = assess_quality(
        report, minimum_confidence=minimum_confidence,
        maximum_uncertain_share=maximum_uncertain_share,
        require_inventory=require_inventory,
    )
    wants_prepare = prepare or prepare_dry_run
    preparation_error: Exception | None = None
    try:
        if wants_prepare and not gate["may_prepare_automatically"] and not allow_low_confidence:
            status = "quality_blocked"
            prepare_result = None
        elif prepare_dry_run:
            prepare_result = {
                "dry_run": True,
                "plan": prepare_plan(
                    paths.score, paths.preset, paths.session_dir,
                    source, discard_unsaved,
                ),
            }
            status = "prepare_plan_ready"
        elif prepare:
            prepare_args = SimpleNamespace(
                score=paths.score,
                preset=paths.preset,
                output_dir=paths.session_dir,
                reference_audio=source,
                discard_unsaved=discard_unsaved,
                reference_track_index=None,
                keep_reference_audible=keep_reference_audible,
                no_wait=no_wait,
                dry_run=False,
            )
            prepare_result = run_prepare(prepare_args)
            status = "prepared"
        else:
            prepare_result = None
            status = ("transcribed" if gate["may_prepare_automatically"]
                      else "quality_review_required")
    except Exception as exc:
        status = "prepare_failed"
        prepare_result = None
        preparation_error = exc

    if status == "prepared":
        next_action = "Save the open .band project, compare against the reference, then edit in GarageBand."
    elif status == "prepare_plan_ready":
        next_action = "Run the same command with --resume --prepare on the GarageBand Mac."
    elif not gate["may_prepare_automatically"]:
        next_action = "Review quality findings or rerun with stronger engines/overrides."
    else:
        next_action = "Run with --resume --prepare, or --prepare-dry-run to inspect the Mac plan."
    result = {
        "schema_version": 1,
        "status": status,
        "source": source_identity,
        "configuration": configuration,
        "paths": {key: str(value) for key, value in asdict(paths).items()},
        "reused_transcription": reused,
        "artifact_verification": verification,
        "quality_gate": gate,
        "prepare": prepare_result,
        "prepare_error": str(preparation_error) if preparation_error else None,
        "platform": platform.system(),
        "next_action": next_action,
        "reference_contract": {
            "exact_audio": "The unchanged source is imported as the A/B reference track.",
            "editable_reconstruction": "MIDI notes and GarageBand patches are an approximation.",
            "one_to_one_reconstruction_claim": False,
        },
    }
    _write_json_atomic(paths.manifest, result)
    if preparation_error is not None:
        raise WorkflowError(
            f"GarageBand preparation failed: {preparation_error}") from preparation_error
    if status == "quality_blocked":
        raise WorkflowError(
            "GarageBand preparation was blocked by the quality gate. "
            f"Inspect {paths.manifest} or use --allow-low-confidence explicitly.")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="instrumental MP3/M4A/WAV")
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--quality", choices=("auto", "high", "fast"), default="auto")
    parser.add_argument("--separate", choices=("auto", "demucs", "off"))
    parser.add_argument("--pitch-engine", choices=("auto", "basic-pitch", "dsp", "off"))
    parser.add_argument("--instrument-engine", choices=("auto", "clap", "stem", "off"))
    parser.add_argument("--instrument-map", type=Path)
    parser.add_argument("--garageband-inventory", type=Path)
    parser.add_argument("--content", choices=("auto", "full", "percussion"), default="auto")
    parser.add_argument("--bpm", type=float)
    parser.add_argument("--downbeat", type=float)
    parser.add_argument("--demucs-model", default="htdemucs_6s")
    parser.add_argument("--clap-model", default="laion/clap-htsat-unfused")
    parser.add_argument("--device", choices=("cpu", "cuda", "mps"), default="cpu")
    parser.add_argument("--minimum-confidence", type=float, default=.50)
    parser.add_argument("--maximum-uncertain-share", type=float, default=.35)
    parser.add_argument("--require-inventory", action="store_true")
    lifecycle = parser.add_mutually_exclusive_group()
    lifecycle.add_argument("--resume", action="store_true")
    lifecycle.add_argument("--overwrite", action="store_true")
    parser.add_argument("--keep-work", action="store_true",
                        help="keep Demucs/intermediate analysis files")
    preparation = parser.add_mutually_exclusive_group()
    preparation.add_argument("--prepare", action="store_true",
                             help="open and patch GarageBand on this Mac")
    preparation.add_argument("--prepare-dry-run", action="store_true",
                             help="include the complete non-mutating Mac plan")
    parser.add_argument("--allow-low-confidence", action="store_true")
    parser.add_argument("--discard-unsaved", action="store_true")
    parser.add_argument("--keep-reference-audible", action="store_true")
    parser.add_argument("--no-wait", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = run_workflow(
            args.source,
            project_dir=args.project_dir,
            quality=args.quality,
            separation=args.separate,
            pitch_engine=args.pitch_engine,
            instrument_engine=args.instrument_engine,
            instrument_map_path=args.instrument_map,
            inventory_path=args.garageband_inventory,
            content=args.content,
            bpm=args.bpm,
            downbeat=args.downbeat,
            demucs_model=args.demucs_model,
            clap_model=args.clap_model,
            device=args.device,
            minimum_confidence=args.minimum_confidence,
            maximum_uncertain_share=args.maximum_uncertain_share,
            require_inventory=args.require_inventory,
            resume=args.resume,
            overwrite=args.overwrite,
            keep_work=args.keep_work,
            prepare=args.prepare,
            prepare_dry_run=args.prepare_dry_run,
            allow_low_confidence=args.allow_low_confidence,
            discard_unsaved=args.discard_unsaved,
            keep_reference_audible=args.keep_reference_audible,
            no_wait=args.no_wait,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

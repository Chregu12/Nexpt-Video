"""Compile animation specs into explicit, reviewable Motion automation plans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .spec import validate_spec


class CompileError(ValueError):
    pass


def _read_source(spec: dict[str, Any], source: str) -> Any:
    parts = source.split(".")
    current: Any = spec
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
            continue
        raise CompileError(f"binding source does not exist: {source}")
    if isinstance(current, (dict, list)):
        raise CompileError(f"binding source must resolve to a scalar: {source}")
    return current


def compile_plan(
    spec: dict[str, Any],
    *,
    project_path: str | Path | None = None,
    bindings: list[dict[str, Any]] | None = None,
    screenshot_path: str | Path | None = None,
    open_export_dialog: bool = False,
    check_assets: bool = False,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    normalized = validate_spec(spec, base_dir=base_dir, check_assets=check_assets)
    warnings: list[str] = []
    steps: list[dict[str, Any]] = []
    if project_path is None:
        warnings.append("A real project saved by the installed Motion version is required before live execution.")
    else:
        project = Path(project_path).expanduser().resolve()
        if project.suffix.lower() not in {".motn", ".moti", ".motr", ".moef"}:
            raise CompileError(f"unsupported Motion project extension: {project.suffix}")
        steps.append({"action": "open", "path": str(project), "wait_seconds": 1.5})

    for index, binding in enumerate(bindings or []):
        if not isinstance(binding, dict):
            raise CompileError(f"binding {index} must be an object")
        source = binding.get("source")
        path = binding.get("ui_path")
        if not isinstance(source, str) or not isinstance(path, str):
            raise CompileError(f"binding {index} requires source and ui_path")
        steps.append({"action": "set_ui", "path": path, "value": _read_source(normalized, source)})
    if project_path is not None:
        steps.append({"action": "save"})
    if open_export_dialog:
        steps.append({"action": "export_dialog"})
    if screenshot_path is not None:
        steps.append({"action": "screenshot", "path": str(Path(screenshot_path).expanduser().resolve())})
    return {
        "version": 1,
        "name": f"Motion: {normalized['project']['name']}",
        "spec_summary": {
            "duration": normalized["project"]["duration"],
            "duration_frames": normalized["project"]["duration_frames"],
            "layer_count": len(normalized["layers"]),
        },
        "requires_motion_template": project_path is None,
        "warnings": warnings,
        "steps": steps,
    }

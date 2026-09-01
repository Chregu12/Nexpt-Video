"""Validation and normalization for the versioned Motion animation spec."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


class SpecError(ValueError):
    """Raised when an animation spec is unsafe or internally inconsistent."""


LAYER_TYPES = {"text", "image", "video", "shape", "group"}
EASINGS = {"linear", "ease_in", "ease_out", "ease_in_out", "hold"}
ANIMATABLE = {
    "opacity", "position", "position.x", "position.y", "scale", "scale.x",
    "scale.y", "rotation", "anchor", "color", "blur", "crop", "text",
}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SpecError(f"{label} must be a finite number")
    value = float(value)
    if minimum is not None and value < minimum:
        raise SpecError(f"{label} must be >= {minimum}")
    return value


def validate_spec(spec: Any, *, base_dir: str | Path | None = None, check_assets: bool = False) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise SpecError("animation spec must be an object")
    if spec.get("version") != 1:
        raise SpecError("version must be 1")
    project = spec.get("project")
    if not isinstance(project, dict):
        raise SpecError("project must be an object")
    for field in ("width", "height"):
        value = _number(project.get(field), f"project.{field}", minimum=1)
        if not value.is_integer():
            raise SpecError(f"project.{field} must be an integer")
    fps = _number(project.get("fps"), "project.fps", minimum=1)
    if fps > 240:
        raise SpecError("project.fps must be <= 240")
    duration = _number(project.get("duration"), "project.duration", minimum=0.001)
    background = project.get("background", "#000000")
    if not isinstance(background, str) or not HEX_COLOR.match(background):
        raise SpecError("project.background must be #RRGGBB or #RRGGBBAA")

    layers = spec.get("layers")
    if not isinstance(layers, list):
        raise SpecError("layers must be an array")
    seen: set[str] = set()
    root = Path(base_dir).resolve() if base_dir is not None else Path.cwd()
    for index, layer in enumerate(layers):
        label = f"layers[{index}]"
        if not isinstance(layer, dict):
            raise SpecError(f"{label} must be an object")
        layer_id = layer.get("id")
        if not isinstance(layer_id, str) or not re.match(r"^[A-Za-z][A-Za-z0-9_.-]*$", layer_id):
            raise SpecError(f"{label}.id must be a stable identifier")
        if layer_id in seen:
            raise SpecError(f"duplicate layer id: {layer_id}")
        seen.add(layer_id)
        layer_type = layer.get("type")
        if layer_type not in LAYER_TYPES:
            raise SpecError(f"{label}.type must be one of {sorted(LAYER_TYPES)}")
        start = _number(layer.get("start", 0), f"{label}.start", minimum=0)
        layer_duration = _number(layer.get("duration", duration - start), f"{label}.duration", minimum=0.001)
        if start + layer_duration > duration + 1e-9:
            raise SpecError(f"{label} extends past project.duration")
        if layer_type == "text" and not isinstance(layer.get("text", ""), str):
            raise SpecError(f"{label}.text must be a string")
        if layer_type in {"image", "video"}:
            asset = layer.get("asset")
            if not isinstance(asset, str) or not asset:
                raise SpecError(f"{label}.asset is required")
            if check_assets and not (root / asset).resolve().is_file():
                raise SpecError(f"asset does not exist: {asset}")
        keyframes = layer.get("keyframes", [])
        if not isinstance(keyframes, list):
            raise SpecError(f"{label}.keyframes must be an array")
        last_by_property: dict[str, float] = {}
        for kindex, keyframe in enumerate(keyframes):
            klabel = f"{label}.keyframes[{kindex}]"
            if not isinstance(keyframe, dict):
                raise SpecError(f"{klabel} must be an object")
            prop = keyframe.get("property")
            if prop not in ANIMATABLE:
                raise SpecError(f"{klabel}.property is unsupported: {prop!r}")
            time_value = _number(keyframe.get("time"), f"{klabel}.time", minimum=0)
            if time_value > layer_duration + 1e-9:
                raise SpecError(f"{klabel}.time exceeds layer duration")
            if time_value < last_by_property.get(prop, -1):
                raise SpecError(f"keyframes for {prop!r} must be ordered")
            last_by_property[prop] = time_value
            if keyframe.get("easing", "linear") not in EASINGS:
                raise SpecError(f"{klabel}.easing must be one of {sorted(EASINGS)}")
            if "value" not in keyframe:
                raise SpecError(f"{klabel}.value is required")
    return normalize_spec(spec)


def normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic copy with explicit defaults and frame metadata."""
    result = deepcopy(spec)
    project = result.setdefault("project", {})
    project.setdefault("name", "Untitled Motion Animation")
    project.setdefault("background", "#000000")
    project["duration_frames"] = round(float(project["duration"]) * float(project["fps"]))
    for layer in result.setdefault("layers", []):
        layer.setdefault("name", layer["id"])
        layer.setdefault("start", 0)
        layer.setdefault("duration", float(project["duration"]) - float(layer["start"]))
        layer.setdefault("position", [float(project["width"]) / 2, float(project["height"]) / 2])
        layer.setdefault("keyframes", [])
        layer["start_frame"] = round(float(layer["start"]) * float(project["fps"]))
        layer["duration_frames"] = round(float(layer["duration"]) * float(project["fps"]))
    return result

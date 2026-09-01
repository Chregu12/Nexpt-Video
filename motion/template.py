"""Safe operations on real Apple Motion template files.

The bridge deliberately does not generate undocumented .motn XML.  Instead it
copies a project saved by the installed Motion version and replaces explicit,
user-owned placeholders such as ``{{MOTION:TITLE}}``.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path
from typing import Any, Mapping


TOKEN = re.compile(r"\{\{MOTION:([A-Z][A-Z0-9_]*)\}\}")
MAX_TEMPLATE_BYTES = 64 * 1024 * 1024


class TemplateError(ValueError):
    pass


def inspect_project(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise TemplateError(f"Motion project does not exist: {source}")
    data = source.read_bytes()
    result: dict[str, Any] = {
        "path": str(source),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "placeholders": [],
        "text": False,
        "xml": False,
    }
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return result
    result["text"] = True
    result["placeholders"] = sorted(set(TOKEN.findall(text)))
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return result
    result.update({"xml": True, "xml_root": root.tag})
    return result


def render_template(
    template_path: str | Path,
    output_path: str | Path,
    values: Mapping[str, Any],
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    source = Path(template_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if source == output:
        raise TemplateError("template and output must be different files")
    if not source.is_file():
        raise TemplateError(f"Motion template does not exist: {source}")
    if source.stat().st_size > MAX_TEMPLATE_BYTES:
        raise TemplateError("Motion template is larger than 64 MiB")
    if output.exists() and not overwrite:
        raise TemplateError(f"output already exists: {output}")
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise TemplateError("template is not UTF-8 text; use a text-based project saved by Motion") from exc
    found = set(TOKEN.findall(text))
    supplied = set(values)
    unknown = supplied - found
    missing = found - supplied
    if unknown:
        raise TemplateError(f"values have no matching placeholder: {sorted(unknown)}")
    if missing:
        raise TemplateError(f"unresolved Motion placeholders: {sorted(missing)}")

    rendered = TOKEN.sub(lambda match: escape(str(values[match.group(1)]), quote=True), text)
    try:
        ET.fromstring(rendered)
    except ET.ParseError as exc:
        raise TemplateError(f"rendered Motion project is not valid XML: {exc}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return inspect_project(output)

#!/usr/bin/env python3
"""Command-line interface for the Nexpt Apple Motion bridge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import core
from .compiler import compile_plan
from .spec import validate_spec
from .template import inspect_project, render_template


def _json_file(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Safe Apple Motion automation bridge")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("capabilities", "status", "launch", "menu-map", "save", "export-dialog"):
        sub.add_parser(name)
    opened = sub.add_parser("open"); opened.add_argument("path")
    inspect = sub.add_parser("inspect-project"); inspect.add_argument("path")
    validate = sub.add_parser("validate-spec"); validate.add_argument("path"); validate.add_argument("--check-assets", action="store_true")
    render = sub.add_parser("render-template")
    render.add_argument("template"); render.add_argument("output"); render.add_argument("values")
    render.add_argument("--overwrite", action="store_true")
    compile_cmd = sub.add_parser("compile-plan")
    compile_cmd.add_argument("spec"); compile_cmd.add_argument("--project"); compile_cmd.add_argument("--bindings")
    compile_cmd.add_argument("--screenshot"); compile_cmd.add_argument("--export-dialog", action="store_true")
    run = sub.add_parser("run-plan"); run.add_argument("path"); run.add_argument("--dry-run", action="store_true")
    snapshot = sub.add_parser("ui-snapshot"); snapshot.add_argument("--max-depth", type=int, default=3); snapshot.add_argument("--max-items", type=int, default=400)
    find = sub.add_parser("find-ui"); find.add_argument("query")
    shot = sub.add_parser("screenshot"); shot.add_argument("path")
    shortcut = sub.add_parser("shortcut"); shortcut.add_argument("keys")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    actions = {
        "capabilities": lambda: core.capabilities(), "status": core.status, "launch": core.launch,
        "open": lambda: core.open_project(args.path), "inspect-project": lambda: inspect_project(args.path),
        "validate-spec": lambda: validate_spec(_json_file(args.path), base_dir=Path(args.path).parent, check_assets=args.check_assets),
        "render-template": lambda: render_template(args.template, args.output, _json_file(args.values), overwrite=args.overwrite),
        "compile-plan": lambda: compile_plan(_json_file(args.spec), project_path=args.project, bindings=_json_file(args.bindings) if args.bindings else None, screenshot_path=args.screenshot, open_export_dialog=args.export_dialog, base_dir=Path(args.spec).parent),
        "run-plan": lambda: core.run_plan(_json_file(args.path), dry_run=args.dry_run),
        "menu-map": core.menu_map, "ui-snapshot": lambda: core.ui_snapshot(max_depth=args.max_depth, max_items=args.max_items),
        "find-ui": lambda: core.find_ui_elements(args.query), "screenshot": lambda: core.screenshot(args.path),
        "shortcut": lambda: core.shortcut(args.keys), "save": core.save, "export-dialog": core.export_dialog,
    }
    print(json.dumps(actions[args.command](), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

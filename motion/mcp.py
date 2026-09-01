#!/usr/bin/env python3
"""Small dependency-free MCP stdio server for Apple Motion."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from . import core
from .compiler import compile_plan
from .spec import validate_spec
from .template import inspect_project, render_template


TOOLS = [
    ("motion_capabilities", "Describe supported workflows and honest limitations.", {}),
    ("motion_status", "Check macOS, Motion installation and running state.", {}),
    ("motion_launch", "Launch Apple Motion.", {}),
    ("motion_open", "Open a Motion project/template.", {"path": {"type": "string"}}),
    ("motion_validate_animation", "Validate and normalize an animation spec.", {"spec": {"type": "object"}}),
    ("motion_inspect_project", "Inspect a Motion file without changing it.", {"path": {"type": "string"}}),
    ("motion_render_template", "Copy and safely fill an explicit Motion template.", {"template_path": {"type": "string"}, "output_path": {"type": "string"}, "values": {"type": "object"}, "overwrite": {"type": "boolean"}}),
    ("motion_compile_plan", "Compile a spec and optional AX bindings into a reviewable plan.", {"spec": {"type": "object"}, "project_path": {"type": "string"}, "bindings": {"type": "array"}, "screenshot_path": {"type": "string"}, "open_export_dialog": {"type": "boolean"}}),
    ("motion_run_plan", "Run or dry-run a guarded Motion plan.", {"plan": {"type": "object"}, "dry_run": {"type": "boolean"}}),
    ("motion_menu_map", "List current Motion menu items.", {}),
    ("motion_find_menu_items", "Find menu items by text.", {"query": {"type": "string"}}),
    ("motion_click_menu", "Click an exact Motion menu item.", {"menu": {"type": "string"}, "item": {"type": "string"}}),
    ("motion_ui_snapshot", "Inspect the active Motion window's AX tree.", {"max_depth": {"type": "integer"}, "max_items": {"type": "integer"}}),
    ("motion_find_ui_elements", "Find AX elements by role, name or value.", {"query": {"type": "string"}, "max_depth": {"type": "integer"}, "max_items": {"type": "integer"}}),
    ("motion_ui_info", "Read an exact AX path.", {"path": {"type": "string"}}),
    ("motion_click_ui", "Click an exact AX path.", {"path": {"type": "string"}}),
    ("motion_set_ui_value", "Set the value of an exact AX path.", {"path": {"type": "string"}, "value": {}}),
    ("motion_shortcut", "Send a shortcut such as cmd+s.", {"keys": {"type": "string"}}),
    ("motion_type_text", "Type text into the focused Motion control.", {"text": {"type": "string"}}),
    ("motion_screenshot", "Capture the current display for visual verification.", {"path": {"type": "string"}}),
    ("motion_save", "Save the active Motion document.", {}),
    ("motion_export_dialog", "Open Export Movie (Command-E), without confirming.", {}),
]


def tool_definitions() -> list[dict[str, Any]]:
    required_by_tool = {
        "motion_open": ["path"], "motion_validate_animation": ["spec"],
        "motion_inspect_project": ["path"],
        "motion_render_template": ["template_path", "output_path", "values"],
        "motion_compile_plan": ["spec"], "motion_run_plan": ["plan"],
        "motion_find_menu_items": ["query"], "motion_click_menu": ["menu", "item"],
        "motion_find_ui_elements": ["query"], "motion_ui_info": ["path"],
        "motion_click_ui": ["path"], "motion_set_ui_value": ["path", "value"],
        "motion_shortcut": ["keys"], "motion_type_text": ["text"],
        "motion_screenshot": ["path"],
    }
    return [{"name": name, "description": description,
             "inputSchema": {"type": "object", "properties": properties,
                             "required": required_by_tool.get(name, []), "additionalProperties": False}}
            for name, description, properties in TOOLS]


def _dispatch(name: str, args: dict[str, Any]) -> Any:
    calls: dict[str, Callable[[], Any]] = {
        "motion_capabilities": lambda: core.capabilities(),
        "motion_status": core.status,
        "motion_launch": core.launch,
        "motion_open": lambda: core.open_project(args["path"]),
        "motion_validate_animation": lambda: validate_spec(args["spec"]),
        "motion_inspect_project": lambda: inspect_project(args["path"]),
        "motion_render_template": lambda: render_template(args["template_path"], args["output_path"], args["values"], overwrite=args.get("overwrite", False)),
        "motion_compile_plan": lambda: compile_plan(args["spec"], project_path=args.get("project_path"), bindings=args.get("bindings"), screenshot_path=args.get("screenshot_path"), open_export_dialog=args.get("open_export_dialog", False)),
        "motion_run_plan": lambda: core.run_plan(args["plan"], dry_run=args.get("dry_run", False)),
        "motion_menu_map": core.menu_map,
        "motion_find_menu_items": lambda: core.find_menu_items(args["query"]),
        "motion_click_menu": lambda: core.click_menu(args["menu"], args["item"]),
        "motion_ui_snapshot": lambda: core.ui_snapshot(max_depth=args.get("max_depth", 3), max_items=args.get("max_items", 400)),
        "motion_find_ui_elements": lambda: core.find_ui_elements(args["query"], max_depth=args.get("max_depth", 5), max_items=args.get("max_items", 800)),
        "motion_ui_info": lambda: core.ui_info_path(args["path"]),
        "motion_click_ui": lambda: core.click_ui_path(args["path"]),
        "motion_set_ui_value": lambda: core.set_ui_value(args["path"], args["value"]),
        "motion_shortcut": lambda: core.shortcut(args["keys"]),
        "motion_type_text": lambda: core.type_text(args["text"]),
        "motion_screenshot": lambda: core.screenshot(args["path"]),
        "motion_save": core.save,
        "motion_export_dialog": core.export_dialog,
    }
    if name not in calls:
        raise ValueError(f"unknown tool: {name}")
    return calls[name]()


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "nexpt-motion-bridge", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": tool_definitions()}
    elif method == "tools/call":
        params = request.get("params", {})
        try:
            value = _dispatch(params.get("name", ""), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}], "isError": False}
        except Exception as exc:
            result = {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = handle(request)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Combined GarageBand MCP server with the NEXPT generative extension."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_BRIDGE = ROOT / "tools" / "garageband-llm-bridge"
if str(UPSTREAM_BRIDGE) not in sys.path:
    sys.path.insert(0, str(UPSTREAM_BRIDGE))

import garageband_mcp as upstream_mcp

from garageband.generative import (
    build_garageband_handoff,
    build_generation_plan,
    generate_and_handoff,
    run_generation,
    status,
)


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


GENERATION_REQUEST = {
    "type": "object",
    "description": "ACE-Step request. action: generate, cover, repaint, extract, lego or complete.",
}

GENERATIVE_TOOLS = [
    _tool(
        "garageband_ai_status",
        "Check the vendored claude-music/ACE-Step runtime without generating audio.",
        {"config_path": {"type": "string"}},
    ),
    _tool(
        "garageband_ai_plan",
        "Validate a generative music request and return the exact non-shell command without executing it.",
        {"request": GENERATION_REQUEST, "config_path": {"type": "string"}},
        ["request"],
    ),
    _tool(
        "garageband_ai_generate",
        "Generate or edit audio with the pinned claude-music/ACE-Step engine and verify every output by SHA-256.",
        {"request": GENERATION_REQUEST, "config_path": {"type": "string"}},
        ["request"],
    ),
    _tool(
        "garageband_ai_handoff_plan",
        "Plan either exact audio import or approximate editable reconstruction of existing audio in GarageBand.",
        {
            "audio_path": {"type": "string"},
            "project_dir": {"type": "string"},
            "transcription_quality": {
                "type": "string",
                "enum": ["auto", "high", "fast"],
            },
            "live": {"type": "boolean", "default": False},
            "acknowledge_live_ui": {"type": "boolean", "default": False},
        },
        ["audio_path"],
    ),
    _tool(
        "garageband_ai_generate_and_handoff",
        "Generate a candidate and return verified GarageBand import/reconstruction handoff commands; dry_run performs no writes.",
        {
            "request": GENERATION_REQUEST,
            "config_path": {"type": "string"},
            "dry_run": {"type": "boolean", "default": False},
        },
        ["request"],
    ),
]


def tool_definitions() -> list[dict[str, Any]]:
    combined = [*upstream_mcp.TOOLS, *GENERATIVE_TOOLS]
    names = [tool["name"] for tool in combined]
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate GarageBand MCP tool name")
    return combined


def _content(value: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"ok": True, "data": value}, ensure_ascii=False, indent=2
                ),
            }
        ],
        "isError": False,
    }


def _call_generative(name: str, args: dict[str, Any]) -> dict[str, Any]:
    calls: dict[str, Callable[[], Any]] = {
        "garageband_ai_status": lambda: status(args.get("config_path")),
        "garageband_ai_plan": lambda: build_generation_plan(
            args["request"], config_path=args.get("config_path")
        ),
        "garageband_ai_generate": lambda: run_generation(
            args["request"], config_path=args.get("config_path")
        ),
        "garageband_ai_generate_and_handoff": lambda: generate_and_handoff(
            args["request"],
            config_path=args.get("config_path"),
            dry_run=args.get("dry_run", False),
        ),
    }
    if name == "garageband_ai_handoff_plan":
        if args.get("live") and not args.get("acknowledge_live_ui"):
            raise ValueError(
                "acknowledge_live_ui=true is required for a plan that touches GarageBand"
            )
        return _content(
            build_garageband_handoff(
                args["audio_path"],
                project_dir=args.get("project_dir"),
                transcription_quality=args.get("transcription_quality", "high"),
                live=args.get("live", False),
            )
        )
    if name not in calls:
        raise ValueError(f"unknown generative GarageBand tool: {name}")
    return _content(calls[name]())


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "nexpt-garageband-bridge", "version": "1.0.0"},
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tool_definitions()},
        }
    if method == "tools/call":
        params = message.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        try:
            if name.startswith("garageband_ai_"):
                result = _call_generative(name, arguments)
            else:
                result = upstream_mcp._call_tool(name, arguments)
                result.setdefault("isError", False)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:  # noqa: BLE001 - MCP boundary must contain tool failures
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "ok": False,
                                    "error": str(exc),
                                    "type": type(exc).__name__,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ],
                    "isError": True,
                },
            }
    if request_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = handle(message)
        except Exception as exc:  # noqa: BLE001 - malformed input must not stop the stdio server
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": str(exc)},
            }
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Dependency-free MCP stdio server for Higgsfield Seedance 2.0."""

from __future__ import annotations

import json
import sys
from typing import Any

from .api import (
    HiggsfieldClient,
    HiggsfieldSettings,
    build_plan,
    generate_seedance,
    status,
)

SEEDANCE_REQUEST = {
    "type": "object",
    "description": "Validated Seedance 2.0 prompt, options and optional local/HTTPS references.",
}


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


TOOLS = [
    _tool(
        "higgsfield_status",
        "Check Seedance API configuration without exposing credentials or making a paid request.",
        {},
    ),
    _tool(
        "higgsfield_seedance_plan",
        "Validate and normalize a Seedance 2.0 request without uploads or generation.",
        {"request": SEEDANCE_REQUEST},
        ["request"],
    ),
    _tool(
        "higgsfield_seedance_submit",
        "Upload local references and submit a paid asynchronous Seedance 2.0 request.",
        {
            "request": SEEDANCE_REQUEST,
            "acknowledge_paid_generation": {"type": "boolean"},
        },
        ["request", "acknowledge_paid_generation"],
    ),
    _tool(
        "higgsfield_seedance_generate",
        "Submit, poll, download and verify a paid Seedance 2.0 MP4, then return Motion and Final Cut handoff data.",
        {
            "request": SEEDANCE_REQUEST,
            "acknowledge_paid_generation": {"type": "boolean"},
        },
        ["request", "acknowledge_paid_generation"],
    ),
    _tool(
        "higgsfield_request_status",
        "Read one Higgsfield request status URL returned by submission.",
        {"status_url": {"type": "string"}},
        ["status_url"],
    ),
    _tool(
        "higgsfield_request_cancel",
        "Cancel a queued Higgsfield request using its returned cancel URL.",
        {"cancel_url": {"type": "string"}},
        ["cancel_url"],
    ),
]


def tool_definitions() -> list[dict[str, Any]]:
    return TOOLS


def _dispatch(name: str, args: dict[str, Any]) -> Any:
    if name == "higgsfield_status":
        return status()
    if name == "higgsfield_seedance_plan":
        return build_plan(args["request"])
    if name in {"higgsfield_seedance_submit", "higgsfield_seedance_generate"}:
        return generate_seedance(
            args["request"],
            acknowledge_paid_generation=args["acknowledge_paid_generation"],
            wait=name.endswith("_generate"),
        )
    settings = HiggsfieldSettings.from_env(require_credentials=True)
    client = HiggsfieldClient(settings)
    if name == "higgsfield_request_status":
        return client.get_status(args["status_url"])
    if name == "higgsfield_request_cancel":
        return client.cancel(args["cancel_url"])
    raise ValueError(f"unknown Higgsfield tool: {name}")


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nexpt-higgsfield-bridge", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {"tools": tool_definitions()}
    elif method == "tools/call":
        params = message.get("params", {})
        try:
            value = _dispatch(params.get("name", ""), params.get("arguments") or {})
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(value, ensure_ascii=False, indent=2),
                    }
                ],
                "isError": False,
            }
        except Exception as exc:  # noqa: BLE001 - MCP boundary contains failures
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "ok": False,
                                "type": type(exc).__name__,
                                "error": str(exc),
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
                "isError": True,
            }
    else:
        if request_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handle(request)
        except Exception as exc:  # noqa: BLE001 - malformed input cannot stop server
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

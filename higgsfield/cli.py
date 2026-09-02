#!/usr/bin/env python3
"""Command-line interface for the Higgsfield Seedance adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .api import (
    HiggsfieldClient,
    HiggsfieldSettings,
    build_plan,
    generate_seedance,
    status,
)


def _json_file(path: str) -> Any:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("request file must contain a JSON object")
    return value


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Higgsfield Seedance 2.0 API bridge")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    plan = sub.add_parser("plan")
    plan.add_argument("request")
    submit = sub.add_parser("submit")
    submit.add_argument("request")
    submit.add_argument("--acknowledge-paid-generation", action="store_true")
    generate = sub.add_parser("generate")
    generate.add_argument("request")
    generate.add_argument("--acknowledge-paid-generation", action="store_true")
    get = sub.add_parser("get")
    get.add_argument("status_url")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("cancel_url")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "status":
        result = status()
    elif args.command == "plan":
        result = build_plan(_json_file(args.request))
    elif args.command in {"submit", "generate"}:
        result = generate_seedance(
            _json_file(args.request),
            acknowledge_paid_generation=args.acknowledge_paid_generation,
            wait=args.command == "generate",
        )
    else:
        settings = HiggsfieldSettings.from_env(require_credentials=True)
        client = HiggsfieldClient(settings)
        result = (
            client.get_status(args.status_url)
            if args.command == "get"
            else client.cancel(args.cancel_url)
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

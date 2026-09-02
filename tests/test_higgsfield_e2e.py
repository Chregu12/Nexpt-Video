from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / "higgsfield" / "seedance-request.example.json"
SECRET_NAMES = {
    "HIGGSFIELD_API_KEY_ID",
    "HIGGSFIELD_API_KEY_SECRET",
    "HIGGSFIELD_SEEDANCE_ENDPOINT",
    "HIGGSFIELD_API_BASE_URL",
    "HIGGSFIELD_OUTPUT_DIR",
}


def clean_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in SECRET_NAMES}


def run_module(module: str, *args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=ROOT,
        env=env or clean_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


class HiggsfieldEndToEndTests(unittest.TestCase):
    def test_public_cli_status_and_plan_are_non_mutating(self):
        status_run = run_module("higgsfield.cli", "status")
        self.assertEqual(status_run.returncode, 0, status_run.stderr)
        status_value = json.loads(status_run.stdout)
        self.assertFalse(status_value["ready"])
        self.assertFalse(status_value["credentials_configured"])

        env = clean_env()
        env["HIGGSFIELD_SEEDANCE_ENDPOINT"] = "/account/seedance-2"
        plan_run = run_module("higgsfield.cli", "plan", str(REQUEST), env=env)
        self.assertEqual(plan_run.returncode, 0, plan_run.stderr)
        plan = json.loads(plan_run.stdout)
        self.assertFalse(plan["executes"])
        self.assertEqual(plan["model"], "seedance_2_0")
        self.assertEqual(plan["request"]["resolution"], "1080p")

    def test_mcp_lists_tools_and_status_never_exposes_credentials(self):
        env = clean_env()
        env.update(
            {
                "HIGGSFIELD_API_KEY_ID": "e2e-key-id",
                "HIGGSFIELD_API_KEY_SECRET": "e2e-secret",
                "HIGGSFIELD_SEEDANCE_ENDPOINT": "/account/seedance-2",
            }
        )
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "higgsfield_status", "arguments": {}},
            },
        ]
        process = subprocess.run(
            [sys.executable, "-m", "higgsfield.mcp"],
            cwd=ROOT,
            env=env,
            input="".join(json.dumps(message) + "\n" for message in messages),
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        names = {tool["name"] for tool in responses[1]["result"]["tools"]}
        self.assertIn("higgsfield_seedance_generate", names)
        self.assertIn("higgsfield_request_cancel", names)
        self.assertFalse(responses[2]["result"]["isError"])
        self.assertNotIn("e2e-key-id", process.stdout)
        self.assertNotIn("e2e-secret", process.stdout)

    def test_mcp_paid_generation_is_blocked_without_acknowledgement(self):
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "higgsfield_seedance_generate",
                "arguments": {
                    "request": {"prompt": "must not run"},
                    "acknowledge_paid_generation": False,
                },
            },
        }
        process = subprocess.run(
            [sys.executable, "-m", "higgsfield.mcp"],
            cwd=ROOT,
            env=clean_env(),
            input=json.dumps(message) + "\n",
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        response = json.loads(process.stdout)
        self.assertTrue(response["result"]["isError"])
        self.assertIn(
            "acknowledge_paid_generation", response["result"]["content"][0]["text"]
        )


if __name__ == "__main__":
    unittest.main()

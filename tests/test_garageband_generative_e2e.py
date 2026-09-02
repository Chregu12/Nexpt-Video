from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GarageBandGenerativeE2ETests(unittest.TestCase):
    def run_python(self, *arguments: str, input_text: str | None = None):
        return subprocess.run(
            [sys.executable, *arguments],
            cwd=ROOT,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_vendored_engine_help_contract(self):
        engine = (
            ROOT
            / "tools"
            / "claude-music"
            / "skills"
            / "claude-music"
            / "scripts"
            / "music_engine.py"
        )
        result = self.run_python(str(engine), "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for action in ("generate", "cover", "repaint", "extract", "lego", "complete"):
            self.assertIn(action, result.stdout)

    def test_public_cli_plan_and_handoff_without_gpu(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ace = root / "ace-step"
            ace.mkdir()
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "ace_step_dir": str(ace),
                        "output_dir": str(root / "outputs"),
                        "defaults": {
                            "quality": "draft",
                            "format": "wav",
                            "instrumental": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            request = root / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "action": "generate",
                        "caption": "restrained kinetic typography percussion",
                        "duration": 20,
                        "bpm": 118,
                    }
                ),
                encoding="utf-8",
            )
            planned = self.run_python(
                "-m",
                "garageband.generative",
                "--config",
                str(config),
                "plan",
                str(request),
            )
            self.assertEqual(planned.returncode, 0, planned.stderr)
            plan = json.loads(planned.stdout)
            self.assertTrue(plan["ready"])
            self.assertIn("--instrumental", plan["command"])
            self.assertIn("--bpm", plan["command"])

            audio = root / "candidate.wav"
            audio.write_bytes(b"RIFF-candidate")
            handed = self.run_python(
                "-m",
                "garageband.generative",
                "handoff",
                str(audio),
                "--project-dir",
                str(root / "project"),
                "--transcription-quality",
                "fast",
            )
            self.assertEqual(handed.returncode, 0, handed.stderr)
            handoff = json.loads(handed.stdout)
            self.assertIn(
                "--prepare-dry-run", handoff["editable_reconstruction"]["command"]
            )

    def test_combined_mcp_advertises_upstream_and_generative_tools(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "garageband_capabilities",
                    "arguments": {"include_live": False},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "garageband_ai_status",
                    "arguments": {},
                },
            },
        ]
        result = self.run_python(
            "-m",
            "garageband.mcp",
            input_text="".join(json.dumps(request) + "\n" for request in requests),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([response["id"] for response in responses], [1, 2, 3, 4])
        names = {tool["name"] for tool in responses[1]["result"]["tools"]}
        self.assertIn("garageband_make_music", names)
        self.assertIn("garageband_ai_generate", names)
        self.assertIn("garageband_ai_handoff_plan", names)
        self.assertFalse(responses[2]["result"]["isError"])
        self.assertFalse(responses[3]["result"]["isError"])

    def test_combined_mcp_plan_is_non_mutating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ace = root / "ace-step"
            ace.mkdir()
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "ace_step_dir": str(ace),
                        "output_dir": str(root / "outputs"),
                        "defaults": {"quality": "draft", "format": "wav"},
                    }
                ),
                encoding="utf-8",
            )
            request = {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "garageband_ai_plan",
                    "arguments": {
                        "config_path": str(config),
                        "request": {
                            "caption": "minimal product launch drums",
                            "duration": 20,
                        },
                    },
                },
            }
            result = self.run_python(
                "-m", "garageband.mcp", input_text=json.dumps(request) + "\n"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            response = json.loads(result.stdout)
            self.assertFalse(response["result"]["isError"])
            envelope = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(envelope["data"]["ready"])
            self.assertFalse((root / "outputs").exists())


if __name__ == "__main__":
    unittest.main()

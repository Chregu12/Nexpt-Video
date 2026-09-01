import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MotionE2ETests(unittest.TestCase):
    def run_python(self, *arguments, input_text=None):
        return subprocess.run(
            [sys.executable, *arguments], cwd=ROOT, input=input_text, text=True,
            capture_output=True, timeout=15, check=False,
        )

    def test_cli_validates_example_end_to_end(self):
        result = self.run_python("-m", "motion.cli", "validate-spec", "motion/examples/nexpt-kinetic-title.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["project"]["duration_frames"], 120)
        self.assertEqual(payload["layers"][0]["id"], "headline")

    def test_cli_renders_template_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory, "base.motn")
            values = Path(directory, "values.json")
            output = Path(directory, "working.motn")
            template.write_text('<motion><text>{{MOTION:TITLE}}</text></motion>', encoding="utf-8")
            values.write_text(json.dumps({"TITLE": "NEXPT & Motion"}), encoding="utf-8")
            result = self.run_python("-m", "motion.cli", "render-template", str(template), str(output), str(values))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["xml"])
            self.assertIn("NEXPT &amp; Motion", output.read_text(encoding="utf-8"))

    def test_mcp_stdio_initialize_list_and_call(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "motion_capabilities", "arguments": {}}},
        ]
        result = self.run_python("-m", "motion.mcp", input_text="".join(json.dumps(item) + "\n" for item in requests))
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([item["id"] for item in responses], [1, 2, 3])
        self.assertGreaterEqual(len(responses[1]["result"]["tools"]), 20)
        self.assertFalse(responses[2]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()

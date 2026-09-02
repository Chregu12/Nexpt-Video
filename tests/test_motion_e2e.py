import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MotionE2ETests(unittest.TestCase):
    def run_python(self, *arguments, input_text=None, environment=None):
        process_environment = os.environ.copy()
        process_environment.update(environment or {})
        return subprocess.run(
            [sys.executable, *arguments], cwd=ROOT, input=input_text, text=True,
            capture_output=True, timeout=15, check=False, env=process_environment,
        )

    def run_mcp(self, requests):
        wire = "".join(json.dumps(item) + "\n" for item in requests)
        result = self.run_python("-m", "motion.mcp", input_text=wire)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines()]

    def mcp_payload(self, response):
        self.assertFalse(response["result"]["isError"], response)
        return json.loads(response["result"]["content"][0]["text"])

    def write_spec(self, directory, *, asset=None):
        spec = {
            "version": 1,
            "project": {
                "name": "E2E Animation",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "duration": 2.0,
                "background": "#050608",
            },
            "layers": [{
                "id": "title",
                "type": "text",
                "text": "NEXPT & Motion",
                "start": 0,
                "duration": 2.0,
                "keyframes": [
                    {"time": 0, "property": "opacity", "value": 0},
                    {"time": 0.25, "property": "opacity", "value": 1, "easing": "ease_out"},
                ],
            }],
        }
        if asset is not None:
            spec["layers"].append({
                "id": "hero",
                "type": "image",
                "asset": asset,
                "start": 0,
                "duration": 2.0,
            })
        path = Path(directory, "animation.json")
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path, spec

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

    def test_cli_full_compile_and_dry_run_workflow_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            spec_path, _ = self.write_spec(directory)
            project = Path(directory, "working.motn")
            project.write_text("<motion/>", encoding="utf-8")
            bindings = Path(directory, "bindings.json")
            bindings.write_text(json.dumps([{
                "source": "layers.0.text",
                "ui_path": "window[1]/ui[2]",
            }]), encoding="utf-8")
            screenshot = Path(directory, "proof.png")

            compiled = self.run_python(
                "-m", "motion.cli", "compile-plan", str(spec_path),
                "--project", str(project), "--bindings", str(bindings),
                "--screenshot", str(screenshot), "--export-dialog",
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            plan = json.loads(compiled.stdout)
            self.assertEqual(
                [step["action"] for step in plan["steps"]],
                ["open", "set_ui", "save", "export_dialog", "screenshot"],
            )
            self.assertEqual(plan["steps"][1]["value"], "NEXPT & Motion")

            plan_path = Path(directory, "plan.json")
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            before_project = project.read_bytes()
            dry_run = self.run_python("-m", "motion.cli", "run-plan", str(plan_path), "--dry-run")
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            result = json.loads(dry_run.stdout)
            self.assertTrue(result["dry_run"])
            self.assertEqual(len(result["steps"]), 5)
            self.assertEqual(project.read_bytes(), before_project)
            self.assertFalse(screenshot.exists())

    def test_cli_asset_validation_covers_success_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            spec_path, _ = self.write_spec(directory, asset="hero.png")
            missing = self.run_python("-m", "motion.cli", "validate-spec", str(spec_path), "--check-assets")
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("asset does not exist", missing.stderr)

            Path(directory, "hero.png").write_bytes(b"fake-png-for-path-validation")
            valid = self.run_python("-m", "motion.cli", "validate-spec", str(spec_path), "--check-assets")
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(len(json.loads(valid.stdout)["layers"]), 2)

    def test_cli_template_overwrite_protection_preserves_first_result(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory, "base.motn")
            values = Path(directory, "values.json")
            output = Path(directory, "working.motn")
            template.write_text("<motion>{{MOTION:TITLE}}</motion>", encoding="utf-8")
            values.write_text(json.dumps({"TITLE": "First"}), encoding="utf-8")
            first = self.run_python("-m", "motion.cli", "render-template", str(template), str(output), str(values))
            self.assertEqual(first.returncode, 0, first.stderr)
            first_bytes = output.read_bytes()

            values.write_text(json.dumps({"TITLE": "Second"}), encoding="utf-8")
            second = self.run_python("-m", "motion.cli", "render-template", str(template), str(output), str(values))
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("output already exists", second.stderr)
            self.assertEqual(output.read_bytes(), first_bytes)

    def test_mcp_stdio_initialize_list_and_call(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "motion_capabilities", "arguments": {}}},
        ]
        responses = self.run_mcp(requests)
        self.assertEqual([item["id"] for item in responses], [1, 2, 3])
        self.assertGreaterEqual(len(responses[1]["result"]["tools"]), 20)
        self.assertFalse(responses[2]["result"]["isError"])

    def test_mcp_complete_file_workflow_in_one_server_session(self):
        with tempfile.TemporaryDirectory() as directory:
            _, spec = self.write_spec(directory)
            template = Path(directory, "base.motn")
            output = Path(directory, "working.motn")
            template.write_text(
                '<motion title="{{MOTION:TITLE}}"><accent>{{MOTION:COLOR}}</accent></motion>',
                encoding="utf-8",
            )
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                    "name": "motion_validate_animation", "arguments": {"spec": spec},
                }},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "name": "motion_render_template", "arguments": {
                        "template_path": str(template), "output_path": str(output),
                        "values": {"TITLE": "NEXPT & Motion", "COLOR": "#6E5BFF"},
                    },
                }},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                    "name": "motion_inspect_project", "arguments": {"path": str(output)},
                }},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
                    "name": "motion_compile_plan", "arguments": {
                        "spec": spec, "project_path": str(output),
                        "bindings": [{"source": "layers.0.text", "ui_path": "window[1]/ui[1]"}],
                        "open_export_dialog": True,
                    },
                }},
            ]
            first_responses = self.run_mcp(requests)
            self.assertEqual([response["id"] for response in first_responses], [1, 2, 3, 4, 5])
            normalized = self.mcp_payload(first_responses[1])
            rendered = self.mcp_payload(first_responses[2])
            inspected = self.mcp_payload(first_responses[3])
            plan = self.mcp_payload(first_responses[4])
            self.assertEqual(normalized["project"]["duration_frames"], 60)
            self.assertTrue(rendered["xml"])
            self.assertEqual(inspected["sha256"], rendered["sha256"])
            self.assertEqual(inspected["placeholders"], [])
            self.assertEqual(plan["steps"][1]["value"], "NEXPT & Motion")

            dry_run_responses = self.run_mcp([{
                "jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
                    "name": "motion_run_plan", "arguments": {"plan": plan, "dry_run": True},
                },
            }])
            dry_run = self.mcp_payload(dry_run_responses[0])
            self.assertTrue(dry_run["ok"])
            self.assertTrue(dry_run["dry_run"])
            self.assertEqual(len(dry_run["steps"]), len(plan["steps"]))
            self.assertIn("NEXPT &amp; Motion", output.read_text(encoding="utf-8"))

    def test_mcp_tool_failure_is_isolated_from_following_request(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory, "missing.motn")
            output = Path(directory, "working.motn")
            responses = self.run_mcp([
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                    "name": "motion_render_template", "arguments": {
                        "template_path": str(missing), "output_path": str(output), "values": {},
                    },
                }},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                    "name": "motion_status", "arguments": {},
                }},
            ])
            self.assertTrue(responses[0]["result"]["isError"])
            self.assertIn("does not exist", responses[0]["result"]["content"][0]["text"])
            status = self.mcp_payload(responses[1])
            self.assertIn("supported", status)
            self.assertFalse(output.exists())

    def test_mcp_malformed_json_returns_parse_error_and_keeps_serving(self):
        wire = "not-json\n" + json.dumps({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "motion_status", "arguments": {}},
        }) + "\n"
        result = self.run_python("-m", "motion.mcp", input_text=wire)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["id"], 9)
        self.assertFalse(responses[1]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from motion import core
from motion.compiler import CompileError, compile_plan
from tests.test_motion_spec import sample_spec


class MotionCoreTests(unittest.TestCase):
    @patch("motion.core.platform.system", return_value="Linux")
    def test_status_is_safe_off_macos(self, _system):
        self.assertEqual(core.status()["supported"], False)
        self.assertEqual(core.status()["running"], False)

    def test_shortcut_validation_happens_before_live_call(self):
        with self.assertRaisesRegex(core.MotionError, "final shortcut"):
            core.shortcut("cmd+enter")

    def test_run_plan_dry_run_has_no_live_effects(self):
        plan = {"version": 1, "steps": [{"action": "launch"}, {"action": "shortcut", "keys": "cmd+s"}]}
        result = core.run_plan(plan, dry_run=True)
        self.assertTrue(result["ok"]); self.assertEqual(len(result["steps"]), 2)

    def test_compile_plan_with_binding(self):
        plan = compile_plan(sample_spec(), project_path="/tmp/demo.motn",
                            bindings=[{"source": "layers.0.text", "ui_path": "window[1]/ui[2]"}],
                            open_export_dialog=True)
        self.assertEqual([step["action"] for step in plan["steps"]], ["open", "set_ui", "save", "export_dialog"])
        self.assertEqual(plan["steps"][1]["value"], "Hello")

    def test_compile_plan_explains_missing_template(self):
        plan = compile_plan(sample_spec())
        self.assertTrue(plan["requires_motion_template"]); self.assertTrue(plan["warnings"])

    def test_compile_plan_rejects_unknown_binding(self):
        with self.assertRaisesRegex(CompileError, "does not exist"):
            compile_plan(sample_spec(), bindings=[{"source": "layers.8.text", "ui_path": "window[1]"}])


if __name__ == "__main__":
    unittest.main()

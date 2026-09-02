"""Opt-in checks against a real macOS installation of Apple Motion.

Run manually on the target Mac with:
    MOTION_LIVE_E2E=1 python3 -m unittest tests.test_motion_live_e2e -v

Optionally set MOTION_LIVE_PROJECT to a disposable Motion project.  The test
opens but never saves or exports it.
"""

import os
import platform
import tempfile
import unittest
from pathlib import Path

from motion import core


LIVE = os.environ.get("MOTION_LIVE_E2E") == "1"


@unittest.skipUnless(LIVE and platform.system() == "Darwin", "requires MOTION_LIVE_E2E=1 on macOS")
class MotionLiveE2ETests(unittest.TestCase):
    def test_motion_launch_accessibility_snapshot_and_screenshot(self):
        status = core.status()
        self.assertTrue(status["supported"])
        self.assertTrue(status["installed"], f"Motion not installed at {status['app_path']}")

        launched = core.launch(wait_seconds=2)
        self.assertTrue(launched["running"])

        project = os.environ.get("MOTION_LIVE_PROJECT")
        if project:
            opened = core.open_project(project, wait_seconds=2)
            self.assertEqual(opened["opened"], str(Path(project).expanduser().resolve()))

        snapshot = core.ui_snapshot(max_depth=2, max_items=150)
        self.assertGreater(len(snapshot["elements"]), 0)
        self.assertEqual(snapshot["elements"][0]["path"], "window[1]")

        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory, "motion-live-proof.png")
            result = core.screenshot(proof)
            self.assertGreater(result["size"], 0)
            self.assertTrue(proof.is_file())


if __name__ == "__main__":
    unittest.main()

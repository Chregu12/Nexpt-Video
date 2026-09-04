"""Opt-in actual checkpoint inference; default CI never downloads models.

NEXPT_RUN_CDX_LIVE=1 NEXPT_CDX_CONFIG=/absolute/config.json \
NEXPT_CDX_LIVE_SOURCE=/absolute/owned-reference.mp4 \
python3 -m unittest discover -s tests -p test_cdx_live_e2e.py -v
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

from cdx_runtime import smoke_test, verify_receipt
from cinematic_separation import CDX_REVISION, CdxSeparator


@unittest.skipUnless(os.environ.get("NEXPT_RUN_CDX_LIVE") == "1",
                     "requires explicit NEXPT_RUN_CDX_LIVE=1 and trusted local model/source")
class CdxLiveE2ETests(unittest.TestCase):
    def test_real_checkpoint_to_stems_and_verified_receipt(self):
        # Once explicitly requested, unavailable dependencies/config are test
        # failures, not a misleading successful suite of skipped live tests.
        self.assertTrue(os.environ.get("NEXPT_CDX_CONFIG"), "Set NEXPT_CDX_CONFIG")
        self.assertTrue(os.environ.get("NEXPT_CDX_LIVE_SOURCE"), "Set NEXPT_CDX_LIVE_SOURCE")
        config = Path(os.environ["NEXPT_CDX_CONFIG"]).expanduser().resolve()
        source = Path(os.environ["NEXPT_CDX_LIVE_SOURCE"]).expanduser().resolve()
        backend = CdxSeparator(config)
        backend.ensure_ready()
        self.assertEqual(backend.settings["revision"], CDX_REVISION,
                         "Live acceptance test requires the documented upstream revision")
        self.assertEqual(backend.settings.get("runner"), "safe-pytorch")
        with tempfile.TemporaryDirectory(prefix="nexpt-cdx-live-") as temporary:
            destination = Path(temporary) / "result"
            result = smoke_test(source, config=config, output_dir=destination, seconds=5,
                                device=os.environ.get("NEXPT_CDX_LIVE_DEVICE", "cpu"), timeout=600)
            self.assertTrue(result["runtime_verified"])
            self.assertTrue(result["mix_consistency"]["passed"])
            self.assertFalse(result["model_accuracy_verified"])
            self.assertEqual(result["processing"]["provenance"]["runner"], "safe-pytorch")
            self.assertTrue(verify_receipt(destination / "smoke-result.json", config=config)["runtime_verified"])


if __name__ == "__main__":
    unittest.main()

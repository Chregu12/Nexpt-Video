"""Opt-in known-stem model acceptance, separate from simulated CLI tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

from cinematic_separation import CdxSeparator
from separation_benchmark import load_corpus, run_cdx


@unittest.skipUnless(os.environ.get("NEXPT_RUN_KNOWN_STEMS_LIVE") == "1",
                     "requires NEXPT_RUN_KNOWN_STEMS_LIVE=1 and known isolated reference recordings")
class KnownStemsLiveTests(unittest.TestCase):
    def test_real_cdx_against_known_recordings(self):
        self.assertTrue(os.environ.get("NEXPT_CDX_CONFIG"), "Set NEXPT_CDX_CONFIG")
        self.assertTrue(os.environ.get("NEXPT_KNOWN_STEM_CORPUS"), "Set NEXPT_KNOWN_STEM_CORPUS")
        config = Path(os.environ["NEXPT_CDX_CONFIG"]).expanduser().resolve()
        corpus_path = Path(os.environ["NEXPT_KNOWN_STEM_CORPUS"]).expanduser().resolve()
        corpus = load_corpus(corpus_path)
        self.assertTrue(all(case["reference_kind"] == "isolated-recordings" for case in corpus["cases"]),
                        "Synthetic scorer controls are not real-recording model acceptance")
        backend = CdxSeparator(config)
        backend.ensure_ready()
        self.assertEqual(backend.settings.get("runner"), "safe-pytorch")
        with tempfile.TemporaryDirectory(prefix="nexpt-known-stems-live-") as temporary:
            report = run_cdx(corpus_path, config, Path(temporary) / "result")
            self.assertEqual(report["summary"]["failed_cases"], 0, json.dumps(report["candidate"]["attempts"]))
            self.assertTrue(report["summary"]["numerical_gate_passed"], json.dumps(report["summary"]))
            self.assertFalse(report["perceptual_quality_verified"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

import numpy as np


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from garageband.evaluate import (  # noqa: E402
    build_evaluation,
    event_match_metrics,
)


SR = 48_000
BPM = 120.0


def profile() -> dict:
    roles = {
        name: {
            "events_per_bar": 2.0,
            "step_probability": [.8 if index in {0, 4, 8, 12} else .05
                                 for index in range(16)],
        }
        for name in ("low", "body", "tonal", "detail")
    }
    return {
        "source": {"duration_seconds_decoded": 4.0},
        "tempo": {"bpm": BPM},
        "mix": {
            "bands": {
                "sub": .10, "bass": .18, "low_mid": .20,
                "mid": .24, "presence": .18, "air": .10,
            },
            "side_mid_db": -12.0,
            "crest_db": 14.0,
            "loudness_range_lu": None,
        },
        "generation_targets": {"events_per_bar": 8.0},
        "rhythm_model": {
            "roles": roles,
            "events_per_bar": 8.0,
            "four_bar_repeat_jaccard": .65,
        },
        "events": [{"time": value} for value in (0.0, .5, 1.0, 1.5, 2.0, 2.5, 3.0)],
    }


def write_audio(path: Path, seconds: float = 3.0) -> None:
    audio = np.zeros((int(round(seconds*SR)), 2), dtype=np.float64)
    for index, moment in enumerate(np.arange(0, seconds, .5)):
        start = int(round(moment*SR))
        count = min(int(.30*SR), len(audio)-start)
        time = np.arange(count)/SR
        frequency = (220.0, 277.18, 329.63, 440.0)[index % 4]
        note = np.sin(2*np.pi*frequency*time)*np.exp(-time*8)*.60
        audio[start:start+count, 0] += note
        audio[start:start+count, 1] += note
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes((np.clip(audio, -1, 1)*32767).astype("<i2").tobytes())


class GarageBandEvaluationTest(unittest.TestCase):
    def test_event_alignment_compensates_constant_export_latency(self) -> None:
        metrics = event_match_metrics(
            [0.0, .5, 1.0, 1.5], [.1, .6, 1.1, 1.6])
        self.assertAlmostEqual(
            metrics["estimated_candidate_latency_seconds"], .1, places=3)
        self.assertEqual(metrics["matched_events"], 4)
        self.assertEqual(metrics["f1"], 1.0)
        self.assertAlmostEqual(
            metrics["median_absolute_timing_error_seconds"], 0.0, places=5)

    def test_evaluation_distinguishes_matching_and_weak_reconstruction(self) -> None:
        reference = profile()
        chroma = np.asarray([1.0, .2, 0, 0, .8, 0, 0, .6, 0, 0, 0, 0])
        matching = build_evaluation(
            reference, deepcopy(reference),
            reference_chroma=chroma, candidate_chroma=chroma,
            minimum_score=80,
        )
        self.assertTrue(matching["passed"])
        self.assertEqual(matching["verdict"], "strong_match")
        self.assertGreaterEqual(matching["technical_score_0_100"], 99)

        candidate = deepcopy(reference)
        candidate["source"]["duration_seconds_decoded"] = 2.0
        candidate["events"] = [{"time": .2}]
        weak = build_evaluation(
            reference, candidate,
            reference_chroma=chroma,
            candidate_chroma=np.roll(chroma, 1),
            minimum_score=70,
        )
        self.assertFalse(weak["passed"])
        self.assertIn(weak["verdict"], {"review_required", "weak_match"})
        self.assertTrue(weak["findings"])

    def test_public_cli_writes_machine_readable_ab_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/"reference.wav"
            candidate = root/"candidate.wav"
            output = root/"ab-report.json"
            write_audio(source)
            candidate.write_bytes(source.read_bytes())
            process = subprocess.run([
                sys.executable, str(REPO/"garageband"/"evaluate.py"),
                str(source), str(candidate), "--output", str(output),
                "--bpm", str(BPM), "--downbeat", "0",
                "--minimum-score", "90", "--strict",
            ], cwd=REPO, capture_output=True, text=True, timeout=90)
            self.assertEqual(
                process.returncode, 0,
                f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}")
            summary = json.loads(process.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(summary["passed"])
            self.assertTrue(report["passed"])
            self.assertGreaterEqual(report["technical_score_0_100"], 99)
            self.assertEqual(
                report["reference"]["sha256"], report["candidate"]["sha256"])
            self.assertIn("not sample identity", report["purpose"].casefold())
            self.assertTrue(any(
                "unchanged reference track" in text.casefold()
                for text in report["limitations"]
            ))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

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

from garageband.workflow import assess_quality  # noqa: E402


SR = 48_000
BPM = 120.0


def write_percussion_fixture(path: Path, seconds: float = 4.0) -> None:
    audio = np.zeros((int(round(seconds*SR)), 2), dtype=np.float64)
    for moment in np.arange(0.0, seconds, .5):
        low = int(round(moment*SR))
        count = min(int(.20*SR), len(audio)-low)
        time = np.arange(count)/SR
        frequency = 72.0 if int(round(moment*2)) % 2 == 0 else 920.0
        hit = np.sin(2*np.pi*frequency*time)*np.exp(-time*24)*.65
        audio[low:low+count, 0] += hit
        audio[low:low+count, 1] += hit
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes((np.clip(audio, -1, 1)*32767).astype("<i2").tobytes())


def quality_report() -> dict:
    return {
        "score": {"sounding_notes": 12},
        "quality": {"estimated_confidence": .78},
        "content": {"used": "full"},
        "instruments": {
            "note_events": 10,
            "uncertain_notes": 1,
            "detected": [{"instrument": "piano", "mean_confidence": .82}],
        },
        "engines": {"pitch": {"used": "basic-pitch"}},
        "outputs": {"garageband_inventory": None},
    }


class GarageBandWorkflowTest(unittest.TestCase):
    def test_quality_gate_reports_review_errors_and_inventory_requirement(self) -> None:
        review = assess_quality(quality_report())
        self.assertEqual(review["status"], "review")
        self.assertTrue(review["may_prepare_automatically"])
        self.assertEqual(
            [row["code"] for row in review["findings"]],
            ["garageband_inventory_missing"],
        )

        required = assess_quality(quality_report(), require_inventory=True)
        self.assertEqual(required["status"], "failed")
        self.assertFalse(required["may_prepare_automatically"])
        self.assertIn(
            "garageband_inventory_required",
            [row["code"] for row in required["findings"]],
        )

        weak = quality_report()
        weak["quality"]["estimated_confidence"] = .22
        weak["instruments"]["uncertain_notes"] = 8
        failed = assess_quality(
            weak, minimum_confidence=.5, maximum_uncertain_share=.35)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(
            {row["code"] for row in failed["findings"] if row["level"] == "error"},
            {"low_overall_confidence", "too_many_uncertain_instruments"},
        )

    def test_public_cli_runs_complete_workflow_and_resumes_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/"reference.wav"
            project = root/"project"
            write_percussion_fixture(source)
            base = [
                sys.executable, str(REPO/"garageband"/"workflow.py"), str(source),
                "--project-dir", str(project),
                "--quality", "fast", "--content", "percussion",
                "--separate", "off", "--pitch-engine", "off",
                "--instrument-engine", "off", "--bpm", str(BPM),
                "--downbeat", "0", "--minimum-confidence", "0.1",
                "--prepare-dry-run",
            ]
            first = subprocess.run(
                base, cwd=REPO, capture_output=True, text=True, timeout=90)
            self.assertEqual(
                first.returncode, 0,
                f"stdout:\n{first.stdout}\nstderr:\n{first.stderr}")
            result = json.loads(first.stdout)
            self.assertEqual(result["status"], "prepare_plan_ready")
            self.assertFalse(result["reused_transcription"])
            self.assertTrue(result["artifact_verification"]["score_preset"]["compatible"])
            self.assertTrue(result["quality_gate"]["may_prepare_automatically"])
            self.assertFalse(
                result["reference_contract"]["one_to_one_reconstruction_claim"])
            phases = [
                row["phase"] for row in result["prepare"]["plan"]["steps"]
            ]
            self.assertIn("user_drag_reference", phases)
            self.assertIn("label_and_mute_reference", phases)
            for name in (
                    "score.json", "score.mid", "preset.json", "workflow-result.json"):
                self.assertTrue((project/name).is_file(), name)
            self.assertTrue((project/"analysis"/"transcription-report.json").is_file())

            resumed = subprocess.run(
                [*base, "--resume"], cwd=REPO,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(
                resumed.returncode, 0,
                f"stdout:\n{resumed.stdout}\nstderr:\n{resumed.stderr}")
            resumed_result = json.loads(resumed.stdout)
            self.assertTrue(resumed_result["reused_transcription"])
            self.assertEqual(
                resumed_result["source"]["sha256"], result["source"]["sha256"])

            protected = subprocess.run(
                base, cwd=REPO, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(protected.returncode, 0)
            self.assertIn("--resume", protected.stderr)
            self.assertIn("--overwrite", protected.stderr)

            changed_command = [*base, "--resume"]
            changed_command[changed_command.index("--bpm")+1] = "119"
            changed = subprocess.run(
                changed_command,
                cwd=REPO, capture_output=True, text=True, timeout=30,
            )
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("configuration has changed", changed.stderr)

            stricter_gate = [*base, "--resume"]
            stricter_gate[stricter_gate.index("--minimum-confidence")+1] = "1.0"
            blocked = subprocess.run(
                stricter_gate, cwd=REPO,
                capture_output=True, text=True, timeout=30)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("blocked by the quality gate", blocked.stderr)
            self.assertNotIn("configuration has changed", blocked.stderr)

            recovered = subprocess.run(
                [*base, "--resume"], cwd=REPO,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(
                recovered.returncode, 0,
                f"stdout:\n{recovered.stdout}\nstderr:\n{recovered.stderr}")

            with (project/"preset.json").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            tampered = subprocess.run(
                [*base, "--resume"], cwd=REPO,
                capture_output=True, text=True, timeout=30)
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("artifacts changed", tampered.stderr)
            self.assertIn("preset", tampered.stderr)


if __name__ == "__main__":
    unittest.main()

"""Unit contracts for resumable paired experiments; inference is a test double."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

from experiment_fixtures import fake_run, make_experiment_fixture, ready_preflight
from cinematic_separation import sha256
from separation_benchmark import BenchmarkError, _seal
from separation_metrics import Gates
import separation_experiment as experiment


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.corpus, self.config = make_experiment_fixture(self.root)
        self.output = self.root / "experiment"
        self.preflight = self.enterContext(mock.patch.object(experiment, "preflight", side_effect=ready_preflight))
        self.model = self.enterContext(mock.patch.object(experiment, "run_cdx", side_effect=fake_run))

    def run_experiment(self, **kwargs):
        return experiment.run_experiment(self.corpus, self.config, self.output, **kwargs)

    def partial(self):
        return self.run_experiment(max_new_runs=1)

    def test_schedule_alternates_order_without_changing_profile_labels(self):
        jobs = experiment._schedule(3)
        self.assertEqual([j["quality"] for j in jobs], ["standard", "high", "high", "standard", "standard", "high"])
        self.assertEqual(len({j["id"] for j in jobs}), 6)
        for repeats in (0, 6, True, 1.5, None):
            with self.subTest(repeats=repeats), self.assertRaises(BenchmarkError):
                experiment._schedule(repeats)

    def test_complete_repeated_pairs_keep_roles_silence_and_no_winner(self):
        report = self.run_experiment()
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["completed_runs"], 6)
        self.assertEqual(report["planned_case_attempts"], 18)
        self.assertEqual(report["evaluated_case_attempts"], 18)
        self.assertFalse(report["numerical_gate_passed"])
        self.assertFalse(report["perceptual_quality_verified"])
        self.assertTrue(report["listening_review_required"])
        self.assertIsNone(report["overall_winner"])
        self.assertEqual([c.kwargs["quality"] for c in self.model.call_args_list], ["standard", "high", "high", "standard", "standard", "high"])
        music_only = next(c for c in report["cases"] if c["id"] == "music-only")
        self.assertEqual(music_only["paired_trials"], 3)
        music = music_only["high_minus_standard"]["music"]
        self.assertGreater(music["snr_db_delta"]["median"], 0)
        self.assertEqual(music["snr_db_delta"]["min"], music["snr_db_delta"]["max"])
        self.assertEqual(music["high_gate_passes"], 3)
        dialogue = music_only["high_minus_standard"]["dialogue"]
        self.assertIsNone(dialogue["snr_db_delta"]["median"])
        self.assertEqual(dialogue["snr_db_delta"]["count"], 0)
        self.assertLess(dialogue["silent_window_rms_delta"]["median"], 0)
        self.assertEqual(report, experiment.summarize_experiment(self.output))

    def test_partial_limit_and_resume_preserve_finished_bytes(self):
        partial = self.partial()
        self.assertEqual(partial["status"], "incomplete")
        self.assertEqual(partial["completed_runs"], 1)
        self.assertEqual(partial["pending_case_attempts"], 15)
        self.assertEqual(partial["cases"][0]["paired_trials"], 0)
        completed = self.output / "runs/trial-01-standard"
        before = {p.relative_to(completed): p.read_bytes() for p in completed.rglob("*") if p.is_file()}
        self.model.reset_mock()
        after = self.run_experiment(resume=True)
        self.assertEqual(after["status"], "complete")
        self.assertEqual(self.model.call_count, 5)
        self.assertEqual(before, {p.relative_to(completed): p.read_bytes() for p in completed.rglob("*") if p.is_file()})
        self.assertEqual(len(list((self.output / "summaries").glob("*.json"))), 2)

    def test_completed_resume_does_not_infer_or_overwrite_summary(self):
        before = self.run_experiment(repeats=1)
        snapshots = {p.name: p.read_bytes() for p in (self.output / "summaries").iterdir()}
        self.model.reset_mock()
        self.assertEqual(before, self.run_experiment(repeats=1, resume=True))
        self.model.assert_not_called()
        self.assertEqual(snapshots, {p.name: p.read_bytes() for p in (self.output / "summaries").iterdir()})

    def test_interruption_releases_lock_and_preserves_completed_runs(self):
        calls = 0
        def interrupt(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt()
            return fake_run(*args, **kwargs)
        self.model.side_effect = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_experiment(repeats=1)
        self.assertTrue((self.output / "runs/trial-01-standard/completion.json").is_file())
        self.assertFalse((self.output / "runs/trial-01-high").exists())
        self.assertFalse(list((self.output / "runs").glob(".separation-benchmark-*")))
        self.model.side_effect = fake_run
        self.model.reset_mock()
        self.assertEqual(self.run_experiment(repeats=1, resume=True)["status"], "complete")
        self.assertEqual(self.model.call_count, 1)

    def test_failed_cases_are_counted_and_not_retried_on_resume(self):
        def failed(*args, **kwargs):
            return fake_run(*args, **kwargs, missing_case="overlap")
        self.model.side_effect = failed
        report = self.run_experiment(repeats=1)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["completed_runs"], 2)
        self.assertEqual(report["pending_jobs"], [])
        self.assertEqual(len(report["failed_case_attempts"]), 2)
        self.assertEqual(report["evaluated_case_attempts"], 4)
        self.assertEqual(report["planned_case_attempts"], 6)
        overlap = next(c for c in report["cases"] if c["id"] == "overlap")
        self.assertEqual(overlap["missing_or_failed_trials"], 1)
        self.model.reset_mock()
        self.assertEqual(report, self.run_experiment(repeats=1, resume=True))
        self.model.assert_not_called()

    def test_existing_unknown_directory_and_missing_resume_are_untouched(self):
        with self.assertRaises(BenchmarkError):
            self.run_experiment(resume=True)
        self.output.mkdir()
        (self.output / "keep.txt").write_text("keep")
        with self.assertRaises(BenchmarkError):
            self.run_experiment()
        with self.assertRaises((BenchmarkError, OSError)):
            self.run_experiment(resume=True)
        self.assertEqual(list(self.output.iterdir()), [self.output / "keep.txt"])
        self.model.assert_not_called()
        self.preflight.assert_not_called()

    def test_blocked_preflight_and_unlocked_runtime_do_not_create_experiment(self):
        self.preflight.side_effect = None
        self.preflight.return_value = {"ready_for_run": False, "blockers": ["missing model"]}
        report = self.run_experiment()
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["model_inference_executed"])
        self.assertFalse(self.output.exists())
        ready = ready_preflight(self.corpus, config=self.config)
        ready["profiles"]["high"]["runtime_locked"] = False
        self.preflight.return_value = ready
        with self.assertRaisesRegex(BenchmarkError, "verify-runtime"):
            self.run_experiment()
        self.assertFalse(self.output.exists())
        self.model.assert_not_called()

    def test_changed_options_cannot_silently_resume(self):
        self.partial()
        self.model.reset_mock()
        for options in ({"repeats": 2}, {"timeout": 601}, {"device": "cuda"}, {"gates": Gates(minimum_snr_db=11)}):
            with self.subTest(options=options), self.assertRaisesRegex(BenchmarkError, "Plan"):
                self.run_experiment(resume=True, **options)
        self.model.assert_not_called()

    def test_changed_config_runtime_or_integration_cannot_resume(self):
        self.partial()
        self.model.reset_mock()
        before = self.config.read_bytes()
        self.config.write_bytes(before + b"\n")
        with self.assertRaises(BenchmarkError):
            self.run_experiment(resume=True)
        self.config.write_bytes(before)
        changed = ready_preflight(self.corpus, config=self.config)
        changed["profiles"]["standard"]["runtime"]["fingerprint"] = "b" * 64
        with mock.patch.object(experiment, "preflight", return_value=changed), self.assertRaises(BenchmarkError):
            self.run_experiment(resume=True)
        with mock.patch.object(experiment, "_integration", return_value={"changed": "c" * 64}), self.assertRaises(BenchmarkError):
            self.run_experiment(resume=True)
        self.model.assert_not_called()

    def test_changed_source_is_rejected_before_any_resumed_inference(self):
        self.partial()
        self.model.reset_mock()
        source = self.corpus.parent / "cases/overlap/music.wav"
        source.write_bytes(source.read_bytes() + b"changed")
        with self.assertRaises(BenchmarkError):
            self.run_experiment(resume=True)
        self.model.assert_not_called()

    def test_tampered_plan_is_not_used_to_write_a_lock(self):
        self.partial()
        path = self.output / "experiment.json"
        plan = json.loads(path.read_text())
        plan["parameters"]["repeats"] = 5
        path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(BenchmarkError, "Versuchsplan"):
            self.run_experiment(resume=True)

    def test_modified_stem_report_and_completion_are_rejected(self):
        self.partial()
        self.model.reset_mock()
        directory = self.output / "runs/trial-01-standard"
        for relative in ("estimates/overlap/music.wav", "report.json", "completion.json"):
            path = directory / relative
            before = path.read_bytes()
            path.write_bytes(before + b"tampered")
            with self.subTest(relative=relative), self.assertRaises((RuntimeError, ValueError)):
                self.run_experiment(resume=True)
            path.write_bytes(before)
        self.model.assert_not_called()

    def test_copy_of_same_profile_is_not_counted_as_a_new_trial(self):
        self.partial()
        self.model.reset_mock()
        shutil.copytree(self.output / "runs/trial-01-standard", self.output / "runs/trial-02-standard")
        with self.assertRaisesRegex(BenchmarkError, "Laufbeleg"):
            self.run_experiment(resume=True)
        self.model.assert_not_called()

    def test_resealed_wrong_profile_or_contract_is_not_accepted_as_a_valid_run(self):
        self.partial()
        self.model.reset_mock()
        directory = self.output / "runs/trial-01-standard"
        report_path, receipt_path = directory / "report.json", directory / "completion.json"
        original_report, original_receipt = report_path.read_bytes(), receipt_path.read_bytes()
        for field in ("quality", "corpus_id", "metric_version"):
            report = json.loads(original_report)
            if field == "quality":
                report["candidate"]["quality"] = "high"
            else:
                report[field] = "different"
            report = _seal({k: v for k, v in report.items() if k != "report_id"})
            report_path.write_text(json.dumps(report))
            receipt = json.loads(original_receipt)
            receipt.update(benchmark_report_id=report["report_id"], benchmark_report_sha256=sha256(report_path))
            receipt_path.write_text(json.dumps(_seal({k: v for k, v in receipt.items() if k != "report_id"})))
            with self.subTest(field=field), self.assertRaises(BenchmarkError):
                self.run_experiment(resume=True)
            report_path.write_bytes(original_report)
            receipt_path.write_bytes(original_receipt)
        self.model.assert_not_called()

    def test_model_false_success_without_artifacts_cannot_publish_a_completed_job(self):
        self.model.side_effect = None
        self.model.return_value = {"status": "success"}
        with self.assertRaises((BenchmarkError, OSError)):
            self.run_experiment()
        self.assertEqual(list((self.output / "runs").iterdir()), [])

    def test_saved_artifact_symlinks_cannot_escape_experiment(self):
        self.partial()
        self.model.reset_mock()
        path = self.output / "runs/trial-01-standard/estimates/overlap/music.wav"
        copy_path = self.root / "external.wav"
        path.rename(copy_path)
        path.symlink_to(copy_path)
        with self.assertRaisesRegex(BenchmarkError, "ausserhalb"):
            self.run_experiment(resume=True)
        self.model.assert_not_called()

    def test_concurrent_start_is_rejected_and_kernel_lock_is_reusable(self):
        self.partial()
        self.model.reset_mock()
        with experiment._lock(self.output):
            with self.assertRaisesRegex(BenchmarkError, "anderen Prozess"):
                self.run_experiment(resume=True)
        self.model.assert_not_called()
        self.assertEqual(self.run_experiment(resume=True)["status"], "complete")

    def test_context_change_mid_run_does_not_publish_that_run(self):
        def changed(*args, **kwargs):
            value = fake_run(*args, **kwargs)
            self.config.write_bytes(self.config.read_bytes() + b"\n")
            return value
        self.model.side_effect = changed
        with self.assertRaisesRegex(BenchmarkError, "geaendert"):
            self.run_experiment()
        self.assertEqual(list((self.output / "runs").iterdir()), [])

    def test_changed_summary_is_preserved_instead_of_overwritten(self):
        self.run_experiment(repeats=1)
        path = next((self.output / "summaries").glob("*.json"))
        path.write_text("user edit")
        self.model.reset_mock()
        with self.assertRaises((RuntimeError, ValueError)):
            self.run_experiment(repeats=1, resume=True)
        self.assertEqual(path.read_text(), "user edit")
        self.model.assert_not_called()

    def test_offline_summary_does_not_probe_runtime_or_require_original_sources(self):
        self.run_experiment(repeats=1)
        self.config.unlink()
        self.corpus.rename(self.corpus.with_suffix(".saved"))
        self.preflight.reset_mock()
        self.model.reset_mock()
        report = experiment.summarize_experiment(self.output)
        self.assertEqual(report["status"], "complete")
        self.preflight.assert_not_called()
        self.model.assert_not_called()

    def test_invalid_limits_fail_before_preflight_or_filesystem_writes(self):
        for options in ({"timeout": True}, {"timeout": float("nan")}, {"timeout": 0}, {"timeout": 3601},
                        {"max_new_runs": True}, {"max_new_runs": 0}, {"max_new_runs": 7}, {"device": "mps"}):
            with self.subTest(options=options), self.assertRaises(BenchmarkError):
                self.run_experiment(**options)
        self.assertFalse(self.output.exists())
        self.preflight.assert_not_called()
        self.model.assert_not_called()

    def test_distributions_are_observed_ranges_and_preserve_undefined_scores(self):
        self.assertEqual(experiment._distribution([3, 1, 2]), {"count": 3, "median": 2.0, "min": 1, "max": 3})
        self.assertEqual(experiment._distribution([]), {"count": 0, "median": None, "min": None, "max": None})


if __name__ == "__main__":
    unittest.main()

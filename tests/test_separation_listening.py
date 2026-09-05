"""Unit contracts for blinded listening kits; audio/model outputs are doubles."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

from experiment_fixtures import fake_run, make_experiment_fixture, ready_preflight
from cinematic_separation import sha256
from separation_benchmark import BenchmarkError, _digest, _seal
import separation_experiment as experiment
import separation_listening as listening


class ListeningKitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.corpus, self.config = make_experiment_fixture(self.root, case_count=2)
        self.experiment = self.root / "experiment"
        self.kit = self.root / "listening kit"
        with (mock.patch.object(experiment, "preflight", side_effect=ready_preflight),
              mock.patch.object(experiment, "run_cdx", side_effect=fake_run)):
            report = experiment.run_experiment(self.corpus, self.config, self.experiment,
                                               repeats=2)
        self.assertEqual(report["status"], "complete")

    def build(self, destination=None, seed=17):
        destination = destination or self.kit
        return listening.build_listening_kit(
            self.experiment, self.corpus, destination, _rng=random.Random(seed))

    def load(self):
        return listening._load_kit(self.kit, experiment=self.experiment,
                                   corpus_path=self.corpus)

    def completed_review(self, reviewer="christian", *, high_score=5, standard_score=2):
        manifest, key = self.load()
        review = listening._review_template(manifest)
        review["reviewer_id"] = reviewer
        review["playback"] = {"device": "studio headphones", "environment": "quiet room"}
        mappings = {row["id"]: row["candidates"] for row in key["mappings"]}
        for row in review["items"]:
            labels = {value["quality"]: label for label, value in mappings[row["id"]].items()}
            row["preference"] = labels["high"]
            row["confidence"] = 4
            for criterion in listening.CRITERIA:
                row["ratings"][labels["high"]][criterion] = high_score
                row["ratings"][labels["standard"]][criterion] = standard_score
            row["notes"] = ""
        return review

    def write_review(self, payload, name="review.json"):
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def reseal(self, manifest, key):
        manifest["kit_id"] = _digest({k: v for k, v in manifest.items() if k != "kit_id"})
        (self.kit / "public/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.kit / "public/review-template.json").write_text(
            json.dumps(listening._review_template(manifest)), encoding="utf-8")
        (self.kit / "public/index.html").write_text(
            listening._review_page(manifest), encoding="utf-8")
        key["kit_id"] = manifest["kit_id"]
        key = _seal({k: v for k, v in key.items() if k != "report_id"})
        (self.kit / "private/key.json").write_text(json.dumps(key), encoding="utf-8")

    def test_complete_kit_is_balanced_blinded_and_byte_exact(self):
        result = self.build()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["items"], 12)
        self.assertEqual(result["trials"], 2)
        self.assertFalse(result["profiles_disclosed_in_public_package"])
        self.assertFalse(result["model_inference_executed"])
        self.assertIsNone(result["overall_winner"])
        self.assertEqual(Path(result["review_ui"]), self.kit / "public/index.html")
        self.assertTrue((self.kit / "public/index.html").is_file())
        manifest, key = self.load()
        public_text = "\n".join(path.read_text(encoding="utf-8")
                                 for path in (self.kit / "public").glob("*.json"))
        self.assertNotIn('"standard"', public_text)
        self.assertNotIn('"high"', public_text)
        a_high = sum(row["candidates"]["A"]["quality"] == "high" for row in key["mappings"])
        self.assertLessEqual(abs(a_high - (len(key["mappings"]) - a_high)), 1)
        items = {row["id"]: row for row in manifest["items"]}
        for mapping in key["mappings"]:
            item = items[mapping["id"]]
            for label, candidate in mapping["candidates"].items():
                public = self.kit / "public" / item["candidates"][label]["path"]
                source = (self.experiment / "runs" / candidate["job"] / "estimates"
                          / item["case_id"] / f"{item['role']}.wav")
                self.assertEqual(public.read_bytes(), source.read_bytes())
        for case in manifest["cases"]:
            original = self.corpus.parent / f"cases/{case['id']}/mix.wav"
            copied = self.kit / "public" / case["mix"]["path"]
            self.assertEqual(copied.read_bytes(), original.read_bytes())

    def test_offline_ui_is_blind_self_contained_and_bound_to_manifest(self):
        self.build()
        manifest, _ = self.load()
        page = (self.kit / "public/index.html").read_text(encoding="utf-8")
        self.assertEqual(page, listening._review_page(manifest))
        self.assertIn(manifest["kit_id"], page)
        self.assertNotIn("__NEXPT_MANIFEST__", page)
        self.assertNotIn('"standard"', page)
        self.assertNotIn('"high"', page)
        self.assertNotIn("https://", page)
        self.assertIn("connect-src 'none'", page)
        self.assertIn('id="import-button"', page)
        self.assertIn('id="draft-button"', page)
        self.assertIn('id="export-button"', page)
        self.assertIn("nexpt-blind-listening-review", page)
        for case in manifest["cases"]:
            self.assertIn(case["mix"]["path"], page)
            for entry in case["references"].values():
                self.assertIn(entry["path"], page)
        for item in manifest["items"]:
            for entry in item["candidates"].values():
                self.assertIn(entry["path"], page)

        hostile = copy.deepcopy(manifest)
        hostile["limitations"] = ["</script><script>globalThis.pwned=true</script>"]
        escaped = listening._review_page(hostile)
        self.assertNotIn("</script><script>globalThis.pwned", escaped)
        self.assertIn(r"\u003c/script>\u003cscript>", escaped)

    def test_fixed_test_rng_reproduces_identity_while_different_rng_changes_blinding(self):
        first = self.build()
        second_path = self.root / "same"
        second = self.build(second_path)
        self.assertEqual(first["kit_id"], second["kit_id"])
        self.assertEqual((self.kit / "public/manifest.json").read_bytes(),
                         (second_path / "public/manifest.json").read_bytes())
        self.assertEqual((self.kit / "public/index.html").read_bytes(),
                         (second_path / "public/index.html").read_bytes())
        third = self.build(self.root / "different", seed=18)
        self.assertNotEqual(first["kit_id"], third["kit_id"])

    def test_incomplete_and_failed_experiments_never_publish_a_kit(self):
        for mode in ("partial", "failed"):
            work = self.root / mode
            work.mkdir()
            corpus, config = make_experiment_fixture(work, case_count=1)
            output = work / "experiment"
            with (mock.patch.object(experiment, "preflight", side_effect=ready_preflight),
                  mock.patch.object(experiment, "run_cdx", side_effect=(
                      fake_run if mode == "partial" else
                      lambda *a, **kw: fake_run(*a, **kw, missing_case="overlap")))):
                experiment.run_experiment(corpus, config, output, repeats=1,
                                          max_new_runs=1 if mode == "partial" else None)
            destination = work / "kit"
            with self.subTest(mode=mode), self.assertRaisesRegex(BenchmarkError, "vollstaendigen"):
                listening.build_listening_kit(output, corpus, destination)
            self.assertFalse(destination.exists())

    def test_wrong_or_changed_corpus_is_rejected_before_publication(self):
        other = self.root / "other"
        other.mkdir()
        wrong_corpus, _ = make_experiment_fixture(other, case_count=1)
        with self.assertRaisesRegex(BenchmarkError, "Corpus"):
            listening.build_listening_kit(self.experiment, wrong_corpus, self.kit)
        corpus = json.loads(self.corpus.read_text())
        source = self.corpus.parent / corpus["cases"][0]["stems"]["music"]["path"]
        source.write_bytes(source.read_bytes() + b"changed")
        with self.assertRaises(BenchmarkError):
            self.build()
        self.assertFalse(self.kit.exists())

    def test_existing_destination_and_experiment_subdirectory_are_not_modified(self):
        self.kit.mkdir()
        marker = self.kit / "keep"
        marker.write_text("keep")
        with self.assertRaises(BenchmarkError):
            self.build()
        self.assertEqual(marker.read_text(), "keep")
        nested = self.experiment / "listening"
        with self.assertRaisesRegex(BenchmarkError, "innerhalb"):
            self.build(nested)
        self.assertFalse(nested.exists())

    def test_public_audio_manifest_instruction_and_unknown_artifact_tampering_is_detected(self):
        self.build()
        targets = [self.kit / "public/audio/items/item-0001/A.wav",
                   self.kit / "public/manifest.json",
                   self.kit / "public/README.md",
                   self.kit / "public/index.html"]
        for path in targets:
            before = path.read_bytes()
            path.write_bytes(before + b"tampered")
            with self.subTest(path=path.name), self.assertRaises((BenchmarkError, ValueError)):
                self.load()
            path.write_bytes(before)
        unexpected = self.kit / "public/extra.txt"
        unexpected.write_text("extra")
        with self.assertRaisesRegex(BenchmarkError, "unbekannte"):
            self.load()

    def test_symlinked_public_or_private_artifacts_are_rejected(self):
        self.build()
        for relative in ("public/audio/items/item-0001/A.wav", "public/index.html",
                         "private/key.json"):
            path = self.kit / relative
            external = self.root / f"external-{path.name}"
            path.rename(external)
            path.symlink_to(external)
            with self.subTest(relative=relative), self.assertRaises(BenchmarkError):
                self.load()
            path.unlink()
            external.rename(path)

    def test_resealed_candidate_or_private_mapping_is_checked_against_experiment(self):
        self.build()
        manifest, key = self.load()
        item = manifest["items"][0]
        a_path = self.kit / "public" / item["candidates"]["A"]["path"]
        b_path = self.kit / "public" / item["candidates"]["B"]["path"]
        a_path.write_bytes(b_path.read_bytes())
        item["candidates"]["A"]["sha256"] = sha256(a_path)
        key["mappings"][0]["candidates"]["A"]["sha256"] = sha256(a_path)
        self.reseal(manifest, key)
        with self.assertRaisesRegex(BenchmarkError, "Modellresultaten"):
            self.load()

    def test_resealed_reference_is_still_checked_against_corpus(self):
        self.build()
        manifest, key = self.load()
        case = manifest["cases"][0]
        target = self.kit / "public" / case["references"]["music"]["path"]
        replacement = self.kit / "public" / case["references"]["dialogue"]["path"]
        target.write_bytes(replacement.read_bytes())
        case["references"]["music"]["sha256"] = sha256(target)
        case["reference_active"]["music"] = case["reference_active"]["dialogue"]
        self.reseal(manifest, key)
        with self.assertRaisesRegex(BenchmarkError, "Corpus"):
            self.load()

    def test_resealed_missing_item_is_rejected_as_incomplete_coverage(self):
        self.build()
        manifest, key = self.load()
        removed = manifest["items"].pop()
        key["mappings"] = [row for row in key["mappings"] if row["id"] != removed["id"]]
        shutil.rmtree(self.kit / "public/audio/items" / removed["id"])
        self.reseal(manifest, key)
        with self.assertRaisesRegex(BenchmarkError, "jedes Trial"):
            self.load()

    def test_complete_review_is_unblinded_with_descriptive_deltas_but_no_winner(self):
        self.build()
        review = self.write_review(self.completed_review())
        result = listening.summarize_listening(self.kit, self.experiment,
                                               self.corpus, [review])
        self.assertEqual(result["status"], "reviewed")
        self.assertEqual(result["declared_human_reviewers"], 1)
        self.assertEqual(result["completed_judgements"], 12)
        self.assertEqual(result["overall"]["preference_counts"]["high"], 12)
        self.assertEqual(result["overall"]["preference_counts"]["standard"], 0)
        for criterion in listening.CRITERIA:
            self.assertEqual(result["overall"]["high_minus_standard"][criterion]["median"], 3)
        self.assertTrue(result["listening_review_completed"])
        self.assertFalse(result["perceptual_quality_verified"])
        self.assertIsNone(result["overall_winner"])
        self.assertEqual(result["report_id"], _digest({k: v for k, v in result.items()
                                                       if k != "report_id"}))

    def test_multiple_reviewers_are_aggregated_and_duplicate_identity_is_rejected(self):
        self.build()
        first = self.write_review(self.completed_review("reviewer-1"), "first.json")
        second_payload = self.completed_review("reviewer-2", high_score=1, standard_score=4)
        for row in second_payload["items"]:
            row["preference"] = "tie"
        second = self.write_review(second_payload, "second.json")
        result = listening.summarize_listening(self.kit, self.experiment,
                                               self.corpus, [first, second])
        self.assertEqual(result["declared_human_reviewers"], 2)
        self.assertEqual(result["overall"]["preference_counts"],
                         {"standard": 0, "high": 12, "tie": 12, "both_unusable": 0})
        self.assertEqual(result["overall"]["high_minus_standard"]["reference_match"]["median"], 0)
        duplicate = self.write_review(self.completed_review("reviewer-1"), "duplicate.json")
        with self.assertRaisesRegex(BenchmarkError, "eindeutig"):
            listening.summarize_listening(self.kit, self.experiment,
                                          self.corpus, [first, duplicate])

    def test_review_items_may_be_reordered_but_must_be_complete_and_typed(self):
        self.build()
        valid = self.completed_review()
        reordered = copy.deepcopy(valid)
        reordered["items"].reverse()
        normalized = listening._validate_review(reordered, self.load()[0])
        self.assertEqual([row["id"] for row in normalized["items"]],
                         [row["id"] for row in valid["items"]])
        mutations = []
        wrong = copy.deepcopy(valid); wrong["reviewer_id"] = "replace-me"; mutations.append(wrong)
        wrong = copy.deepcopy(valid); wrong["kit_id"] = "wrong"; mutations.append(wrong)
        wrong = copy.deepcopy(valid); wrong["items"][0]["preference"] = None; mutations.append(wrong)
        wrong = copy.deepcopy(valid); wrong["items"][0]["confidence"] = True; mutations.append(wrong)
        wrong = copy.deepcopy(valid); wrong["items"][0]["ratings"]["A"]["isolation"] = 6; mutations.append(wrong)
        wrong = copy.deepcopy(valid); wrong["items"] = wrong["items"][:-1]; mutations.append(wrong)
        wrong = copy.deepcopy(valid); wrong["items"].append(copy.deepcopy(wrong["items"][0])); mutations.append(wrong)
        wrong = copy.deepcopy(valid); wrong["unexpected"] = True; mutations.append(wrong)
        wrong = copy.deepcopy(valid); wrong["items"][0]["notes"] = "x" * 2001; mutations.append(wrong)
        for payload in mutations:
            with self.subTest(payload=payload), self.assertRaises(BenchmarkError):
                listening._validate_review(payload, self.load()[0])

    def test_template_symlink_changed_during_read_and_review_count_limits_fail(self):
        self.build()
        template = self.kit / "public/review-template.json"
        with self.assertRaises(BenchmarkError):
            listening.summarize_listening(self.kit, self.experiment, self.corpus, [])
        with self.assertRaises(BenchmarkError):
            listening.summarize_listening(self.kit, self.experiment, self.corpus,
                                          [template] * 21)
        review = self.write_review(self.completed_review())
        link = self.root / "review-link.json"
        link.symlink_to(review)
        with self.assertRaisesRegex(BenchmarkError, "Symlink"):
            listening.summarize_listening(self.kit, self.experiment, self.corpus, [link])

    def test_review_changed_during_summary_is_detected(self):
        self.build()
        review = self.write_review(self.completed_review())
        original = listening._validate_review

        def mutate(payload, manifest):
            result = original(payload, manifest)
            review.write_bytes(review.read_bytes() + b" ")
            return result

        with mock.patch.object(listening, "_validate_review", side_effect=mutate):
            with self.assertRaisesRegex(BenchmarkError, "waehrend"):
                listening.summarize_listening(self.kit, self.experiment,
                                              self.corpus, [review])


if __name__ == "__main__":
    unittest.main()

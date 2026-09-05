#!/usr/bin/env python3
"""Create and score a blinded human review for a completed CDX A/B run.

The shareable directory contains only anonymous A/B candidates and known
references.  The profile mapping stays in a separate private directory.  A
summary validates both against the immutable experiment before unblinding.
It records declared human judgements but never elects a model automatically.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import re
import secrets
import shutil
from statistics import median
from typing import Any

from cinematic_separation import sha256
from separation_benchmark import (BenchmarkError, _bundle, _case_audio, _digest,
                                  _entry, _json, _owned_file, _seal, _wav,
                                  _write_json, load_corpus)
from separation_experiment import (_load_plan, _read_run,
                                   summarize_experiment)
from separation_metrics import ROLES, SILENCE_RMS, rms


CRITERIA = ("reference_match", "isolation", "artifact_free")
PREFERENCES = ("A", "B", "tie", "both_unusable")
MAX_REVIEWS = 20
MAX_NOTES = 2_000
MAX_LISTENING_BYTES = 8 * 1024 ** 3


def _copy_verified(source: Path, destination: Path, expected: str) -> None:
    if source.is_symlink() or not source.is_file() or sha256(source) != expected:
        raise BenchmarkError(f"Hoertest-Quelle fehlt, ist ein Symlink oder wurde veraendert: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256(destination) != expected or sha256(source) != expected:
        raise BenchmarkError(f"Hoertest-Kopie stimmt nicht mit der Quelle ueberein: {source.name}")


def _packaged_file(root: Path, entry: dict) -> Path:
    if isinstance(entry, dict) and isinstance(entry.get("path"), str):
        candidate = root / entry["path"]
        if candidate.is_symlink():
            raise BenchmarkError("Hoertest-Dateien duerfen keine Symlinks sein")
    return _owned_file(root, entry)


def _review_template(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "nexpt-blind-listening-review",
        "kit_id": manifest["kit_id"],
        "reviewer_id": "replace-me",
        "playback": {"device": "", "environment": ""},
        "items": [{
            "id": item["id"],
            "preference": None,
            "confidence": None,
            "ratings": {
                label: {criterion: None for criterion in CRITERIA}
                for label in ("A", "B")
            },
            "notes": "",
        } for item in manifest["items"]],
    }


def _instructions() -> str:
    return """# Blinder Hoertest

Nur diesen Ordner an die testende Person weitergeben. Der benachbarte Ordner
`private` enthaelt die Aufloesung und darf vor Abschluss nicht geteilt werden.

Fuer jedes Item zuerst die Referenz, danach A und B bei unveraenderter
Lautstaerke abhoeren. Der Mix dient nur als Kontext. Keine Normalisierung,
Effekte oder Klangverbesserer einschalten. Kopfhoerer oder dieselben
Abhoermonitore fuer den gesamten Durchgang verwenden.

`review-template.json` kopieren und ausfuellen:

- `preference`: `A`, `B`, `tie` oder `both_unusable`
- `confidence`: 1 (unsicher) bis 5 (sehr sicher)
- `reference_match`: 1 (passt nicht) bis 5 (passt sehr gut)
- `isolation`: 1 (starke Fremdanteile) bis 5 (sauber isoliert)
- `artifact_free`: 1 (starke Artefakte) bis 5 (keine wahrnehmbaren Artefakte)

Jedes Item muss vollstaendig bewertet werden. `reviewer_id` muss pro Person
eindeutig sein. Notizen sind optional. Das Paket waehlt keinen Sieger und ist
kein Nachweis dafuer, dass die Person tatsaechlich unter kontrollierten
Bedingungen gehoert hat.
"""


def _source_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {row["id"]: row for row in report["cases"]}
    if len(rows) != len(report["cases"]):
        raise BenchmarkError("A/B-Bericht enthaelt doppelte Cases")
    return rows


def _balanced_assignments(count: int, rng: random.Random) -> list[bool]:
    assignments = [False, True] * (count // 2)
    if count % 2:
        assignments.append(bool(rng.randrange(2)))
    rng.shuffle(assignments)
    return assignments


def build_listening_kit(experiment: Path, corpus_path: Path, destination: Path, *,
                        _rng: random.Random | None = None) -> dict[str, Any]:
    """Build one immutable public/private listening package transactionally."""
    root = experiment.expanduser().absolute()
    plan = _load_plan(root)
    numerical = summarize_experiment(root)
    if numerical["status"] != "complete":
        raise BenchmarkError("Blinder Hoertest braucht einen vollstaendigen A/B-Versuch ohne fehlgeschlagene Cases")
    corpus_path = corpus_path.expanduser().resolve()
    corpus = load_corpus(corpus_path)
    if corpus["corpus_id"] != plan["corpus_id"]:
        raise BenchmarkError("Referenz-Corpus gehoert nicht zum A/B-Versuch")
    case_ids = [row["id"] for row in plan["cases"]]
    if case_ids != [row["id"] for row in corpus["cases"]]:
        raise BenchmarkError("Case-Reihenfolge oder Abdeckung des Corpus stimmt nicht mit dem Versuch")
    destination_path = destination.expanduser().absolute().resolve()
    if destination_path.is_relative_to(root.resolve()):
        raise BenchmarkError("Hoertest-Paket darf nicht innerhalb des unveraenderlichen A/B-Versuchs liegen")

    jobs = {job["id"]: job for job in plan["jobs"]}
    reports = {identifier: _read_run(root, plan, job) for identifier, job in jobs.items()}
    if any(report is None for report in reports.values()):
        raise BenchmarkError("A/B-Versuch ist nicht vollstaendig")
    report_rows = {identifier: _source_rows(report) for identifier, report in reports.items()}
    rng = _rng or secrets.SystemRandom()

    raw_items = []
    repeats = plan["parameters"]["repeats"]
    for trial in range(1, repeats + 1):
        profile_jobs = {
            quality: f"trial-{trial:02d}-{quality}"
            for quality in ("standard", "high")
        }
        for case_id in case_ids:
            for role in ROLES:
                raw_items.append({"trial": trial, "case_id": case_id, "role": role,
                                  "jobs": profile_jobs})
    rng.shuffle(raw_items)
    assignments = _balanced_assignments(len(raw_items), rng)

    with _bundle(destination) as bundle:
        public = bundle / "public"
        private = bundle / "private"
        public.mkdir()
        private.mkdir()
        instructions = public / "README.md"
        instructions.write_text(_instructions(), encoding="utf-8")

        manifest: dict[str, Any] = {
            "schema_version": 1,
            "kind": "nexpt-blind-listening-kit",
            "protocol": "paired-known-reference-v1",
            "experiment_id": plan["experiment_id"],
            "corpus_id": plan["corpus_id"],
            "profiles_disclosed": False,
            "instructions": _entry(instructions, public),
            "criteria": {
                "reference_match": "1 does not match; 5 matches the known reference very well",
                "isolation": "1 strong unwanted sources; 5 cleanly isolated",
                "artifact_free": "1 severe processing artefacts; 5 no audible artefacts",
            },
            "scale": {"minimum": 1, "maximum": 5},
            "cases": [],
            "items": [],
            "limitations": [
                "Local blinding reduces expectation bias but is not adversarial if the reviewer also has the experiment or private key.",
                "Known references and candidate WAVs are copied byte-for-byte; playback hardware and loudness are not controlled by this package.",
                "A completed form is a declared human review, not independent proof that listening occurred.",
            ],
        }
        corpus_index = {case["id"]: case for case in corpus["cases"]}
        copied_bytes = 0
        for case_id in case_ids:
            case = corpus_index[case_id]
            _, references = _case_audio(corpus_path.parent, case)
            source_mix = _owned_file(corpus_path.parent, case["mix"])
            mix_target = public / "audio" / "references" / case_id / "mix.wav"
            _copy_verified(source_mix, mix_target, case["mix"]["sha256"])
            copied_bytes += source_mix.stat().st_size
            stems = {}
            active = {}
            for role in ROLES:
                source = _owned_file(corpus_path.parent, case["stems"][role])
                target = public / "audio" / "references" / case_id / f"{role}.wav"
                _copy_verified(source, target, case["stems"][role]["sha256"])
                copied_bytes += source.stat().st_size
                stems[role] = _entry(target, public)
                active[role] = bool(rms(references[role]) > SILENCE_RMS)
            manifest["cases"].append({
                "id": case_id,
                "sample_rate": case["sample_rate"],
                "frames": case["frames"],
                "channels": case["channels"],
                "mix": _entry(mix_target, public),
                "references": stems,
                "reference_active": active,
            })

        mappings = []
        for number, (raw, a_is_high) in enumerate(zip(raw_items, assignments), 1):
            item_id = f"item-{number:04d}"
            labels = {"A": "high" if a_is_high else "standard",
                      "B": "standard" if a_is_high else "high"}
            candidates, private_candidates = {}, {}
            for label, quality in labels.items():
                job_id = raw["jobs"][quality]
                report_row = report_rows[job_id][raw["case_id"]]
                if report_row.get("status") != "evaluated":
                    raise BenchmarkError("Blinder Hoertest akzeptiert keine fehlgeschlagenen Case-Ergebnisse")
                entry = report_row["estimates"][raw["role"]]
                source = _owned_file(root / "runs" / job_id / "estimates", entry)
                target = public / "audio" / "items" / item_id / f"{label}.wav"
                _copy_verified(source, target, entry["sha256"])
                copied_bytes += source.stat().st_size
                candidates[label] = _entry(target, public)
                private_candidates[label] = {"quality": quality, "job": job_id,
                                             "sha256": entry["sha256"]}
            manifest["items"].append({"id": item_id, "trial": raw["trial"],
                                      "case_id": raw["case_id"], "role": raw["role"],
                                      "candidates": candidates})
            mappings.append({"id": item_id, "candidates": private_candidates})
        if copied_bytes > MAX_LISTENING_BYTES:
            raise BenchmarkError("Hoertest-Paket waere groesser als 8 GiB; Corpus oder Wiederholungen reduzieren")

        manifest["kit_id"] = _digest(manifest)
        _write_json(public / "manifest.json", manifest)
        _write_json(public / "review-template.json", _review_template(manifest))
        key = _seal({"schema_version": 1, "kind": "nexpt-blind-listening-key",
                     "kit_id": manifest["kit_id"], "experiment_id": plan["experiment_id"],
                     "corpus_id": plan["corpus_id"], "mappings": mappings})
        _write_json(private / "key.json", key)
        _load_kit(bundle, experiment=root, corpus_path=corpus_path)

    return {"status": "ready", "kit_id": manifest["kit_id"],
            "experiment_id": plan["experiment_id"], "cases": len(case_ids),
            "trials": repeats, "items": len(manifest["items"]),
            "copied_bytes": copied_bytes,
            "share_directory": str(destination.expanduser().absolute() / "public"),
            "private_key": str(destination.expanduser().absolute() / "private" / "key.json"),
            "profiles_disclosed_in_public_package": False,
            "model_inference_executed": False, "overall_winner": None}


def _exact_keys(value: Any, keys: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise BenchmarkError(f"Ungueltige Felder in {label}")


def _verify_public_tree(public: Path, expected_files: set[str]) -> None:
    expected_directories = {str(Path(path).parent) for path in expected_files}
    for directory in list(expected_directories):
        parent = Path(directory)
        while str(parent) not in (".", ""):
            expected_directories.add(str(parent))
            parent = parent.parent
    for item in public.rglob("*"):
        relative = str(item.relative_to(public))
        if (item.is_symlink() or (item.is_file() and relative not in expected_files)
                or (item.is_dir() and relative not in expected_directories)
                or (not item.is_file() and not item.is_dir())):
            raise BenchmarkError("Oeffentliches Hoertest-Paket enthaelt unbekannte oder unsichere Artefakte")


def _load_kit(directory: Path, *, experiment: Path | None = None,
              corpus_path: Path | None = None) -> tuple[dict, dict]:
    root = directory.expanduser().absolute()
    if root.is_symlink() or not root.is_dir() or set(p.name for p in root.iterdir()) != {"public", "private"}:
        raise BenchmarkError("Hoertest-Paket braucht genau public und private als echte Verzeichnisse")
    public, private = root / "public", root / "private"
    if public.is_symlink() or private.is_symlink() or not public.is_dir() or not private.is_dir():
        raise BenchmarkError("Hoertest-Verzeichnisse fehlen oder sind Symlinks")
    if set(p.name for p in private.iterdir()) != {"key.json"} or (private / "key.json").is_symlink():
        raise BenchmarkError("Private Hoertest-Daten duerfen nur den Schluessel enthalten")
    for name in ("README.md", "manifest.json", "review-template.json"):
        if (public / name).is_symlink() or not (public / name).is_file():
            raise BenchmarkError("Oeffentliche Hoertest-Metadaten fehlen oder sind Symlinks")

    manifest = _json(public / "manifest.json")
    required_manifest = {"schema_version", "kind", "protocol", "experiment_id", "corpus_id",
                         "profiles_disclosed", "instructions", "criteria", "scale", "cases",
                         "items", "limitations", "kit_id"}
    _exact_keys(manifest, required_manifest, "Hoertest-Manifest")
    identity = {key: value for key, value in manifest.items() if key != "kit_id"}
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["kind"] != "nexpt-blind-listening-kit"
            or manifest["protocol"] != "paired-known-reference-v1"
            or manifest["profiles_disclosed"] is not False
            or manifest["kit_id"] != _digest(identity)
            or tuple(manifest["criteria"]) != CRITERIA
            or manifest["scale"] != {"minimum": 1, "maximum": 5}):
        raise BenchmarkError("Ungueltiges oder veraendertes Hoertest-Manifest")
    if (not isinstance(manifest["cases"], list) or not manifest["cases"]
            or not isinstance(manifest["items"], list) or not manifest["items"]):
        raise BenchmarkError("Hoertest-Paket braucht Cases und Items")

    expected_files = {"README.md", "manifest.json", "review-template.json"}
    if manifest["instructions"] != _entry(public / "README.md", public):
        raise BenchmarkError("Hoertest-Anleitung wurde veraendert")
    cases = {}
    for case in manifest["cases"]:
        _exact_keys(case, {"id", "sample_rate", "frames", "channels", "mix",
                           "references", "reference_active"}, "Hoertest-Case")
        identifier = case["id"]
        if (not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identifier)
                or identifier in cases or set(case["references"]) != set(ROLES)
                or set(case["reference_active"]) != set(ROLES)):
            raise BenchmarkError("Ungueltiger oder doppelter Hoertest-Case")
        expected_mix = f"audio/references/{identifier}/mix.wav"
        if case["mix"].get("path") != expected_mix:
            raise BenchmarkError("Unerwarteter Mix-Pfad im Hoertest")
        mix_path = _packaged_file(public, case["mix"])
        rate, mix = _wav(mix_path)
        if (rate != case["sample_rate"] or mix.shape != (case["frames"], case["channels"])
                or type(case["channels"]) is not int or case["channels"] != 2):
            raise BenchmarkError("Hoertest-Mix stimmt nicht mit seinen Metadaten")
        expected_files.add(expected_mix)
        for role in ROLES:
            expected = f"audio/references/{identifier}/{role}.wav"
            if case["references"][role].get("path") != expected:
                raise BenchmarkError("Unerwarteter Referenzpfad im Hoertest")
            ref_rate, audio = _wav(_packaged_file(public, case["references"][role]))
            if (ref_rate != rate or audio.shape != mix.shape
                    or case["reference_active"][role] is not bool(rms(audio) > SILENCE_RMS)):
                raise BenchmarkError("Hoertest-Referenz stimmt nicht mit Case oder Aktivitaetslabel")
            expected_files.add(expected)
        cases[identifier] = case

    items = {}
    for item in manifest["items"]:
        _exact_keys(item, {"id", "trial", "case_id", "role", "candidates"}, "Hoertest-Item")
        identifier = item["id"]
        if (not isinstance(identifier, str) or not re.fullmatch(r"item-[0-9]{4}", identifier)
                or identifier in items or item["case_id"] not in cases or item["role"] not in ROLES
                or type(item["trial"]) is not int or item["trial"] < 1
                or set(item["candidates"]) != {"A", "B"}):
            raise BenchmarkError("Ungueltiges oder doppeltes Hoertest-Item")
        shape = (cases[item["case_id"]]["frames"], cases[item["case_id"]]["channels"])
        rate = cases[item["case_id"]]["sample_rate"]
        for label in ("A", "B"):
            expected = f"audio/items/{identifier}/{label}.wav"
            entry = item["candidates"][label]
            if entry.get("path") != expected:
                raise BenchmarkError("Unerwarteter Kandidatenpfad im Hoertest")
            candidate_rate, audio = _wav(_packaged_file(public, entry))
            if candidate_rate != rate or audio.shape != shape:
                raise BenchmarkError("Hoertest-Kandidat ist nicht samplegenau ausgerichtet")
            expected_files.add(expected)
        items[identifier] = item
    if set(items) != {f"item-{number:04d}" for number in range(1, len(items) + 1)}:
        raise BenchmarkError("Hoertest-Itemnummern sind nicht lueckenlos")

    template = _json(public / "review-template.json")
    if template != _review_template(manifest):
        raise BenchmarkError("Hoertest-Vorlage wurde veraendert")
    _verify_public_tree(public, expected_files)

    key = _json(private / "key.json")
    required_key = {"schema_version", "kind", "kit_id", "experiment_id", "corpus_id",
                    "mappings", "report_id"}
    _exact_keys(key, required_key, "Hoertest-Schluessel")
    if (type(key["schema_version"]) is not int or key["schema_version"] != 1
            or key["kind"] != "nexpt-blind-listening-key"
            or key["kit_id"] != manifest["kit_id"]
            or key["experiment_id"] != manifest["experiment_id"]
            or key["corpus_id"] != manifest["corpus_id"]
            or key["report_id"] != _digest({k: v for k, v in key.items() if k != "report_id"})):
        raise BenchmarkError("Ungueltiger oder veraenderter Hoertest-Schluessel")
    mappings = {}
    for mapping in key["mappings"]:
        _exact_keys(mapping, {"id", "candidates"}, "Hoertest-Zuordnung")
        if mapping["id"] in mappings or mapping["id"] not in items or set(mapping["candidates"]) != {"A", "B"}:
            raise BenchmarkError("Ungueltige oder doppelte Hoertest-Zuordnung")
        for label, candidate in mapping["candidates"].items():
            _exact_keys(candidate, {"quality", "job", "sha256"}, "private Kandidaten-Zuordnung")
            if (candidate["quality"] not in ("standard", "high")
                    or candidate["sha256"] != items[mapping["id"]]["candidates"][label]["sha256"]):
                raise BenchmarkError("Private Zuordnung stimmt nicht mit dem oeffentlichen Kandidaten")
        if {c["quality"] for c in mapping["candidates"].values()} != {"standard", "high"}:
            raise BenchmarkError("Jedes Item muss genau Standard und High enthalten")
        mappings[mapping["id"]] = mapping
    if set(mappings) != set(items):
        raise BenchmarkError("Private Zuordnung deckt nicht alle Hoertest-Items ab")

    if experiment is not None:
        experiment_root = experiment.expanduser().absolute()
        plan = _load_plan(experiment_root)
        if plan["experiment_id"] != manifest["experiment_id"] or plan["corpus_id"] != manifest["corpus_id"]:
            raise BenchmarkError("Hoertest gehoert nicht zum angegebenen A/B-Versuch")
        jobs = {job["id"]: job for job in plan["jobs"]}
        reports = {name: _read_run(experiment_root, plan, job) for name, job in jobs.items()}
        report_rows = {name: _source_rows(report) for name, report in reports.items() if report is not None}
        expected_cases = [case["id"] for case in plan["cases"]]
        if [case["id"] for case in manifest["cases"]] != expected_cases:
            raise BenchmarkError("Hoertest-Case-Abdeckung stimmt nicht mit dem A/B-Versuch")
        expected_items = {(trial, case_id, role)
                          for trial in range(1, plan["parameters"]["repeats"] + 1)
                          for case_id in expected_cases for role in ROLES}
        actual_items = {(item["trial"], item["case_id"], item["role"])
                        for item in manifest["items"]}
        if len(manifest["items"]) != len(expected_items) or actual_items != expected_items:
            raise BenchmarkError("Hoertest deckt nicht jedes Trial/Case/Rollen-Paar genau einmal ab")
        for identifier, mapping in mappings.items():
            item = items[identifier]
            for label, candidate in mapping["candidates"].items():
                job = jobs.get(candidate["job"])
                if (job is None or job["trial"] != item["trial"] or job["quality"] != candidate["quality"]
                        or candidate["job"] not in report_rows):
                    raise BenchmarkError("Private Zuordnung verweist auf einen falschen A/B-Lauf")
                row = report_rows[candidate["job"]].get(item["case_id"])
                if (not row or row.get("status") != "evaluated"
                        or row["estimates"][item["role"]]["sha256"] != candidate["sha256"]):
                    raise BenchmarkError("Private Zuordnung passt nicht zu den gespeicherten Modellresultaten")

    if corpus_path is not None:
        corpus_file = corpus_path.expanduser().resolve()
        corpus = load_corpus(corpus_file)
        if corpus["corpus_id"] != manifest["corpus_id"]:
            raise BenchmarkError("Hoertest gehoert nicht zum angegebenen Referenz-Corpus")
        source_cases = {case["id"]: case for case in corpus["cases"]}
        if [case["id"] for case in manifest["cases"]] != [case["id"] for case in corpus["cases"]]:
            raise BenchmarkError("Hoertest-Case-Abdeckung stimmt nicht mit dem Referenz-Corpus")
        for case in manifest["cases"]:
            source = source_cases[case["id"]]
            if (case["sample_rate"] != source["sample_rate"] or case["frames"] != source["frames"]
                    or case["channels"] != source["channels"]
                    or case["mix"]["sha256"] != source["mix"]["sha256"]
                    or any(case["references"][role]["sha256"] != source["stems"][role]["sha256"]
                           for role in ROLES)):
                raise BenchmarkError("Hoertest-Referenzen stimmen nicht mit dem Corpus ueberein")
    return manifest, key


def _validate_review(payload: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "kind", "kit_id", "reviewer_id", "playback", "items"}
    _exact_keys(payload, required, "Hoertest-Bewertung")
    reviewer = payload["reviewer_id"]
    if (type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or payload["kind"] != "nexpt-blind-listening-review"
            or payload["kit_id"] != manifest["kit_id"]
            or not isinstance(reviewer, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", reviewer)
            or reviewer == "replace-me"):
        raise BenchmarkError("Bewertung hat ungueltige Version, Kit-ID oder reviewer_id")
    _exact_keys(payload["playback"], {"device", "environment"}, "Playback-Angaben")
    if any(not isinstance(value, str) or len(value) > 200 for value in payload["playback"].values()):
        raise BenchmarkError("Playback-Angaben muessen kurze Texte sein")
    if not isinstance(payload["items"], list):
        raise BenchmarkError("Bewertung braucht eine Item-Liste")
    expected = {item["id"] for item in manifest["items"]}
    rows = {}
    for row in payload["items"]:
        _exact_keys(row, {"id", "preference", "confidence", "ratings", "notes"}, "Bewertungs-Item")
        identifier = row["id"]
        if identifier in rows or identifier not in expected or row["preference"] not in PREFERENCES:
            raise BenchmarkError("Bewertung enthaelt ein unbekanntes, doppeltes oder unvollstaendiges Item")
        if type(row["confidence"]) is not int or not 1 <= row["confidence"] <= 5:
            raise BenchmarkError("confidence muss eine ganze Zahl von 1 bis 5 sein")
        _exact_keys(row["ratings"], {"A", "B"}, "Kandidatenbewertungen")
        for ratings in row["ratings"].values():
            _exact_keys(ratings, set(CRITERIA), "Bewertungskriterien")
            if any(type(value) is not int or not 1 <= value <= 5 for value in ratings.values()):
                raise BenchmarkError("Alle Bewertungskriterien brauchen ganze Werte von 1 bis 5")
        if not isinstance(row["notes"], str) or len(row["notes"]) > MAX_NOTES:
            raise BenchmarkError("Notizen muessen Text bis 2000 Zeichen sein")
        rows[identifier] = row
    if set(rows) != expected:
        raise BenchmarkError("Bewertung muss jedes Hoertest-Item genau einmal enthalten")
    return {**payload, "items": [rows[item["id"]] for item in manifest["items"]]}


def _distribution(values: list[int]) -> dict[str, Any]:
    return {"count": len(values), "median": float(median(values)) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def _aggregate(judgements: list[dict[str, Any]]) -> dict[str, Any]:
    preferences = {name: sum(row["preference"] == name for row in judgements)
                   for name in ("standard", "high", "tie", "both_unusable")}
    return {"judgements": len(judgements), "preference_counts": preferences,
            "high_minus_standard": {
                criterion: _distribution([row["deltas"][criterion] for row in judgements])
                for criterion in CRITERIA
            },
            "confidence": _distribution([row["confidence"] for row in judgements])}


def summarize_listening(kit: Path, experiment: Path, corpus_path: Path,
                        review_paths: list[Path]) -> dict[str, Any]:
    if not 1 <= len(review_paths) <= MAX_REVIEWS:
        raise BenchmarkError("Hoertest-Auswertung braucht 1–20 vollstaendige Bewertungen")
    manifest, key = _load_kit(kit, experiment=experiment, corpus_path=corpus_path)
    mappings = {row["id"]: row for row in key["mappings"]}
    items = {row["id"]: row for row in manifest["items"]}
    reviews, sources, reviewer_ids = [], [], set()
    for path in review_paths:
        supplied = path.expanduser().absolute()
        if supplied.is_symlink() or not supplied.is_file():
            raise BenchmarkError("Bewertungsdatei fehlt oder ist ein Symlink")
        source = supplied.resolve()
        before = sha256(source)
        review = _validate_review(_json(source), manifest)
        if review["reviewer_id"] in reviewer_ids:
            raise BenchmarkError("reviewer_id muss ueber alle Bewertungen eindeutig sein")
        reviewer_ids.add(review["reviewer_id"])
        reviews.append(review)
        sources.append({"reviewer_id": review["reviewer_id"],
                        "playback": review["playback"], "sha256": before})

    judgements = []
    for review in reviews:
        for row in review["items"]:
            item = items[row["id"]]
            mapping = mappings[row["id"]]["candidates"]
            labels = {candidate["quality"]: label for label, candidate in mapping.items()}
            if row["preference"] in ("A", "B"):
                preference = mapping[row["preference"]]["quality"]
            else:
                preference = row["preference"]
            deltas = {criterion: row["ratings"][labels["high"]][criterion]
                      - row["ratings"][labels["standard"]][criterion]
                      for criterion in CRITERIA}
            judgements.append({"reviewer_id": review["reviewer_id"], "item_id": row["id"],
                               "case_id": item["case_id"], "role": item["role"],
                               "trial": item["trial"], "preference": preference,
                               "confidence": row["confidence"], "deltas": deltas})
    per_item = []
    for item in manifest["items"]:
        rows = [row for row in judgements if row["item_id"] == item["id"]]
        per_item.append({"id": item["id"], "case_id": item["case_id"],
                         "role": item["role"], "trial": item["trial"], **_aggregate(rows)})
    result = _seal({
        "schema_version": 1,
        "kind": "nexpt-blind-listening-summary",
        "kit_id": manifest["kit_id"],
        "experiment_id": manifest["experiment_id"],
        "corpus_id": manifest["corpus_id"],
        "key_id": key["report_id"],
        "status": "reviewed",
        "declared_human_reviewers": len(reviews),
        "review_sources": sources,
        "expected_items_per_reviewer": len(manifest["items"]),
        "completed_judgements": len(judgements),
        "overall": _aggregate(judgements),
        "cases": {case["id"]: _aggregate([row for row in judgements
                                            if row["case_id"] == case["id"]])
                  for case in manifest["cases"]},
        "roles": {role: _aggregate([row for row in judgements if row["role"] == role]) for role in ROLES},
        "items": per_item,
        "listening_review_completed": True,
        "perceptual_quality_verified": False,
        "overall_winner": None,
        "limitations": [
            "Ratings are self-declared and this program cannot verify playback conditions or that listening occurred.",
            "Repeated trials of the same cases and multiple ratings by one person are not independent recordings.",
            "Observed counts and rating deltas are descriptive; no significance or automatic model ranking is claimed.",
            "The private key and original experiment must remain unavailable to reviewers until forms are final.",
        ],
    })
    for path, expected in zip(review_paths, sources):
        if sha256(path.expanduser().resolve()) != expected["sha256"]:
            raise BenchmarkError("Bewertungsdatei wurde waehrend der Auswertung geaendert")
    _load_kit(kit, experiment=experiment, corpus_path=corpus_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="create a blinded public kit and a separate private key")
    build.add_argument("experiment", type=Path)
    build.add_argument("corpus", type=Path)
    build.add_argument("--output-dir", type=Path, required=True)
    summary = commands.add_parser("summarize", help="validate, unblind and aggregate completed reviews")
    summary.add_argument("kit", type=Path)
    summary.add_argument("reviews", nargs="+", type=Path)
    summary.add_argument("--experiment", type=Path, required=True)
    summary.add_argument("--corpus", type=Path, required=True)
    summary.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    code = 0
    try:
        if args.command == "build":
            result = build_listening_kit(args.experiment, args.corpus, args.output_dir)
        else:
            output = args.output_dir.expanduser().absolute().resolve()
            if output.is_relative_to(args.kit.expanduser().absolute().resolve()):
                raise BenchmarkError("Auswertung darf nicht in das unveraenderliche Hoertest-Paket geschrieben werden")
            result = summarize_listening(args.kit, args.experiment, args.corpus, args.reviews)
            with _bundle(args.output_dir) as bundle:
                _write_json(bundle / "listening-summary.json", result)
    except (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError, EOFError) as exc:
        result, code = {"status": "failed", "error": str(exc)}, 1
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    raise SystemExit(code)


if __name__ == "__main__":
    main()

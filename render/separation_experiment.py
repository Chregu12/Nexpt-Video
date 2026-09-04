"""Repeat paired CDX profiles, preserve completed runs and verify explicit resume.

The experiment is an immutable plan plus immutable run bundles. Only new runs
and content-addressed summaries are added. No hidden retry or winner selection.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import math
import os
from pathlib import Path
import re
from statistics import median
from typing import Any

from cinematic_separation import sha256
from separation_benchmark import (BenchmarkError, MAX_CASES, _bundle, _digest,
                                  _evaluation_policy, _implementation_id, _json,
                                  _owned_file, _seal, _summarize, _write_json,
                                  compare_reports, load_corpus, run_cdx)
from separation_metrics import Gates, METRIC_VERSION, ROLES
from separation_preflight import preflight


INTEGRATION_FILES = ("separation_experiment.py", "separation_benchmark.py", "separation_metrics.py",
                     "separation_preflight.py", "cinematic_separation.py", "cdx_runtime.py",
                     "cdx_safe_inference.py", "audio_decomposition.py", "music_separation.py", "video_music.py")
DELTA_FIELDS = ("snr_db_delta", "si_sdr_db_delta", "silent_window_rms_delta")


def _integration() -> dict[str, str]:
    return {name: sha256(Path(__file__).with_name(name)) for name in INTEGRATION_FILES}


def _schedule(repeats: int) -> list[dict[str, Any]]:
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise BenchmarkError("Ein A/B-Versuch braucht 1–5 Wiederholungen je Profil")
    return [{"id": f"trial-{trial:02d}-{quality}", "trial": trial, "quality": quality}
            for trial in range(1, repeats + 1)
            for quality in (("standard", "high") if trial % 2 else ("high", "standard"))]


def _make_plan(corpus: dict, config: Path, checks: dict, *, repeats: int, device: str,
               timeout: float, gates: Gates) -> dict[str, Any]:
    config_hash = sha256(config)
    if checks["corpus_id"] != corpus["corpus_id"] or any(
            row["config_sha256"] != config_hash for row in checks["profiles"].values()):
        raise BenchmarkError("Referenzen/Konfiguration wurden nach der Vorpruefung geaendert")
    plan = {"schema_version": 1, "kind": "nexpt-cdx-ab-experiment", "corpus_id": corpus["corpus_id"],
            "config_sha256": config_hash, "integration_sha256": _integration(),
            "runtime_fingerprints": {p: checks["profiles"][p]["runtime"]["fingerprint"] for p in ("standard", "high")},
            "parameters": {"repeats": repeats, "device": device, "timeout": timeout, "gates": asdict(gates)},
            "contract": {"corpus_id": corpus["corpus_id"], "metric_version": METRIC_VERSION,
                         "metric_implementation_sha256": sha256(Path(__file__).with_name("separation_metrics.py")),
                         "benchmark_implementation_sha256": _implementation_id(),
                         "gate_profile": {"calibration": "provisional-engineering-v1", **asdict(gates)},
                         "evaluation_policy": _evaluation_policy()},
            "cases": [{"id": row["id"], "reference_kind": row["reference_kind"]} for row in corpus["cases"]],
            "jobs": _schedule(repeats), "random_seed": None,
            "note": "Alternating run order; stochastic CDX shifts are not made deterministic by repetition."}
    return {**plan, "experiment_id": _digest(plan)}


def _directory(root: Path, name: str) -> Path:
    path = root / name
    if path.is_symlink() or not path.is_dir():
        raise BenchmarkError(f"Versuchsverzeichnis fehlt oder ist ein Symlink: {name}")
    return path


def _load_plan(root: Path) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir() or (root / "experiment.json").is_symlink():
        raise BenchmarkError("A/B-Versuch muss ein eigenes Verzeichnis ohne Paket-Symlinks sein")
    plan = _json(root / "experiment.json")
    if (not isinstance(plan, dict) or type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or plan.get("kind") != "nexpt-cdx-ab-experiment"
            or plan.get("experiment_id") != _digest({k: v for k, v in plan.items() if k != "experiment_id"})):
        raise BenchmarkError("Ungueltiger oder veraenderter A/B-Versuchsplan")
    if plan["jobs"] != _schedule(plan["parameters"]["repeats"]):
        raise BenchmarkError("Versuchsplan hat eine ungueltige Job-Reihenfolge")
    cases = plan["cases"]
    if (not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES
            or any(not isinstance(c, dict) or not isinstance(c.get("id"), str)
                   or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", c["id"])
                   or c.get("reference_kind") != "isolated-recordings" for c in cases)
            or len({c["id"] for c in cases}) != len(cases)):
        raise BenchmarkError("Versuchsplan braucht eindeutige deklarierte Aufnahme-Cases")
    for name in ("runs", "summaries"):
        _directory(root, name)
    return plan


@contextmanager
def _lock(root: Path):
    try:
        import fcntl
    except ImportError as exc:
        raise BenchmarkError("A/B-Prozesssperre braucht Linux/macOS (fcntl)") from exc
    # Kernel locks are released even after process death. Never delete or steal
    # a lock file, and never follow a substituted symlink when opening it.
    descriptor = os.open(root / ".experiment.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "r+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BenchmarkError("Dieser A/B-Versuch wird bereits von einem anderen Prozess ausgefuehrt") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read_run(root: Path, plan: dict, job: dict) -> dict | None:
    directory = root / "runs" / job["id"]
    if not directory.exists() and not directory.is_symlink():
        return None
    return _verify_run(directory, plan, job)


def _verify_run(directory: Path, plan: dict, job: dict) -> dict:
    if directory.is_symlink() or not directory.is_dir() or (directory / "report.json").is_symlink():
        raise BenchmarkError(f"Ungueltiges Laufverzeichnis: {job['id']}")
    path = directory / "report.json"
    receipt_path = directory / "completion.json"
    if receipt_path.is_symlink():
        raise BenchmarkError("Laufbeleg darf kein Symlink sein")
    receipt = _json(receipt_path)
    if (not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1
            or receipt.get("kind") != "nexpt-ab-run-completion"
            or receipt.get("report_id") != _digest({k: v for k, v in receipt.items() if k != "report_id"})
            or receipt.get("experiment_id") != plan["experiment_id"] or receipt.get("job") != job
            or receipt.get("benchmark_report_sha256") != sha256(path)):
        raise BenchmarkError("Laufbeleg stimmt nicht mit Versuch, Wiederholung oder Bericht ueberein")
    # Reuse the sealed report/schema checks, including explicit failed cases.
    compare_reports([path, path])
    report = _json(path)
    if report["report_id"] != receipt.get("benchmark_report_id"):
        raise BenchmarkError("Laufbeleg verweist auf einen anderen Benchmark-Bericht")
    if any(report.get(key) != expected for key, expected in plan["contract"].items()):
        raise BenchmarkError(f"Lauf gehoert zu anderen Referenzen/Messregeln: {job['id']}")
    candidate = report["candidate"]
    if (candidate.get("kind") != "configured-cdx-run" or candidate.get("quality") != job["quality"]
            or candidate.get("device") != plan["parameters"]["device"]
            or candidate.get("config_sha256") != plan["config_sha256"]
            or candidate.get("estimates_dir") != "estimates"):
        raise BenchmarkError(f"Modellprofil/Konfiguration des Laufs stimmt nicht: {job['id']}")
    rows = report["cases"]
    expected_cases = {c["id"]: c["reference_kind"] for c in plan["cases"]}
    if (len(rows) != len(expected_cases) or {c["id"]: c["reference_kind"] for c in rows} != expected_cases
            or any(c["status"] not in ("evaluated", "failed") for c in rows)
            or report["summary"] != _summarize(rows)):
        raise BenchmarkError(f"Case-Abdeckung/Zaehler des Laufs stimmt nicht: {job['id']}")
    estimates = _directory(directory, "estimates")
    expected_files, expected_directories = set(), set()
    for case in rows:
        if case["status"] != "evaluated":
            continue
        expected_directories.add(case["id"])
        if set(case["estimates"]) != set(ROLES):
            raise BenchmarkError("Im fertigen Lauf fehlen Stem-Eintraege")
        for role, entry in case["estimates"].items():
            if entry.get("path") != f"{case['id']}/{role}.wav":
                raise BenchmarkError("Unbekannter Stem-Pfad im fertigen Lauf")
            _owned_file(estimates, entry)
            expected_files.add(entry["path"])
    for item in estimates.rglob("*"):
        relative = str(item.relative_to(estimates))
        if (item.is_symlink() or (item.is_dir() and relative not in expected_directories)
                or (item.is_file() and relative not in expected_files)
                or (not item.is_dir() and not item.is_file())):
            raise BenchmarkError("Fertiger Lauf enthaelt unbekannte oder nicht belegte Artefakte")
    if _json(path) != report or _json(receipt_path) != receipt:
        raise BenchmarkError("Bericht/Laufbeleg wurde waehrend seiner Pruefung geaendert")
    return report


def _distribution(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "median": float(median(values)) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def summarize_experiment(directory: Path) -> dict[str, Any]:
    """Inspect immutable local run evidence, without requiring original sources or models."""
    root = directory.expanduser().absolute()
    plan = _load_plan(root)
    reports = {job["id"]: _read_run(root, plan, job) for job in plan["jobs"]}
    pending = [job for job, report in reports.items() if report is None]
    completed = {job: report for job, report in reports.items() if report is not None}
    pair_reports = []
    for trial in range(1, plan["parameters"]["repeats"] + 1):
        names = [f"trial-{trial:02d}-{quality}" for quality in ("standard", "high")]
        if all(reports[name] is not None for name in names):
            pair_reports.append({"trial": trial, **compare_reports([root / "runs" / name / "report.json" for name in names])})
    case_results = []
    for case in plan["cases"]:
        pairs = [row["right_minus_left"] for comparison in pair_reports for row in comparison["pairs"] if row["id"] == case["id"]]
        case_results.append({"id": case["id"], "paired_trials": len(pairs),
            "missing_or_failed_trials": plan["parameters"]["repeats"] - len(pairs),
            "high_minus_standard": {role: {
                **{field: _distribution([row[role][field] for row in pairs if row[role][field] is not None]) for field in DELTA_FIELDS},
                "standard_gate_passes": sum(row[role]["left_gate_passed"] for row in pairs),
                "high_gate_passes": sum(row[role]["right_gate_passed"] for row in pairs)} for role in ROLES}})
    failed = [{"job": job, "case": case["id"], "error": case["error"]}
              for job, report in completed.items() for case in report["cases"] if case["status"] == "failed"]
    complete = not pending and not failed
    result = {"schema_version": 1, "kind": "nexpt-cdx-ab-summary", "experiment_id": plan["experiment_id"],
              "corpus_id": plan["corpus_id"], "summary_implementation_sha256": sha256(Path(__file__)),
              "status": "complete" if complete else "incomplete", "planned_runs": len(plan["jobs"]),
              "completed_runs": len(completed), "pending_jobs": pending,
              "planned_case_attempts": len(plan["jobs"]) * len(plan["cases"]),
              "evaluated_case_attempts": sum(r["summary"]["evaluated_cases"] for r in completed.values()),
              "failed_case_attempts": failed, "pending_case_attempts": len(pending) * len(plan["cases"]),
              "report_ids": {job: report["report_id"] for job, report in completed.items()},
              "pairs": pair_reports, "cases": case_results,
              "numerical_gate_passed": complete and all(r["summary"]["numerical_gate_passed"] for r in completed.values()),
              "overall_winner": None, "perceptual_quality_verified": False, "listening_review_required": True,
              "limitations": ["Paired observed min/median/max, not confidence intervals or model rankings.",
                              "Repeated cases are not additional independent recordings; no significance claim.",
                              "No delay/gain fitting, normalization, best-run selection or failed-case deletion.",
                              "Saved evidence only; this summary does not probe the current model runtime or original media.",
                              "Local checksums are integrity checks, not signed external attestations."]}
    # Detect reports changed between artifact validation and paired comparison.
    for job, report in completed.items():
        if _json(root / "runs" / job / "report.json") != report:
            raise BenchmarkError("Laufbericht wurde waehrend der Zusammenfassung geaendert")
    if _load_plan(root) != plan:
        raise BenchmarkError("Versuchsplan wurde waehrend der Zusammenfassung geaendert")
    return _seal(result)


def _assert_context(corpus_path: Path, config: Path, plan: dict) -> None:
    if (load_corpus(corpus_path)["corpus_id"] != plan["corpus_id"]
            or sha256(config) != plan["config_sha256"] or _integration() != plan["integration_sha256"]):
        raise BenchmarkError("Referenzen, Konfiguration oder Integrationscode geaendert; neuen Versuch anlegen")


def run_experiment(corpus_path: Path, config: Path, destination: Path, *, repeats: int = 3,
                   device: str = "cpu", timeout: float = 600, gates: Gates | None = None,
                   resume: bool = False, max_new_runs: int | None = None) -> dict[str, Any]:
    jobs = _schedule(repeats)
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or not 1 <= timeout <= 3600 or device not in ("cpu", "cuda")):
        raise BenchmarkError("A/B braucht cpu/cuda und ein Zeitlimit von 1–3600 s je Modellprozess")
    if max_new_runs is not None and (type(max_new_runs) is not int or not 1 <= max_new_runs <= len(jobs)):
        raise BenchmarkError("max_new_runs muss zwischen 1 und der geplanten Laufzahl liegen")
    gates = gates or Gates()
    gates.validate()
    root = destination.expanduser().absolute()
    if root.exists() or root.is_symlink():
        if not resume:
            raise BenchmarkError("A/B-Ziel existiert bereits; nur mit explizitem --resume fortsetzen")
        _load_plan(root)  # Do not write a lock into an unrelated user directory.
    elif resume:
        raise BenchmarkError("Kein vorhandener A/B-Versuch zum Fortsetzen")
    corpus_path, config = corpus_path.expanduser().resolve(), config.expanduser().resolve()
    checks = preflight(corpus_path, config=config, profiles=("standard", "high"), device=device)
    if not checks["ready_for_run"]:
        return {"status": "blocked", "preflight": checks, "model_inference_executed": False,
                "numerical_gate_passed": False, "perceptual_quality_verified": False}
    if not all(checks["profiles"][p]["runtime_locked"] for p in ("standard", "high")):
        raise BenchmarkError("Wiederholbare A/B-Laeufe brauchen eine mit --verify-runtime registrierte CDX-Konfiguration")
    plan = _make_plan(load_corpus(corpus_path), config, checks, repeats=repeats, device=device, timeout=timeout, gates=gates)
    if not resume:
        with _bundle(root) as bundle:
            _write_json(bundle / "experiment.json", plan)
            _write_json(bundle / "preflight.json", checks)
            (bundle / "runs").mkdir()
            (bundle / "summaries").mkdir()
    with _lock(root):
        if _load_plan(root) != plan:
            raise BenchmarkError("Fortsetzen passt nicht zum gespeicherten Plan: Referenzen, Optionen, Runtime oder Code geaendert")
        # Verify ALL saved outputs before spending more compute on any new run.
        existing = {job["id"]: _read_run(root, plan, job) for job in jobs}
        executed = 0
        for job in jobs:
            if existing[job["id"]] is not None:
                continue  # Failed case reports are evidence, never silently retried.
            if max_new_runs is not None and executed >= max_new_runs:
                break
            _assert_context(corpus_path, config, plan)
            with _bundle(root / "runs" / job["id"]) as stage:
                run_cdx(corpus_path, config, stage / "result", quality=job["quality"],
                        device=device, timeout=timeout, gates=gates)
                _assert_context(corpus_path, config, plan)
                for child in (stage / "result").iterdir():
                    child.rename(stage / child.name)
                (stage / "result").rmdir()
                report = _json(stage / "report.json")
                _write_json(stage / "completion.json", _seal({
                    "schema_version": 1, "kind": "nexpt-ab-run-completion", "experiment_id": plan["experiment_id"],
                    "job": job, "benchmark_report_id": report["report_id"],
                    "benchmark_report_sha256": sha256(stage / "report.json")}))
                _verify_run(stage, plan, job)
            if _read_run(root, plan, job) is None:
                raise BenchmarkError("Modelllauf hat keinen pruefbaren Bericht publiziert")
            executed += 1
        _assert_context(corpus_path, config, plan)
        summary = summarize_experiment(root)
        path = _directory(root, "summaries") / f"summary-{summary['report_id'][:16]}.json"
        if path.exists() or path.is_symlink():
            if path.is_symlink() or _json(path) != summary:
                raise BenchmarkError("Vorhandene Zusammenfassung wurde veraendert; kein Ueberschreiben")
        else:
            _write_json(path, summary)
        return summary

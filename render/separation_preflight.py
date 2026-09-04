"""Read-only readiness checks for a real-recording CDX benchmark.

Checks input coverage, hashes, selected checkpoints and actual dependency imports.
Never executes model inference or turns engineering readiness into a quality claim.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cdx_runtime import probe_runtime
from cinematic_separation import CdxSeparator, sha256
from separation_benchmark import BenchmarkError, _case_audio, _digest, load_corpus
from separation_metrics import ROLES, SILENCE_RMS, rms
from video_music import executable


COVERAGE_POLICY = "nexpt-real-reference-coverage-v1"
EXPECTED_ERRORS = (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError, EOFError)


def _coverage(path: Path, corpus: dict) -> dict[str, Any]:
    active_counts = {role: 0 for role in ROLES}
    counts = {"three_role_overlap_cases": 0, "music_sfx_without_dialogue_cases": 0, "music_only_cases": 0}
    rows = []
    for case in corpus["cases"]:
        _, refs = _case_audio(path.parent, case)
        active = {role: rms(refs[role]) > SILENCE_RMS for role in ROLES}
        for role, present in active.items():
            active_counts[role] += int(present)
        # Coexistence within a 250 ms window is a declared coarse coverage rule,
        # not evidence that sample-level events coincide or that speech is present.
        window = max(1, case["sample_rate"] // 4)
        overlap = sum(all(rms(refs[role][start:start + window]) > SILENCE_RMS for role in ROLES)
                      for start in range(0, case["frames"], window))
        counts["three_role_overlap_cases"] += int(overlap > 0)
        counts["music_sfx_without_dialogue_cases"] += int(active["music"] and active["sfx"] and not active["dialogue"])
        counts["music_only_cases"] += int(active["music"] and not active["dialogue"] and not active["sfx"])
        rows.append({"id": case["id"], "reference_kind": case["reference_kind"],
                     "active_roles": active, "overlap_windows": overlap,
                     "channels": case["channels"], "seconds": case["frames"] / case["sample_rate"]})
    return {"policy": COVERAGE_POLICY, "total_cases": len(rows), "active_case_counts": active_counts,
            **counts, "cases": rows, "source_labels_verified": False,
            "note": "Energy coverage only; isolated-recordings is an author declaration, not authenticated source labeling."}


def preflight(corpus_path: Path, *, config: Path | None = None,
              profiles: tuple[str, ...] = ("standard", "high"), device: str = "cpu") -> dict[str, Any]:
    if (not profiles or len(profiles) != len(set(profiles))
            or any(p not in ("standard", "high") for p in profiles) or device not in ("cpu", "cuda")):
        raise BenchmarkError("Vorpruefung braucht standard/high und cpu/cuda")
    corpus_path = corpus_path.expanduser().resolve()
    result: dict[str, Any] = {
        "schema_version": 1, "kind": "nexpt-separation-preflight", "device": device,
        "corpus_id": None, "coverage": None, "profiles": {}, "blockers": [], "warnings": [],
        "implementation_sha256": _digest({name: sha256(Path(__file__).with_name(name)) for name in
                                           ("separation_preflight.py", "cdx_runtime.py", "cinematic_separation.py")}),
        "reference_ready": False, "ready_for_run": False, "model_inference_executed": False,
        "runtime_verified": False, "perceptual_quality_verified": False,
    }

    def block(code: str, detail: str, *, scope: str) -> None:
        result["blockers"].append({"code": code, "scope": scope, "detail": detail})

    corpus = None
    corpus_hash = None
    try:
        corpus_hash = sha256(corpus_path)
        corpus = load_corpus(corpus_path)
        result["corpus_id"] = corpus["corpus_id"]
        coverage = result["coverage"] = _coverage(corpus_path, corpus)
        if any(row["reference_kind"] != "isolated-recordings" for row in coverage["cases"]):
            block("diagnostic_references", "Synthetische Kontrollen sind keine Freigabe fuer einen Aufnahme-Benchmark.", scope="references")
        if any(row["channels"] != 2 for row in coverage["cases"]):
            block("stereo_required", "CDX braucht Stereo; Mono bewusst mit prepare vorbereiten.", scope="references")
        for field, detail in (
            ("three_role_overlap_cases", "Mindestens ein Fall mit Musik, Dialog und SFX im selben 250-ms-Fenster fehlt."),
            ("music_sfx_without_dialogue_cases", "Musik mit SFX ohne Dialog fehlt als Kontrolle unerwuenschter Sprache."),
            ("music_only_cases", "Reine Musik fehlt als Erhaltungskontrolle ohne Dialog und SFX."),
        ):
            if not coverage[field]:
                block(field, detail, scope="references")
    except EXPECTED_ERRORS as exc:
        block("invalid_corpus", str(exc), scope="references")

    for name in ("ffmpeg", "ffprobe"):
        if not executable(name, required=False):
            block(f"missing_{name}", f"{name} fuer die CDX-Dekodierung installieren oder konfigurieren.", scope="tools")
    if os.environ.get("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "").lower() in {"1", "y", "yes", "true"}:
        block("unsafe_loader_environment", "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD wird vom sicheren Runner abgelehnt.", scope="tools")

    runtimes: dict[str, dict] = {}
    backends: list[tuple[str, CdxSeparator, str]] = []
    for profile in profiles:
        row: dict[str, Any] = {"ready": False, "runtime_verified": False}
        result["profiles"][profile] = row
        initial_blockers = len(result["blockers"])
        try:
            backend = CdxSeparator(config, quality=profile, device=device)
            config_hash = sha256(backend.config_path) if backend.config_path and backend.config_path.is_file() else None
            backend.ensure_ready()
            settings = backend.settings
            row.update({"config_sha256": config_hash, "revision": settings["revision"],
                        "runner": settings.get("runner", "upstream"),
                        "runtime_locked": bool(settings.get("runtime_lock"))})
            backends.append((profile, backend, config_hash))
            if settings.get("runner") != "safe-pytorch":
                block("safe_runner_required", "CDX-Konfiguration bewusst mit safe-pytorch neu registrieren.", scope=profile)
                continue
            interpreter = settings["python"]
            if interpreter not in runtimes:
                runtimes[interpreter] = probe_runtime(interpreter)
            runtime = runtimes[interpreter]
            # Do not export absolute local interpreter paths or the whole package list.
            row["runtime"] = {key: runtime.get(key) for key in (
                "fingerprint", "dependencies_ready", "missing_or_broken", "cuda_available", "restricted_checkpoint_loader")}
            if not runtime["dependencies_ready"]:
                block("runtime_dependencies", "Fehlende/defekte Imports: " + ", ".join(runtime["missing_or_broken"]), scope=profile)
            if not runtime.get("restricted_checkpoint_loader"):
                block("restricted_loader_required", "Runtime braucht den eingeschraenkten PyTorch-Checkpoint-Lader.", scope=profile)
            if device == "cuda" and not runtime.get("cuda_available"):
                block("cuda_unavailable", "CUDA ist im konfigurierten Modell-Python nicht verfuegbar.", scope=profile)
            if settings.get("runtime_lock") and settings["runtime_lock"] != runtime["fingerprint"]:
                block("runtime_lock_mismatch", "Runtime weicht vom registrierten Fingerprint ab; Konfiguration bewusst erneuern.", scope=profile)
            if not settings.get("runtime_lock"):
                result["warnings"].append({"scope": profile, "code": "runtime_not_locked",
                                           "detail": "Fuer reproduzierbare Vergleiche mit --verify-runtime registrieren."})
            row["ready"] = len(result["blockers"]) == initial_blockers
        except EXPECTED_ERRORS as exc:
            block("backend_unavailable", str(exc), scope=profile)

    # A long dependency probe must not validate files changed in the meantime.
    for profile, backend, before in backends:
        try:
            if sha256(backend.config_path) != before:
                raise BenchmarkError("CDX-Konfiguration wurde waehrend der Vorpruefung geaendert")
            backend.ensure_ready()
        except EXPECTED_ERRORS as exc:
            result["profiles"][profile]["ready"] = False
            block("backend_changed", str(exc), scope=profile)
    if corpus is not None:
        try:
            if sha256(corpus_path) != corpus_hash or load_corpus(corpus_path)["corpus_id"] != corpus["corpus_id"]:
                raise BenchmarkError("Corpus wurde waehrend der Vorpruefung geaendert")
        except EXPECTED_ERRORS as exc:
            block("corpus_changed", str(exc), scope="references")
    result["reference_ready"] = not any(row["scope"] == "references" for row in result["blockers"])
    result["ready_for_run"] = not result["blockers"]
    result["status"] = "ready_for_run" if result["ready_for_run"] else "blocked"
    result["limitations"] = ["Readiness is not model execution or acoustic acceptance.",
                              "Coverage is a minimum engineering policy, not proof of representative data.",
                              "No checkpoints are deserialized, packages installed or sources uploaded by preflight."]
    result["report_id"] = _digest(result)
    return result

#!/usr/bin/env python3
"""Build known-stem corpora, evaluate named outputs and compare paired runs.

Local media preparation and WAV scoring. No model/data downloads, source uploads,
guessed ground truth, role permutations, resampling or normalization in scoring.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

import numpy as np
from scipy.io import wavfile

from audio_decomposition import _float_samples, decompose
from cinematic_separation import CdxSeparator, sha256
from separation_metrics import Gates, METRIC_VERSION, ROLES, SILENCE_RMS, evaluate_arrays, rms


MAX_CASES = 20
MAX_SECONDS = 30
REFERENCE_KINDS = {"isolated-recordings", "synthetic-diagnostic"}


class BenchmarkError(RuntimeError):
    pass


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _json(path: Path) -> Any:
    if path.stat().st_size > 8 * 1024 * 1024:
        raise BenchmarkError("JSON-Datei ist zu gross")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    # Only write inside a fresh transaction, never into user-owned outputs.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


@contextmanager
def _bundle(destination: Path):
    destination = destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise BenchmarkError(f"Ausgabeverzeichnis existiert bereits: {destination}")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".separation-benchmark-", dir=destination.parent) as temporary:
        bundle = Path(temporary) / "bundle"
        bundle.mkdir()
        yield bundle
        if destination.exists() or destination.is_symlink():
            raise BenchmarkError("Benchmark-Ziel wurde waehrend des Laufs angelegt")
        os.rename(bundle, destination)


def _wav(path: Path) -> tuple[int, np.ndarray]:
    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise BenchmarkError(f"WAV fehlt oder ist groesser als 64 MiB: {path}")
    rate, raw = wavfile.read(path)
    audio = _float_samples(raw)
    if audio.ndim == 1:
        audio = audio[:, None]
    if (not 8_000 <= rate <= 96_000 or audio.ndim != 2 or audio.shape[1] not in (1, 2)
            or not rate <= len(audio) <= MAX_SECONDS * rate
            or not np.isfinite(audio).all() or np.max(np.abs(audio)) > 1e6):
        raise BenchmarkError("WAV braucht 1–30 s, 8–96 kHz, 1–2 Kanaele und endliche Samples")
    return int(rate), audio


def _entry(path: Path, root: Path) -> dict[str, str]:
    return {"path": str(path.relative_to(root)), "sha256": sha256(path)}


def _owned_file(root: Path, entry: dict) -> Path:
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        raise BenchmarkError("Ungueltiger Corpus-Dateieintrag")
    relative = Path(entry["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise BenchmarkError("Corpus-Pfade muessen innerhalb des Pakets liegen")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise BenchmarkError("Corpus-Symlink verweist nach ausserhalb")
    if sha256(path) != entry.get("sha256"):
        raise BenchmarkError(f"Corpus-Hash stimmt nicht: {relative}")
    return path


def build_corpus(spec_path: Path, destination: Path, *, preparation: dict | None = None) -> dict[str, Any]:
    spec_path = spec_path.expanduser().resolve()
    spec_hash = sha256(spec_path)
    spec = _json(spec_path)
    cases = spec.get("cases") if isinstance(spec, dict) else None
    if not isinstance(spec, dict) or spec.get("schema_version") != 1 or not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise BenchmarkError("Corpus-Spezifikation braucht schema_version 1 und 1–20 cases")
    seen = set()
    result = {"schema_version": 1, "kind": "nexpt-known-stem-corpus", "cases": []}
    if preparation is not None:
        # Import provenance is included in the corpus identity, not a loose sidecar.
        result["preparation"] = preparation
    originals = {}
    with _bundle(destination) as bundle:
        for case in cases:
            if not isinstance(case, dict):
                raise BenchmarkError("Case muss ein Objekt sein")
            identifier = case.get("id")
            if (not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identifier)
                    or identifier in seen):
                raise BenchmarkError("Case-IDs muessen eindeutig und dateisystemsicher sein")
            seen.add(identifier)
            if not isinstance(case.get("reference_kind"), str) or case["reference_kind"] not in REFERENCE_KINDS:
                raise BenchmarkError("reference_kind muss isolated-recordings oder synthetic-diagnostic sein")
            sources = case.get("stems")
            if not isinstance(sources, dict) or set(sources) != set(ROLES):
                raise BenchmarkError("Jeder Case braucht music/dialogue/sfx; null bedeutet bewusste Stille")
            gain = case.get("mix_gain", 1.0)
            if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not math.isfinite(gain) or not 0 < gain <= 1:
                raise BenchmarkError("mix_gain muss zwischen 0 (exklusiv) und 1 liegen")
            references, provenance = {}, {}
            sample_rate = shape = None
            for role, entry in sources.items():
                if entry is None:
                    provenance[role] = {"declared_absent": True}
                    continue
                if not isinstance(entry, dict) or any(
                        not isinstance(entry.get(key), str) or not entry[key].strip()
                        for key in ("path", "license", "attribution")):
                    raise BenchmarkError("Jede Quelle braucht path, license und attribution")
                path = (spec_path.parent / Path(entry["path"]).expanduser()).resolve()
                before = sha256(path)
                if path in originals and originals[path] != before:
                    raise BenchmarkError("Mehrfach verwendete Quelle wurde zwischen Cases geaendert")
                rate, audio = _wav(path)
                if shape is not None and (rate != sample_rate or audio.shape != shape):
                    raise BenchmarkError("Originalspuren muessen gleiche Laenge, Samplerate und Kanaele haben")
                sample_rate, shape = rate, audio.shape
                references[role] = (audio * gain).astype(np.float32)
                originals[path] = before
                provenance[role] = {"input_sha256": before, "license": entry["license"],
                                    "attribution": entry["attribution"], "declared_absent": False}
            if not references:
                raise BenchmarkError("Mindestens eine aktive Referenzspur ist erforderlich")
            for role in ROLES:
                references.setdefault(role, np.zeros(shape, dtype=np.float32))
            mixture = sum(x.astype(np.float64) for x in references.values()).astype(np.float32)
            if rms(mixture) <= SILENCE_RMS:
                raise BenchmarkError("Mix ist stumm oder durch Ausloeschung nicht aussagekraeftig")
            if max(float(np.max(np.abs(x))) for x in (mixture, *references.values())) > 1:
                raise BenchmarkError("Mix/Referenz ueber 0 dBFS; kleineren gemeinsamen mix_gain waehlen")
            case_dir = bundle / "cases" / identifier
            case_dir.mkdir(parents=True)
            wavfile.write(case_dir / "mix.wav", sample_rate, mixture)
            for role in ROLES:
                wavfile.write(case_dir / f"{role}.wav", sample_rate, references[role])
            result["cases"].append({"id": identifier, "reference_kind": case["reference_kind"],
                                     "mix_gain": gain, "sample_rate": sample_rate,
                                     "frames": len(mixture), "channels": shape[1],
                                     "mix": _entry(case_dir / "mix.wav", bundle),
                                     "stems": {role: _entry(case_dir / f"{role}.wav", bundle) for role in ROLES},
                                     "provenance": provenance})
        if sha256(spec_path) != spec_hash or any(sha256(p) != h for p, h in originals.items()):
            raise BenchmarkError("Spezifikation oder Originalspur wurde waehrend des Builds geaendert")
        result["corpus_id"] = _digest(result)
        _write_json(bundle / "corpus.json", result)
    return result


def _case_audio(root: Path, case: dict) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    rate, mixture = _wav(_owned_file(root, case["mix"]))
    if (rate != case["sample_rate"] or mixture.shape != (case["frames"], case["channels"])
            or set(case["stems"]) != set(ROLES)):
        raise BenchmarkError("Corpus-Metadaten stimmen nicht mit WAVs ueberein")
    references = {}
    for role in ROLES:
        stem_rate, audio = _wav(_owned_file(root, case["stems"][role]))
        if stem_rate != rate or audio.shape != mixture.shape:
            raise BenchmarkError("Referenzspuren sind nicht ausgerichtet")
        references[role] = audio
    if rms(mixture) <= SILENCE_RMS or rms(mixture - sum(references.values())) / rms(mixture) > 1e-6:
        raise BenchmarkError("Referenzspuren ergeben nicht den deklarierten Mix")
    return mixture, references


def load_corpus(path: Path) -> dict[str, Any]:
    corpus = _json(path)
    if not isinstance(corpus, dict):
        raise BenchmarkError("Ungueltiger Corpus")
    identity = {key: value for key, value in corpus.items() if key != "corpus_id"}
    if (corpus.get("schema_version") != 1 or corpus.get("kind") != "nexpt-known-stem-corpus"
            or corpus.get("corpus_id") != _digest(identity)):
        raise BenchmarkError("Corpus-Identitaet stimmt nicht")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise BenchmarkError("Corpus braucht 1–20 cases")
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise BenchmarkError("Corpus-Case muss ein Objekt sein")
        identifier = case.get("id")
        if (not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identifier)
                or identifier in seen or not isinstance(case.get("reference_kind"), str)
                or case["reference_kind"] not in REFERENCE_KINDS):
            raise BenchmarkError("Ungueltiger oder doppelter Corpus-Case")
        seen.add(identifier)
        _case_audio(path.parent, case)
    return corpus


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "report_id": _digest(payload)}


def _implementation_id() -> str:
    # Include WAV conversion and report/gate orchestration, not just the
    # numerical formulas. Re-evaluating stored stems is cheap after updates.
    return _digest({name: sha256(Path(__file__).with_name(name)) for name in (
        "separation_benchmark.py", "separation_metrics.py", "audio_decomposition.py")})


def _summarize(rows: list[dict]) -> dict[str, Any]:
    valid = [row for row in rows if row["status"] == "evaluated"]
    roles = {}
    for role in ROLES:
        metrics = [row["metrics"]["roles"][role] for row in valid]
        snr = [row["scores"]["snr_db"] for row in metrics if row["scores"] is not None]
        improvement = [row["si_sdr_improvement_db"] for row in metrics if row["si_sdr_improvement_db"] is not None]
        silence = [row["silence"]["maximum_estimate_rms"] for row in metrics
                   if row["silence"]["maximum_estimate_rms"] is not None]
        roles[role] = {"active_cases": sum(row["reference_active"] for row in metrics),
                       "silent_cases": sum(not row["reference_active"] for row in metrics),
                       "median_snr_db": float(np.median(snr)) if snr else None,
                       "median_si_sdr_improvement_db": float(np.median(improvement)) if improvement else None,
                       "median_worst_silent_window_rms": float(np.median(silence)) if silence else None}
    return {"total_cases": len(rows), "evaluated_cases": len(valid),
            "failed_cases": len(rows) - len(valid), "roles": roles,
            "numerical_gate_passed": len(valid) == len(rows) and all(
                row["metrics"]["numerical_gate_passed"] for row in valid)}


def _evaluate(corpus_path: Path, corpus: dict, estimates_dir: Path, gates: Gates,
              candidate: dict) -> dict[str, Any]:
    rows = []
    corpus_hash = sha256(corpus_path)
    metric_path = Path(__file__).with_name("separation_metrics.py")
    metric_hash = sha256(metric_path)
    implementation_id = _implementation_id()
    for case in corpus["cases"]:
        mixture, references = _case_audio(corpus_path.parent, case)
        row = {"id": case["id"], "reference_kind": case["reference_kind"]}
        try:
            estimates, artifacts = {}, {}
            for role in ROLES:
                path = estimates_dir / case["id"] / f"{role}.wav"
                before = sha256(path)
                rate, audio = _wav(path)
                if rate != case["sample_rate"] or audio.shape != mixture.shape:
                    raise BenchmarkError("Schaetzung ist nicht ausgerichtet; keine automatische Korrektur")
                estimates[role] = audio
                artifacts[role] = _entry(path, estimates_dir)
                if artifacts[role]["sha256"] != before:
                    raise BenchmarkError("Schaetzung waehrend des Lesens geaendert")
            metrics = evaluate_arrays(mixture, references, estimates, case["sample_rate"], gates)
            if any(sha256(estimates_dir / item["path"]) != item["sha256"] for item in artifacts.values()):
                raise BenchmarkError("Schaetzung waehrend der Bewertung geaendert")
            row.update(status="evaluated", metrics=metrics, estimates=artifacts)
        except (RuntimeError, OSError, ValueError, EOFError) as exc:
            row.update(status="failed", error=str(exc))
        rows.append(row)
    # A changed truth set invalidates the whole run, not only one case.
    if sha256(corpus_path) != corpus_hash or load_corpus(corpus_path)["corpus_id"] != corpus["corpus_id"]:
        raise BenchmarkError("Corpus wurde waehrend der Bewertung geaendert")
    if sha256(metric_path) != metric_hash or _implementation_id() != implementation_id:
        raise BenchmarkError("Metrik-Code wurde waehrend der Bewertung geaendert")
    return {"schema_version": 1, "kind": "nexpt-separation-benchmark",
            "metric_version": METRIC_VERSION,
            "metric_implementation_sha256": metric_hash,
            "benchmark_implementation_sha256": implementation_id,
            "corpus_id": corpus["corpus_id"], "candidate": candidate,
            "gate_profile": {"calibration": "provisional-engineering-v1", **asdict(gates)},
            "evaluation_policy": {"db_cap": 120, "alignment": "exact-samples",
                                   "auto_permutation": False, "auto_gain_or_filter": False,
                                   "aggregation": "macro-median per role; failures never dropped"},
            "cases": rows, "summary": _summarize(rows),
            "perceptual_quality_verified": False, "listening_review_required": True,
            "limitations": ["Reference labels and licenses are supplied by the corpus author, not independently verified.",
                            "Synthetic diagnostics do not establish performance on recorded music or speech.",
                            "The projection matrix is a linear diagnostic, not a perceptual leakage percentage."]}


def evaluate_corpus(corpus_path: Path, estimates_dir: Path, destination: Path, *,
                    name: str = "external-estimates", gates: Gates | None = None,
                    candidate_kind: str = "external-unverified") -> dict[str, Any]:
    gates = gates or Gates()
    gates.validate()
    corpus_path = corpus_path.expanduser().resolve()
    estimates_dir = estimates_dir.expanduser().resolve()
    corpus = load_corpus(corpus_path)
    with _bundle(destination) as bundle:
        report = _evaluate(corpus_path, corpus, estimates_dir, gates,
                           {"name": name, "kind": candidate_kind, "estimates_dir": str(estimates_dir)})
        report = _seal(report)
        _write_json(bundle / "report.json", report)
    return report


def run_cdx(corpus_path: Path, config: Path, destination: Path, *, quality: str = "standard",
            device: str = "cpu", timeout: float = 600, gates: Gates | None = None) -> dict[str, Any]:
    gates = gates or Gates()
    gates.validate()
    if not math.isfinite(timeout) or not 1 <= timeout <= 3600:
        raise BenchmarkError("Modell-Zeitlimit muss zwischen 1 und 3600 Sekunden liegen")
    corpus_path = corpus_path.expanduser().resolve()
    config = config.expanduser().resolve()
    corpus = load_corpus(corpus_path)
    if any(case["channels"] != 2 for case in corpus["cases"]):
        raise BenchmarkError("CDX-Benchmark braucht Stereo-Referenzen; kein stilles Downmixing")
    backend = CdxSeparator(config, quality=quality, device=device, timeout=timeout)
    backend.ensure_ready()
    config_hash = sha256(config)
    attempts = {}
    with _bundle(destination) as bundle:
        estimates_dir = bundle / "estimates"
        estimates_dir.mkdir()
        with tempfile.TemporaryDirectory(prefix=".cdx-cases-", dir=bundle) as work:
            for case in corpus["cases"]:
                try:
                    # A failed mixture gate must not suppress ground-truth
                    # measurements. Inference failures remain explicit rows.
                    decomposition = decompose(
                        _owned_file(corpus_path.parent, case["mix"]),
                        output_dir=Path(work) / case["id"], cdx_config=config,
                        sample_rate=case["sample_rate"], quality=quality, device=device,
                        strict=False, inference_timeout=timeout)
                    case_dir = estimates_dir / case["id"]
                    case_dir.mkdir()
                    for role in ROLES:
                        shutil.copyfile(decomposition["outputs"][role]["path"], case_dir / f"{role}.wav")
                    attempts[case["id"]] = {"status": "completed", "processing": decomposition["processing"]}
                except (RuntimeError, OSError, ValueError) as exc:
                    attempts[case["id"]] = {"status": "failed", "error": str(exc)}
        report = _evaluate(corpus_path, corpus, estimates_dir, gates,
                           {"name": f"cdx-{quality}-{device}", "kind": "configured-cdx-run",
                            "config_sha256": config_hash, "quality": quality, "device": device,
                            "estimates_dir": "estimates", "attempts": attempts})
        for row in report["cases"]:
            if attempts[row["id"]]["status"] == "failed":
                identifier, reference_kind = row["id"], row["reference_kind"]
                row.clear()
                row.update(id=identifier, reference_kind=reference_kind,
                           status="failed", error=attempts[identifier]["error"])
        report["summary"] = _summarize(report["cases"])
        if sha256(config) != config_hash:
            raise BenchmarkError("CDX-Konfiguration wurde waehrend des Benchmarks geaendert")
        backend.ensure_ready()
        report = _seal(report)
        _write_json(bundle / "report.json", report)
    return report


def compare_reports(paths: list[Path]) -> dict[str, Any]:
    if len(paths) != 2:
        raise BenchmarkError("Vergleich braucht genau zwei Berichte")
    reports = [_json(path) for path in paths]
    for report in reports:
        if (not isinstance(report, dict) or report.get("kind") != "nexpt-separation-benchmark"
                or report.get("schema_version") != 1
                or report.get("report_id") != _digest({k: v for k, v in report.items() if k != "report_id"})):
            raise BenchmarkError("Ungueltiger oder veraenderter Benchmark-Bericht")
    left, right = reports
    for field in ("corpus_id", "metric_version", "metric_implementation_sha256",
                  "benchmark_implementation_sha256", "gate_profile", "evaluation_policy"):
        if field not in left or field not in right or left[field] != right[field]:
            raise BenchmarkError(f"Nicht vergleichbar: {field} unterscheidet sich")
    indexes = [{case["id"]: case for case in report["cases"]} for report in reports]
    if (not indexes[0] or set(indexes[0]) != set(indexes[1])
            or any(len(indexes[i]) != len(reports[i]["cases"]) for i in (0, 1))):
        raise BenchmarkError("Case-Abdeckung unterscheidet sich oder enthaelt Duplikate")
    pairs, incomplete = [], []
    for identifier in sorted(indexes[0]):
        a, b = indexes[0][identifier], indexes[1][identifier]
        if a["status"] != "evaluated" or b["status"] != "evaluated":
            incomplete.append(identifier)
            continue
        differences = {}
        for role in ROLES:
            x, y = a["metrics"]["roles"][role], b["metrics"]["roles"][role]
            differences[role] = {"snr_db_delta": y["scores"]["snr_db"] - x["scores"]["snr_db"]
                                  if x["scores"] is not None and y["scores"] is not None else None,
                                 "si_sdr_db_delta": y["scores"]["si_sdr_db"] - x["scores"]["si_sdr_db"]
                                  if x["scores"] and y["scores"] and x["scores"]["si_sdr_db"] is not None
                                  and y["scores"]["si_sdr_db"] is not None else None,
                                 "silent_window_rms_delta": y["silence"]["maximum_estimate_rms"] - x["silence"]["maximum_estimate_rms"]
                                  if x["silence"]["maximum_estimate_rms"] is not None
                                  and y["silence"]["maximum_estimate_rms"] is not None else None,
                                 "left_gate_passed": x["numerical_gate_passed"],
                                 "right_gate_passed": y["numerical_gate_passed"]}
        pairs.append({"id": identifier, "right_minus_left": differences})
    return {"schema_version": 1, "kind": "nexpt-paired-benchmark-comparison",
            "corpus_id": left["corpus_id"], "left": left["candidate"]["name"],
            "right": right["candidate"]["name"], "report_ids": [x["report_id"] for x in reports],
            "complete": not incomplete, "incomplete_cases": incomplete, "pairs": pairs,
            "overall_winner": None, "perceptual_quality_verified": False,
            "note": "Paired measurements only; no model ranking from silent, failed or missing cases."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("spec", type=Path)
    build.add_argument("--output-dir", type=Path, required=True)
    prepare = commands.add_parser("prepare", help="compose declared isolated local media excerpts")
    prepare.add_argument("spec", type=Path)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--decode-timeout", type=float, default=60)
    precheck = commands.add_parser("preflight", help="inspect reference coverage and model dependencies without inference")
    precheck.add_argument("corpus", type=Path)
    precheck.add_argument("--cdx-config", type=Path)
    precheck.add_argument("--quality", choices=("standard", "high", "both"), default="both")
    precheck.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    precheck.add_argument("--output-dir", type=Path)
    check = commands.add_parser("evaluate")
    run = commands.add_parser("run-cdx")
    for command in (check, run):
        command.add_argument("corpus", type=Path)
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--gate-config", type=Path)
        command.add_argument("--strict", action="store_true")
    check.add_argument("--estimates-dir", type=Path, required=True)
    check.add_argument("--name", default="external-estimates")
    run.add_argument("--cdx-config", type=Path, required=True)
    run.add_argument("--quality", choices=("standard", "high"), default="standard")
    run.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    run.add_argument("--timeout", type=float, default=600)
    compare = commands.add_parser("compare")
    compare.add_argument("reports", nargs=2, type=Path)
    compare.add_argument("--output-dir", type=Path, required=True)
    diagnostic = commands.add_parser("self-test")
    diagnostic.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    code = 0
    try:
        if args.command == "build":
            result = build_corpus(args.spec, args.output_dir)
        elif args.command == "prepare":
            from separation_reference import prepare_corpus
            result = prepare_corpus(args.spec, args.output_dir, decode_timeout=args.decode_timeout)
        elif args.command == "preflight":
            from separation_preflight import preflight
            profiles = ("standard", "high") if args.quality == "both" else (args.quality,)
            result = preflight(args.corpus, config=args.cdx_config, profiles=profiles, device=args.device)
            if args.output_dir:
                with _bundle(args.output_dir) as bundle:
                    _write_json(bundle / "preflight.json", result)
            code = 0 if result["ready_for_run"] else 2
        elif args.command == "self-test":
            from separation_benchmark_fixtures import self_test
            result = self_test(args.output_dir)
            code = 0 if result["self_test_passed"] else 2
        elif args.command == "compare":
            with _bundle(args.output_dir) as bundle:
                result = compare_reports(args.reports)
                _write_json(bundle / "comparison.json", result)
            code = 0 if result["complete"] else 2
        else:
            gates = Gates(**_json(args.gate_config)) if args.gate_config else Gates()
            if args.command == "run-cdx":
                result = run_cdx(args.corpus, args.cdx_config, args.output_dir, quality=args.quality,
                                 device=args.device, timeout=args.timeout, gates=gates)
            else:
                result = evaluate_corpus(args.corpus, args.estimates_dir, args.output_dir,
                                         name=args.name, gates=gates)
            if result["summary"]["failed_cases"] or (args.strict and not result["summary"]["numerical_gate_passed"]):
                code = 2
    except (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError, EOFError) as exc:
        result, code = {"status": "failed", "error": str(exc)}, 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(code)


if __name__ == "__main__":
    main()

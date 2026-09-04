"""Explicit preflight/CDX doubles for experiment tests; no real model evidence."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

from cdx_fixtures import make_cdx_fixture
from cinematic_separation import sha256
from separation_benchmark import _bundle, _digest, _evaluate, _seal, _write_json, load_corpus
from separation_benchmark_fixtures import control_estimates, diagnostic_corpus


def make_experiment_fixture(root: Path, *, mode: str = "valid", case_count: int = 3) -> tuple[Path, Path]:
    corpus_dir = root / "corpus"
    corpus = diagnostic_corpus(corpus_dir)
    corpus["cases"] = corpus["cases"][:case_count]
    # Testing author-declaration contracts only. The underlying signals remain
    # generated tones/noise, NOT recorded speech or acoustic quality evidence.
    for case in corpus["cases"]:
        case["reference_kind"] = "isolated-recordings"
    corpus["corpus_id"] = _digest({k: v for k, v in corpus.items() if k != "corpus_id"})
    (corpus_dir / "corpus.json").write_text(json.dumps(corpus))
    _, config = make_cdx_fixture(root, mode)
    return corpus_dir / "corpus.json", config


def ready_preflight(corpus_path, *, config, **kwargs):
    return {"ready_for_run": True, "corpus_id": load_corpus(corpus_path)["corpus_id"],
            "profiles": {quality: {"config_sha256": sha256(config), "runtime_locked": True,
                          "runtime": {"fingerprint": "a" * 64}} for quality in ("standard", "high")},
            "model_inference_executed": False, "fixture_only": True}


def fake_run(corpus_path, config, destination, *, quality, device, gates, timeout,
             control: str | None = None, missing_case: str | None = None):
    corpus = load_corpus(corpus_path)
    control = control or ("swapped" if quality == "standard" else "oracle")
    with _bundle(destination) as bundle:
        estimates = bundle / "estimates"
        control_estimates(corpus_path.parent, corpus, estimates, control)
        if missing_case:
            (estimates / missing_case / "sfx.wav").unlink()
        report = _seal(_evaluate(corpus_path, corpus, estimates, gates, {
            "name": f"cdx-{quality}-{device}", "kind": "configured-cdx-run", "quality": quality,
            "device": device, "config_sha256": sha256(config), "estimates_dir": "estimates",
            "fixture_only": True}))
        if missing_case:
            shutil.rmtree(estimates / missing_case)
        _write_json(bundle / "report.json", report)
    return report


if __name__ == "__main__":
    # Exercise the actual argument parser, filesystem transactions and FFmpeg
    # across a process boundary; the runtime readiness and CDX CLI are doubles.
    import separation_benchmark
    import separation_experiment

    with mock.patch.object(separation_experiment, "preflight", side_effect=ready_preflight):
        separation_benchmark.main()

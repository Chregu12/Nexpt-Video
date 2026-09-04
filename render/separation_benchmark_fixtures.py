"""Deterministic measurement controls, explicitly NOT realistic training data."""
from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

import numpy as np
from scipy.io import wavfile

from separation_benchmark import (
    _bundle, _case_audio, _evaluate, _seal, _write_json, build_corpus,
)
from separation_metrics import Gates, ROLES


CONTROLS = ("oracle", "swapped", "equal-split", "silence-leak", "muted-music")


def diagnostic_corpus(destination: Path) -> dict[str, Any]:
    """Three fixed 2-second cases: overlap, absent dialogue, music alone."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".benchmark-sources-", dir=destination.parent) as temporary:
        root = Path(temporary)
        rate = 44_100
        times = np.arange(2 * rate) / rate
        music = .08 * np.sin(2 * np.pi * 277 * times) + .02 * np.sin(2 * np.pi * 554 * times)
        # A gated tone occupying the dialogue SLOT, not synthesized speech.
        envelope = np.maximum(0, np.sin(np.pi * np.clip((times - .5), 0, 1))) ** 2
        dialogue = .08 * envelope * np.sin(2 * np.pi * 937 * times)
        random = np.random.Generator(np.random.PCG64(731))
        sfx = random.normal(0, .035, len(times)) * (
            np.exp(-np.maximum(times - .25, 0) * 40) * (times >= .25)
            + np.exp(-np.maximum(times - 1.5, 0) * 40) * (times >= 1.5))
        sources = {}
        for role, values in zip(ROLES, (music, dialogue, sfx)):
            stereo = np.column_stack((values, np.roll(values, 3) * .8)).astype(np.float32)
            wavfile.write(root / f"{role}.wav", rate, stereo)
            sources[role] = {"path": f"{role}.wav", "license": "generated diagnostic signals",
                             "attribution": "NEXPT deterministic sine/noise controls, PCG64 seed 731"}
        cases = []
        for identifier, absent in (("overlap", ()), ("no-dialogue", ("dialogue",)),
                                   ("music-only", ("dialogue", "sfx"))):
            cases.append({"id": identifier, "reference_kind": "synthetic-diagnostic",
                          "stems": {role: None if role in absent else sources[role] for role in ROLES}})
        _write_json(root / "spec.json", {"schema_version": 1, "cases": cases})
        return build_corpus(root / "spec.json", destination)


def control_estimates(corpus_root: Path, corpus: dict, destination: Path, control: str) -> None:
    if control not in CONTROLS:
        raise ValueError("Unknown diagnostic control")
    destination.mkdir(parents=True, exist_ok=False)
    for case in corpus["cases"]:
        mix, truth = _case_audio(corpus_root, case)
        estimated = {role: truth[role].copy() for role in ROLES}
        if control == "swapped":
            estimated["music"], estimated["dialogue"] = truth["dialogue"], truth["music"]
        elif control == "equal-split":
            estimated = {role: mix / 3 for role in ROLES}
        elif control == "silence-leak":
            estimated["music"] -= truth["music"] * .1
            estimated["dialogue"] += truth["music"] * .1
        elif control == "muted-music":
            estimated["music"] *= 0
        case_dir = destination / case["id"]
        case_dir.mkdir()
        for role in ROLES:
            wavfile.write(case_dir / f"{role}.wav", case["sample_rate"], estimated[role].astype(np.float32))


def self_test(destination: Path) -> dict[str, Any]:
    with _bundle(destination) as bundle:
        corpus_dir = bundle / "corpus"
        corpus = diagnostic_corpus(corpus_dir)
        results = {}
        for control in CONTROLS:
            control_dir = bundle / "controls" / control
            control_dir.mkdir(parents=True)
            estimates = control_dir / "estimates"
            control_estimates(corpus_dir, corpus, estimates, control)
            report = _seal(_evaluate(corpus_dir / "corpus.json", corpus, estimates, Gates(),
                                     {"name": control, "kind": "diagnostic-control", "estimates_dir": "estimates"}))
            _write_json(control_dir / "report.json", report)
            expected = control == "oracle"
            observed = report["summary"]["numerical_gate_passed"]
            results[control] = {"expected_gate_passed": expected, "observed_gate_passed": observed,
                                "matched_expectation": expected == observed and report["summary"]["failed_cases"] == 0,
                                "all_sums_passed": all(row["metrics"]["mix_consistency"]["passed"]
                                                       for row in report["cases"] if row["status"] == "evaluated"),
                                "report": f"controls/{control}/report.json"}
        result = {"schema_version": 1, "kind": "nexpt-benchmark-self-test", "corpus_id": corpus["corpus_id"],
                  "self_test_passed": all(row["matched_expectation"] for row in results.values()),
                  "controls": results, "model_inference_executed": False,
                  "perceptual_quality_verified": False,
                  "note": "Measures scorer correctness only. Dialogue fixture is a gated tone, not speech."}
        _write_json(bundle / "self-test.json", result)
    return result

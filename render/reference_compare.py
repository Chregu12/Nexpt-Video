#!/usr/bin/env python3
"""Ein neues Rendering gegen die Eigenschaften eines Referenzprofils messen.

Der Score bewertet Tempo, Frequenzbalance, Rollen-Dichte, Schrittmuster,
Vier-Takt-Wiederholung, Stereobreite und Dynamik. Er bleibt eine technische
Diagnose und ersetzt keinen Hoertest.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

from audio_common import OUT, write_manifest
from reference_analyzer import analyze_reference
from reference_rhythm import ROLES, legacy_rhythm_model
from reference_sound import load_profile


def _rhythm_similarity(reference: dict, candidate: dict) -> tuple[dict, dict]:
    ref = reference.get("rhythm_model") or legacy_rhythm_model(reference)
    new = candidate.get("rhythm_model") or legacy_rhythm_model(candidate)
    density_scores = []
    pattern_scores = []
    density_differences = {}
    pattern_differences = {}
    weights = []
    for role in ROLES:
        ref_row = ref["roles"][role]
        new_row = new["roles"][role]
        ref_density = max(.03, float(ref_row.get("events_per_bar", 0.0)))
        new_density = max(.03, float(new_row.get("events_per_bar", 0.0)))
        density_ratio = new_density/ref_density
        density_scores.append(100*math.exp(-abs(math.log(density_ratio))/.68))
        density_differences[role] = round(density_ratio, 4)

        ref_steps = np.asarray(ref_row.get("step_probability", [0]*16), dtype=float)
        new_steps = np.asarray(new_row.get("step_probability", [0]*16), dtype=float)
        ref_steps /= max(1e-12, float(ref_steps.sum()))
        new_steps /= max(1e-12, float(new_steps.sum()))
        variation_distance = float(np.sum(np.abs(ref_steps-new_steps))*.5)
        pattern_scores.append(100*math.exp(-variation_distance/.42))
        pattern_differences[role] = round(variation_distance, 4)
        weights.append(ref_density)

    weights_array = np.asarray(weights, dtype=float)
    weights_array /= weights_array.sum()
    role_density = float(np.sum(np.asarray(density_scores)*weights_array))
    step_pattern = float(np.sum(np.asarray(pattern_scores)*weights_array))
    repeat_delta = abs(float(ref.get("four_bar_repeat_jaccard", 0.0))-
                       float(new.get("four_bar_repeat_jaccard", 0.0)))
    repeat_score = 100*math.exp(-repeat_delta/.24)
    return ({
        "role_density": role_density,
        "step_pattern": step_pattern,
        "four_bar_repeat": repeat_score,
    }, {
        "role_density_ratio": density_differences,
        "step_pattern_total_variation": pattern_differences,
        "four_bar_repeat_jaccard": {
            "reference": round(float(ref.get("four_bar_repeat_jaccard", 0.0)), 4),
            "candidate": round(float(new.get("four_bar_repeat_jaccard", 0.0)), 4),
            "absolute_difference": round(repeat_delta, 4),
        },
    })


def similarity_report(reference: dict, candidate: dict) -> dict:
    ref_mix = reference["mix"]
    new_mix = candidate["mix"]
    band_names = ("sub", "bass", "low_mid", "mid", "presence", "air")
    ref_bands = np.asarray([ref_mix["bands"][name] for name in band_names], dtype=float)
    new_bands = np.asarray([new_mix["bands"][name] for name in band_names], dtype=float)
    band_l1 = float(np.sum(np.abs(ref_bands-new_bands)))

    tempo_delta = abs(float(reference["tempo"]["bpm"])-float(candidate["tempo"]["bpm"]))
    width_delta = abs(float(ref_mix.get("side_mid_db", -15))-
                      float(new_mix.get("side_mid_db", -15)))
    crest_delta = abs(float(ref_mix.get("crest_db", 18))-
                      float(new_mix.get("crest_db", 18)))
    ref_lra = ref_mix.get("loudness_range_lu")
    new_lra = new_mix.get("loudness_range_lu")
    lra_delta = abs(float(ref_lra)-float(new_lra)) if ref_lra is not None and new_lra is not None else None
    ref_density = max(.01, float(reference["generation_targets"].get("events_per_bar", 1)))
    new_density = max(.01, float(candidate["generation_targets"].get("events_per_bar", 1)))
    density_ratio = new_density/ref_density
    rhythm_scores, rhythm_differences = _rhythm_similarity(reference, candidate)

    scores = {
        "tempo": 100*math.exp(-tempo_delta/1.5),
        "frequency_balance": 100*math.exp(-band_l1/.55),
        "stereo_width": 100*math.exp(-width_delta/5.0),
        "crest_factor": 100*math.exp(-crest_delta/6.0),
        "event_density": 100*math.exp(-abs(math.log(density_ratio))/.75),
        **rhythm_scores,
    }
    if lra_delta is not None:
        scores["section_dynamics"] = 100*math.exp(-lra_delta/5.0)
    weights = {"tempo": .07, "frequency_balance": .18, "stereo_width": .07,
               "crest_factor": .08, "event_density": .07, "section_dynamics": .08,
               "role_density": .15, "step_pattern": .23, "four_bar_repeat": .07}
    used = {name: weight for name, weight in weights.items() if name in scores}
    overall = sum(scores[name]*weight for name, weight in used.items())/sum(used.values())
    return {
        "purpose": ("Technische Struktur- und Klangprofil-Aehnlichkeit. Kein Ersatz fuer "
                    "subjektive Klangqualitaet und keine Aussage ueber Melodiegleichheit."),
        "overall_score_0_100": round(overall, 1),
        "scores_0_100": {name: round(value, 1) for name, value in scores.items()},
        "differences": {
            "tempo_bpm": round(tempo_delta, 4),
            "band_distribution_l1": round(band_l1, 5),
            "side_mid_db": round(width_delta, 3),
            "crest_db": round(crest_delta, 3),
            "loudness_range_lu": round(lra_delta, 3) if lra_delta is not None else None,
            "event_density_ratio": round(density_ratio, 4),
            **rhythm_differences,
        },
        "bands": {
            name: {"reference": round(float(ref_bands[index]), 5),
                   "candidate": round(float(new_bands[index]), 5)}
            for index, name in enumerate(band_names)
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="neu erzeugte WAV/M4A/MP3")
    parser.add_argument("--profile", type=Path,
                        default=OUT/"analysis"/"reference-profile.json")
    parser.add_argument("--output", type=Path,
                        default=OUT/"analysis"/"reference-match.json")
    parser.add_argument("--bpm", type=float, help="Tempo des Kandidaten")
    parser.add_argument("--downbeat", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reference = load_profile(args.profile)
    bpm = args.bpm or float(reference["tempo"]["bpm"])
    candidate = analyze_reference(args.candidate, bpm_hint=bpm,
                                  downbeat_hint=args.downbeat,
                                  include_events=False, ebu=True)
    report = similarity_report(reference, candidate)
    report["reference_profile"] = str(args.profile)
    report["candidate"] = str(args.candidate)
    write_manifest(args.output, report)
    print(f"{args.output} · Profil-Aehnlichkeit {report['overall_score_0_100']:.1f}/100")
    for name, value in report["scores_0_100"].items():
        print(f"  {name:<20}{value:5.1f}")


if __name__ == "__main__":
    main()

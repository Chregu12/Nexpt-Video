"""Deterministic CDX CLI stand-in: tests the contract, never model accuracy."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap

from cinematic_separation import CDX_CHECKPOINTS, sha256


def make_cdx_fixture(root: Path, mode: str = "valid") -> tuple[Path, Path]:
    repo = root / "CDX checkout with spaces"
    repo.mkdir()
    (repo / ".gitignore").write_text("models/\n", encoding="utf-8")
    script = textwrap.dedent(f"""\
        import argparse
        from pathlib import Path
        import numpy as np
        from scipy.io import wavfile
        parser = argparse.ArgumentParser()
        parser.add_argument('--input_audio', nargs='+', required=True)
        parser.add_argument('--output_folder', type=Path, required=True)
        parser.add_argument('--cpu', action='store_true')
        parser.add_argument('--high_quality', action='store_true')
        args = parser.parse_args()
        mode = {mode!r}
        if mode == 'fail':
            raise SystemExit('fixture inference failed')
        source = Path(args.input_audio[0])
        rate, audio = wavfile.read(source)
        args.output_folder.mkdir(parents=True, exist_ok=True)
        for role, gain in [('music', .5), ('dialog', .3), ('effect', .2)]:
            if mode == 'missing' and role == 'effect':
                continue
            stem = audio.astype(np.float32) * (gain if mode != 'residual' else .01)
            if mode == 'short' and role == 'effect':
                stem = stem[:len(stem)//2]
            if mode == 'nan' and role == 'effect':
                stem[0] = np.nan
            wavfile.write(args.output_folder / (source.stem + '_' + role + '.wav'), rate, stem)
        """)
    (repo / "inference.py").write_text(script, encoding="utf-8")
    for args in (("init", "-q"), ("add", "inference.py", ".gitignore"),
                 ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                  "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    (repo / "models").mkdir()
    for name in CDX_CHECKPOINTS:
        (repo / "models" / name).write_bytes(b"fixture, not an actual model")
    config = root / "cdx.json"
    config.write_text(json.dumps({
        "schema_version": 1, "repository": str(repo), "python": sys.executable,
        "revision": revision, "checkpoint_license": "test-fixture-only",
        "checkpoint_sha256": {name: sha256(repo / "models" / name) for name in CDX_CHECKPOINTS},
    }), encoding="utf-8")
    return repo, config

#!/usr/bin/env python3
"""Run the pinned CDX entry point with PyTorch's restricted unpickler.

No automatic allowlisting based on checkpoint content, and never
weights_only=False. Only the explicitly listed, reviewed Demucs classes may
be reconstructed. This is defense in depth, not a sandbox for untrusted code.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import importlib
import os
from pathlib import Path
import runpy
import sys


ALLOWED_MODEL_CLASSES = (
    ("demucs.htdemucs", "HTDemucs"),
)


def _reject_download(*args, **kwargs):
    raise RuntimeError("Automatischer CDX-Modelldownload ist deaktiviert; Gewichte lokal bereitstellen")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    args, forwarded = parser.parse_known_args()
    repo = args.repository.expanduser().resolve()
    if not (repo / "inference.py").is_file():
        raise SystemExit("CDX inference.py fehlt")
    if os.environ.get("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "").lower() in {"1", "y", "yes", "true"}:
        raise SystemExit("Unsichere TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD-Konfiguration abgelehnt")
    # Also protects code paths that explicitly request unrestricted loading.
    os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "1"
    import torch

    if not hasattr(torch.serialization, "get_unsafe_globals_in_checkpoint"):
        raise SystemExit("Safe CDX runner braucht PyTorch >= 2.6 mit eingeschraenktem Loader")
    # The pinned entry point uses this helper if a file disappears between
    # preflight and load. A local race must not trigger a network download.
    torch.hub.download_url_to_file = _reject_download
    sys.path.insert(0, str(repo))
    classes = [getattr(importlib.import_module(module), name)
               for module, name in ALLOWED_MODEL_CLASSES]
    # The released standard checkpoint stores model segment lengths as the
    # stdlib's rational-number value type, not as an executable callback.
    classes.append(Fraction)
    allowed_names = {f"{cls.__module__}.{cls.__name__}" for cls in classes}
    needed = ["97d170e1-dbb4db15.th"]
    if "--high_quality" in forwarded:
        needed += ["97d170e1-a778de4a.th", "97d170e1-e41a5468.th"]
    for name in needed:
        path = repo / "models" / name
        if not path.is_file():
            raise SystemExit(f"Checkpoint fehlt; kein automatischer Download: {name}")
        unknown = set(torch.serialization.get_unsafe_globals_in_checkpoint(path)) - allowed_names
        if unknown:
            raise SystemExit("Nicht freigegebene Checkpoint-Klassen: " + ", ".join(sorted(unknown)))
    sys.argv = [str(repo / "inference.py"), *forwarded]
    with torch.serialization.safe_globals(classes):
        runpy.run_path(str(repo / "inference.py"), run_name="__main__")


if __name__ == "__main__":
    main()

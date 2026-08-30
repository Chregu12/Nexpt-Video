"""Shared test configuration.

Puts the repository root on sys.path so the package and the two top-level
modules (garageband_mcp, garageband_cli) import without installation, and
exposes the repo root to tests that read source files directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT

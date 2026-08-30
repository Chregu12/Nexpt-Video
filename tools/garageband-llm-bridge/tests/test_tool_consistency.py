"""Guard against drift between the MCP tool surface and its documentation.

The project keeps three parallel lists in sync by hand:
  * the MCP ``TOOLS`` advertisement (``_tool("name", ...)``),
  * the MCP ``_call_tool`` dispatch table (``"name": lambda``),
  * the ``garageband_*`` tools listed in README.md.

If any of them drift apart an MCP client will advertise a tool it cannot
run, or run one it never advertised. These tests fail loudly on that.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture(scope="module")
def mcp_source(repo_root):
    return (repo_root / "garageband_mcp.py").read_text(encoding="utf-8")


def _declared_tools(src: str) -> list[str]:
    return re.findall(r'_tool\(\s*"([^"]+)"', src)


def _dispatched_tools(src: str) -> list[str]:
    return re.findall(r'"(garageband_[a-z_]+)":\s*lambda', src)


def test_no_duplicate_tool_declarations(mcp_source):
    declared = _declared_tools(mcp_source)
    dupes = sorted({n for n in declared if declared.count(n) > 1})
    assert dupes == [], f"duplicate tool declarations: {dupes}"


def test_declared_tools_match_dispatch(mcp_source):
    declared = set(_declared_tools(mcp_source))
    dispatched = set(_dispatched_tools(mcp_source))
    assert declared == dispatched, {
        "advertised_but_not_dispatched": sorted(declared - dispatched),
        "dispatched_but_not_advertised": sorted(dispatched - declared),
    }


def test_readme_lists_every_tool(mcp_source, repo_root):
    declared = set(_declared_tools(mcp_source))
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"`(garageband_[a-z_]+)`", readme))
    missing = sorted(declared - documented)
    phantom = sorted(documented - declared)
    assert not missing, f"tools missing from README: {missing}"
    assert not phantom, f"README names tools that do not exist: {phantom}"

"""Tests for the machine-readable feature map used by LLM clients."""

from __future__ import annotations

from garageband_bridge import core


def test_capabilities_include_agent_decision_guide():
    data = core.capabilities(include_live=False)

    guide = data["agent_decision_guide"]
    assert len(guide) >= 4
    assert any("guitar tab" in entry["when"] for entry in guide)
    assert any("visible control" in entry["when"] for entry in guide)

    all_preferred_tools = "\n".join(
        item
        for entry in guide
        for item in entry.get("prefer", [])
    )
    assert "garageband_make_from_tab" in all_preferred_tools
    assert "garageband_annotated_screenshot" not in all_preferred_tools


def test_capabilities_keep_coordinates_as_fallback():
    data = core.capabilities(include_live=False)
    visible_control = next(
        entry for entry in data["agent_decision_guide"]
        if "visible control" in entry["when"]
    )

    fallback = "\n".join(visible_control["fallback"])
    assert "garageband_annotated_screenshot" in fallback
    assert "garageband_window_click" in fallback

"""Tests for the run_plan executor using only GarageBand-free actions."""

from __future__ import annotations

from garageband_bridge import core


SIMPLE_TAB = """e|--0--2--3--|
B|--1--3--0--|
G|--0--2--0--|
D|--2--0--0--|
A|--3-----2--|
E|--------3--|"""


def test_deterministic_plan_succeeds(tmp_path):
    midi = tmp_path / "plan.mid"
    plan = {
        "name": "tab-then-inspect",
        "steps": [
            {"action": "tab_to_midi", "args": {"tab": SIMPLE_TAB, "output": str(midi)}},
            {"action": "midi_info", "args": {"path": str(midi)}},
            {"action": "wait", "args": {"seconds": 0}},
        ],
    }
    result = core.run_plan(plan)
    assert result["ok"] is True
    assert result["steps_completed"] == 3
    actions = [r["action"] for r in result["results"]]
    assert actions == ["tab_to_midi", "midi_info", "wait"]
    assert all(r["ok"] for r in result["results"])
    # The midi_info step should report the same note count the writer produced.
    assert result["results"][1]["data"]["note_on_count"] == 15


def test_plan_tab_to_midi_accepts_capo(tmp_path):
    midi = tmp_path / "capo.mid"
    plan = {
        "steps": [
            {"action": "tab_to_midi", "args": {"tab": SIMPLE_TAB, "output": str(midi), "capo": 2}},
        ],
    }

    result = core.run_plan(plan)

    assert result["ok"] is True
    assert result["results"][0]["data"]["capo"] == 2
    assert result["results"][0]["data"]["preview"][0]["midi"] == 50


def test_plan_tab_to_midi_accepts_tuning(tmp_path):
    midi = tmp_path / "tuning.mid"
    plan = {
        "steps": [
            {
                "action": "tab_to_midi",
                "args": {
                    "tab": "e|-0-|\nB|-0-|\nG|-0-|\nD|-0-|\nA|-0-|\nE|-0-|",
                    "output": str(midi),
                    "tuning": "drop d",
                },
            },
        ],
    }

    result = core.run_plan(plan)

    assert result["ok"] is True
    assert result["results"][0]["data"]["tuning"] == "drop d"
    assert result["results"][0]["data"]["string_pitches"]["E"] == 38


def test_plan_tab_to_midi_detects_bpm(tmp_path):
    midi = tmp_path / "tempo.mid"
    plan = {
        "steps": [
            {"action": "tab_to_midi", "args": {"tab": "BPM 144\n" + SIMPLE_TAB, "output": str(midi)}},
            {"action": "midi_info", "args": {"path": str(midi)}},
        ],
    }

    result = core.run_plan(plan)

    assert result["ok"] is True
    assert result["results"][0]["data"]["bpm"] == 144
    assert result["results"][1]["data"]["tempo_changes"][0]["bpm"] == 144.0


def test_unknown_action_fails_cleanly():
    result = core.run_plan(
        {"name": "bad", "steps": [{"action": "definitely_not_real"}]},
        stop_on_error=True,
    )
    assert result["ok"] is False
    step = result["results"][0]
    assert step["ok"] is False
    assert "Unknown plan action" in step["error"]
    assert step["type"] == "GarageBandError"


def test_stop_on_error_halts_remaining_steps(tmp_path):
    midi = tmp_path / "after.mid"
    plan = {
        "name": "halts",
        "steps": [
            {"action": "definitely_not_real"},
            {"action": "tab_to_midi", "args": {"tab": SIMPLE_TAB, "output": str(midi)}},
        ],
    }
    result = core.run_plan(plan, stop_on_error=True)
    assert result["ok"] is False
    # The second step must not have run, so its output file should not exist.
    assert not midi.exists()


def test_continue_on_error_runs_all_steps(tmp_path):
    midi = tmp_path / "continue.mid"
    plan = {
        "name": "continues",
        "stop_on_error": False,
        "steps": [
            {"action": "definitely_not_real"},
            {"action": "tab_to_midi", "args": {"tab": SIMPLE_TAB, "output": str(midi)}},
        ],
    }
    result = core.run_plan(plan)
    assert result["ok"] is False  # overall fails because one step failed
    assert result["steps_completed"] == 2
    assert midi.exists()  # the good step still ran

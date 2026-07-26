"""Golden XML fixture presence checks.

These tests skip until company-exported XML files are placed under fixtures/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cueplayer.exporters.xml_inspect import load_xml_root, require_tags, xml_tag_local

ROOT = Path(__file__).resolve().parents[2]
MA2 = ROOT / "fixtures" / "ma2"
MA3 = ROOT / "fixtures" / "ma3"

REQUIRED_FILES = ("main_sequence.xml", "button_sequence.xml", "timecode.xml")


def _missing(folder: Path) -> list[str]:
    return [name for name in REQUIRED_FILES if not (folder / name).is_file()]


@pytest.mark.parametrize("folder", [MA2, MA3], ids=["ma2", "ma3"])
def test_golden_xml_files_present(folder: Path) -> None:
    missing = _missing(folder)
    if missing:
        pytest.skip(f"Golden XML not collected yet in {folder}: missing {', '.join(missing)}")


@pytest.mark.parametrize("folder", [MA2, MA3], ids=["ma2", "ma3"])
def test_golden_xml_is_parseable(folder: Path) -> None:
    missing = _missing(folder)
    if missing:
        pytest.skip(f"Golden XML not collected yet in {folder}")

    for name in REQUIRED_FILES:
        root = load_xml_root(folder / name)
        assert root is not None


def test_ma3_timecode_has_goto_or_targeted_go_and_top_events() -> None:
    path = MA3 / "timecode.xml"
    if not path.is_file():
        pytest.skip("MA3 timecode.xml not collected yet")

    root = load_xml_root(path)
    missing = require_tags(root, {"Timecode", "Track", "CmdEvent", "RealtimeCmd"})
    assert not missing, f"MA3 timecode.xml missing tags: {missing}"

    tokens = {
        (cmd.get("ExecToken") or "")
        for cmd in root.iter()
        if xml_tag_local(cmd.tag) == "RealtimeCmd"
    }
    assert "Top" in tokens
    # Product default (user habit): Go+ with CueDestination on Main track.
    assert "Go+" in tokens


def test_ma3_button_sequence_has_follow_point_one() -> None:
    path = MA3 / "button_sequence.xml"
    if not path.is_file():
        pytest.skip("MA3 button_sequence.xml not collected yet")

    root = load_xml_root(path)
    follow_cues = [
        cue
        for cue in root.iter()
        if xml_tag_local(cue.tag) == "Cue" and cue.get("TrigType") == "Follow"
    ]
    assert follow_cues, "Expected a Follow cue on the button sequence"
    assert any(cue.get("TrigTime") == "0.100" for cue in follow_cues)


def test_ma2_button_sequence_has_follow_release() -> None:
    path = MA2 / "button_sequence.xml"
    if not path.is_file():
        pytest.skip("MA2 button_sequence.xml not collected yet")

    root = load_xml_root(path)
    release_cues = [
        cue
        for cue in root.iter()
        if xml_tag_local(cue.tag) == "Cue" and cue.get("cue_mode") == "Release"
    ]
    assert release_cues, "Expected Release cue_mode on MA2 button cue 2"

    triggers = [
        trig
        for trig in root.iter()
        if xml_tag_local(trig.tag) == "Trigger" and trig.get("type") == "Follow"
    ]
    assert triggers, "Expected Follow trigger on MA2 button cue 2"
    assert any(trig.get("data_f") == "0.1" for trig in triggers)


def test_ma2_timecode_has_go_and_top_events() -> None:
    path = MA2 / "timecode.xml"
    if not path.is_file():
        pytest.skip("MA2 timecode.xml not collected yet")

    root = load_xml_root(path)
    missing = require_tags(root, {"Timecode", "Track", "Event"})
    assert not missing, f"MA2 timecode.xml missing tags: {missing}"

    commands = {
        (event.get("command") or "")
        for event in root.iter()
        if xml_tag_local(event.tag) == "Event"
    }
    assert "Go" in commands  # MA2 XML token for Go+
    assert "Top" in commands

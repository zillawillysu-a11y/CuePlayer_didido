"""Audio output settings persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from cueplayer.domain.models import AudioOutputSettings, Project
from cueplayer.persistence.project_store import load_project, save_project
from cueplayer.routing.matrix import default_route_dict


def test_default_route_multichannel() -> None:
    route = default_route_dict(4)
    assert route[0] == [0]
    assert route[1] == [1]
    assert route[2] == [2]


def test_default_route_stereo_no_ltc() -> None:
    route = default_route_dict(2)
    assert route[0] == [0]
    assert route[1] == [1]
    assert 2 not in route


def test_default_ltc_channels_stereo_is_ch2() -> None:
    from cueplayer.domain.models import default_ltc_channels_for_device

    assert default_ltc_channels_for_device(2) == [1]


def test_audio_output_roundtrip(tmp_path: Path) -> None:
    project = Project.create("路由測試")
    project.audio_output = AudioOutputSettings(
        output_device_name="Focusrite USB",
        music_left_channels=[0],
        music_right_channels=[1],
        ltc_enabled=True,
        ltc_source="source_left",
        ltc_gain=0.55,
        ltc_channels=[2],
        mtc_enabled=True,
        midi_enabled=True,
        midi_port_name="loopMIDI Port",
        midi_cue_notes_enabled=True,
        midi_cue_channel=2,
        midi_main_base_note=40,
        midi_button_base_note=52,
    )
    path = tmp_path / "中文專案" / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    ao = loaded.audio_output
    assert ao.output_device_name == "Focusrite USB"
    assert ao.ltc_enabled is True
    assert ao.ltc_source == "source_left"
    assert ao.ltc_gain == pytest.approx(0.55)
    assert ao.ltc_channels == [2]
    assert ao.mtc_enabled is True
    assert ao.midi_enabled is True
    assert ao.midi_port_name == "loopMIDI Port"
    assert ao.midi_cue_notes_enabled is True
    assert ao.midi_cue_channel == 2
    assert ao.midi_main_base_note == 40
    assert ao.midi_button_base_note == 52

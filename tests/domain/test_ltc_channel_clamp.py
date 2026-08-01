"""LTC / music channel clamp helpers for stereo (2-ch) devices."""

from __future__ import annotations

from cueplayer.domain.models import (
    clamp_output_channels,
    default_ltc_channels_for_device,
)
from cueplayer.playback.routing_parse import parse_channel_ui as _parse_channel_ui
from cueplayer.ui.audio_timecode_dialog import _clamp_channel_ui_text


def test_default_ltc_jumps_into_stereo_range() -> None:
    assert default_ltc_channels_for_device(4) == [2]  # CH3
    assert default_ltc_channels_for_device(3) == [2]  # CH3
    assert default_ltc_channels_for_device(2) == [1]  # CH2
    assert default_ltc_channels_for_device(1) == [0]  # CH1
    assert default_ltc_channels_for_device(0) == []


def test_clamp_output_channels_maps_ch3_to_ch2_on_stereo() -> None:
    assert clamp_output_channels([2], 2) == [1]
    assert clamp_output_channels([0, 1, 2], 2) == [0, 1]
    assert clamp_output_channels([5], 2) == [1]
    assert clamp_output_channels([2], 4) == [2]


def test_parse_channel_ui_clamps_ltc_three_on_stereo() -> None:
    assert _parse_channel_ui("3", max_ch=2) == [1]
    assert _parse_channel_ui("1+3", max_ch=2) == [0, 1]
    assert _parse_channel_ui("3", max_ch=4) == [2]


def test_clamp_channel_ui_text_rewrites_three_to_two() -> None:
    assert _clamp_channel_ui_text("3", max_ch=2, fallback=[1]) == "2"
    assert _clamp_channel_ui_text("", max_ch=2, fallback=[1]) == "2"
    assert _clamp_channel_ui_text("3", max_ch=4, fallback=[2]) == "3"

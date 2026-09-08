"""Per-channel output mode routing round-trip."""

from __future__ import annotations

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.playback.routing_parse import (
    SRC_FILE_MUSIC,
    SRC_LTC_BUS,
    build_stereo_route_map,
    derive_channel_modes,
    ltc_output_channels_from_settings,
    stereo_routes_from_channel_modes,
)


def test_stereo_split_from_channel_modes() -> None:
    modes = ["music_source", "ltc"]
    left_kind, left_ch, right_kind, right_ch, ltc_bus = stereo_routes_from_channel_modes(
        modes,
        max_ch=2,
    )
    assert left_kind == "music_source"
    assert left_ch == [0]
    assert right_kind == "ltc"
    assert right_ch == [1]
    assert ltc_bus == [1]


def test_derive_channel_modes_from_legacy_stereo() -> None:
    settings = AudioOutputSettings(
        music_l_route="Music Source",
        music_r_route="LTC",
        ltc_enabled=True,
        ltc_channels=[2],
    )
    modes = derive_channel_modes(settings, max_ch=4)
    assert modes[0] == "music_source"
    assert modes[1] == "ltc"
    assert modes[2] == "ltc"


def test_four_channel_labels_round_trip() -> None:
    modes = ["music_source", "music_source", "ltc", "off"]
    left_kind, left_ch, right_kind, right_ch, ltc_bus = stereo_routes_from_channel_modes(
        modes,
        max_ch=4,
    )
    assert left_kind == "music_source" and left_ch == [0]
    assert right_kind == "music_source" and right_ch == [1]
    assert ltc_bus == [2]

    settings = AudioOutputSettings(output_channel_modes=modes)
    derived = derive_channel_modes(settings, max_ch=4)
    assert derived[:4] == modes


def test_music_source_only_has_no_ltc_wire() -> None:
    from cueplayer.playback.routing_parse import ltc_output_channels_from_settings

    settings = AudioOutputSettings(
        output_channel_modes=["music_source", "music_source"],
        ltc_enabled=True,
        ltc_source="generator",
        ltc_generator_enabled=True,
        ltc_channels=[1],
    )
    assert ltc_output_channels_from_settings(settings, max_ch=2) == []

    route = build_stereo_route_map(
        left_kind="music_source",
        left_channels=[0],
        right_kind="music_source",
        right_channels=[1],
        ltc_channels=[],
        ltc_bus_active=False,
    )
    assert SRC_LTC_BUS not in route
    assert route[SRC_FILE_MUSIC] == [0, 1]

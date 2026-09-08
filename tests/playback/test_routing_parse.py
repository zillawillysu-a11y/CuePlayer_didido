"""Stereo route string parsing tests."""

from __future__ import annotations

from cueplayer.playback.routing_parse import (
    LTC_LABEL,
    MUSIC_SOURCE_LABEL,
    SRC_FILE_LTC,
    SRC_FILE_MUSIC,
    SRC_LTC_BUS,
    build_stereo_route_map,
    parse_stereo_route,
)


def test_music_source_and_ltc_split_route() -> None:
    left = parse_stereo_route(MUSIC_SOURCE_LABEL, side="l", max_ch=4)
    right = parse_stereo_route(LTC_LABEL, side="r", max_ch=4)
    assert left == ("music_source", [0])
    assert right == ("ltc", [1])
    route = build_stereo_route_map(
        left_kind=left[0],
        left_channels=left[1],
        right_kind=right[0],
        right_channels=right[1],
        ltc_channels=[2],
        ltc_bus_active=True,
    )
    assert route[SRC_FILE_MUSIC] == [0]
    assert route[SRC_FILE_LTC] == [1]
    assert route[SRC_LTC_BUS] == [2]


def test_both_music_source_routes_to_stereo_outs() -> None:
    left = parse_stereo_route(MUSIC_SOURCE_LABEL, side="l", max_ch=2)
    right = parse_stereo_route(MUSIC_SOURCE_LABEL, side="r", max_ch=2)
    route = build_stereo_route_map(
        left_kind=left[0],
        left_channels=left[1],
        right_kind=right[0],
        right_channels=right[1],
        ltc_channels=[],
        ltc_bus_active=False,
    )
    assert route[SRC_FILE_MUSIC] == [0, 1]


def test_exclusive_ltc_removes_music_from_ltc_channel() -> None:
    from cueplayer.playback.routing_parse import SRC_MUSIC_L, SRC_MUSIC_R, exclusive_ltc_route

    route = {
        SRC_MUSIC_L: [0],
        SRC_MUSIC_R: [1],
        SRC_LTC_BUS: [1],  # 2-ch device: LTC landed on CH2 with Music R
    }
    cleaned, cleared = exclusive_ltc_route(route)
    assert cleared == [1]
    assert cleaned[SRC_MUSIC_L] == [0]
    assert SRC_MUSIC_R not in cleaned
    assert cleaned[SRC_LTC_BUS] == [1]


def test_speaker_channels_skip_ltc_wire() -> None:
    from cueplayer.playback.routing_parse import speaker_channels_without_ltc

    assert speaker_channels_without_ltc(
        preferred=[0, 1], ltc_channels=[2], max_ch=8
    ) == [0, 1]
    assert speaker_channels_without_ltc(
        preferred=[0, 1], ltc_channels=[1], max_ch=2
    ) == [0]

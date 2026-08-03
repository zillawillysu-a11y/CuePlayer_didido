"""Parse stereo output route strings (Music Source / LTC / channel numbers)."""

from __future__ import annotations

from cueplayer.domain.models import clamp_output_channels

# Source bus indices (see AudioEngine stream callback).
SRC_MUSIC_L = 0
SRC_MUSIC_R = 1
SRC_LTC_BUS = 2
SRC_FILE_MUSIC = 3
SRC_FILE_LTC = 4

MUSIC_SOURCE_LABEL = "Music Source"
LTC_LABEL = "LTC"


def _normalize_route_text(text: str) -> str:
    return (text or "").strip()


def is_music_source_route(text: str) -> bool:
    low = _normalize_route_text(text).casefold().replace(" ", "")
    return low in ("musicsource", "music", "source")


def is_ltc_route(text: str) -> bool:
    return _normalize_route_text(text).casefold() == "ltc"


def is_mute_route(text: str) -> bool:
    low = _normalize_route_text(text).casefold()
    return low in ("", "mute", "off", "—", "-")


def default_dest_for_side(side: str, max_ch: int) -> list[int]:
    if max_ch <= 0:
        return []
    if side == "l":
        return [0]
    return [min(1, max_ch - 1)]


def parse_channel_ui(text: str, *, max_ch: int) -> list[int] | None:
    """Parse '1', '1+2', '3' (1-based) → 0-based indices."""
    raw = _normalize_route_text(text).replace(",", "+")
    if not raw:
        return []
    parts = [p for p in raw.split("+") if p]
    out: list[int] = []
    for part in parts:
        try:
            one_based = int(part)
        except ValueError:
            return None
        if one_based < 1:
            return None
        idx = one_based - 1
        if max_ch > 0 and idx >= max_ch:
            idx = max_ch - 1
        if idx not in out:
            out.append(idx)
    return out


def parse_stereo_route(
    text: str,
    *,
    side: str,
    max_ch: int,
) -> tuple[str, list[int]] | None:
    """
    Return (kind, destinations) where kind is mute | music_source | ltc | channels.
    None when the text is invalid.
    """
    if is_mute_route(text):
        return "mute", []
    if is_music_source_route(text):
        dest = default_dest_for_side(side, max_ch)
        return "music_source", clamp_output_channels(dest, max_ch)
    if is_ltc_route(text):
        dest = default_dest_for_side(side, max_ch)
        return "ltc", clamp_output_channels(dest, max_ch)
    chs = parse_channel_ui(text, max_ch=max_ch)
    if chs is None:
        return None
    return "channels", chs


def route_to_ui(kind: str, channels: list[int], *, legacy_text: str = "") -> str:
    if kind == "music_source" or is_music_source_route(legacy_text):
        return MUSIC_SOURCE_LABEL
    if kind == "ltc" or is_ltc_route(legacy_text):
        return LTC_LABEL
    if kind == "mute" or is_mute_route(legacy_text):
        return ""
    if not channels:
        return legacy_text
    return "+".join(str(int(c) + 1) for c in channels)


def build_stereo_route_map(
    *,
    left_kind: str,
    left_channels: list[int],
    right_kind: str,
    right_channels: list[int],
    ltc_channels: list[int],
    ltc_bus_active: bool,
) -> dict[int, list[int]]:
    """Merge L/R/LTC bus routes into a source→dest map."""
    route: dict[int, list[int]] = {}

    def add(src: int, dests: list[int]) -> None:
        if not dests:
            return
        route.setdefault(src, [])
        for d in dests:
            if d not in route[src]:
                route[src].append(d)

    if left_kind == "music_source":
        add(SRC_FILE_MUSIC, left_channels)
    elif left_kind == "ltc":
        add(SRC_FILE_LTC, left_channels)
    elif left_kind == "channels":
        add(SRC_MUSIC_L, left_channels)

    if right_kind == "music_source":
        add(SRC_FILE_MUSIC, right_channels)
    elif right_kind == "ltc":
        add(SRC_FILE_LTC, right_channels)
    elif right_kind == "channels":
        add(SRC_MUSIC_R, right_channels)

    if ltc_bus_active and ltc_channels:
        add(SRC_LTC_BUS, ltc_channels)
    return route

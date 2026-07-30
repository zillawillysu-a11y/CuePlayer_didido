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


_MUSIC_ROUTE_SOURCES = (SRC_MUSIC_L, SRC_MUSIC_R, SRC_FILE_MUSIC)


def exclusive_ltc_route(
    route: dict[int, list[int]],
) -> tuple[dict[int, list[int]], list[int]]:
    """
    Keep dedicated LTC output channel(s) free of music.

    Any Music L/R / Music Source destinations that overlap ``SRC_LTC_BUS``
    outs are removed so the LTC wire stays timecode-only.
    """
    ltc_dests = {int(d) for d in route.get(SRC_LTC_BUS, [])}
    if not ltc_dests:
        return {k: list(v) for k, v in route.items()}, []

    out: dict[int, list[int]] = {}
    cleared: list[int] = []
    for src, dests in route.items():
        if src in _MUSIC_ROUTE_SOURCES:
            kept = [d for d in dests if int(d) not in ltc_dests]
            removed = [d for d in dests if int(d) in ltc_dests]
            cleared.extend(int(d) for d in removed)
            if kept:
                out[src] = kept
            continue
        out[src] = list(dests)
    return out, sorted(set(cleared))


def speaker_channels_without_ltc(
    *,
    preferred: list[int],
    ltc_channels: list[int],
    max_ch: int,
) -> list[int]:
    """Pick Music Source destinations that do not share the LTC wire(s)."""
    blocked = {int(c) for c in ltc_channels}
    speakers = [int(c) for c in preferred if 0 <= int(c) < max_ch and int(c) not in blocked]
    if speakers:
        return speakers
    return [c for c in range(max(0, max_ch)) if c not in blocked]


ChannelMode = str  # "music_source" | "ltc" | "off"


def derive_channel_modes(settings, *, max_ch: int) -> list[str]:  # noqa: ANN001
    """Build per-output-channel modes from legacy stereo + LTC routes."""
    from cueplayer.domain.models import AudioOutputSettings, clamp_output_channels, default_ltc_channels_for_device

    if not isinstance(settings, AudioOutputSettings):
        raise TypeError("settings must be AudioOutputSettings")
    max_ch = max(1, int(max_ch))
    if settings.output_channel_modes and len(settings.output_channel_modes) >= max_ch:
        out = [str(m) for m in settings.output_channel_modes[:max_ch]]
        while len(out) < max_ch:
            out.append("off")
        return out

    modes: list[str] = ["off"] * max_ch
    left_p = parse_stereo_route(settings.music_l_route, side="l", max_ch=max_ch)
    right_p = parse_stereo_route(settings.music_r_route, side="r", max_ch=max_ch)
    ltc_list = (
        clamp_output_channels(list(settings.ltc_channels), max_ch)
        if settings.ltc_enabled
        else []
    )
    for ch in ltc_list:
        if 0 <= ch < max_ch:
            modes[ch] = "ltc"

    def _apply(kind: str, chs: list[int]) -> None:
        for ch in chs:
            if 0 <= ch < max_ch and modes[ch] == "off":
                if kind in ("music_source", "channels"):
                    modes[ch] = "music_source"
                elif kind == "ltc":
                    modes[ch] = "ltc"

    if left_p is not None:
        _apply(left_p[0], left_p[1])
    if right_p is not None:
        _apply(right_p[0], right_p[1])

    for i in range(min(2, max_ch)):
        if modes[i] == "off":
            modes[i] = "music_source"
    if settings.ltc_enabled and not any(m == "ltc" for m in modes):
        for ch in default_ltc_channels_for_device(max_ch):
            if 0 <= ch < max_ch:
                modes[ch] = "ltc"
    return modes


def stereo_routes_from_channel_modes(
    modes: list[str],
    *,
    max_ch: int,
) -> tuple[str, list[int], str, list[int], list[int]]:
    """Map per-channel Music/LTC picks → stereo leg kinds + LTC bus channel(s)."""
    max_ch = max(1, int(max_ch))
    norm = [str(modes[i]) if i < len(modes) else "off" for i in range(max_ch)]
    music_idxs = [i for i, m in enumerate(norm) if m == "music_source"]
    ltc_idxs = [i for i, m in enumerate(norm) if m == "ltc"]

    if len(music_idxs) >= 2:
        left_kind, left_ch = "channels", [music_idxs[0]]
        right_kind, right_ch = "channels", [music_idxs[1]]
    elif len(music_idxs) == 1 and ltc_idxs:
        left_kind, left_ch = "music_source", [music_idxs[0]]
        right_kind, right_ch = "ltc", [ltc_idxs[0]]
    elif len(music_idxs) == 1:
        ch = music_idxs[0]
        left_kind, left_ch = "channels", [ch]
        right_kind, right_ch = "channels", [ch]
    else:
        left_kind, left_ch = "music_source", default_dest_for_side("l", max_ch)
        right_kind, right_ch = "music_source", default_dest_for_side("r", max_ch)

    bus_ltc = ltc_idxs[:1]
    return left_kind, left_ch, right_kind, right_ch, bus_ltc

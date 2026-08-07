"""UTF-8 JSON project persistence with schema versioning."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cueplayer.domain.models import (
    SCHEMA_VERSION,
    MARKER_SHAPE_LABELS,
    VIDEO_DECODE_QUALITY_MAX_HEIGHT,
    AudioOutputSettings,
    AudioTrack,
    CleanVideoOutputSettings,
    Mark,
    MarkLane,
    MaExportSettings,
    Project,
    SetlistCategory,
    SetlistNameMode,
    Song,
    VideoClip,
    VideoDecodeQuality,
    coerce_file_ltc_side,
)
from cueplayer.domain.song_variant import SongVariant, coerce_variant_kind
from cueplayer.persistence.mark_template import dicts_to_lanes, lanes_to_dicts
from cueplayer.persistence.media_paths import (
    from_storage_path,
    project_root_for,
    to_storage_path,
)
from cueplayer.persistence.project_migrations import SchemaError, migrate_project_dict
from cueplayer.exporters.common import ma_export_name_from_display
from cueplayer.domain.cue_list_columns import normalize_cue_list_column_order

__all__ = [
    "SchemaError",
    "migrate_project_dict",
    "load_project",
    "save_project",
    "project_to_dict",
    "project_from_dict",
]


def _coerce_setlist_name_mode(data: dict[str, Any]) -> SetlistNameMode:
    raw = data.get("setlist_name_mode")
    if raw in ("zh", "both", "en"):
        return raw  # type: ignore[return-value]
    # Legacy bool: True ≈ 中英共存.
    if bool(data.get("show_setlist_ma_names", False)):
        return "both"
    return "zh"


def _coerce_optional_bpm(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def ma_export_to_dict(settings: MaExportSettings) -> dict[str, Any]:
    return {
        "console": settings.console,
        "export_mode": settings.export_mode,
        "sequence_pool_start": int(settings.sequence_pool_start),
        "timecode_pool_start": int(settings.timecode_pool_start),
        "main_executor": settings.main_executor,
        "button_executor_start": settings.button_executor_start,
        "timecode_slot": int(settings.timecode_slot),
        "data_pool": settings.data_pool,
        "latency_ms": float(settings.latency_ms),
        "page_per_song": bool(settings.page_per_song),
        "show_install_macro_name": settings.show_install_macro_name,
        "ma2_song_viewbutton": settings.ma2_song_viewbutton,
        "ma2_include_fixed_macros": bool(settings.ma2_include_fixed_macros),
        "ma2_include_song_macros": bool(settings.ma2_include_song_macros),
        "ma2_include_song_list": bool(settings.ma2_include_song_list),
        "ma2_template_page": int(settings.ma2_template_page),
        "ma2_fixed_macro_start": int(settings.ma2_fixed_macro_start),
        "ma2_song_macro_start": int(settings.ma2_song_macro_start),
        "ma2_add_main_preset_cue": bool(settings.ma2_add_main_preset_cue),
        "ma2_main_preset_cue_id": float(settings.ma2_main_preset_cue_id),
        "ma2_include_song_views": bool(settings.ma2_include_song_views),
        "ma2_view_pool_start": int(settings.ma2_view_pool_start),
        "ma2_effect_pool_start": int(settings.ma2_effect_pool_start),
        "ma2_effect_slots_per_song": int(settings.ma2_effect_slots_per_song),
        "ma2_sequence_slots_per_song": int(settings.ma2_sequence_slots_per_song),
        "ma2_view_layout": [dict(widget) for widget in settings.ma2_view_layout],
        "ma2_telnet_host": settings.ma2_telnet_host,
        "ma2_telnet_command_port": int(settings.ma2_telnet_command_port),
        "ma2_telnet_monitor_port": int(settings.ma2_telnet_monitor_port),
        "ma2_telnet_user": settings.ma2_telnet_user,
        "ma2_telnet_plugin_pool": int(settings.ma2_telnet_plugin_pool),
        "ma2_telnet_plugin_import_path": settings.ma2_telnet_plugin_import_path,
        "export_song_ids": list(settings.export_song_ids),
        "export_content_by_song": {
            str(song_id): dict(content)
            for song_id, content in settings.export_content_by_song.items()
            if isinstance(content, dict)
        },
        "output_dir_ma2": settings.output_dir_ma2,
        "output_dir_ma3": settings.output_dir_ma3,
        "ma2_target_version": settings.ma2_target_version,
        "ma2_output_dir_follows_version": bool(
            settings.ma2_output_dir_follows_version
        ),
    }


def dict_to_ma_export(raw: Any) -> MaExportSettings:
    if not isinstance(raw, dict):
        return MaExportSettings()
    console = str(raw.get("console") or "ma2")
    if console not in ("ma2", "ma3"):
        console = "ma2"
    mode = str(raw.get("export_mode") or "full")
    if mode not in ("full", "timecode_only"):
        mode = "full"
    legacy_defaults = "ma2_target_version" not in raw
    timecode_start = int(raw.get("timecode_pool_start", 201) or 201)
    main_executor = str(raw.get("main_executor") or "201.130")
    button_executor = str(raw.get("button_executor_start") or "201.101")
    template_page = int(raw.get("ma2_template_page", 200) or 200)
    fixed_macro_start = int(
        raw.get("ma2_fixed_macro_start", raw.get("ma2_macro_pool_start", 101)) or 101
    )
    song_macro_start = int(raw.get("ma2_song_macro_start", 201) or 201)
    if legacy_defaults:
        if timecode_start == 1:
            timecode_start = 201
        if main_executor == "1.101":
            main_executor = "201.130"
        if button_executor == "1.201":
            button_executor = "201.101"
        if template_page == 100:
            template_page = 200
        if fixed_macro_start == 1001:
            fixed_macro_start = 101
        if song_macro_start == 1009:
            song_macro_start = 201
    return MaExportSettings(
        console=console,
        export_mode=mode,
        sequence_pool_start=int(raw.get("sequence_pool_start", 1) or 1),
        timecode_pool_start=timecode_start,
        main_executor=main_executor,
        button_executor_start=button_executor,
        timecode_slot=int(raw.get("timecode_slot", 1) or 1),
        data_pool=str(raw.get("data_pool") or "Default"),
        latency_ms=float(raw.get("latency_ms", 0.0) or 0.0),
        page_per_song=bool(raw.get("page_per_song", True)),
        show_install_macro_name=str(
            raw.get("show_install_macro_name") or "CuePlayer_Show_Install"
        ),
        ma2_song_viewbutton=str(raw.get("ma2_song_viewbutton") or "1.20"),
        ma2_include_fixed_macros=bool(raw.get("ma2_include_fixed_macros", True)),
        ma2_include_song_macros=bool(raw.get("ma2_include_song_macros", True)),
        ma2_include_song_list=bool(raw.get("ma2_include_song_list", True)),
        ma2_template_page=template_page,
        ma2_fixed_macro_start=fixed_macro_start,
        ma2_song_macro_start=song_macro_start,
        ma2_add_main_preset_cue=bool(raw.get("ma2_add_main_preset_cue", False)),
        ma2_main_preset_cue_id=float(raw.get("ma2_main_preset_cue_id", 0.5) or 0.5),
        ma2_include_song_views=bool(raw.get("ma2_include_song_views", True)),
        ma2_view_pool_start=int(raw.get("ma2_view_pool_start", 201) or 201),
        ma2_effect_pool_start=int(raw.get("ma2_effect_pool_start", 201) or 201),
        ma2_effect_slots_per_song=max(
            1, int(raw.get("ma2_effect_slots_per_song", 100) or 100)
        ),
        ma2_sequence_slots_per_song=max(
            1, int(raw.get("ma2_sequence_slots_per_song", 20) or 20)
        ),
        ma2_view_layout=[
            dict(widget)
            for widget in raw.get("ma2_view_layout", [])
            if isinstance(widget, dict)
        ],
        ma2_telnet_host=str(raw.get("ma2_telnet_host") or "127.0.0.1"),
        ma2_telnet_command_port=max(
            1, int(raw.get("ma2_telnet_command_port", 30000) or 30000)
        ),
        ma2_telnet_monitor_port=max(
            1, int(raw.get("ma2_telnet_monitor_port", 30001) or 30001)
        ),
        ma2_telnet_user=str(raw.get("ma2_telnet_user") or "CuePlayerScan"),
        ma2_telnet_plugin_pool=max(
            2, int(raw.get("ma2_telnet_plugin_pool", 9999) or 9999)
        ),
        ma2_telnet_plugin_import_path=str(raw.get("ma2_telnet_plugin_import_path") or ""),
        export_song_ids=[
            str(x) for x in (raw.get("export_song_ids") or []) if str(x).strip()
        ],
        export_content_by_song={
            str(song_id): dict(content)
            for song_id, content in (raw.get("export_content_by_song") or {}).items()
            if isinstance(content, dict)
        },
        output_dir_ma2=str(raw.get("output_dir_ma2") or ""),
        output_dir_ma3=str(raw.get("output_dir_ma3") or ""),
        ma2_target_version=str(raw.get("ma2_target_version") or ""),
        ma2_output_dir_follows_version=bool(
            raw.get("ma2_output_dir_follows_version", True)
        ),
    )


def _coerce_channel_list(raw: Any, default: list[int]) -> list[int]:
    if raw is None:
        return list(default)
    if not isinstance(raw, list):
        return list(default)
    out: list[int] = []
    for item in raw:
        try:
            ch = int(item)
        except (TypeError, ValueError):
            continue
        if ch >= 0:
            out.append(ch)
    return out


def audio_output_to_dict(settings: AudioOutputSettings) -> dict[str, Any]:
    return {
        "output_device_name": settings.output_device_name,
        "output_device_index": settings.output_device_index,
        "output_hostapi": str(settings.output_hostapi or ""),
        "music_l_route": str(settings.music_l_route or "1"),
        "music_r_route": str(settings.music_r_route or "2"),
        "music_left_channels": list(settings.music_left_channels),
        "music_right_channels": list(settings.music_right_channels),
        "ltc_enabled": bool(settings.ltc_enabled),
        "ltc_source": str(settings.ltc_source),
        "ltc_generator_enabled": bool(settings.ltc_generator_enabled),
        "ltc_gain": float(settings.ltc_gain),
        "ltc_channels": list(settings.ltc_channels),
        "ltc_to_mtc_translate": bool(settings.ltc_to_mtc_translate),
        "midi_enabled": bool(settings.midi_enabled),
        "mtc_enabled": bool(settings.mtc_enabled),
        "midi_port_name": settings.midi_port_name,
        "midi_cue_notes_enabled": bool(settings.midi_cue_notes_enabled),
        "midi_cue_channel": int(settings.midi_cue_channel),
        "midi_cue_velocity": int(settings.midi_cue_velocity),
        "midi_main_base_note": int(settings.midi_main_base_note),
        "midi_button_base_note": int(settings.midi_button_base_note),
        "output_channel_modes": list(settings.output_channel_modes),
    }


def dict_to_audio_output(raw: Any) -> AudioOutputSettings:
    if not isinstance(raw, dict):
        return AudioOutputSettings()
    gain = float(raw.get("ltc_gain", 0.8) or 0.8)
    gain = min(1.5, max(0.0, gain))
    ltc_source = str(raw.get("ltc_source") or "auto")
    if ltc_source not in ("generator", "auto", "source_left", "source_right"):
        ltc_source = "auto"
    left = _coerce_channel_list(raw.get("music_left_channels"), [0])
    right = _coerce_channel_list(raw.get("music_right_channels"), [1])
    music_l_route = str(raw.get("music_l_route") or "").strip()
    music_r_route = str(raw.get("music_r_route") or "").strip()
    if not music_l_route:
        music_l_route = "+".join(str(int(c) + 1) for c in left) or "1"
    if not music_r_route:
        music_r_route = "+".join(str(int(c) + 1) for c in right) or "2"
    dev_index = raw.get("output_device_index")
    try:
        dev_index = int(dev_index) if dev_index is not None else None
    except (TypeError, ValueError):
        dev_index = None
    ltc_to_mtc = bool(raw.get("ltc_to_mtc_translate", False))
    mtc_on = bool(raw.get("mtc_enabled", False))
    notes_on = bool(raw.get("midi_cue_notes_enabled", False))
    if "midi_enabled" in raw:
        midi_on = bool(raw.get("midi_enabled"))
    else:
        midi_on = mtc_on or notes_on or ltc_to_mtc
    return AudioOutputSettings(
        output_device_name=str(raw.get("output_device_name") or ""),
        output_device_index=dev_index,
        output_hostapi=str(raw.get("output_hostapi") or ""),
        music_l_route=music_l_route,
        music_r_route=music_r_route,
        music_left_channels=left,
        music_right_channels=right,
        ltc_enabled=bool(raw.get("ltc_enabled", False)),
        ltc_source=ltc_source,  # type: ignore[arg-type]
        ltc_generator_enabled=bool(raw.get("ltc_generator_enabled", True)),
        ltc_gain=gain,
        ltc_channels=_coerce_channel_list(raw.get("ltc_channels"), [2]),
        ltc_to_mtc_translate=ltc_to_mtc,
        midi_enabled=midi_on,
        mtc_enabled=mtc_on,
        midi_port_name=str(raw.get("midi_port_name") or ""),
        midi_cue_notes_enabled=notes_on,
        midi_cue_channel=max(1, min(16, int(raw.get("midi_cue_channel", 1) or 1))),
        midi_cue_velocity=max(1, min(127, int(raw.get("midi_cue_velocity", 100) or 100))),
        midi_main_base_note=max(0, min(127, int(raw.get("midi_main_base_note", 36) or 36))),
        midi_button_base_note=max(
            0, min(127, int(raw.get("midi_button_base_note", 48) or 48))
        ),
        output_channel_modes=[
            str(m) for m in (raw.get("output_channel_modes") or []) if str(m)
        ],
    )


def clean_video_output_to_dict(settings: CleanVideoOutputSettings) -> dict[str, Any]:
    mode = str(getattr(settings, "ndi_frame_mode", "") or "output_window")
    if mode not in ("video", "output_window"):
        mode = "output_window"
    return {
        "width": int(settings.width),
        "height": int(settings.height),
        "aspect_locked": bool(settings.aspect_locked),
        "was_open": bool(settings.was_open),
        "ndi_enabled": bool(getattr(settings, "ndi_enabled", False)),
        "ndi_name": str(getattr(settings, "ndi_name", "") or "CuePlayer"),
        "ndi_frame_mode": mode,
    }


def dict_to_clean_video_output(raw: Any) -> CleanVideoOutputSettings:
    if not isinstance(raw, dict):
        return CleanVideoOutputSettings()
    default = CleanVideoOutputSettings()
    try:
        width = int(raw.get("width", default.width))
    except (TypeError, ValueError):
        width = default.width
    try:
        height = int(raw.get("height", default.height))
    except (TypeError, ValueError):
        height = default.height
    if width <= 0:
        width = default.width
    if height <= 0:
        height = default.height
    mode = str(raw.get("ndi_frame_mode") or "output_window")
    if mode not in ("video", "output_window"):
        mode = "output_window"
    return CleanVideoOutputSettings(
        width=width,
        height=height,
        aspect_locked=bool(raw.get("aspect_locked", default.aspect_locked)),
        was_open=bool(raw.get("was_open", default.was_open)),
        ndi_enabled=bool(raw.get("ndi_enabled", False)),
        ndi_name=str(raw.get("ndi_name") or "CuePlayer"),
        ndi_frame_mode=mode,
    )


def _coerce_video_decode_quality(raw: Any) -> VideoDecodeQuality:
    if raw in VIDEO_DECODE_QUALITY_MAX_HEIGHT:
        return raw  # type: ignore[return-value]
    return "1080p"


def _variant_metadata_to_dict(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        out[str(key)] = str(value)
    return out


def _variant_to_dict(
    variant: SongVariant, *, project_dir: Path | None
) -> dict[str, Any]:
    return {
        "id": variant.id,
        "name": variant.name,
        "kind": variant.kind,
        "path": _path_to_str(variant.path, project_dir),
        "anchor_offset": float(variant.anchor_offset),
        "enabled": bool(variant.enabled),
        "metadata": dict(variant.metadata),
    }


def _variant_from_dict(
    raw: dict[str, Any], *, project_dir: Path | None
) -> SongVariant:
    return SongVariant(
        id=str(raw.get("id") or ""),
        name=str(raw.get("name") or "Variant"),
        kind=coerce_variant_kind(raw.get("kind")),
        path=_str_to_path(str(raw.get("path") or ""), project_dir),
        anchor_offset=float(raw.get("anchor_offset", 0.0) or 0.0),
        enabled=bool(raw.get("enabled", True)),
        metadata=_variant_metadata_to_dict(raw.get("metadata")),
    )


def _variants_from_song_data(
    song_data: dict[str, Any], *, project_dir: Path | None
) -> tuple[list[SongVariant], str | None]:
    raw_list = song_data.get("variants")
    variants: list[SongVariant] = []
    if isinstance(raw_list, list):
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            variant = _variant_from_dict(item, project_dir=project_dir)
            if not variant.id:
                continue
            variants.append(variant)
    selected = song_data.get("selected_variant_id")
    selected_id = str(selected) if selected else None
    if selected_id and not any(v.id == selected_id for v in variants):
        selected_id = variants[0].id if variants else None
    elif selected_id is None and variants:
        selected_id = variants[0].id
    return variants, selected_id


def _path_to_str(path: Path, project_dir: Path | None = None) -> str:
    return to_storage_path(path, project_dir)


def _str_to_path(value: str, project_dir: Path | None = None) -> Path:
    return from_storage_path(value, project_dir)


def _coerce_mark_line_style(value: Any, *, default: str = "solid") -> str:
    style = str(value or default).strip().lower()
    if style not in ("solid", "dash", "dot"):
        return default
    return style


def _coerce_waveform_color(value: Any, *, default: str = "#616161") -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    if not raw.startswith("#"):
        raw = f"#{raw}"
    if len(raw) not in (4, 7, 9):
        return default
    return raw


_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _coerce_row_color(value: Any) -> str:
    """Song.row_color: "" (unset) or a strict "#RRGGBB"; anything else → unset."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not raw.startswith("#"):
        raw = f"#{raw}"
    if not _HEX_COLOR_RE.match(raw):
        return ""
    return raw.upper()


def _load_project_mark_line_settings(
    data: dict[str, Any], songs: list[Song]
) -> tuple[str, float, float, float]:
    """
    Project-global mark line look.

    Prefer project keys; if missing, migrate from the first song (older per-song
    Display Settings). Default style is solid.
    """
    if "mark_line_style" in data or "mark_line_width" in data:
        style = _coerce_mark_line_style(data.get("mark_line_style"), default="solid")
        width = float(data.get("mark_line_width", 1.0))
        dash_on = float(data.get("mark_dash_on", 4.0))
        dash_off = float(data.get("mark_dash_off", dash_on))
        return style, width, dash_on, dash_off
    for song in songs:
        return (
            _coerce_mark_line_style(song.mark_line_style, default="solid"),
            float(song.mark_line_width or 1.0),
            float(song.mark_dash_on or 4.0),
            float(song.mark_dash_off or 4.0),
        )
    return "solid", 1.0, 4.0, 4.0


def _load_project_waveform_color(data: dict[str, Any], songs: list[Song]) -> str:
    if "waveform_color" in data:
        return _coerce_waveform_color(data.get("waveform_color"))
    for song in songs:
        return _coerce_waveform_color(song.waveform_color)
    return "#616161"


def _load_project_playhead_color(data: dict[str, Any]) -> str:
    return _coerce_waveform_color(data.get("playhead_color"), default="#3dd68c")


def _load_project_show_video_track(data: dict[str, Any], songs: list[Song]) -> bool:
    """Project-global eye; legacy projects inherit from the first song."""
    if "show_video_track" in data:
        return bool(data.get("show_video_track"))
    if songs:
        return bool(songs[0].show_video_track)
    return True


def _clamp_mark_lane_height(value: Any, *, default: float = 28.0) -> float:
    try:
        height = float(value)
    except (TypeError, ValueError):
        height = default
    return float(min(80.0, max(24.0, height)))


def _load_project_mark_lane_height(data: dict[str, Any], songs: list[Song]) -> float:
    """Project-global mark lane height; migrate from first song when missing."""
    if "mark_lane_height" in data:
        return _clamp_mark_lane_height(data.get("mark_lane_height"))
    for song in songs:
        return _clamp_mark_lane_height(song.mark_lane_height)
    return 28.0


def _load_project_show_mark_track_colors(data: dict[str, Any], songs: list[Song]) -> bool:
    if "show_mark_track_colors" in data:
        return bool(data.get("show_mark_track_colors"))
    for song in songs:
        for lane in song.mark_lanes:
            if not getattr(lane, "show_row_color", True):
                return False
    return True


def _load_now_config(song_data: dict[str, Any]) -> tuple[bool, list[int], list[int]]:
    """Return (configured, primary_lanes, secondary_lanes), with legacy migration."""
    if "now_primary_lanes" in song_data or "now_secondary_lanes" in song_data:
        primary = _coerce_int_list(song_data.get("now_primary_lanes"))
        secondary = _coerce_int_list(song_data.get("now_secondary_lanes"))
        configured = bool(song_data.get("now_lanes_configured", True))
        return configured, primary, secondary

    if any(k in song_data for k in ("now_lane_a", "now_lane_b", "now_show_secondary")):
        primary: list[int] = []
        a = song_data.get("now_lane_a")
        if a is not None:
            try:
                ai = int(a)
            except (TypeError, ValueError):
                ai = 0
            if ai != 0:
                primary = [ai]
        secondary: list[int] = []
        if bool(song_data.get("now_show_secondary", True)):
            b = song_data.get("now_lane_b")
            if b is None:
                # Keep unconfigured so secondary auto-fills all buttons.
                return False, primary, []
            try:
                bi = int(b)
            except (TypeError, ValueError):
                bi = 0
            if bi != 0:
                secondary = [bi]
        return True, primary, secondary

    return False, [], []


def _coerce_clip_duration(clip: dict[str, Any]) -> float:
    """New field; derive from legacy source_in/out when an older project lacks it."""
    if "duration_seconds" in clip:
        try:
            duration = float(clip["duration_seconds"])
            if duration > 0:
                return duration
        except (TypeError, ValueError):
            pass
    src_in = float(clip.get("source_in_seconds", 0.0) or 0.0)
    src_out = clip.get("source_out_seconds")
    if src_out is not None:
        try:
            duration = float(src_out) - src_in
            if duration > 0:
                return duration
        except (TypeError, ValueError):
            pass
    return 5.0


def _coerce_int_list(raw: Any) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for item in raw:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out



def project_to_dict(
    project: Project, *, project_dir: Path | None = None
) -> dict[str, Any]:
    return {
        "schema_version": project.schema_version,
        "id": project.id,
        "name": project.name,
        "setlist_name_mode": project.setlist_name_mode,
        "setlist_show_bpm": bool(project.setlist_show_bpm),
        "setlist_show_ltc_badge": bool(project.setlist_show_ltc_badge),
        "setlist_show_video_badge": bool(project.setlist_show_video_badge),
        "default_mark_lanes": lanes_to_dicts(project.default_mark_lanes),
        "mark_line_style": project.mark_line_style,
        "mark_dash_on": project.mark_dash_on,
        "mark_dash_off": project.mark_dash_off,
        "mark_line_width": project.mark_line_width,
        "wave_label_font_px": int(getattr(project, "wave_label_font_px", 10) or 10),
        "waveform_color": project.waveform_color,
        "playhead_color": project.playhead_color,
        "mark_lane_height": float(project.mark_lane_height),
        "show_mark_track_colors": bool(project.show_mark_track_colors),
        "show_output_timecode_clock": bool(project.show_output_timecode_clock),
        "output_timecode_clock_color": project.output_timecode_clock_color,
        "show_output_quick_toggles": bool(project.show_output_quick_toggles),
        "show_video_track": bool(project.show_video_track),
        "show_wave_gain_line": bool(project.show_wave_gain_line),
        "show_ltc_gain_line": bool(project.show_ltc_gain_line),
        "ma_export": ma_export_to_dict(project.ma_export),
        "audio_output": audio_output_to_dict(project.audio_output),
        "clean_video_output": clean_video_output_to_dict(project.clean_video_output),
        "video_decode_quality": project.video_decode_quality,
        "setlist_categories": [
            {
                "id": category.id,
                "name": category.name,
                "collapsed": bool(category.collapsed),
                "sheet_collapsed": bool(category.sheet_collapsed),
                "row_color": category.row_color,
            }
            for category in project.setlist_categories
        ],
        "songs": [
            {
                "id": song.id,
                "name": song.name,
                "setlist_number": song.setlist_number,
                "ma_export_name": song.ma_export_name,
                "bpm": song.bpm,
                "bpm_auto": bool(getattr(song, "bpm_auto", False) and song.bpm is not None),
                "note": song.note,
                "row_color": song.row_color,
                "category_id": song.category_id,
                "start_timecode": song.start_timecode,
                "fps": song.fps,
                "duration_seconds": song.duration_seconds,
                "use_left_ltc": bool(song.file_ltc_side == "left"),  # legacy mirror
                "file_ltc_side": coerce_file_ltc_side(song.file_ltc_side),
                "audio_tracks": [
                    {
                        "id": track.id,
                        "name": track.name,
                        "path": _path_to_str(track.path, project_dir),
                        "role": track.role,
                        "color": track.color,
                        "muted": track.muted,
                        "solo": track.solo,
                        "locked": track.locked,
                        "hidden": track.hidden,
                        "offset_seconds": track.offset_seconds,
                    }
                    for track in song.audio_tracks
                ],
                "variants": [
                    _variant_to_dict(variant, project_dir=project_dir)
                    for variant in song.variants
                ],
                "selected_variant_id": song.selected_variant_id,
                "video_clips": [
                    {
                        "id": clip.id,
                        "name": clip.name,
                        "path": _path_to_str(clip.path, project_dir),
                        "start_seconds": clip.start_seconds,
                        "source_in_seconds": clip.source_in_seconds,
                        "source_out_seconds": clip.source_out_seconds,
                        "duration_seconds": clip.duration_seconds,
                        "locked": clip.locked,
                        "hidden": clip.hidden,
                        "volume": clip.volume,
                        "media_kind": clip.media_kind,
                        "source_duration_seconds": clip.source_duration_seconds,
                    }
                    for clip in song.video_clips
                ],
                "video_track_muted": song.video_track_muted,
                "show_video_track": bool(song.show_video_track),
                "show_ltc_track": bool(song.show_ltc_track),
                "ltc_lane_height": song.ltc_lane_height,
                "music_volume": song.music_volume,
                "audio_gain_db": song.audio_gain_db,
                "video_lane_height": song.video_lane_height,
                "mark_lanes": [
                    {
                        "index": lane.index,
                        "name": lane.name,
                        "lane_type": lane.lane_type,
                        "color": lane.color,
                        "shortcut": lane.shortcut,
                        "visible": lane.visible,
                        "locked": lane.locked,
                        "export_enabled": lane.export_enabled,
                        "cue_id_enabled": lane.cue_id_enabled,
                        "cue_list_enabled": lane.cue_list_enabled,
                        "midi_note_enabled": bool(getattr(lane, "midi_note_enabled", False)),
                        "midi_note": int(getattr(lane, "midi_note", 0) or 0),
                        "pause_on_mark": bool(getattr(lane, "pause_on_mark", False)),
                        "prompt_note_on_mark": bool(
                            getattr(lane, "prompt_note_on_mark", False)
                        ),
                        "show_note_on_wave": bool(
                            getattr(lane, "show_note_on_wave", False)
                        ),
                        "show_cue_id_on_wave": bool(
                            getattr(lane, "show_cue_id_on_wave", False)
                        ),
                        "marker_shape": lane.marker_shape,
                        "show_row_color": bool(getattr(lane, "show_row_color", True)),
                    }
                    for lane in song.mark_lanes
                ],
                "marks": [
                    {
                        "id": mark.id,
                        "lane_index": mark.lane_index,
                        "time_seconds": mark.time_seconds,
                        "display_name": mark.display_name,
                        "ma_export_name": mark.ma_export_name,
                        "main_cue_id": mark.main_cue_id,
                    }
                    for mark in song.marks
                ],
                "show_mark_tracks": song.show_mark_tracks,
                "show_mark_stem": song.show_mark_stem,
                "now_lanes_configured": song.now_lanes_configured,
                "now_primary_lanes": list(song.now_primary_lanes),
                "now_secondary_lanes": list(song.now_secondary_lanes),
                "now_secondary_enabled": song.now_secondary_enabled,
                "now_primary_visible": song.now_primary_visible,
                "now_secondary_visible": song.now_secondary_visible,
                "cue_list_visible": song.cue_list_visible,
                "cue_list_column_order": list(song.cue_list_column_order),
                "cue_list_show_cue_id": bool(song.cue_list_show_cue_id),
                "now_primary_show_cue_id": bool(song.now_primary_show_cue_id),
                "now_primary_single_line": bool(song.now_primary_single_line),
                "now_secondary_clear_seconds": song.now_secondary_clear_seconds,
            }
            for song in project.songs
        ],
    }


def project_from_dict(
    data: dict[str, Any], *, project_dir: Path | None = None
) -> Project:
    version = int(data.get("schema_version", 0))
    data = migrate_project_dict(data, version)

    songs: list[Song] = []
    for song_index, song_data in enumerate(data.get("songs", [])):
        audio_tracks = [
            AudioTrack(
                id=track["id"],
                name=track["name"],
                path=_str_to_path(track["path"], project_dir),
                role=track.get("role", "reference"),
                color=track.get("color", "#2BB673"),
                muted=bool(track.get("muted", False)),
                solo=bool(track.get("solo", False)),
                locked=bool(track.get("locked", False)),
                hidden=bool(track.get("hidden", False)),
                offset_seconds=float(track.get("offset_seconds", 0.0)),
            )
            for track in song_data.get("audio_tracks", [])
        ]
        video_clips = [
            VideoClip(
                id=clip["id"],
                name=clip["name"],
                path=_str_to_path(clip["path"], project_dir),
                start_seconds=float(clip.get("start_seconds", 0.0)),
                source_in_seconds=float(clip.get("source_in_seconds", 0.0)),
                source_out_seconds=clip.get("source_out_seconds"),
                duration_seconds=_coerce_clip_duration(clip),
                locked=bool(clip.get("locked", False)),
                hidden=bool(clip.get("hidden", False)),
                volume=float(min(1.0, max(0.0, clip.get("volume", 1.0)))),
                media_kind="still" if clip.get("media_kind") == "still" else "video",
                source_duration_seconds=(
                    float(clip["source_duration_seconds"])
                    if clip.get("source_duration_seconds") is not None
                    else None
                ),
            )
            for clip in song_data.get("video_clips", [])
        ]
        mark_lanes = []
        for lane in song_data.get("mark_lanes", []):
            shape = lane.get("marker_shape", "circle")
            if shape not in MARKER_SHAPE_LABELS:
                shape = "circle"
            mark_lanes.append(
                MarkLane(
                    index=int(lane["index"]),
                    name=lane["name"],
                    lane_type=lane.get("lane_type", "top_button"),
                    color=lane.get("color", "#4C8BF5"),
                    shortcut=lane.get("shortcut", ""),
                    visible=bool(lane.get("visible", True)),
                    locked=bool(lane.get("locked", False)),
                    export_enabled=bool(lane.get("export_enabled", True)),
                    cue_id_enabled=bool(
                        lane.get(
                            "cue_id_enabled",
                            lane.get("lane_type", "top_button") == "main",
                        )
                    ),
                    cue_list_enabled=bool(
                        lane.get(
                            "cue_list_enabled",
                            lane.get("lane_type", "top_button") == "main",
                        )
                    ),
                    midi_note_enabled=bool(lane.get("midi_note_enabled", False)),
                    midi_note=int(lane.get("midi_note", 0) or 0),
                    pause_on_mark=bool(lane.get("pause_on_mark", False)),
                    prompt_note_on_mark=bool(lane.get("prompt_note_on_mark", False)),
                    show_note_on_wave=bool(lane.get("show_note_on_wave", False)),
                    show_cue_id_on_wave=bool(lane.get("show_cue_id_on_wave", False)),
                    marker_shape=shape,
                    show_row_color=bool(lane.get("show_row_color", True)),
                )
            )
        marks = [
            Mark(
                id=mark["id"],
                lane_index=int(mark["lane_index"]),
                time_seconds=float(mark["time_seconds"]),
                display_name=mark.get("display_name", ""),
                ma_export_name=mark.get("ma_export_name"),
                main_cue_id=str(mark.get("main_cue_id") or ""),
            )
            for mark in song_data.get("marks", [])
        ]
        variants, selected_variant_id = _variants_from_song_data(
            song_data, project_dir=project_dir
        )
        now_cfg = _load_now_config(song_data)
        songs.append(
            Song(
                id=song_data["id"],
                name=song_data["name"],
                setlist_number=float(
                    song_data.get("setlist_number", song_index + 1)
                ),
                ma_export_name=(
                    (song_data.get("ma_export_name") or "").strip()
                    or ma_export_name_from_display(song_data["name"])
                ),
                bpm=_coerce_optional_bpm(song_data.get("bpm")),
                bpm_auto=bool(
                    song_data.get("bpm_auto", False)
                    and _coerce_optional_bpm(song_data.get("bpm")) is not None
                ),
                note=str(song_data.get("note") or ""),
                row_color=_coerce_row_color(song_data.get("row_color")),
                category_id=song_data.get("category_id"),
                start_timecode=song_data.get("start_timecode", "01:00:00:00"),
                fps=float(song_data.get("fps", 30.0)),
                duration_seconds=float(song_data.get("duration_seconds", 60.0)),
                file_ltc_side=coerce_file_ltc_side(
                    song_data.get("file_ltc_side"),
                    use_left_ltc=bool(song_data.get("use_left_ltc", False)),
                ),
                audio_tracks=audio_tracks,
                variants=variants,
                selected_variant_id=selected_variant_id,
                video_clips=video_clips,
                video_track_muted=bool(song_data.get("video_track_muted", False)),
                show_video_track=bool(song_data.get("show_video_track", True)),
                show_ltc_track=bool(song_data.get("show_ltc_track", False)),
                ltc_lane_height=float(
                    min(400.0, max(28.0, song_data.get("ltc_lane_height", 56.0)))
                ),
                music_volume=float(min(1.0, max(0.0, song_data.get("music_volume", 1.0)))),
                audio_gain_db=float(
                    max(-12.0, min(12.0, float(song_data.get("audio_gain_db", 0.0))))
                ),
                mark_lane_height=float(
                    min(80.0, max(24.0, float(song_data.get("mark_lane_height", 28.0))))
                ),
                video_lane_height=float(
                    min(4096.0, max(28.0, song_data.get("video_lane_height", 40.0)))
                ),
                mark_lanes=mark_lanes,
                marks=marks,
                show_mark_tracks=bool(song_data.get("show_mark_tracks", True)),
                show_mark_stem=bool(song_data.get("show_mark_stem", False)),
                mark_line_style=_coerce_mark_line_style(
                    song_data.get("mark_line_style"), default="solid"
                ),
                mark_dash_on=float(song_data.get("mark_dash_on", 4.0)),
                mark_dash_off=float(song_data.get("mark_dash_off", 4.0)),
                mark_line_width=float(song_data.get("mark_line_width", 1.0)),
                waveform_color=str(song_data.get("waveform_color") or "#616161"),
                now_lanes_configured=now_cfg[0],
                now_primary_lanes=now_cfg[1],
                now_secondary_lanes=now_cfg[2],
                now_secondary_enabled=bool(song_data.get("now_secondary_enabled", True)),
                now_primary_visible=bool(song_data.get("now_primary_visible", True)),
                now_secondary_visible=bool(song_data.get("now_secondary_visible", True)),
                cue_list_visible=bool(song_data.get("cue_list_visible", True)),
                cue_list_column_order=normalize_cue_list_column_order(
                    song_data.get("cue_list_column_order")
                ),
                cue_list_show_cue_id=bool(song_data.get("cue_list_show_cue_id", True)),
                now_primary_show_cue_id=bool(song_data.get("now_primary_show_cue_id", True)),
                now_primary_single_line=bool(song_data.get("now_primary_single_line", False)),
                now_secondary_clear_seconds=float(
                    song_data.get("now_secondary_clear_seconds", 2.0)
                ),
            )
        )

    line_style, line_width, dash_on, dash_off = _load_project_mark_line_settings(data, songs)
    wave_color = _load_project_waveform_color(data, songs)
    playhead_color = _load_project_playhead_color(data)
    show_video_track = _load_project_show_video_track(data, songs)
    mark_lane_height = _load_project_mark_lane_height(data, songs)
    show_mark_track_colors = _load_project_show_mark_track_colors(data, songs)
    from cueplayer.domain.main_cue_id import migrate_main_cue_ids

    for song in songs:
        song.show_video_track = show_video_track
        song.show_ltc_track = show_video_track
        migrate_main_cue_ids(song)
        song.sort_marks()
    categories = [
        SetlistCategory(
            id=str(item["id"]),
            name=str(item.get("name") or "Category"),
            collapsed=bool(item.get("collapsed", False)),
            sheet_collapsed=bool(item.get("sheet_collapsed", False)),
            row_color=_coerce_row_color(item.get("row_color")),
        )
        for item in data.get("setlist_categories") or []
        if isinstance(item, dict) and item.get("id")
    ]

    return Project(
        id=data["id"],
        name=data["name"],
        schema_version=int(data["schema_version"]),
        songs=songs,
        setlist_categories=categories,
        setlist_name_mode=_coerce_setlist_name_mode(data),
        setlist_show_bpm=bool(data.get("setlist_show_bpm", True)),
        setlist_show_ltc_badge=bool(data.get("setlist_show_ltc_badge", True)),
        setlist_show_video_badge=bool(data.get("setlist_show_video_badge", True)),
        default_mark_lanes=dicts_to_lanes(data.get("default_mark_lanes") or []),
        mark_line_style=line_style,  # type: ignore[arg-type]
        mark_line_width=line_width,
        mark_dash_on=dash_on,
        mark_dash_off=dash_off,
        wave_label_font_px=max(
            8,
            min(28, int(data.get("wave_label_font_px", 10) or 10)),
        ),
        waveform_color=wave_color,
        playhead_color=playhead_color,
        mark_lane_height=mark_lane_height,
        show_mark_track_colors=show_mark_track_colors,
        show_output_timecode_clock=bool(data.get("show_output_timecode_clock", True)),
        output_timecode_clock_color=_coerce_waveform_color(
            data.get("output_timecode_clock_color"), default="#3dd68c"
        ),
        show_output_quick_toggles=bool(data.get("show_output_quick_toggles", True)),
        show_video_track=show_video_track,
        show_wave_gain_line=bool(data.get("show_wave_gain_line", False)),
        show_ltc_gain_line=bool(data.get("show_ltc_gain_line", False)),
        ma_export=dict_to_ma_export(data.get("ma_export")),
        audio_output=dict_to_audio_output(data.get("audio_output")),
        clean_video_output=dict_to_clean_video_output(data.get("clean_video_output")),
        video_decode_quality=_coerce_video_decode_quality(data.get("video_decode_quality")),
    )


def save_project(project: Project, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = project_to_dict(project, project_dir=project_root_for(path))
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def load_project(path: Path) -> Project:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise SchemaError("Project file root must be a JSON object.")
    return project_from_dict(data, project_dir=project_root_for(path))

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
from cueplayer.persistence.mark_template import dicts_to_lanes, lanes_to_dicts


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
        "export_song_ids": list(settings.export_song_ids),
        "output_dir_ma2": settings.output_dir_ma2,
        "output_dir_ma3": settings.output_dir_ma3,
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
    return MaExportSettings(
        console=console,
        export_mode=mode,
        sequence_pool_start=int(raw.get("sequence_pool_start", 1) or 1),
        timecode_pool_start=int(raw.get("timecode_pool_start", 1) or 1),
        main_executor=str(raw.get("main_executor") or "1.101"),
        button_executor_start=str(raw.get("button_executor_start") or "1.201"),
        timecode_slot=int(raw.get("timecode_slot", 1) or 1),
        data_pool=str(raw.get("data_pool") or "Default"),
        latency_ms=float(raw.get("latency_ms", 0.0) or 0.0),
        page_per_song=bool(raw.get("page_per_song", True)),
        show_install_macro_name=str(
            raw.get("show_install_macro_name") or "CuePlayer_Show_Install"
        ),
        export_song_ids=[
            str(x) for x in (raw.get("export_song_ids") or []) if str(x).strip()
        ],
        output_dir_ma2=str(raw.get("output_dir_ma2") or ""),
        output_dir_ma3=str(raw.get("output_dir_ma3") or ""),
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
        "mtc_enabled": bool(settings.mtc_enabled),
        "midi_port_name": settings.midi_port_name,
    }


def dict_to_audio_output(raw: Any) -> AudioOutputSettings:
    if not isinstance(raw, dict):
        return AudioOutputSettings()
    gain = float(raw.get("ltc_gain", 0.8) or 0.8)
    gain = min(1.5, max(0.0, gain))
    ltc_source = str(raw.get("ltc_source") or "generator")
    if ltc_source not in ("generator", "auto", "source_left", "source_right"):
        ltc_source = "generator"
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
        mtc_enabled=bool(raw.get("mtc_enabled", False)),
        midi_port_name=str(raw.get("midi_port_name") or ""),
    )


def clean_video_output_to_dict(settings: CleanVideoOutputSettings) -> dict[str, Any]:
    return {
        "width": int(settings.width),
        "height": int(settings.height),
        "aspect_locked": bool(settings.aspect_locked),
        "was_open": bool(settings.was_open),
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
    return CleanVideoOutputSettings(
        width=width,
        height=height,
        aspect_locked=bool(raw.get("aspect_locked", default.aspect_locked)),
        was_open=bool(raw.get("was_open", default.was_open)),
    )


def _coerce_video_decode_quality(raw: Any) -> VideoDecodeQuality:
    if raw in VIDEO_DECODE_QUALITY_MAX_HEIGHT:
        return raw  # type: ignore[return-value]
    return "1080p"


class SchemaError(ValueError):
    """Raised when a project file cannot be migrated or parsed."""


def _path_to_str(path: Path) -> str:
    return str(path)


def _str_to_path(value: str) -> Path:
    return Path(value)


def _coerce_mark_line_style(value: Any, *, default: str = "solid") -> str:
    style = str(value or default).strip().lower()
    if style not in ("solid", "dash", "dot"):
        return default
    return style


def _coerce_waveform_color(value: Any, *, default: str = "#3dd68c") -> str:
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
    return "#3dd68c"


def _load_project_playhead_color(data: dict[str, Any]) -> str:
    return _coerce_waveform_color(data.get("playhead_color"), default="#ff5a5f")


def _load_project_show_video_track(data: dict[str, Any], songs: list[Song]) -> bool:
    """Project-global eye; legacy projects inherit from the first song."""
    if "show_video_track" in data:
        return bool(data.get("show_video_track"))
    if songs:
        return bool(songs[0].show_video_track)
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



def project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "schema_version": project.schema_version,
        "id": project.id,
        "name": project.name,
        "setlist_name_mode": project.setlist_name_mode,
        "setlist_show_bpm": bool(project.setlist_show_bpm),
        "default_mark_lanes": lanes_to_dicts(project.default_mark_lanes),
        "mark_line_style": project.mark_line_style,
        "mark_dash_on": project.mark_dash_on,
        "mark_dash_off": project.mark_dash_off,
        "mark_line_width": project.mark_line_width,
        "waveform_color": project.waveform_color,
        "playhead_color": project.playhead_color,
        "show_video_track": bool(project.show_video_track),
        "ma_export": ma_export_to_dict(project.ma_export),
        "audio_output": audio_output_to_dict(project.audio_output),
        "clean_video_output": clean_video_output_to_dict(project.clean_video_output),
        "video_decode_quality": project.video_decode_quality,
        "setlist_categories": [
            {
                "id": category.id,
                "name": category.name,
                "collapsed": bool(category.collapsed),
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
                        "path": _path_to_str(track.path),
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
                "video_clips": [
                    {
                        "id": clip.id,
                        "name": clip.name,
                        "path": _path_to_str(clip.path),
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
                        "marker_shape": lane.marker_shape,
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
                "now_secondary_clear_seconds": song.now_secondary_clear_seconds,
            }
            for song in project.songs
        ],
    }


def project_from_dict(data: dict[str, Any]) -> Project:
    version = int(data.get("schema_version", 0))
    data = migrate_project_dict(data, version)

    songs: list[Song] = []
    for song_index, song_data in enumerate(data.get("songs", [])):
        audio_tracks = [
            AudioTrack(
                id=track["id"],
                name=track["name"],
                path=_str_to_path(track["path"]),
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
                path=_str_to_path(clip["path"]),
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
                    marker_shape=shape,
                )
            )
        marks = [
            Mark(
                id=mark["id"],
                lane_index=int(mark["lane_index"]),
                time_seconds=float(mark["time_seconds"]),
                display_name=mark.get("display_name", ""),
                ma_export_name=mark.get("ma_export_name"),
            )
            for mark in song_data.get("marks", [])
        ]
        now_cfg = _load_now_config(song_data)
        songs.append(
            Song(
                id=song_data["id"],
                name=song_data["name"],
                setlist_number=float(
                    song_data.get("setlist_number", song_index + 1)
                ),
                ma_export_name=song_data.get("ma_export_name"),
                bpm=_coerce_optional_bpm(song_data.get("bpm")),
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
                video_clips=video_clips,
                video_track_muted=bool(song_data.get("video_track_muted", False)),
                show_video_track=bool(song_data.get("show_video_track", True)),
                show_ltc_track=bool(song_data.get("show_ltc_track", False)),
                ltc_lane_height=float(
                    min(400.0, max(28.0, song_data.get("ltc_lane_height", 56.0)))
                ),
                music_volume=float(min(1.0, max(0.0, song_data.get("music_volume", 1.0)))),
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
                waveform_color=str(song_data.get("waveform_color") or "#3dd68c"),
                now_lanes_configured=now_cfg[0],
                now_primary_lanes=now_cfg[1],
                now_secondary_lanes=now_cfg[2],
                now_secondary_enabled=bool(song_data.get("now_secondary_enabled", True)),
                now_primary_visible=bool(song_data.get("now_primary_visible", True)),
                now_secondary_visible=bool(song_data.get("now_secondary_visible", True)),
                now_secondary_clear_seconds=float(
                    song_data.get("now_secondary_clear_seconds", 2.0)
                ),
            )
        )

    line_style, line_width, dash_on, dash_off = _load_project_mark_line_settings(data, songs)
    wave_color = _load_project_waveform_color(data, songs)
    playhead_color = _load_project_playhead_color(data)
    show_video_track = _load_project_show_video_track(data, songs)
    for song in songs:
        song.show_video_track = show_video_track
        song.show_ltc_track = show_video_track
    categories = [
        SetlistCategory(
            id=str(item["id"]),
            name=str(item.get("name") or "Category"),
            collapsed=bool(item.get("collapsed", False)),
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
        default_mark_lanes=dicts_to_lanes(data.get("default_mark_lanes") or []),
        mark_line_style=line_style,  # type: ignore[arg-type]
        mark_line_width=line_width,
        mark_dash_on=dash_on,
        mark_dash_off=dash_off,
        waveform_color=wave_color,
        playhead_color=playhead_color,
        show_video_track=show_video_track,
        ma_export=dict_to_ma_export(data.get("ma_export")),
        audio_output=dict_to_audio_output(data.get("audio_output")),
        clean_video_output=dict_to_clean_video_output(data.get("clean_video_output")),
        video_decode_quality=_coerce_video_decode_quality(data.get("video_decode_quality")),
    )


def migrate_project_dict(data: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Migrate older project dicts up to SCHEMA_VERSION."""
    if from_version > SCHEMA_VERSION:
        raise SchemaError(
            f"Project schema_version {from_version} is newer than supported {SCHEMA_VERSION}."
        )

    migrated = dict(data)
    version = from_version
    if version == 0:
        migrated.setdefault("schema_version", SCHEMA_VERSION)
        migrated.setdefault("songs", [])
        version = 1

    if version != SCHEMA_VERSION:
        raise SchemaError(f"No migration path from schema_version {from_version}.")

    migrated["schema_version"] = SCHEMA_VERSION
    return migrated


def save_project(project: Project, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = project_to_dict(project)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def load_project(path: Path) -> Project:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise SchemaError("Project file root must be a JSON object.")
    return project_from_dict(data)

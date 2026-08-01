"""Build JSON state snapshots for the Web Remote UI."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from cueplayer.domain.models import Mark, MarkLane, Project, Song
from cueplayer.media.audio_loader import AudioBuffer
from cueplayer.timecode.smpte import seconds_to_timecode


class _EngineView(Protocol):
    @property
    def playing(self) -> bool: ...

    @property
    def position(self) -> float: ...

    @property
    def duration(self) -> float: ...


def format_clock(seconds: float) -> str:
    """Song-relative clock: ``HH:MM:SS.cc`` (centiseconds), e.g. ``00:00:07.07``."""
    total_cs = int(round(max(0.0, float(seconds)) * 100.0))
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def mark_payload(mark: Mark, lane: MarkLane | None) -> dict[str, Any]:
    t = float(mark.time_seconds)
    return {
        "id": mark.id,
        "lane_index": int(mark.lane_index),
        "time_seconds": t,
        "time_display": format_clock(t),
        "display_name": mark.display_name or "",
        "main_cue_id": mark.main_cue_id or "",
        "lane_name": lane.name if lane is not None else f"Mark {mark.lane_index}",
        "lane_type": lane.lane_type if lane is not None else "top_button",
        "color": lane.color if lane is not None else "#888888",
        "shortcut": lane.shortcut if lane is not None else "",
        "cue_list_enabled": bool(lane.cue_list_enabled) if lane is not None else True,
        "lane_visible": bool(lane.visible) if lane is not None else True,
    }


def _lane_map(song: Song) -> dict[int, MarkLane]:
    return {lane.index: lane for lane in song.mark_lanes}


def _now_for_lanes(
    song: Song,
    position: float,
    lane_indices: list[int],
    lanes: dict[int, MarkLane],
) -> list[dict[str, Any]]:
    wanted = set(lane_indices)
    if not wanted:
        return []
    latest: dict[int, Mark] = {}
    for mark in song.marks:
        if mark.lane_index not in wanted:
            continue
        if mark.time_seconds - 1e-9 > position:
            continue
        prev = latest.get(mark.lane_index)
        if prev is None or mark.time_seconds >= prev.time_seconds:
            latest[mark.lane_index] = mark
    out: list[dict[str, Any]] = []
    for index in lane_indices:
        mark = latest.get(index)
        if mark is None:
            continue
        out.append(mark_payload(mark, lanes.get(index)))
    return out


def build_state(
    *,
    project: Project,
    song: Song,
    engine: _EngineView,
) -> dict[str, Any]:
    songs = list(project.songs)
    try:
        song_index = songs.index(song) if song in songs else -1
    except ValueError:
        song_index = -1

    categories = {c.id: c.name for c in project.setlist_categories}
    song_rows: list[dict[str, Any]] = []
    for i, s in enumerate(songs):
        song_rows.append(
            {
                "index": i,
                "id": s.id,
                "name": s.name,
                "setlist_number": float(s.setlist_number),
                "category": categories.get(s.category_id or "", "") if s.category_id else "",
                "duration_seconds": float(s.duration_seconds),
                "active": i == song_index,
            }
        )

    lanes = _lane_map(song)
    lane_rows = [
        {
            "index": lane.index,
            "name": lane.name,
            "shortcut": lane.shortcut or "",
            "color": lane.color,
            "lane_type": lane.lane_type,
            "visible": bool(lane.visible),
            "locked": bool(lane.locked),
            "cue_list_enabled": bool(lane.cue_list_enabled),
        }
        for lane in sorted(song.mark_lanes, key=lambda L: L.index)
    ]

    mark_rows = [
        mark_payload(m, lanes.get(m.lane_index))
        for m in sorted(song.marks, key=lambda m: (m.time_seconds, m.lane_index))
    ]
    cue_list_rows = [
        m
        for m in mark_rows
        if m.get("cue_list_enabled", True) and m.get("lane_visible", True)
    ]

    primary_lanes = list(song.now_primary_lanes) if song.now_lanes_configured else [1]
    secondary_lanes = list(song.now_secondary_lanes) if song.now_lanes_configured else []
    if not song.now_secondary_enabled:
        secondary_lanes = []

    position = float(engine.position)
    duration = float(engine.duration)

    # Playhead Cue List row (same rule as desktop last_cue_list_mark_at_or_before).
    playhead_cue_id = ""
    for m in cue_list_rows:
        if float(m["time_seconds"]) - 1e-9 <= position:
            playhead_cue_id = str(m["id"])
        else:
            break

    fps = float(song.fps) if song.fps > 0 else 30.0
    abs_tc = seconds_to_timecode(
        timecode_to_abs_seconds(song.start_timecode, fps) + position,
        fps,
    ).format()

    playhead = str(getattr(project, "playhead_color", "") or "#3dd68c")
    waveform_color = str(getattr(project, "waveform_color", "") or "#616161")

    return {
        "project_name": project.name,
        "playing": bool(engine.playing),
        "position": position,
        "duration": duration,
        "clock": format_clock(position),
        "duration_clock": format_clock(duration),
        "timecode": abs_tc,
        "playhead_color": playhead,
        "waveform_color": waveform_color,
        "playhead_cue_id": playhead_cue_id,
        "song": {
            "id": song.id,
            "index": song_index,
            "name": song.name,
            "setlist_number": float(song.setlist_number),
            "start_timecode": song.start_timecode,
            "fps": fps,
            "in_setlist": song_index >= 0,
        },
        "songs": song_rows,
        "lanes": lane_rows,
        "marks": mark_rows,
        "cue_list": cue_list_rows,
        "now": {
            "primary": _now_for_lanes(song, position, primary_lanes, lanes),
            "secondary": _now_for_lanes(song, position, secondary_lanes, lanes),
        },
    }


def build_waveform_overview(
    buffer: AudioBuffer | None,
    *,
    song_id: str,
    duration: float,
    buckets: int = 900,
) -> dict[str, Any]:
    """Downsample peak pyramid into a fixed-width overview for the remote canvas."""
    n = max(32, min(2000, int(buckets)))
    empty = {
        "ok": True,
        "song_id": song_id,
        "duration": float(max(0.1, duration)),
        "buckets": n,
        "mins": [0.0] * n,
        "maxs": [0.0] * n,
        "ready": False,
    }
    if buffer is None or not buffer.peak_levels:
        return empty

    # Prefer a coarse level so overview stays light for iPad Safari.
    level = buffer.peak_levels[-1]
    for candidate in reversed(buffer.peak_levels):
        if candidate.mins.size >= n // 2:
            level = candidate
            break

    mins = np.asarray(level.mins, dtype=np.float32)
    maxs = np.asarray(level.maxs, dtype=np.float32)
    if mins.size == 0:
        return empty

    src_n = int(mins.size)
    out_mins = np.zeros(n, dtype=np.float32)
    out_maxs = np.zeros(n, dtype=np.float32)
    for i in range(n):
        a = int(i * src_n / n)
        b = max(a + 1, int((i + 1) * src_n / n))
        out_mins[i] = float(mins[a:b].min())
        out_maxs[i] = float(maxs[a:b].max())

    # Soft normalize for display (avoid flat lines on quiet beds).
    peak = float(max(np.max(np.abs(out_mins)), np.max(np.abs(out_maxs)), 1e-6))
    scale = 1.0 / peak
    out_mins = out_mins * scale
    out_maxs = out_maxs * scale

    dur = float(buffer.duration_seconds) if buffer.frames > 0 else float(duration)
    return {
        "ok": True,
        "song_id": song_id,
        "duration": float(max(0.1, dur)),
        "buckets": n,
        "mins": [round(float(v), 4) for v in out_mins.tolist()],
        "maxs": [round(float(v), 4) for v in out_maxs.tolist()],
        "ready": True,
    }


def timecode_to_abs_seconds(timecode: str, fps: float) -> float:
    from cueplayer.timecode.smpte import timecode_to_seconds

    return float(timecode_to_seconds(timecode, fps))

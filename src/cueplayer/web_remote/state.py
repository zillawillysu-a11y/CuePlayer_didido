"""Build JSON state snapshots for the Web Remote UI."""

from __future__ import annotations

from typing import Any, Protocol

from cueplayer.domain.models import Mark, MarkLane, Project, Song
from cueplayer.timecode.smpte import seconds_to_timecode


class _EngineView(Protocol):
    @property
    def playing(self) -> bool: ...

    @property
    def position(self) -> float: ...

    @property
    def duration(self) -> float: ...


def format_clock(seconds: float) -> str:
    total = max(0.0, float(seconds))
    minutes = int(total // 60.0)
    secs = total - minutes * 60.0
    if minutes >= 100:
        return f"{minutes}:{secs:06.3f}"
    return f"{minutes:02d}:{secs:06.3f}"


def mark_payload(mark: Mark, lane: MarkLane | None) -> dict[str, Any]:
    return {
        "id": mark.id,
        "lane_index": int(mark.lane_index),
        "time_seconds": float(mark.time_seconds),
        "display_name": mark.display_name or "",
        "main_cue_id": mark.main_cue_id or "",
        "lane_name": lane.name if lane is not None else f"Mark {mark.lane_index}",
        "lane_type": lane.lane_type if lane is not None else "top_button",
        "color": lane.color if lane is not None else "#888888",
        "shortcut": lane.shortcut if lane is not None else "",
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
        }
        for lane in sorted(song.mark_lanes, key=lambda L: L.index)
    ]

    mark_rows = [
        mark_payload(m, lanes.get(m.lane_index))
        for m in sorted(song.marks, key=lambda m: (m.time_seconds, m.lane_index))
    ]

    primary_lanes = list(song.now_primary_lanes) if song.now_lanes_configured else [1]
    secondary_lanes = list(song.now_secondary_lanes) if song.now_lanes_configured else []
    if not song.now_secondary_enabled:
        secondary_lanes = []

    position = float(engine.position)
    duration = float(engine.duration)
    fps = float(song.fps) if song.fps > 0 else 30.0
    abs_tc = seconds_to_timecode(
        timecode_to_abs_seconds(song.start_timecode, fps) + position,
        fps,
    ).format()

    return {
        "project_name": project.name,
        "playing": bool(engine.playing),
        "position": position,
        "duration": duration,
        "clock": format_clock(position),
        "duration_clock": format_clock(duration),
        "timecode": abs_tc,
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
        "now": {
            "primary": _now_for_lanes(song, position, primary_lanes, lanes),
            "secondary": _now_for_lanes(song, position, secondary_lanes, lanes),
        },
    }


def timecode_to_abs_seconds(timecode: str, fps: float) -> float:
    from cueplayer.timecode.smpte import timecode_to_seconds

    return float(timecode_to_seconds(timecode, fps))

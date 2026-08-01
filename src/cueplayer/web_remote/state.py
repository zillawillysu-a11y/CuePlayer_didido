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

    def output_timecode_state(self, position_seconds: float | None = None) -> Any: ...


def format_clock(seconds: float) -> str:
    """Match desktop Cue Monitor ``format_time``: ``MM:SS.mmm``."""
    total_ms = int(round(max(0.0, float(seconds)) * 1000.0))
    mins, rem_ms = divmod(total_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{mins:02d}:{secs:02d}.{ms:03d}"


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


def _now_role(song: Song, lane_index: int) -> str:
    primary, secondary = song.resolve_now_groups()
    if lane_index in primary:
        return "primary"
    if lane_index in secondary:
        return "secondary"
    return "off"


def _now_slot(
    song: Song,
    position: float,
    lane_indices: list[int],
    lanes: dict[int, MarkLane],
) -> list[dict[str, Any]]:
    """At most one active mark for a NOW card (desktop active_mark_among_lanes)."""
    mark = song.active_mark_among_lanes(lane_indices, position)
    if mark is None:
        return []
    return [mark_payload(mark, lanes.get(mark.lane_index))]


def _now_for_lanes(
    song: Song,
    position: float,
    lane_indices: list[int],
    lanes: dict[int, MarkLane],
) -> list[dict[str, Any]]:
    # Kept name for callers; behavior is single-slot like the desktop NOW cards.
    return _now_slot(song, position, lane_indices, lanes)


def _setlist_rows(project: Project, active_song_id: str) -> list[dict[str, Any]]:
    """Flat display rows: uncategorized songs, then folders + children."""
    rows: list[dict[str, Any]] = []
    for i, song in enumerate(project.songs):
        if song.category_id:
            continue
        rows.append(
            {
                "kind": "song",
                "index": i,
                "id": song.id,
                "name": song.name,
                "setlist_number": float(song.setlist_number),
                "category_id": "",
                "active": song.id == active_song_id,
            }
        )
    for category in project.setlist_categories:
        rows.append(
            {
                "kind": "folder",
                "id": category.id,
                "name": category.name,
                "collapsed": bool(category.collapsed),
            }
        )
        if category.collapsed:
            continue
        for i, song in enumerate(project.songs):
            if song.category_id != category.id:
                continue
            rows.append(
                {
                    "kind": "song",
                    "index": i,
                    "id": song.id,
                    "name": song.name,
                    "setlist_number": float(song.setlist_number),
                    "category_id": category.id,
                    "active": song.id == active_song_id,
                }
            )
    return rows


def _output_payload(project: Project, engine: _EngineView, position: float) -> dict[str, Any]:
    ao = project.audio_output
    try:
        tc_state = engine.output_timecode_state(position)
        outputs = list(getattr(tc_state, "outputs", ()) or ())
        timecode = str(getattr(tc_state, "timecode", "—") or "—")
        sending = bool(getattr(tc_state, "sending", False))
    except Exception:  # noqa: BLE001
        outputs = []
        timecode = "—"
        sending = False
        if ao.ltc_enabled:
            outputs.append("LTC")
        if ao.midi_enabled and ao.mtc_enabled:
            if ao.effective_ltc_to_mtc_translate():
                outputs.append("LTC → MTC")
            else:
                outputs.append("MTC")
        if ao.effective_midi_cue_notes():
            outputs.append("Notes")
    status = " · ".join(outputs) if outputs else "TC off"
    accent = str(getattr(project, "output_timecode_clock_color", "") or "#3dd68c")
    return {
        "timecode": timecode,
        "status": status,
        "outputs": outputs,
        "sending": sending,
        "accent": accent,
        "toggles": {
            "translate": bool(ao.ltc_to_mtc_translate),
            "note": bool(ao.midi_cue_notes_enabled),
            "mtc": bool(ao.mtc_enabled),
            "ltc": bool(ao.ltc_enabled),
        },
    }


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

    lanes = _lane_map(song)
    primary_lanes = list(song.now_primary_lanes) if song.now_lanes_configured else [1]
    secondary_lanes = list(song.now_secondary_lanes) if song.now_lanes_configured else []
    if not song.now_secondary_enabled:
        secondary_lanes = []

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
            "cue_id_enabled": bool(lane.cue_id_enabled),
            "now": _now_role(song, lane.index),
            "pause_on_mark": bool(lane.pause_on_mark),
            "prompt_note_on_mark": bool(getattr(lane, "prompt_note_on_mark", False)),
            "show_note_on_wave": bool(getattr(lane, "show_note_on_wave", False)),
            "show_cue_id_on_wave": bool(getattr(lane, "show_cue_id_on_wave", False)),
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

    position = float(engine.position)
    duration = float(engine.duration)

    playhead_cue_id = ""
    for m in cue_list_rows:
        if float(m["time_seconds"]) - 1e-9 <= position:
            playhead_cue_id = str(m["id"])
        else:
            break

    fps = float(song.fps) if song.fps > 0 else 30.0
    output = _output_payload(project, engine, position)
    # Prefer engine output TC (file LTC / MTC); fall back to song-start + position.
    if not output["outputs"] or output["timecode"] in ("—", "", None):
        output["timecode"] = seconds_to_timecode(
            timecode_to_abs_seconds(song.start_timecode, fps) + position,
            fps,
        ).format()

    playhead = str(getattr(project, "playhead_color", "") or "#3dd68c")
    waveform_color = str(getattr(project, "waveform_color", "") or "#616161")
    active_id = song.id if song_index >= 0 else ""

    return {
        "project_name": project.name,
        "playing": bool(engine.playing),
        "position": position,
        "duration": duration,
        "clock": format_clock(position),
        "duration_clock": format_clock(duration),
        "timecode": output["timecode"],
        "tc_status": output["status"],
        "tc_sending": output["sending"],
        "tc_accent": output["accent"],
        "output_toggles": output["toggles"],
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
        "setlist": _setlist_rows(project, active_id),
        # Back-compat for older remote JS.
        "songs": [
            {
                "index": i,
                "id": s.id,
                "name": s.name,
                "setlist_number": float(s.setlist_number),
                "category": "",
                "duration_seconds": float(s.duration_seconds),
                "active": i == song_index,
            }
            for i, s in enumerate(songs)
        ],
        "lanes": lane_rows,
        "marks": mark_rows,
        "cue_list": cue_list_rows,
        "now": {
            "primary": _now_for_lanes(song, position, primary_lanes, lanes),
            "secondary": _now_for_lanes(song, position, secondary_lanes, lanes),
            "secondary_enabled": bool(song.now_secondary_enabled),
            "secondary_clear_seconds": float(
                getattr(song, "now_secondary_clear_seconds", 0.5) or 0.0
            ),
            "primary_lanes": list(primary_lanes),
            "secondary_lanes": list(secondary_lanes),
            "primary_visible": bool(getattr(song, "now_primary_visible", True)),
            "secondary_visible": bool(getattr(song, "now_secondary_visible", True)),
        },
        "display": {
            "primary": bool(getattr(song, "now_primary_visible", True)),
            "secondary": bool(getattr(song, "now_secondary_visible", True)),
            "timecode": bool(getattr(project, "show_output_timecode_clock", True)),
            "toggles": bool(getattr(project, "show_output_quick_toggles", True)),
        },
    }


def build_waveform_overview(
    buffer: AudioBuffer | None,
    *,
    song_id: str,
    duration: float,
    buckets: int = 1600,
) -> dict[str, Any]:
    """Downsample peak pyramid into a fixed-width overview for the remote canvas."""
    n = max(32, min(4000, int(buckets)))
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

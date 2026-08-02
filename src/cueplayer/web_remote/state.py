"""Build JSON state snapshots for the Web Remote UI."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from cueplayer.domain.models import Mark, MarkLane, Project, Song
from cueplayer.media.audio_loader import AudioBuffer, choose_peak_level
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
        "lane_locked": bool(lane.locked) if lane is not None else False,
        "cue_id_enabled": bool(lane.cue_id_enabled) if lane is not None else False,
        "show_note_on_wave": (
            bool(getattr(lane, "show_note_on_wave", False)) if lane is not None else False
        ),
        "show_cue_id_on_wave": (
            bool(getattr(lane, "show_cue_id_on_wave", False)) if lane is not None else False
        ),
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


def _song_media_badges(
    project: Project,
    song: Song,
    *,
    ltc_channel_for_song: Any | None = None,
) -> dict[str, Any]:
    """Desktop Set List parity: V / LTC / L / R indicators."""
    show_video = bool(getattr(project, "setlist_show_video_badge", True))
    show_ltc = bool(getattr(project, "setlist_show_ltc_badge", True))
    has_video = bool(getattr(song, "video_clips", None))
    ltc_channel: int | None = None
    if show_ltc and ltc_channel_for_song is not None:
        try:
            raw = ltc_channel_for_song(song)
            if raw is not None:
                side = int(raw)
                if side in (0, 1):
                    ltc_channel = side
        except Exception:  # noqa: BLE001
            ltc_channel = None
    return {
        "has_video": bool(show_video and has_video),
        "ltc_channel": ltc_channel if show_ltc else None,
    }


def _setlist_rows(
    project: Project,
    active_song_id: str,
    *,
    ltc_channel_for_song: Any | None = None,
) -> list[dict[str, Any]]:
    """Flat display rows: uncategorized songs, then folders + children."""
    rows: list[dict[str, Any]] = []

    def _song_row(i: int, song: Song, *, category_id: str) -> dict[str, Any]:
        badges = _song_media_badges(
            project,
            song,
            ltc_channel_for_song=ltc_channel_for_song,
        )
        return {
            "kind": "song",
            "index": i,
            "id": song.id,
            "name": song.name,
            "setlist_number": float(song.setlist_number),
            "category_id": category_id,
            "active": song.id == active_song_id,
            "has_video": badges["has_video"],
            "ltc_channel": badges["ltc_channel"],
        }

    for i, song in enumerate(project.songs):
        if song.category_id:
            continue
        rows.append(_song_row(i, song, category_id=""))
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
            rows.append(_song_row(i, song, category_id=category.id))
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
    ltc_channel_for_song: Any | None = None,
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
    # Desktop parity: no LTC/MTC/Notes outputs → show em-dash, not a fake running TC.
    if not output["outputs"]:
        output["timecode"] = "—"
    elif output["timecode"] in ("—", "", None):
        output["timecode"] = seconds_to_timecode(
            timecode_to_abs_seconds(song.start_timecode, fps) + position,
            fps,
        ).format()

    playhead = str(getattr(project, "playhead_color", "") or "#3dd68c")
    waveform_color = str(getattr(project, "waveform_color", "") or "#616161")
    active_id = song.id if song_index >= 0 else ""
    loop_a = getattr(engine, "loop_a", None)
    loop_b = getattr(engine, "loop_b", None)

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
        "tc_active": bool(output["outputs"]),
        "tc_accent": output["accent"],
        "pc_muted": bool(getattr(engine, "music_muted", False)),
        "output_toggles": output["toggles"],
        "loop": {
            "a": None if loop_a is None else float(loop_a),
            "b": None if loop_b is None else float(loop_b),
            "enabled": bool(getattr(engine, "loop_enabled", False)),
        },
        "playhead_color": playhead,
        "waveform_color": waveform_color,
        "wave_label_font_px": int(getattr(project, "wave_label_font_px", 11) or 11),
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
        "setlist": _setlist_rows(
            project,
            active_id,
            ltc_channel_for_song=ltc_channel_for_song,
        ),
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
                **_song_media_badges(
                    project,
                    s,
                    ltc_channel_for_song=ltc_channel_for_song,
                ),
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


def _resample_peaks(
    mins: np.ndarray,
    maxs: np.ndarray,
    *,
    src_a: int,
    src_b: int,
    buckets: int,
    normalize: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Min/max resample a peak slice into ``buckets`` columns."""
    n = max(1, int(buckets))
    src_a = max(0, int(src_a))
    src_b = max(src_a + 1, int(src_b))
    src_n = max(1, src_b - src_a)
    # Vectorized index edges.
    edges = (np.arange(n + 1, dtype=np.float64) * src_n / n).astype(np.int64)
    edges = np.maximum.accumulate(edges)
    out_mins = np.empty(n, dtype=np.float32)
    out_maxs = np.empty(n, dtype=np.float32)
    for i in range(n):
        a = src_a + int(edges[i])
        b = src_a + max(int(edges[i]) + 1, int(edges[i + 1]))
        b = min(src_b, b)
        out_mins[i] = float(mins[a:b].min())
        out_maxs[i] = float(maxs[a:b].max())
    if normalize:
        peak = float(max(np.max(np.abs(out_mins)), np.max(np.abs(out_maxs)), 1e-6))
        scale = 1.0 / peak
        out_mins = out_mins * scale
        out_maxs = out_maxs * scale
    return out_mins, out_maxs


def _minmax_from_mono(mono: np.ndarray, buckets: int) -> tuple[np.ndarray, np.ndarray]:
    """Build min/max columns directly from display mono (high-zoom path)."""
    n = max(1, int(buckets))
    if mono.size <= 0:
        z = np.zeros(n, dtype=np.float32)
        return z, z.copy()
    if mono.size >= n * 2:
        spb = mono.size // n
        usable = spb * n
        chunk = mono[:usable].reshape(n, spb)
        return chunk.min(axis=1).astype(np.float32), chunk.max(axis=1).astype(np.float32)

    # Sparse / near sample-per-bucket: scatter samples into columns.
    out_mins = np.full(n, np.inf, dtype=np.float32)
    out_maxs = np.full(n, -np.inf, dtype=np.float32)
    idx = np.minimum(n - 1, (np.arange(mono.size) * n) // max(1, mono.size))
    for i, sample in enumerate(mono):
        j = int(idx[i])
        v = float(sample)
        if v < out_mins[j]:
            out_mins[j] = v
        if v > out_maxs[j]:
            out_maxs[j] = v
    empty = ~np.isfinite(out_mins)
    out_mins[empty] = 0.0
    out_maxs[empty] = 0.0
    return out_mins, out_maxs


def build_waveform_overview(
    buffer: AudioBuffer | None,
    *,
    song_id: str,
    duration: float,
    buckets: int = 3200,
) -> dict[str, Any]:
    """Downsample peak pyramid into a full-song overview for the remote canvas."""
    n = max(32, min(8000, int(buckets)))
    empty = {
        "ok": True,
        "song_id": song_id,
        "duration": float(max(0.1, duration)),
        "start": 0.0,
        "end": float(max(0.1, duration)),
        "buckets": n,
        "mins": [0.0] * n,
        "maxs": [0.0] * n,
        "ready": False,
        "detail": False,
        "source": "empty",
    }
    if buffer is None or not buffer.peak_levels:
        return empty

    dur = float(buffer.duration_seconds) if buffer.frames > 0 else float(duration)
    dur = float(max(0.1, dur))
    sr = max(1, int(getattr(buffer, "sample_rate", 48000) or 48000))
    samples_per_pixel = (
        float(buffer.frames) / float(n) if buffer.frames > 0 else float(sr * dur) / float(n)
    )
    level = choose_peak_level(buffer.peak_levels, samples_per_pixel) or buffer.peak_levels[-1]
    mins = np.asarray(level.mins, dtype=np.float32)
    maxs = np.asarray(level.maxs, dtype=np.float32)
    if mins.size == 0:
        return empty

    # Overview may normalize once so quiet songs still fill the lane.
    out_mins, out_maxs = _resample_peaks(
        mins, maxs, src_a=0, src_b=mins.size, buckets=n, normalize=True
    )
    return {
        "ok": True,
        "song_id": song_id,
        "duration": dur,
        "start": 0.0,
        "end": dur,
        "buckets": n,
        "mins": [round(float(v), 5) for v in out_mins.tolist()],
        "maxs": [round(float(v), 5) for v in out_maxs.tolist()],
        "ready": True,
        "detail": False,
        "source": "overview",
    }


def build_waveform_window(
    buffer: AudioBuffer | None,
    *,
    song_id: str,
    duration: float,
    start: float,
    end: float,
    buckets: int = 4000,
) -> dict[str, Any]:
    """High-resolution peaks for a zoomed time window (marking accuracy)."""
    n = max(128, min(12000, int(buckets)))
    dur = float(max(0.1, duration))
    if buffer is not None and buffer.frames > 0:
        dur = float(max(0.1, buffer.duration_seconds))
    t0 = float(max(0.0, min(dur, start)))
    t1 = float(max(t0 + 0.01, min(dur, end)))
    empty = {
        "ok": True,
        "song_id": song_id,
        "duration": dur,
        "start": t0,
        "end": t1,
        "buckets": n,
        "mins": [0.0] * n,
        "maxs": [0.0] * n,
        "ready": False,
        "detail": True,
        "source": "empty",
    }
    if buffer is None:
        return empty

    sr = max(1, int(getattr(buffer, "sample_rate", 48000) or 48000))
    samples_in_window = max(1.0, (t1 - t0) * float(sr))
    samples_per_pixel = samples_in_window / float(n)

    # Desktop uses raw mono when <= ~1.5 samples/pixel. Do the same for remote
    # marking zooms — pyramid alone is too coarse for cue placement.
    mono = getattr(buffer, "mono", None)
    use_raw = (
        mono is not None
        and getattr(mono, "size", 0) > 0
        and samples_per_pixel <= 2.5
    )
    if use_raw:
        i0 = int(max(0, min(int(mono.size), round(t0 * sr))))
        i1 = int(max(i0 + 1, min(int(mono.size), round(t1 * sr))))
        out_mins, out_maxs = _minmax_from_mono(np.asarray(mono[i0:i1], dtype=np.float32), n)
        source = "mono"
    else:
        if not buffer.peak_levels:
            return empty
        level = choose_peak_level(buffer.peak_levels, samples_per_pixel)
        if level is None:
            level = buffer.peak_levels[0]
        # Prefer a finer level when available (never coarser than needed).
        for candidate in reversed(buffer.peak_levels):
            if candidate.samples_per_bucket <= max(1.0, samples_per_pixel * 1.25):
                level = candidate
                break
        mins = np.asarray(level.mins, dtype=np.float32)
        maxs = np.asarray(level.maxs, dtype=np.float32)
        if mins.size == 0:
            return empty
        spb = max(1.0, float(level.samples_per_bucket))
        src_a = int(max(0, min(mins.size - 1, (t0 * sr) / spb)))
        src_b = int(max(src_a + 1, min(mins.size, (t1 * sr) / spb)))
        # Keep song-global normalization from the pyramid (do not re-peak).
        out_mins, out_maxs = _resample_peaks(
            mins, maxs, src_a=src_a, src_b=src_b, buckets=n, normalize=False
        )
        source = f"peaks:{level.samples_per_bucket}"

    return {
        "ok": True,
        "song_id": song_id,
        "duration": dur,
        "start": t0,
        "end": t1,
        "buckets": n,
        "mins": [round(float(v), 5) for v in out_mins.tolist()],
        "maxs": [round(float(v), 5) for v in out_maxs.tolist()],
        "ready": True,
        "detail": True,
        "source": source,
        "samples_per_pixel": round(float(samples_per_pixel), 4),
    }


def timecode_to_abs_seconds(timecode: str, fps: float) -> float:
    from cueplayer.timecode.smpte import timecode_to_seconds

    return float(timecode_to_seconds(timecode, fps))


# LAN monitor stream for Safari / iPad Listen (no LTC):
# main music when present; otherwise video-clip embedded audio.
MONITOR_SAMPLE_RATE = 24000
MONITOR_MAX_SECONDS = 1.0


def music_mono_samples(
    buffer: AudioBuffer,
    *,
    exclude_channel: int | None = None,
) -> np.ndarray:
    """Raw float32 mono from music channels (LTC stripped). Not peak-normalized."""
    samples = np.asarray(buffer.samples, dtype=np.float32)
    if samples.size == 0:
        return np.zeros(0, dtype=np.float32)
    if samples.ndim == 1:
        return samples
    if samples.shape[1] <= 1:
        return samples[:, 0]
    keep = list(range(int(samples.shape[1])))
    if exclude_channel is not None:
        ch = int(exclude_channel)
        if 0 <= ch < samples.shape[1]:
            keep = [i for i in keep if i != ch]
    if not keep:
        return samples.mean(axis=1).astype(np.float32)
    if len(keep) == 1:
        return samples[:, keep[0]].astype(np.float32)
    return samples[:, keep].mean(axis=1).astype(np.float32)


def _to_out_mono(
    samples: np.ndarray | None,
    *,
    src_rate: int,
    out_rate: int,
    out_frames: int,
) -> np.ndarray:
    """Resample / pad / trim float audio to mono length ``out_frames`` at ``out_rate``."""
    from cueplayer.playback.resample import resample_linear

    n = max(1, int(out_frames))
    if samples is None:
        return np.zeros(n, dtype=np.float32)
    arr = np.asarray(samples, dtype=np.float32)
    if arr.size == 0:
        return np.zeros(n, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr.mean(axis=1).astype(np.float32)
    else:
        arr = arr.reshape(-1)
    sr = max(1, int(src_rate))
    orate = max(1, int(out_rate))
    if abs(float(sr) - float(orate)) > 0.5:
        arr = resample_linear(arr, float(sr), float(orate))
    if arr.size < n:
        arr = np.concatenate([arr, np.zeros(n - arr.size, dtype=np.float32)])
    elif arr.size > n:
        arr = arr[:n]
    return np.asarray(arr, dtype=np.float32)


def mix_listen_mono(
    *,
    music_mono: np.ndarray | None,
    music_rate: int,
    video_stereo: np.ndarray | None,
    video_rate: int,
    out_rate: int,
    out_frames: int,
) -> np.ndarray:
    """Resample beds to mono float32 for Web Remote Listen.

    Callers choose the source: music-only when a main file exists, or
    video-only for pure-video songs. Passing both mixes them (tests).
    """
    music = _to_out_mono(
        music_mono, src_rate=music_rate, out_rate=out_rate, out_frames=out_frames
    )
    video = _to_out_mono(
        video_stereo, src_rate=video_rate, out_rate=out_rate, out_frames=out_frames
    )
    return np.clip(music + video, -1.0, 1.0).astype(np.float32, copy=False)


def pcm16_le_to_wav(pcm: bytes, *, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap little-endian int16 PCM in a minimal mono/stereo WAV container."""
    import struct

    sr = max(1, int(sample_rate))
    ch = max(1, int(channels))
    data = bytes(pcm or b"")
    byte_rate = sr * ch * 2
    block_align = ch * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        1,
        ch,
        sr,
        byte_rate,
        block_align,
        16,
        b"data",
        len(data),
    )
    return header + data


def build_monitor_pcm(
    buffer: AudioBuffer | None,
    *,
    song_id: str,
    position: float,
    playing: bool,
    duration: float,
    start: float | None = None,
    seconds: float = 0.35,
    out_rate: int = MONITOR_SAMPLE_RATE,
    exclude_channel: int | None = None,
    as_wav: bool = False,
) -> tuple[dict[str, Any], bytes]:
    """
    Slice music-only mono PCM for the Web Remote listen stream.

    Returns ``(meta, body)`` where body is little-endian int16 mono at
    ``out_rate`` (default 24 kHz), or a WAV file when ``as_wav`` is True.
    Intentionally lossy / low-rate — listen-along on LAN, not cue-critical.
    """
    from cueplayer.playback.resample import resample_linear

    t0 = float(position if start is None else start)
    if not np.isfinite(t0) or t0 < 0.0:
        t0 = 0.0
    want = float(seconds)
    if not np.isfinite(want) or want <= 0.0:
        want = 0.35
    want = min(float(MONITOR_MAX_SECONDS), max(0.05, want))
    out_sr = int(out_rate) if out_rate and int(out_rate) > 0 else MONITOR_SAMPLE_RATE
    out_sr = max(8000, min(48000, out_sr))
    dur = max(0.0, float(duration))

    meta: dict[str, Any] = {
        "ok": True,
        "song_id": str(song_id),
        "playing": bool(playing),
        "position": float(position),
        "duration": dur,
        "start": t0,
        "seconds": 0.0,
        "sample_rate": out_sr,
        "channels": 1,
        "format": "wav" if as_wav else "s16le",
        "ready": False,
        "frames": 0,
    }
    if buffer is None or int(getattr(buffer, "frames", 0) or 0) <= 0:
        body = pcm16_le_to_wav(b"", sample_rate=out_sr, channels=1) if as_wav else b""
        return meta, body

    src_sr = float(getattr(buffer, "sample_rate", 0) or 0)
    if src_sr <= 0:
        body = pcm16_le_to_wav(b"", sample_rate=out_sr, channels=1) if as_wav else b""
        return meta, body
    mono = music_mono_samples(buffer, exclude_channel=exclude_channel)
    if mono.size == 0:
        body = pcm16_le_to_wav(b"", sample_rate=out_sr, channels=1) if as_wav else b""
        return meta, body

    # Clamp to available audio; pad short tails with silence so the client
    # can keep a steady schedule near song end.
    i0 = int(max(0, min(mono.size, round(t0 * src_sr))))
    need = int(max(1, round(want * src_sr)))
    i1 = min(mono.size, i0 + need)
    chunk = mono[i0:i1]
    if chunk.size < need:
        pad = np.zeros(need - chunk.size, dtype=np.float32)
        chunk = np.concatenate([chunk, pad]) if chunk.size else pad
    if abs(src_sr - float(out_sr)) > 0.5:
        chunk = resample_linear(chunk, src_sr, float(out_sr))
    # Soft clip then quantize.
    chunk = np.clip(chunk, -1.0, 1.0).astype(np.float32, copy=False)
    pcm = (chunk * 32767.0).astype(np.int16)
    raw = pcm.tobytes(order="C")
    actual = float(pcm.size) / float(out_sr) if out_sr else 0.0
    meta.update(
        {
            "ready": True,
            "seconds": actual,
            "frames": int(pcm.size),
            "start": float(i0) / src_sr,
            "format": "wav" if as_wav else "s16le",
        }
    )
    if as_wav:
        return meta, pcm16_le_to_wav(raw, sample_rate=out_sr, channels=1)
    return meta, raw

"""Build a SongExportPlan from a CuePlayer Song."""

from __future__ import annotations

from cueplayer.domain.models import Song
from cueplayer.exporters.common import (
    ConsoleFamily,
    ExportButtonLane,
    ExportCue,
    ExportMode,
    MaExportProfile,
    SongExportPlan,
    parse_page_executor,
    sanitize_ma_name,
)


def timecode_to_seconds(timecode: str, fps: float) -> float:
    """Convert HH:MM:SS:FF (or H:MM:SS:FF) to absolute seconds."""
    raw = timecode.strip().replace(";", ":")
    parts = raw.split(":")
    if len(parts) != 4:
        return 0.0
    try:
        hours, minutes, seconds, frames = (int(p) for p in parts)
    except ValueError:
        return 0.0
    rate = fps if fps > 0 else 30.0
    return hours * 3600.0 + minutes * 60.0 + seconds + frames / rate


def _song_ascii_base(song: Song) -> str:
    if song.ma_export_name and song.ma_export_name.strip():
        return sanitize_ma_name(song.ma_export_name, fallback="Song")
    return sanitize_ma_name(song.name, fallback="Song")


def build_export_plan(
    song: Song,
    *,
    console: ConsoleFamily,
    export_mode: ExportMode = "full",
    sequence_pool_start: int = 1,
    timecode_pool: int = 1,
    main_executor: str = "1.101",
    button_executor_start: str = "1.201",
    timecode_slot: int = 1,
    ltc_latency_compensation_seconds: float = 0.0,
    data_pool: str = "Default",
    main_sequence_name: str | None = None,
    button_sequence_name: str | None = None,
    timecode_name: str | None = None,
    start_offset_seconds: float | None = None,
    fps: float | None = None,
    button_allocations: list[dict] | None = None,
) -> SongExportPlan:
    """
    Map the current song's Main / Button marks into an MA export plan.

    Main lane marks → ExportCue (Go+ destination cues).
    export_enabled top_button lanes → one Sequence + executor each.
    """
    rate = float(fps) if fps is not None else float(song.fps or 30.0)
    offset = (
        float(start_offset_seconds)
        if start_offset_seconds is not None
        else timecode_to_seconds(song.start_timecode or "01:00:00:00", rate)
    )
    base = _song_ascii_base(song)
    file_base = base.replace(" ", "_")

    id_lanes = {lane.index for lane in song.mark_lanes if lane.cue_id_enabled}
    # Timecode events must stay in time order; Cue numbers come from Cue ID.
    from cueplayer.domain.main_cue_id import mark_time_sort_key

    main_marks = sorted(
        (m for m in song.marks if m.lane_index in id_lanes),
        key=mark_time_sort_key,
    )
    main_cues: list[ExportCue] = []
    for i, mark in enumerate(main_marks, start=1):
        display = (mark.display_name or "").strip() or f"Cue {i}"
        raw_id = (mark.main_cue_id or "").strip()
        if raw_id:
            try:
                cue_number = float(raw_id)
            except ValueError:
                cue_number = float(i)
        else:
            cue_number = float(i)
        if cue_number <= 0:
            cue_number = float(i)
        main_cues.append(
            ExportCue(
                cue_number=cue_number,
                display_name=display,
                ma_export_name=mark.ma_export_name,
                time_seconds=float(mark.time_seconds),
            )
        )

    page, exec_start = parse_page_executor(button_executor_start)
    alloc_by_lane: dict[int, dict] = {}
    if button_allocations:
        for item in button_allocations:
            alloc_by_lane[int(item["lane_index"])] = item

    button_lanes: list[ExportButtonLane] = []
    button_i = 0
    for lane in sorted(song.mark_lanes, key=lambda item: item.index):
        if lane.cue_id_enabled or not lane.export_enabled:
            continue
        times = sorted(
            m.time_seconds for m in song.marks if m.lane_index == lane.index
        )
        if not times:
            continue
        alloc = alloc_by_lane.get(lane.index)
        if alloc is not None:
            executor = str(alloc.get("executor") or f"{page}.{exec_start + button_i}")
            seq_pool = int(alloc.get("sequence_pool") or (sequence_pool_start + 1 + button_i))
        else:
            executor = f"{page}.{exec_start + button_i}"
            seq_pool = int(sequence_pool_start) + 1 + button_i
        lane_slug = sanitize_ma_name(lane.name, fallback=f"Button{lane.index}")
        seq_name = f"{base}_{lane_slug}"
        file_stem = f"{file_base}_{lane_slug.replace(' ', '_')}"
        button_lanes.append(
            ExportButtonLane(
                lane_index=lane.index,
                display_name=lane.name,
                executor=executor,
                mark_times_seconds=[float(t) for t in times],
                sequence_pool=seq_pool,
                sequence_name=seq_name,
                sequence_file=f"{file_stem}.xml",
            )
        )
        button_i += 1

    first_button_name = (
        button_lanes[0].sequence_name
        if button_lanes
        else (button_sequence_name or f"{base}_Button")
    )
    first_button_file = (
        button_lanes[0].sequence_file if button_lanes else f"{file_base}_button.xml"
    )

    profile = MaExportProfile(
        console=console,
        sequence_pool_start=int(sequence_pool_start),
        timecode_pool=int(timecode_pool),
        page=page,
        page_name=base,
        main_executor=main_executor.strip() or "1.101",
        timecode_slot=int(timecode_slot),
        fps=rate,
        start_offset_seconds=offset,
        ltc_latency_compensation_seconds=float(ltc_latency_compensation_seconds),
        data_pool=data_pool.strip() or "Default",
        export_mode=export_mode,
        main_sequence_name=main_sequence_name or f"{base}_Main",
        button_sequence_name=first_button_name,
        timecode_name=timecode_name or f"{base}_TC",
        main_sequence_file=f"{file_base}_main.xml",
        button_sequence_file=first_button_file,
        timecode_file=f"{file_base}_timecode.xml",
    )
    return SongExportPlan(
        song_name=base,
        profile=profile,
        main_cues=main_cues,
        button_lanes=button_lanes,
    )


def plan_summary_text(plan: SongExportPlan) -> str:
    main_n = len(plan.main_cues)
    button_n = len(plan.button_lanes)
    button_marks = sum(len(lane.mark_times_seconds) for lane in plan.button_lanes)
    return (
        f"{plan.profile.console.upper()} · {plan.profile.export_mode} · "
        f"Main cues {main_n} · Button lanes {button_n}（{button_marks} tops） · "
        f"FPS {plan.profile.fps:g} · offset {plan.profile.start_offset_seconds:.3f}s"
    )

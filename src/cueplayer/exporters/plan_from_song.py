"""Build a SongExportPlan from a CuePlayer Song."""

from __future__ import annotations

from cueplayer.domain.models import Song
from cueplayer.domain.ltc_clips import (
    clip_at_position,
    ltc_clip_tc_range,
    ltc_timecode_at,
    sorted_ltc_clips,
    validate_ltc_clips,
)
from cueplayer.exporters.common import (
    ConsoleFamily,
    ExportButtonLane,
    ExportCue,
    ExportMode,
    MaExportProfile,
    SongExportPlan,
    format_ma_cue_number,
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
    include_main: bool = True,
    included_button_lane_indices: set[int] | None = None,
    export_base_name: str | None = None,
) -> SongExportPlan:
    """
    Map the current song's Main / Button marks into an MA export plan.

    Main lane marks → ExportCue (Go+ destination cues).
    export_enabled top_button lanes → one Sequence + executor each.
    """
    rate = float(fps) if fps is not None else float(song.fps or 30.0)
    clip_mode = song.ltc_source_mode == "clip_generator"
    offset = (
        float(start_offset_seconds)
        if start_offset_seconds is not None
        else timecode_to_seconds(song.start_timecode or "01:00:00:00", rate)
    )
    if clip_mode:
        # Clip mappings are discontinuous, so their absolute mapped TC is
        # baked into each event inside the song's single Timecode object.
        offset = 0.0
    base = (
        sanitize_ma_name(export_base_name, fallback="Song")
        if export_base_name is not None
        else _song_ascii_base(song)
    )
    file_base = base.replace(" ", "_")

    id_lanes = {lane.index for lane in song.mark_lanes if lane.cue_id_enabled}
    # Timecode events must stay in time order; Cue numbers come from Cue ID.
    from cueplayer.domain.main_cue_id import mark_time_sort_key

    main_marks = sorted(
        (m for m in song.marks if include_main and m.lane_index in id_lanes),
        key=mark_time_sort_key,
    )
    main_cues: list[ExportCue] = []
    warnings: list[str] = []
    mapped_events: list[tuple[str, int]] = []
    warning_song = song.name.strip() or base

    def mapped_event(mark, *, mark_label: str) -> tuple[bool, float | None]:
        if not clip_mode:
            return True, None
        clip = clip_at_position(song.ltc_clips, float(mark.time_seconds))
        tc = ltc_timecode_at(song.ltc_clips, rate, float(mark.time_seconds))
        if clip is None or tc is None:
            warnings.append(
                f"Song {warning_song}: out-of-clip Mark {mark_label} at "
                f"{float(mark.time_seconds):.3f}s; Sequence Cue exported, "
                "Timecode Event omitted"
            )
            return False, None
        frame = tc.total_frames(rate)
        mapped_events.append((mark_label, frame))
        return True, frame / rate
    for i, mark in enumerate(main_marks, start=1):
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
        # Never invent "Cue {index}" — that drifts from Cue ID when fractions
        # exist (14, 14.1 → fake Cue 15) and MA Store labels break Timecode links.
        display = (mark.display_name or "").strip()
        if not display:
            display = f"Cue {format_ma_cue_number(cue_number)}"
        emit_event, mapped_seconds = mapped_event(
            mark, mark_label=f"Main Cue {format_ma_cue_number(cue_number)}"
        )
        main_cues.append(
            ExportCue(
                cue_number=cue_number,
                display_name=display,
                ma_export_name=mark.ma_export_name,
                time_seconds=float(mark.time_seconds),
                emit_timecode_event=emit_event,
                timecode_event_seconds=mapped_seconds,
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
        if included_button_lane_indices is not None and lane.index not in included_button_lane_indices:
            continue
        lane_marks = sorted(
            (m for m in song.marks if m.lane_index == lane.index),
            key=lambda mark: float(mark.time_seconds),
        )
        if not lane_marks:
            continue
        times = [float(mark.time_seconds) for mark in lane_marks]
        mapped_times: list[float] | None = [] if clip_mode else None
        if clip_mode:
            for mark_index, mark in enumerate(lane_marks, start=1):
                emit_event, mapped_seconds = mapped_event(
                    mark, mark_label=f"{lane.name} #{mark_index}"
                )
                if emit_event and mapped_seconds is not None:
                    mapped_times.append(mapped_seconds)
        alloc = alloc_by_lane.get(lane.index)
        if alloc is not None:
            executor = str(alloc.get("executor") or f"{page}.{exec_start + button_i}")
            seq_pool = int(alloc.get("sequence_pool") or (sequence_pool_start + int(include_main) + button_i))
        else:
            executor = f"{page}.{exec_start + button_i}"
            seq_pool = int(sequence_pool_start) + int(include_main) + button_i
        lane_slug = sanitize_ma_name(lane.name, fallback=f"Button{lane.index}")
        # Sequence labels stay short and match the user-facing Mark/Button
        # name. The XML filename keeps the song prefix below, preventing file
        # collisions when different songs both have a "Mark 2".
        seq_name = lane_slug
        file_stem = f"{file_base}_{lane_slug.replace(' ', '_')}"
        button_lanes.append(
            ExportButtonLane(
                lane_index=lane.index,
                display_name=lane.name,
                executor=executor,
                mark_times_seconds=[float(t) for t in times],
                timecode_event_times_seconds=mapped_times,
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

    if clip_mode:
        errors, clip_warnings = validate_ltc_clips(
            song.ltc_clips, rate, song.duration_seconds
        )
        warnings.extend(
            f"Song {warning_song}: LTC clip validation error: {text}"
            for text in errors
        )
        warnings.extend(
            f"Song {warning_song}: LTC clip validation warning: {text}"
            for text in clip_warnings
        )

        ordered = sorted_ltc_clips(song.ltc_clips)
        for earlier_index, earlier in enumerate(ordered):
            for later in ordered[earlier_index + 1 :]:
                a_range = ltc_clip_tc_range(earlier, rate)
                b_range = ltc_clip_tc_range(later, rate)
                if a_range is None or b_range is None:
                    continue
                if b_range.start_frames < a_range.start_frames:
                    warnings.append(
                        f"Song {warning_song}: backward TC range between Clip "
                        f"{earlier.id[:8]} ({a_range.start_tc.format()}-"
                        f"{a_range.end_tc.format()}) and Clip {later.id[:8]} "
                        f"({b_range.start_tc.format()}-{b_range.end_tc.format()})"
                    )
                elif b_range.start_frames < a_range.end_frames:
                    warnings.append(
                        f"Song {warning_song}: overlapping TC ranges between Clip "
                        f"{earlier.id[:8]} ({a_range.start_tc.format()}-"
                        f"{a_range.end_tc.format()}) and Clip {later.id[:8]} "
                        f"({b_range.start_tc.format()}-{b_range.end_tc.format()})"
                    )

        event_labels: dict[int, list[str]] = {}
        for label, frame in mapped_events:
            event_labels.setdefault(frame, []).append(label)
        for frame, labels in sorted(event_labels.items()):
            if len(labels) <= 1:
                continue
            tc_seconds = frame / rate
            hours = int(tc_seconds // 3600)
            minutes = int((tc_seconds % 3600) // 60)
            seconds = int(tc_seconds % 60)
            frames = frame % int(round(rate))
            tc_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"
            warnings.append(
                f"Song {warning_song}: duplicate resulting Timecode Event at "
                f"{tc_text}: " + ", ".join(labels)
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
        include_main=include_main,
    )
    return SongExportPlan(
        song_name=base,
        profile=profile,
        main_cues=main_cues,
        button_lanes=button_lanes,
        duration_seconds=max(0.0, float(song.duration_seconds or 0.0)),
        song_bpm=float(song.bpm or 120.0),
        song_id=song.id,
        warnings=warnings,
    )


def plan_summary_text(plan: SongExportPlan) -> str:
    main_n = len(plan.main_cues)
    button_n = len(plan.button_lanes)
    button_marks = sum(len(lane.mark_times_seconds) for lane in plan.button_lanes)
    return (
        f"{plan.profile.console.upper()} · {plan.profile.export_mode} · "
        f"Main cues {main_n} · Button lanes {button_n}（{button_marks} tops） · "
        f"FPS {plan.profile.fps:g} · offset {plan.profile.start_offset_seconds:.3f}s · "
        f"warnings {len(plan.warnings)}"
    )

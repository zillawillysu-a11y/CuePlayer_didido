"""Read-only MA Preflight context built from Project / Song (no exporters)."""

from __future__ import annotations

from dataclasses import dataclass

from cueplayer.domain.models import Project, Song
from cueplayer.domain.validation.ma_names import format_executor, parse_executor_ref


@dataclass(frozen=True, slots=True)
class PreflightCueView:
    mark_id: str
    song_id: str
    lane_index: int
    time_seconds: float
    display_name: str
    ma_export_name: str
    export_enabled: bool
    main_cue_id: str = ""


@dataclass(frozen=True, slots=True)
class PreflightSequenceView:
    """One intended Sequence (main or top-button lane) for a song."""

    key: str
    song_id: str
    kind: str  # main | button
    label: str
    cue_count: int
    executor: str
    lane_index: int | None = None


@dataclass(frozen=True, slots=True)
class PreflightSongView:
    id: str
    name: str
    ma_export_name: str
    export_included: bool
    variant_count: int
    note: str
    bpm: float | None
    sequences: tuple[PreflightSequenceView, ...]
    cues: tuple[PreflightCueView, ...]


@dataclass(frozen=True, slots=True)
class MaPreflightContext:
    """Immutable snapshot for MA Preflight rules — never mutated by rules."""

    songs: tuple[PreflightSongView, ...]
    console: str
    export_mode: str
    sequence_pool_start: int
    main_executor: str
    button_executor_start: str
    page_per_song: bool
    project_name: str = ""

    @property
    def included_songs(self) -> tuple[PreflightSongView, ...]:
        return tuple(s for s in self.songs if s.export_included)

    @property
    def total_songs(self) -> int:
        return len(self.songs)

    @property
    def total_included_songs(self) -> int:
        return len(self.included_songs)

    @property
    def total_sequences(self) -> int:
        return sum(len(s.sequences) for s in self.included_songs)

    @property
    def total_executors(self) -> int:
        refs = {
            seq.executor
            for song in self.included_songs
            for seq in song.sequences
            if seq.executor.strip()
        }
        return len(refs)

    @property
    def total_variants(self) -> int:
        return sum(s.variant_count for s in self.songs)


def _song_sequence_label(song: Song) -> str:
    if song.ma_export_name and str(song.ma_export_name).strip():
        return str(song.ma_export_name).strip()
    return str(song.name or "").strip() or "Song"


def _lane_sequence_label(song: Song, lane_index: int, lane_name: str) -> str:
    base = _song_sequence_label(song)
    slug = (lane_name or f"Button{lane_index}").strip()
    return f"{base}_{slug}"


def _song_page(index: int, *, page_per_song: bool, main_executor: str) -> int:
    parsed = parse_executor_ref(main_executor)
    base_page = parsed[0] if parsed else 1
    if not page_per_song:
        return base_page
    return base_page + index


def build_ma_preflight_context(project: Project) -> MaPreflightContext:
    """Snapshot Project into a frozen preflight context (read-only)."""
    settings = project.ma_export
    selected = set(settings.export_song_ids or [])
    songs_out: list[PreflightSongView] = []

    for song_index, song in enumerate(project.songs):
        included = True if not selected else song.id in selected
        page = _song_page(
            song_index,
            page_per_song=bool(settings.page_per_song),
            main_executor=settings.main_executor,
        )
        main_parsed = parse_executor_ref(settings.main_executor)
        button_parsed = parse_executor_ref(settings.button_executor_start)
        main_exec_num = main_parsed[1] if main_parsed else 0
        button_exec_num = button_parsed[1] if button_parsed else 0

        sequences: list[PreflightSequenceView] = []
        cues: list[PreflightCueView] = []

        lane_by_index = {lane.index: lane for lane in song.mark_lanes}
        main_marks = [
            m
            for m in song.marks
            if lane_by_index.get(m.lane_index) is not None
            and lane_by_index[m.lane_index].lane_type == "main"
            and lane_by_index[m.lane_index].export_enabled
        ]
        sequences.append(
            PreflightSequenceView(
                key=f"{song.id}:main",
                song_id=song.id,
                kind="main",
                label=_song_sequence_label(song),
                cue_count=len(main_marks),
                executor=format_executor(page, main_exec_num) if main_exec_num else str(
                    settings.main_executor or ""
                ),
                lane_index=1,
            )
        )

        button_offset = 0
        for lane in sorted(song.mark_lanes, key=lambda L: L.index):
            if lane.lane_type != "top_button" or not lane.export_enabled:
                continue
            lane_marks = [m for m in song.marks if m.lane_index == lane.index]
            exec_num = button_exec_num + button_offset if button_exec_num else 0
            button_offset += 1
            sequences.append(
                PreflightSequenceView(
                    key=f"{song.id}:button:{lane.index}",
                    song_id=song.id,
                    kind="button",
                    label=_lane_sequence_label(song, lane.index, lane.name),
                    cue_count=len(lane_marks),
                    executor=format_executor(page, exec_num) if exec_num else str(
                        settings.button_executor_start or ""
                    ),
                    lane_index=lane.index,
                )
            )

        for mark in song.marks:
            lane = lane_by_index.get(mark.lane_index)
            cues.append(
                PreflightCueView(
                    mark_id=mark.id,
                    song_id=song.id,
                    lane_index=mark.lane_index,
                    time_seconds=float(mark.time_seconds),
                    display_name=str(mark.display_name or ""),
                    ma_export_name=str(mark.ma_export_name or ""),
                    export_enabled=bool(lane.export_enabled) if lane is not None else False,
                    main_cue_id=str(getattr(mark, "main_cue_id", "") or ""),
                )
            )

        songs_out.append(
            PreflightSongView(
                id=song.id,
                name=str(song.name or ""),
                ma_export_name=str(song.ma_export_name or ""),
                export_included=included,
                variant_count=len(song.variants),
                note=str(song.note or ""),
                bpm=song.bpm,
                sequences=tuple(sequences),
                cues=tuple(cues),
            )
        )

    return MaPreflightContext(
        songs=tuple(songs_out),
        console=str(settings.console or "ma2"),
        export_mode=str(settings.export_mode or "full"),
        sequence_pool_start=int(settings.sequence_pool_start or 1),
        main_executor=str(settings.main_executor or ""),
        button_executor_start=str(settings.button_executor_start or ""),
        page_per_song=bool(settings.page_per_song),
        project_name=str(project.name or ""),
    )

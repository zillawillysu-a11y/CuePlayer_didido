"""Show-wide Sequence / Fader patch planning for multi-song MA export."""

from __future__ import annotations

from dataclasses import dataclass

from cueplayer.domain.models import MaExportSettings, Song
from cueplayer.exporters.common import parse_page_executor, sanitize_ma_name
from cueplayer.exporters.plan_from_song import build_export_plan, timecode_to_seconds


@dataclass(frozen=True)
class ButtonPatch:
    lane_index: int
    name: str
    sequence: int
    executor: str
    mark_count: int
    sequence_name: str  # e.g. Song_Hit


@dataclass(frozen=True)
class SongPatchSlot:
    """One song's place in the show Sequence chain."""

    song_index: int
    song: Song
    ma_base: str
    page: int
    main_sequence: int
    main_sequence_name: str  # e.g. Song_Main
    buttons: tuple[ButtonPatch, ...]
    timecode_pool: int
    main_executor: str
    main_cue_count: int

    @property
    def button_lane_count(self) -> int:
        return len(self.buttons)

    @property
    def button_mark_count(self) -> int:
        return sum(b.mark_count for b in self.buttons)

    @property
    def button_executor_start(self) -> str:
        if self.buttons:
            return self.buttons[0].executor
        return f"{self.page}.201"

    @property
    def sequence_span(self) -> int:
        """How many Sequence pool slots this song consumes."""
        return 1 + len(self.buttons)

    @property
    def display_name(self) -> str:
        """English short name used in MA (fallback to sanitized Chinese)."""
        return self.ma_base


def _button_lanes_with_marks(song: Song) -> list[tuple[int, str, int]]:
    """Return (lane_index, name, mark_count) for exportable button lanes that have marks."""
    out: list[tuple[int, str, int]] = []
    for lane in sorted(song.mark_lanes, key=lambda item: item.index):
        if lane.lane_type != "top_button" or not lane.export_enabled:
            continue
        count = sum(1 for m in song.marks if m.lane_index == lane.index)
        if count <= 0:
            continue
        out.append((lane.index, lane.name, count))
    return out


def _main_cue_count(song: Song) -> int:
    main = next((lane for lane in song.mark_lanes if lane.lane_type == "main"), None)
    idx = main.index if main is not None else 1
    return sum(1 for m in song.marks if m.lane_index == idx)


def format_executor(page: int, executor: int) -> str:
    return f"{page}.{executor}"


def build_show_patch(
    songs: list[Song],
    settings: MaExportSettings,
) -> list[SongPatchSlot]:
    """
    Allocate Sequence numbers in show order:

      Song1 Main → Song1 ButtonA → Song1 ButtonB → Song2 Main → …

    By default each song uses its own Page (1.201, 2.201, …), labeled with the
    song English name. Sequence names: {EN}_Main, {EN}_{MarkName}.
    """
    seq = max(1, int(settings.sequence_pool_start))
    tc = max(1, int(settings.timecode_pool_start))
    main_page0, main_exec = parse_page_executor(settings.main_executor or "1.101")
    _btn_page0, btn_exec = parse_page_executor(settings.button_executor_start or "1.201")
    page_per_song = bool(getattr(settings, "page_per_song", True))

    slots: list[SongPatchSlot] = []
    for i, song in enumerate(songs):
        page = (main_page0 + i) if page_per_song else main_page0
        base = sanitize_ma_name(song.ma_export_name or song.name, fallback="Song")
        lane_rows = _button_lanes_with_marks(song)
        buttons: list[ButtonPatch] = []
        for offset, (lane_index, name, mark_count) in enumerate(lane_rows):
            mark_slug = sanitize_ma_name(name, fallback=f"Button{lane_index}")
            buttons.append(
                ButtonPatch(
                    lane_index=lane_index,
                    name=name,
                    sequence=seq + 1 + offset,
                    executor=format_executor(page, btn_exec + offset),
                    mark_count=mark_count,
                    sequence_name=f"{base}_{mark_slug}",
                )
            )
        slots.append(
            SongPatchSlot(
                song_index=i,
                song=song,
                ma_base=base,
                page=page,
                main_sequence=seq,
                main_sequence_name=f"{base}_Main",
                buttons=tuple(buttons),
                timecode_pool=tc,
                main_executor=format_executor(page, main_exec),
                main_cue_count=_main_cue_count(song),
            )
        )
        seq += 1 + len(buttons)
        tc += 1
    return slots


def sequence_chain_labels(slots: list[SongPatchSlot]) -> list[str]:
    """Flat labels for the top chain strip."""
    labels: list[str] = []
    for slot in slots:
        labels.append(f"Seq {slot.main_sequence} {slot.main_sequence_name} ({slot.main_executor})")
        for button in slot.buttons:
            labels.append(
                f"Seq {button.sequence} {button.sequence_name} ({button.executor})"
            )
    return labels


def plans_from_show_patch(
    slots: list[SongPatchSlot],
    settings: MaExportSettings,
    *,
    fps_override: float | None = None,
):
    """Build export plans for each slot using the allocated pools / faders."""
    console = "ma3" if settings.console == "ma3" else "ma2"
    mode = "timecode_only" if settings.export_mode == "timecode_only" else "full"
    plans = []
    for slot in slots:
        fps = float(fps_override) if fps_override is not None else float(slot.song.fps or 30.0)
        offset = timecode_to_seconds(slot.song.start_timecode or "01:00:00:00", fps)
        button_alloc = [
            {
                "lane_index": b.lane_index,
                "sequence_pool": b.sequence,
                "executor": b.executor,
            }
            for b in slot.buttons
        ]
        plans.append(
            build_export_plan(
                slot.song,
                console=console,  # type: ignore[arg-type]
                export_mode=mode,  # type: ignore[arg-type]
                sequence_pool_start=slot.main_sequence,
                timecode_pool=slot.timecode_pool,
                main_executor=slot.main_executor,
                button_executor_start=slot.button_executor_start,
                timecode_slot=int(settings.timecode_slot),
                ltc_latency_compensation_seconds=float(settings.latency_ms) / 1000.0,
                data_pool=settings.data_pool.strip() or "Default",
                start_offset_seconds=offset,
                fps=fps,
                button_allocations=button_alloc,
            )
        )
    return plans

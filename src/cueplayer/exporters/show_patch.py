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
    sequence_name: str  # e.g. Mark_2


@dataclass(frozen=True)
class SongPatchSlot:
    """One song's place in the show Sequence chain."""

    song_index: int
    song: Song
    ma_base: str
    page: int
    main_sequence: int
    main_sequence_name: str  # MA2: Song; MA3: Song_Main
    buttons: tuple[ButtonPatch, ...]
    timecode_pool: int
    main_executor: str
    main_cue_count: int
    include_main: bool = True
    # Single source of truth for the remaining four Pool types (used by every
    # UI table, the CSV/TXT report, and — for View/Effects — the exporter).
    effect_start: int = 1
    group_start: int = 1
    generator_start: int = 1
    view_pool: int = 1
    song_macro_pool: int = 1

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
        return int(self.include_main) + len(self.buttons)

    @property
    def display_name(self) -> str:
        """English short name used in MA (fallback to sanitized Chinese)."""
        return self.ma_base


def _button_lanes_with_marks(song: Song, included: set[int] | None = None) -> list[tuple[int, str, int]]:
    """Return (lane_index, name, mark_count) for exportable button lanes that have marks."""
    out: list[tuple[int, str, int]] = []
    for lane in sorted(song.mark_lanes, key=lambda item: item.index):
        if lane.cue_id_enabled or not lane.export_enabled:
            continue
        if included is not None and lane.index not in included:
            continue
        count = sum(1 for m in song.marks if m.lane_index == lane.index)
        if count <= 0:
            continue
        out.append((lane.index, lane.name, count))
    return out


def _main_cue_count(song: Song, include_main: bool) -> int:
    if not include_main:
        return 0
    id_lanes = {lane.index for lane in song.mark_lanes if lane.cue_id_enabled}
    return sum(1 for m in song.marks if m.lane_index in id_lanes)


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
    song English name. Main Sequence: MA2={EN}, MA3={EN}_Main.
    """
    # "Start after scanned Pools": push every base start past the highest
    # number the last Live Scan found, so a new export cannot land on
    # existing show objects. Off = plain export from the configured starts.
    if settings.ma2_start_after_scanned:
        scanned = (
            settings.ma3_scanned_pool_max
            if settings.console == "ma3"
            else settings.ma2_scanned_pool_max
        )
    else:
        scanned = {}

    def _base(configured: int, scanned_key: str) -> int:
        floor = int(scanned.get(scanned_key, 0)) + 1 if scanned.get(scanned_key) else 1
        return max(1, int(configured), floor)

    seq = _base(settings.sequence_pool_start, "sequence")
    tc = _base(settings.timecode_pool_start, "timecode")
    effect_start_base = _base(settings.ma2_effect_pool_start, "effect")
    effect_slots = max(1, int(settings.ma2_effect_slots_per_song))
    group_start_base = _base(settings.ma2_group_pool_start, "group")
    group_slots = max(1, int(settings.ma2_group_slots_per_song))
    generator_start_base = _base(settings.ma3_generator_pool_start, "generator")
    generator_slots = max(1, int(settings.ma3_generator_slots_per_song))
    view_start_base = _base(settings.ma2_view_pool_start, "view")
    macro_start_base = _base(settings.ma2_song_macro_start, "macro")
    # Per-song pins always win, in either state. That is what lets a manual
    # edit made while "Start after scanned" is on survive switching it off
    # instead of snapping back. Ticking the toggle clears the pins once (see
    # ShowPatchPage._on_start_after_scanned_toggled) so it still repositions
    # everything; anything pinned afterwards is a deliberate manual choice.
    overrides = settings.ma2_pool_overrides or {}
    main_page0, main_exec = parse_page_executor(settings.main_executor or "1.101")
    _btn_page0, btn_exec = parse_page_executor(settings.button_executor_start or "1.201")
    # Page is a full allocation Pool too: "Start after scanned Pools" must
    # keep a new export's Pages off any Page the console already has.
    main_page0 = _base(main_page0, "page")
    page_per_song = bool(getattr(settings, "page_per_song", True))

    raw_bases = [
        sanitize_ma_name(song.ma_export_name or song.name, fallback="Song")
        for song in songs
    ]
    duplicate_bases = {
        base.casefold()
        for base in raw_bases
        if sum(candidate.casefold() == base.casefold() for candidate in raw_bases) > 1
    }
    used_bases: set[str] = set()
    slots: list[SongPatchSlot] = []
    for i, song in enumerate(songs):
        song_overrides = overrides.get(song.id) or {}
        page = (
            int(song_overrides["page"]) if "page" in song_overrides
            else ((main_page0 + i) if page_per_song else main_page0)
        )
        raw_base = raw_bases[i]
        selection = settings.export_content_by_song.get(song.id, {})
        include_main = bool(selection.get("main", True))
        raw_buttons = selection.get("buttons")
        selected_buttons = {int(value) for value in raw_buttons} if isinstance(raw_buttons, list) else None
        lane_rows = _button_lanes_with_marks(song, selected_buttons)
        # A manual override "pins" this song's own number without disturbing
        # where the running counter puts the *next* (non-overridden) song.
        main_sequence = (
            int(song_overrides["sequence"]) if "sequence" in song_overrides else seq
        )
        # Page Change selects Sequence, Timecode, Page, View and the per-song
        # Macro by one shared MA-safe name.  Duplicate song/export names would
        # therefore select an arbitrary object on MA3.  Give every colliding
        # song a stable pool-qualified name and pass it through the whole plan.
        base = (
            f"{raw_base}_S{main_sequence}"
            if raw_base.casefold() in duplicate_bases
            else raw_base
        )
        candidate = base
        suffix = 2
        while candidate.casefold() in used_bases:
            candidate = f"{base}_{suffix}"
            suffix += 1
        base = candidate
        used_bases.add(base.casefold())
        timecode_pool = (
            int(song_overrides["timecode"]) if "timecode" in song_overrides else tc
        )
        effect_start = (
            int(song_overrides["effects"])
            if "effects" in song_overrides
            else effect_start_base + i * effect_slots
        )
        group_start = (
            int(song_overrides["groups"])
            if "groups" in song_overrides
            else group_start_base + i * group_slots
        )
        generator_start = (
            int(song_overrides["generators"])
            if "generators" in song_overrides
            else generator_start_base + i * generator_slots
        )
        view_pool = (
            int(song_overrides["view"]) if "view" in song_overrides else view_start_base + i
        )
        song_macro_pool = (
            int(song_overrides["song_macro"])
            if "song_macro" in song_overrides
            else macro_start_base + i
        )
        buttons: list[ButtonPatch] = []
        for offset, (lane_index, name, mark_count) in enumerate(lane_rows):
            mark_slug = sanitize_ma_name(name, fallback=f"Button{lane_index}")
            buttons.append(
                ButtonPatch(
                    lane_index=lane_index,
                    name=name,
                    # Buttons stay relative to Main so an overridden Main
                    # sequence keeps its Buttons in the same block.
                    sequence=main_sequence + int(include_main) + offset,
                    executor=format_executor(page, btn_exec + offset),
                    mark_count=mark_count,
                    sequence_name=mark_slug,
                )
            )
        slots.append(
            SongPatchSlot(
                song_index=i,
                song=song,
                ma_base=base,
                page=page,
                main_sequence=main_sequence,
                # Bare song name for both consoles: MA3's Song Change
                # workflow (Page Change macro) selects the Main Sequence by
                # exact name match against the $song global variable
                # ("Select Sequence $"song".") — a "_Main" suffix here would
                # make that lookup never match anything on import.
                main_sequence_name=base,
                buttons=tuple(buttons),
                timecode_pool=timecode_pool,
                main_executor=format_executor(page, main_exec),
                main_cue_count=_main_cue_count(song, include_main),
                include_main=include_main,
                effect_start=effect_start,
                group_start=group_start,
                generator_start=generator_start,
                view_pool=view_pool,
                song_macro_pool=song_macro_pool,
            )
        )
        used_slots = int(include_main) + len(buttons)
        # Both consoles reserve a fixed per-song block (same as Effect/
        # Group pools below) rather than packing tightly — leaves room to
        # add marks/buttons later without renumbering every song after it.
        seq += max(used_slots, int(settings.ma2_sequence_slots_per_song or 20))
        tc += 1
    return slots


# One (start-getter, span-getter) pair per manually-overridable Pool column.
_POOL_RANGE_GETTERS: dict[str, tuple] = {
    "sequence": (
        lambda slot: slot.main_sequence,
        lambda slot, settings: max(
            int(settings.ma2_sequence_slots_per_song or 20),
            int(slot.include_main) + len(slot.buttons),
        ),
    ),
    "effects": (
        lambda slot: slot.effect_start,
        lambda slot, settings: max(1, int(settings.ma2_effect_slots_per_song)),
    ),
    "groups": (
        lambda slot: slot.group_start,
        lambda slot, settings: max(1, int(settings.ma2_group_slots_per_song)),
    ),
    "generators": (
        lambda slot: slot.generator_start,
        lambda slot, settings: max(1, int(settings.ma3_generator_slots_per_song)),
    ),
    "timecode": (lambda slot: slot.timecode_pool, lambda slot, settings: 1),
    "view": (lambda slot: slot.view_pool, lambda slot, settings: 1),
    "song_macro": (lambda slot: slot.song_macro_pool, lambda slot, settings: 1),
}


def pool_collisions(
    slots: list[SongPatchSlot], settings: MaExportSettings
) -> dict[str, set[str]]:
    """Song ids whose allocated range overlaps another song's, per Pool type.

    Any two songs sharing numbers in the same Pool type would corrupt each
    other's objects on the console, so this flags it regardless of whether
    the collision came from a manual override or a too-small slots-per-song.
    """
    collisions: dict[str, set[str]] = {pool: set() for pool in _POOL_RANGE_GETTERS}
    for pool, (start_of, span_of) in _POOL_RANGE_GETTERS.items():
        ranges = [
            (start_of(slot), start_of(slot) + span_of(slot, settings) - 1, slot.song.id)
            for slot in slots
        ]
        for a in range(len(ranges)):
            a_start, a_end, a_id = ranges[a]
            for b in range(a + 1, len(ranges)):
                b_start, b_end, b_id = ranges[b]
                if a_start <= b_end and b_start <= a_end:
                    collisions[pool].add(a_id)
                    collisions[pool].add(b_id)
    # Page is only meaningfully "collided" when each song is supposed to get
    # its own Page ("Next Page per song" on) — with it off, every song
    # deliberately shares one Page, and flagging that as a collision would
    # just be noise.
    collisions["page"] = set()
    if bool(getattr(settings, "page_per_song", True)):
        page_ranges = [(slot.page, slot.page, slot.song.id) for slot in slots]
        for a in range(len(page_ranges)):
            a_start, a_end, a_id = page_ranges[a]
            for b in range(a + 1, len(page_ranges)):
                b_start, b_end, b_id = page_ranges[b]
                if a_start <= b_end and b_start <= a_end:
                    collisions["page"].add(a_id)
                    collisions["page"].add(b_id)
    return collisions


def sequence_chain_labels(slots: list[SongPatchSlot]) -> list[str]:
    """Flat labels for the top chain strip."""
    labels: list[str] = []
    for slot in slots:
        if slot.include_main:
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
                include_main=slot.include_main,
                included_button_lane_indices={button.lane_index for button in slot.buttons},
                main_sequence_name=slot.main_sequence_name,
                # Bare name (no "_TC" suffix) on both consoles — Page
                # Change's "Select Timecode $"song"." needs an exact match
                # against the $song global variable, same reason
                # main_sequence_name dropped its "_Main" suffix above.
                timecode_name=slot.ma_base,
                export_base_name=slot.ma_base,
            )
        )
    return plans

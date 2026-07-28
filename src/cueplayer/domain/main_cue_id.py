"""Fractional Main Cue IDs for timeline marks (1, 1.1, 1.01, 1.2, 2, …)."""

from __future__ import annotations

from decimal import Decimal

from cueplayer.domain.models import Mark, Song


def _to_decimal(cue_id: str) -> Decimal:
    return Decimal(cue_id.strip())


def _format_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def between_main_cue_ids(
    left: str | None,
    right: str | None,
    *,
    avoid: set[str] | None = None,
) -> str:
    """Return a new id strictly between left and right (right None = append after left)."""
    blocked = set(avoid or ())
    if left is None and right is None:
        return "1"
    if left is None:
        assert right is not None
        right_value = _to_decimal(right)
        step = Decimal("0.1")
        while step > Decimal("0.000001"):
            candidate = right_value - step
            if candidate > 0:
                formatted = _format_decimal(candidate)
                if formatted not in blocked:
                    return formatted
            step /= 10
        raise ValueError("no room before right bound")
    left_value = _to_decimal(left)
    if right is None:
        candidate = str(int(left_value) + 1)
        if candidate not in blocked:
            return candidate
        step = Decimal("0.1")
        probe = left_value
        while step > Decimal("0.000001"):
            probe += step
            formatted = _format_decimal(probe)
            if formatted not in blocked:
                return formatted
            step /= 10
        raise ValueError("no room after left bound")

    right_value = _to_decimal(right)
    if left_value >= right_value:
        raise ValueError("left must be less than right")

    step = Decimal("0.1")
    while step > Decimal("0.000001"):
        candidate = left_value + step
        while candidate < right_value:
            formatted = _format_decimal(candidate)
            if formatted not in blocked:
                return formatted
            candidate += step
        step /= 10
    raise ValueError(f"cannot insert between {left!r} and {right!r}")


def next_main_cue_id_at_end(existing_ids: list[str]) -> str:
    """Assign the next integer id when appending a Main mark at the end."""
    if not existing_ids:
        return "1"
    max_value = max(_to_decimal(cue_id) for cue_id in existing_ids)
    return str(int(max_value) + 1)


def assign_main_cue_id_for_mark(song: Song, mark: Mark, *, force: bool = False) -> str:
    """Pick and store a Main Cue ID for one mark.

    Existing marks keep their stored id unless ``force`` is True (e.g. after a move).
    """
    main_index = song.main_lane_index()
    if main_index is None or mark.lane_index != main_index:
        mark.main_cue_id = ""
        return ""

    if mark.main_cue_id and not force:
        return mark.main_cue_id

    ordered = song.main_marks_sorted()
    idx = next(i for i, m in enumerate(ordered) if m.id == mark.id)
    others = [m for m in ordered if m.id != mark.id]
    used = {m.main_cue_id for m in others if m.main_cue_id}

    if not others:
        mark.main_cue_id = "1"
        return mark.main_cue_id

    if idx == 0:
        right = ordered[1].main_cue_id or None
        mark.main_cue_id = (
            between_main_cue_ids(None, right, avoid=used) if right else "1"
        )
        return mark.main_cue_id

    left_id = ordered[idx - 1].main_cue_id or "1"
    if idx == len(ordered) - 1:
        mark.main_cue_id = next_main_cue_id_at_end(
            [m.main_cue_id for m in others if m.main_cue_id]
        )
        return mark.main_cue_id

    right_id = ordered[idx + 1].main_cue_id
    if right_id:
        mark.main_cue_id = between_main_cue_ids(left_id, right_id, avoid=used)
    else:
        mark.main_cue_id = next_main_cue_id_at_end(
            [m.main_cue_id for m in others if m.main_cue_id]
        )
    return mark.main_cue_id


def refresh_main_cue_ids(song: Song, *, mark_ids: set[str] | None = None) -> None:
    """Reassign Main Cue IDs only for new/moved marks — never renumber untouched cues."""
    main_index = song.main_lane_index()
    if main_index is None:
        return
    if not mark_ids:
        return
    for mark_id in mark_ids:
        mark = song.mark_by_id(mark_id)
        if mark is None or mark.lane_index != main_index:
            continue
        assign_main_cue_id_for_mark(song, mark, force=True)


def migrate_main_cue_ids(song: Song) -> None:
    """Assign sequential integers to legacy main marks missing ids."""
    main_marks = song.main_marks_sorted()
    if not main_marks:
        return
    if all(mark.main_cue_id for mark in main_marks):
        return
    for index, mark in enumerate(main_marks, start=1):
        if not mark.main_cue_id:
            mark.main_cue_id = str(index)


def main_cue_id_map(song: Song) -> dict[str, str]:
    """Display map mark_id -> cue id string (main lane only)."""
    main_index = song.main_lane_index()
    if main_index is None:
        return {}
    return {
        mark.id: mark.main_cue_id
        for mark in song.marks
        if mark.lane_index == main_index and mark.main_cue_id
    }

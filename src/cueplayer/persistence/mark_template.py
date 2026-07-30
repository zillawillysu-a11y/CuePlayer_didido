"""Save / load Mark Manager lane templates (CuePoints-style type presets)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from cueplayer.domain.models import MARKER_SHAPE_LABELS, MarkLane, Song

TEMPLATE_KIND = "cueplayer.mark_template"
TEMPLATE_VERSION = 1


def clone_lanes(lanes: list[MarkLane]) -> list[MarkLane]:
    return deepcopy(lanes)


def lanes_to_dicts(lanes: list[MarkLane]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lane in sorted(lanes, key=lambda item: item.index):
        out.append(
            {
                "index": int(lane.index),
                "name": lane.name,
                "lane_type": lane.lane_type,
                "color": lane.color,
                "shortcut": lane.shortcut,
                "visible": bool(lane.visible),
                "locked": bool(lane.locked),
                "export_enabled": bool(lane.export_enabled),
                "cue_id_enabled": bool(lane.cue_id_enabled),
                "cue_list_enabled": bool(lane.cue_list_enabled),
                "midi_note_enabled": bool(getattr(lane, "midi_note_enabled", False)),
                "midi_note": int(getattr(lane, "midi_note", 0) or 0),
                "marker_shape": lane.marker_shape,
                "show_row_color": bool(getattr(lane, "show_row_color", True)),
            }
        )
    return out


def dicts_to_lanes(raw: list[Any]) -> list[MarkLane]:
    lanes: list[MarkLane] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        shape = item.get("marker_shape", "circle")
        if shape not in MARKER_SHAPE_LABELS:
            shape = "circle"
        lane_type = item.get("lane_type", "top_button")
        if lane_type not in ("main", "top_button"):
            lane_type = "top_button"
        lanes.append(
            MarkLane(
                index=int(item["index"]),
                name=str(item.get("name") or f"Mark {item['index']}"),
                lane_type=lane_type,  # type: ignore[arg-type]
                color=str(item.get("color") or "#4C8BF5"),
                shortcut=str(item.get("shortcut") or ""),
                visible=bool(item.get("visible", True)),
                locked=bool(item.get("locked", False)),
                export_enabled=bool(item.get("export_enabled", True)),
                cue_id_enabled=bool(
                    item.get(
                        "cue_id_enabled",
                        lane_type == "main",
                    )
                ),
                cue_list_enabled=bool(
                    item.get(
                        "cue_list_enabled",
                        lane_type == "main",
                    )
                ),
                midi_note_enabled=bool(item.get("midi_note_enabled", False)),
                midi_note=int(item.get("midi_note", 0) or 0),
                marker_shape=shape,  # type: ignore[arg-type]
                show_row_color=bool(item.get("show_row_color", True)),
            )
        )
    lanes.sort(key=lambda lane: lane.index)
    return lanes


def build_template(
    lanes: list[MarkLane],
    *,
    name: str = "",
    now_primary_lanes: list[int] | None = None,
    now_secondary_lanes: list[int] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": TEMPLATE_KIND,
        "version": TEMPLATE_VERSION,
        "name": name,
        "mark_lanes": lanes_to_dicts(lanes),
    }
    if now_primary_lanes is not None:
        data["now_primary_lanes"] = list(now_primary_lanes)
        data["now_lanes_configured"] = True
    if now_secondary_lanes is not None:
        data["now_secondary_lanes"] = list(now_secondary_lanes)
        data["now_lanes_configured"] = True
    return data


def save_mark_template(path: Path, template: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_mark_template(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid settings file format")
    if data.get("kind") not in (TEMPLATE_KIND, None):
        # Allow plain {mark_lanes:[...]} without kind for flexibility.
        if "mark_lanes" not in data:
            raise ValueError("Not a CuePlayer Mark settings file")
    if "mark_lanes" not in data:
        raise ValueError("Settings file is missing mark_lanes")
    return data


def apply_lanes_to_song(
    song: Song,
    lanes: list[MarkLane],
    *,
    now_primary_lanes: list[int] | None = None,
    now_secondary_lanes: list[int] | None = None,
) -> int:
    """
    Replace song mark lanes with a cloned template.

    Marks whose lane_index no longer exists are removed.
    Returns how many marks were dropped.
    """
    new_lanes = clone_lanes(lanes)
    if not new_lanes:
        raise ValueError("Settings file has no Mark lanes")
    keep = {lane.index for lane in new_lanes}
    before = len(song.marks)
    song.marks = [m for m in song.marks if m.lane_index in keep]
    song.mark_lanes = new_lanes
    if now_primary_lanes is not None or now_secondary_lanes is not None:
        song.now_lanes_configured = True
        if now_primary_lanes is not None:
            song.now_primary_lanes = [i for i in now_primary_lanes if i in keep] or (
                [new_lanes[0].index]
            )
        if now_secondary_lanes is not None:
            song.now_secondary_lanes = [i for i in now_secondary_lanes if i in keep]
    return before - len(song.marks)

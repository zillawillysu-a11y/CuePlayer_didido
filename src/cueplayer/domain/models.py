"""Core domain models for Project / Song (MVP skeleton)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

import numpy as np

SCHEMA_VERSION = 1

LaneType = Literal["main", "top_button"]
AudioRole = Literal["main", "reference"]
MarkLineStyle = Literal["solid", "dash", "dot"]
SetlistNameMode = Literal["zh", "both", "en"]
FileLtcSide = Literal["off", "left", "right", "auto"]


def coerce_file_ltc_side(
    value: object,
    *,
    use_left_ltc: bool = False,
) -> FileLtcSide:
    """Normalize song file-LTC routing; migrates legacy ``use_left_ltc``.

    Blank / unknown values default to ``auto`` (detect stripe and send it to
    the Settings LTC channel). Explicit ``off`` / ``left`` / ``right`` stay.
    """
    raw = str(value or "").strip().lower()
    if raw in ("off", "left", "right", "auto"):
        return raw  # type: ignore[return-value]
    if use_left_ltc or raw in ("1", "true", "yes", "l"):
        return "left"
    if raw in ("r",):
        return "right"
    return "auto"


# Decode-time cap applied inside VideoDecoder before frames reach either the
# embedded Preview or the Clean Video Output window — they share one decode
# path (AGENTS.md: no second independent video player), so this trades
# resolution for scrub/playback smoothness on both at once. "full" = source
# resolution, never upscaled.
VideoDecodeQuality = Literal["full", "1080p", "720p", "540p"]
VideoMediaKind = Literal["video", "still"]
DEFAULT_STILL_CLIP_DURATION_SECONDS = 5.0
VIDEO_DECODE_QUALITY_MAX_HEIGHT: dict[str, int | None] = {
    "full": None,
    "1080p": 1080,
    "720p": 720,
    "540p": 540,
}
MarkerShape = Literal[
    "circle",
    "diamond",
    "square",
    "triangle_up",
    "triangle_down",
    "arrow_up",
    "arrow_down",
    "arrow_left",
    "arrow_right",
    "cross",
]


MARKER_SHAPE_LABELS: dict[MarkerShape, str] = {
    "circle": "Circle",
    "diamond": "Diamond",
    "square": "Square",
    "triangle_up": "Triangle ▲",
    "triangle_down": "Triangle ▼",
    "arrow_up": "Arrow ↑",
    "arrow_down": "Arrow ↓",
    "arrow_left": "Arrow ←",
    "arrow_right": "Arrow →",
    "cross": "Cross ＋",
}


def _new_id() -> str:
    return uuid4().hex


@dataclass
class MarkLane:
    index: int
    name: str
    lane_type: LaneType = "top_button"
    color: str = "#4C8BF5"
    shortcut: str = ""
    visible: bool = True
    locked: bool = False
    export_enabled: bool = True
    # When True, marks on this lane get numbered Cue IDs (1, 2, 3…).
    cue_id_enabled: bool = False
    # When True, marks on this lane appear in the scrolling Cue List table.
    cue_list_enabled: bool = True
    # When True (and project MIDI cue notes enabled), crossing a mark on this
    # lane while playing sends a short MIDI note (for MA Timecode record / link).
    midi_note_enabled: bool = False
    # 1–127 overrides the default note; 0 = auto from Main/Button base + lane index.
    midi_note: int = 0
    # When True, placing a mark on this lane (shortcut or click) pauses playback.
    pause_on_mark: bool = False
    # When True, after placing a mark, open a dialog to type the Note.
    prompt_note_on_mark: bool = False
    # When True, draw the Note text next to the mark line on the waveform.
    show_note_on_wave: bool = False
    # When True, draw the Cue ID next to the mark line on the waveform.
    show_cue_id_on_wave: bool = False
    marker_shape: MarkerShape = "triangle_up"
    # Tinted row in the timeline (right of the header); header stays neutral.
    # Deprecated — track tint is project-global (show_mark_track_colors).
    show_row_color: bool = True


@dataclass
class AudioTrack:
    id: str
    name: str
    path: Path
    role: AudioRole = "reference"
    color: str = "#2BB673"
    muted: bool = False
    solo: bool = False
    locked: bool = False
    hidden: bool = False
    offset_seconds: float = 0.0


@dataclass
class VideoClip:
    """
    One VJ clip placed on a song's single video lane.

    `duration_seconds` is the authoritative timeline length (end_seconds =
    start_seconds + duration_seconds); `source_out_seconds` is kept in sync
    (source_in_seconds + duration_seconds) so older tools / exporters that
    only look at in/out points still see a consistent trim range.
    """

    id: str
    name: str
    path: Path
    start_seconds: float = 0.0
    source_in_seconds: float = 0.0
    source_out_seconds: float | None = None
    duration_seconds: float = 5.0
    locked: bool = False
    hidden: bool = False
    # Per-clip fader for the clip's own embedded audio (0.0 silent … 1.0 unity),
    # mixed into the master output sample-locked with the music (see
    # cueplayer.playback.video_audio_mixer.VideoAudioMixer). Independent of the
    # song-level `Song.video_track_muted` track mute.
    volume: float = 1.0
    media_kind: VideoMediaKind = "video"
    # Full source media length at add/relocate time (video file duration, or 0
    # for still images). Used to loop picture + embedded audio when the clip
    # is stretched longer than its trimmed source span.
    source_duration_seconds: float | None = None

    @classmethod
    def create(
        cls,
        name: str,
        path: Path,
        *,
        start_seconds: float = 0.0,
        source_in_seconds: float = 0.0,
        duration_seconds: float = 5.0,
        volume: float = 1.0,
        media_kind: VideoMediaKind = "video",
        source_duration_seconds: float | None = None,
    ) -> VideoClip:
        duration = max(0.02, float(duration_seconds))
        source_in = max(0.0, float(source_in_seconds))
        return cls(
            id=_new_id(),
            name=name,
            path=Path(path),
            start_seconds=float(start_seconds),
            source_in_seconds=source_in,
            source_out_seconds=source_in + duration,
            duration_seconds=duration,
            volume=max(0.0, min(1.0, float(volume))),
            media_kind=media_kind,
            source_duration_seconds=source_duration_seconds,
        )

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + max(0.0, self.duration_seconds)

    def contains(self, time_seconds: float) -> bool:
        """Half-open [start, end) so back-to-back clips don't both claim the boundary."""
        return self.start_seconds - 1e-9 <= time_seconds < self.end_seconds - 1e-9

    @property
    def source_span_seconds(self) -> float:
        """Trimmed source range length used for loop modulo."""
        out = self.source_out_seconds
        if out is None:
            return max(0.0, self.duration_seconds)
        return max(0.0, float(out) - self.source_in_seconds)

    def source_time_for(self, timeline_seconds: float) -> float:
        """Map a song-timeline position inside this clip to a source-media time."""
        if self.media_kind == "still":
            return self.source_in_seconds
        offset = max(0.0, timeline_seconds - self.start_seconds)
        span = self.source_span_seconds
        if span <= 1e-9:
            return self.source_in_seconds
        return self.source_in_seconds + (offset % span)


@dataclass
class Mark:
    id: str
    lane_index: int
    time_seconds: float
    display_name: str = ""
    ma_export_name: str | None = None
    # Fractional Main Cue ID (1, 1.1, 1.01, …) for main-lane marks only.
    main_cue_id: str = ""

    @classmethod
    def create(cls, lane_index: int, time_seconds: float, display_name: str = "") -> Mark:
        return cls(
            id=_new_id(),
            lane_index=lane_index,
            time_seconds=time_seconds,
            display_name=display_name,
        )


@dataclass
class SetlistCategory:
    """Folder-like grouping in the Setlist (organizational only — export still uses songs)."""

    id: str
    name: str
    collapsed: bool = False
    # Sheet view folder collapse (independent of left Setlist `collapsed`).
    sheet_collapsed: bool = False
    # Optional setlist folder-row background ("" = none); "#RRGGBB".
    row_color: str = ""

    @classmethod
    def create(cls, name: str) -> SetlistCategory:
        return cls(id=_new_id(), name=name.strip() or "Category")


@dataclass
class Song:
    id: str
    name: str
    start_timecode: str = "01:00:00:00"
    fps: float = 30.0
    duration_seconds: float = 60.0
    # Custom setlist number (supports 0.5 for interludes); list order is separate.
    setlist_number: float = 1.0
    # ASCII / pinyin label for grandMA (Chinese display name stays in `name`).
    ma_export_name: str | None = None
    # Optional tempo for setlist display / future beat grid (None = unset).
    bpm: float | None = None
    # True when `bpm` was filled by auto-detect (shown as gray <120>); False once
    # the user types a value. Cleared with bpm when the field is emptied.
    bpm_auto: bool = False
    # Free-text production note (Setlist Sheet / show notes); not written into MA XML.
    note: str = ""
    # Optional per-song setlist row background ("" = none); "#RRGGBB".
    # User-set marker for e.g. VIP songs or problematic cues; does not affect export.
    row_color: str = ""
    # Optional Setlist folder (see Project.setlist_categories).
    category_id: str | None = None
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    video_clips: list[VideoClip] = field(default_factory=list)
    # When set, route that file channel to the project LTC output channel(s)
    # and strip it from the music/speaker bus. "auto" uses stripe detection.
    # Values: "off" | "left" | "right" | "auto". Default auto — detect & route.
    file_ltc_side: str = "auto"
    # Track-level mute for every video clip's embedded audio (picture keeps
    # showing — this only silences the clip's own audio bus). Defaults to
    # audible: alignment work needs to hear video against the music track;
    # see docs/PRODUCT_SPEC.md's "影片原始音軌預設 Mute" note for the
    # deferred/OBS-reference assumption this overrides per explicit user request.
    video_track_muted: bool = False
    # When False, the Video lane is collapsed out of the timeline after
    # alignment work is done — Preview / Clean Output keep playing; only the
    # editable track chrome is hidden until the user shows it again.
    # Prefer Project.show_video_track (global eye); this field is kept in sync.
    show_video_track: bool = True
    # Optional LTC waveform lane under Music (inspect stripe quality / noise).
    # Bound to the Video eye — kept in sync with show_video_track / project flag.
    show_ltc_track: bool = False
    # Timeline height for the LTC inspect lane (pixels).
    ltc_lane_height: float = 56.0
    # Dedicated music-bed gain for alignment (Video vs Music balancing) —
    # independent of Master Volume (which scales music + video clip audio
    # together) and of LTC (never touched by any volume control, per
    # AGENTS.md). See AudioEngine.set_music_volume / TimelineWidget's
    # expanded Video track chrome.
    music_volume: float = 1.0
    # Per-song waveform gain (dB) for the main audio file — right-click drag line.
    audio_gain_db: float = 0.0
    # Timeline Video clip-row height (waveform lane); persisted per song.
    video_lane_height: float = 40.0
    # Mark lane row height (pixels); drag splitter below mark tracks.
    # Deprecated per-song copy; height is project-global (kept for migration).
    mark_lane_height: float = 28.0
    mark_lanes: list[MarkLane] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    show_mark_tracks: bool = True
    show_mark_stem: bool = False
    # Deprecated per-song copies; mark line look is project-global (kept for migration).
    mark_line_style: MarkLineStyle = "solid"
    mark_dash_on: float = 4.0
    mark_dash_off: float = 4.0
    mark_line_width: float = 1.0
    # Deprecated per-song waveform color (kept for migration).
    waveform_color: str = "#616161"
    # NOW monitor: which lanes feed primary / secondary panels.
    now_lanes_configured: bool = False
    now_primary_lanes: list[int] = field(default_factory=list)
    now_secondary_lanes: list[int] = field(default_factory=list)
    # When False, secondary lanes fold into primary and the secondary display card is hidden.
    now_secondary_enabled: bool = True
    # Show/hide the PRIMARY / SECONDARY NOW cards in the right monitor (lane logic unchanged).
    now_primary_visible: bool = True
    now_secondary_visible: bool = True
    # Show the scrolling Cue List table under the NOW cards.
    cue_list_visible: bool = True
    # Cue List column order (drag headers): time, type, cue_id, note.
    cue_list_column_order: list[str] = field(
        default_factory=lambda: ["time", "type", "cue_id", "note"]
    )
    # When False, the Cue ID column is hidden (right-click Cue List to toggle).
    cue_list_show_cue_id: bool = True
    # When False, PRIMARY NOW card hides Cue ID lines (right-click NOW to toggle).
    now_primary_show_cue_id: bool = True
    # When True, PRIMARY NOW puts Type / Cue / Note on one line (saves height).
    now_primary_single_line: bool = False
    # Seconds before the secondary display clears after a cue (0 = never). Handy for Buttons.
    now_secondary_clear_seconds: float = 2.0

    @classmethod
    def create(cls, name: str, *, mark_lanes: list[MarkLane] | None = None) -> Song:
        if mark_lanes:
            lanes = deepcopy(mark_lanes)
            indices = [lane.index for lane in lanes]
            primary = [lanes[0].index] if lanes else [1]
            secondary = [i for i in indices if i not in primary]
            return cls(
                id=_new_id(),
                name=name,
                mark_lanes=lanes,
                now_lanes_configured=True,
                now_primary_lanes=primary,
                now_secondary_lanes=secondary,
            )
        lanes = [
            MarkLane(
                index=1,
                name="Main",
                lane_type="main",
                shortcut="1",
                color="#E74C3C",
                visible=True,
                cue_id_enabled=True,
                cue_list_enabled=True,
                midi_note_enabled=False,
            ),
        ]
        colors = [
            "#E67E22",
            "#F1C40F",
            "#2ECC71",
            "#1ABC9C",
            "#3498DB",
            "#9B59B6",
            "#34495E",
            "#E91E63",
        ]
        for i in range(2, 10):
            lanes.append(
                MarkLane(
                    index=i,
                    name=f"Mark {i}",
                    lane_type="top_button",
                    shortcut=str(i),
                    color=colors[i - 2],
                    visible=True,
                    cue_id_enabled=False,
                    cue_list_enabled=True,
                    midi_note_enabled=True,
                )
            )
        return cls(
            id=_new_id(),
            name=name,
            mark_lanes=lanes,
            now_lanes_configured=True,
            now_primary_lanes=[1],
            now_secondary_lanes=list(range(2, 10)),
        )

    def lane_by_index(self, index: int) -> MarkLane | None:
        for lane in self.mark_lanes:
            if lane.index == index:
                return lane
        return None

    def lane_by_shortcut(self, shortcut: str) -> MarkLane | None:
        key = shortcut.strip()
        if not key:
            return None
        for lane in self.mark_lanes:
            if lane.shortcut.strip() == key:
                return lane
        return None

    def next_lane_index(self) -> int:
        if not self.mark_lanes:
            return 1
        return max(lane.index for lane in self.mark_lanes) + 1

    def add_lane(
        self,
        *,
        name: str | None = None,
        color: str = "#4C8BF5",
        shortcut: str = "",
        lane_type: LaneType = "top_button",
    ) -> MarkLane:
        index = self.next_lane_index()
        lane = MarkLane(
            index=index,
            name=name or f"Mark {index}",
            lane_type=lane_type,
            color=color,
            shortcut=shortcut,
        )
        self.mark_lanes.append(lane)
        self.mark_lanes.sort(key=lambda item: item.index)
        return lane

    def remove_lane(self, index: int) -> None:
        self.mark_lanes = [lane for lane in self.mark_lanes if lane.index != index]
        self.marks = [mark for mark in self.marks if mark.lane_index != index]

    def main_lane_index(self) -> int | None:
        """First lane with numbered Cue IDs (legacy name for export helpers)."""
        for lane in sorted(self.mark_lanes, key=lambda item: item.index):
            if lane.cue_id_enabled:
                return lane.index
        return None

    def cue_id_lane_indices(self) -> list[int]:
        return sorted(lane.index for lane in self.mark_lanes if lane.cue_id_enabled)

    def lane_has_cue_id(self, lane_index: int) -> bool:
        lane = self.lane_by_index(lane_index)
        return lane is not None and lane.cue_id_enabled

    def main_marks_sorted(self) -> list[Mark]:
        """All marks on Cue-ID lanes, sorted by time (legacy helper)."""
        id_lanes = set(self.cue_id_lane_indices())
        if not id_lanes:
            return []
        return sorted(
            (m for m in self.marks if m.lane_index in id_lanes),
            key=lambda m: (m.time_seconds, m.lane_index, m.id),
        )

    def add_mark(self, lane_index: int, time_seconds: float, display_name: str = "") -> Mark:
        mark = Mark.create(lane_index=lane_index, time_seconds=time_seconds, display_name=display_name)
        self.marks.append(mark)
        self.marks.sort(key=lambda m: (m.time_seconds, m.lane_index))
        from cueplayer.domain.main_cue_id import assign_main_cue_id_for_mark

        assign_main_cue_id_for_mark(self, mark)
        return mark

    def mark_by_id(self, mark_id: str) -> Mark | None:
        for mark in self.marks:
            if mark.id == mark_id:
                return mark
        return None

    def remove_marks_by_ids(self, mark_ids: set[str] | list[str]) -> int:
        wanted = set(mark_ids)
        before = len(self.marks)
        self.marks = [m for m in self.marks if m.id not in wanted]
        return before - len(self.marks)

    def sort_marks(self) -> None:
        self.marks.sort(key=lambda m: (m.time_seconds, m.lane_index))

    def duplicate(
        self,
        *,
        name: str | None = None,
        setlist_number: float | None = None,
    ) -> Song:
        """Copy marks, lanes, media links, and settings with fresh entity ids."""
        dup = Song(
            id=_new_id(),
            name=name if name is not None else f"{self.name} (copy)",
            start_timecode=self.start_timecode,
            fps=self.fps,
            duration_seconds=self.duration_seconds,
            setlist_number=(
                float(setlist_number) if setlist_number is not None else self.setlist_number
            ),
            ma_export_name=self.ma_export_name,
            bpm=self.bpm,
            bpm_auto=self.bpm_auto,
            note=self.note,
            row_color=self.row_color,
            category_id=None,
            file_ltc_side=coerce_file_ltc_side(self.file_ltc_side),
            video_track_muted=self.video_track_muted,
            show_video_track=self.show_video_track,
            show_ltc_track=self.show_ltc_track,
            ltc_lane_height=self.ltc_lane_height,
            music_volume=self.music_volume,
            audio_gain_db=self.audio_gain_db,
            video_lane_height=self.video_lane_height,
            mark_lane_height=self.mark_lane_height,
            mark_lanes=deepcopy(self.mark_lanes),
            show_mark_tracks=self.show_mark_tracks,
            show_mark_stem=self.show_mark_stem,
            mark_line_style=self.mark_line_style,
            mark_dash_on=self.mark_dash_on,
            mark_dash_off=self.mark_dash_off,
            mark_line_width=self.mark_line_width,
            waveform_color=self.waveform_color,
            now_lanes_configured=self.now_lanes_configured,
            now_primary_lanes=list(self.now_primary_lanes),
            now_secondary_lanes=list(self.now_secondary_lanes),
            now_secondary_enabled=self.now_secondary_enabled,
            now_primary_visible=self.now_primary_visible,
            now_secondary_visible=self.now_secondary_visible,
            cue_list_visible=self.cue_list_visible,
            cue_list_column_order=list(self.cue_list_column_order),
            cue_list_show_cue_id=self.cue_list_show_cue_id,
            now_primary_show_cue_id=self.now_primary_show_cue_id,
            now_primary_single_line=self.now_primary_single_line,
            now_secondary_clear_seconds=self.now_secondary_clear_seconds,
        )
        dup.audio_tracks = [
            AudioTrack(
                id=_new_id(),
                name=track.name,
                path=Path(track.path),
                role=track.role,
                color=track.color,
                muted=track.muted,
                solo=track.solo,
                locked=track.locked,
                hidden=track.hidden,
                offset_seconds=track.offset_seconds,
            )
            for track in self.audio_tracks
        ]
        dup.video_clips = []
        for clip in self.video_clips:
            new_clip = VideoClip.create(
                name=clip.name,
                path=clip.path,
                start_seconds=clip.start_seconds,
                source_in_seconds=clip.source_in_seconds,
                duration_seconds=clip.duration_seconds,
                volume=clip.volume,
                media_kind=clip.media_kind,
                source_duration_seconds=clip.source_duration_seconds,
            )
            new_clip.locked = clip.locked
            new_clip.hidden = clip.hidden
            if clip.source_out_seconds is not None:
                new_clip.source_out_seconds = clip.source_out_seconds
            dup.video_clips.append(new_clip)
        dup.marks = [
            Mark(
                id=_new_id(),
                lane_index=mark.lane_index,
                time_seconds=mark.time_seconds,
                display_name=mark.display_name,
                ma_export_name=mark.ma_export_name,
                main_cue_id=mark.main_cue_id,
            )
            for mark in self.marks
        ]
        return dup

    def marks_for_lane(self, lane_index: int) -> list[Mark]:
        return [m for m in self.marks if m.lane_index == lane_index]

    def configured_now_groups(self) -> tuple[list[int], list[int]]:
        """Stored primary/secondary assignment (ignores now_secondary_enabled)."""
        lanes = sorted(self.mark_lanes, key=lambda item: item.index)
        valid = {lane.index for lane in lanes}
        if not lanes:
            return [], []

        if not self.now_lanes_configured:
            primary = [lane.index for lane in lanes if lane.cue_id_enabled]
            if not primary:
                primary = [lanes[0].index]
            primary_set = set(primary)
            secondary = [
                lane.index
                for lane in lanes
                if lane.cue_id_enabled and lane.index not in primary_set
            ]
            return primary, secondary

        primary = [i for i in self.now_primary_lanes if i in valid]
        primary_set = set(primary)
        secondary = [i for i in self.now_secondary_lanes if i in valid and i not in primary_set]
        return primary, secondary

    def resolve_now_groups(self) -> tuple[list[int], list[int]]:
        """Return (primary, secondary) for the NOW monitor; merges when secondary display is off."""
        visible = {lane.index for lane in self.mark_lanes if lane.visible}
        primary, secondary = self.configured_now_groups()
        primary = [i for i in primary if i in visible]
        secondary = [i for i in secondary if i in visible]
        if not self.now_secondary_enabled:
            primary_set = set(primary)
            return [*primary, *[i for i in secondary if i not in primary_set]], []
        return primary, secondary

    def resolve_now_lanes(self) -> list[int]:
        primary, secondary = self.resolve_now_groups()
        return [*primary, *secondary]

    def active_mark_among_lanes(self, lane_indices: list[int], position: float) -> Mark | None:
        """Latest mark at or before position among the given lanes (for NOW switching)."""
        allowed = set(lane_indices)
        if not allowed:
            return None
        active: Mark | None = None
        for mark in self.marks:
            if mark.time_seconds > position + 1e-4:
                break
            if mark.lane_index in allowed:
                active = mark
        return active

    def last_mark_at_or_before(self, position: float) -> Mark | None:
        """Latest visible mark at or before position (chronological, all lanes)."""
        active: Mark | None = None
        for mark in self.marks:
            lane = self.lane_by_index(mark.lane_index)
            if lane is not None and not lane.visible:
                continue
            if mark.time_seconds > position + 1e-4:
                break
            active = mark
        return active

    def last_cue_list_mark_at_or_before(self, position: float) -> Mark | None:
        """Latest Cue List row mark at or before position (visible + cue_list_enabled)."""
        active: Mark | None = None
        for mark in self.marks:
            lane = self.lane_by_index(mark.lane_index)
            if lane is None or not lane.visible or not lane.cue_list_enabled:
                continue
            if mark.time_seconds > position + 1e-4:
                break
            active = mark
        return active

    def next_mark_among_lanes(self, lane_indices: list[int], position: float) -> Mark | None:
        allowed = set(lane_indices)
        if not allowed:
            return None
        for mark in self.marks:
            if mark.lane_index in allowed and mark.time_seconds > position + 1e-4:
                return mark
        return None

    def active_mark_for_lane(self, lane_index: int, position: float) -> Mark | None:
        """Latest mark on this lane at or before position."""
        active: Mark | None = None
        for mark in self.marks:
            if mark.time_seconds > position + 1e-4:
                break
            if mark.lane_index == lane_index:
                active = mark
        return active

    def next_mark_for_lane(self, lane_index: int, position: float) -> Mark | None:
        for mark in self.marks:
            if mark.lane_index == lane_index and mark.time_seconds > position + 1e-4:
                return mark
        return None

    def sort_video_clips(self) -> None:
        self.video_clips.sort(key=lambda clip: clip.start_seconds)

    def video_clip_by_id(self, clip_id: str) -> VideoClip | None:
        for clip in self.video_clips:
            if clip.id == clip_id:
                return clip
        return None

    def add_video_clip(self, clip: VideoClip) -> VideoClip:
        self.video_clips.append(clip)
        self.sort_video_clips()
        return clip

    def remove_video_clips_by_ids(self, clip_ids: set[str] | list[str]) -> int:
        wanted = set(clip_ids)
        before = len(self.video_clips)
        self.video_clips = [c for c in self.video_clips if c.id not in wanted]
        return before - len(self.video_clips)

    def overlapping_video_clip_ids(self) -> set[str]:
        """
        Clip ids whose timeline range overlaps another clip's.

        P0 scope: only one clip may play at a time; overlaps are flagged
        for the UI/status bar, not layered/composited (see PRODUCT_SPEC.md).
        """
        clips = sorted(self.video_clips, key=lambda c: c.start_seconds)
        overlapping: set[str] = set()
        for a, b in zip(clips, clips[1:]):
            if b.start_seconds < a.end_seconds - 1e-6:
                overlapping.add(a.id)
                overlapping.add(b.id)
        return overlapping

    def active_video_clips_at(self, time_seconds: float) -> list[VideoClip]:
        """All visible clips covering this timeline time (may overlap)."""
        return [c for c in self.video_clips if not c.hidden and c.contains(time_seconds)]

    def active_video_clip_at(self, time_seconds: float) -> VideoClip | None:
        """
        Primary clip for UI chrome (volume slider, status). On overlap, the
        latest-starting clip with the highest crossfade weight wins.
        """
        clips = self.active_video_clips_at(time_seconds)
        if not clips:
            return None
        if len(clips) == 1:
            return clips[0]
        return max(
            clips,
            key=lambda c: (
                video_clip_crossfade_weight(c, time_seconds, self.video_clips),
                c.start_seconds,
            ),
        )


def video_clip_crossfade_weights(
    clip: VideoClip,
    times_seconds: np.ndarray,
    all_clips: list[VideoClip],
) -> np.ndarray:
    """
    Vectorized 0..1 visibility weights for auto crossfade when clips overlap.

    ``times_seconds`` may be any shape; returns float32 weights of the same shape.
    """
    times = np.asarray(times_seconds, dtype=np.float64)
    if clip.hidden:
        return np.zeros(times.shape, dtype=np.float32)
    weights = np.ones(times.shape, dtype=np.float64)
    in_clip = (times + 1e-9 >= clip.start_seconds) & (times < clip.end_seconds - 1e-9)
    weights[~in_clip] = 0.0
    for other in all_clips:
        if other.hidden or other.id == clip.id:
            continue
        overlap_start = max(clip.start_seconds, other.start_seconds)
        overlap_end = min(clip.end_seconds, other.end_seconds)
        if overlap_end <= overlap_start + 1e-9:
            continue
        mask = (times + 1e-9 >= overlap_start) & (times < overlap_end - 1e-9)
        if not np.any(mask):
            continue
        span = overlap_end - overlap_start
        progress = np.clip((times - overlap_start) / span, 0.0, 1.0)
        if other.start_seconds > clip.start_seconds + 1e-9:
            weights[mask] = np.minimum(weights[mask], 1.0 - progress[mask])
        elif other.start_seconds + 1e-9 < clip.start_seconds:
            weights[mask] = np.minimum(weights[mask], progress[mask])
    return weights.astype(np.float32)


def video_clip_crossfade_weight(
    clip: VideoClip,
    time_seconds: float,
    all_clips: list[VideoClip],
) -> float:
    """
    0..1 visibility weight for auto crossfade when clips overlap.

    The earlier-starting clip fades out across the overlap; the later one
    fades in. Outside overlap each active clip is at full weight.
    """
    return float(
        video_clip_crossfade_weights(
            clip,
            np.asarray(time_seconds, dtype=np.float64),
            all_clips,
        ).item()
    )


@dataclass
class MaExportSettings:
    """Show-wide grandMA Sequence / Fader / Timecode patch."""

    console: str = "ma2"  # ma2 | ma3
    export_mode: str = "full"  # full | timecode_only
    sequence_pool_start: int = 1
    timecode_pool_start: int = 1
    main_executor: str = "1.101"
    button_executor_start: str = "1.201"
    timecode_slot: int = 1
    data_pool: str = "Default"
    latency_ms: float = 0.0
    # Each song uses its own Page: 1.201, 2.201, 3.201…
    page_per_song: bool = True
    # MA3 show-wide install macro basename (no .xml).
    show_install_macro_name: str = "CuePlayer_Show_Install"
    # Song ids selected for export; empty = all songs.
    export_song_ids: list[str] = field(default_factory=list)
    output_dir_ma2: str = ""
    output_dir_ma3: str = ""


# How LTC reaches the output bus.
# - auto: detect striped LTC in the loaded stereo file (default)
# - generator: internal SMPTE generator
# - source_left / source_right: pass that file channel through to ltc_channels
LtcSourceMode = Literal["generator", "auto", "source_left", "source_right"]
MusicRouteKind = Literal["mute", "music_source", "ltc", "channels"]


@dataclass
class AudioOutputSettings:
    """
    Output device, multi-channel routing, and generated timecode.

    Live UI uses machine-global prefs (QSettings) so New / Load Project keep
    the user's Driver / Device / MIDI choices. Project JSON still stores a
    copy for older builds / round-trips.

    Channel indices are 0-based internally (UI shows 1-based).
    Master music volume must not affect LTC gain.
    """

    # Empty name = system default output device.
    output_device_name: str = ""
    # PortAudio device index when known (stable across host APIs).
    output_device_index: int | None = None
    # Host API filter / label saved with the device (ASIO, Windows WASAPI, …).
    output_hostapi: str = ""
    # L / R stereo legs: channel numbers, "Music Source", or "LTC".
    music_l_route: str = "1"
    music_r_route: str = "2"
    # Legacy channel lists (derived from routes when loading old projects).
    music_left_channels: list[int] = field(default_factory=lambda: [0])
    music_right_channels: list[int] = field(default_factory=lambda: [1])
    # LTC output (independent of MTC). Default source = file auto-detect L/R.
    ltc_enabled: bool = False
    ltc_source: LtcSourceMode = "auto"
    # When ltc_source is "generator", actually run the internal SMPTE generator.
    ltc_generator_enabled: bool = True
    ltc_gain: float = 0.8
    ltc_channels: list[int] = field(default_factory=lambda: [2])
    # Decode file LTC stripe and drive MTC with those numbers (instead of generator).
    # Only applies when ltc_source != "generator" and MIDI is on.
    ltc_to_mtc_translate: bool = False
    # Master MIDI output switch — port + sub-features only active when True.
    midi_enabled: bool = False
    # MIDI Timecode quarter-frame output (Song Start TC + playhead).
    mtc_enabled: bool = False
    midi_port_name: str = ""
    # MIDI Note pulses when enabled mark lanes are crossed during play.
    midi_cue_notes_enabled: bool = False
    midi_cue_channel: int = 1  # 1–16
    midi_cue_velocity: int = 100
    midi_main_base_note: int = 36  # C2 + (lane.index - 1)
    midi_button_base_note: int = 48  # C3 + (lane.index - 1)
    # Per physical output channel: "music_source" | "ltc" | "off" (1-based UI).
    output_channel_modes: list[str] = field(default_factory=list)

    def effective_mtc_output(self) -> bool:
        """MTC quarter-frames — requires the MTC toggle (TRANS alone is not enough)."""
        return bool(self.midi_enabled and self.mtc_enabled)

    def effective_midi_cue_notes(self) -> bool:
        return bool(self.midi_enabled and self.midi_cue_notes_enabled)

    def effective_ltc_to_mtc_translate(self) -> bool:
        """Mirror file LTC numbers into MTC when both MTC and TRANS are on."""
        return bool(
            self.midi_enabled and self.mtc_enabled and self.ltc_to_mtc_translate
        )


@dataclass
class CleanVideoOutputSettings:
    """
    Project-global "Clean Video Output" window geometry.

    An OBS Window Capture source targets this window directly, so its pixel
    size (the video content area, not counting OS window chrome) must stay
    stable across sessions — hence this is saved with the project rather
    than per-song. Width/height describe the content area; aspect_locked
    keeps manual resizes at 16:9 so the OBS capture region doesn't drift.
    """

    width: int = 1920
    height: int = 1080
    aspect_locked: bool = True
    # When True, reopen this window on next launch / project open so OBS Window
    # Capture keeps targeting "CuePlayer Clean Video Output" instead of the
    # main UI.
    was_open: bool = False
    # Optional NDI sender mirroring the same decoded frames (Depence / etc.).
    ndi_enabled: bool = False
    ndi_name: str = "CuePlayer"
    # "video" = NDI size follows decoded frame; "output_window" = Clean Output
    # canvas + Fit/Fill (what you see in the Output box).
    ndi_frame_mode: str = "output_window"


def default_channel_routing(output_channels: int) -> tuple[list[int], list[int], list[int]]:
    """
    Sensible defaults: Music→CH1+CH2, LTC→CH3 when device has ≥3 outs.
    Stereo-only: Music→CH1+CH2, LTC left unmapped until the generator is enabled
    (see ``default_ltc_channels_for_device`` / UI clamp — LTC jumps into CH1–2).
    """
    n = max(0, int(output_channels))
    if n >= 3:
        return [0], [1], [2]
    if n == 2:
        return [0], [1], []
    if n == 1:
        return [0], [0], []
    return [0], [1], [2]


def default_ltc_channels_for_device(output_channels: int) -> list[int]:
    """
    Where Generated LTC should land on this device.

    ≥3 outs → CH3 (index 2). 2-ch → CH2 (index 1). 1-ch → CH1 (index 0).
    So a Focusrite-style default of CH3 automatically jumps back within the
    available range on stereo headphones / laptop speakers.
    """
    n = max(0, int(output_channels))
    if n <= 0:
        return []
    if n >= 3:
        return [2]
    return [n - 1]


def clamp_output_channels(channels: list[int], output_channels: int) -> list[int]:
    """Keep 0-based destination indices inside ``0 .. output_channels-1`` (deduped)."""
    n = max(0, int(output_channels))
    if n <= 0:
        return []
    out: list[int] = []
    for raw in channels:
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            continue
        if idx < 0:
            continue
        if idx >= n:
            idx = n - 1
        if idx not in out:
            out.append(idx)
    return out


@dataclass
class Project:
    id: str
    name: str
    schema_version: int = SCHEMA_VERSION
    songs: list[Song] = field(default_factory=list)
    setlist_categories: list[SetlistCategory] = field(default_factory=list)
    # Setlist title display: Chinese / both / English (MA).
    setlist_name_mode: SetlistNameMode = "zh"
    # Optional setlist columns (right-click toggle).
    setlist_show_bpm: bool = True
    setlist_show_ltc_badge: bool = True
    setlist_show_video_badge: bool = True
    # Optional Mark Manager preset for new songs (and "apply to show").
    default_mark_lanes: list[MarkLane] = field(default_factory=list)
    # Global waveform mark-line look (all songs share; saved with the project).
    mark_line_style: MarkLineStyle = "solid"
    mark_dash_on: float = 4.0
    mark_dash_off: float = 4.0
    mark_line_width: float = 1.0
    # Font size (pt) for Wave Cue / Wave Note labels on the waveform — project-global.
    wave_label_font_px: int = 10
    waveform_color: str = "#616161"
    # Playhead (NOW) line on the timeline — project-global like waveform_color.
    playhead_color: str = "#3dd68c"
    # Mark lane row height (pixels) — one value for the whole show.
    mark_lane_height: float = 28.0
    # Tinted mark-track rows on the timeline (all lanes share one eye).
    show_mark_track_colors: bool = True
    # Output timecode clock under the monitor seconds display.
    show_output_timecode_clock: bool = True
    output_timecode_clock_color: str = "#3dd68c"
    show_output_quick_toggles: bool = True
    # Video + LTC timeline lanes — one eye for the whole show (not per song).
    show_video_track: bool = True
    # Waveform / LTC Music volume adjustment lines (±12 dB UI) — show-wide.
    show_wave_gain_line: bool = False
    show_ltc_gain_line: bool = False
    ma_export: MaExportSettings = field(default_factory=MaExportSettings)
    audio_output: AudioOutputSettings = field(default_factory=AudioOutputSettings)
    clean_video_output: CleanVideoOutputSettings = field(
        default_factory=CleanVideoOutputSettings
    )
    # Preview/Clean Output decode resolution cap — see VideoDecodeQuality.
    video_decode_quality: VideoDecodeQuality = "1080p"

    @classmethod
    def create(cls, name: str) -> Project:
        return cls(id=_new_id(), name=name, songs=[Song.create("Untitled Song")])

    def new_song(self, name: str) -> Song:
        """Create a song using the project Mark template when set."""
        lanes = self.default_mark_lanes or None
        song = Song.create(name, mark_lanes=lanes)
        song.show_video_track = bool(self.show_video_track)
        song.show_ltc_track = bool(self.show_video_track)
        return song

    def set_show_video_track(self, visible: bool) -> None:
        """Global Video + LTC eye — applies to every song in the show."""
        visible = bool(visible)
        self.show_video_track = visible
        for song in self.songs:
            song.show_video_track = visible
            song.show_ltc_track = visible

    def setlist_category_by_id(self, category_id: str) -> SetlistCategory | None:
        for category in self.setlist_categories:
            if category.id == category_id:
                return category
        return None

    def songs_in_category(self, category_id: str | None) -> list[Song]:
        """Songs in one setlist folder (``None`` = main list, outside folders)."""
        return [song for song in self.songs if song.category_id == category_id]

    def next_setlist_number(self, category_id: str | None = None) -> float:
        """Next # for a folder — numbers are independent per category."""
        peers = self.songs_in_category(category_id)
        if not peers:
            return 1.0
        return max(float(song.setlist_number) for song in peers) + 1.0

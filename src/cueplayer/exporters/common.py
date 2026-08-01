"""Shared helpers for grandMA exporters."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

ConsoleFamily = Literal["ma2", "ma3"]
ExportMode = Literal["full", "timecode_only"]


_SAFE_RE = re.compile(r"[^A-Za-z0-9 _.-]+")
_SPACE_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
# Auto / placeholder cue titles — not real Notes (also catches Cue_15 after sanitize).
_CUE_PLACEHOLDER_RE = re.compile(r"^cue[_\s]*[\d.]+$", re.IGNORECASE)


def ma_export_name_from_display(display_name: str) -> str:
    """Always produce a non-empty MA/English label from a display name (Chinese → pinyin)."""
    return sanitize_ma_name(display_name.strip() or "Song", fallback="Song")


def chinese_to_pinyin_ascii(text: str) -> str:
    """
    Replace Chinese runs with tone-less pinyin (ASCII).

    Example: 「主歌 Verse」→「ZhuGe Verse」
    """
    if not text or not _CJK_RE.search(text):
        return text
    from pypinyin import Style, lazy_pinyin

    def _repl(match: re.Match[str]) -> str:
        syllables = lazy_pinyin(match.group(0), style=Style.NORMAL)
        return "".join(s.capitalize() for s in syllables if s)

    return _CJK_RE.sub(_repl, text)


def sanitize_ma_name(name: str, *, fallback: str) -> str:
    """
    Produce an MA-safe ASCII label.

    Chinese is converted to pinyin first, then punctuation stripped.
    Spaces become underscores (MA2 Import / Timecode Object break on spaces).
    Empty results fall back to the provided id.
    """
    converted = chinese_to_pinyin_ascii(name)
    cleaned = _SAFE_RE.sub("", converted).strip()
    cleaned = _SPACE_RE.sub("_", cleaned)
    cleaned = cleaned.strip("._-+")
    return cleaned if cleaned else fallback


def to_ma_label(text: str, *, fallback: str = "") -> str:
    """Cue / object label: Chinese→pinyin, then MA-safe ASCII (may be empty)."""
    return sanitize_ma_name(text, fallback=fallback)


def parse_page_executor(value: str) -> tuple[int, int]:
    """Parse '1.101' into (page, executor). Incomplete values use safe defaults."""
    text = (value or "").strip()
    if not text:
        return 1, 101
    if "." in text:
        page_s, exec_s = text.split(".", 1)
        page_s, exec_s = page_s.strip(), exec_s.strip()
        page = int(page_s) if page_s.isdigit() else 1
        # While typing "1." exec is empty — don't crash the UI.
        executor = int(exec_s) if exec_s.isdigit() else 0
        return page, executor
    if text.isdigit():
        return 1, int(text)
    return 1, 101


def export_event_time_seconds(mark_time_seconds: float, profile: MaExportProfile) -> float:
    """
    Convert a CuePlayer mark time into MA Timecode *timeline* event time.

    Events stay song-relative (like CuePoints). Song start LTC is applied as
    Timecode Offset on the pool object — not baked into each event.

    Only LTC/console latency compensation is applied here (typically negative).
    """
    t = mark_time_seconds + profile.ltc_latency_compensation_seconds
    return max(0.0, t)


def format_ma3_offset_seconds(seconds: float) -> str:
    """
    MA3 Timecode «Offset TC Slot» / OffsetTCSlot value.

    Matches the settings calculator style (e.g. 1h00m00.00), not baked event time.
    """
    s = max(0.0, float(seconds))
    hours = int(s // 3600)
    rem = s - hours * 3600
    mins = int(rem // 60)
    secs = rem - mins * 60
    if hours > 0 or mins > 0:
        return f"{hours}h{mins:02d}m{secs:05.2f}"
    return f"{secs:.2f}"


def format_ma2_offset_frames(seconds: float, fps: float) -> str:
    """Deprecated: old frame-based XML offset. Prefer Assign /Offset=… time."""
    from cueplayer.exporters.xml_write import seconds_to_ma2_frames

    return str(max(0, seconds_to_ma2_frames(max(0.0, float(seconds)), fps)))


def format_ma2_offset_assign(seconds: float) -> str:
    """
    MA2 Assign Timecode /Offset=… value (settings Offset field).

    Official help accepts time (0s … 255h…). Prefer compact hour form when whole hours.
    """
    s = max(0.0, float(seconds))
    if abs(s - round(s / 3600.0) * 3600.0) < 1e-6 and s >= 3600.0:
        return f"{int(round(s / 3600.0))}h"
    if abs(s - round(s)) < 1e-6:
        return f"{int(round(s))}s"
    return f"{s:.2f}s"


def ma2_timecode_assign_settings(plan_profile: MaExportProfile) -> list[str]:
    """
    Post-Import MA2 Timecode options (match common CuePoints / show-setup prefs).

    Screenshot target:
      Slot=1 (or project Timecode Slot) · Runs=Endless Repeat
      Switch Off=Keep Playbacks · Status Call=Off
      When Ending=Stop · When Stopping=Rewind · AutoStart=Off
      TimeUnit matches XML event units (24/25/30 FPS — MA default on Import)
      Record Mode=Go (Go Cue X, not Goto Cue X).

    Song-start LTC → ``/Offset=…``.

    Important: XML ``time`` / ``lenght`` are interpreted with the Timecode's
    TimeUnit **at Import**. Changing TimeUnit afterward only changes display.
    Event times are therefore written as frames at this same FPS.
    """
    from cueplayer.exporters.xml_write import ma2_timecode_frame_format

    tc = int(plan_profile.timecode_pool)
    slot = int(plan_profile.timecode_slot)
    # Help: Intern=-1, Link Selected=0, fixed slots=1..8. Default / UI = 1.
    if slot < 0:
        slot_token = "-1"
    elif slot == 0:
        slot_token = "0"
    else:
        slot_token = str(max(1, min(8, slot)))
    offset = (
        format_ma2_offset_assign(plan_profile.start_offset_seconds)
        if plan_profile.start_offset_seconds > 1e-6
        else "0s"
    )
    frame_format = ma2_timecode_frame_format(plan_profile.fps)
    return [
        (
            f'Assign Timecode {tc} /Slot={slot_token} '
            f'/Runs="Endless Repeat" '
            f'/SwitchOff="Keep Playbacks" /StatusCall="Off" '
            f'/WhenEnding="Stop" /WhenStopping="Rewind" '
            f'/AutoStart="Off" /Offset={offset}'
        ),
        # Quoted enum — numeric /TimeUnit=0 was 1/100s and fought FPS frame times.
        f'Assign Timecode {tc} /TimeUnit="{frame_format}"',
        f'Assign Timecode {tc} /RecordMode="Go"',
    ]


def ma2_timecode_pre_import_timeunit(plan_profile: MaExportProfile) -> str:
    """Set TimeUnit before Import so XML frame times decode correctly."""
    from cueplayer.exporters.xml_write import ma2_timecode_frame_format

    tc = int(plan_profile.timecode_pool)
    frame_format = ma2_timecode_frame_format(plan_profile.fps)
    return f'Assign Timecode {tc} /TimeUnit="{frame_format}"'


def ma_import_filename(stem: str, *, suffix: str = ".xml") -> str:
    """
    Basename for MA Import \"file.xml\" commands.

    Spaces break some Import paths; keep ASCII via sanitize, then underscore.
    """
    safe = sanitize_ma_name(stem, fallback="cueplayer").replace(" ", "_")
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return f"{safe}{suffix}"


def ma3_timecode_set_property_commands(plan_profile: MaExportProfile) -> list[str]:
    """
    MA3 Timecode settings from the user's preferred editor layout.

    Offset → property OffsetTCSlot («Offset TC Slot» in UI).
    Playback: Auto Start/Stop On, Loop Off, Keep Playbacks, Assert No, Restart Continue;
    Record Manual Events / as Go; Display 10d11h23m45 + Seconds.
    """
    tc = plan_profile.timecode_pool
    slot = int(plan_profile.timecode_slot)
    # -1 = none/internal in older XML; positive = TCSlot N (user screenshot uses 1).
    tc_slot_value = str(slot) if slot >= 0 else "-1"
    offset = format_ma3_offset_seconds(plan_profile.start_offset_seconds)
    return [
        f'Set Timecode {tc} Property "TCSlot" "{tc_slot_value}"',
        # Official property name (forum / Lua): OffsetTCSlot — NOT "Offset".
        f'Set Timecode {tc} Property "OffsetTCSlot" "{offset}"',
        f'Set Timecode {tc} Property "AutoStart" "Yes"',
        f'Set Timecode {tc} Property "AutoStop" "Yes"',
        f'Set Timecode {tc} Property "LoopMode" "Off"',
        f'Set Timecode {tc} Property "SwitchOff" "Keep Playbacks"',
        f'Set Timecode {tc} Property "AssertPrevEvents" "No"',
        f'Set Timecode {tc} Property "RestartOption" "Continue"',
        f'Set Timecode {tc} Property "Goto" "as Go"',
        f'Set Timecode {tc} Property "Playback and Record" "Manual Events"',
        f'Set Timecode {tc} Property "TimeDisplayFormat" "10d11h23m45"',
        f'Set Timecode {tc} Property "FrameReadout" "Seconds"',
    ]


def format_ma_cue_number(cue_number: float) -> str:
    """Command-line / display cue id (4, 4.1, 4.01) without trailing zeros."""
    from decimal import Decimal

    text = format(Decimal(str(cue_number)).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def split_ma_cue_number(cue_number: float) -> tuple[int, int]:
    """MA2 Number fields: cue 4.1 → (4, 100) because MA stores three decimals."""
    from decimal import Decimal, ROUND_HALF_UP

    quantized = Decimal(str(cue_number)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    major = int(quantized)
    frac = quantized - Decimal(major)
    sub = int((frac * Decimal(1000)).to_integral_value(rounding=ROUND_HALF_UP))
    return major, max(0, sub)


def format_ma2_timecode_step(cue_number: float) -> str:
    """
    Deprecated: Main Timecode events should use ``MA2_TC_STEP_NONE`` so Import
    does not create phantom Cue numbers from sequence indices.
    """
    major, sub = split_ma_cue_number(cue_number)
    if sub:
        return str(major * 1000 + sub)
    return str(major)


# Same sentinel Top events use — "no step". Using the Store-order index as
# step (45, 46, …) made MA Timecode Import invent Cue 45…N when Cue IDs only
# went to 44 because of fractional inserts.
MA2_TC_STEP_NONE = "4294967295"


def format_ma2_cue_link_name(cue_number: float) -> str:
    """Timecode ``Cue name=`` / Sequence Label — matches MA Store default ``Cue N``."""
    return f"Cue {format_ma_cue_number(cue_number)}"


def ma2_timecode_cue_nos(sequence_pool: int, cue_index: int) -> list[int]:
    """
    MA2 Timecode Event Cue ``<No>`` list.

    Third value is the 1-based **index** of the cue inside the sequence (the
    order cues were Store'd), not the Cue ID number. When Cue IDs are 1…N with
    no fractions, index == number so old exports looked fine — but after
    ``14.1`` the next cue id ``15`` is index 16, and writing ``15`` made MA
    fire Cue 14.1 (the 15th cue) instead.
    """
    return [1, int(sequence_pool), max(1, int(cue_index))]


def ma2_phantom_cue_delete_range(plan: "SongExportPlan") -> tuple[int, int] | None:
    """
    If Timecode Import still spawned Cue (max_id+1)…(cue_count), return that
    inclusive Delete range. Example: 44 IDs + 9 fractions → 53 Stores, max ID
    44 → delete Cue 45 Thru 53.
    """
    if not plan.main_cues:
        return None
    max_major = max(split_ma_cue_number(c.cue_number)[0] for c in plan.main_cues)
    count = len(plan.main_cues)
    if count > max_major:
        return max_major + 1, count
    return None


def ma3_cue_destination_handle(cue_number: float) -> int:
    """MA3 ValCueDestination milli-handle: cue 1 → 1000, cue 4.1 → 4100."""
    return int(round(float(cue_number) * 1000))


def format_ma3_cue_no_attr(cue_number: float) -> str:
    """MA3 Cue/@No text (right-padded whole numbers; decimals keep three places)."""
    major, sub = split_ma_cue_number(cue_number)
    if sub == 0:
        return f"{major:3d}"
    return f"{major}.{sub:03d}"


@dataclass
class ExportCue:
    cue_number: float
    display_name: str
    ma_export_name: str | None = None
    time_seconds: float = 0.0

    def resolved_ma_name(self) -> str:
        label = format_ma_cue_number(self.cue_number)
        if self.ma_export_name and self.ma_export_name.strip():
            return sanitize_ma_name(self.ma_export_name, fallback=f"Cue{label}")
        return sanitize_ma_name(self.display_name, fallback=f"Cue{label}")

    def cue_name_for_export(self) -> str | None:
        """
        Sequence Cue label from mark Note / MA name.

        Returns None when there is no real note (leave cue numbered only).
        Chinese notes become pinyin (MA Label rejects / drops CJK).

        Any ``Cue 14`` / ``Cue_15`` / ``Cue 14.1`` style title is treated as a
        placeholder — never Store that as the MA cue name. Timecode events
        resolve ``Cue name="Cue 14.1"``; a mismatched ``Cue_15`` breaks the link.
        """
        if self.ma_export_name and self.ma_export_name.strip():
            cleaned = sanitize_ma_name(self.ma_export_name, fallback="")
            if cleaned and not _CUE_PLACEHOLDER_RE.match(cleaned):
                return cleaned
            return None
        raw = (self.display_name or "").strip()
        if not raw:
            return None
        if _CUE_PLACEHOLDER_RE.match(raw):
            return None
        for ch in '\\"$&*?,.;^{|}~':
            raw = raw.replace(ch, "")
        raw = " ".join(raw.split())
        if not raw:
            return None
        cleaned = sanitize_ma_name(raw, fallback="") or None
        if cleaned and _CUE_PLACEHOLDER_RE.match(cleaned):
            return None
        return cleaned


@dataclass
class ExportButtonLane:
    lane_index: int
    display_name: str
    ma_export_name: str | None = None
    executor: str = "1.201"
    mark_times_seconds: list[float] = field(default_factory=list)
    # Pool index / file for this button's own Sequence (flash template).
    sequence_pool: int = 0
    sequence_name: str = ""
    sequence_file: str = ""

    def resolved_ma_name(self) -> str:
        fallback = f"Button{self.lane_index}"
        if self.ma_export_name and self.ma_export_name.strip():
            return sanitize_ma_name(self.ma_export_name, fallback=fallback)
        return sanitize_ma_name(self.display_name, fallback=fallback)


@dataclass
class MaExportProfile:
    console: ConsoleFamily
    sequence_pool_start: int = 1
    timecode_pool: int = 1
    page: int = 1
    # English name applied via Label Page N "…" (CuePoints-style page-per-song).
    page_name: str = ""
    main_executor: str = "1.101"
    timecode_slot: int = 1
    fps: float = 30.0
    start_offset_seconds: float = 0.0
    # Negative = fire earlier (CuePoints "Global Latency Negative Offset").
    # Typical live LTC→MA lag: -0.10 ~ -0.20.
    ltc_latency_compensation_seconds: float = 0.0
    data_pool: str = "Default"  # MA3
    button_follow_seconds: float = 0.1  # hidden internal default
    export_mode: ExportMode = "full"
    main_sequence_name: str = "CuePlayer_Main"
    button_sequence_name: str = "CuePlayer_Button"
    timecode_name: str = "CuePlayer_TC"
    # Filenames used by macros/plugins when importing from library folders.
    main_sequence_file: str = "cueplayer_test_main.xml"
    button_sequence_file: str = "cueplayer_test_button.xml"
    timecode_file: str = "cueplayer_test_timecode.xml"


@dataclass
class SongExportPlan:
    song_name: str
    profile: MaExportProfile
    main_cues: list[ExportCue] = field(default_factory=list)
    button_lanes: list[ExportButtonLane] = field(default_factory=list)
    # Song media length — Timecode ``lenght`` should cover the full song, not
    # only the last cue.
    duration_seconds: float = 0.0

"""Dialog for creating / editing one per-song LTC Generator Clip.

Timeline Start + Duration use the existing Cue List time parsing
(``parse_time``); the Start Timecode uses the existing SMPTE parsing
(``parse_timecode``). Timeline-range overlap is blocked here (UI editing
layer); overlapping / backwards TC ranges are allowed with a warning.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.ltc_clips import POS_EPS, ltc_clip_tc_range
from cueplayer.domain.models import LtcClip, Song
from cueplayer.timecode.smpte import parse_timecode
from cueplayer.ui.transport_bar import format_time, parse_time


def _overlapping_timeline_clip(
    clips: list[LtcClip],
    candidate: LtcClip,
) -> LtcClip | None:
    """First other clip whose timeline range overlaps the candidate."""
    c0 = float(candidate.timeline_start_seconds)
    c1 = float(candidate.end_seconds)
    for other in clips:
        if other.id == candidate.id:
            continue
        o0 = float(other.timeline_start_seconds)
        o1 = float(other.end_seconds)
        if c0 < o1 - POS_EPS and c1 > o0 + POS_EPS:
            return other
    return None


def _tc_conflicting_clip(
    clips: list[LtcClip],
    candidate: LtcClip,
    fps: float,
) -> LtcClip | None:
    """First other clip with an overlapping or backwards TC range (warning)."""
    cand = ltc_clip_tc_range(candidate, fps)
    if cand is None:
        return None
    for other in clips:
        if other.id == candidate.id:
            continue
        other_range = ltc_clip_tc_range(other, fps)
        if other_range is None:
            continue
        if other_range.start_frames < cand.end_frames:
            return other
    return None


class LtcClipEditDialog(QDialog):
    """Create or edit one LTC generator clip (start, duration, start TC)."""

    def __init__(
        self,
        song: Song,
        parent: QWidget | None = None,
        *,
        clip: LtcClip | None = None,
        default_start_seconds: float | None = None,
    ) -> None:
        super().__init__(parent)
        self._song = song
        self._clip_id = clip.id if clip is not None else None
        self._timeline_duration = max(0.0, float(song.duration_seconds))
        self.setWindowTitle("Edit LTC Clip" if clip is not None else "Add LTC Clip")

        start = (
            float(clip.timeline_start_seconds)
            if clip is not None
            else min(self._timeline_duration, max(0.0, float(default_start_seconds or 0.0)))
        )
        duration = (
            float(clip.duration_seconds)
            if clip is not None
            else max(5.0, min(60.0, self._timeline_duration - start))
        )
        start_tc = (
            str(clip.start_timecode)
            if clip is not None
            else str(song.start_timecode or "01:00:00:00")
        )

        root = QVBoxLayout(self)
        hint = QLabel(
            "Generated LTC is sent only inside this clip. Start Timecode is the "
            "TC actually sent at the clip's timeline start "
            "(independent of the song start TC). Outside the clip: no LTC / no MTC."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; margin-bottom: 4px;")
        root.addWidget(hint)

        form = QFormLayout()
        self.timeline_start = QLineEdit(format_time(start))
        self.duration = QLineEdit(format_time(duration))
        self.start_timecode = QLineEdit(start_tc)
        for editor in (self.timeline_start, self.duration):
            editor.setPlaceholderText("MM:SS.mmm or HH:MM:SS.mmm")
        self.start_timecode.setPlaceholderText("HH:MM:SS:FF")
        for editor in (self.timeline_start, self.duration, self.start_timecode):
            editor.textChanged.connect(self._refresh_validation)
        form.addRow("Timeline Start", self.timeline_start)
        form.addRow("Duration", self.duration)
        form.addRow("Start Timecode", self.start_timecode)
        self.validation = QLabel("")
        self.validation.setWordWrap(True)
        root.addLayout(form)
        root.addWidget(self.validation)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self._refresh_validation()

    # -- validation ---------------------------------------------------------

    def _candidate_clip(self) -> LtcClip | None:
        """Build the would-be clip from the current fields (None if unparseable)."""
        start = parse_time(self.timeline_start.text())
        duration = parse_time(self.duration.text())
        tc = parse_timecode(self.start_timecode.text())
        if start is None or duration is None or tc is None:
            return None
        return LtcClip(
            id=self._clip_id or "candidate",
            timeline_start_seconds=float(start),
            duration_seconds=float(duration),
            start_timecode=tc.format(),
        )

    def _other_clips(self) -> list[LtcClip]:
        return [c for c in self._song.ltc_clips if c.id != self._clip_id]

    def _validation_result(self) -> tuple[str, str, list[str]]:
        """Return (error, warning, overlapping_tc_ids)."""
        candidate = self._candidate_clip()
        errors: list[str] = []
        warnings: list[str] = []
        if candidate is None:
            return (
                "Enter times as MM:SS.mmm / HH:MM:SS.mmm and the start TC as "
                "HH:MM:SS:FF.",
                "",
                [],
            )
        if candidate.timeline_start_seconds < -POS_EPS:
            errors.append("Timeline Start cannot be before 0:00.")
        if candidate.duration_seconds <= 0:
            errors.append("Duration must be greater than 0.")
        elif candidate.end_seconds > self._timeline_duration + POS_EPS:
            errors.append(
                "The clip ends after the song ends "
                f"({format_time(candidate.end_seconds)} > "
                f"{format_time(self._timeline_duration)})."
            )
        other = _overlapping_timeline_clip(self._other_clips(), candidate)
        if other is not None:
            errors.append(
                "Overlaps an existing LTC clip on the timeline "
                f"({format_time(other.timeline_start_seconds)}–"
                f"{format_time(other.end_seconds)}). Timeline clips cannot overlap."
            )
        tc_other = _tc_conflicting_clip(
            self._other_clips(), candidate, float(self._song.fps or 30.0)
        )
        if tc_other is not None:
            warnings.append(
                "Warning: overlapping or backwards timecode range vs the clip at "
                f"{format_time(tc_other.timeline_start_seconds)} — allowed, check "
                "your rehearsal plan."
            )
        return (" ".join(errors), " ".join(warnings), [tc_other.id] if tc_other else [])

    def _refresh_validation(self) -> None:
        error, warning, _ = self._validation_result()
        if error:
            self.validation.setStyleSheet("color: #ff6b6b;")
            text = error
        elif warning:
            self.validation.setStyleSheet("color: #d29922;")
            text = warning
        else:
            self.validation.setStyleSheet("color: #3dd68c;")
            text = "OK"
        self.validation.setText(text)

    # -- accept -------------------------------------------------------------

    def _validate_and_accept(self) -> None:
        error, warning, _ = self._validation_result()
        if error:
            QMessageBox.warning(self, "Invalid LTC Clip", error)
            return
        self.accept()
        if warning:
            # Surfaced by the caller via status bar; dialog text stays readable.
            del warning

    def values(self) -> tuple[float, float, str]:
        candidate = self._candidate_clip()
        assert candidate is not None
        return (
            float(candidate.timeline_start_seconds),
            float(candidate.duration_seconds),
            candidate.start_timecode,
        )

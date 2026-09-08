"""Direct editor for timeline placement and source-media trim points."""

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

from cueplayer.domain.models import VideoClip
from cueplayer.ui.transport_bar import format_time, parse_time


class VideoClipEditDialog(QDialog):
    def __init__(
        self,
        clip: VideoClip,
        parent: QWidget | None = None,
        *,
        timeline_duration: float | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_duration = max(0.0, float(clip.source_duration_seconds or 0.0))
        self._timeline_duration = (
            max(0.0, float(timeline_duration))
            if timeline_duration is not None
            else None
        )
        self.setWindowTitle("Edit Video Clip")
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.timeline_start = QLineEdit(format_time(max(0.0, clip.start_seconds)))
        self.source_in = QLineEdit(format_time(clip.source_in_seconds))
        self.source_out = QLineEdit(
            format_time(
                clip.source_out_seconds
                if clip.source_out_seconds is not None
                else clip.source_in_seconds + clip.duration_seconds
            )
        )
        for editor in (self.timeline_start, self.source_in, self.source_out):
            editor.setPlaceholderText("MM:SS.mmm or HH:MM:SS.mmm")
            editor.textChanged.connect(self._refresh_duration)
        self.duration = QLabel()
        source_length = (
            format_time(self._source_duration) if self._source_duration > 0 else "Unknown"
        )
        form.addRow("Timeline Start", self.timeline_start)
        form.addRow("Source In", self.source_in)
        form.addRow("Source Out", self.source_out)
        form.addRow("Duration", self.duration)
        form.addRow("Source Length", QLabel(source_length))
        root.addLayout(form)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self._refresh_duration()

    def values(self) -> tuple[float, float, float]:
        start = parse_time(self.timeline_start.text())
        source_in = parse_time(self.source_in.text())
        source_out = parse_time(self.source_out.text())
        assert start is not None and source_in is not None and source_out is not None
        return float(start), float(source_in), float(source_out)

    def _refresh_duration(self) -> None:
        source_in = parse_time(self.source_in.text())
        source_out = parse_time(self.source_out.text())
        if source_in is None or source_out is None or source_out <= source_in:
            self.duration.setText("—")
            return
        self.duration.setText(format_time(source_out - source_in))

    def _validate_and_accept(self) -> None:
        start = parse_time(self.timeline_start.text())
        source_in = parse_time(self.source_in.text())
        source_out = parse_time(self.source_out.text())
        error = ""
        if start is None or source_in is None or source_out is None:
            error = "Enter time as MM:SS.mmm, HH:MM:SS.mmm, or seconds."
        elif (
            self._timeline_duration is not None
            and start > self._timeline_duration + 1e-6
        ):
            error = (
                "Timeline Start cannot exceed the song length "
                f"({format_time(self._timeline_duration)})."
            )
        elif source_out <= source_in:
            error = "Source Out must be later than Source In."
        elif self._source_duration > 0 and source_out > self._source_duration + 1e-6:
            error = f"Source Out cannot exceed {format_time(self._source_duration)}."
        if error:
            QMessageBox.warning(self, "Invalid Video Clip Time", error)
            return
        self.accept()

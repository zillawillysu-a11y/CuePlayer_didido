"""Editors for beat-grid regions and generated marks."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout, QWidget

from cueplayer.domain.models import BeatGridRegion, Song
from cueplayer.ui.spinboxes import NoWheelDoubleSpinBox, NoWheelSpinBox


class BeatGridEditDialog(QDialog):
    def __init__(self, grid: BeatGridRegion, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Beat Grid")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.bpm = NoWheelDoubleSpinBox()
        self.bpm.setRange(1.0, 999.0)
        self.bpm.setDecimals(3)
        self.bpm.setValue(grid.bpm)
        self.numerator = NoWheelSpinBox()
        self.numerator.setRange(1, 32)
        self.numerator.setValue(grid.beats_per_bar)
        self.denominator = NoWheelSpinBox()
        self.denominator.setRange(1, 32)
        self.denominator.setValue(grid.beat_unit)
        self.subdivision = NoWheelSpinBox()
        self.subdivision.setRange(1, 16)
        self.subdivision.setValue(grid.subdivision)
        self.duration = NoWheelDoubleSpinBox()
        self.duration.setRange(0.01, 86400.0)
        self.duration.setDecimals(3)
        self.duration.setSuffix(" s")
        self.duration.setValue(max(0.01, grid.end_seconds - grid.start_seconds))
        form.addRow("BPM", self.bpm)
        form.addRow("Beats per bar", self.numerator)
        form.addRow("Beat unit", self.denominator)
        form.addRow("Subdivision", self.subdivision)
        form.addRow("Duration", self.duration)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[float, int, int, int, float]:
        return (
            float(self.bpm.value()), int(self.numerator.value()),
            int(self.denominator.value()), int(self.subdivision.value()),
            float(self.duration.value()),
        )


class AutoAddMarksDialog(QDialog):
    def __init__(self, song: Song, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Auto Add Marks")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.lane = QComboBox()
        for lane in sorted(song.mark_lanes, key=lambda item: item.index):
            if lane.visible and not lane.locked:
                self.lane.addItem(lane.name, lane.index)
        self.interval = QComboBox()
        self.interval.addItem("1 Beat", "beat")
        self.interval.addItem("2 Beats", "beat_2")
        self.interval.addItem("3 Beats", "beat_3")
        self.interval.addItem("8 Beats", "beat_8")
        self.interval.addItem("1 Bar", "bar")
        self.interval.addItem("1 Subdivision", "subdivision")
        self.bars = NoWheelSpinBox()
        self.bars.setRange(0, 9999)
        self.bars.setSpecialValueText("To Grid End")
        self.bars.setValue(0)
        self.bars.setToolTip(
            "0 uses the rest of the Beat Grid; otherwise stop after this many bars"
        )
        form.addRow("Mark Type", self.lane)
        form.addRow("Interval", self.interval)
        form.addRow("Bars", self.bars)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[int, str, int]:
        return (
            int(self.lane.currentData()),
            str(self.interval.currentData()),
            int(self.bars.value()),
        )

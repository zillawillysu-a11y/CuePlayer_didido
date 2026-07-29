"""Compact output toggles for the monitor clock (MIDI / MTC / LTC / Notes)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from cueplayer.domain.models import AudioOutputSettings

_CHIP_BASE = """
QPushButton {
    min-height: 22px;
    max-height: 22px;
    padding: 1px 9px;
    border-radius: 11px;
    border: 1px solid #3f3f46;
    background: #18181b;
    color: #71717a;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.3px;
}
QPushButton:hover:enabled {
    border-color: #52525b;
    color: #a1a1aa;
}
QPushButton:checked {
    border-color: %(accent)s;
    background: %(bg)s;
    color: %(accent)s;
}
QPushButton:checked:hover:enabled {
    border-color: %(accent_hover)s;
    color: %(accent_hover)s;
}
QPushButton:disabled {
    background: #141416;
    border-color: #27272a;
    color: #3f3f46;
}
"""


def _chip_style(*, accent: str, bg: str, accent_hover: str) -> str:
    return _CHIP_BASE % {
        "accent": accent,
        "bg": bg,
        "accent_hover": accent_hover,
    }


class OutputQuickToggles(QWidget):
    """Pill toggles under the output timecode clock."""

    toggled = Signal(str, bool)  # key: midi | mtc | ltc | notes

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._syncing = False
        self._accent = "#3dd68c"
        self._accent_hover = "#5ee0a8"
        self._accent_bg = "#132218"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._midi = self._make_chip("MIDI", "midi", "Master MIDI output")
        self._mtc = self._make_chip("MTC", "mtc", "MTC Generator (Song Start TC)")
        self._ltc = self._make_chip("LTC", "ltc", "LTC on audio output")
        self._notes = self._make_chip("Notes", "notes", "Send MIDI cue notes at marks")

        for chip in (self._midi, self._mtc, self._ltc, self._notes):
            layout.addWidget(chip)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def _make_chip(self, label: str, key: str, tooltip: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setProperty("toggle_key", key)
        btn.toggled.connect(lambda checked, k=key: self._on_toggled(k, checked))
        return btn

    def set_accent_color(self, color: str) -> None:
        qcolor = QColor(color or "#3dd68c")
        if not qcolor.isValid():
            qcolor = QColor("#3dd68c")
        self._accent = qcolor.name()
        hover = QColor(qcolor)
        hover.setHsv(
            hover.hue(),
            max(0, hover.saturation() - 30),
            min(255, hover.value() + 35),
        )
        self._accent_hover = hover.name()
        bg = QColor(qcolor)
        bg.setAlpha(36)
        self._accent_bg = bg.name(QColor.NameFormat.HexArgb)
        style = _chip_style(
            accent=self._accent,
            bg=self._accent_bg,
            accent_hover=self._accent_hover,
        )
        for chip in (self._midi, self._mtc, self._ltc, self._notes):
            chip.setStyleSheet(style)

    def apply_settings(self, settings: AudioOutputSettings) -> None:
        self._syncing = True
        try:
            self._midi.setChecked(bool(settings.midi_enabled))
            self._mtc.setChecked(bool(settings.mtc_enabled))
            self._ltc.setChecked(bool(settings.ltc_enabled))
            self._notes.setChecked(bool(settings.midi_cue_notes_enabled))
            self._sync_dependent_enabled(settings)
        finally:
            self._syncing = False

    def _sync_dependent_enabled(self, settings: AudioOutputSettings) -> None:
        midi_on = bool(settings.midi_enabled)
        self._mtc.setEnabled(midi_on)
        self._notes.setEnabled(midi_on)
        self._ltc.setEnabled(True)

    def _on_toggled(self, key: str, checked: bool) -> None:
        if self._syncing:
            return
        self.toggled.emit(key, checked)

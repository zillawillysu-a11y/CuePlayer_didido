"""Compact output toggles for the monitor clock (TRANS / Note / MTC / LTC)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from cueplayer.domain.models import AudioOutputSettings

_CHIP_BASE = """
QPushButton {
    min-height: 22px;
    max-height: 22px;
    padding: 1px 8px;
    border-radius: 6px;
    border: none;
    background: transparent;
    color: #71717a;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.2px;
}
QPushButton:hover:enabled {
    background: #222222;
    color: #a1a1aa;
}
QPushButton:checked {
    border: none;
    background: %(bg)s;
    color: %(accent)s;
}
QPushButton:checked:hover:enabled {
    background: %(bg)s;
    color: %(accent_hover)s;
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

    toggled = Signal(str, bool)  # key: translate | note | mtc | ltc

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._syncing = False
        self._accent = "#3dd68c"
        self._accent_hover = "#5ee0a8"
        self._accent_bg = "#132218"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 2)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._translate = self._make_chip(
            "TRANS",
            "translate",
            "Translate file LTC stripe → MTC (auto-enables MIDI)",
        )
        self._note = self._make_chip(
            "Note",
            "note",
            "Send MIDI cue notes at marks (auto-enables MIDI)",
        )
        self._mtc = self._make_chip(
            "MTC",
            "mtc",
            "MTC Generator from Song Start TC (auto-enables MIDI)",
        )
        self._ltc = self._make_chip("LTC", "ltc", "LTC on audio output")

        for chip in (self._translate, self._note, self._mtc, self._ltc):
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

    def _all_chips(self) -> tuple[QPushButton, ...]:
        return self._translate, self._note, self._mtc, self._ltc

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
        for chip in self._all_chips():
            chip.setStyleSheet(style)

    def apply_settings(self, settings: AudioOutputSettings) -> None:
        self._syncing = True
        try:
            self._translate.setChecked(bool(settings.ltc_to_mtc_translate))
            self._note.setChecked(bool(settings.midi_cue_notes_enabled))
            self._mtc.setChecked(bool(settings.mtc_enabled))
            self._ltc.setChecked(bool(settings.ltc_enabled))
        finally:
            self._syncing = False

    def _on_toggled(self, key: str, checked: bool) -> None:
        if self._syncing:
            return
        self.toggled.emit(key, checked)

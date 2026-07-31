"""Compact output toggles for the monitor clock (TRANS / Note / MTC / LTC)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QResizeEvent
from PySide6.QtWidgets import QGridLayout, QPushButton, QSizePolicy, QWidget

from cueplayer.domain.models import AudioOutputSettings

_CHIP_BASE = """
QPushButton {
    min-height: %(height)s;
    max-height: %(height)s;
    padding: %(padding)s;
    border-radius: 6px;
    border: none;
    background: transparent;
    color: #71717a;
    font-size: %(font)s;
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

# Below this inner width, four chips in one row clip (TRANS → "RAN").
_WRAP_WIDTH_PX = 200


def _chip_style(
    *,
    accent: str,
    bg: str,
    accent_hover: str,
    compact: bool,
) -> str:
    return _CHIP_BASE % {
        "accent": accent,
        "bg": bg,
        "accent_hover": accent_hover,
        "height": "20px" if compact else "22px",
        "padding": "1px 3px" if compact else "1px 8px",
        "font": "9px" if compact else "10px",
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
        self._wrapped = False
        self._compact_style = False

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 6, 0, 2)
        self._layout.setHorizontalSpacing(4)
        self._layout.setVerticalSpacing(4)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._translate = self._make_chip(
            "TRANS",
            "translate",
            "When MTC is on, send file LTC stripe numbers instead of Song Start TC",
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

        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self._place_chips(wrapped=False)
        self.set_accent_color(self._accent)

    def _make_chip(self, label: str, key: str, tooltip: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setProperty("toggle_key", key)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        btn.toggled.connect(lambda checked, k=key: self._on_toggled(k, checked))
        return btn

    def _all_chips(self) -> tuple[QPushButton, ...]:
        return self._translate, self._note, self._mtc, self._ltc

    def _row_width_hint(self) -> int:
        chips = self._all_chips()
        return sum(chip.sizeHint().width() for chip in chips) + (
            self._layout.horizontalSpacing() * (len(chips) - 1)
        )

    def _place_chips(self, *, wrapped: bool) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().setParent(self)
        chips = self._all_chips()
        if wrapped:
            # 2×2 so TRANS / Note / MTC / LTC keep readable padding.
            positions = ((0, 0), (0, 1), (1, 0), (1, 1))
            for chip, (row, col) in zip(chips, positions, strict=True):
                self._layout.addWidget(chip, row, col, Qt.AlignmentFlag.AlignCenter)
        else:
            for col, chip in enumerate(chips):
                self._layout.addWidget(chip, 0, col, Qt.AlignmentFlag.AlignCenter)
        self._wrapped = wrapped

    def _apply_styles(self, *, compact: bool) -> None:
        style = _chip_style(
            accent=self._accent,
            bg=self._accent_bg,
            accent_hover=self._accent_hover,
            compact=compact,
        )
        for chip in self._all_chips():
            chip.setStyleSheet(style)
        self._compact_style = compact

    def _fit_to_width(self) -> None:
        width = self.width()
        if width <= 1:
            return
        # Prefer wrap before crushing chip text; also compact style when tight.
        need = self._row_width_hint()
        wrapped = width < max(_WRAP_WIDTH_PX, need + 4)
        compact = wrapped or width < need + 24
        if wrapped != self._wrapped:
            self._place_chips(wrapped=wrapped)
        if compact != self._compact_style:
            self._apply_styles(compact=compact)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_to_width()

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        self._fit_to_width()

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
        self._apply_styles(compact=self._compact_style)

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

"""Checkboxes with a visible tick (Fusion + global QSS hides the default mark)."""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtWidgets import QCheckBox

_ASSETS = Path(__file__).resolve().parent / "assets"
_CHECKMARK_B64 = base64.b64encode((_ASSETS / "checkmark.png").read_bytes()).decode("ascii")

_CHECKBOX_QSS = f"""
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #333333;
    border-radius: 3px;
    background: #0a0a0a;
}}
QCheckBox::indicator:checked {{
    background: #5a5a5a;
    border-color: #5a5a5a;
    image: url(data:image/png;base64,{_CHECKMARK_B64});
}}
QCheckBox::indicator:hover {{
    border-color: #8a8a8a;
}}
QCheckBox::indicator:checked:hover {{
    background: #8a8a8a;
    border-color: #8a8a8a;
}}
QCheckBox::indicator:disabled {{
    background: #1a1a1a;
    border-color: #1f1f1f;
}}
"""


class TickCheckBox(QCheckBox):
    """QCheckBox that always paints a white checkmark when checked."""

    def __init__(self, text: str = "", parent=None) -> None:  # noqa: ANN001
        super().__init__(text, parent)
        self.setStyleSheet(_CHECKBOX_QSS)

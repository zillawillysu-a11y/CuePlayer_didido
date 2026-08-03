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
    border: 1px solid #3f3f46;
    border-radius: 3px;
    background: #0c0c0e;
}}
QCheckBox::indicator:checked {{
    background: #4a9eff;
    border-color: #4a9eff;
    image: url(data:image/png;base64,{_CHECKMARK_B64});
}}
QCheckBox::indicator:hover {{
    border-color: #79b8ff;
}}
QCheckBox::indicator:checked:hover {{
    background: #79b8ff;
    border-color: #79b8ff;
}}
QCheckBox::indicator:disabled {{
    background: #18181b;
    border-color: #27272a;
}}
"""


class TickCheckBox(QCheckBox):
    """QCheckBox that always paints a white checkmark when checked."""

    def __init__(self, text: str = "", parent=None) -> None:  # noqa: ANN001
        super().__init__(text, parent)
        self.setStyleSheet(_CHECKBOX_QSS)

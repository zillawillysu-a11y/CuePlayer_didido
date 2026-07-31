from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_ndi_runtime_missing_message_mentions_tools_runtime() -> None:
    from cueplayer.playback.ndi_output import ndi_runtime_missing_message

    text = ndi_runtime_missing_message()
    assert "NDI Tools / Runtime" in text
    assert "restart CuePlayer" in text


def test_ndi_install_required_detects_runtime_errors() -> None:
    from cueplayer.playback.ndi_output import ndi_install_required, ndi_runtime_missing_message

    assert not ndi_install_required(None)
    assert not ndi_install_required("")
    assert ndi_install_required(ndi_runtime_missing_message("DLL load failed"))
    assert ndi_install_required("Processing.NDI.Lib.x64.dll not found")
    assert ndi_install_required("NDI open failed: cannot load shared library")


def test_ndi_install_dialog_has_links(app: QApplication) -> None:
    from cueplayer.playback.ndi_output import NDI_RUNTIME_URL, NDI_TOOLS_URL
    from cueplayer.ui.ndi_install_dialog import NdiInstallDialog

    dlg = NdiInstallDialog(detail="DLL load failed")
    joined = "\n".join(lb.text() for lb in dlg.findChildren(QLabel))
    assert NDI_TOOLS_URL in joined
    assert NDI_RUNTIME_URL in joined
    assert "ndi.video" in joined
    assert "DLL load failed" in joined
    dlg.close()

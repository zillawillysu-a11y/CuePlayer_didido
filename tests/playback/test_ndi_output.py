"""NDI output helper (optional cyndilib)."""

from __future__ import annotations

import numpy as np

from cueplayer.playback.ndi_output import NdiVideoOutput, ndi_available, ndi_status


def test_ndi_status_string() -> None:
    text = ndi_status()
    assert "NDI" in text
    assert isinstance(ndi_available(), bool)


def test_ndi_configure_disabled_is_noop() -> None:
    out = NdiVideoOutput()
    assert out.configure(enabled=False) is None
    assert out.enabled is False
    out.send_frame(np.zeros((4, 4, 3), dtype=np.uint8))
    out.close()


def test_rgb_to_rgbx_bytes() -> None:
    from cueplayer.playback.ndi_output import _rgb_to_rgbx_bytes

    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    rgb[0, 0] = (10, 20, 30)
    flat = _rgb_to_rgbx_bytes(rgb)
    assert flat.shape == (2 * 2 * 4,)
    assert list(flat[0:4]) == [10, 20, 30, 255]


def test_ndi_configure_without_library_returns_error() -> None:
    if ndi_available():
        return
    out = NdiVideoOutput()
    err = out.configure(enabled=True, name="CuePlayerTest")
    assert err is not None
    assert "cyndilib" in err or "NDI" in err
    assert out.enabled is False

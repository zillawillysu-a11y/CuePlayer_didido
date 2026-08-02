"""NDI output helper (optional cyndilib)."""

from __future__ import annotations

import numpy as np

from cueplayer.playback.ndi_output import (
    NdiVideoOutput,
    _build_fit_maps,
    _pack_rgbx_into,
    ndi_available,
    ndi_status,
)


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


def test_fit_maps_and_pack_rgbx() -> None:
    y_idx, x_idx, y0, x0, nh, nw = _build_fit_maps(10, 20, 40, 20, fit_mode="fit")
    assert nh > 0 and nw > 0
    y_idx2, x_idx2, y02, x02, nh2, nw2 = _build_fit_maps(
        10, 20, 40, 20, fit_mode="fill"
    )
    assert nh2 == 20 and nw2 == 40
    flat = np.zeros(20 * 40 * 4, dtype=np.uint8)
    canvas = np.zeros((20, 40, 3), dtype=np.uint8)
    _pack_rgbx_into(flat, canvas)
    assert flat.reshape(20, 40, 4)[0, 0, 3] == 255
    del y_idx, x_idx, y0, x0, y_idx2, x_idx2, y02, x02


def test_ndi_configure_without_library_returns_error() -> None:
    if ndi_available():
        return
    out = NdiVideoOutput()
    err = out.configure(enabled=True, name="CuePlayerTest", frame_mode="video")
    assert err is not None
    assert "cyndilib" in err or "NDI" in err
    assert out.enabled is False


def test_ndi_frame_mode_persists_default() -> None:
    out = NdiVideoOutput()
    assert out.configure(enabled=False, frame_mode="video") is None
    assert out.frame_mode == "video"
    assert out.configure(enabled=False, frame_mode="output_window") is None
    assert out.frame_mode == "output_window"


def test_send_frame_queues_when_disabled_is_noop() -> None:
    out = NdiVideoOutput()
    out.send_frame(np.zeros((8, 8, 3), dtype=np.uint8))
    out.close()

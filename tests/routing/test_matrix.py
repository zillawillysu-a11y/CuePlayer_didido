"""Routing matrix unit tests."""

from __future__ import annotations

import numpy as np
import pytest

from cueplayer.routing.matrix import apply_routing, warn_if_outputs_insufficient


def test_route_ltc_left_music_right_to_three_outputs() -> None:
    # one frame: L=0.5 (LTC), R=0.25 (Music)
    src = np.array([[0.5, 0.25]], dtype=np.float32)
    out = apply_routing(src, route={0: [2], 1: [0, 1]}, output_channels=4)
    assert out.shape == (1, 4)
    assert out[0, 0] == pytest.approx(0.25)
    assert out[0, 1] == pytest.approx(0.25)
    assert out[0, 2] == pytest.approx(0.5)
    assert out[0, 3] == pytest.approx(0.0)


def test_warn_when_device_too_small() -> None:
    msg = warn_if_outputs_insufficient([0, 1, 2], available=2)
    assert msg is not None
    assert "3" in msg

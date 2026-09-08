"""BPM detect must not depend on Numba/librosa in the hot path."""

from __future__ import annotations

import os

import numpy as np
import pytest

from cueplayer.media.bpm_analyzer import (
    BPM_DETECT_VERSION,
    estimate_bpm,
    estimate_bpm_from_path,
    run_bpm_detect_cli,
    warmup_bpm_analyzer,
)
from cueplayer.media.bpm_native import configure_bpm_native_runtime


def _click_track(bpm: float, *, seconds: float = 16.0, sr: int = 44100) -> np.ndarray:
    period = int(round(sr * 60.0 / bpm))
    n = int(sr * seconds)
    mono = np.zeros(n, dtype=np.float32)
    for i in range(0, n - 200, period):
        mono[i : i + 120] = 1.0
    return mono.reshape(-1, 1)


def test_configure_forces_numba_jit_off() -> None:
    os.environ.pop("NUMBA_DISABLE_JIT", None)
    configure_bpm_native_runtime()
    assert os.environ.get("NUMBA_DISABLE_JIT") == "1"
    assert os.environ.get("NUMBA_CACHE_DIR")


def test_warmup_and_estimate_without_librosa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Frozen crash path: detect must work even if librosa import fails."""
    import builtins

    real_import = builtins.__import__

    def _block_librosa(name, *args, **kwargs):  # noqa: ANN001
        if name == "librosa" or name.startswith("librosa."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_librosa)
    warmup_bpm_analyzer()
    est = estimate_bpm(_click_track(128.0), 44100)
    assert est is not None
    assert abs(float(est) - 128.0) <= 1.0


def test_bpm_detect_cli_writes_result(tmp_path) -> None:  # noqa: ANN001
    import soundfile as sf

    wav = tmp_path / "click.wav"
    sf.write(str(wav), _click_track(120.0)[:, 0], 44100)
    out = tmp_path / "out.json"
    progress = tmp_path / "progress.txt"
    os.environ["CUEPLAYER_BPM_INNER"] = "1"
    rc = run_bpm_detect_cli(["--bpm-detect", str(wav), str(out), str(progress), ""])
    assert rc == 0
    assert out.is_file()
    assert '"bpm"' in out.read_text(encoding="utf-8")
    assert BPM_DETECT_VERSION >= 15


def test_estimate_bpm_from_path_inner_skips_subprocess(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    import soundfile as sf

    wav = tmp_path / "click.wav"
    sf.write(str(wav), _click_track(120.0)[:, 0], 44100)
    os.environ["CUEPLAYER_BPM_INNER"] = "1"
    monkeypatch.setattr(
        "cueplayer.media.bpm_analyzer._estimate_bpm_via_subprocess",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocess should not run")),
    )
    est = estimate_bpm_from_path(wav)
    assert est is not None
    assert abs(float(est) - 120.0) <= 1.0

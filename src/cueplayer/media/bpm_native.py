"""Native runtime guards for BPM detect (Numba / PyInstaller).

Frozen Windows builds often abort inside Numba/llvmlite during the first
librosa onset/STFT call (~30% progress). Disable JIT early and keep a
writable cache dir so a partial Numba load cannot kill CuePlayer.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def configure_bpm_native_runtime() -> None:
    """Set Numba env vars before any librosa/numba import.

    Safe to call repeatedly. Must run at process start for frozen builds.
    Always disable JIT — PyInstaller + llvmlite aborts are hard process exits
    (BPM detect flash-quit near 30%). Librosa still works, just slower.
    """
    os.environ["NUMBA_DISABLE_JIT"] = "1"
    # Always point cache at a writable temp dir (Program Files is read-only).
    if "NUMBA_CACHE_DIR" not in os.environ:
        cache = Path(tempfile.gettempdir()) / "cueplayer_numba_cache"
        try:
            cache.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            cache = Path(tempfile.gettempdir())
        os.environ["NUMBA_CACHE_DIR"] = str(cache)
    os.environ.setdefault("NUMBA_DEBUG_CACHE", "0")

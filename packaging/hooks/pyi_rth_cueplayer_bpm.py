# PyInstaller runtime hook — must run before BPM / librosa imports.
import os
import tempfile
from pathlib import Path

os.environ["NUMBA_DISABLE_JIT"] = "1"
cache = Path(tempfile.gettempdir()) / "cueplayer_numba_cache"
try:
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["NUMBA_CACHE_DIR"] = str(cache)
except Exception:
    os.environ.setdefault("NUMBA_CACHE_DIR", tempfile.gettempdir())

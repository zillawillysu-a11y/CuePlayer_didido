"""Local LAN Web Remote (Safari / iPad control surface).

Windows CuePlayer is the session server (timeline, cues, LTC, export).
The remote is control-only in v1 — no monitor audio stream yet.
"""

from cueplayer.web_remote.prefs import (
    WebRemotePrefs,
    load_web_remote_prefs,
    save_web_remote_prefs,
)

__all__ = [
    "WebRemotePrefs",
    "load_web_remote_prefs",
    "save_web_remote_prefs",
]

"""Local LAN Web Remote (Safari / iPad control surface).

Windows CuePlayer is the session server (timeline, cues, LTC, export).
The remote can control transport/marks and optionally listen to a music-only
monitor stream (no LTC) over the LAN — latency is listen-along, not cue-critical.
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

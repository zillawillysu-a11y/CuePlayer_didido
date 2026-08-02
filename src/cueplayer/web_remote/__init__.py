"""Local LAN Web Remote (Safari / iPad control surface).

Windows CuePlayer is the session server (timeline, cues, LTC, export).
The remote controls transport/marks and can Listen to music (or video audio
when there is no music file):

- Primary: WebRTC (Opus / UDP) — Sunshine-class low-latency monitor
- Fallback: HTTP PCM chunks when WebRTC is unavailable
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

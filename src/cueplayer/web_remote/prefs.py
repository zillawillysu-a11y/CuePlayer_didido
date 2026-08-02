"""Machine-global Web Remote preferences (QSettings)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

_SETTINGS_ORG = "CuePlayer"
_SETTINGS_APP = "CuePlayer"

_KEY_ENABLED = "web_remote/enabled"
_KEY_PORT = "web_remote/port"
_KEY_PASSWORD = "web_remote/password"
_KEY_BIND_LAN = "web_remote/bind_lan"

DEFAULT_PORT = 8765


@dataclass
class WebRemotePrefs:
    enabled: bool = False
    port: int = DEFAULT_PORT
    password: str = ""
    # True → bind 0.0.0.0 (LAN); False → 127.0.0.1 only.
    bind_lan: bool = True

    def normalized_port(self) -> int:
        try:
            port = int(self.port)
        except (TypeError, ValueError):
            return DEFAULT_PORT
        if port < 1024 or port > 65535:
            return DEFAULT_PORT
        return port


def _settings() -> QSettings:
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def load_web_remote_prefs() -> WebRemotePrefs:
    store = _settings()
    raw_port = store.value(_KEY_PORT, DEFAULT_PORT)
    try:
        port = int(raw_port)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    password = store.value(_KEY_PASSWORD, "")
    if not isinstance(password, str):
        password = str(password or "")
    enabled_raw = store.value(_KEY_ENABLED, False)
    bind_raw = store.value(_KEY_BIND_LAN, True)
    return WebRemotePrefs(
        enabled=_as_bool(enabled_raw),
        port=port,
        password=password,
        bind_lan=_as_bool(bind_raw),
    )


def save_web_remote_prefs(prefs: WebRemotePrefs) -> None:
    store = _settings()
    store.setValue(_KEY_ENABLED, bool(prefs.enabled))
    store.setValue(_KEY_PORT, int(prefs.normalized_port()))
    store.setValue(_KEY_PASSWORD, str(prefs.password or ""))
    store.setValue(_KEY_BIND_LAN, bool(prefs.bind_lan))
    store.sync()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in ("1", "true", "yes", "on")

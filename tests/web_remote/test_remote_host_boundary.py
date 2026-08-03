"""RemoteHost boundary: bridge must not duck-type MainWindow privates."""

from __future__ import annotations

import ast
from pathlib import Path

from cueplayer.ports.remote_host import RemoteEnginePort, RemoteHost
from cueplayer.web_remote.main_window_remote_host import MainWindowRemoteHost


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "src" / "cueplayer" / "web_remote" / "bridge.py"
ADAPTER = ROOT / "src" / "cueplayer" / "web_remote" / "main_window_remote_host.py"


def test_bridge_has_no_host_private_attribute_access() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            # Allow self._* (bridge internals) and module-level privates.
            if isinstance(node.value, ast.Name) and node.value.id == "host":
                banned.append(f"host.{node.attr}")
            if (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr == "_host"
                and node.attr.startswith("_")
            ):
                banned.append(f"self._host.{node.attr}")
    assert banned == [], f"bridge still touches host privates: {banned}"


def test_bridge_has_no_engine_private_attribute_access() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not node.attr.startswith("_"):
            continue
        # engine._video_mixer / _playback_rate / _song
        if isinstance(node.value, ast.Name) and node.value.id == "engine":
            banned.append(f"engine.{node.attr}")
    assert banned == [], f"bridge still touches engine privates: {banned}"


def test_bridge_does_not_reference_monitor_timeline_status_attrs() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    for needle in ("host.monitor.", "host.timeline.", "host.status."):
        assert needle not in source


def test_adapter_file_is_the_only_main_window_private_shim() -> None:
    assert ADAPTER.is_file()
    source = ADAPTER.read_text(encoding="utf-8")
    assert "_mark_dirty" in source
    assert "MainWindowRemoteHost" in source


def test_remote_host_protocols_are_runtime_checkable() -> None:
    assert getattr(RemoteHost, "_is_runtime_protocol", False) is True
    assert getattr(RemoteEnginePort, "_is_runtime_protocol", False) is True


def test_main_window_remote_host_is_importable() -> None:
    assert MainWindowRemoteHost is not None

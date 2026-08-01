"""Startup / BPM worker must not crash on Windows cp950 consoles."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from cueplayer import app as app_mod


def test_boot_log_survives_cp950_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Song paths with 个 (U+4E2A) used to UnicodeEncodeError on Traditional Chinese Windows."""

    class Cp950Stdout(io.TextIOBase):
        encoding = "cp950"

        def write(self, s: str) -> int:  # noqa: D401
            s.encode("cp950")  # raises on 个
            return len(s)

        def flush(self) -> None:
            return None

    monkeypatch.setattr(app_mod.sys, "stdout", Cp950Stdout())
    monkeypatch.setattr(app_mod.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.chdir(tmp_path)

    # Must not raise — same path shape as frozen ``--bpm-detect`` argv logging.
    app_mod._boot_log(r"argv=['CuePlayer.exe', '--bpm-detect', 'D:\\Media\\講袂出嘴的彼个字.wav']")

    log = tmp_path / "cueplayer_startup.log"
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    assert "彼个字" in text


def test_bpm_detect_cli_entry_runs_before_boot_log(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_cli(argv: list[str]) -> int:
        calls.append("cli")
        return 0

    def boom_boot(message: str) -> None:
        calls.append("boot")
        raise AssertionError(f"boot log should not run for BPM worker: {message}")

    monkeypatch.setattr(app_mod, "_boot_log", boom_boot)
    monkeypatch.setattr(
        "cueplayer.media.bpm_analyzer.run_bpm_detect_cli",
        fake_cli,
        raising=False,
    )

    # Patch import path used inside main().
    import cueplayer.media.bpm_analyzer as bpm_mod

    monkeypatch.setattr(bpm_mod, "run_bpm_detect_cli", fake_cli)
    monkeypatch.setattr(app_mod.sys, "argv", ["CuePlayer.exe", "--bpm-detect", "a.wav", "o.json", "p.txt"])

    assert app_mod.main() == 0
    assert calls == ["cli"]

"""NDI probe / Runtime path helpers (no real NDI install required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cueplayer.playback import ndi_output as ndi_mod


def test_ensure_ndi_runtime_search_path_adds_dll_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "NDI" / "NDI 6 Runtime" / "v6"
    runtime.mkdir(parents=True)
    (runtime / ndi_mod._NDI_DLL_NAME).write_bytes(b"fake")

    monkeypatch.setattr(ndi_mod.sys, "platform", "win32")
    monkeypatch.setattr(ndi_mod, "_program_files_roots", lambda: [tmp_path])
    monkeypatch.delenv("PATH", raising=False)
    monkeypatch.setenv("PATH", "")

    added_dirs: list[str] = []

    def _fake_add(path: str) -> object:
        added_dirs.append(path)
        return object()

    monkeypatch.setattr(ndi_mod.os, "add_dll_directory", _fake_add, raising=False)

    added = ndi_mod.ensure_ndi_runtime_search_path()
    assert added == [str(runtime.resolve())]
    assert str(runtime.resolve()) in ndi_mod.os.environ.get("PATH", "")
    assert added_dirs == [str(runtime.resolve())]


def test_ndi_status_missing_package_mentions_pip_not_only_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ndi_mod.sys, "frozen", False, raising=False)
    monkeypatch.setattr(
        ndi_mod,
        "ndi_probe",
        lambda force=False: ndi_mod.NdiProbe(
            False, "missing_package", "No module named 'cyndilib'"
        ),
    )
    text = ndi_mod.ndi_status()
    assert "cyndilib" in text
    assert "pip install" in text
    assert "NDI Tools alone is not enough" in text


def test_ndi_failure_kind_uses_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ndi_mod,
        "ndi_probe",
        lambda force=False: ndi_mod.NdiProbe(
            False, "missing_package", "No module named 'cyndilib'"
        ),
    )
    assert ndi_mod.ndi_failure_kind("anything") == "missing_package"
    assert ndi_mod.ndi_install_required("No module named 'cyndilib'")

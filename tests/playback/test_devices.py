"""Tests for output device listing / dedupe."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from cueplayer.playback import devices as devices_mod
from cueplayer.playback.devices import (
    OutputDeviceInfo,
    filter_output_devices,
    find_output_device,
    resolve_output_samplerate,
    upgrade_device_for_channels,
)


def _dev(
    index: int,
    name: str,
    *,
    ch: int = 2,
    api: str = "Windows WASAPI",
) -> OutputDeviceInfo:
    return OutputDeviceInfo(
        index=index,
        name=name,
        max_output_channels=ch,
        default_samplerate=48000.0,
        hostapi_name=api,
    )


def test_filter_keeps_one_entry_preferring_wasapi() -> None:
    devices = [
        _dev(0, "Speakers (Realtek)", api="MME", ch=2),
        _dev(1, "Speakers (Realtek)", api="Windows DirectSound", ch=2),
        _dev(2, "Speakers (Realtek)", api="Windows WASAPI", ch=2),
        _dev(3, "Speakers (Realtek)", api="Windows WDM-KS", ch=2),
        _dev(4, "CABLE In 16ch", api="MME", ch=16),
        _dev(5, "CABLE In 16ch", api="Windows WASAPI", ch=16),
    ]
    filtered = filter_output_devices(devices)
    assert len(filtered) == 2
    by_name = {d.name: d for d in filtered}
    assert by_name["Speakers (Realtek)"].hostapi_name == "Windows WASAPI"
    assert by_name["CABLE In 16ch"].hostapi_name == "Windows WASAPI"


def test_filter_prefers_16ch_mme_over_2ch_wasapi() -> None:
    """VB-Cable often exposes full channel count only on MME/DS."""
    devices = [
        _dev(0, "CABLE In 16ch (VB-Audio Virtual Cable)", api="Windows WASAPI", ch=2),
        _dev(1, "CABLE In 16ch (VB-Audio Virtual C", api="MME", ch=16),
    ]
    filtered = filter_output_devices(devices)
    assert len(filtered) == 1
    assert filtered[0].max_output_channels == 16
    assert filtered[0].index == 1
    # Keep the longer/clearer name.
    assert "VB-Audio Virtual Cable)" in filtered[0].name


def test_filter_merges_truncated_mme_names() -> None:
    devices = [
        _dev(0, "1 - Mi monitor (AMD High Definition Audio Device)", api="Windows WASAPI"),
        _dev(1, "1 - Mi monitor (AMD High Defini", api="MME"),
    ]
    filtered = filter_output_devices(devices)
    assert len(filtered) == 1
    assert filtered[0].hostapi_name == "Windows WASAPI"


def test_filter_drops_junk_bluetooth_and_empty_names() -> None:
    devices = [
        _dev(0, "Good Device", api="Windows WASAPI"),
        _dev(1, "耳機 ()", api="Windows WDM-KS"),
        _dev(
            2,
            "AirPods Pro (@System32\\drivers\\bthhfenum.sys,#2;...)",
            api="Windows WDM-KS",
        ),
        _dev(3, "Primary Sound Driver", api="MME"),
    ]
    filtered = filter_output_devices(devices)
    assert [d.name for d in filtered] == ["Good Device"]


def test_filter_prefers_more_channels_when_same_api_rank() -> None:
    devices = [
        _dev(0, "Focusrite", api="Windows WASAPI", ch=2),
        _dev(1, "Focusrite", api="Windows WASAPI", ch=8),
    ]
    filtered = filter_output_devices(devices)
    assert len(filtered) == 1
    assert filtered[0].max_output_channels == 8


def test_upgrade_device_for_channels_picks_multichannel_sibling() -> None:
    """Stored 2ch index must upgrade to 8ch sibling for LTC→CH3."""
    raw = [
        _dev(0, "Focusrite USB", api="Windows WASAPI", ch=2),
        _dev(1, "Focusrite USB", api="Windows WASAPI", ch=8),
    ]
    base = _dev(0, "Focusrite USB", api="Windows WASAPI", ch=2)
    upgraded = upgrade_device_for_channels(base, min_channels=3, raw_devices=raw)
    assert upgraded.index == 1
    assert upgraded.max_output_channels == 8


def test_resolve_output_endpoint_prefers_asio_multichannel(monkeypatch) -> None:
    stereo = _dev(0, "Speakers (Focusrite USB)", ch=2)
    asio = _dev(3, "Focusrite USB ASIO", api="ASIO", ch=8)
    monkeypatch.setattr(devices_mod.sd, "check_output_settings", lambda **kwargs: None)
    picked = devices_mod.resolve_output_endpoint_for_channels(
        preferred_name="Focusrite USB",
        min_channels=3,
        samplerate=48000.0,
        raw_devices=[stereo, asio],
    )
    assert picked is not None
    assert picked.index == 3
    assert picked.max_output_channels == 8


def test_engine_ltc_route_opens_three_channels_on_focusrite(monkeypatch) -> None:
    """Regression: LTC→CH3 must not collapse to stereo Ch1+2 on multi-out interfaces."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from cueplayer.domain.models import AudioOutputSettings
    from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
    from cueplayer.playback import audio_engine as eng_mod

    stereo = _dev(0, "Focusrite USB", ch=2)
    multi = _dev(1, "Focusrite USB", ch=8)
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [multi] if dedupe else [stereo, multi])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    settings = AudioOutputSettings(
        output_device_name="Focusrite USB",
        ltc_enabled=True,
        ltc_channels=[2],
    )
    engine.apply_audio_settings(settings)
    n = int(48000 * 0.5)
    tone = __import__("numpy").zeros((n, 2), dtype=__import__("numpy").float32)
    mono, levels = build_peak_pyramid(tone, 48000)
    engine.set_buffer(AudioBuffer(path="x.wav", sample_rate=48000, samples=tone, mono=mono, peak_levels=levels))

    assert engine._device_index == 1
    assert engine._output_channel_count >= 3
    assert engine._route.get(2) == [2]


def test_probe_failure_switches_to_asio_multichannel(monkeypatch) -> None:
    """When WASAPI only opens 2ch but ASIO supports LTC→CH3, switch endpoints."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from cueplayer.domain.models import AudioOutputSettings
    from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
    from cueplayer.playback import audio_engine as eng_mod

    stereo = _dev(0, "Focusrite USB", ch=2)
    asio = _dev(3, "Focusrite USB ASIO", api="ASIO", ch=8)

    def fake_list(dedupe=True):
        return [asio] if dedupe else [stereo, asio]

    monkeypatch.setattr(eng_mod, "list_output_devices", fake_list)

    def fake_probe(device_index, *, min_channels, samplerate):
        if device_index == 0:
            return 2
        if device_index == 3:
            return 8
        return min_channels

    monkeypatch.setattr(eng_mod, "probe_supported_output_channels", fake_probe)
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    settings = AudioOutputSettings(
        output_device_name="Focusrite USB",
        ltc_enabled=True,
        ltc_source="source_left",
        ltc_channels=[2],
    )
    engine.apply_audio_settings(settings)
    n = int(48000 * 0.5)
    tone = __import__("numpy").zeros((n, 2), dtype=__import__("numpy").float32)
    mono, levels = build_peak_pyramid(tone, 48000)
    engine.set_buffer(AudioBuffer(path="x.wav", sample_rate=48000, samples=tone, mono=mono, peak_levels=levels))

    assert engine._device_index == 3
    assert engine._output_channel_count >= 3
    assert engine._route.get(2) == [2]


def test_picker_hostapi_options_lists_asio_first_without_default_bucket(monkeypatch) -> None:
    monkeypatch.setattr(
        devices_mod,
        "hostapi_names",
        lambda: ["ASIO", "Windows WASAPI", "Windows DirectSound", "MME"],
    )
    options = devices_mod.picker_hostapi_options()
    labels = [label for label, _api in options]
    apis = [api for _label, api in options]
    assert "Default" not in " ".join(labels)
    assert apis[0] == "ASIO"
    assert labels[0] == "ASIO"
    assert devices_mod.default_picker_hostapi() == "ASIO"
    assert devices_mod.resolve_output_hostapi("") == "ASIO"
    assert devices_mod.resolve_output_hostapi("Windows WASAPI") == "Windows WASAPI"


def test_list_output_devices_for_picker_keeps_asio_and_multichannel_ds(monkeypatch) -> None:
    """Routing dialog must list ASIO separately and keep 4ch DirectSound siblings."""
    stereo = _dev(0, "Speakers (Focusrite USB)", api="Windows WASAPI", ch=2)
    ds4 = _dev(1, "喇叭 (2- Focusrite USB Audio)", api="Windows DirectSound", ch=4)
    asio = _dev(2, "Focusrite USB ASIO", api="ASIO", ch=8)
    raw = [stereo, ds4, asio]

    def fake_list(*, dedupe=True):
        return devices_mod.filter_output_devices(raw) if dedupe else raw

    monkeypatch.setattr(devices_mod, "list_output_devices", fake_list)
    out_default = devices_mod.list_output_devices_for_picker()
    out_ds = devices_mod.list_output_devices_for_picker("Windows DirectSound")
    apis = {d.hostapi_name for d in out_default}
    assert "ASIO" in apis
    assert any(d.hostapi_name == "ASIO" and d.max_output_channels == 8 for d in out_default)
    assert all(d.hostapi_name == "Windows DirectSound" for d in out_ds)
    assert any(d.max_output_channels == 4 for d in out_ds)


def test_play_pause_reuses_stream_without_reopen(monkeypatch) -> None:
    """Toggling transport must not tear down/recreate the PortAudio stream each time."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from cueplayer.domain.models import AudioOutputSettings
    from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
    from cueplayer.playback import audio_engine as eng_mod

    device = _dev(0, "Test Out", ch=2)
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [device])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    opens = 0
    closes = 0

    class FakeStream:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            nonlocal closes
            closes += 1

    def fake_output_stream(**kwargs):
        nonlocal opens
        opens += 1
        return FakeStream()

    monkeypatch.setattr(eng_mod.sd, "OutputStream", fake_output_stream)

    QApplication.instance() or QApplication([])
    engine = eng_mod.AudioEngine()
    engine.apply_audio_settings(AudioOutputSettings(output_device_name="Test Out"))
    n = int(48000 * 0.25)
    tone = __import__("numpy").zeros((n, 2), dtype=__import__("numpy").float32)
    mono, levels = build_peak_pyramid(tone, 48000)
    engine.set_buffer(AudioBuffer(path="x.wav", sample_rate=48000, samples=tone, mono=mono, peak_levels=levels))

    engine.play()
    assert opens == 1
    engine.pause()
    assert closes == 0
    engine.play()
    assert opens == 1
    engine.pause()
    assert closes == 0
    # Stream stays warm until audio is no longer needed or routing changes.
    engine._stop_stream()
    assert closes == 1


def test_filter_drops_wdm_ks_clutter_without_wasapi_sibling() -> None:
    """
    WDM-KS exposes raw per-jack / virtual endpoints Windows itself hides
    from the tray (HAP sub-speakers, Intelligo line-outs, HDMI, VB-Audio
    Point, Steam Streaming). None of these have a matching WASAPI name, so
    once real WASAPI endpoints exist they should not appear at all.
    """
    devices = [
        _dev(0, "Speakers (Realtek(R) Audio)", api="Windows WASAPI", ch=2),
        _dev(1, "Speakers 1 (Realtek HD Audio output with HAP)", api="Windows WDM-KS", ch=2),
        _dev(2, "Speakers 2 (Realtek HD Audio output with HAP)", api="Windows WDM-KS", ch=2),
        _dev(3, "Headphones (Realtek HD Audio 2nd output)", api="Windows WDM-KS", ch=2),
        _dev(4, "Line Out 1 (Intelligo VAC (W))", api="Windows WDM-KS", ch=2),
        _dev(5, "Output (AMD HD Audio HDMI out #0)", api="Windows WDM-KS", ch=2),
        _dev(6, "Output (VB-Audio Point)", api="Windows WDM-KS", ch=16),
        _dev(7, "Speakers (Steam Streaming Speakers Wave)", api="Windows WDM-KS", ch=8),
    ]
    filtered = filter_output_devices(devices)
    assert [d.name for d in filtered] == ["Speakers (Realtek(R) Audio)"]


def test_filter_keeps_wasapi_only_extras_like_asus_ai_noise_cancelling() -> None:
    """Extra WASAPI-native endpoints (no dedup target) still show up as-is."""
    devices = [
        _dev(0, "Speakers (Realtek(R) Audio)", api="Windows WASAPI", ch=2),
        _dev(1, "AI Noise-cancelling Output (ASUS Utility)", api="Windows WASAPI", ch=2),
    ]
    filtered = filter_output_devices(devices)
    assert {d.name for d in filtered} == {
        "Speakers (Realtek(R) Audio)",
        "AI Noise-cancelling Output (ASUS Utility)",
    }


def test_filter_keeps_asio_only_device_with_no_wasapi_sibling() -> None:
    """ASIO is a seed rank too (pro audio interfaces), so it stands alone."""
    devices = [
        _dev(0, "Speakers (Realtek(R) Audio)", api="Windows WASAPI", ch=2),
        _dev(1, "Focusrite USB ASIO", api="ASIO", ch=8),
    ]
    filtered = filter_output_devices(devices)
    assert {d.name for d in filtered} == {
        "Speakers (Realtek(R) Audio)",
        "Focusrite USB ASIO",
    }


def test_filter_falls_back_to_all_devices_without_wasapi_or_asio() -> None:
    """Non-Windows host APIs (Core Audio, ALSA, JACK) have no WASAPI rank;
    nothing should be dropped just because there is no rank-0 seed."""
    devices = [
        _dev(0, "Built-in Output", api="Core Audio", ch=2),
        _dev(1, "USB Audio Device", api="Core Audio", ch=2),
    ]
    filtered = filter_output_devices(devices)
    assert {d.name for d in filtered} == {"Built-in Output", "USB Audio Device"}


def test_filter_realistic_windows_snapshot_matches_tray_closely() -> None:
    """
    Regression test approximating the reported real-world device list: 37
    raw PortAudio endpoints across MME/DirectSound/WASAPI/WDM-KS should
    collapse to roughly the 4-5 endpoints Windows' own tray shows.
    """
    devices = [
        _dev(0, "Microsoft 音效对应器 - Output", api="MME", ch=2),
        _dev(1, "喇叭 (Realtek(R) Audio)", api="MME", ch=2),
        _dev(2, "CABLE Input (VB-Audio Virtual C", api="MME", ch=16),
        _dev(3, "CABLE In 16ch (VB-Audio Virtual", api="MME", ch=16),
        _dev(4, "1 - Mi monitor (AMD High Defini", api="MME", ch=2),
        _dev(5, "AI Noise-cancelling Output (ASU", api="MME", ch=2),
        _dev(6, "主要声音驱动程序", api="Windows DirectSound", ch=2),
        _dev(7, "喇叭 (Realtek(R) Audio)", api="Windows DirectSound", ch=2),
        _dev(8, "CABLE Input (VB-Audio Virtual Cable)", api="Windows DirectSound", ch=16),
        _dev(9, "CABLE In 16ch (VB-Audio Virtual Cable)", api="Windows DirectSound", ch=16),
        _dev(10, "1 - Mi monitor (AMD High Definition Audio Device)", api="Windows DirectSound", ch=2),
        _dev(11, "AI Noise-cancelling Output (ASUS Utility)", api="Windows DirectSound", ch=2),
        _dev(12, "CABLE Input (VB-Audio Virtual Cable)", api="Windows WASAPI", ch=2),
        _dev(13, "CABLE In 16ch (VB-Audio Virtual Cable)", api="Windows WASAPI", ch=2),
        _dev(14, "喇叭 (Realtek(R) Audio)", api="Windows WASAPI", ch=2),
        _dev(15, "1 - Mi monitor (AMD High Definition Audio Device)", api="Windows WASAPI", ch=2),
        _dev(16, "AI Noise-cancelling Output (ASUS Utility)", api="Windows WASAPI", ch=2),
        _dev(17, "Output (VB-Audio Point)", api="Windows WDM-KS", ch=16),
        _dev(18, "Speakers 1 (Realtek HD Audio output with HAP)", api="Windows WDM-KS", ch=2),
        _dev(19, "Speakers 2 (Realtek HD Audio output with HAP)", api="Windows WDM-KS", ch=2),
        _dev(20, "Headphones (Realtek HD Audio 2nd output)", api="Windows WDM-KS", ch=2),
        _dev(21, "Line Out 1 (Intelligo VAC (W))", api="Windows WDM-KS", ch=2),
        _dev(22, "Line Out 2 (Intelligo VAC (W))", api="Windows WDM-KS", ch=2),
        _dev(23, "Output (AMD HD Audio HDMI out #0)", api="Windows WDM-KS", ch=2),
        _dev(24, "Speakers (Steam Streaming Speakers Wave)", api="Windows WDM-KS", ch=8),
    ]
    filtered = filter_output_devices(devices)
    names = {d.name for d in filtered}
    assert names == {
        "喇叭 (Realtek(R) Audio)",
        "1 - Mi monitor (AMD High Definition Audio Device)",
        "AI Noise-cancelling Output (ASUS Utility)",
        "CABLE Input (VB-Audio Virtual Cable)",
        "CABLE In 16ch (VB-Audio Virtual Cable)",
    }
    by_name = {d.name: d for d in filtered}
    # Multi-channel routing must still see the full 16ch VB-Cable endpoints.
    assert by_name["CABLE In 16ch (VB-Audio Virtual Cable)"].max_output_channels == 16
    assert by_name["CABLE Input (VB-Audio Virtual Cable)"].max_output_channels == 16
    assert by_name["喇叭 (Realtek(R) Audio)"].hostapi_name == "Windows WASAPI"


def test_resolve_output_samplerate_prefers_media_rate_when_device_accepts_it(monkeypatch) -> None:
    monkeypatch.setattr(devices_mod.sd, "check_output_settings", lambda **kwargs: None)
    rate = resolve_output_samplerate(
        device_index=22, channels=2, preferred_rate=44100.0, device_default_rate=48000.0
    )
    assert rate == 44100.0


def test_resolve_output_samplerate_falls_back_when_media_rate_rejected(monkeypatch) -> None:
    """
    Regression for the reported crash: selecting WASAPI 喇叭 (Realtek Speakers)
    while a 44.1kHz file is loaded raised
    `sounddevice.PortAudioError: Invalid sample rate [PaErrorCode -9997]`
    because the shared-mode endpoint is locked to a single mixer rate
    (48000 Hz here). Probing with check_output_settings must steer us to
    the rate the device actually accepts.
    """

    def fake_check(*, device, channels, samplerate, dtype):
        if samplerate != 48000:
            raise RuntimeError("Invalid sample rate [PaErrorCode -9997]")

    monkeypatch.setattr(devices_mod.sd, "check_output_settings", fake_check)
    rate = resolve_output_samplerate(
        device_index=22, channels=2, preferred_rate=44100.0, device_default_rate=48000.0
    )
    assert rate == 48000.0


def test_resolve_output_samplerate_tries_common_rates_without_device_default(monkeypatch) -> None:
    def fake_check(*, device, channels, samplerate, dtype):
        if samplerate != 48000:
            raise RuntimeError("Invalid sample rate [PaErrorCode -9997]")

    monkeypatch.setattr(devices_mod.sd, "check_output_settings", fake_check)
    rate = resolve_output_samplerate(device_index=22, channels=2, preferred_rate=44100.0)
    assert rate == 48000.0


def test_resolve_output_samplerate_returns_preferred_rate_with_no_device() -> None:
    assert resolve_output_samplerate(device_index=None, channels=2, preferred_rate=44100.0) == 44100.0


class _FakeInputOutputPair:
    """
    Mimics `sounddevice`'s internal `_InputOutputPair`: supports `[1]`
    indexing but is not a `list`/`tuple` and does not support `int()`.
    Real `sd.default.device` returns one of these on some `sounddevice`
    builds -- the original `isinstance(default, (list, tuple)) else
    int(default)` check missed this, always raised, and was silently
    swallowed, so "System Default" resolution *always* fell through to
    `devices[0]` regardless of the actual OS default.
    """

    def __init__(self, pair: tuple[int, int]) -> None:
        self._pair = pair

    def __getitem__(self, index: int) -> int:
        return self._pair[index]


def test_query_default_output_index_handles_input_output_pair_object(monkeypatch) -> None:
    monkeypatch.setattr(devices_mod.sd, "query_hostapis", lambda: [])
    monkeypatch.setattr(
        devices_mod.sd, "default", SimpleNamespace(device=_FakeInputOutputPair((7, 22)))
    )
    assert devices_mod.query_default_output_index() == 22


def test_find_output_device_default_prefers_wasapi_hostapi_default_over_global(monkeypatch) -> None:
    """
    PortAudio's global `sd.default.device` is keyed off the default host
    API, which on Windows is often *not* WASAPI (e.g. MME) and therefore
    doesn't track the tray's current default endpoint. The WASAPI host
    API's own `default_output_device` does track it live, so it must win
    when both are available and disagree.
    """
    devices = [
        _dev(1, "喇叭 (Realtek(R) Audio)", api="Windows WASAPI", ch=2),
        _dev(2, "CABLE In 16ch (VB-Audio Virtual Cable)", api="Windows WASAPI", ch=16),
    ]
    monkeypatch.setattr(
        devices_mod.sd,
        "query_hostapis",
        lambda: [{"name": "Windows WASAPI", "default_output_device": 1}],
    )
    monkeypatch.setattr(devices_mod.sd.default, "device", (7, 2))  # global default disagrees
    chosen = find_output_device(devices, name="")
    assert chosen is not None
    assert chosen.name == "喇叭 (Realtek(R) Audio)"


def test_find_output_device_default_index_missing_maps_by_name_not_devices0(monkeypatch) -> None:
    """
    Reproduces the reported bug: the OS default output index (as resolved
    by PortAudio) no longer matches any `.index` in the filtered/deduped
    device list -- e.g. `filter_output_devices` kept the WASAPI sibling's
    index for "喇叭" while the resolved default index is the raw MME
    sibling's index. Falling back to `devices[0]` after sorting by
    `-max_output_channels` would silently hand playback to the 16ch cable;
    mapping the raw default index's *name* onto the filtered list must find
    the real Speakers entry instead.
    """
    devices = filter_output_devices(
        [
            _dev(1, "喇叭 (Realtek(R) Audio)", api="MME", ch=2),
            _dev(14, "喇叭 (Realtek(R) Audio)", api="Windows WASAPI", ch=2),
            _dev(8, "CABLE Input (VB-Audio Virtual Cable)", api="Windows WASAPI", ch=16),
        ]
    )
    # Sanity: dedupe kept the WASAPI index (14), and the 16ch cable sorts first.
    assert devices[0].name == "CABLE Input (VB-Audio Virtual Cable)"
    assert {d.index for d in devices} == {14, 8}

    monkeypatch.setattr(devices_mod.sd, "query_hostapis", lambda: [])
    monkeypatch.setattr(devices_mod.sd.default, "device", (7, 1))  # raw MME index, not in `devices`
    monkeypatch.setattr(
        devices_mod.sd,
        "query_devices",
        lambda index=None: {"name": "喇叭 (Realtek(R) Audio)"},
    )

    chosen = find_output_device(devices, name="")
    assert chosen is not None
    assert chosen.name == "喇叭 (Realtek(R) Audio)"
    assert chosen.max_output_channels == 2


def test_find_output_device_prefer_index_missing_maps_by_name(monkeypatch) -> None:
    """`prefer_index` (e.g. a previously-resolved raw index) gets the same
    by-name recovery when it no longer exists in the filtered list."""
    devices = [
        _dev(14, "喇叭 (Realtek(R) Audio)", api="Windows WASAPI", ch=2),
        _dev(8, "CABLE Input (VB-Audio Virtual Cable)", api="Windows WASAPI", ch=16),
    ]
    monkeypatch.setattr(
        devices_mod.sd,
        "query_devices",
        lambda index=None: {"name": "喇叭 (Realtek(R) Audio)"},
    )
    chosen = find_output_device(devices, prefer_index=1)
    assert chosen is not None
    assert chosen.name == "喇叭 (Realtek(R) Audio)"


def test_find_output_device_falls_back_to_devices0_when_nothing_resolves(monkeypatch) -> None:
    """With no usable default info and no name match at all, the historical
    last-resort of `devices[0]` still applies (nothing better to do)."""
    devices = [
        _dev(8, "CABLE Input (VB-Audio Virtual Cable)", api="Windows WASAPI", ch=16),
        _dev(14, "喇叭 (Realtek(R) Audio)", api="Windows WASAPI", ch=2),
    ]
    monkeypatch.setattr(devices_mod.sd, "query_hostapis", lambda: [])
    monkeypatch.setattr(devices_mod.sd.default, "device", (7, 99))

    def _raise(index=None):
        raise RuntimeError("no such device")

    monkeypatch.setattr(devices_mod.sd, "query_devices", _raise)
    chosen = find_output_device(devices, name="")
    assert chosen is devices[0]


def test_resolve_output_samplerate_returns_preferred_as_last_resort(monkeypatch) -> None:
    """If nothing probes successfully, don't crash resolving -- let the caller's
    open attempt surface the real error (and its own retry fallback try again)."""

    def fake_check(**kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(devices_mod.sd, "check_output_settings", fake_check)
    rate = resolve_output_samplerate(
        device_index=5, channels=2, preferred_rate=44100.0, device_default_rate=48000.0
    )
    assert rate == 44100.0

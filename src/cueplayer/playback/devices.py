"""Enumerate audio output devices for routing UI."""

from __future__ import annotations

from dataclasses import dataclass

import sounddevice as sd


@dataclass(frozen=True, slots=True)
class OutputDeviceInfo:
    index: int
    name: str
    max_output_channels: int
    default_samplerate: float
    hostapi_name: str

    @property
    def label(self) -> str:
        # Short API name in the UI; full hostapi kept for ranking.
        api = self.hostapi_name.replace("Windows ", "")
        return f"{self.name}  [{self.max_output_channels} ch | {api}]"


# Prefer modern Windows APIs; avoid listing the same speaker 4× (MME/DS/WASAPI/WDM-KS).
_HOSTAPI_RANK: dict[str, int] = {
    "Windows WASAPI": 0,
    "ASIO": 0,
    "Windows WDM-KS": 1,
    "Windows DirectSound": 2,
    "MME": 3,
}


def _hostapi_rank(name: str) -> int:
    return _HOSTAPI_RANK.get(name, 50)


def _is_junk_device_name(name: str) -> bool:
    """Skip empty / Bluetooth enum path / mapper noise that pollutes the combo."""
    n = (name or "").strip()
    if not n:
        return True
    # e.g. "耳機 ()" or "Speakers ()"
    if "()" in n.replace(" ", ""):
        bare = n.replace("()", "").replace("（）", "").strip()
        if len(bare) <= 8:
            return True
    lower = n.lower()
    if "@system32\\drivers\\" in lower or "@system32/drivers/" in lower:
        return True
    if "bthhfenum.sys" in lower or "bthenum.sys" in lower:
        return True
    if lower in {"primary sound driver", "microsoft sound mapper", "default"}:
        return True
    return False


def _normalize_device_key(name: str) -> str:
    """Collapse trivial whitespace differences for dedupe."""
    return " ".join((name or "").strip().split()).casefold()


def _names_likely_same(a: str, b: str) -> bool:
    """
    PortAudio often truncates MME names vs WASAPI.
    Treat prefix matches (long enough) as the same device.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < 12:
        return False
    return longer.startswith(shorter)


def _better_device(candidate: OutputDeviceInfo, current: OutputDeviceInfo) -> bool:
    """
    Multi-channel routing needs max channels first (VB-Cable 16ch etc.).
    Then prefer WASAPI / ASIO over MME duplicates.
    """
    if candidate.max_output_channels != current.max_output_channels:
        return candidate.max_output_channels > current.max_output_channels
    return _hostapi_rank(candidate.hostapi_name) < _hostapi_rank(current.hostapi_name)


def _merge_into(
    best: list[OutputDeviceInfo],
    d: OutputDeviceInfo,
    *,
    allow_new: bool,
) -> None:
    """Merge one device into the running `best` list, matching by (fuzzy) name."""
    key = _normalize_device_key(d.name)
    match_i: int | None = None
    for i, prev in enumerate(best):
        prev_key = _normalize_device_key(prev.name)
        if key == prev_key or _names_likely_same(key, prev_key):
            match_i = i
            break
    if match_i is None:
        if allow_new:
            best.append(d)
        return
    if _better_device(d, best[match_i]):
        # Keep the longer/clearer name when replacing.
        keep = d
        if len(best[match_i].name) > len(d.name):
            keep = OutputDeviceInfo(
                index=d.index,
                name=best[match_i].name,
                max_output_channels=d.max_output_channels,
                default_samplerate=d.default_samplerate,
                hostapi_name=d.hostapi_name,
            )
        best[match_i] = keep


def filter_output_devices(
    devices: list[OutputDeviceInfo],
    *,
    prefer_hostapis: bool = True,
) -> list[OutputDeviceInfo]:
    """
    Keep one sensible entry per physical/virtual device, close to what the
    Windows tray "Sound output" list shows.

    - Drop junk / empty names.
    - When WASAPI/ASIO endpoints are present (the same device family Windows'
      own picker is built from), only *those* devices seed the result list.
      MME/DirectSound/WDM-KS entries are folded onto a matching WASAPI/ASIO
      seed (by name, handling PortAudio's truncated MME names) but are never
      added as brand-new rows on their own -- that's what causes duplicate
      "Speakers 1/2 (... HAP)", "Line Out 1/2 (Intelligo VAC)", HDMI, Steam
      Streaming, "VB-Audio Point" style clutter that Windows itself hides.
    - Prefer higher channel count (routing) first, so a 16ch VB-Cable
      exposed only via MME/DirectSound still wins over a 2ch WASAPI sibling,
      then prefer WASAPI/ASIO over MME/DS/WDM-KS when channel counts match.
    - If no WASAPI/ASIO endpoints exist at all (e.g. non-Windows hostapis),
      fall back to treating every device as a possible seed.
    """
    usable = [d for d in devices if not _is_junk_device_name(d.name)]
    if not prefer_hostapis:
        return usable

    seeds = [d for d in usable if _hostapi_rank(d.hostapi_name) == 0]
    others = [d for d in usable if _hostapi_rank(d.hostapi_name) != 0]

    best: list[OutputDeviceInfo] = []
    if seeds:
        for d in seeds:
            _merge_into(best, d, allow_new=True)
        for d in others:
            _merge_into(best, d, allow_new=False)
    else:
        for d in usable:
            _merge_into(best, d, allow_new=True)

    return sorted(
        best,
        key=lambda d: (
            -d.max_output_channels,
            _hostapi_rank(d.hostapi_name),
            d.name.casefold(),
            d.index,
        ),
    )


def list_output_devices(*, dedupe: bool = True) -> list[OutputDeviceInfo]:
    hostapis = sd.query_hostapis()
    out: list[OutputDeviceInfo] = []
    for index, device in enumerate(sd.query_devices()):
        max_out = int(device["max_output_channels"])
        if max_out <= 0:
            continue
        api = hostapis[int(device["hostapi"])]["name"]
        out.append(
            OutputDeviceInfo(
                index=index,
                name=str(device["name"]),
                max_output_channels=max_out,
                default_samplerate=float(device["default_samplerate"]),
                hostapi_name=str(api),
            )
        )
    return filter_output_devices(out) if dedupe else out


def hostapi_names() -> list[str]:
    """Installed PortAudio host APIs (e.g. ASIO, Windows WASAPI)."""
    try:
        return [str(api.get("name", "")) for api in sd.query_hostapis()]
    except Exception:
        return []


def asio_available() -> bool:
    return any(name == "ASIO" for name in hostapi_names())


def list_output_devices_for_picker() -> list[OutputDeviceInfo]:
    """
    Full routing picker: always list every ASIO endpoint separately (Reaper-style),
    plus deduped WASAPI defaults and any extra multi-channel siblings.

    ``filter_output_devices`` hides DirectSound/MME clutter for the tray-style
    list, but that also hid ASIO when only a 4ch DirectSound Focusrite entry
    matched the same name family — users could not pick ASIO for LTC→CH3.
    """
    raw = list_output_devices(dedupe=False)
    usable = [d for d in raw if not _is_junk_device_name(d.name)]
    picked: list[OutputDeviceInfo] = []
    seen: set[int] = set()

    def add(d: OutputDeviceInfo) -> None:
        if d.index in seen:
            return
        seen.add(d.index)
        picked.append(d)

    for d in usable:
        if d.hostapi_name == "ASIO":
            add(d)
    for d in filter_output_devices(usable):
        add(d)
    # Multi-channel endpoints that dedupe skipped (e.g. 4ch DirectSound Focusrite).
    for d in usable:
        if d.max_output_channels >= 3 and d.index not in seen:
            add(d)

    return sorted(
        picked,
        key=lambda d: (
            0 if d.hostapi_name == "ASIO" else 1 if d.hostapi_name == "Windows WASAPI" else 2,
            -d.max_output_channels,
            _hostapi_rank(d.hostapi_name),
            d.name.casefold(),
            d.index,
        ),
    )


def _match_by_name(devices: list[OutputDeviceInfo], wanted: str) -> OutputDeviceInfo | None:
    """Exact, then substring (either direction) name match against `devices`."""
    wanted = (wanted or "").strip()
    if not wanted:
        return None
    for d in devices:
        if d.name == wanted:
            return d
    for d in devices:
        if wanted.lower() in d.name.lower():
            return d
    # Stored name may include old "[WASAPI, 2 ch]" suffix from earlier labels.
    for d in devices:
        if d.name.lower() in wanted.lower():
            return d
    return None


def _raw_device_name(index: int) -> str:
    """Name of a raw (unfiltered) PortAudio device index, best-effort."""
    try:
        return str(sd.query_devices(index)["name"])
    except Exception:
        return ""


def query_default_output_index() -> int | None:
    """
    Resolve the OS's current default *output* device index (into the raw,
    unfiltered `sd.query_devices()` list).

    Prefer the "Windows WASAPI" host API's own `default_output_device`:
    PortAudio's WASAPI backend queries this live from
    `IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender, eConsole)`, which
    is the same endpoint Windows' Sound Settings / tray flyout lets the user
    pick -- so it tracks the tray selection when the user switches it.

    Fall back to `sd.default.device`, PortAudio's *global* default output,
    which is chosen from the default host API. On many Windows setups that
    default host API is MME (or another API entirely), whose "default"
    device is resolved by PortAudio itself (often the sound mapper) and can
    disagree with the tray -- this is only a last-resort hint, not a
    reliable tray follower, hence the WASAPI-first lookup above.

    Note: `sounddevice`'s `sd.default.device` does not always return a
    plain `int`/`tuple` -- some versions return an internal
    `_InputOutputPair` object that only supports `[1]` indexing (not
    `int()`). Indexing with `[1]` first (before trying a bare `int()`)
    covers both cases; getting this wrong previously meant the whole
    lookup silently raised and was swallowed, so "System Default" *always*
    fell through to `devices[0]`.
    """
    try:
        hostapis = sd.query_hostapis()
    except Exception:
        hostapis = []
    for api in hostapis:
        if str(api.get("name", "")) == "Windows WASAPI":
            idx = api.get("default_output_device", -1)
            if isinstance(idx, int) and idx >= 0:
                return idx
            break
    try:
        default = sd.default.device
        try:
            idx = int(default[1])
        except (TypeError, IndexError, KeyError):
            idx = int(default)
        if idx >= 0:
            return idx
    except Exception:
        pass
    return None


def upgrade_device_for_channels(
    chosen: OutputDeviceInfo,
    *,
    min_channels: int,
    raw_devices: list[OutputDeviceInfo] | None = None,
) -> OutputDeviceInfo:
    """
    Pick a PortAudio endpoint for the same logical device that exposes at
    least ``min_channels`` outputs.

    Windows often lists the same interface twice (e.g. Focusrite WASAPI 2ch
    stereo vs 8ch). ``filter_output_devices`` usually keeps the higher-count
    sibling, but a stored device index or name match can still resolve to the
    2ch endpoint — which breaks LTC→CH3 routing.
    """
    need = max(1, int(min_channels))
    if chosen.max_output_channels >= need:
        return chosen
    key = _normalize_device_key(chosen.name)
    best = chosen
    pool = raw_devices if raw_devices is not None else list_output_devices(dedupe=False)
    for candidate in pool:
        if candidate.max_output_channels < need:
            continue
        cand_key = _normalize_device_key(candidate.name)
        if not (
            key == cand_key
            or _names_likely_same(key, cand_key)
            or _names_likely_same(cand_key, key)
        ):
            continue
        if _better_device(candidate, best):
            best = candidate
    return best


def _device_name_score(preferred_name: str, device_name: str) -> int:
    """Higher = better match between saved device label and a raw endpoint name."""
    pref = (preferred_name or "").strip().casefold()
    name = (device_name or "").strip().casefold()
    if not pref:
        return 0
    if pref == name:
        return 300
    if pref in name or name in pref:
        return 200
    tokens = [t for t in pref.replace("(", " ").replace(")", " ").split() if len(t) >= 3]
    if any(t in name for t in tokens):
        return 120
    if _names_likely_same(_normalize_device_key(pref), _normalize_device_key(name)):
        return 100
    return 0


def resolve_output_endpoint_for_channels(
    *,
    preferred_name: str,
    min_channels: int,
    samplerate: float,
    raw_devices: list[OutputDeviceInfo],
) -> OutputDeviceInfo | None:
    """
    Pick a PortAudio output endpoint that can actually open ``min_channels`` at
    ``samplerate``.

    Windows often exposes the same interface as a 2ch WASAPI "Speakers" entry
    and a separate 8ch ASIO / multi-line endpoint. Saved names like
    "Speakers (Focusrite USB)" must not trap LTC→CH3 on the stereo pair.
    """
    need = max(1, int(min_channels))
    best: OutputDeviceInfo | None = None
    best_score = -1
    for candidate in raw_devices:
        if candidate.max_output_channels < need:
            continue
        try:
            sd.check_output_settings(
                device=candidate.index,
                channels=need,
                samplerate=float(samplerate),
                dtype="float32",
            )
        except Exception:
            continue
        score = _device_name_score(preferred_name, candidate.name)
        api = candidate.hostapi_name.casefold()
        if "asio" in api:
            score += 45
        elif api == "windows wasapi":
            score += 35
        elif "wdm" in api:
            score += 15
        score += min(candidate.max_output_channels, 32)
        if score > best_score:
            best_score = score
            best = candidate
    return best


def probe_supported_output_channels(
    device_index: int,
    *,
    min_channels: int,
    samplerate: float,
) -> int:
    """
    Highest channel count the device accepts at ``samplerate`` (downward probe).
    Falls back to ``min( device max, min_channels )`` when probing fails.
    """
    need = max(1, int(min_channels))
    try:
        dev_max = int(sd.query_devices(device_index)["max_output_channels"])
    except Exception:
        return need
    for ch in range(dev_max, 0, -1):
        if ch < need:
            break
        try:
            sd.check_output_settings(
                device=device_index,
                channels=ch,
                samplerate=float(samplerate),
                dtype="float32",
            )
            return ch
        except Exception:
            continue
    return max(1, min(dev_max, need))


def find_output_device(
    devices: list[OutputDeviceInfo],
    *,
    name: str = "",
    prefer_index: int | None = None,
) -> OutputDeviceInfo | None:
    """
    Resolve a stored device name (exact, then substring) or, for "System
    Default" (empty name / no index), the OS's current default output
    device.

    `devices` is the filtered/deduped list shown in the UI, but
    `prefer_index` / the OS default index are indices into the *raw*
    PortAudio device list -- `filter_output_devices` merges e.g. an MME
    sibling onto a WASAPI seed and keeps only one `index` for that logical
    device, so the raw default index is frequently absent from `devices`
    even though the same physical device is present under a different
    index. When the index isn't found directly, look up the raw device's
    name and match it into `devices` instead of silently returning
    `devices[0]` -- that list is sorted by channel count first, so a bare
    "give up" fallback there means multi-channel virtual devices (e.g. a
    16ch VB-Cable) win over the real default speakers.
    """
    if prefer_index is not None:
        for d in devices:
            if d.index == prefer_index:
                return d
        match = _match_by_name(devices, _raw_device_name(prefer_index))
        if match is not None:
            return match

    wanted = (name or "").strip()
    if wanted:
        match = _match_by_name(devices, wanted)
        if match is not None:
            return match

    default_index = query_default_output_index()
    if default_index is not None:
        for d in devices:
            if d.index == default_index:
                return d
        match = _match_by_name(devices, _raw_device_name(default_index))
        if match is not None:
            return match

    return devices[0] if devices else None


def build_source_route(
    *,
    music_left: list[int],
    music_right: list[int],
    ltc: list[int],
) -> dict[int, list[int]]:
    """
    Source channels: 0 = Music L, 1 = Music R, 2 = Generated LTC.
    """
    route: dict[int, list[int]] = {}
    if music_left:
        route[0] = list(music_left)
    if music_right:
        route[1] = list(music_right)
    if ltc:
        route[2] = list(ltc)
    return route


# Probed in order after the caller's preferred rate; covers the common
# WASAPI shared-mode "locked mixer format" rates seen in the wild.
_FALLBACK_SAMPLE_RATES: tuple[float, ...] = (48000.0, 44100.0, 96000.0, 32000.0, 22050.0)


def resolve_output_samplerate(
    *,
    device_index: int | None,
    channels: int,
    preferred_rate: float,
    device_default_rate: float | None = None,
) -> float:
    """
    Pick a sample rate the given output device will actually accept.

    WASAPI shared-mode endpoints commonly lock to a single mixer rate (e.g.
    48000 Hz) and reject `sd.OutputStream(samplerate=...)` at any other rate
    with "Invalid sample rate" (PaErrorCode -9997) -- media files are very
    often 44100 Hz, so opening blindly at the file's native rate is unsafe.
    Probe with `sd.check_output_settings` (cheap, does not open a stream)
    and fall back through the device's own default rate, then a short list
    of common rates, before giving up and returning the preferred rate
    unchanged (so callers still get a deterministic value to try).
    """
    if device_index is None:
        return preferred_rate
    candidates: list[float] = [preferred_rate]
    if device_default_rate and device_default_rate not in candidates:
        candidates.append(device_default_rate)
    for rate in _FALLBACK_SAMPLE_RATES:
        if rate not in candidates:
            candidates.append(rate)
    for rate in candidates:
        try:
            sd.check_output_settings(
                device=device_index,
                channels=max(1, int(channels)),
                samplerate=rate,
                dtype="float32",
            )
            return rate
        except Exception:
            continue
    return preferred_rate


def required_output_channels(route: dict[int, list[int]]) -> int:
    needed = 0
    for dests in route.values():
        for ch in dests:
            needed = max(needed, int(ch) + 1)
    return max(1, needed)

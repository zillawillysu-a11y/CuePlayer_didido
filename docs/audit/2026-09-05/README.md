# 0815 audit evidence — 2026-09-05

Baseline: `d9663ec9b955d76417a5bdcb6751deb105b382f3` (version 1.1.3).
See [technical audit](../../../CUEPLAYER_TECHNICAL_AUDIT.md) for interpretation.
No production behavior was changed.

- `probes.json`: source inventory, versions, synthetic clock/rate/loop/waveform/
  MTC/FPS/resampler/codec probes and mixer microbenchmark.
- `core.txt`: 464 passed, 1 failed.
- `focused.txt`: 79 passed, 2 failed; device tests incompletely isolate native I/O.
- `pytest.txt`: full-suite collection error.
- `pytest-continued.txt`: native access violations; no final summary or established cause.
- `dependencies.txt`: newly resolved audit environment, not the exact August EXE dependencies.

Logs are normalized to UTF-8 with trailing whitespace removed. Absolute source paths and temporary fixture names
remain. Codec fixtures were deleted. No device loopback, console, physical GUI
timing or multi-hour soak measurements are included.

## Reproduction

Python 3.13.14, with the versions in `dependencies.txt`. The editable-install
line names this machine's checkout; install this repository at the baseline.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONIOENCODING = 'utf-8'
.venv/Scripts/python.exe scripts/audit_0815_probes.py
```

The probe replaces OutputStream and manually invokes callbacks. It opens no
hardware stream/network connection. Reported defects are baseline observations,
not correct product expectations. The inventory reflects the checkout being run;
the embedded baseline label identifies the version originally audited.

Completed subsets:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/domain tests/persistence tests/exporters tests/routing tests/timecode tests/application tests/ports tests/repository tests/core tests/unicode --disable-warnings --tb=short
.venv/Scripts/python.exe -m pytest -q tests/playback/test_resample.py tests/playback/test_resample_hold.py tests/playback/test_devices.py tests/playback/test_midi_cue_notes.py tests/media/test_audio_loader.py tests/media/test_audio_disk_cache.py tests/media/test_video_waveform_artifact.py --disable-warnings --tb=short
```

Full-suite attempts used `-m pytest -q --disable-warnings --tb=short`, then
added `--continue-on-collection-errors`. Repair native-device isolation/teardown
before treating an unrestricted rerun as a reliable baseline.

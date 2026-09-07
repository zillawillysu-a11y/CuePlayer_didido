# Next task

## Hardware PERF matrix — verify LTC vectorization + isolate DirectSound/MTC

Date: 2026-09-08. Use the same theater Song/device intent and start CuePlayer with `CUEPLAYER_PERF=1`. After each run use **Tools → Write Performance Report** and preserve only the newest manual dump.

### Problem A post-fix

1. A1 LTC OFF, play 10 seconds.
2. A2 LTC ON, start playback while builder is active.
3. A3 wait for `audio.ltc_clip.builder_active_jobs=0`, then play 10 seconds.

Compare `audio.ltc_clip.builder_event_ring` T0/T1/per-clip/Tn with callback interval/exec/lock-wait counters. Confirm waveform at the receiver. Expected from local benchmark: old 15×270 s scalar workload 6.0947 s, new vectorized workload 0.9036 s, byte-exact PCM.

### Problem B four-cell isolation

1. B1 ASIO + MTC OFF
2. B2 ASIO + MTC ON
3. B3 DirectSound + MTC OFF
4. B4 DirectSound + MTC ON

For every cell record:

- `audio.stream.*` (host API, exact device/index, rate, channels, requested blocksize/latency, reported output latency)
- `audio.callback.frame_count_min/max/mean`, `actual_period_expected_from_frames_ms`
- callback interval mean/max + `interval_miss_count`
- callback exec mean/max + `exec_over_budget_count`
- `audio.callback.lock_wait_ms/max`
- `mtc.clock_lock_wait_ms/max`, `mtc.loop_ms/max`, `mtc.send_ms/max/count`
- output underflow and status flags

Do not treat interval misses alone as underflow. Find the factor unique to B4. If lock wait is unique, evaluate a lock-free bounded sample-clock snapshot; if MTC send/loop is unique, isolate MIDI backend blocking/GIL; if only expected-period interpretation is wrong, fix diagnostics only. Do not enlarge DirectSound buffer, slow MTC cadence, disable quarter-frame, or redesign AudioEngine without evidence.

Pointers: `.ai/REPORT.md` and `.ai/handoffs/2026-09-08_AudioTiming_LTCStartup_DirectSoundMTC.md`.

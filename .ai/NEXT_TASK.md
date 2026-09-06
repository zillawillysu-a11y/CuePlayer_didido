# Next task

Physical loopback pitch test on the Scarlett 4i4, then a longer continuous
capture. Do NOT apply any clock correction before these results.

1. Loopback: play a known pure sine (e.g. 440.000 Hz) at constant level through
   the Focusrite, route line-out -> line-in (or a second ASIO device), record
   30–60 s, and measure the output frequency over time (FFT / freq track).
   This measures the physical output pitch and any drift, independent of the
   driver's internal sample counter.
2. Long capture: continuous playback for 5–10 minutes with periodic
   `Tools -> Write Performance Report` dumps, to check whether dac_time vs
   host_monotonic drifts away from 1.0 over minutes (slow-drift trend).

Background (2026-09-06 capture analysis): three manual dumps from one live
Focusrite USB ASIO stream (epoch 6, 48000 Hz, 1024 frames, 2 ch) show a clean,
stable 48 kHz vs the host clock (worst ~35 ppm = ~0.06 cents, ~two orders of
magnitude below an audible key drift), no underflow, and only single-callback
~21 ms stalls. The audible KEY/pitch drift is NOT explained by the ASIO sample
rate or DAC clock in that data. The `Audio callback continuity` counters are
cumulative since engine creation (misleading for the current stream); the
per-ring `audio.timing` data is the correct signal.

Follow-up diagnostic fix (planned, separate task): reset the audio callback
continuity counters (callback_count, interval sum/max, exec, deadline_miss)
on stream open so the report section reflects the current stream.

No presentation-clock correction has been made. See .ai/REPORT.md,
.ai/handoffs/2026-09-06_FocusriteKeyDriftAnalysis.md,
docs/AUDIO_TIMING_DIAGNOSTICS.md and docs/audit/2026-09-06/README.md.

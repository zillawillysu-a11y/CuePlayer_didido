# Next task

## Hardware verification — DirectSound + deadline-driven MTC

Date: 2026-09-08. Use the same theater Song and Focusrite DirectSound endpoint with
`CUEPLAYER_PERF=1`; verification only, not another architecture change.

1. Play DirectSound + MTC ON for at least 10 seconds; confirm whether continuous severe
   stutter is gone.
2. Press-hold/drag the main or Clean Output title bar; confirm MTC remains continuous.
3. Write a Performance Report and record audio callback continuity/underflow/status/lock
   wait plus MTC wakeups/s, clock reads/s, sends/s, generation/start/stop/live/duplicate.
4. Expected at 24/25/29.97/30 fps: wake/clock rate near 96/100/119.88/120 per second,
   not ~250; QF send cadence must not decrease.
5. Repeat MTC Enable/Disable and ASIO ↔ DirectSound once; require one live sender and
   `duplicate_live_sender_count=0`.

Do not change LTC, enlarge buffers, reduce MTC cadence, or send MIDI in the audio callback.
Pointers: `.ai/REPORT.md` and
`.ai/handoffs/2026-09-08_DirectSound_MTC_Regression.md`.

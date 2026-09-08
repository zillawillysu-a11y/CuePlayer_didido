# Next task — verify MTC clock-rollback candidate on Windows

Date: 2026-09-08
Branch: `cursor/mtc-clock-rollback-028d` (based on `cd8c35a`).

The user reports DirectSound MTC dropout remains. The new candidate removes
false implicit seek detection and adds QF cadence / Full Frame reason metrics.
123 targeted tests pass; this is not yet a hardware-confirmed resolution.

Delivery: the user explicitly authorized GitHub publication on 2026-09-08.
Use the candidate branch `cursor/mtc-clock-rollback-028d` and its draft PR,
which targets `technical-audit-0815-028d`. Hardware testing remains outstanding.

1. Run this checkout from source with `.\scripts\start_audio_diagnostics.ps1`
   using the existing Windows `.venv`.
2. Same Song, MIDI port and receiver: DirectSound + MTC ON, 30 seconds away
   from clip edges, no seeks. While playing, Tools > Write Performance Report.
3. Repeat with ASIO; retain both manual-dump sections and note whether music
   itself stutters or only the MTC receiver drops.
4. Separately verify explicit seeks (including backwards), A-B loop, adjacent
   LTC clips/gaps, and dragging/holding the window title bar.
5. Inspect `mtc.clock_backward_count`, `mtc.clock_backward_max_ms`,
   `mtc.qf_gap_mean_ms`, `mtc.qf_gap_max_ms`, `mtc.qf_send_count`,
   `mtc.full_frame_*_count`, `mtc.send_error_count` plus callback diagnostics.
   For continuous playback, clock corrections should not produce Full Frames;
   real seek/loop/source changes legitimately do. QF rate remains FPS*4.
6. Only after successful source verification, rebuild the Windows package.
   If failures persist, use these metrics to distinguish source-boundary
   oscillation, sender delays, driver failures and audio callback stalls.

References: `.ai/REPORT.md`, `.ai/handoffs/2026-09-08_MtcClockRollback.md`.

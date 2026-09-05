# Next task

**Updated:** 2026-09-05

Phase 0: 修復測試隔離與加入 bounded audio timing/sample-rate diagnostics，不改播放行為。

Read `CUEPLAYER_TECHNICAL_AUDIT.md`, `.ai/REPORT.md` and
`docs/audit/2026-09-05/README.md`. Repair test collection/native device isolation,
establish correct regression expectations, and record bounded rate/generation/
callback/DAC timing and silence reasons. No file logging in the RT callback.

The user's audit request superseded the prior queue. Its unused-media GUI
preview/restore smoke remains outstanding in the handoff. This pointer is a
proposal for the next user task, not authorization to start production changes
or Theatre UI automatically after this audit.

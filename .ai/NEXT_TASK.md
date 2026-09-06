# Next task

Reset audio callback continuity diagnostic counters when opening a new output stream, with a narrow playback regression test.

LTC Generator Clips Phase 1–4 are complete. Phase 4 details: `.ai/handoffs/2026-09-06_LtcClipsExporterPhase4.md`.

**Scope:**

1. Identify continuity / underrun counters scoped to one output-stream lifetime.
2. Reset only those counters after a new stream successfully opens.
3. Add a narrow playback regression test.
4. Do not alter routing, clock math, LTC/MTC mapping, UI, or exporters.

**Carry-over (not blocking):**

- Physical loopback 440 Hz + long-capture drift check (parked by user).
- Pre-existing unrelated failures are documented in `.ai/REPORT.md`.

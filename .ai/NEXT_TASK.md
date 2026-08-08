# Next task

**Status:** Queued - awaiting real-Windows verification
**Type:** Performance fix (Exporter view-switch latency)
**Updated:** 2026-08-08

## Newest item (2026-08-08, do this first)

Verify the Exporter switch latency fix — see
`.ai/handoffs/2026-08-08_ExporterViewSwitchLatencyFix.md`:

1. Click Timeline → Exporter (MA Playlist). Should now feel instant — no
   stutter, no delay. Measured offscreen: 2870ms → 1.7ms.
2. Click back to Timeline, then Exporter again. Should also be instant
   (was 2548ms, now 1.6ms) — confirms it's not just a "first time" fluke.
3. Click **Detect MA2**. This should still visibly take ~3 seconds (that's
   expected/by design — it always does a real rediscovery) and the Target
   Version dropdown should still show your full real installed-version
   list afterward.
4. Open a different project (or restore the last session on a fresh
   launch) — this is the one case still allowed to take ~3s per the
   approved plan, since it's a genuine project load, not a view switch.

## Also pending (not blocking)

The pre-existing full `tests/ui` pytest suite crashes with `Windows fatal
exception: stack overflow` partway through when run all together in one
process (confirmed unrelated to this repo's recent changes via `git stash`
bisection on multiple occasions). Run narrower/targeted pytest paths
instead of the full `tests/ui` directory.

`tests/ui/test_transport_main_window_center.py::test_main_window_transport_centered_under_timeline`
and `tests/ui/test_ma_preflight_export_integration.py` /
`tests/ui/test_row_color_export.py` have pre-existing failures unrelated to
this repo's recent rounds (confirmed via `git stash`) — not investigated
further here.

Startup itself still runs MA2 discovery twice (~3s each, serially) — not
addressed this round (in scope only if it becomes its own complaint; see
handoff "Remaining issues"). No async/QThread work has been started —
explicitly deferred until asked for.

## Explicitly not touched this round (per instruction)

- MA2 export semantics, Page/Groups allocation, CSV — untouched.
- video-waveform code — out of scope, not touched.
- No QThread/QtConcurrent introduced — this round used lifecycle +
  caching only, per instruction.

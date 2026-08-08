# Next task

**Status:** Queued - awaiting real-Windows verification
**Type:** MA2 installed-version discovery
**Updated:** 2026-08-08

## Newest item (2026-08-08, do this first)

Verify this round's changes — see
`.ai/handoffs/2026-08-08_Ma2VersionIdentityValidationAndSummaryRemoval.md`:

1. Open Console Setup, click **Detect MA2**. Confirm the Target Version
   dropdown lists all twelve real installed versions with full 4-segment
   precision — 3.1.2.5, 3.3.4.3, 3.7.0.1, 3.7.0.5, 3.8.0.0, 3.9.0.3,
   3.9.60.18, 3.9.60.74, 3.9.60.89, 3.9.60.91, 3.9.61.5, 3.9.63.6 — with
   **no** `3.9.60`/`3.9.61`/`3.9.63` truncated duplicates.
2. Confirm **`10.0.26100.8875` no longer appears** in the dropdown. This
   was traced (not proven on real hardware — this environment can't run
   PowerShell against your machine) to most likely be an "Uninstall
   grandMA2 onPC ..." shortcut whose target resolves to `msiexec.exe`
   (Windows' own installer engine, whose FileVersion just tracks the
   Windows OS build). Fixed with two layers: an executable-identity check
   (CompanyName/ProductName/FileDescription/path must actually reference
   MA Lighting/grandMA2) and excluding "Uninstall ..." shortcuts from the
   scan outright.
3. Confirm the right-side "Running X · Installed Y, Z, ..." summary text
   next to Detect MA2 is gone. The console radios, Target Version
   dropdown, Detect MA2 button, and the (still-present) unsupported-
   version warning should all look and work the same as before.
4. **If any real version is still missing**, the most useful thing to
   report back is whether that specific install has a Start Menu/Desktop
   shortcut named with "grandMA2"/"onPC", and whether it shows up in
   Windows "Programs and Features" — those are the two precision discovery
   sources; an install with neither can currently only be found via the
   ProgramData library folder, which only ever recovers 3 version
   segments (architecture limit, not a bug).

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

## Explicitly not touched this round (per instruction)

- MA2 Page allocation / scan logic, Groups, CSV Allocation Report, Export
  object logic — all untouched.
- grandMA3 discovery (`default_ma3_export_dir` and friends) — confirmed
  independent, shares no code with anything changed this round.
- video-waveform code — out of scope, not touched.

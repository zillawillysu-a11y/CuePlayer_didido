# Next task

**Status:** Queued - awaiting real-Windows verification
**Type:** UI layout/label consistency + MA2 version discovery
**Updated:** 2026-08-08

## Newest item (2026-08-08, do this first)

Verify this round's changes — see
`.ai/handoffs/2026-08-08_ConsoleSetupScrollCheckboxUnifyManualPoolGridAndMa2VersionDiscovery.md`:

1. Maximize the window (1920x1080), open **Console Setup**: confirm the
   whole page no longer needs to scroll to see every control (measured
   height dropped 739px -> 524px offscreen; real Windows font metrics
   weren't available to verify byte-exact, so this is the one part of the
   layout work most worth a visual glance).
2. Open **Export Registry**: confirm "MA2 Live Pool Scan"'s title and its
   field labels (MA2 Host / Target Version / Command / Monitor / MA2 Show
   User / Password / Plugin Pool / MA2 Plugin Import Path) no longer show a
   dark rectangle behind the text — this was a real Qt/Windows-native-style
   quirk (QGroupBox::title paints an opaque theme background unless told
   `background: transparent`) this environment's offscreen renderer can't
   reproduce to double-check visually.
3. Open **Review & Export**: confirm the 7 Manual Pool Starts fields
   (Sequence/Effect/Timecode/Group/Macro/View/Page) look evenly spaced with
   no overlap at any window size, and that "Export Content Check" now
   reads **Song List Sequence / Fixed control Macros / Song Macro / Song
   View / Add Main Cue named Preset** in that order — same order/labels on
   Console Setup's Export Options and in the Export confirm dialog.
4. **Most important — needs your actual machine**: click **Detect MA2**
   and confirm the Target Version dropdown lists every real installed
   grandMA2 onPC version you have, with full 4-segment precision:
   3.1.2.5, 3.3.4.3, 3.7.0.1, 3.7.0.5, 3.8.0.0, 3.9.0.3, 3.9.60.18,
   3.9.60.74, 3.9.60.89, 3.9.60.91, 3.9.61.5, 3.9.63.6 — and that no
   truncated/generic "3.9.60" / "3.9.61" / "3.9.63" duplicate appears
   alongside them. The new discovery shells out to PowerShell to read the
   Windows uninstall registry and resolve Start Menu/Desktop shortcut
   targets — none of that could be exercised against your real machine
   from this environment. If any version is still missing, check whether
   that install has a Start Menu/Desktop shortcut and/or shows up in
   Windows "Programs and Features", since those are the two new sources.

## Also pending (not blocking)

The pre-existing full `tests/ui` pytest suite crashes with `Windows fatal
exception: stack overflow` partway through when run all together in one
process (confirmed unrelated to this repo's recent changes via `git stash`
bisection on multiple occasions). Run narrower/targeted pytest paths
instead of the full `tests/ui` directory.

`tests/ui/test_transport_main_window_center.py::test_main_window_transport_centered_under_timeline`
and `tests/ui/test_ma_preflight_export_integration.py` /
`tests/ui/test_row_color_export.py` have pre-existing failures unrelated to
this round (confirmed via `git stash`) — not investigated further here.

## Explicitly not touched this round (per instruction)

- MA2 Page allocation / scan logic, Groups, CSV Allocation Report, Export
  object logic — all untouched.
- video-waveform code — out of scope, not touched.

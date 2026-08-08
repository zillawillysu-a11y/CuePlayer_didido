# Next task

**Status:** Queued - awaiting real-Windows verification
**Type:** MA2 installed-version discovery
**Updated:** 2026-08-08

## Newest item (2026-08-08, do this first)

Verify this round's fix — see
`.ai/handoffs/2026-08-08_Ma2DiscoveryFixedFromRealMachineData.md`. This is
a direct correction of the previous round, built from Willy's own real
diagnostic PowerShell output (not guessed):

1. Click **Detect MA2** and confirm the Target Version dropdown lists all
   twelve real versions with full precision: 3.1.2.5, 3.3.4.3, 3.7.0.1,
   3.7.0.5, 3.8.0.0, 3.9.0.3, 3.9.60.18, 3.9.60.74, 3.9.60.89, 3.9.60.91,
   3.9.61.5, 3.9.63.6.
2. Confirm **no** `3.9.60`/`3.9.61`/`3.9.63` truncated duplicates and
   **no** `10.0.26100.8875`.
3. If anything is still wrong: the fastest path to a fix is running the
   same diagnostic PowerShell script from the previous round again (or
   just its registry/shortcut sections) and pasting the raw output back —
   that is exactly what unblocked this round, versus guessing at what
   grandMA2 onPC's file metadata should look like.

### What was actually wrong last round (for context)

The previous identity check required a registry Publisher or an
executable's CompanyName/ProductName to mention "MA Lighting"/"grandMA2".
Willy's real machine data showed: registry DisplayVersion/Publisher/
InstallLocation are all blank (only DisplayName carries the version), and
`gma2onpc.exe` embeds no VersionInfo at all — so that check rejected every
real install, silently falling back to the old truncated 3-segment
ProgramData-folder-only behavior. Rebuilt to parse the version from
DisplayName/shortcut-filename text (confirmed reliable) and validate
identity via the shortcut's target executable *filename*
(`gma2onpc*.exe`/`grandma2*.exe`) instead of file metadata — which is also
what correctly rejects MA Lighting's own "Open Show Folder grandMA2 onPC
X.X.X" shortcut (targets `C:\Windows\explorer.exe`, the confirmed source
of the `10.0.26100.8875` false positive).

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
- grandMA3 discovery — confirmed independent, shares no code with anything
  changed in MA2 version discovery.
- video-waveform code — out of scope, not touched.

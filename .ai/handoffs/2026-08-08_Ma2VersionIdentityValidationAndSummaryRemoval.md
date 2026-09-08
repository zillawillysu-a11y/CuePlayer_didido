# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`
**PR:** #244

## Task objective

Follow-up to the previous MA2 version-discovery round: Willy's real-Windows
test found the Target Version dropdown still missing some real installs,
still showing truncated entries (`3.9.60` / `3.9.61` / `3.9.63`), and now
also showing a clear **false positive**: `10.0.26100.8875` — not a
grandMA2 onPC version at all. Also asked to remove the "Running X ·
Installed Y, Z, ..." summary text next to Detect MA2. Scope: MA2 version
discovery only — no Page/Groups/CSV/export-logic/video-waveform changes.

## What was implemented

### 1) Where the version list came from originally

Three sources, as documented in the previous round: the ProgramData
`gma2_V_X.Y.Z` library-folder name scan (3 segments only), a running-process
FileVersion read (`_running_ma2_version_windows`), and — the actual bug
source — three **hardcoded literal strings** (`"3.9.60"`, `"3.9.61"`,
`"3.9.63.6"`) unconditionally injected into the dropdown by
`_detect_ma2_versions()` on every run. That hardcoded injection was removed
last round.

### 2) Why some real MA2 versions were still missing

The only *precise* (4-segment) discovery sources added last round were the
Windows uninstall registry and Start Menu/Desktop shortcuts, each requiring
a `DisplayName`/shortcut filename to match `grandMA2.*onPC`. Any real
install whose registry entry or shortcut is named differently, or that has
neither a registry entry nor a shortcut (e.g. a portable/manual install)
falls through to the coarse ProgramData folder scan, which can only ever
report 3 segments. This is architecture, not a bug — Willy's report doesn't
point at a specific missing version this round, so no further source was
added on top of registry + shortcuts + folder-fallback; see "Remaining
issues" below for what to check if a version is still missing.

### 3) Why truncated `3.9.60` / `3.9.61` / `3.9.63` appeared

Same underlying cause as before, restated for completeness: the
ProgramData library folder is genuinely only ever named to 3 segments
(`gma2_V_3.9.60`), and several onPC point releases can share one such
folder — that scan is now used **only as a last-resort fallback** per
X.Y.Z family (see `merge_installed_ma2_versions`, unchanged from last
round), never mixed in alongside a precise version for a family that
already has one.

### 4) `10.0.26100.8875` — root cause

**Traced, not blacklisted.** `10.0.26100.8875` is exactly Windows' own OS
build version format (Windows 11 24H2-era). Reading through the discovery
code, the most likely path: the Start Menu/Desktop shortcut scan matched
any `.lnk` filename containing `grandMA2.*onPC` — which also matches an
**"Uninstall grandMA2 onPC ..."** shortcut (a very common installer
convention). That shortcut's `TargetPath` typically resolves to a generic
uninstall helper — often `msiexec.exe`, Windows' own installer engine —
whose `FileVersion` simply tracks the Windows OS build, not any product it
uninstalls. The previous round's code accepted **any** well-formed
`x.x.x.x` FileVersion string with no check on *whose* file it was, so this
sailed straight through.

**Fix, two independent layers (identity is the primary one, not a
blacklist):**
- **`_looks_like_grandma2_identity()`** — the real fix. For every
  registry/shortcut candidate, the resolved executable's
  `CompanyName`/`ProductName`/`FileDescription` (now read via `VersionInfo`
  in the same PowerShell call that gets `FileVersion`) — plus the registry
  `Publisher` field and the install/target path — must contain "MA
  Lighting" or a "grand MA 2"-shaped string (space-tolerant) somewhere. A
  file having a valid version number is **never** sufficient by itself.
  `msiexec.exe`'s own identity (`CompanyName: Microsoft Corporation`,
  `ProductName: Windows(R) Operating System`) fails this check and is
  rejected regardless of its FileVersion.
- **`_is_ma2_version_number()`** — a defense-in-depth sanity backstop
  (every grandMA2 onPC release has been a 3.x build), applied *in addition
  to*, never *instead of*, the identity check above — this is not a
  hardcoded "exclude 10.x" special case; it's a general "the major version
  must be 3" rule that would equally reject an 11.x or 4.x false positive.
- Additionally, the shortcut scan now excludes any `.lnk` whose filename
  contains "uninstall" (`-notmatch 'uninstall'`) — an uninstall shortcut
  is evidence of an uninstaller, not of "this version is installed here,
  here's its real executable," and is exactly the shape of the
  `msiexec.exe` false positive.

### 5) New MA2 identity validation rules

A candidate version from the registry or shortcut scan is accepted only if
**both**:
1. `_is_ma2_version_number(version)` — major segment is `3`.
2. `_looks_like_grandma2_identity(...)` — at least one of Publisher /
   CompanyName / ProductName / FileDescription / InstallLocation-or-target-
   path contains "MA Lighting" or a `grand\s*ma\s*2`-shaped string.

Applied identically in both `_registry_ma2_versions_windows()` and
`_shortcut_ma2_versions_windows()`. The running-process detector
(`_running_ma2_version_windows`) was left as-is — it already only matches
a process whose **image name itself** starts with `grandma2`/`gma2`, a much
tighter check than a DisplayName/shortcut-name substring match, and Willy's
report didn't implicate it.

### 6) Deduplicate / numeric sort

Unchanged from last round (`merge_installed_ma2_versions`, `_version_key`):
dedupe is by exact full version string per X.Y.Z family (precise
registry/shortcut versions for a family always win over — and suppress —
that family's coarse folder-derived fallback; multiple distinct patches
sharing one family, e.g. 3.9.60.18/.74/.89/.91, are all kept individually);
sort is numeric, parsing each dot-segment as an int, so `"3.9.9.1"` sorts
before `"3.9.60.91"` (a plain string sort would put it after).

### 7) grandMA3

Untouched. `default_ma3_export_dir()` and MA3's whole discovery path share
no code with the functions changed here — confirmed by inspection, not just
assumption: grep shows zero overlap between the MA2-specific functions
touched this round and anything MA3-related.

### 8) Detect MA2 summary removed

`_detect_ma2_versions()` no longer builds or sets the
`"Running {x} · Installed {y, z, ...}"` text. `ma2_detect_status` (the
label itself) is **kept** — it's still used for the unsupported-target-
version warning (`"Unsupported X · minimum Y"`, still shown in red) and by
`_on_ma2_version_changed`/`apply_registry_scan_result`'s own status
messages, which are unrelated to the removed summary and were left alone.
On a *supported* selection, the label is now just cleared (`""`) instead of
showing the version dump. Console radios, Target Version dropdown, Detect
MA2 button, and both discovery/running-detection code paths are all
unchanged.

## Files changed

- `src/cueplayer/exporters/ma_default_dirs.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma_default_dirs.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

- Identity validation reads `VersionInfo` fields (CompanyName/ProductName/
  FileDescription) in the *same* PowerShell round trip that already reads
  FileVersion, rather than a second call per candidate — keeps discovery
  fast and keeps the identity fields available for the rejection reason
  instead of throwing them away.
- The two now-unused single-purpose helpers from last round
  (`_file_version_windows`, `_find_ma2_executable`) were removed rather
  than left as dead code, since their logic is now inlined into the
  richer PowerShell scripts that also fetch identity fields.
- Kept following the codebase's established pattern for anything
  OS-specific: shell out to `powershell.exe` (never `winreg`, which would
  break import on non-Windows), and make every OS-facing call swappable
  via an injected callable / the new `_run_powershell()` seam, so tests
  never depend on the real host machine.

## Tests performed

All run with `QT_QPA_PLATFORM=offscreen`:

- `tests/exporters/test_ma_default_dirs.py`: **21 passed** — 17 carried
  over from last round + 5 new: `_is_ma2_version_number` major-version
  gate, `_looks_like_grandma2_identity` (accepts Publisher/ProductName/
  path signals, rejects a `msiexec.exe`-shaped Microsoft identity even
  with a well-formed version), and two end-to-end tests that feed
  synthetic multi-field PowerShell-style output (via monkeypatching the
  new `_run_powershell` seam) through the real registry/shortcut scan
  functions and confirm the `10.0.26100.8875`/Microsoft-identity row is
  dropped while the real MA Lighting row survives.
- `tests/ui/test_show_patch_ma2_discovery.py` + `tests/exporters/`:
  **147 passed**, including the updated
  `test_target_version_dropdown_lists_every_real_installed_patch_full_precision`
  (now asserts the status label is blank on success instead of checking
  removed summary text) and a new
  `test_detect_ma2_summary_removed_but_controls_and_warning_kept` (radios/
  dropdown/button/discovery all still present; an unsupported version
  still produces its warning; the always-shown version dump does not).
- `tests/ui/test_setlist_folder_drag.py` + `tests/persistence/test_schema.py`:
  passed as part of the broader run (12 passed).

## Target Version dropdown after this fix (Willy's reported install set)

Given the twelve versions Willy reported, and assuming the registry/
shortcut scan can actually see each of them (this environment cannot run
PowerShell against the real machine to confirm — see below), the dropdown
should list exactly:

```
3.1.2.5, 3.3.4.3, 3.7.0.1, 3.7.0.5, 3.8.0.0, 3.9.0.3,
3.9.60.18, 3.9.60.74, 3.9.60.89, 3.9.60.91, 3.9.61.5, 3.9.63.6
```

with no `3.9.60`/`3.9.61`/`3.9.63` duplicates and no `10.0.26100.8875`.
This exact list is what
`test_target_version_dropdown_lists_every_real_installed_patch_full_precision`
asserts (it was already covering this before this round; this round adds
the identity-rejection tests on top).

## Remaining issues / needs Willy's real-Windows verification

- **This is the item most worth re-testing.** The registry scan, shortcut
  scan, and every FileVersion/identity read all shell out to
  `powershell.exe`/COM objects this sandboxed environment cannot exercise
  against Willy's actual machine. Please run **Detect MA2** again and
  confirm: (a) `10.0.26100.8875` no longer appears, (b) all twelve real
  versions still appear with full precision, (c) the right-side summary
  text is gone.
- If any real version is *still* missing after this fix, the most useful
  next fact to report is **which discovery source should have found it** —
  does that install have a Start Menu/Desktop shortcut named with
  "grandMA2"/"onPC"? Does it appear in Windows "Programs and Features"?
  If neither, it can currently only be found via the ProgramData library
  folder (3-segment precision only), which is an architecture limit, not a
  bug, unless a fourth discovery source is worth adding.
- The `grand\s*ma\s*2` identity pattern assumes MA Lighting's own
  FileVersion metadata actually names the product recognizably (e.g.
  CompanyName containing "MA Lighting" or ProductName containing
  "grandMA2"). If a real install's own EXE metadata is unusually sparse
  (all fields blank), it would now be rejected by the identity check even
  though it's real MA2 — this trades a residual false-negative risk for
  eliminating the false-positive that was reported; worth flagging if it
  ever causes a real version to vanish.

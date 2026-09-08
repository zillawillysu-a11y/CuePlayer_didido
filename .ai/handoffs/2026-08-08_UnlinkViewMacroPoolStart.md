# Unlink View Macro Pool from Fixed Macro import start

## Task objective

Keep the View Layout Macro Pool start independent from the Fixed Macro import
start in Console Setup.

## What was implemented

- Removed the default-layout link from `ma2_fixed_macro_start` to the Screen 3
  Macro Pool window.
- Removed the reverse link from the View inspector's Macro Pool start to the
  Fixed Macro import control.
- Added a regression test proving Macro import at 191 and a View Macro Pool
  starting at 501 can coexist.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_UnlinkViewMacroPoolStart.md`

## Architecture decisions

- The macro import allocation and a View Pool's visual scroll/window are
  separate concerns; neither control updates the other.

## Tests performed

- Focused offscreen UI and MA show-patch suite: **25 passed**.

## Remaining issues

- Real MA2 verification of mixed selected content is still pending.
- `startup_error.txt` remains untouched.

## Suggested next task

Validate the mixed per-song selections in MA2, then fix only native-console
differences if found.

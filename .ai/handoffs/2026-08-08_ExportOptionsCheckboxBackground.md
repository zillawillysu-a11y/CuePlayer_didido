# Export Options checkbox background

## Task objective

Make the Export Options checkbox area use the same surface color as its panel.

## What was implemented

- Assigned an object name to the Export Options group.
- Scoped a checkbox background override to that group, preventing the global
  black `QWidget` background from showing behind the controls.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_ExportOptionsCheckboxBackground.md`

## Architecture decisions

- This is a scoped visual override, so other pages retain their existing
  checkbox appearance.

## Tests performed

- Focused offscreen UI suite: **12 passed**.

## Remaining issues

- Real MA2 verification of mixed export content selection remains pending.
- `startup_error.txt` remains untouched.

## Suggested next task

Validate mixed per-song selections in MA2 and fix only native-console
differences if found.

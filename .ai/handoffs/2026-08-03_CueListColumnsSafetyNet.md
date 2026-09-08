# Handoff: Cue List columns migration safety net

**Date:** 2026-08-03  
**TaskName:** `CueListColumnsSafetyNet`  
**Branch:** `cursor/cue-list-columns-safety-net-028d`  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Lock current `ui/cue_list_columns` behavior with tests and document dependencies /
risks before any relocate. No production behavior change; no move.

## What was implemented

- Expanded pure-API tests + persistence load normalize tests (15 passed).
- Dependency graph + risks recorded below.
- `NEXT_TASK` set to Step 1 migrate.

## Files changed

- `tests/ui/test_cue_list_columns.py` (expanded)
- `tests/persistence/test_cue_list_column_order_load.py` (new)
- Docs / `.ai` updates (`ARCHITECTURE_TARGET` step 1S, REPORT, NEXT_TASK)
- Production `cue_list_columns.py` **not** modified

## Architecture decisions

- Pure leaf module (no Qt) — safe domain candidate.
- Persistence load-path tests protect user-visible project reopen behavior.
- Header drag UX covered lightly by existing global UI test; not re-tested here.

## Tests performed

`pytest tests/ui/test_cue_list_columns.py tests/persistence/test_cue_list_column_order_load.py` → 15 passed.

## Current dependency graph

```text
cueplayer.ui.cue_list_columns
  ├── (stdlib only — no Qt, no domain, no persistence)

Consumers (import / call):
  ├── cueplayer.persistence.project_store
  │     └── normalize_cue_list_column_order(...) on song load
  │     └── saves song.cue_list_column_order list as-is
  ├── cueplayer.ui.cue_monitor_panel
  │     └── CUE_LIST_FIELDS, CUE_LIST_FIELD_LABELS,
  │         DEFAULT_CUE_LIST_COLUMN_ORDER, LOGICAL_INDEX_BY_FIELD,
  │         normalize_cue_list_column_order
  │     └── header labels, widths, reorder, note-column logical index
  ├── tests/ui/test_cue_list_columns.py
  ├── tests/ui/test_cue_list_global_ui.py  (LOGICAL_INDEX_BY_FIELD + header modes)
  └── tests/persistence/test_cue_list_column_order_load.py

Domain field (data, not import of the helper module):
  └── Song.cue_list_column_order: list[str]
```

**Forbidden edge today:** `persistence → ui` (must clear in Step 1).

## Behavior covered by tests

| Behavior | Where |
|----------|--------|
| Default order Time/Type/Cue ID/Note | `test_cue_list_columns` |
| Fields/labels/logical index consistency | same |
| Normalize fills missing fields | same |
| Drops unknown + duplicates (keeps first) | same |
| `None` / `[]` → default | same |
| Strip + case-fold keys | same |
| Preserves first-seen valid permutation | same |
| Idempotent; always full permutation | same |
| Module source has no Qt imports | same |
| `project_store` still imports from `ui` (sentinel) | same — **update on migrate** |
| `load_project` normalizes dirty JSON order (Unicode names) | `test_cue_list_column_order_load` |
| Missing key on disk → default order | same |
| Header Interactive + movable (integration) | existing `test_cue_list_global_ui` |

## Remaining migration risks

1. Shim must re-export **all** public names, not only `normalize_*`.
2. Flip persistence import to domain without changing normalize outputs (safety-net asserts exact lists).
3. Update/remove the persistence→ui **sentinel** test in the migrate PR.
4. `CueMonitorPanel` logical-vs-visual column mapping bugs are pre-existing; do not “fix” during move.
5. Merge this release-based branch carefully with ports/guardrails history on older tips.
6. Manual/header drag pixel layouts are not exhaustively automated — rely on global UI test + post-migrate smoke on desktop if available.

## Suggested next task

Step 1: move module to `domain/`, shim `ui.cue_list_columns`, point `project_store` at domain, keep tests green, REPORT + handoff, **stop**.

# MA Preflight — Validation Domain

**Status:** Sprint 6 Feature Task 5 complete (Export Integration)  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint6-preflight-export-028d`  
**Package:** `cueplayer.domain.validation` + `cueplayer.application.ma_preflight_export_gate` + `cueplayer.ui.ma_preflight_dialog`

---

## Goals

- Reusable, **read-only** validation report model for MA Preflight (and future non-MA packs).
- Independent of `cueplayer.exporters` XML generation.
- Extensible rule registration for Task 2+ rule packs.
- Stable presentation layer for UI / CLI / JSON (Task 3).
- Read-only Preflight dialog (Task 4) consuming `PreflightReport` only.
- **No** auto-fixes, **no** project mutation, **no** exporter changes from Preflight.

---

## Domain model

| Type | Role |
|------|------|
| `ValidationSeverity` | `error` · `warning` · `information` |
| `ValidationCode` | Stable id (`MA001`); format `^[A-Z]{2,4}\d{3}$` |
| `ValidationIssue` | One finding: code, severity, message, subject, path, details |
| `ValidationReport` | Aggregated issues + summary helpers (`has_errors`, `sorted_issues`, …) |
| `ValidationRule` | Protocol: `code`, `title`, `evaluate(context) -> issues` |
| `ValidationRuleSet` | Ordered registry; rejects duplicate codes; `run(context)` |
| `PreflightIssueRow` | Presentation row: code, severity, category, message, song/object refs |
| `PreflightReport` | Stable sorted report: groups, `has_errors` / `has_warnings` / `summary` |

Factory helpers: `make_issue`, `coerce_severity`, `coerce_validation_code`, `run_validation`,
`build_preflight_report`, `build_preflight_report_for_project`.

Severities:

| Level | Meaning |
|-------|---------|
| **Error** | Blocks a safe-export recommendation |
| **Warning** | Review before import |
| **Information** | Mode / counts / hints |

---

## Validation lifecycle

```text
1. Build / select a ValidationRuleSet (registered rules)
2. Provide a read-only context object (Task 2: export-intent view / song snapshot)
3. report = rule_set.run(context, context_label="Song name")
4. Consumers (UI / export gate) inspect report.has_errors / sorted_issues()
5. Operator fixes data elsewhere — validation never writes back
```

Rules **inspect** context only. Appending issues onto a `ValidationReport` is not project mutation.

---

## Validation code convention

| Rule | Example |
|------|---------|
| Format | `PREFIX` (2–4 A–Z) + three digits |
| MA Preflight pack | `MA001` … `MA999` |
| Stable once shipped | Do not renumber |
| One primary code per rule | Message carries detail |
| Reusable outside MA | Other prefixes later (`TC001`, `MEDIA001`) |

Reserved MA bands:

| Band | Intent |
|------|--------|
| MA001–MA049 | Label / charset / empty / Display vs MA name |
| MA050–MA099 | Cue / sequence identity conflicts |
| MA100–MA149 | Executor / page / pool range & duplicates |
| MA150–MA199 | Timecode / mode / latency informational |
| MA200+ | Reserved |

---

## Rule registration strategy

1. Instantiate `ValidationRuleSet(rule_set_id="ma-preflight")`.  
2. `register(rule)` each rule; duplicate `code` raises.  
3. Task 2 provides `ma_preflight_rules() -> ValidationRuleSet` factory.  
4. Application layer runs rules against a **view** of export intent (not XML writers).  
5. Optional later: filter by severity / prefix without changing rule classes.

No import-time global registry — explicit registration keeps tests deterministic.

---

## Sprint 6 Task 2 — MA Validation Rule Pack (done)

**Scope tip:** `cursor/sprint6-ma-validation-rules-028d`

### Rule summary

| Code | Severity | Rule |
|------|----------|------|
| MA001 | Error | Invalid MA Export Name (non-ASCII / illegal chars) |
| MA002 | Error | Missing required Song MA Export Name |
| MA003 | Error | Duplicate Sequence identifiers |
| MA004 | Error | Invalid / colliding Executor assignments |
| MA050 | Warning | Empty Sequence (no cues) |
| MA051 | Warning | Disabled / excluded Song |
| MA052 | Warning | Unused Cue (non-export lane) |
| MA053 | Warning | Missing optional metadata (note / bpm) |
| MA150 | Information | Total Songs |
| MA151 | Information | Total Sequences |
| MA152 | Information | Total Executors |
| MA153 | Information | Total Variants |

Factory: `ma_preflight_rules()` / `run_ma_preflight(context)`.  
Context: `build_ma_preflight_context(project)` — frozen snapshot; **no** exporter imports.

### Remaining validation gaps

| Gap | Notes |
|-----|-------|
| Cue-level required MA names | Only song-level required today |
| Pool number range vs console limits | Not checked |
| Timecode-only vs full mode specifics | Info only (MA150 band); no MA100 mode issue yet |
| Latency / TC Slot conflicts | Deferred |
| Exact exporter sanitize parity | Domain uses ASCII-safe check; no pypinyin in rules |

---

## Sprint 6 Task 3 — Preflight Report Builder (done)

**Scope tip:** `cursor/sprint6-preflight-report-028d`  
**Module:** `cueplayer.domain.validation.preflight_report`

### Report lifecycle

```text
Project
  → build_ma_preflight_context (frozen snapshot)
  → run_ma_preflight → ValidationReport (raw findings)
  → build_preflight_report → PreflightReport (presentation)
  → format_text() / to_dict() for CLI / JSON / future UI
```

Convenience: `build_preflight_report_for_project(project)` runs the full chain.  
The project is never mutated. Exporters are never imported.

### Report API

| Symbol | Role |
|--------|------|
| `PreflightCategory` | Presentation buckets: labels, sequences, executors, cues, songs, metadata, summary, other |
| `PreflightIssueRow` | One row: code, severity, category, message, song_id/name, object_kind/id, path, details |
| `PreflightReport` | Frozen report: `issues`, `has_errors`, `has_warnings`, `summary()`, groups, `format_text()`, `to_dict()` |
| `build_preflight_report(ValidationReport, context=…, title=…)` | Raw → presentation |
| `build_preflight_report_for_project(Project)` | Snapshot → rules → presentation |
| `category_for_code(code)` | MA code → category |

Each issue row exposes:

- `ValidationCode`
- `Severity`
- `Category`
- Song / object reference (`song_id`, `song_name`, `object_ref`)
- Human-readable `message`

### Sorting rules (deterministic)

Issues are sorted by this key (ascending):

1. Severity rank — error → warning → information  
2. Category rank — labels → sequences → executors → cues → songs → metadata → summary → other  
3. Code string (`MA001` …)  
4. Song name (casefold)  
5. Song id  
6. Object ref (`kind:id`)  
7. Path  
8. Message  

`grouped_by_severity()` and `grouped_by_category()` preserve that order within each bucket.

### Summary generation

```text
{title}: {N} error(s), {M} warning(s), {K} info
```

- `has_errors` / `has_warnings` — boolean gates for export dialogs  
- Counts from severity partitions of the sorted `issues` tuple  

### Example output (text)

```text
Demo Show: 2 error(s), 1 warning(s), 4 info

## ERROR
[ERROR] MA001  (labels)  Song MA Export Name has non-ASCII  [song:s1]
[ERROR] MA002  (labels)  Song is missing MA Export Name  [song:s2]

## WARNING
[WARNING] MA050  (sequences)  Sequence 'Opening' has no cues  [sequence:s1:main]

## INFORMATION
[INFORMATION] MA150  (summary)  Total songs: 2 (1 included)  [project:songs]
…
```

### Example output (JSON shape)

```python
report = build_preflight_report_for_project(project)
payload = report.to_dict()
# {
#   "title": "Demo Show",
#   "rule_set_id": "ma-preflight",
#   "summary": "Demo Show: 2 error(s), …",
#   "has_errors": true,
#   "has_warnings": true,
#   "error_count": 2,
#   "warning_count": 1,
#   "information_count": 4,
#   "issues": [ { "code": "MA001", "severity": "error", "category": "labels", … }, … ],
#   "by_severity": { "error": [...], "warning": [...], "information": [...] },
#   "by_category": { "labels": [...], "sequences": [...], … }
# }
```

### Future serialization strategy

| Consumer | Strategy |
|----------|----------|
| **JSON** | `PreflightReport.to_dict()` — stable keys; dump with `json.dumps` for file / IPC |
| **CLI** | `format_text()` — severity sections; suitable for `cueplayer preflight` later |
| **UI (Task 4)** | Bind table model to `issues` or `grouped_by_severity()`; gate Export on `has_errors` |

Do not invent a second schema in the UI layer — consume this object / dict only.

### Coverage

- Unit tests: `tests/domain/test_preflight_report.py`
- Category mapping for MA001–004, MA050–053, MA150–153
- Deterministic sort / group / summary / text / JSON round-trip
- Project read-only after `build_preflight_report_for_project`
- Prior rule + framework suites remain green

### Remaining work (after Task 3)

| Item | Notes |
|------|-------|
| Preflight UI | ✅ Task 4 |
| Export gate | Task 5 — wire Export to `has_errors` |
| CLI entry | Optional thin wrapper calling `format_text()` |
| Auto-fix | Still deferred — separate command layer later |
| Deeper rules | Cue-level names, pool ranges, TC mode — still Task 2 gaps |

---

## Sprint 6 Task 4 — Preflight UI (done)

**Scope tip:** `cursor/sprint6-preflight-ui-028d`  
**Module:** `cueplayer.ui.ma_preflight_dialog.MaPreflightDialog`  
**Entry:** Tools → **MA Preflight…**

### UI layout

```text
┌─ MA Preflight ─────────────────────────────────────┐
│ Demo Show: 1 error(s), 2 warning(s), 1 info          │
│ Errors: 1    Warnings: 2    Information: 1           │
│ Hint: double-click to navigate (read-only)           │
│ ┌──────────────────────────────────────────────────┐ │
│ │ Code │ Severity │ Song / Object │ Message        │ │
│ │ MA001│ error    │ 開場          │ …              │ │
│ │ MA050│ warning  │ 開場 · seq…   │ …              │ │
│ │ …    │ …        │ …             │ …              │ │
│ └──────────────────────────────────────────────────┘ │
│                                          [ Close ]   │
└──────────────────────────────────────────────────────┘
```

- One table (report already sorted: errors → warnings → information).
- No filter / search / auto-fix in MVP.
- Dialog accepts **`PreflightReport` only** — never calls `run_ma_preflight` / rule factories.
- Host (`MainWindow._open_ma_preflight`) builds the report via `build_preflight_report_for_project`.

### Navigation behavior

| Double-click target | Action |
|---------------------|--------|
| `song:…` | Activate that song in the setlist |
| `mark:…` (+ `song_id`) | Activate song, select mark, seek playhead |
| `sequence:…` (+ `song_id`) | Activate song |
| `project:` / `settings:` / executor-only / info totals | No navigation |

Signal: `navigate_requested(song_id, object_kind, object_id)`.

### Coverage

- UI tests: `tests/ui/test_ma_preflight_dialog.py`
- Layout / summary counts / double-click navigate / read-only / no exporter imports

### Remaining UX work

| Item | Notes |
|------|-------|
| Category column | Optional; severity + code sufficient for MVP |
| Keep dialog open while jumping | Modal today; modeless later if needed |
| Highlight mark after seek | Timeline selection set; cue-list scroll polish later |
| Filter / search | Explicitly out of MVP |
| Export integration | ✅ Task 5 |

### Risks

| Risk | Mitigation |
|------|------------|
| Stale report if project edited while dialog open | Dialog is modal; rebuild on each open |
| Missing `song_id` on some issues | `navigation_target` returns `None`; no jump |
| Operators expect auto-fix | Hint text + no Fix buttons |

---

## Sprint 6 Task 5 — Export Integration (done)

**Scope tip:** `cursor/sprint6-preflight-export-028d`  
**Application:** `cueplayer.application.ma_preflight_export_gate`  
**UI present:** `present_export_preflight_gate` · wired from `ShowPatchPage._export`

### Export workflow

```text
Show Patch → Export Checked Songs…
  1. Write UI → MaExportSettings
  2. Validate folder
  3. evaluate_ma_preflight_for_export(project)   # fresh ValidationReport every time
  4. present_export_preflight_gate(gate)         # dialog if any issues
  5. If gate denies → stop (exporters never called)
  6. Existing empty-main-cues confirm (unchanged)
  7. Ma2Exporter / Ma3Exporter.export_show_to_directory  # export only
```

Layers:

| Layer | Responsibility |
|-------|----------------|
| Validation engine | Produce `ValidationReport` (independent) |
| Application gate | Fresh evaluate + allow/deny from **ValidationReport only** |
| UI | Present `PreflightReport`; Continue / Cancel |
| Exporters | Write XML only — **no** validation |

### Error / Warning behavior

| Severity | Dialog | Continue Export |
|----------|--------|-----------------|
| **Error** | Shown | **Blocked** (Close / Cancel only) |
| **Warning** | Shown | Allowed (Continue Export) |
| **Information** | Always included when dialog shown | Allowed |

- Dialog appears whenever `ValidationReport` has any issues (info totals count).
- Even if the dialog were accepted, `present_export_preflight_gate` still returns `False` when `validation.has_errors`.
- No result caching — every export re-runs rules.

### Coverage

- Application: `tests/application/test_ma_preflight_export_gate.py`
- UI gate mode: `tests/ui/test_ma_preflight_dialog.py`
- Integration: `tests/ui/test_ma_preflight_export_integration.py`

### Remaining UX improvements

| Item | Notes |
|------|-------|
| Force-export override | Not in MVP (errors hard-block) |
| Skip dialog when info-only | Optional preference later |
| Modeless jump-from-export | Modal today |
| CLI preflight before headless export | Reuse application gate |
| Auto-fix | Still deferred |

### Risks

| Risk | Mitigation |
|------|------------|
| Info rules always open dialog | Intentional review; preference later |
| Settings not flushed before gate | Gate runs after `_write_ui_to_settings` |
| Operators want force-export | Documented hard block; Sprint 7 if needed |

### Recommendation for Sprint 7

1. **Production soak** — real show files through Preflight → Export on MA2/MA3.  
2. Optional **force-export** (hold modifier / confirm) if operators need it.  
3. Deeper rules (cue-level required names, pool ranges, TC mode).  
4. Optional CLI: `evaluate_ma_preflight_for_export` + `format_text()`.  
5. Do **not** put validation inside exporters; keep the gate.

Still **no** auto-fix.

---

## Extension strategy

| Extension | Approach |
|-----------|----------|
| Sprint 7 polish / soak | Prefer prefs + deeper rules over exporter rewrites |
| Export-intent fidelity | Keep `MaPreflightContext` aligned with Show Patch fields |
| Auto-fix (later) | Separate command layer; never inside `evaluate` or report builder |
| Non-MA packs | New prefixes + rule sets; reuse `build_preflight_report` |

---

## READY FOR MA PREFLIGHT PRODUCTION

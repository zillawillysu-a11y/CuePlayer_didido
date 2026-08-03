# MA Preflight — Validation Domain

**Status:** Sprint 6 Feature Task 3 complete (report builder)  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint6-preflight-report-028d`  
**Package:** `cueplayer.domain.validation`

---

## Goals

- Reusable, **read-only** validation report model for MA Preflight (and future non-MA packs).
- Independent of `cueplayer.exporters` XML generation.
- Extensible rule registration for Task 2+ rule packs.
- Stable presentation layer for UI / CLI / JSON (Task 3).
- **No** UI, **no** auto-fixes, **no** project mutation.

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

### Remaining work

| Item | Notes |
|------|-------|
| Preflight UI | Task 4 — dialog / panel over `PreflightReport` |
| Export gate | Wire Export action to `has_errors` (warn-or-block policy TBD) |
| CLI entry | Optional thin wrapper calling `format_text()` |
| Auto-fix | Still deferred — separate command layer later |
| Deeper rules | Cue-level names, pool ranges, TC mode — still Task 2 gaps |

### Recommendation for Task 4 (Preflight UI)

1. Read-only dialog: summary line + severity-filtered table bound to `PreflightReport.issues`.  
2. Columns: Severity, Code, Category, Song, Object, Message.  
3. Export menu: run `build_preflight_report_for_project` first; if `has_errors`, block or confirm.  
4. No auto-fix buttons in MVP; “Open song” navigation optional.  
5. Do **not** call exporters from the preflight UI.

Still **no** auto-fix, **no** XML write, **no** exporter changes in Task 3.

---

## Extension strategy

| Extension | Approach |
|-----------|----------|
| Task 4 Preflight UI | Present `PreflightReport` in a dialog / export gate |
| Export-intent fidelity | Keep `MaPreflightContext` aligned with Show Patch fields |
| Auto-fix (later) | Separate command layer; never inside `evaluate` or report builder |
| Non-MA packs | New prefixes + rule sets; reuse `build_preflight_report` |

---

## READY FOR PREFLIGHT UI

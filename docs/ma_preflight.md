# MA Preflight — Validation Domain

**Status:** Sprint 6 Feature Task 1 complete (domain framework only)  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint6-ma-preflight-domain-028d`  
**Package:** `cueplayer.domain.validation`

---

## Goals

- Reusable, **read-only** validation report model for MA Preflight (and future non-MA packs).
- Independent of `cueplayer.exporters` XML generation.
- Extensible rule registration for Task 2+ rule packs.
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

Factory helpers: `make_issue`, `coerce_severity`, `coerce_validation_code`, `run_validation`.

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

Reserved MA bands (planned for Task 2; not enforced in code yet):

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

## Example validation report

```text
開場: 1 error(s), 1 warning(s), 1 info

[ERROR] MA001  MA Export Name contains non-ASCII characters
        subject=mark:m1  path=marks[0].ma_export_name  value=主歌A

[WARNING] MA010  Executor 1.201 already used by another sequence
        subject=executor:1.201  sequence=TopBtn_2

[INFORMATION] MA100  Export mode: full (sequences + timecode)
        mode=full
```

Python shape:

```python
from cueplayer.domain.validation import ValidationReport, make_issue

report = ValidationReport(context_label="開場", rule_set_id="ma-preflight")
report.add(make_issue(
    "MA001",
    "error",
    "MA Export Name contains non-ASCII characters",
    subject="mark:m1",
    path="marks[0].ma_export_name",
    details={"value": "主歌A"},
))
```

---

## Extension strategy

| Extension | Approach |
|-----------|----------|
| Task 3 Report Builder | Present `ValidationReport` for UI / export gate (no auto-fix) |
| Export-intent fidelity | Keep `MaPreflightContext` aligned with Show Patch fields |
| Auto-fix (later) | Separate command layer; never inside `evaluate` |
| Non-MA packs | New prefixes + rule sets (framework already reusable) |

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

### Example report (after rules)

```text
Show: 2 error(s), 3 warning(s), 4 info

[ERROR] MA001  Song MA Export Name has non-ASCII
[ERROR] MA002  Song is missing MA Export Name
[WARNING] MA050  Sequence 'Opening' has no cues
[WARNING] MA051  Song 'Skip' is excluded from export
[INFORMATION] MA150  Total songs: 2 (1 included)
…
```

### Coverage

- Errors / warnings / information listed above
- Unit tests: `tests/domain/test_ma_preflight_rules.py`
- Read-only: project fields unchanged after `run_ma_preflight`

### Remaining validation gaps

| Gap | Notes |
|-----|-------|
| Cue-level required MA names | Only song-level required today |
| Pool number range vs console limits | Not checked |
| Timecode-only vs full mode specifics | Info only (MA150 band); no MA100 mode issue yet |
| Latency / TC Slot conflicts | Deferred |
| Exact exporter sanitize parity | Domain uses ASCII-safe check; no pypinyin in rules |

### Recommendation for Task 3 (Report Builder)

Build a **Preflight Report** presentation layer over `ValidationReport`:

1. Group by severity / song / code  
2. Stable sort for UI tables  
3. Optional JSON/text export of the report (still no project mutation)  
4. Hook point for future Export dialog gate (`has_errors`)  

Still **no** auto-fix, **no** XML write, **no** exporter changes.

---

## READY FOR PREFLIGHT REPORT

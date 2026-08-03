# MA Export Preflight — Validation Domain

**Status:** Sprint 6 Feature Task 1 complete (domain framework only)  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint6-ma-preflight-domain-028d`  
**Package:** `cueplayer.domain.validation`

---

## Goals

- Reusable, **read-only** validation report model for MA Export Preflight.
- Independent of `cueplayer.exporters` XML generation.
- Extensible rule registration for Task 2+ rule packs.
- **No** UI, **no** auto-fixes, **no** project mutation.

---

## Domain model summary

| Type | Role |
|------|------|
| `ValidationSeverity` | `error` · `warning` · `information` |
| `ValidationCode` | Stable id (`MA001`); format `^[A-Z]{2,4}\d{3}$` |
| `ValidationIssue` | One finding: code, severity, message, subject, path, details |
| `ValidationReport` | Aggregated issues + summary helpers |
| `ValidationRule` | Protocol: `code`, `title`, `evaluate(context) -> issues` |
| `ValidationRuleSet` | Ordered registry; rejects duplicate codes; `run(context)` |

Factory helpers: `make_issue`, `coerce_severity`, `coerce_validation_code`, `run_validation`.

---

## Validation lifecycle

```text
1. Build / select a ValidationRuleSet (registered rules)
2. Provide a read-only context object (Task 2: export plan view / song snapshot)
3. report = rule_set.run(context, context_label="Song name")
4. Consumers (UI / export gate) inspect report.has_errors / sorted_issues()
5. Operator fixes data elsewhere (Apply / edit) — validation never writes back
```

Rules **inspect** context only. Reports may append issues to themselves; that is not project mutation.

---

## ValidationCode naming rules

| Rule | Example |
|------|---------|
| Format | `PREFIX` (2–4 A–Z) + three digits |
| MA export pack | `MA001` … `MA999` |
| Stable once shipped | Do not renumber |
| One primary code per rule | Message carries detail |
| Other domains later | e.g. `TC001`, `MEDIA001` |

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
3. Task 2 provides `ma_export_preflight_rules() -> ValidationRuleSet` factory.  
4. Application layer runs rules against a **view** of export intent (not by importing XML writers).  
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
report.add(make_issue("MA001", "error", "MA Export Name contains non-ASCII characters",
                      subject="mark:m1", path="marks[0].ma_export_name",
                      details={"value": "主歌A"}))
```

---

## Future extension strategy

| Extension | Approach |
|-----------|----------|
| Task 2 concrete rules | New modules under `domain/validation/ma_rules/` or `application/ma_preflight/` calling domain types |
| Export-plan context | Protocol / dataclass **view** built from song+patch — still no exporter XML deps inside rules if avoidable |
| UI Preview | Consume `ValidationReport` only |
| Auto-fix (later) | Separate command layer; never inside `evaluate` |
| Non-MA packs | New prefixes + rule sets |

---

## Risks

| Risk | Mitigation |
|------|------------|
| Rules accidentally mutate context | Protocol docs + unit tests with mutable spy |
| Preview drift from real export | Task 2 context must mirror `plan_from_song` fields |
| Code renumbering chaos | Document bands; freeze codes once shipped |
| Coupling to exporters | Domain package forbids exporter imports |

---

## Recommendation for Task 2 (Validation Rules)

Implement the first **MA rule pack** against a read-only export-intent context:

1. Empty / illegal / non-ASCII MA Export Names (`MA001`–).  
2. Duplicate MA labels / executor collisions (`MA010`–).  
3. Pool / page / executor range checks.  
4. Mode information (`timecode_only` vs `full`) as Information.  

Still **no UI**, **no XML write**, **no auto-fix**. Wire tests with song fixtures; keep domain types unchanged unless gaps appear.

---

## READY FOR VALIDATION RULES

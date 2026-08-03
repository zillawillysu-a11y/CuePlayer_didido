# Sprint 0 Retrospective

**Status:** Complete (review only — no feature / migration / refactor in this document’s delivery)  
**Date:** 2026-08-03  
**Scope of Sprint 0:** Establish AI engineering workflow, architecture guardrails, interface-first `ports/` (on architecture line), first strangler migrate (`cue_list_columns` → domain on release line), and repo-local history (`.ai/`).  
**Audience:** Humans + ChatGPT / Cursor (engineering history without chat)

Related archives:

| Handoff | Topic |
|---------|--------|
| `.ai/handoffs/2026-08-03_PermanentAiWorkflowStandard.md` | AI READ→PLAN→REPORT→STOP |
| `.ai/handoffs/2026-08-03_PortsPackageStep0.md` | `ports/` Protocols |
| `.ai/handoffs/2026-08-03_ArchitectureGuardrails.md` | BOUNDARY + MIGRATION rules |
| `.ai/handoffs/2026-08-03_CueListColumnsSafetyNet.md` | Pre-migrate test lock |
| `.ai/handoffs/2026-08-03_CueListColumnsDomainMigrate.md` | Step 1 domain + shim |

---

## 1. Objectives achieved

| Objective | Outcome |
|-----------|---------|
| Repo-local AI handoff (survive multi-machine / no chat sync) | ✅ `.ai/README`, `WORKFLOW`, `NEXT_TASK`, `REPORT`, `handoffs/`, `prompts/cursor_system.md`, Cursor rule `ai-workflow.mdc` |
| Permanent task loop | ✅ Plan before code; REPORT + handoff; ChatGPT paste block; stop (no auto-continue) |
| As-built + target architecture written down | ✅ `ARCHITECTURE_REVIEW.md`, `ARCHITECTURE_TARGET.md` |
| Dependency + migration law | ✅ `BOUNDARY_RULES.md`, `MIGRATION_RULES.md` (inserted before first prod move) |
| Interface-first ports (step 0) | ✅ `cueplayer.ports` Protocols on architecture PR line |
| Safety net before first move | ✅ Expanded column-order + persistence load tests |
| First real strangler migrate (step 1) | ✅ `cue_list_columns` → `domain/`; UI shim; `persistence` → domain (clears forbidden persistence→ui) |
| Product clock / product non-negotiables untouched | ✅ No second playback clock; no feature scope shrink |

Sprint 0 was **foundation**, not feature delivery. Product 1.0.x work (video audio stutter, Web Remote password, Note arrow, packaging) continued on release tips in parallel and is **out of Sprint 0’s architecture charter**, but informed risk notes (locks, shared `Song`).

---

## 2. What worked well

1. **Strangler discipline on a tiny leaf** — `cue_list_columns` was Qt-free, pure, and well suited to domain; shim + safety-net made the move low-drama (23 tests green).
2. **Safety net before move** — exact normalize lists + persistence load path + shim `is` identity caught the need to flip the persistence→ui sentinel deliberately.
3. **Guardrails before production relocate** — BOUNDARY/MIGRATION docs gave agents a shared “law” instead of rediscovering rules in chat.
4. **`.ai/` as source of truth** — REPORT/handoffs/ChatGPT paste made cross-tool review possible without Cursor transcript portability.
5. **One-module / stop rule** — prevented stacking RemoteHost + columns + adapters in one turn.
6. **Clear forbidden-edge win** — persistence no longer imports `ui.cue_list_columns`.

---

## 3. Problems discovered

1. **Branch topology split** — Architecture docs / `ports/` were started from an older `master` tip that **lacked** `cue_list_columns`; safety-net + Step 1 had to rebase onto **release** tip and overlay `.ai`/docs. Result: multiple parallel PR chains that are easy to mis-merge.
2. **`ports/` not present on the release-based migrate tip** — Step 0 exists on `cursor/ports-package-step0-028d` (and parents), but this Sprint 0 “complete” product line may only have leftover `__pycache__` under `ports/`. Step 2 cannot assume `import cueplayer.ports` works until lines are unified.
3. **Doc sprawl / duplication** — ARCHITECTURE.md, REVIEW, TARGET, BOUNDARY, MIGRATION, AGENTS, `.ai/WORKFLOW` overlap on “one module”, clock rule, and forbidden edges.
4. **PRODUCT_SPEC status header still stale** (“尚未開始實作”) vs shipped app — confuses new agents.
5. **As-built giants remain** — `MainWindow`, `TimelineWidget`, `AudioEngine`, `av_path_lock` contention unchanged; Sprint 0 did not reduce runtime fragility.
6. **Shim debt starts immediately** — `ui.cue_list_columns` shim + callers still on ui path (`cue_monitor_panel`) by design; must not be forgotten.
7. **Empty package stubs** — `timeline/`, `ltc/` packages still empty placeholders (pre-existing).

---

## 4. Technical debt introduced

| Debt | Why it exists | Pay-down hint |
|------|----------------|---------------|
| `ui.cue_list_columns` shim | Backward-compatible imports | Later task: point callers at domain, then delete shim |
| Parallel git lines (architecture vs release) | Started ports/docs on stale master | Merge/rebase Sprint 0 architecture commits onto release/`master` once; single trunk |
| Ports Protocols unused | Interface-first; no wiring yet | Step 2+ adopt `RemoteHost` / clock façades |
| Sentinel/tests knowledge | Tests encode import paths | Keep updating when edges change |
| Extra architecture markdown surface | Needed for clarity mid-sprint | See §5 merge recommendations |
| `.ai` + architecture docs copied onto release branch | Continuity for migrate | Prefer merge commits over copy-overlay next time |

**Not introduced (pre-existing, still open):** MainWindow god-object, dual LTC detect paths, remote→MainWindow privates, `domain.media_relink` cross-layer helper, video lock thrash risk.

---

## 5. Documentation quality review

### Strengths

- Permanent rules are explicit and CuePlayer-specific (not generic clean-arch boilerplate).
- Handoffs include checklists / rollback for the migrate — good ChatGPT audit trail.
- Cross-links from AGENTS / ARCHITECTURE / `.ai` make discovery possible.

### Weaknesses

- **Too many overlapping “how to move / what depends on what” docs** (see merge recommendations below).
- ARCHITECTURE.md still shows the old aspirational “Domain owns everything” fan-out diagram that **doesn’t match** BOUNDARY_RULES target (`ui → application → ports ← adapters`).
- PRODUCT_SPEC front-matter status is misleading.
- REVIEW is long and partially duplicated by TARGET + BOUNDARY.

### Merge / simplify recommendations (do **not** execute in this retrospective)

| Action | Rationale |
|--------|-----------|
| Keep **BOUNDARY_RULES** + **MIGRATION_RULES** as the only “law” docs | Clearest permanent rules |
| Slim **ARCHITECTURE.md** to a short map + links only (remove competing long layer story or align it 1:1 with BOUNDARY) | Stops contradictory diagrams |
| Keep **ARCHITECTURE_TARGET** as the ordered backlog table only; move narrative into TARGET intro referencing BOUNDARY/MIGRATION | One queue of record |
| Treat **ARCHITECTURE_REVIEW** as historical as-built snapshot; add banner “as of 2026-08; not the migration procedure” | Avoid agents following REVIEW as process |
| Deduplicate clock / Unicode / MA rules: **AGENTS.md** remains product non-negotiables; architecture docs link out instead of restating | Single product truth |
| Keep `.ai/WORKFLOW` as process; avoid restating full BOUNDARY tables inside it | Link, don’t copy |
| Fix PRODUCT_SPEC status header in a docs-only chore | Reduces false “greenfield” reads |

No documentation files were deleted or merged in this retrospective delivery (review-only).

---

## 6. AI workflow review

| Practice | Assessment |
|----------|------------|
| READ → PLAN → IMPLEMENT → REPORT → HANDOFF → STOP | Worked; prevented runaway multi-step migrates |
| ChatGPT paste block | Useful for human↔ChatGPT↔Cursor triangle |
| `NEXT_TASK` single focus | Worked when updated; risk if branches diverge and NEXT_TASK disagrees with reality |
| Cursor `alwaysApply` rule | Reinforces workflow for new sessions |
| Plan-before-code | Especially valuable for migrate vs “just git mv” |
| Stop rule | Observed for architecture steps; product bugfixs earlier in release were outside this discipline |

**Gaps:** Workflow does not yet require “confirm module exists on this git tip before planning a migrate” (the missing-`cue_list_columns`-on-old-master issue). Recommend adding that check to MIGRATION_RULES / WORKFLOW in Sprint 1 **docs chore** (recommendation only).

---

## 7. Architecture review

### Progress vs target

```text
Done in Sprint 0:
  ports/          (Protocols on architecture line)
  BOUNDARY/MIGRATION law
  domain/cue_list_columns + ui shim
  persistence → domain for normalize

Not started:
  application/* services
  adapters/* package moves
  RemoteHost adoption
  SongSession / MediaJobQueue / FrameBus wiring
  MainWindow thinning
```

### Dependency health

- ✅ One forbidden edge cleared: `persistence → ui` (for columns).
- ⚠️ Many as-built violations remain (remote privates, domain media_relink, ui hub).
- ⚠️ Ports unused on the migrate tip until merge.

### Runtime architecture

Unchanged and still the highest product risk: shared `av_path_lock`, shared mutable `Song`, mega-`MainWindow` / `AudioEngine`. Sprint 0 correctly did **not** touch these.

---

## 8. Remaining risks

1. Merging architecture PR chain into release/`master` without a planned integration order → lost ports or duplicated `.ai` conflicts.
2. Starting Step 2 RemoteHost before `ports` exists on the working tip.
3. Deleting the columns shim too early → break `cue_monitor_panel` / tests still on ui path.
4. Agents treating ARCHITECTURE.md old diagram as current law.
5. Continuing product hotfixes on release while architecture docs lag → NEXT_TASK points at work the tip cannot build.
6. Lock/Song fragility still can cause user-visible A/V issues independent of package layout.

---

## 9. Lessons learned

1. **Pick a trunk before strangling** — start foundation docs/ports on the same tip that has the modules you will move.
2. **Smallest leaf first was the right migrate** — columns was ideal; don’t start with `MainWindow`.
3. **Safety net pays for itself** — especially import-path sentinels that must intentionally flip.
4. **Law docs beat long reviews for day-to-day agent behavior** — BOUNDARY/MIGRATION > rereading REVIEW every time.
5. **Shims are features of the strategy, not failures** — but they need an explicit delete backlog.
6. **Chat-free history works only if REPORT/handoff stay honest about branch bases.**

---

## 10. Recommended priorities for Sprint 1

Recommendations only — **do not encode as `.ai/NEXT_TASK` here.** Human chooses order.

### P0 — Stabilize the foundation line

1. **Integrate git lines:** merge architecture (`ports`, guardrails) + columns migrate onto one trunk (`master` or release integrate). Verify `import cueplayer.ports` and columns domain/shim on that trunk.
2. **Docs chore:** apply §5 merge/simplify (slim ARCHITECTURE.md; banner on REVIEW; fix PRODUCT_SPEC status). Add “module exists on tip” check to migration workflow.

### P1 — Next strangler seams (still one module per task)

3. **RemoteHost adoption** (former TARGET step 2) — only after ports on trunk.
4. **Remove columns shim** after switching `cue_monitor_panel` (+ tests) to `domain.cue_list_columns`.
5. **`application/autosave_service` or `project_service` extract** — first MainWindow thinning with no behavior change.

### P2 — Risk reduction (product-adjacent, still disciplined)

6. Document `av_path_lock` consumer registry (docs-only) before any mixer/video change.
7. `SongSession` port adoption for refresh contracts (reduce missed refresh bugs).

### Explicitly defer

- Full `adapters/` package renames of playback/media.
- NDI-only milestones, multi-audio Align Anchors, etc. as **product** sprints — not mixed into architecture moves.
- Rewriting `AudioEngine` / timeline paint splits until application shell exists.

---

## Sprint 0 scorecard (summary)

| Area | Grade | Note |
|------|-------|------|
| AI workflow | A- | Solid loop; tip-awareness gap |
| Architecture law | A | BOUNDARY/MIGRATION landed |
| First migrate | A | Clean leaf + tests |
| Trunk hygiene | C | Split lines / ports missing on migrate tip |
| Doc duplication | B- | Complete but overlapping |
| Runtime debt | — | Unchanged (out of scope) |

**Verdict:** Sprint 0 met its foundation goals. Sprint 1 should **unify the branch line and docs**, then continue one-module strangler moves—not new features under the architecture banner.

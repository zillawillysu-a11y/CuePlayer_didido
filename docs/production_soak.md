# CuePlayer — Production Soak Plan (Sprint 7)

**Status:** Planning complete (docs only — no new features)  
**Updated:** 2026-08-04  
**Scope tip:** `cursor/sprint7-production-soak-028d`  
**Audience:** Operators + engineering review before Sprint 7 Feature Planning  

**Pillars under soak**

| Pillar | What “done enough” means for soak |
|--------|-----------------------------------|
| **Song Variant** | Select-one mix playback; persistence; Song Time cues stay put |
| **Align Anchors** | Draft → Preview → Apply/undo; Cancel restores entry; marks fixed in Song Time |
| **MA Preflight** | Tools review + export gate; errors block; warnings allow Continue; MA2/MA3 import succeeds |

Related: [`song_variant_design.md`](song_variant_design.md) · [`ma_preflight.md`](ma_preflight.md) · [`roadmap.md`](roadmap.md) · [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md)

---

## Goals

1. Run CuePlayer on **real shows** (laptop + desktop) without adding features.  
2. Collect structured feedback on Variants, Align Anchors, and MA Preflight.  
3. Decide Sprint 7 Feature Planning priorities from evidence, not speculation.  

**Out of scope for this plan:** code changes, auto-fix, exporter redesign, Variant CRUD chrome, overlay compare, NDI/OSC.

---

## 1. Production checklist

Use before calling a show “soak-ready.” Check boxes on site; attach notes to the run log.

### A. Environment

- [ ] Windows build from a known tip (record commit SHA / PR stack).  
- [ ] Audio device: production interface (Focusrite / soundcard), not only laptop speakers.  
- [ ] Unicode paths: project folder and media under a Chinese / mixed-name directory.  
- [ ] Autosave + recent files work after a cold start.  
- [ ] Optional: Bundle collect then open on the second machine.

### B. Song Variant

- [ ] Song with **Main** + ≥1 alternate mix; switch active variant; hear correct bed.  
- [ ] Marks / cue list times unchanged after variant switch (Song Time).  
- [ ] Save → reopen → selected variant restored.  
- [ ] Legacy song (no variants / offset 0) still loads and plays.  
- [ ] Relink / missing media path heal does not drop variant paths silently.

### C. Align Anchors

- [ ] Tools → Align Anchors: capture anchors, draft updates, Preview auditions offset.  
- [ ] Cancel / close restores entry (position / loops / playing) — no stuck preview.  
- [ ] Apply commits via undo; Ctrl+Z restores prior `anchor_offset`.  
- [ ] After Apply, marks still sit on Song Time; only mix alignment changes.  
- [ ] Song switch while Preview ends preview safely.

### D. MA Preflight + Export

- [ ] Tools → MA Preflight… shows Errors / Warnings / Information with codes.  
- [ ] Double-click navigates to Song / mark when applicable.  
- [ ] Show Patch → Export: fresh dialog; **errors block**; warnings allow Continue.  
- [ ] Fix MA Export Name (ASCII) → re-export succeeds; Chinese never appears in XML labels.  
- [ ] MA2 full + MA3 full (or timecode-only) import smoke on console or offline XML inspect.  
- [ ] Timecode-only re-export after executors already assigned (if used on this show).

### E. Reliability pass

- [ ] Missing media → Relink dialog → play resumes.  
- [ ] Undo/Redo across mark edit, Align Apply, setlist move (no silent desync).  
- [ ] Large setlist scroll / song switch does not stall transport for multi-second freezes.  
- [ ] No second clock feel: video / playhead track audio (sample clock).

### F. Sign-off

- [ ] Operator name / date / show name recorded.  
- [ ] Blockers filed (severity: stop-show / workaround / polish).  
- [ ] Verdict: **Pass** · **Pass with notes** · **Fail — block Feature Sprint until fixed**.

---

## 2. Test matrix

Rows = scenarios. Columns = pillars / concerns. Mark **P** pass, **F** fail, **N** N/A, **W** workaround.

| # | Scenario | Variant | Align | Preflight | Export | Undo | Media | Perf notes |
|---|----------|---------|-------|-----------|--------|------|-------|------------|
| S1 | **New project** — blank → add songs → audio → marks → Align → Preflight → Export | | | | | | | |
| S2 | **Legacy project** — pre-variant / offset-0 file from archive | | | | | | | |
| S3 | **Large show** — ≥30 songs, many marks, folders, mixed MA names | | | | | | | |
| S4 | **Multiple variants** — 2–3 mixes/song; switch under play; save/reload | | | | | | | |
| S5 | **MA export** — MA2 full + MA3 full; Preflight errors then fix; warnings Continue | | | | | | | |
| S6 | **Error recovery** — bad MA name, empty sequence, excluded song; recover without crash | | | | | | | |
| S7 | **Missing media** — move folder → Relink → Bundle path | | | | | | | |
| S8 | **Undo/Redo** — mark nudge, Align Apply, setlist reorder, song edit | | | | | | | |
| S9 | **Performance** — scrub, zoom, song switch, export of large show | | | | | | | |

### Scenario scripts (expected operator actions)

#### S1 — New project

1. New Project → add 2–3 songs with Unicode names.  
2. Drop audio; set `ma_export_name` ASCII; place Main + Top Button marks.  
3. Add a second variant mix; Align Anchors Preview → Apply.  
4. Tools → MA Preflight; then File → Export / Show Patch → Export.  
5. **Success:** XML imports; cues fire on console at intended TC.

#### S2 — Legacy project

1. Open an old `.cueproj` / bundle without variants (or offset 0 only).  
2. Play, scrub, export timecode-only if that was the old habit.  
3. Optionally add one variant and Align once.  
4. **Success:** No migration surprise; marks and TC unchanged vs last known good.

#### S3 — Large show

1. Open production setlist (≥30 songs).  
2. Jump songs, scrub waveforms, open Preflight, export checked subset.  
3. **Success:** No multi-second UI freeze; Preflight completes; export finishes; memory stable enough for rehearsal.

#### S4 — Multiple variants

1. Per song: Main + “Old mix” / “TV”; switch while stopped and while playing.  
2. Align one non-zero offset; Confirm marks do not move.  
3. Save, quit, reopen.  
4. **Success:** Correct bed; offset persisted; Song Time cues stable.

#### S5 — MA export

1. Intentionally break one `ma_export_name` (Chinese / empty) → Export blocked.  
2. Fix → Continue past warnings (empty seq / excluded song) if acceptable.  
3. Import MA2 and/or MA3; run install macro/plugin once.  
4. **Success:** Console sequences/executors/TC match Show Patch intent; no Chinese in labels.

#### S6 — Error recovery

1. Trigger Preflight errors and warnings; use double-click navigation.  
2. Cancel export mid-dialog; change settings; export again (fresh report).  
3. **Success:** No stuck modal; no partial XML from blocked export; second run reflects fixes.

#### S7 — Missing media

1. Rename/move media directory; open project; Relink File/Folder.  
2. Optional: Collect Bundle / Save As on second machine.  
3. **Success:** Paths heal; playback and export work; variants still resolve.

#### S8 — Undo/Redo

1. Align Apply → Undo → Redo.  
2. Delete/move marks → Undo.  
3. Reorder setlist → Undo.  
4. **Success:** Timeline, monitor, and disk-dirty state stay consistent; no orphan preview offset.

#### S9 — Performance

1. Hold scrub / zoom on dense waveform; rapid song switch.  
2. Time Preflight + Export on large show (wall clock, subjective).  
3. **Success:** Transport remains usable; no crash; note any hitch > ~200 ms as friction.

---

## 3. Risk assessment

### High-risk workflows

| Workflow | Why high risk | Soak focus |
|----------|---------------|------------|
| Non-zero Align + export | Wrong mental model (marks vs mix) → console early/late | S4 + S5 with known TC points |
| MA Preflight hard block | Operator blocked mid-rehearsal; may demand force-export | S5 / S6 — document workarounds |
| Large-show song switch | Stutter / waveform rebuild | S3 / S9 |
| Missing media + variants | Wrong bed after relink | S7 |
| Preview not ended | Ghost offset / wrong hear | Align Cancel / song-switch cases |
| Unicode / Display vs MA name | Chinese leaking to XML or empty MA names | S1 / S5 Preflight |

### Expected operator actions (happy path)

1. Build or open show; select variant per song as needed.  
2. Align Anchors when a new mix arrives; Apply once trusted.  
3. Program marks in Song Time.  
4. Run Preflight (or rely on export gate); fix errors; accept warnings knowingly.  
5. Export → console import → spot-check a few Go+ and Top Buttons.

### Success criteria (soak exit)

| Criterion | Pass bar |
|-----------|----------|
| Clock integrity | No dual-clock symptoms; video locked to audio |
| Cue accuracy | Spot-check ≥5 cues/song against TC on console or offline |
| Variant safety | Switch mix does not move marks |
| Align safety | Cancel safe; Apply undoable; Preview never persists |
| Preflight | Errors always block; warnings never silently skipped without Continue |
| Export | MA2 and/or MA3 import without manual XML label surgery |
| Stability | No crash in S1–S9; blockers documented |
| Unicode | Chinese display names OK; MA labels ASCII-safe |

### Metrics to observe

| Metric | How to capture |
|--------|----------------|
| Time to first successful export | Stopwatch from open → console import |
| Preflight error/warning counts | Dialog summary per show |
| Song-switch hitch | Subjective / optional screen recording |
| Align iterations to “good enough” | Count Preview→Apply cycles |
| Relink success rate | Files healed / files still missing |
| Undo surprises | Count “I undid but UI wrong” events |
| Force-export demand | How often operators ask to bypass errors |
| Crash / hang count | Per session |

### Potential UX friction

| Friction | Symptom | Likely follow-up |
|----------|---------|------------------|
| Info-always dialog on export | Extra click every export | Pref: skip dialog when info-only |
| No force-export | Blocked with “I know what I’m doing” | Confirm-to-force (gated) |
| Variant CRUD thin | Hard to add/rename mixes | Variant management UI |
| Align discovery | Operators miss Tools → Align Anchors | Hint on variant switch |
| Modal Preflight | Can’t edit while reading list | Modeless / dock later |
| Large Preflight tables | Noise from info totals | Collapse information by default |
| Duration / missing chips | Unclear why song won’t play | Media status polish |

---

## 4. Recommended refinements (no implementation in this task)

Prioritize only after soak evidence. Suggested buckets:

| Bucket | Refinement | Depends on soak signal |
|--------|------------|------------------------|
| **P0 fix** | Any crash, stuck Preview, marks moving, Chinese in XML | Fail checklist F |
| **P0 fix** | Export gate false positives (blocks safe shows) | S5 false-block rate |
| **P1 UX** | Info-only export dialog skip / collapse | “Too many clicks” |
| **P1 UX** | Force-export with typed confirm | Rehearsal urgency |
| **P1 product** | Variant add/rename/select chrome | Mix management pain |
| **P2 rules** | Deeper Preflight (cue-level names, pool ranges, TC mode) | Missed console rejects |
| **P2 polish** | Align entry points / duration chips / relink clarity | Confusion notes |
| **Defer** | Overlay compare, NDI, OSC, auto-fix | Not soak blockers |

---

## 5. Priority recommendations for Sprint 7 Feature Planning

Use soak outcomes to pick **one** Feature Sprint theme. Suggested order of consideration:

| Rank | Candidate | Choose when soak shows… |
|------|-----------|-------------------------|
| **1** | **Stability / Preflight UX pack** (info-only skip, optional force-export, false-positive fixes) | Export friction dominates; few Variant/Align bugs |
| **2** | **Variant CRUD / picker UI** | Daily mix management is the #1 complaint; Align/Preflight OK |
| **3** | **Deeper MA validation rules** | Console still rejects after green Preflight |
| **4** | **Align / media polish** (discovery, duration, relink) | Programming OK; setup awkward |
| **5** | **Reference overlay / A-B** | Only after Variants + Align trusted on desk |

**Planning rule:** Do not start Feature Sprint 7 until checklist **F** is Pass or Pass-with-notes and P0 blockers are filed or fixed.

**Explicit non-goals until soak passes:** auto-fix, exporter redesign, EventBus-as-feature, large UI redesign.

---

## Soak run log template

```text
Show: ____________________  Date: __________  Operator: __________
Build SHA: ________________  Machine: laptop / desktop
Audio device: ______________

Checklist F verdict: Pass / Pass with notes / Fail
P0 blockers: ________________________________________________
Top friction: ________________________________________________
Force-export requested? Y/N   Info-dialog annoyance? Y/N
Recommended Sprint 7 theme (1–5): ____
```

---

## READY FOR REAL-WORLD VALIDATION

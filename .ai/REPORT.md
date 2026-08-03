# Latest AI task report

**Date:** 2026-08-03  
**Branch:** `cursor/sprint2-settings-service-028d`  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Sprint 2 · Task 7 — **Settings Service Foundation**: introduce
`application/settings_service.py` for machine-level preferences only,
preserving QSettings schema and separating Machine State from Project State.

## What was implemented

- `SettingsService`: QSettings owner; audio via existing `audio_prefs`; window/UI
  chrome keys; autosave/recent raw APIs; fixed `theme_id()` = `pitch_black`.
- MainWindow constructs `SettingsService(QSettings(...))`; `_settings` aliases
  the service (tests keep working); audio apply/save go through the service.
- ProjectService receives SettingsService as its SettingsStore.
- Design contracts documented in module + `docs/current_architecture.md`.

## Remaining MainWindow QSettings usages

- Still constructs `QSettings` once to inject into `SettingsService` (test patch
  compatibility: `patch(...main_window.QSettings)`).
- Still calls `self._settings` / `self.settings` value/setValue for UI session
  (now the SettingsService façade, not a raw orphaned QSettings).

## Remaining machine settings outside SettingsService

- `web_remote/prefs.py`
- `ui/color_presets.py`
- `ui/export_dialog.py` (MA export dirs / last console)
- Sync-calib / Remote mute paths unrelated to settings store

## Remaining technical debt

- ProjectService still duplicates autosave/recent orchestration on same keys
- MainWindow still has many chrome setValue call sites (routed, not extracted helpers)
- No persisted theme switch (theme is code-fixed)
- Project JSON still mirrors some chrome flags onto songs

## Risks

- Dual APIs (SettingsService + ProjectService) for autosave/recent keys
- Injected QSettings vs audio_prefs internal QSettings (same org/app; tests
  isolate audio_prefs separately)

## Tests

- Targeted settings + session/autosave: **14 passed**
- Full suite: **905 passed**, **16 failed** (same pre-existing / Linux env set)

## Suggested next task

Sprint 2 Task 8 — Event Bus foundation (READY FOR EVENT BUS FOUNDATION).

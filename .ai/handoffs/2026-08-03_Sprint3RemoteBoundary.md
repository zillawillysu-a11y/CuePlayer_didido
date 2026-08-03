# Handoff — Sprint 3 Task 2: Remote Boundary Foundation

**Date:** 2026-08-03  
**Branch:** `cursor/sprint3-remote-boundary-028d`  
**Base:** `cursor/sprint3-show-host-protocol-028d`

## Done

- Explicit `RemoteHost` / `RemoteEnginePort` in `ports/remote_host.py`
- `MainWindowRemoteHost` adapter confines MainWindow/engine private access
- `WebRemoteBridge(host: RemoteHost)` — no `host._*` / `engine._*` / widget duck-typing
- MainWindow construction site uses the adapter
- Architecture + CHANGELOG updated; boundary tests added

## Not done (intentionally)

- EventBus
- Networking redesign
- Routing remote ops exclusively through PlaybackService
- Lifting adapter `_` helpers to public MainWindow façades

## Next

Sprint 3 Task 3 — Event Bus foundation.

## Suite

Full: **919 passed**, **16 failed** (pre-existing Linux/env; unchanged failure set).

## Marker

READY FOR EVENT BUS FOUNDATION

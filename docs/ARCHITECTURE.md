# CuePlayer Architecture

Current intended layer diagram (aspirational). For a full as-built review and the
incremental target layout, see:

- [`ARCHITECTURE_REVIEW.md`](ARCHITECTURE_REVIEW.md) — as-built review
- [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md) — strangler / one-module-at-a-time plan
- [`BOUNDARY_RULES.md`](BOUNDARY_RULES.md) — **permanent** allowed/forbidden dependencies
- [`MIGRATION_RULES.md`](MIGRATION_RULES.md) — **permanent** how to move one module safely

AI agents: follow [`.ai/WORKFLOW.md`](../.ai/WORKFLOW.md) end-to-end (plan → implement → [`.ai/REPORT.md`](../.ai/REPORT.md) + handoff → stop). Active task: [`.ai/NEXT_TASK.md`](../.ai/NEXT_TASK.md). Read boundary + migration rules before any architecture move.

## Layers

```text
UI (PySide6)
  └── Domain model (Project / Song / Tracks / Marks / Export profile)
        ├── Persistence (UTF-8 JSON + schema migrations)
        ├── Playback Engine (audio sample clock)
        ├── Media (decode, waveform cache, video frames)
        ├── Routing (source channel → device output channel)
        ├── LTC (striped or generated/cached)
        └── Exporters (ma2 / ma3, versioned)
```

## Data model (MVP)

```text
Project / Setlist
└── Song
    ├── Timebase (start TC, FPS, duration)
    ├── Audio Tracks[] (Main / Reference)
    ├── Generated or Striped LTC
    ├── Video Clips[]
    ├── Mark Lanes 1–9
    └── MA Export Profile
```

## Persistence rules

- Store projects as UTF-8 JSON (not ASCII-escaped-only).
- Include `schema_version` from v1.
- Prefer `pathlib.Path`; treat Chinese paths as required test cases.
- Auto backup / migration hooks exist from the first schema.

## Playback rules

- Audio sample position is the master clock.
- Video preview and clean output share one decoded frame path.
- Native NDI is optional and must reuse the same frame path.

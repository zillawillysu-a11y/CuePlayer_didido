# Sprint 8 — Video PASS; Audio contiguous-keys eviction hole (A)

**Tip under test:** `7cb1bf1fd815e125f23ef8db5b7ee730526af58f`  
**Follow-up tip:** (see latest commit on this branch)  
**PR:** #240 — do not merge #239/#240; Audio P0 still open until Windows re-validates  
**Video:** PASS — frozen (Mark-jump path not modified)

## Decision tree

**A applies:** `publish_late` 6→7, `steady_gap_fill_delta=16384`, `steady_gap_fill_samples=16384`.

Not B-only: coverage was still missing at seams. Boundary deltas also exist
(secondary), but late publish + gap_fill explain the cable-unplug clicks.

## Totals (manual-dump @ 2026-08-06T13:54:30Z)

| Field | Value |
|---|---|
| steady_gap_fill_delta | 16384 (~0.34 s) |
| steady_gap_fill_samples | 16384 |
| cold_seek_gap_fill_delta | 14336 |
| gap_fill | 30720 |
| publish_late | 6 (7 after ui-profile) |
| publish_lead_seconds (last) | 35.90 (healthy tail) |
| publish_lead_ms | n=48 mean≈23119 max≈35925 |
| contiguous_ahead_seconds | 46.29 (end-of-report; masks earlier holes) |
| owner_switch | 26 |
| callback deadline_miss | 0 |
| callback exec mean/max | 0.265 ms / 32.5 ms |
| PortAudio underflow/flags | 0 |

## Timestamp correlation

User MM:SS treated as **song time**; media ≈ song + 600 s (from scrub traces).

| User | Song | Media≈ | Ring evidence |
|---|---|---|---|
| 18:42–19:54 | 1122–1194 | 1722–1794 | Aged out of 80-deep ring (report taken later) |
| 20:11 | 1211 | 1811 | `owner_switch` 1800→1809 + `boundary_delta` max_adj=0.273 @ media 1812 |

Later measured gap/late sequence (song ~1277 / 1352):

1. Seek → late publish **1899** lead=**-7.45 s**
2. Gap_fill @ media **1877** (~5×1024) → late publish **1872** lead=**-5.20 s** → switch 1800→1872
3. Gap_fill @ media **1951.8–1952.0** (~9×1024) → late publish **1944** lead=**-8.03 s** → switch 1872→1944 (jumped a hole)
4. `boundary_delta` @ 1956 (0.042) and 1983 (0.155)

`preserved_contiguous` listed holes **1845→1872 (27 s)** and **1917→1944 (27 s)** — 3×9 s grid.

## Root cause

`_contiguous_keys` treated any window with `start <= frontier` as contiguous.
Disjoint past islands polluted the protected set; eviction then dropped true
forward 9 s cells → holes → gap_fill → publish_late → audible drop.

## Fix (mixer only; Video untouched)

- Contiguous component = true interval-union merge (must overlap/touch the union)
- Eviction prefers disjoint / fully-behind; never drops pin-covering window
- Regression: keys exclude disjoint past; forward chain survives full cache

READY FOR WINDOWS VIDEO AUDIO CONTIGUOUS-KEYS / EVICTION HOLE VALIDATION

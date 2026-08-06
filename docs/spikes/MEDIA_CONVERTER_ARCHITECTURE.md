# CuePlayer Media Converter — Architecture Investigation

**Status:** Design / investigation only (no converter implementation)  
**Revised:** 2026-08-05 (final product-priority revision)  
**Branch:** `cursor/media-converter-architecture-d910`  
**PR:** [#235](https://github.com/zillawillysu-a11y/CuePlayer_didido/pull/235) (documentation-only)  
**Base inspected:** `master` (+ read-only review of Sprint 4–8 tip branches)  

**Hard constraints for this document and PR #235:**

- Do **not** implement the converter yet.
- Do **not** modify Sprint 8 playback, `VideoSyncController`, `AudioEngine`, Export UI, Song Time semantics, or existing project behavior.

**Sprint 8 reference (corrected):** Video Track Responsiveness is **PR [#232](https://github.com/zillawillysu-a11y/CuePlayer_didido/pull/232)** (`cursor/sprint8-video-responsive-028d`). PR #234 is a later Round 8 follow-up (`postland-starvation`), not the primary responsiveness PR.

---

## 0. Final product priorities (locked)

### 0.1 User goal

1. Audio with **no noticeable audible change**
2. **No** audio timing drift or synchronization error
3. A video proxy **meaningfully smaller** than the original
4. The **smoothest possible** CuePlayer performance experience
5. A **simple one-click** workflow

### 0.2 Priority order (optimization rule)

Meet Windows playback, seek, scrub, and UI responsiveness targets **first**. Then minimize proxy video size **within** those performance requirements.

| Rank | Priority |
|------|----------|
| 1 | Timeline drag and scrub responsiveness |
| 2 | Playhead and Qt UI smoothness |
| 3 | Stable video presentation |
| 4 | Exact Song Time synchronization |
| 5 | No noticeable audio change |
| 6 | Reduce proxy video size as much as possible after performance targets are satisfied |
| 7 | Fast song switching and waveform display |

### 0.3 User-facing workflow (locked direction)

```text
Drop audio and video → Convert → CuePlayer Optimized
```

- Default user-facing preset name: **CuePlayer Optimized**
- Normal users must **not** need to understand WAV, codec, GOP, CRF, CFR, keyframes, bit depth, or encoder selection.
- Advanced technical settings are optional / hidden; not required for normal use.

Internally, **CuePlayer Optimized** maps to a Windows-benchmarked short-GOP H.264 profile (§5). All-Intra is a **diagnostic / fallback** candidate only — not the default unless short-GOP fails responsiveness targets.

---

## 1. Repository findings (exact files / classes)

### 1.1 Layers (as-built on `master`)

```text
UI (PySide6) → Domain → Persistence / Playback Engine / Media / Routing / Exporters
```

Docs: `docs/ARCHITECTURE.md`, `docs/PRODUCT_SPEC.md`, `AGENTS.md`.  
PRODUCT_SPEC already notes preview-proxy strategy as **undecided** (§7 Media).

### 1.2 Audio loading path

| Piece | Location | Behavior |
|-------|----------|----------|
| Load entry | `cueplayer.ui.main_window.MainWindow._load_audio_path` | `load_audio(path)` → sets `Song.duration_seconds`, replaces/keeps `AudioTrack`, `AudioEngine.set_buffer`, `TimelineWidget.set_audio` |
| Decode | `cueplayer.media.audio_loader.load_audio` | `soundfile.read(..., dtype="float32")` → in-memory `AudioBuffer` + peak pyramid |
| Peaks | `build_peak_pyramid` / `PeakLevel` / `choose_peak_level` | Signed min/max pyramid (~1 ms finest); display mono is peak-normalized; **playback samples stay raw** |
| Engine | `cueplayer.playback.audio_engine.AudioEngine` | One `AudioBuffer`; sample position is master clock; `sync_offset_seconds` for monitoring calibration only |
| Device rate | `cueplayer.playback.devices.resolve_output_samplerate` | Prefer media rate; fall back through device default / 48k / 44.1k / … when WASAPI rejects |
| Playback resample | `cueplayer.playback.resample.resample_linear` + `AudioEngine._playback_source` | Resamples **at open-stream time** if device rate ≠ media rate — **not** a reason to bake 48 kHz into proxies |
| Tests | `tests/media/test_audio_loader.py`, Chinese fixture under `fixtures/media/中文測試/` | Unicode path coverage |

**Implication for converter:** Proxy PCM should preserve source rate, channel count/layout/order, and decoded sample timing so Song Time mapping stays identity (aside from explicitly recorded trims/offsets). Device resampling remains a **runtime** concern, identical for original or proxy.

### 1.3 Video loading / seek / scrub / presentation

| Piece | Location | Behavior |
|-------|----------|----------|
| Probe / decode | `cueplayer.media.video_loader` — `VideoInfo`, `VideoDecoder`, `StillImageDecoder`, `open_media_decoder` | PyAV (`av`); `frame_at(seconds)` seek-on-backward/large-forward (`_MAX_FORWARD_SKIP_SECONDS = 2.0`); RGB24 ndarray |
| Clock sync | `cueplayer.playback.video_sync.VideoSyncController` | Fed by `AudioEngine.position_changed`; **no independent video clock**; Preview + Clean Output share one frame path |
| Quality cap | `VideoDecodeQuality` in `domain.models` + `set_decode_quality` | Decode-time height cap (full/1080/720/540) — temporary runtime tradeoff, not a media package |
| Clip model | `domain.models.VideoClip` | Timeline placement + `source_in` / duration / loop via `source_time_for` |
| Embedded audio | `media.video_audio_loader.load_video_audio`, `video_audio_cache`, `playback.video_audio_mixer.VideoAudioMixer` | Whole-clip PCM decode once; mixed on sample clock; video proxies should omit unnecessary audio when main bed is separate |

**Sprint 8 (PR #232):** async latest-wins decode worker, `ScrubFrameCache`, `av_path_lock`, play/scrub pipeline states, perf audit in `docs/playback_performance_audit.md` (on that tip). **Converter design must not replace or conflict with this runtime pipeline** — proxies should make PyAV seek cheaper so Sprint 8 work stays valid.

### 1.4 Waveform generation / cache (today)

| Layer | Master | Sprint 8 tip (ahead of master) |
|-------|--------|--------------------------------|
| Music peaks | Built in RAM at every `load_audio` | + `media.audio_disk_cache` — `~/.cache/cueplayer/audio/*.peaks.npz` + optional full `.npz`, keyed by `(resolved path, mtime_ns, size)` |
| Video-clip lane | `media.video_clip_waveform.VideoClipWaveformCache` (ThreadPoolExecutor) | Same idea + heavier play-time deferral |
| Invalidation | N/A on master (rebuild each load) | Path + mtime (+ size); adopt/clone helpers when Media/ relocates |

**Gap:** No project-local, generation-published, converter-produced peak package yet.

### 1.5 Song Time / variants / anchors

**On `master`:** Song timeline is implicit song seconds; `AudioTrack.offset_seconds` exists but product paths are largely **single main bed**. Marks store `Mark.time_seconds` on the song.

**On Sprint 4–5 tips:**

| Concept | Module / doc | Rule |
|---------|--------------|------|
| Song Variant | `domain.song_variant.SongVariant` | Switchable media package; marks stay on Song |
| Song Time ↔ Variant Time | `domain.anchor_mapping` | `variant_time = song_time - anchor_offset`; `song_time = variant_time + anchor_offset` |

**Converter rule:** Proxies attach to a media package. Marks, LTC, loops, remote control continue to use **Song Time**. Codec priming / proxy trim / media start offsets are **separate** fields — **never** compensated by moving marks or changing Song Time.

### 1.6 Persistence / output location context

| Item | Location |
|------|----------|
| Project JSON | `persistence.project_store` — UTF-8 JSON, `SCHEMA_VERSION = 1` on master |
| Paths | `AudioTrack.path`, `VideoClip.path`; Chinese paths required |
| Media folder layout (Sprint tip) | `persistence.media_layout` — `Media/<Setlist>/<Song>/` under project root |

Original-media directories are **not** assumed writable (read-only media, external drives, network paths). See §3.2 for output location priority.

### 1.7 PyAV / FFmpeg dependencies today

| Dependency | Role |
|------------|------|
| `av>=13` (`pyproject.toml`) | Video probe/decode + embedded audio extract |
| `soundfile` + libsndfile | Primary music load |
| System / CLI `ffmpeg` | **Not** required by CuePlayer today |
| Packaging (Sprint tip) | Windows zip/Setup via PyInstaller; Qt + PyAV/FFmpeg libs |

### 1.8 Qt threading patterns already in use

- `QTimer` engine poll (~16 ms) on UI thread  
- `ThreadPoolExecutor` for video-clip waveforms; Sprint 8 adds audio load workers, scrub cache worker, async video decode, and `ports.media_jobs.MediaJobQueue`  

**Converter must** run outside the Qt UI thread (worker / subprocess).

---

## 2. Recommended converter architecture

### 2.1 Product form (first version)

**Recommendation: separate companion executable that shares CuePlayer library modules** (`CuePlayer Media Converter`).

| Option | Verdict |
|--------|---------|
| A. Companion app (shared `cueplayer.converter`) | **Choose for v1** |
| B. In-app Tools dialog | Later (v1.1+) |
| C. Totally separate repo | Reject |

```text
cueplayer                 → existing app
cueplayer-media-converter → thin UI + converter engine
```

User sees: **Drop → Convert → CuePlayer Optimized**. Technical presets stay internal.

### 2.2 Module split (future; MC-1 is a tiny subset)

```text
cueplayer/converter/
  __init__.py
  models.py         # MC-1: schema models, rational rate, sample timing
  manifest.py       # MC-1: Unicode JSON read/write + validation
  package.py        # MC-1: generations, publish, cleanup
  errors.py         # MC-1: typed failures
  probe.py          # later
  audio_proxy.py    # later
  video_proxy.py    # later
  peaks.py          # later
  jobs.py           # later
  ffmpeg_locate.py  # later
```

Custom seek-index modules are **deferred** until benchmarks prove PyAV/Sprint 8 can use them beneficially — **not** in MC-1.

### 2.3 Runtime vs convert-time

| Concern | Convert-time | Playback-time |
|---------|--------------|---------------|
| Originals | Read-only | Relink / missing media |
| Audio proxy | PCM WAV/RF64 per §4 | Load proxy when package valid |
| Video proxy | CuePlayer Optimized (short-GOP first) | Existing decoder + Sprint 8 pipeline |
| Peaks | Later PR | Instant paint |
| Song Time | Record relationships only | Unchanged |
| Device rate | Preserve source in proxy | Runtime resample if needed |

---

## 3. Package directory, output location, Windows-safe publishing

### 3.1 Generation-based layout (locked)

```text
cueplayer_media/
  manifest.json                 # ONLY exists when package is fully valid/ready
  manifest.partial.json         # in-progress job state (never consumed by CuePlayer)
  manifest.failed.json          # optional diagnostics (never consumed)
  generations/
    <package-id>/
      audio/
        main.proxy.wav          # or .wav with RF64 as needed
      video/
        vj.proxy.mp4
      peaks/                    # later; not MC-1
        main.peaks.npz
      logs/
        convert.log
        ffmpeg_audio.stderr.txt
        ffmpeg_video.stderr.txt
```

- `<package-id>` is a new immutable generation id per conversion attempt.  
- Artifact paths inside the final manifest are **relative** to `cueplayer_media/` (or to the generation root — schema must pick one; recommend relative to `cueplayer_media/` including `generations/<id>/…`).  
- Do **not** overwrite a generation currently referenced by the published `manifest.json` while CuePlayer may be reading it.  
- On failure/cancel: discard the new generation; **keep** the previous valid generation + its `manifest.json`.  
- Clean old unused generations only when no longer active (policy details deferred).  
- A crash must never leave a package that **appears** valid: absence of final `manifest.json`, or a stale pointer, means “use originals”.

### 3.2 Output location priority (locked)

Do **not** assume the original-media directory is writable.

1. **CuePlayer project Media directory** (preferred when a project context exists)  
2. **User-selected output location**  
3. **Original-file sidecar** (`<original_dir>/cueplayer_media/`) **only when writable**

Must account for: read-only media, external drives, network paths, Chinese filenames/directories, Windows long paths (`\\?\` / pathlib-safe handling).

### 3.3 Manifest lifecycle (locked)

| File | Role |
|------|------|
| `manifest.partial.json` | In-progress job: package-id, paths, progress, tool versions |
| `manifest.failed.json` | Optional post-failure diagnostics |
| `manifest.json` | **Exists only after complete validation**; represents a ready package |

**Corrections vs earlier draft:**

- Final `manifest.json` does **not** carry `status=pending/running/failed/cancelled`.  
- Presence of valid `manifest.json` + resolvable relative artifacts + matching fingerprints **is** the ready signal.  
- CuePlayer must **never** consume partial, failed, or cancelled output.

### 3.4 Publish sequence

1. Create new immutable `generations/<package-id>/`.  
2. Write all outputs into that generation (future encode PRs).  
3. Validate every required artifact.  
4. Atomically publish the small final `manifest.json` (write temp + replace) pointing at the new generation.  
5. Remove `manifest.partial.json`.  
6. On cancel/fail: delete the new generation (best-effort), write optional `manifest.failed.json`, leave previous `manifest.json` intact if any.  
7. Never modify original media files.

---

## 4. Audio proxy requirements (locked)

The audio proxy is a **disposable CuePlayer working file/cache**, not a new master.

### 4.1 Meaning of “no audio change”

- No **noticeable audible** change vs normal playback of the source.  
- No timing / channel-order / layout change.  
- Bit-identical preservation of compressed MP3/AAC bitstreams is **not** required.

### 4.2 Rules

| Topic | Rule |
|-------|------|
| Originals | Untouched |
| Processing | Forbidden: normalize, gain, limiter, fades, EQ, denoise, remix, duplicate, swap |
| Re-encode | No lossy re-encode; PCM WAV only |
| Sample rate | Preserve source rate unless runtime device playback requires resampling |
| Bit depth | 16-bit PCM for MP3/AAC/normal 16-bit sources; preserve 24-bit **only** when source is genuine 24-bit PCM |
| Channels | Preserve **count, layout, and order explicitly**; do **not** use bare `-ac N` as “preservation” (FFmpeg may remix) |
| Large files | Use RF64 automatically when WAV would exceed RIFF 4 GB (`-rf64 auto`) |
| Drift | Must not create cumulative drift vs Song Time, marks, LTC, video, waveforms, loops, remote |
| Future validation | Explicit `L=LTC, R=Music` fixture proving no swap/remix/duplication |

### 4.3 Authoritative timing: integer samples (locked)

**Do not** use floating-point seconds as the authoritative audio timing representation.

Authoritative fields:

| Field | Meaning |
|-------|---------|
| `sample_rate` | Hz (integer) |
| `source_start_sample` | Source-domain sample index that corresponds to `proxy_start_sample` (first retained source sample) |
| `proxy_start_sample` | Proxy-file sample index paired with `source_start_sample` (normally `0`) |
| `leading_trim_samples` | Descriptive/validation metadata: how many leading decoded source samples were removed during conversion. In the normal trimmed case `source_start_sample == leading_trim_samples`. **Not** subtracted again in the playback affine map |
| `trailing_trim_samples` | Descriptive/validation metadata for how many trailing samples were removed; affects valid range / end checks, **not** the affine start-position formula |
| `decoded_sample_count` | Samples present in the proxy PCM (frame count per channel layout) |

Seconds may be **derived for display only**: `seconds = samples / sample_rate`.

### 4.4 Keep these concepts separate (locked)

| Concept | Owns | Must not be used for |
|---------|------|----------------------|
| **Song Time** | Marks, LTC timeline, loops, remote, UI playhead semantics | Encoder priming compensation |
| **Variant anchor offset** | Align Anchors / media shift vs song (`anchor_mapping`) | Codec delay |
| **Codec priming** | Encoder/decoder delay inherent to source codec | Moving marks |
| **Proxy trim** | `leading_trim_samples` / `trailing_trim_samples` applied while building proxy | Song Time edits |
| **Proxy media start offset** | Residual mapping if proxy sample 0 ≠ intended media origin after trim | Silent mark shifts |

**Never** compensate for codec priming by moving marks or changing Song Time.

### 4.5 Offset convention (exact)

Authoritative affine mapping in **integer samples** (same rate).  
`leading_trim_samples` is **not** part of this formula (it must not be subtracted a second time when `source_start_sample` already names the first retained source sample):

```text
source_sample = song_to_variant_sample(song_sample)   # via anchor_offset in samples at this rate
proxy_sample  = proxy_start_sample + (source_sample - source_start_sample)
```

**Definitions:**

- `source_start_sample` — source-domain sample corresponding to `proxy_start_sample`
- `proxy_start_sample` — normally `0`
- `leading_trim_samples` — how many leading decoded source samples were removed; normally equals `source_start_sample`; descriptive/validation only
- `trailing_trim_samples` — affects valid range / end validation only, not this start map

**Valid source range for a published proxy:**

```text
source_start_sample <= source_sample < source_start_sample + decoded_sample_count
```

**Examples:**

1. **Clean WAV identity**  
   `source_start_sample = 0`, `proxy_start_sample = 0`, `source_sample = 0`  
   → `proxy_sample = 0 + (0 - 0) = 0`

2. **AAC with 2112 leading samples removed**  
   `leading_trim_samples = 2112`, `source_start_sample = 2112`, `proxy_start_sample = 0`, `source_sample = 2112`  
   → `proxy_sample = 0 + (2112 - 2112) = 0`  
   Marks on Song Time unchanged.

3. **Later retained sample**  
   `source_start_sample = 2112`, `proxy_start_sample = 0`, `source_sample = 6912`  
   → `proxy_sample = 0 + (6912 - 2112) = 4800`

4. **Forbidden**  
   Subtracting priming from every mark’s Song Time, or using  
   `source_sample - leading_trim_samples + proxy_start_sample - source_start_sample`  
   (that double-subtracts when `source_start_sample == leading_trim_samples`).

If residual mapping cannot be expressed exactly with the integer fields above, conversion **fails validation** (do not publish `manifest.json`).

### 4.6 Channel preservation (encode guidance)

- Probe and store `channel_count`, `channel_layout` (e.g. `stereo`, `5.1`), and explicit order.  
- Prefer stream copy of decoded planar/interleaved PCM into WAV with matching channel count **without** `-ac` remix filters.  
- If a layout must be named for WAV/WAVEFORMATEX, choose a mapping that is **verified** not to swap L/R.  
- Validation: per-channel correlation / known LTC-left fixture (`L=LTC, R=Music`).

### 4.7 Illustrative FFmpeg audio pattern (not MC-1)

```bash
ffmpeg -hide_banner -y \
  -i "<original_audio>" \
  -map 0:a:0 \
  -vn \
  -c:a pcm_s16le \
  -ar <SOURCE_RATE> \
  -rf64 auto \
  "<generation>/audio/main.proxy.wav"
```

- Bit depth: `pcm_s16le` or `pcm_s24le` per §4.2.  
- **Avoid** `-ac <N>` unless tests prove it is a no-op for that layout.  
- Avoid loudnorm/volume/pan/aresample-as-remix. Any `aresample` usage must be justified and sample-count validated.  
- Final GOP/CRF/audio filter details remain subject to Windows validation in later PRs.

---

## 5. Video proxy requirements

### 5.1 Goals

- Meaningfully **smaller** than original.  
- Must **not** sacrifice timeline responsiveness to chase size.  
- Existing Sprint 8 async decode + scrub architecture remains intact.

### 5.2 Default internal profile for **CuePlayer Optimized** (benchmark candidate)

| Knob | Initial candidate |
|------|-------------------|
| Resolution | 720p |
| Codec | H.264 |
| GOP | Short GOP (exact length TBD by Windows benchmarks) |
| B-frames | None (`-bf 0`) |
| Frame rate | CFR; exact rational rates (§5.4) |
| Audio | No embedded audio when separate main audio is used (`-an`) |
| Rate control | Balanced CRF/bitrate (final values deferred) |

**Do not permanently choose All-Intra** unless Windows testing proves short-GOP cannot meet responsiveness targets. All-Intra may remain diagnostic/fallback.

### 5.3 Illustrative short-GOP command (candidate; finals deferred)

```bash
ffmpeg -hide_banner -y \
  -i "<original_video>" \
  -an \
  -map 0:v:0 \
  -vf "scale=-2:720:flags=bicubic,fps=<FPS_NUM>/<FPS_DEN>,format=yuv420p" \
  -c:v libx264 \
  -preset veryfast \
  -crf <TBD> \
  -profile:v high \
  -g <TBD_SHORT_GOP> \
  -keyint_min <TBD_SHORT_GOP> \
  -sc_threshold 0 \
  -bf 0 \
  -pix_fmt yuv420p \
  -movflags +faststart \
  "<generation>/video/vj.proxy.mp4"
```

All-Intra fallback (diagnostic only): `-g 1` / `keyint=1` — not default.

### 5.4 Exact frame-rate rules (locked)

**Do not** convert 29.97 → 30 or 59.94 → 60 merely because they are “close”.

Preserve exact standard rational rates, including:

| Rate | Fraction |
|------|----------|
| 23.976 | `24000/1001` |
| 24 | `24/1` |
| 25 | `25/1` |
| 29.97 | `30000/1001` |
| 30 | `30/1` |
| 50 | `50/1` |
| 59.94 | `60000/1001` |
| 60 | `60/1` |

Manifest stores `fps_num` + `fps_den` (integers). Decimal floats are display-only.

**Genuine VFR sources:** do not assume 30 FPS is always correct. Document a deterministic CFR policy in a later decision (deferred): e.g. prefer dominant mode rate if it matches a standard rational; else prefer song FPS if standard; else fail with explicit user choice in advanced UI. Validation must compare output frame count vs expected CFR duration within a defined tolerance and confirm constant `r_frame_rate`/`avg_frame_rate` equality on the proxy.

### 5.5 Windows performance validation (required before locking GOP/CRF)

Measure with the **Sprint 8 decoder** on Windows:

- Random seek p50 / p95  
- Scrub preview delivery rate  
- Pointer-follow responsiveness  
- First-frame latency  
- Resume-after-scrub behavior  
- CPU usage  
- Proxy file size  
- Stable presentation at 29.97, 30, 59.94, 60 FPS  
- Long-duration video ↔ Song Time alignment  

Do **not** assume lower bitrate alone improves scrubbing. GOP, keyframe placement, B-frames, CFR, decode cost, color conversion, and disk I/O all matter.

### 5.6 Seek index

**Defer** custom packet-position seek indexes until benchmarks prove benefit with current PyAV / Sprint 8 decoder. **Not in MC-1.**

### 5.7 Codec trade-offs (summary)

| Mode | Role |
|------|------|
| H.264 short-GOP, no B-frames | **Default CuePlayer Optimized candidate** — size + seek balance |
| H.264 All-Intra | Fallback / diagnostic if short-GOP fails scrub targets |
| MJPEG / ProRes / DNxHR | Deferred experiments; size or licensing cost usually wrong for show floor |

---

## 6. Manifest schema (v1 shape for MC-1+)

Final `manifest.json` example (ready package only — **no** lifecycle status field):

```json
{
  "schema": "cueplayer.media_package",
  "conversion_version": 1,
  "created_utc": "2026-08-05T12:00:00Z",
  "preset": "cueplayer_optimized",
  "package_id": "01JABC…",
  "generation_relpath": "generations/01JABC…",
  "tool": { "name": "cueplayer-media-converter", "version": "0.1.0" },

  "timing_model": {
    "audio_authoritative_unit": "samples",
    "video_authoritative_unit": "pts_ticks_plus_time_base"
  },

  "relationships": {
    "song_time_note": "Marks/LTC/loops/remote remain on Song Time",
    "variant_anchor_offset_samples": null,
    "concepts_separated": [
      "song_time",
      "variant_anchor_offset",
      "codec_priming",
      "proxy_trim",
      "proxy_media_start_offset"
    ]
  },

  "originals": {
    "audio": {
      "path": "原版.wav",
      "size_bytes": 123,
      "mtime_ns": 456,
      "codec": "pcm_s24le",
      "sample_rate": 48000,
      "channel_count": 2,
      "channel_layout": "stereo",
      "channel_order": ["L", "R"],
      "bit_depth": 24,
      "decoded_sample_count": 12345678
    },
    "video": {
      "path": "show.mp4",
      "size_bytes": 1,
      "mtime_ns": 2,
      "codec": "h264",
      "width": 1920,
      "height": 1080,
      "fps_num": 30000,
      "fps_den": 1001,
      "time_base_num": 1,
      "time_base_den": 30000,
      "is_cfr": false,
      "decoded_frame_count": 7716
    }
  },

  "proxies": {
    "audio": {
      "path": "generations/01JABC…/audio/main.proxy.wav",
      "codec": "pcm_s16le",
      "sample_rate": 48000,
      "channel_count": 2,
      "channel_layout": "stereo",
      "channel_order": ["L", "R"],
      "bit_depth": 16,
      "rf64": false,
      "source_start_sample": 0,
      "proxy_start_sample": 0,
      "leading_trim_samples": 0,
      "trailing_trim_samples": 0,
      "decoded_sample_count": 12345678
    },
    "video": {
      "path": "generations/01JABC…/video/vj.proxy.mp4",
      "codec": "h264",
      "width": 1280,
      "height": 720,
      "fps_num": 30000,
      "fps_den": 1001,
      "gop": null,
      "audio_streams": 0
    }
  },

  "fingerprints": {
    "strategy": "path+mtime_ns+size",
    "content_hash_optional": true
  }
}
```

`manifest.partial.json` may include job progress fields; it is never a CuePlayer playback input.

---

## 7. Windows FFmpeg packaging (deferred finals)

Discovery order (when encode PRs land):

1. Bundled converter `ffmpeg.exe`  
2. `CUEPLAYER_FFMPEG`  
3. `PATH` (dev only)

Licensing choice (**deferred**): LGPL shared build vs GPL libx264 companion binary vs OpenH264/MF. Do not silently enlarge CuePlayer’s playback dependency set; keep encode tooling with the converter.

PyAV remains the in-process decode/validation path; CLI FFmpeg is for cancelable long encodes.

---

## 8. UI workflow (companion)

1. Drop audio and/or video (Unicode OK).  
2. Quiet auto-probe (technical details hidden).  
3. Default preset label: **CuePlayer Optimized**.  
4. Choose output via §3.2 priority (do not require sidecar-on-original).  
5. One **Convert** button.  
6. Progress + Cancel.  
7. Success → ready package (`manifest.json` published).  
8. Failure/cancel → previous ready package preserved if any; new generation discarded.

---

## 9. Failure / cancellation / crash

| Event | Behavior |
|-------|----------|
| Start | Write `manifest.partial.json`; create new `generations/<id>/` |
| Success | Validate → atomic write `manifest.json` → delete partial |
| Cancel / fail | Discard new generation; optional `manifest.failed.json`; **keep** previous `manifest.json` |
| Crash | Missing/incomplete final manifest ⇒ CuePlayer uses originals; orphan generation eligible for cleanup |

Invariant: only a fully validated `manifest.json` makes a package appear valid.

---

## 10. Test strategy

| Layer | Focus |
|-------|-------|
| MC-1 | Manifest/package lifecycle, Unicode paths, generation publish/cancel/crash, no original mutation |
| Audio (later) | Integer sample timing; channel order; `L=LTC,R=Music`; RF64; MP3/AAC priming trims |
| Video (later) | Exact rational FPS; CFR validation; Windows seek/scrub benches vs Sprint 8 decoder |
| Compat | Projects without packages unchanged; Song Time untouched |

---

## 11. Migration / backward compatibility

1. No package / invalid package → originals (today’s behavior).  
2. Valid `manifest.json` + matching fingerprints → prefer proxies.  
3. Original changed → ignore package; offer reconvert.  
4. Sprint 8 pipeline stays; proxies reduce decode cost rather than replacing async/scrub design.  
5. Do not overload `anchor_offset` with codec priming — use proxy trim / sample fields.

---

## 12. Implementation plan

| PR | Scope |
|----|-------|
| **MC-0** | This architecture document (PR #235) |
| **MC-1** | Manifest + package generation skeleton only (§12.1) — **not started in this PR** |
| **MC-2** | Audio proxy encode + sample/channel validation (+ RF64, LTC L/R fixture) |
| **MC-3** | Peak writer into `peaks/` |
| **MC-4** | Video CuePlayer Optimized short-GOP + Windows bench harness |
| **MC-5** | All-Intra fallback path + compare benches |
| **MC-6** | FFmpeg bundle/license docs for converter |
| **MC-7** | Companion UI: Drop → Convert → CuePlayer Optimized |
| **MC-8** | CuePlayer resolver — **after** Sprint 8 PR #232 lineage lands |
| **MC-9+** | Optional thumbs; seek index only if benches prove value |

### 12.1 MC-1 file and test plan (approved scope; do not implement yet)

**Files:**

```text
src/cueplayer/converter/
  __init__.py
  models.py
  manifest.py
  package.py
  errors.py

tests/converter/
  test_manifest.py
  test_package.py
  test_sample_mapping.py   # mandatory §4.5 affine map cases
```

**MC-1 may implement only:**

- Manifest v1 models/schema  
- Exact rational frame-rate model (`fps_num`/`fps_den`)  
- Integer sample / PTS timing model fields  
- Pure helper for §4.5: `proxy_sample = proxy_start_sample + (source_sample - source_start_sample)` plus valid-range check (no FFmpeg)  
- Package ID  
- Generation directory layout  
- Relative artifact-path validation  
- Source fingerprint model  
- Unicode-safe manifest read/write  
- Staging generation creation  
- Successful publish (atomic final manifest)  
- Cancel/failure cleanup  
- Crash-recovery behavior (no false-valid package)  
- Preservation of previous valid generation  
- Protection against modifying original media  

**Mandatory MC-1 unit tests (`test_sample_mapping.py`):**

- Clean WAV identity → `proxy_sample == 0`  
- AAC leading trim (`leading_trim=2112`, `source_start=2112`, `source_sample=2112`) → `proxy_sample == 0`  
- Later retained sample (`source_sample=6912`) → `proxy_sample == 4800`  
- Valid range: `source_start <= source_sample < source_start + decoded_sample_count`  
- Assert mapping does **not** also subtract `leading_trim_samples`  

**MC-1 must not implement:**

- FFmpeg execution  
- Audio / video conversion  
- Companion UI  
- Playback resolver  
- Waveform peak generation  
- Custom seek index  
- Sprint 8 integration  
- Export UI changes  
- Song Time changes  

---

## 13. Decisions locked vs deferred

### 13.1 Locked now

- Product priority order (§0.2) and optimization rule  
- User workflow / default label **CuePlayer Optimized**  
- Audio: disposable PCM cache; no processing; preserve rate; bit-depth policy; explicit channel preservation (no casual `-ac`); RF64 auto; integer-sample authoritative timing with affine map `proxy_sample = proxy_start_sample + (source_sample - source_start_sample)`; `leading_trim_samples` descriptive only; concept separation  
- Video: short-GOP H.264 720p candidate as default; All-Intra not default without proof; exact rational FPS; no 29.97→30 “rounding”  
- Manifest lifecycle: partial / failed / final; final has no status enum  
- Generation-based Windows-safe publishing; keep previous valid generation  
- Output location priority (project Media → user-selected → writable sidecar)  
- Seek index deferred; not in MC-1  
- Sprint 8 primary reference = PR **#232**  
- PR #235 remains documentation-only; MC-1 not started here  
- Companion exe for v1; resolver only after Sprint 8  

### 13.2 Intentionally deferred

- Final FFmpeg redistribution / licensing choice  
- libx264 GPL companion vs LGPL-compatible encoder path  
- Final GOP and CRF values  
- Short-GOP vs All-Intra fallback threshold  
- VFR target-frame-rate selection policy  
- Float WAV and >24-bit source policy  
- Optional thumbnail cache  
- Final cleanup policy for old generations  
- Content-hash vs mtime+size as mandatory invalidation  
- Whether packages ever copy originals vs reference only  

---

## 14. Concise handoff block (for ChatGPT)

```text
HANDOFF — CuePlayer Media Converter Architecture (REVISED, docs only)
Date: 2026-08-05
Branch: cursor/media-converter-architecture-d910
PR: #235 (documentation-only — do not implement converter here)
Doc: docs/spikes/MEDIA_CONVERTER_ARCHITECTURE.md

Locked product order:
1) timeline drag/scrub  2) playhead/UI smoothness  3) stable video
4) exact Song Time sync  5) no noticeable audio change
6) minimize video proxy size after performance met  7) fast song switch/waveform

User flow: Drop → Convert → “CuePlayer Optimized” (hide codecs/GOP/CRF from normal UI)

Audio: disposable PCM WAV/RF64 cache; preserve sample rate; 16-bit for MP3/AAC/16-bit;
24-bit only if source is real 24-bit PCM; NO -ac remix; preserve channel count/layout/order;
authoritative map: proxy_sample = proxy_start_sample + (source_sample - source_start_sample);
leading_trim_samples is metadata only (do not double-subtract); never move marks for priming;
validate L=LTC,R=Music later.

Video: default candidate = 720p H.264 short-GOP, no B-frames, CFR, no embedded audio;
All-Intra = fallback only after Windows benches fail short-GOP;
preserve exact rationals (30000/1001 etc); never “round” 29.97→30.
Seek index deferred. Sprint 8 reference = PR #232.

Package: cueplayer_media/generations/<id>/ + atomic final manifest.json only when valid;
manifest.partial.json / manifest.failed.json never consumed; keep previous generation on fail.
Output: project Media → user folder → sidecar only if writable.

MC-1 (NOT started): converter/{models,manifest,package,errors}.py + tests only;
no ffmpeg/UI/resolver/peaks/seek-index/Sprint8/Export/SongTime changes.

Next: architecture re-review approval, then a separate branch for MC-1.
```

---

READY FOR FINAL MEDIA CONVERTER ARCHITECTURE APPROVAL

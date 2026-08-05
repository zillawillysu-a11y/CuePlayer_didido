# CuePlayer Media Converter — Architecture Investigation

**Status:** Design / investigation only (no converter implementation)  
**Date:** 2026-08-05  
**Branch:** `cursor/media-converter-architecture-d910`  
**Base inspected:** `master` (+ read-only review of Sprint 4–8 tip branches)  
**Constraint:** Do not modify Sprint 8 playback work; do not change Song Time semantics, Export UI, or current playback behavior in this investigation.

---

## 0. Audio proxy requirement (authoritative clarification)

The audio proxy is **not** a mastering / “better sounding” stage. Goal: **playback efficiency with no audible quality loss and no timing difference** vs the original decoded audio.

| Rule | Decision |
|------|----------|
| Sample rate | **Do not force 48 kHz.** Preserve source sample rate unless/until CuePlayer’s output device path must resample at **playback** time (already true today via WASAPI). |
| Container / codec | PCM WAV only — **no lossy re-encode**. |
| Bit depth | **16-bit PCM** for MP3, AAC, and genuine 16-bit PCM sources. **Preserve 24-bit only** when the source is real 24-bit PCM. |
| Channels | Preserve original channel layout / count. No remix. |
| Processing | **Forbidden:** normalization, gain, limiter, fades, denoise, EQ, channel remix. |
| Timing | Handle codec delay / encoder priming / padding / timestamp offsets correctly. |
| Validation | Compare **decoded sample count, duration, start, end** — not container duration alone. |
| Drift | Proxy must not introduce cumulative drift vs Song Time, marks, LTC, video, or waveforms. |
| Residual offset | If an unavoidable start offset remains, record it in the **manifest** and compensate deterministically at playback. |
| Originals | Never modify or overwrite original media. |

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

**Implication for converter:** Proxy WAV should match source rate/channels/decoded length so `load_audio` + Song Time stay identity-mapped. Device resampling remains a **runtime** concern, identical for original or proxy.

### 1.3 Video loading / seek / scrub / presentation

| Piece | Location | Behavior |
|-------|----------|----------|
| Probe / decode | `cueplayer.media.video_loader` — `VideoInfo`, `VideoDecoder`, `StillImageDecoder`, `open_media_decoder` | PyAV (`av`); `frame_at(seconds)` seek-on-backward/large-forward (`_MAX_FORWARD_SKIP_SECONDS = 2.0`); RGB24 ndarray |
| Clock sync | `cueplayer.playback.video_sync.VideoSyncController` | Fed by `AudioEngine.position_changed`; **no independent video clock**; Preview + Clean Output share one frame path |
| Quality cap | `VideoDecodeQuality` in `domain.models` + `set_decode_quality` | Decode-time height cap (full/1080/720/540) — temporary runtime tradeoff, not a media package |
| Clip model | `domain.models.VideoClip` | Timeline placement + `source_in` / duration / loop via `source_time_for` |
| Embedded audio | `media.video_audio_loader.load_video_audio`, `video_audio_cache`, `playback.video_audio_mixer.VideoAudioMixer` | Whole-clip PCM decode once; mixed on sample clock; video proxies should omit unnecessary audio when main bed is separate |

**Sprint 8 tip (`origin/cursor/sprint8-video-responsive-028d`, related PR #234):** async latest-wins decode worker, `ScrubFrameCache` (sparse ~10 fps / 360p posters), `av_path_lock`, play/scrub pipeline states, perf audit in `docs/playback_performance_audit.md`. **Converter design must not replace or conflict with this runtime pipeline** — proxies should make PyAV seek cheaper so Sprint 8 work stays valid.

### 1.4 Waveform generation / cache (today)

| Layer | Master | Sprint 8 tip (ahead of master) |
|-------|--------|--------------------------------|
| Music peaks | Built in RAM at every `load_audio` | + `media.audio_disk_cache` — `~/.cache/cueplayer/audio/*.peaks.npz` + optional full `.npz`, keyed by `(resolved path, mtime_ns, size)` |
| Video-clip lane | `media.video_clip_waveform.VideoClipWaveformCache` (ThreadPoolExecutor) | Same idea + heavier play-time deferral |
| Invalidation | N/A on master (rebuild each load) | Path + mtime (+ size); adopt/clone helpers when Media/ relocates |

**Gap:** No project-local, versioned, converter-produced peak package yet. Converter should emit a **deterministic peak cache** colocated with the media package (not only the global user cache).

### 1.5 Song Time / variants / anchors

**On `master`:** Song timeline is implicit song seconds; `AudioTrack.offset_seconds` exists but product paths are largely **single main bed** (`_load_audio_path` replace-only). Marks store `Mark.time_seconds` on the song.

**On Sprint 4–5 tips (not merged into this investigation’s `master` tip, but authoritative for future integration):**

| Concept | Module / doc | Rule |
|---------|--------------|------|
| Song Variant | `domain.song_variant.SongVariant` | Switchable media package; marks stay on Song |
| Song Time ↔ Variant Time | `domain.anchor_mapping` | `variant_time = song_time - anchor_offset`; `song_time = variant_time + anchor_offset` |
| Design | `docs/song_variant_design.md`, handoff `Sprint5SongTimeFacade` | PlaybackService / remote already pushed toward Song Time façade |

**Converter rule:** Proxies attach to a **media package / variant path**. Marks, LTC generation, loops, remote control continue to use **Song Time**. Any proxy priming offset is **extra media metadata**, applied when mapping Song Time → media read position — **never** by shifting marks.

### 1.6 Persistence / where metadata should live

| Item | Location |
|------|----------|
| Project JSON | `persistence.project_store` — UTF-8 JSON, `SCHEMA_VERSION = 1` on master |
| Paths | `AudioTrack.path`, `VideoClip.path` (absolute/relative); Chinese paths required |
| Media folder layout (Sprint tip) | `persistence.media_layout` — `Media/<Setlist>/<Song>/` under project root |
| Relink | Missing-media flows / heal helpers on advanced branches |

**Recommendation:** Converter outputs live in a **sidecar package directory** next to (or under) song media; project JSON gains optional `media_package` / proxy path fields via a future schema bump — originals remain the source of truth when no valid package exists.

### 1.7 PyAV / FFmpeg dependencies today

| Dependency | Role |
|------------|------|
| `av>=13` (`pyproject.toml`) | Video probe/decode + embedded audio extract (links against FFmpeg libs inside the wheel) |
| `soundfile` + libsndfile | Primary music load |
| System / CLI `ffmpeg` | **Not** required by CuePlayer today |
| Packaging (Sprint tip `docs/DISTRIBUTION.md`) | Windows zip/Setup via PyInstaller; build already ships Qt + PyAV/FFmpeg libs |

### 1.8 Qt threading patterns already in use

- `QTimer` engine poll (~16 ms) on UI thread  
- `ThreadPoolExecutor` for video-clip waveforms; Sprint 8 adds audio load workers, scrub cache worker, async video decode, and `ports.media_jobs.MediaJobQueue` as the future submission surface  

**Converter must** use a worker / subprocess outside the Qt UI thread (same discipline as Sprint 8 media jobs).

---

## 2. Recommended converter architecture

### 2.1 Product form (first version)

**Recommendation: separate companion executable that shares CuePlayer library modules** (`CuePlayer Media Converter`), not an in-app dialog and not a fully independent codebase.

| Option | Verdict |
|--------|---------|
| A. Separate companion app (own window, shared `cueplayer.media` / future `cueplayer.converter`) | **Choose for v1** — isolates long FFmpeg jobs from show playback; can ship beside CuePlayer.zip without touching Sprint 8 UI |
| B. Same process, Tools dialog | Later (v1.1+) once job queue + cancel UX prove stable |
| C. Totally separate repo / no shared modules | Reject — duplicates Unicode path, peak format, manifest schema |

Entry points:

```text
cueplayer                 → existing app
cueplayer-media-converter → thin PySide6 shell + converter engine
```

Both packaged on Windows; converter may also run headless (`--manifest` / CI).

### 2.2 Module split (future code — not implemented now)

```text
cueplayer/converter/
  probe.py          # ffprobe / PyAV / soundfile metadata + decoded timing
  audio_proxy.py    # PCM WAV encode rules (clarified in §0)
  video_proxy.py    # preset → ffmpeg argv
  peaks.py          # write peak pyramid compatible with AudioBuffer
  seek_index.py     # optional keyframe / thumbnail index
  manifest.py       # schema read/write + validation
  package.py        # atomic directory publish
  jobs.py           # cancel, progress, cleanup
  ffmpeg_locate.py  # bundled → env → PATH discovery
```

CuePlayer playback later gains a thin **resolver**: prefer valid proxy paths from manifest; else original path (backward compatible).

### 2.3 Runtime vs convert-time responsibilities

| Concern | Convert-time | Playback-time (unchanged semantics) |
|---------|--------------|-------------------------------------|
| Original files | Read-only | Relink / missing media |
| PCM proxy | Write deterministic WAV | `load_audio(proxy)` |
| Video proxy | CFR short-GOP / All-Intra | Existing `VideoDecoder` / Sprint 8 async+scrub cache |
| Peaks | Precompute package peaks | Instant paint; may still refresh if mtime changes |
| Song Time / marks | Record relationship + offsets only | Marks stay on Song Time |
| Device sample rate | Preserve source in proxy | `resolve_output_samplerate` + optional linear resample |

---

## 3. Recommended media package directory structure

Sidecar package (Unicode-safe paths; never overwrite originals):

```text
MySong_concert/
  original/                         # optional copies OR only path refs in manifest
    (not required — prefer external originals by absolute/relative path)
  cueplayer_media/                  # package root
    manifest.json                   # only valid when status=ready
    manifest.json.partial           # in-progress (never treated as ready)
    audio/
      main.proxy.wav                # PCM per §0
      main.peaks.npz                # peak pyramid (same arrays as disk-cache tip)
    video/
      vj.proxy.mp4                  # or .mov for ProRes experiments
      vj.seek.json                  # optional keyframe PTS list
      thumbs/                       # optional contact sheet / sparse JPG
        000000.jpg
    logs/
      convert.log
      ffmpeg_audio.stderr.txt
      ffmpeg_video.stderr.txt
    tmp/                            # deleted on success; wiped on cancel/fail
```

Project integration (later schema):

```text
ProjectDir/
  Media/<Setlist>/<Song>/
    原版.wav                        # original (untouched)
    show.mp4                        # original
    cueplayer_media/                # package beside originals
      manifest.json
      ...
```

Fingerprint fields in manifest point at **original** path + size + mtime_ns (+ optional content hash). Proxy filenames are stable for a given `(conversion_version, preset, source fingerprint)`.

---

## 4. Recommended manifest schema

`conversion_version`: start at `1`.  
`status`: `pending` | `running` | `ready` | `failed` | `cancelled` — CuePlayer only consumes **`ready`**.

```json
{
  "schema": "cueplayer.media_package",
  "conversion_version": 1,
  "status": "ready",
  "created_utc": "2026-08-05T12:00:00Z",
  "preset": "performance",
  "tool": { "name": "cueplayer-media-converter", "version": "0.1.0" },
  "ffmpeg": { "path": "...", "version": "...", "license": "LGPL|GPL", "configuration_excerpt": "..." },

  "song_time": {
    "note": "Marks/LTC/loops remain on Song Time; proxies are Variant/media time",
    "anchor_offset_seconds": 0.0,
    "proxy_audio_start_offset_seconds": 0.0,
    "proxy_video_start_offset_seconds": 0.0,
    "offset_reason": null
  },

  "originals": {
    "audio": {
      "path": "原版.wav",
      "path_resolved": "D:/Shows/.../原版.wav",
      "size_bytes": 123,
      "mtime_ns": 456,
      "sha256": null,
      "codec": "pcm_s24le",
      "sample_rate": 48000,
      "channels": 2,
      "bit_depth": 24,
      "decoded_frames": 12345678,
      "decoded_duration_seconds": 257.201625
    },
    "video": {
      "path": "show.mp4",
      "size_bytes": 1,
      "mtime_ns": 2,
      "codec": "h264",
      "width": 1920,
      "height": 1080,
      "avg_fps": 29.97,
      "time_base": "1/30000",
      "is_cfr": false,
      "decoded_frame_count": 7716,
      "decoded_duration_seconds": 257.2
    }
  },

  "proxies": {
    "audio": {
      "path": "audio/main.proxy.wav",
      "format": "wav",
      "codec": "pcm_s16le",
      "sample_rate": 48000,
      "channels": 2,
      "bit_depth": 16,
      "decoded_frames": 12345678,
      "decoded_duration_seconds": 257.201625,
      "validation": {
        "frames_match_source": true,
        "max_abs_sample_error": null,
        "start_pts_seconds": 0.0,
        "end_pts_seconds": 257.201625
      }
    },
    "video": {
      "path": "video/vj.proxy.mp4",
      "codec": "h264",
      "width": 1280,
      "height": 720,
      "fps": 30,
      "gop": 15,
      "pix_fmt": "yuv420p",
      "audio_streams": 0,
      "seek_index_path": "video/vj.seek.json"
    },
    "waveform_peaks": { "path": "audio/main.peaks.npz", "format": "cueplayer.peaks.v1" },
    "thumbnails": { "dir": "video/thumbs", "interval_seconds": 1.0 }
  },

  "invalidation": {
    "strategy": "path+mtime_ns+size",
    "content_hash_optional": true
  }
}
```

**Playback compensation (deterministic):**

```text
media_read_time = song_to_variant_time(song_time) - proxy_*_start_offset_seconds
```

If both offsets are 0 (expected for clean WAV/CFR proxies), behavior matches originals.

---

## 5. Exact FFmpeg settings proposed per preset

Paths must be passed carefully for Chinese Windows paths (prefer subprocess list argv; avoid shell; UTF-8 / long-path aware).

### 5.1 Audio proxy (both presets — identical rules)

Bit-depth selection (probe with ffprobe / soundfile / PyAV):

| Source | Output |
|--------|--------|
| PCM 24-bit (or higher intentional PCM) | `pcm_s24le` WAV |
| PCM 16-bit | `pcm_s16le` WAV |
| MP3 / AAC / other lossy | `pcm_s16le` WAV (decode once; no second lossy encode) |
| Float WAV | Prefer `pcm_s24le` only if source bits warrant; else document as unresolved — default **do not up-invent 24-bit**; store float→PCM policy in conversion_version notes |

**Canonical decode → WAV (timing-safe pattern):**

```bash
ffmpeg -hide_banner -y \
  -i "<original_audio>" \
  -map 0:a:0 \
  -vn \
  -af "aresample=async=0:first_pts=0" \
  -c:a pcm_s16le \
  -ar <SOURCE_RATE> \
  -ac <SOURCE_CHANNELS> \
  -f wav \
  "<tmp>/main.proxy.wav"
```

Notes:

- `-ar` / `-ac` set to **probed source** values (never hardcode 48000).  
- For true 24-bit PCM sources use `-c:a pcm_s24le`.  
- Prefer **decoded frame-count validation** after write (PyAV or soundfile).  
- If priming/padding cannot be stripped to exact identity, set `proxy_audio_start_offset_seconds` and fail validation if drift exceeds a tiny threshold (e.g. 1 sample).  
- Do **not** use loudnorm, volume, pan, or mono downmix filters.

### 5.2 Video — Preset `performance`

Goals: balanced size, short GOP, CFR, no embedded audio, 720p.

```bash
ffmpeg -hide_banner -y \
  -i "<original_video>" \
  -an \
  -map 0:v:0 \
  -vf "scale=-2:720:flags=bicubic,fps=<TARGET_FPS>,format=yuv420p" \
  -c:v libx264 \
  -preset veryfast \
  -crf 20 \
  -profile:v high \
  -level 4.1 \
  -g 15 \
  -keyint_min 15 \
  -sc_threshold 0 \
  -bf 0 \
  -pix_fmt yuv420p \
  -movflags +faststart \
  "<tmp>/vj.proxy.mp4"
```

`TARGET_FPS`:

- If source is already near 24/25/30/50/60 CFR → preserve that family.  
- If VFR / messy → constant **30** (or song FPS when it matches a standard rate).  
- `-sc_threshold 0` + fixed `-g` → predictable keyframes for scrub.  
- `-bf 0` → no B-frames (cheaper random access / decode).

### 5.3 Video — Preset `smooth_scrub`

Goals: maximum seek/scrub responsiveness; larger files; 720p default, optional 1080p.

**Primary (H.264 All-Intra):**

```bash
ffmpeg -hide_banner -y \
  -i "<original_video>" \
  -an \
  -map 0:v:0 \
  -vf "scale=-2:720:flags=bicubic,fps=<TARGET_FPS>,format=yuv420p" \
  -c:v libx264 \
  -preset ultrafast \
  -crf 18 \
  -g 1 \
  -keyint_min 1 \
  -sc_threshold 0 \
  -bf 0 \
  -x264-params "keyint=1:min-keyint=1:scenecut=0" \
  -pix_fmt yuv420p \
  -movflags +faststart \
  "<tmp>/vj.proxy.mp4"
```

Optional 1080p: `scale=-2:1080`.

**Extremely short GOP fallback** (if All-Intra size unacceptable): `-g 2` / `-g 3` with same CFR/no-B-frame rules.

### 5.4 Peaks / seek index / thumbs (post steps)

- Peaks: decode proxy WAV (or source PCM) with the same `build_peak_pyramid` logic; write `main.peaks.npz`.  
- Seek index: list of `{pts_seconds, packet_pos}` for keyframes (ffprobe `-show_frames` / `-skip_frame nokey`).  
- Thumbs: `fps=1` image2 under `video/thumbs/` (optional).

---

## 6. Codec trade-offs for CuePlayer scrubbing

| Codec / mode | Seek / scrub | Decode CPU | Size | Windows / PyAV fit | Verdict |
|--------------|--------------|------------|------|--------------------|---------|
| **H.264 short-GOP** (`performance`) | Good if GOP≤15, no B-frames | Low–medium | Small–medium | Excellent (already primary path) | **Default preset** |
| **H.264 All-Intra** (`smooth_scrub`) | Excellent (every frame IDR) | Low per seek | Large | Excellent | **Scrub preset** |
| **MJPEG** | Excellent | Easy but higher bitrate CPU/IO | Very large | Good | Optional experiment; weaker compression than intra-H.264 |
| **ProRes** | Excellent | Easy | Very large | Needs ProRes encode path; licensing/size heavy | Defer — editor interchange, not show-floor default |
| **DNxHR** | Excellent | Easy | Very large | Less common in current PyAV Windows wheels | Defer |

**Do not assume bitrate reduction alone improves scrubbing.** Scrub cost is dominated by **distance to previous keyframe + sequential decode + colorspace convert** (see `VideoDecoder._seek` / Sprint 8 audit). Short GOP / All-Intra / CFR matter more than CRF alone.

---

## 7. Windows FFmpeg packaging recommendation

### 7.1 Discovery order

1. Bundled `ffmpeg.exe` + DLLs next to converter (`tools/ffmpeg/`)  
2. `CUEPLAYER_FFMPEG` env override  
3. System `PATH` (dev only; warn if license/version mismatch)

PyAV remains for **in-process decode/validation**; CLI FFmpeg is for **long encode jobs** (cancelable subprocess).

### 7.2 Licensing / redistribution

| Build | Notes |
|-------|-------|
| **LGPL shared** | Preferred for product redistribution: no `--enable-gpl` / `--enable-nonfree`; ship `COPYING.LGPLv2.1`, About credit, matching sources |
| **GPL (libx264)** | Common for H.264 encode (`libx264` is GPL). Shipping GPL `ffmpeg.exe` as a **separate companion binary** invoked by subprocess is the usual practical approach; still requires GPL notices + source offer for **that** binary. Does **not** automatically force CuePlayer’s Python code GPL if kept as separate executable + subprocess, but legal review should confirm distribution model |
| **`--enable-nonfree`** | **Do not redistribute** |
| System chocolatey / gyan.dev GPL builds | Fine for **dev**; pin a known build for employee zip |

**Practical v1 recommendation:**

- Ship a **pinned windows-x64 FFmpeg build** used only by the converter subprocess.  
- Prefer documenting GPL companion status clearly if libx264 is required.  
- Longer-term evaluate **OpenH264** or Media Foundation H.264 encode for LGPL-friendlier employee builds (quality/GOP control must meet scrub goals — unresolved).  
- Do **not** silently add a second multi-hundred-MB dependency into the main CuePlayer playback critical path; keep it in the converter package.

### 7.3 PyAV relationship

CuePlayer already ships FFmpeg **libraries** via `av` wheels for decode. Converter CLI FFmpeg is an **additional encode tool**, not a replacement for PyAV playback.

---

## 8. Proposed UI workflow (converter companion)

1. Drop zone: audio and/or video (Unicode names OK).  
2. Auto-probe: rate, channels, bit depth, fps, VFR warning, duration (decoded).  
3. Preset: **Performance** (default) / **Smooth Scrub** (+ optional 1080p).  
4. Output folder default: `<original_dir>/cueplayer_media/` (never inside a write over originals).  
5. One primary **Convert** button.  
6. Progress: audio % / video % / peaks / validate; Cancel always available.  
7. On success: show package path + “ready” summary (rates, frames matched, offsets).  
8. On failure/cancel: package not ready; tmp wiped; message + log path.

Later CuePlayer integration: “Open package…” / auto-detect `cueplayer_media/manifest.json` beside song media; badge when proxies active.

---

## 9. Failure and cancellation behavior

| Event | Behavior |
|-------|----------|
| Start | Write `manifest.json.partial` (`status=running`); create `tmp/` |
| Success | Validate sample/frame counts; move artifacts from `tmp/` → final names; write `manifest.json` with `status=ready`; delete `.partial` and `tmp/` |
| Cancel | Kill ffmpeg process group; delete `tmp/`; delete `.partial`; **do not** leave a `ready` manifest; remove any half-published proxy names |
| Fail | Same cleanup as cancel; optional `manifest.failed.json` with error for support (not loaded as ready) |
| Crash mid-job | Next launch treats missing/`partial` as invalid; refuses proxies |

**Invariant:** A directory never looks like a valid package unless `manifest.json` exists with `status=ready` and all referenced files exist with matching fingerprints.

---

## 10. Test strategy

| Layer | Tests |
|-------|-------|
| Unicode | Chinese source paths + Chinese output dirs (extend `tests/unicode/`) |
| Audio timing | MP3/AAC priming cases: decoded frame count / start / end vs source; assert offset field when needed |
| Audio fidelity | PCM 16/24 round-trip: sample-accurate or max abs error ≤ 1 LSB; no channel swap |
| No processing | Hash / sample compare proves no gain/normalize |
| Video CFR | Probe proxy `avg_frame_rate` == `r_frame_rate`; keyframe interval ≈ GOP |
| Seek cost | Synthetic: random seeks N times on original vs proxy (PyAV `frame_at`) — expect lower p95 on short-GOP/All-Intra |
| Invalidation | Touch mtime/size → package marked stale |
| Cancel | SIGINT/kill during encode → no ready manifest |
| Playback compat | Load proxy via existing `load_audio` / `VideoDecoder` without Song Time drift (marks at fixed seconds still align) |
| Golden | Small fixtures under `fixtures/media/` + checked-in expected manifest fields (not huge binaries) |

---

## 11. Migration and backward compatibility

1. Projects **without** packages behave exactly as today (original paths).  
2. Resolver: if `cueplayer_media/manifest.json` ready **and** fingerprints match → use proxies for decode/waveform; Song Time unchanged.  
3. If original changed → ignore proxies; show “Reconvert” (do not auto-delete without user action).  
4. Schema: additive fields only; old CuePlayer versions ignore package dirs.  
5. Sprint 8 scrub cache / async decode continue to work; proxies should **reduce** cold-decode cost, not require removing those systems.  
6. Song Variant / anchor_offset (Sprint 4–5) compose with `proxy_*_start_offset_seconds` as specified in §4 — do not overload `anchor_offset` for encoder priming.

---

## 12. Implementation plan (PR-sized tasks)

| PR | Scope |
|----|-------|
| **MC-0** | This design doc + decision log (this document) |
| **MC-1** | `cueplayer.converter` skeleton: probe + manifest schema + package atomic publish (no UI encode yet) |
| **MC-2** | Audio proxy encoder + validation harness (PCM rules §0); Chinese path tests |
| **MC-3** | Peak writer compatible with `AudioBuffer` / disk-cache tip format |
| **MC-4** | Video `performance` preset + CFR/GOP validation |
| **MC-5** | Video `smooth_scrub` All-Intra + seek benchmark tests |
| **MC-6** | FFmpeg locate/bundle docs + license notices; Windows packaging hook for converter exe |
| **MC-7** | Companion UI: drop → Convert → progress/cancel |
| **MC-8** | CuePlayer resolver (opt-in): prefer ready package; stale detection — **after** Sprint 8 video responsiveness merges |
| **MC-9** | Optional thumbs/seek index; 1080p smooth option |

**Hard rule:** MC-8+ must land on a branch that already contains Sprint 8 playback, and must not rewrite `VideoSyncController` pipeline modes.

---

## 13. Risks and unresolved decisions

1. **libx264 GPL vs LGPL employee builds** — product/legal choice; OpenH264 quality/GOP unknown for scrub.  
2. **Float WAV / >24-bit PCM policy** — default conservative; confirm with real show files.  
3. **VFR concert cameras** — fps pick (song FPS vs 30) needs a desk decision.  
4. **Whether to copy originals into package** vs reference external paths (portable Bundle vs disk savings).  
5. **Content hash** (SHA-256) vs mtime+size only — hash is safer, slower on huge files.  
6. **Proxy video + embedded audio alignment** — when users still need clip audio for alignment, either keep a separate audio extract or allow an “include stereo AAC” escape hatch (default still `-an` when main bed exists).  
7. **Exact merge base for MC-8** — wait for Sprint 8 Task 2 PR (#234 lineage) to settle.  
8. **Companion vs in-app** for v1 — recommended companion; product may still prefer a Tools dialog later.

---

## 14. Concise handoff block (for ChatGPT)

```text
HANDOFF — CuePlayer Media Converter Architecture (investigation only)
Date: 2026-08-05
Branch: cursor/media-converter-architecture-d910
Doc: docs/spikes/MEDIA_CONVERTER_ARCHITECTURE.md

Done:
- Audited master media/playback paths + Sprint 4–8 tip designs (Song Time, disk cache, Sprint 8 async video)
- Locked audio proxy rules: preserve sample rate; PCM WAV; 16-bit for lossy/16-bit; 24-bit only for real 24-bit PCM; no processing; validate decoded frames; manifest offsets if needed
- Recommended companion exe sharing modules; package dir + manifest schema; Performance vs Smooth Scrub ffmpeg settings; Windows FFmpeg packaging/licensing notes
- PR-sized implementation plan that waits to wire playback resolver until after Sprint 8 video work

Do NOT:
- Implement converter yet
- Touch Sprint 8 playback / Export UI / Song Time semantics
- Force 48 kHz audio proxies

Next:
- Architecture review / decide GPL libx264 companion vs LGPL encode path
- Then MC-1 skeleton on a new branch off agreed base
```

---

READY FOR MEDIA CONVERTER ARCHITECTURE REVIEW

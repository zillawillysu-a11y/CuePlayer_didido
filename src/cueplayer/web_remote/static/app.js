(() => {
  const TOKEN_KEY = "cueplayer_web_remote_token";

  const els = {
    songTitle: document.getElementById("songTitle"),
    clock: document.getElementById("clock"),
    duration: document.getElementById("duration"),
    tcStatus: document.getElementById("tcStatus"),
    timecode: document.getElementById("timecode"),
    toggles: document.getElementById("toggles"),
    nowPrimaryLabel: document.getElementById("nowPrimaryLabel"),
    nowPrimary: document.getElementById("nowPrimary"),
    nowSecondaryLabel: document.getElementById("nowSecondaryLabel"),
    nowSecondary: document.getElementById("nowSecondary"),
    songList: document.getElementById("songList"),
    cueList: document.getElementById("cueList"),
    markButtons: document.getElementById("markButtons"),
    playBtn: document.getElementById("playBtn"),
    pauseBtn: document.getElementById("pauseBtn"),
    stopBtn: document.getElementById("stopBtn"),
    prevSong: document.getElementById("prevSong"),
    nextSong: document.getElementById("nextSong"),
    waveWrap: document.getElementById("waveWrap"),
    waveCanvas: document.getElementById("waveCanvas"),
    waveEmpty: document.getElementById("waveEmpty"),
    waveRange: document.getElementById("waveRange"),
    zoomIn: document.getElementById("zoomIn"),
    zoomOut: document.getElementById("zoomOut"),
    zoomFit: document.getElementById("zoomFit"),
    toast: document.getElementById("toast"),
    authBtn: document.getElementById("authBtn"),
    authDialog: document.getElementById("authDialog"),
    passwordInput: document.getElementById("passwordInput"),
    savePassword: document.getElementById("savePassword"),
    listenBtn: document.getElementById("listenBtn"),
    mutePcBtn: document.getElementById("mutePcBtn"),
    previewBtn: document.getElementById("previewBtn"),
    previewWrap: document.getElementById("previewWrap"),
    previewVideo: document.getElementById("previewVideo"),
    previewEmpty: document.getElementById("previewEmpty"),
    markMgrBtn: document.getElementById("markMgrBtn"),
    markMgrDialog: document.getElementById("markMgrDialog"),
    markMgrClose: document.getElementById("markMgrClose"),
    markMgrBody: document.getElementById("markMgrBody"),
    noteDialog: document.getElementById("noteDialog"),
    noteDialogTitle: document.getElementById("noteDialogTitle"),
    noteInput: document.getElementById("noteInput"),
    noteCancel: document.getElementById("noteCancel"),
    noteSave: document.getElementById("noteSave"),
    dispBtn: document.getElementById("dispBtn"),
    dispDialog: document.getElementById("dispDialog"),
    dispClose: document.getElementById("dispClose"),
    dispPrimary: document.getElementById("dispPrimary"),
    dispSecondary: document.getElementById("dispSecondary"),
    dispTimecode: document.getElementById("dispTimecode"),
    dispToggles: document.getElementById("dispToggles"),
    cueFollowBtn: document.getElementById("cueFollowBtn"),
    renumberCueBtn: document.getElementById("renumberCueBtn"),
    waveFollowBtn: document.getElementById("waveFollowBtn"),
    deleteMarkBtn: document.getElementById("deleteMarkBtn"),
    layout: document.getElementById("layout"),
    splitSetlist: document.getElementById("splitSetlist"),
    splitMonitor: document.getElementById("splitMonitor"),
    confirmDialog: document.getElementById("confirmDialog"),
    confirmTitle: document.getElementById("confirmTitle"),
    confirmBody: document.getElementById("confirmBody"),
    confirmYes: document.getElementById("confirmYes"),
    confirmNo: document.getElementById("confirmNo"),
    cueActionDialog: document.getElementById("cueActionDialog"),
    cueActionTitle: document.getElementById("cueActionTitle"),
    cueActionBody: document.getElementById("cueActionBody"),
    cueActionList: document.getElementById("cueActionList"),
    cueActionCancel: document.getElementById("cueActionCancel"),
    nowPrimaryCard: document.querySelector(".now-card.primary"),
    nowSecondaryCard: document.querySelector(".now-card.secondary"),
  };

  let token = localStorage.getItem(TOKEN_KEY) || "";
  let scrubbing = false;
  let lastSetlistSig = "";
  let lastMarksSig = "";
  let lastLanesSig = "";
  let failCount = 0;
  let lastSongId = "";
  let wave = null;
  let waveOverview = null;
  let waveDetail = null;
  let waveLoading = false;
  let waveDetailLoading = false;
  let waveDetailReq = 0;
  let waveDetailTimer = null;
  let stateCache = null;
  let playheadColor = "#3dd68c";
  let waveColor = "#616161";
  let tcAccent = "#3dd68c";

  let syncPlaying = false;
  let syncPos = 0;
  let syncDur = 1;
  let syncEpochMs = performance.now();
  let syncSongId = "";
  let lastDrawnClock = "";
  let lastPlayheadCueId = "";
  let cueFollowSuspended = false;
  let cueFollowLeftViewport = false;
  let cueUserScrolling = false;
  let ignoreCueScroll = false;
  let lastWaveDrawMs = 0;
  let displayPrefs = {
    primary: true,
    secondary: true,
    timecode: true,
    toggles: true,
  };
  let tcSyncCode = "00:00:00:00";
  let tcSyncPos = 0;
  let tcFps = 30;
  let tcActive = false;
  let lastDrawnTc = "";
  let waveLabelFontPx = 11;
  let lastMgrLanesSig = "";
  let waveFollowSuspended = false;
  const LAYOUT_KEY = "cueplayer_web_remote_layout_v1";
  let colSetlist = 200;
  let colMonitor = 300;

  // Wave view window (seconds).
  let viewStart = 0;
  let viewEnd = 1;
  let panning = null;
  let pinching = null;

  function headers(json) {
    const h = {};
    if (json) h["Content-Type"] = "application/json";
    if (token) {
      h.Authorization = `Bearer ${token}`;
      h["X-CuePlayer-Token"] = token;
    }
    return h;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: { ...headers(Boolean(options.body)), ...(options.headers || {}) },
    });
    if (res.status === 401) {
      showToast("Password required");
      openAuth();
      throw new Error("unauthorized");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `http_${res.status}`);
    return data;
  }

  function showToast(msg) {
    els.toast.hidden = false;
    els.toast.textContent = msg;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => { els.toast.hidden = true; }, 2200);
  }

  function openAuth() {
    els.passwordInput.value = token;
    if (els.authDialog.showModal) els.authDialog.showModal();
  }

  function formatClock(seconds) {
    const totalMs = Math.max(0, Math.round(Number(seconds) * 1000));
    const mins = Math.floor(totalMs / 60000);
    const rem = totalMs % 60000;
    const secs = Math.floor(rem / 1000);
    const ms = rem % 1000;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
  }

  function tcFrameRate(fps) {
    const f = Number(fps) || 30;
    if (Math.abs(f - 29.97) < 0.02) return 30;
    return Math.max(1, Math.round(f));
  }

  function parseTimecodeSeconds(tc, fps) {
    const parts = String(tc || "").trim().replace(/;/g, ":").split(":");
    if (parts.length !== 4) return 0;
    const nums = parts.map((p) => Number(p));
    if (nums.some((n) => !Number.isFinite(n))) return 0;
    const [h, m, s, fr] = nums;
    const rate = Number(fps) > 0 ? Number(fps) : 30;
    return h * 3600 + m * 60 + s + fr / rate;
  }

  function formatSmpte(seconds, fps) {
    const rate = tcFrameRate(fps);
    const real = Number(fps) > 0 ? Number(fps) : 30;
    let total = Math.max(0, Math.round(Math.max(0, Number(seconds) || 0) * real));
    const frames = total % rate;
    total = Math.floor(total / rate);
    const secs = total % 60;
    total = Math.floor(total / 60);
    const mins = total % 60;
    const hours = Math.floor(total / 60) % 24;
    const p = (n) => String(n).padStart(2, "0");
    return `${p(hours)}:${p(mins)}:${p(secs)}:${p(frames)}`;
  }

  function syncTimecode(timecode, position, fps, active) {
    if (active != null) tcActive = Boolean(active);
    if (!tcActive || !timecode || timecode === "—") {
      tcActive = false;
      tcSyncCode = "—";
      if (position != null && Number.isFinite(Number(position))) tcSyncPos = Number(position);
      if (fps != null && Number(fps) > 0) tcFps = Number(fps);
      return;
    }
    tcActive = true;
    tcSyncCode = String(timecode);
    if (position != null && Number.isFinite(Number(position))) tcSyncPos = Number(position);
    if (fps != null && Number(fps) > 0) tcFps = Number(fps);
  }

  function liveTimecode() {
    if (!tcActive || !tcSyncCode || tcSyncCode === "—") return "—";
    const base = parseTimecodeSeconds(tcSyncCode, tcFps);
    return formatSmpte(base + (livePosition() - tcSyncPos), tcFps);
  }

  function livePosition() {
    if (scrubbing && scrubbing.seconds != null) return scrubbing.seconds;
    if (!syncPlaying) return syncPos;
    const elapsed = (performance.now() - syncEpochMs) / 1000;
    return Math.min(syncDur, Math.max(0, syncPos + elapsed));
  }

  // --- LAN music-only listen + video preview (WebRTC; HTTP audio fallback) ---
  let listenOn = false;
  let previewOn = false;
  let listenMode = ""; // "webrtc" | "http" | ""
  let listenCursor = 0;
  let listenBusy = false;
  let listenPumpTimer = null;
  let listenWasPlaying = false;
  let listenFailToastAt = 0;
  let listenCtx = null;
  let listenGain = null;
  let listenDest = null;
  let listenElement = null;
  let listenSources = [];
  let listenNextAt = 0;
  let listenSchedFrames = 0;
  let listenOriginAt = 0;
  let listenPc = null;
  let listenRtcAudio = null;
  let webrtcWantAudio = false;
  let webrtcWantVideo = false;
  let pcMuted = false;
  let markDragging = null; // { id, startSeconds, liveSeconds, pointerId }
  let markPointer = null; // pending tap vs drag: { id, startX, startY, startSeconds, pointerId }
  let selectedMarkId = "";
  const LISTEN_CHUNK = 0.55;
  const LISTEN_AHEAD = 1.25;
  const LISTEN_LEAD = 0.28;
  const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  function updateListenBtn() {
    if (!els.listenBtn) return;
    els.listenBtn.classList.toggle("on", listenOn);
    els.listenBtn.textContent = listenOn ? "Listening" : "Listen";
    els.listenBtn.title = listenOn
      ? "Stop music-only listen (LAN latency)"
      : "Listen music only on this device (no LTC)";
    if (els.mutePcBtn) {
      els.mutePcBtn.hidden = false;
      els.mutePcBtn.disabled = false;
    }
  }

  function updatePreviewBtn() {
    if (!els.previewBtn) return;
    els.previewBtn.classList.toggle("on", previewOn);
    els.previewBtn.textContent = previewOn ? "Preview On" : "Preview";
    els.previewBtn.title = previewOn
      ? "Stop low-latency video preview"
      : "Show desktop video preview (WebRTC · low latency)";
    if (els.previewWrap) els.previewWrap.hidden = !previewOn;
    if (els.previewEmpty) {
      els.previewEmpty.textContent = previewOn ? "Waiting for video…" : "Preview off";
      els.previewEmpty.classList.toggle("hidden", false);
    }
  }

  function updateMutePcBtn() {
    if (!els.mutePcBtn) return;
    els.mutePcBtn.classList.toggle("on", pcMuted);
    els.mutePcBtn.textContent = pcMuted ? "PC Muted" : "Mute PC";
    els.mutePcBtn.title = pcMuted
      ? "Unmute PC music speakers (LTC never muted)"
      : "Mute PC music speakers while Listening (LTC stays)";
  }

  async function setPcMute(muted) {
    const result = await command({ op: "set_pc_mute", muted: Boolean(muted) });
    pcMuted = Boolean(result && result.muted);
    updateMutePcBtn();
    if (stateCache) stateCache.pc_muted = pcMuted;
    return pcMuted;
  }

  function listenToastOnce(msg, everyMs = 4000) {
    const now = performance.now();
    if (now - listenFailToastAt < everyMs) return;
    listenFailToastAt = now;
    showToast(msg);
  }

  function listenStopSources() {
    for (const src of listenSources) {
      try { src.onended = null; } catch (_) { /* noop */ }
      try { src.stop(0); } catch (_) { /* noop */ }
      try { src.disconnect(); } catch (_) { /* noop */ }
    }
    listenSources = [];
  }

  function listenFlush(atPos) {
    listenBusy = false;
    listenCursor = Math.max(0, Number(atPos) || 0);
    listenStopSources();
    listenNextAt = 0;
    listenSchedFrames = 0;
    listenOriginAt = 0;
  }

  function listenResync(atPos) {
    if (!listenOn || listenMode === "webrtc") return;
    listenFlush(atPos);
    if (syncPlaying) scheduleListenPump(0);
  }

  function listenOnTransport(playing, pos) {
    if (!listenOn || listenMode === "webrtc") return;
    if (!playing) {
      listenWasPlaying = false;
      listenFlush(pos);
      return;
    }
    if (!listenWasPlaying) {
      listenWasPlaying = true;
      listenFlush(pos);
      scheduleListenPump(0);
      return;
    }
    listenWasPlaying = true;
  }

  function makeUnlockBeepBlob() {
    const sr = 22050;
    const frames = Math.floor(sr * 0.07);
    const dataSize = frames * 2;
    const buf = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buf);
    const w = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
    w(0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    w(8, "WAVE");
    w(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sr, true);
    view.setUint32(28, sr * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    w(36, "data");
    view.setUint32(40, dataSize, true);
    for (let i = 0; i < frames; i += 1) {
      const t = i / sr;
      const env = Math.min(1, i / 180) * Math.min(1, (frames - i) / 350);
      const sample = Math.sin(2 * Math.PI * 880 * t) * 0.16 * env;
      view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, sample)) * 32767, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  async function ensureListenGraph() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) throw new Error("Web Audio unsupported");
    if (!listenCtx) {
      listenCtx = new AC();
      listenGain = listenCtx.createGain();
      listenGain.gain.value = 1.0;
      // iOS: route Web Audio graph through an <audio> element so playback
      // behaves like media (and can survive the silent switch better).
      // Desktop: direct destination is enough.
      if (IS_IOS && typeof listenCtx.createMediaStreamDestination === "function") {
        listenDest = listenCtx.createMediaStreamDestination();
        listenGain.connect(listenDest);
        listenElement = new Audio();
        listenElement.playsInline = true;
        listenElement.setAttribute("playsinline", "true");
        listenElement.srcObject = listenDest.stream;
      } else {
        listenGain.connect(listenCtx.destination);
      }
    }
    if (listenCtx.state === "suspended") {
      await listenCtx.resume();
    }
    if (listenElement) {
      try {
        await listenElement.play();
      } catch (_) {
        // May succeed after the unlock beep in the same gesture.
      }
    }
    return listenCtx;
  }

  async function unlockListenAudio() {
    await ensureListenGraph();
    // Also fire a short HTMLAudio beep in the user gesture (confirms speakers).
    const blob = makeUnlockBeepBlob();
    const url = URL.createObjectURL(blob);
    const a = new Audio();
    a.playsInline = true;
    a.src = url;
    try {
      await a.play();
    } finally {
      setTimeout(() => {
        try { a.pause(); } catch (_) { /* noop */ }
        try { URL.revokeObjectURL(url); } catch (_) { /* noop */ }
      }, 200);
    }
    if (listenElement) {
      await listenElement.play();
    }
    if (listenCtx && listenCtx.state === "suspended") {
      await listenCtx.resume();
    }
  }

  function listenSampleRate() {
    const sr = listenCtx ? Math.round(listenCtx.sampleRate) : 44100;
    return Math.max(22050, Math.min(48000, sr || 44100));
  }

  async function fetchMonitorPcm(start, seconds) {
    const q = new URLSearchParams({
      start: String(start),
      seconds: String(seconds),
      rate: String(listenSampleRate()),
      format: "s16le",
    });
    const res = await fetch(`/api/monitor?${q}`, { headers: headers(false) });
    if (res.status === 401) {
      showToast("Password required");
      openAuth();
      throw new Error("unauthorized");
    }
    if (!res.ok) throw new Error(`monitor_${res.status}`);
    const ready = res.headers.get("X-CuePlayer-Ready") === "1";
    const rate = Number(res.headers.get("X-CuePlayer-Sample-Rate") || listenSampleRate());
    const chunkStart = Number(res.headers.get("X-CuePlayer-Start") || start);
    const chunkSec = Number(res.headers.get("X-CuePlayer-Seconds") || 0);
    const songId = res.headers.get("X-CuePlayer-Song-Id") || "";
    const frames = Number(res.headers.get("X-CuePlayer-Frames") || 0);
    const ab = await res.arrayBuffer();
    return { ready, rate, chunkStart, chunkSec, songId, frames, ab };
  }

  function pcm16ToAudioBuffer(ab, rate) {
    const ctx = listenCtx;
    const bytes = ab.byteLength - (ab.byteLength % 2);
    const frames = bytes / 2;
    if (!ctx || frames < 8) return null;
    // Always create at the AudioContext rate — Safari rejects mismatches.
    const ctxRate = ctx.sampleRate;
    const srcRate = rate > 0 ? rate : ctxRate;
    const i16 = new Int16Array(ab, 0, frames);
    let outFrames = frames;
    let samples;
    if (Math.abs(srcRate - ctxRate) < 1) {
      samples = new Float32Array(frames);
      for (let i = 0; i < frames; i += 1) samples[i] = i16[i] / 32768;
    } else {
      // Lightweight linear resample to context rate (gapless join stays exact).
      outFrames = Math.max(1, Math.round(frames * ctxRate / srcRate));
      samples = new Float32Array(outFrames);
      const scale = (frames - 1) / Math.max(1, outFrames - 1);
      for (let i = 0; i < outFrames; i += 1) {
        const src = i * scale;
        const i0 = Math.floor(src);
        const i1 = Math.min(frames - 1, i0 + 1);
        const frac = src - i0;
        const a = i16[i0] / 32768;
        const b = i16[i1] / 32768;
        samples[i] = a + (b - a) * frac;
      }
    }
    const buf = ctx.createBuffer(1, outFrames, ctxRate);
    buf.getChannelData(0).set(samples);
    return buf;
  }

  function scheduleListenBuffer(audioBuf, meta) {
    const ctx = listenCtx;
    if (!ctx || !audioBuf || !listenGain) return 0;
    const src = ctx.createBufferSource();
    src.buffer = audioBuf;
    src.connect(listenGain);
    const now = ctx.currentTime;
    if (!listenOriginAt || listenNextAt < now + 0.02) {
      listenOriginAt = now + LISTEN_LEAD;
      listenSchedFrames = 0;
      listenNextAt = listenOriginAt;
    }
    // Sample-accurate schedule from origin to avoid chunk-boundary drift/gaps.
    const startAt = listenOriginAt + listenSchedFrames / ctx.sampleRate;
    src.start(startAt);
    listenSources.push(src);
    src.onended = () => {
      listenSources = listenSources.filter((s) => s !== src);
    };
    listenSchedFrames += audioBuf.length;
    listenNextAt = listenOriginAt + listenSchedFrames / ctx.sampleRate;
    const songDur = Number(meta.chunkSec) > 0
      ? Number(meta.chunkSec)
      : (audioBuf.length / (meta.rate || ctx.sampleRate));
    listenCursor = (Number.isFinite(meta.chunkStart) ? meta.chunkStart : listenCursor) + songDur;
    return songDur;
  }

  async function listenFill() {
    if (!listenOn || listenBusy || !syncPlaying) return;
    const ctx = listenCtx;
    if (!ctx) return;
    if (ctx.state === "suspended") {
      try { await ctx.resume(); } catch (_) { /* noop */ }
    }
    if (listenElement && listenElement.paused) {
      try { await listenElement.play(); } catch (_) { /* noop */ }
    }
    const pos = livePosition();
    // Underrun / late: snap cursor forward and restart the schedule timeline.
    if (listenCursor + 0.12 < pos) {
      listenCursor = pos;
      listenNextAt = 0;
      listenOriginAt = 0;
      listenSchedFrames = 0;
      listenStopSources();
    }
    // Enough audio already queued ahead of the playhead.
    const queuedSong = listenCursor - pos;
    if (queuedSong > LISTEN_AHEAD) return;
    // Also keep wall-clock queue healthy.
    if (listenNextAt - ctx.currentTime > LISTEN_AHEAD + 0.15 && queuedSong > 0.4) return;

    listenBusy = true;
    try {
      // Pull enough chunks in one pump to stay ahead (reduces gap risk on slow LAN).
      let guard = 0;
      while (
        listenOn
        && syncPlaying
        && guard < 3
        && (listenCursor - livePosition()) < LISTEN_AHEAD
      ) {
        guard += 1;
        const chunk = await fetchMonitorPcm(listenCursor, LISTEN_CHUNK);
        if (!listenOn || !syncPlaying) return;
        if (chunk.songId && syncSongId && chunk.songId !== syncSongId) {
          listenFlush(livePosition());
          return;
        }
        if (!chunk.ready || !chunk.ab || chunk.ab.byteLength < 2 || chunk.frames < 32) {
          listenToastOnce("No music buffer on PC yet — open a song with audio");
          listenCursor += LISTEN_CHUNK;
          break;
        }
        const audioBuf = pcm16ToAudioBuffer(chunk.ab, chunk.rate || listenSampleRate());
        if (!audioBuf) {
          listenToastOnce("Listen decode failed");
          break;
        }
        scheduleListenBuffer(audioBuf, chunk);
      }
    } catch (err) {
      if (String(err && err.message) === "unauthorized") return;
      listenToastOnce(`Listen error: ${err && err.message ? err.message : "error"}`);
    } finally {
      listenBusy = false;
    }
  }

  function scheduleListenPump(delayMs) {
    if (listenMode === "webrtc") return;
    if (listenPumpTimer) clearTimeout(listenPumpTimer);
    listenPumpTimer = setTimeout(async () => {
      listenPumpTimer = null;
      if (!listenOn || listenMode !== "http") return;
      try {
        await listenFill();
      } catch (_) { /* ignore */ }
      if (listenOn && listenMode === "http") {
        scheduleListenPump(syncPlaying ? 120 : 450);
      }
    }, delayMs);
  }

  function waitIceComplete(pc, timeoutMs) {
    if (!pc || pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        resolve();
      };
      const timer = setTimeout(finish, timeoutMs || 4000);
      pc.addEventListener("icegatheringstatechange", () => {
        if (pc.iceGatheringState === "complete") {
          clearTimeout(timer);
          finish();
        }
      });
    });
  }

  async function stopWebRtcListen() {
    const pc = listenPc;
    listenPc = null;
    webrtcWantAudio = false;
    webrtcWantVideo = false;
    if (pc) {
      try { pc.ontrack = null; } catch (_) { /* noop */ }
      try { pc.close(); } catch (_) { /* noop */ }
    }
    if (listenRtcAudio) {
      try { listenRtcAudio.pause(); } catch (_) { /* noop */ }
      try { listenRtcAudio.srcObject = null; } catch (_) { /* noop */ }
      listenRtcAudio = null;
    }
    if (els.previewVideo) {
      try { els.previewVideo.pause(); } catch (_) { /* noop */ }
      try { els.previewVideo.srcObject = null; } catch (_) { /* noop */ }
    }
    try {
      await api("/api/webrtc", {
        method: "POST",
        body: JSON.stringify({ op: "hangup" }),
      });
    } catch (_) { /* offline / already down */ }
  }

  async function startWebRtcSession({ audio = false, video = false } = {}) {
    const wantAudio = Boolean(audio);
    const wantVideo = Boolean(video);
    if (!wantAudio && !wantVideo) {
      await stopWebRtcListen();
      return;
    }
    if (
      listenPc
      && webrtcWantAudio === wantAudio
      && webrtcWantVideo === wantVideo
      && listenPc.connectionState !== "failed"
      && listenPc.connectionState !== "closed"
    ) {
      return;
    }
    if (typeof RTCPeerConnection !== "function") {
      throw new Error("RTCPeerConnection unsupported");
    }
    const caps = await api("/api/webrtc", {
      method: "POST",
      body: JSON.stringify({ op: "capabilities" }),
    });
    if (!caps || !caps.webrtc) {
      throw new Error(caps && caps.error ? caps.error : "webrtc_unavailable");
    }
    if (wantVideo && caps.video === false) {
      throw new Error("video_unavailable");
    }

    await stopWebRtcListen();

    const pc = new RTCPeerConnection({
      iceServers: [],
      bundlePolicy: "max-bundle",
    });
    listenPc = pc;
    webrtcWantAudio = wantAudio;
    webrtcWantVideo = wantVideo;
    if (wantAudio) pc.addTransceiver("audio", { direction: "recvonly" });
    if (wantVideo) pc.addTransceiver("video", { direction: "recvonly" });

    let audioEl = null;
    if (wantAudio) {
      audioEl = new Audio();
      audioEl.playsInline = true;
      audioEl.setAttribute("playsinline", "true");
      audioEl.autoplay = true;
      try { audioEl.playbackRate = 1; } catch (_) { /* noop */ }
      try { audioEl.defaultPlaybackRate = 1; } catch (_) { /* noop */ }
      listenRtcAudio = audioEl;
    }

    pc.ontrack = (ev) => {
      const stream = (ev.streams && ev.streams[0])
        ? ev.streams[0]
        : new MediaStream([ev.track]);
      if (ev.track && ev.track.kind === "video") {
        if (els.previewVideo) {
          els.previewVideo.srcObject = stream;
          els.previewVideo.muted = true;
          els.previewVideo.playsInline = true;
          els.previewVideo.setAttribute("playsinline", "true");
          els.previewVideo.play().catch(() => {});
          if (els.previewEmpty) els.previewEmpty.classList.add("hidden");
        }
        return;
      }
      if (audioEl && ev.track && ev.track.kind === "audio") {
        audioEl.srcObject = stream;
        try { audioEl.playbackRate = 1; } catch (_) { /* noop */ }
        audioEl.play().catch(() => {});
      }
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState !== "failed") return;
      if (listenOn && listenMode === "webrtc") {
        listenToastOnce("WebRTC failed — falling back");
        fallbackListenHttp();
        return;
      }
      if (previewOn) {
        listenToastOnce("Preview WebRTC failed");
        setPreviewOn(false).catch(() => {});
      }
    };

    const offer = await pc.createOffer({
      offerToReceiveAudio: wantAudio,
      offerToReceiveVideo: wantVideo,
    });
    await pc.setLocalDescription(offer);
    await waitIceComplete(pc, 4000);
    if (!listenPc) throw new Error("webrtc_cancelled");
    // User may have toggled off while negotiating.
    if (!(wantAudio && listenOn) && !(wantVideo && previewOn)) {
      throw new Error("webrtc_cancelled");
    }

    const answer = await api("/api/webrtc", {
      method: "POST",
      body: JSON.stringify({
        op: "offer",
        type: pc.localDescription.type,
        sdp: pc.localDescription.sdp,
        audio: wantAudio,
        video: wantVideo,
      }),
    });
    if (!answer || !answer.ok || !answer.sdp) {
      throw new Error((answer && answer.error) || "webrtc_answer");
    }
    await pc.setRemoteDescription({
      type: answer.type || "answer",
      sdp: answer.sdp,
    });
    if (audioEl && audioEl.srcObject) {
      await audioEl.play();
    }
    if (wantVideo && els.previewVideo && els.previewVideo.srcObject) {
      await els.previewVideo.play();
    }
  }

  async function refreshWebRtcMedia() {
    const wantVideo = previewOn;
    const wantAudio = listenOn && listenMode !== "http";
    if (!wantAudio && !wantVideo) {
      await stopWebRtcListen();
      return;
    }
    await startWebRtcSession({ audio: wantAudio, video: wantVideo });
  }

  async function fallbackListenHttp() {
    if (!listenOn) return;
    listenMode = "http";
    // Keep / rebuild WebRTC for Preview-only if needed.
    try {
      if (previewOn) {
        await startWebRtcSession({ audio: false, video: true });
      } else {
        await stopWebRtcListen();
      }
    } catch (_) {
      await stopWebRtcListen();
    }
    listenWasPlaying = syncPlaying;
    listenFlush(livePosition());
    showToast("Listening (HTTP fallback)");
    scheduleListenPump(0);
  }

  async function setPreviewOn(on) {
    previewOn = Boolean(on);
    updatePreviewBtn();
    if (!previewOn) {
      if (els.previewVideo) {
        try { els.previewVideo.pause(); } catch (_) { /* noop */ }
        try { els.previewVideo.srcObject = null; } catch (_) { /* noop */ }
      }
      try {
        if (listenOn && listenMode === "webrtc") {
          await startWebRtcSession({ audio: true, video: false });
        } else if (listenOn && listenMode === "http") {
          await stopWebRtcListen();
        } else {
          await stopWebRtcListen();
        }
      } catch (e) {
        showToast(String(e.message || e));
      }
      showToast("Preview off");
      return;
    }
    try {
      if (listenOn && listenMode === "webrtc") {
        await startWebRtcSession({ audio: true, video: true });
      } else if (listenOn && listenMode === "http") {
        await startWebRtcSession({ audio: false, video: true });
      } else {
        await startWebRtcSession({ audio: false, video: true });
      }
      showToast("Preview on (WebRTC · low latency)");
    } catch (err) {
      previewOn = false;
      updatePreviewBtn();
      showToast(`Preview failed: ${err && err.message ? err.message : "error"}`);
    }
  }

  async function setListenOn(on) {
    listenOn = Boolean(on);
    updateListenBtn();
    if (!listenOn) {
      if (listenPumpTimer) {
        clearTimeout(listenPumpTimer);
        listenPumpTimer = null;
      }
      listenFlush(livePosition());
      listenWasPlaying = false;
      listenMode = "";
      if (listenElement) {
        try { listenElement.pause(); } catch (_) { /* noop */ }
      }
      try {
        if (previewOn) {
          await startWebRtcSession({ audio: false, video: true });
        } else {
          await stopWebRtcListen();
        }
      } catch (_) {
        await stopWebRtcListen();
      }
      if (pcMuted) {
        try { await setPcMute(false); } catch (_) { /* keep */ }
      }
      showToast("Listen off");
      return;
    }
    try {
      await unlockListenAudio();
    } catch (err) {
      listenOn = false;
      updateListenBtn();
      showToast(IS_IOS
        ? "iPad blocked audio — check silent switch / volume"
        : "Browser blocked audio unlock");
      return;
    }

    // Prefer Sunshine-class WebRTC (Opus/UDP). Fall back to HTTP chunks.
    try {
      await startWebRtcSession({ audio: true, video: previewOn });
      listenMode = "webrtc";
      listenWasPlaying = syncPlaying;
      if (!syncPlaying) {
        showToast("WebRTC listen armed — press Play");
      } else {
        showToast("Listening (WebRTC · low latency)");
      }
      return;
    } catch (err) {
      const msg = err && err.message ? String(err.message) : "error";
      if (msg !== "unauthorized") {
        listenToastOnce(`WebRTC unavailable (${msg}) — HTTP fallback`);
      }
      await fallbackListenHttp();
    }
  }

  function syncFromServer(position, duration, playing, songId) {
    const nextPos = Math.max(0, Number(position) || 0);
    const nextDur = Math.max(0.1, Number(duration) || 0.1);
    const songChanged = songId && songId !== syncSongId;
    const posDelta = Math.abs(nextPos - livePosition());
    const seekJump = !songChanged && posDelta > 0.45;
    const listenHardSeek = Boolean(songChanged) || (!songChanged && posDelta > 1.0);
    if (songChanged) {
      syncSongId = songId;
      lastPlayheadCueId = "";
      viewStart = 0;
      viewEnd = nextDur;
      clearSecondaryTimer();
      secondaryHoldId = null;
      secondaryCleared = false;
      setCueFollowSuspended(false);
      cueFollowLeftViewport = false;
      setWaveFollowSuspended(false);
      selectedMarkId = "";
      if (els.deleteMarkBtn) els.deleteMarkBtn.hidden = true;
    } else if (seekJump) {
      setCueFollowSuspended(false);
      cueFollowLeftViewport = false;
    }
    syncPlaying = Boolean(playing);
    syncPos = nextPos;
    syncDur = nextDur;
    syncEpochMs = performance.now();
    if (viewEnd <= viewStart + 0.05 || viewEnd > nextDur + 0.5) {
      viewStart = 0;
      viewEnd = nextDur;
    } else {
      viewEnd = Math.min(viewEnd, nextDur);
      viewStart = Math.max(0, Math.min(viewStart, viewEnd - 0.05));
    }
    if (listenHardSeek) {
      listenResync(nextPos);
    } else {
      listenOnTransport(Boolean(playing), nextPos);
    }
  }

  function formatNowBody(item) {
    if (!item) return "—";
    const bits = [];
    bits.push(item.lane_name || "");
    if (item.main_cue_id) bits.push(`Cue ${item.main_cue_id}`);
    if (item.display_name) bits.push(item.display_name);
    return bits.filter(Boolean).join(" · ") || "—";
  }

  function activeAmongLanes(marks, laneIndices, position) {
    const allowed = new Set(laneIndices || []);
    if (!allowed.size) return null;
    let active = null;
    for (const m of marks || []) {
      if (Number(m.time_seconds) > position + 1e-4) break;
      if (allowed.has(Number(m.lane_index))) active = m;
    }
    return active;
  }

  let secondaryHoldId = null;
  let secondaryCleared = false;
  let secondaryClearTimer = null;
  let secondaryClearSeconds = 0.5;

  function clearSecondaryTimer() {
    if (secondaryClearTimer != null) {
      clearTimeout(secondaryClearTimer);
      secondaryClearTimer = null;
    }
  }

  function showSecondaryEmpty() {
    els.nowSecondaryLabel.textContent = "SECONDARY";
    els.nowSecondary.textContent = "—";
  }

  function applySecondaryHold(mark) {
    if (!mark) {
      clearSecondaryTimer();
      secondaryHoldId = null;
      secondaryCleared = false;
      showSecondaryEmpty();
      return;
    }
    if (mark.id !== secondaryHoldId) {
      secondaryHoldId = mark.id;
      secondaryCleared = false;
      clearSecondaryTimer();
      const clearS = Math.max(0, Number(secondaryClearSeconds) || 0);
      if (clearS > 0) {
        secondaryClearTimer = setTimeout(() => {
          secondaryCleared = true;
          showSecondaryEmpty();
        }, Math.round(clearS * 1000));
      }
    }
    if (secondaryCleared) {
      showSecondaryEmpty();
      return;
    }
    els.nowSecondaryLabel.textContent = `SECONDARY · ${mark.lane_name || ""}`;
    els.nowSecondary.textContent = formatNowBody(mark);
  }

  function updateNowCards(position) {
    if (!stateCache) return;
    const now = stateCache.now || {};
    const marks = stateCache.marks || [];
    const primaryLanes = now.primary_lanes || [];
    const secondaryLanes = now.secondary_lanes || [];
    secondaryClearSeconds = Number(now.secondary_clear_seconds);
    if (!Number.isFinite(secondaryClearSeconds)) secondaryClearSeconds = 0.5;

    const primary = activeAmongLanes(marks, primaryLanes, position)
      || ((now.primary && now.primary[0]) || null);
    if (primary) {
      els.nowPrimaryLabel.textContent = `PRIMARY · ${primary.lane_name || ""}`;
      els.nowPrimary.textContent = formatNowBody(primary);
    } else {
      els.nowPrimaryLabel.textContent = "PRIMARY";
      els.nowPrimary.textContent = "—";
    }

    if (now.secondary_enabled === false) {
      applySecondaryHold(null);
      return;
    }
    const secondary = activeAmongLanes(marks, secondaryLanes, position)
      || ((now.secondary && now.secondary[0]) || null);
    applySecondaryHold(secondary);
  }

  function renderSetlist(rows) {
    const sig = JSON.stringify(rows);
    if (sig === lastSetlistSig) return;
    lastSetlistSig = sig;
    els.songList.innerHTML = "";
    if (!rows.length) {
      els.songList.textContent = "Empty setlist";
      return;
    }
    for (const row of rows) {
      if (row.kind === "folder") {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "folder-item";
        btn.innerHTML = `<span class="chev"></span><span class="name"></span>`;
        btn.querySelector(".chev").textContent = row.collapsed ? "▸" : "▾";
        btn.querySelector(".name").textContent = row.name || "Folder";
        btn.addEventListener("click", () => {
          command({
            op: "toggle_folder",
            category_id: row.id,
            collapsed: !row.collapsed,
          }).catch((e) => showToast(String(e.message || e)));
        });
        els.songList.appendChild(btn);
        continue;
      }
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "song-item" + (row.active ? " active" : "") + (row.category_id ? " nested" : "");
      btn.innerHTML =
        `<span class="num"></span>` +
        `<span class="name"></span>` +
        `<span class="song-badges" aria-hidden="true"></span>`;
      btn.querySelector(".num").textContent = Number(row.setlist_number);
      btn.querySelector(".name").textContent = row.name;
      const badges = btn.querySelector(".song-badges");
      if (row.has_video) {
        const v = document.createElement("span");
        v.className = "b v on";
        v.textContent = "V";
        v.title = "Has video clip(s)";
        badges.appendChild(v);
      }
      if (row.ltc_channel === 0 || row.ltc_channel === 1) {
        const wrap = document.createElement("span");
        wrap.className = "ltc-group";
        wrap.title = row.ltc_channel === 0
          ? "Striped LTC on Left"
          : "Striped LTC on Right";
        for (const [label, on] of [
          ["LTC", true],
          ["L", row.ltc_channel === 0],
          ["R", row.ltc_channel === 1],
        ]) {
          const el = document.createElement("span");
          el.className = "b" + (on ? " on" : "");
          el.textContent = label;
          wrap.appendChild(el);
        }
        badges.appendChild(wrap);
      }
      btn.addEventListener("click", () => {
        command({ op: "select_song", index: row.index }).catch(() => {});
      });
      els.songList.appendChild(btn);
    }
  }

  function cueListMarks(state) {
    if (state && state.cue_list && state.cue_list.length) return state.cue_list;
    return (state && state.marks) || [];
  }

  function playheadCueIdAt(position, marks) {
    let id = "";
    for (const m of marks) {
      if (Number(m.time_seconds) - 1e-9 <= position) id = m.id;
      else break;
    }
    return id;
  }

  function renderCues(marks) {
    const sig = JSON.stringify(marks.map((m) => [m.id, m.display_name, m.main_cue_id, m.time_display, m.color, m.lane_name, m.cue_id_enabled]));
    if (sig === lastMarksSig) return;
    lastMarksSig = sig;
    els.cueList.innerHTML = "";
    if (!marks.length) {
      els.cueList.textContent = "No marks";
      lastPlayheadCueId = "";
      return;
    }
    for (const m of marks) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cue-item";
      btn.dataset.markId = m.id;
      btn.innerHTML = `<span class="time"></span><span class="type"></span><span class="cue-id"></span><span class="note"></span>`;
      btn.querySelector(".time").textContent = m.time_display || formatClock(m.time_seconds);
      const typeEl = btn.querySelector(".type");
      typeEl.textContent = m.lane_name || "";
      typeEl.style.color = m.color || "#aaa";
      const cueEl = btn.querySelector(".cue-id");
      cueEl.textContent = m.main_cue_id || "—";
      cueEl.title = "Edit Cue ID";
      const noteEl = btn.querySelector(".note");
      noteEl.textContent = m.display_name || "—";
      noteEl.title = "Edit Note";
      btn.style.borderLeft = `3px solid ${m.color || "#444"}`;
      cueEl.addEventListener("click", (ev) => {
        if (consumeCueSuppressClick(ev)) return;
        ev.preventDefault();
        ev.stopPropagation();
        editCueId(m).catch((e) => showToast(String(e.message || e)));
      });
      noteEl.addEventListener("click", (ev) => {
        if (consumeCueSuppressClick(ev)) return;
        ev.preventDefault();
        ev.stopPropagation();
        editCueNote(m).catch((e) => showToast(String(e.message || e)));
      });
      btn.addEventListener("click", (ev) => {
        if (consumeCueSuppressClick(ev)) return;
        setSelectedMark(m.id);
        command({ op: "seek_mark", mark_id: m.id }).catch(() => {});
      });
      bindCueItemLongPress(btn, m);
      els.cueList.appendChild(btn);
    }
    lastPlayheadCueId = "";
    requestAnimationFrame(() => updateCueFollow(livePosition(), true));
  }

  function cueRowVisible(el) {
    const list = els.cueList;
    if (!list || !el) return false;
    const top = el.offsetTop;
    const bottom = top + el.offsetHeight;
    const viewTop = list.scrollTop;
    const viewBottom = viewTop + list.clientHeight;
    return bottom > viewTop + 1 && top < viewBottom - 1;
  }

  function setCueFollowSuspended(on) {
    cueFollowSuspended = Boolean(on);
    if (els.cueFollowBtn) {
      els.cueFollowBtn.hidden = !cueFollowSuspended;
    }
  }

  function scrollCueListTo(el, { force = false } = {}) {
    const list = els.cueList;
    if (!list || !el) return;
    const rowH = Math.max(1, el.offsetHeight || 36);
    const viewH = list.clientHeight;
    if (viewH <= 0) return;
    const margin = Math.min(Math.max(4, Math.floor(rowH * 0.5)), Math.max(0, viewH - rowH));
    const top = el.offsetTop;
    const bottom = top + rowH;
    const viewTop = list.scrollTop;
    const viewBottom = viewTop + viewH;
    let target = null;
    if (force) {
      // Match desktop: center when viewport is tall enough, else pin near top.
      if (viewH < rowH + margin + 8) {
        target = Math.max(0, top - margin);
      } else {
        target = Math.max(0, top - (viewH - rowH) / 2);
      }
    } else if (top < viewTop + margin) {
      target = Math.max(0, top - margin);
    } else if (bottom > viewBottom - margin) {
      target = Math.max(0, bottom - viewH + margin);
    }
    if (target == null) return;
    const maxScroll = Math.max(0, list.scrollHeight - viewH);
    const next = Math.min(maxScroll, target);
    if (Math.abs(next - list.scrollTop) < 1) return;
    ignoreCueScroll = true;
    list.scrollTop = next;
    clearTimeout(scrollCueListTo._clearIgnore);
    scrollCueListTo._clearIgnore = setTimeout(() => {
      ignoreCueScroll = false;
    }, 180);
  }

  function updateCueFollow(position, forceScroll) {
    const marks = cueListMarks(stateCache);
    const id = playheadCueIdAt(position, marks);
    const rows = els.cueList.querySelectorAll(".cue-item");
    let currentEl = null;
    for (const row of rows) {
      const on = row.dataset.markId === id;
      row.classList.toggle("current", on);
      if (on) currentEl = row;
    }
    if (!id || !currentEl) {
      lastPlayheadCueId = id;
      return;
    }
    if (cueFollowSuspended) {
      if (cueRowVisible(currentEl) && cueFollowLeftViewport) {
        setCueFollowSuspended(false);
        cueFollowLeftViewport = false;
      } else if (!cueRowVisible(currentEl)) {
        cueFollowLeftViewport = true;
      }
      lastPlayheadCueId = id;
      return;
    }
    const changed = id !== lastPlayheadCueId;
    lastPlayheadCueId = id;
    if (changed || forceScroll || !cueRowVisible(currentEl)) {
      scrollCueListTo(currentEl, { force: changed || forceScroll });
    }
  }

  function applyDisplayPrefs(prefs) {
    const src = prefs || {};
    displayPrefs = {
      primary: src.primary !== false && src.primary_visible !== false,
      secondary: src.secondary !== false && src.secondary_visible !== false,
      timecode: src.timecode !== false,
      toggles: src.toggles !== false,
    };
    if (els.nowPrimaryCard) {
      els.nowPrimaryCard.classList.toggle("hidden-panel", !displayPrefs.primary);
    }
    if (els.nowSecondaryCard) {
      els.nowSecondaryCard.classList.toggle("hidden-panel", !displayPrefs.secondary);
    }
    const showTc = displayPrefs.timecode;
    if (els.tcStatus) els.tcStatus.classList.toggle("hidden-panel", !showTc);
    if (els.timecode) els.timecode.classList.toggle("hidden-panel", !showTc);
    if (els.toggles) els.toggles.classList.toggle("hidden-panel", !displayPrefs.toggles);
    if (els.dispPrimary) els.dispPrimary.checked = displayPrefs.primary;
    if (els.dispSecondary) els.dispSecondary.checked = displayPrefs.secondary;
    if (els.dispTimecode) els.dispTimecode.checked = displayPrefs.timecode;
    if (els.dispToggles) els.dispToggles.checked = displayPrefs.toggles;
  }

  function openDisp() {
    applyDisplayPrefs(displayPrefs);
    if (els.dispDialog && els.dispDialog.showModal) els.dispDialog.showModal();
  }

  function saveDispField(key, checked) {
    applyDisplayPrefs({ ...displayPrefs, [key]: checked });
    const payload = { op: "set_display", [key]: checked };
    command(payload)
      .then((r) => {
        if (r && r.display) applyDisplayPrefs(r.display);
      })
      .catch((e) => showToast(String(e.message || e)));
  }

  function askMarkNote(laneName, initial) {
    return askText(`Note for ${laneName || "mark"}`, initial || "");
  }

  function askText(title, initial) {
    return new Promise((resolve) => {
      if (!els.noteDialog || !els.noteDialog.showModal) {
        resolve(null);
        return;
      }
      els.noteDialogTitle.textContent = title || "Edit";
      els.noteInput.value = initial || "";
      const onClose = () => {
        els.noteDialog.removeEventListener("close", onClose);
        resolve(els.noteDialog.returnValue === "ok" ? els.noteInput.value : null);
      };
      els.noteDialog.addEventListener("close", onClose, { once: true });
      els.noteDialog.showModal();
      requestAnimationFrame(() => {
        els.noteInput.focus();
        els.noteInput.select();
      });
    });
  }

  function askConfirm(title, body) {
    return new Promise((resolve) => {
      if (!els.confirmDialog || !els.confirmDialog.showModal) {
        resolve(window.confirm(`${title}\n\n${body}`));
        return;
      }
      els.confirmTitle.textContent = title || "Confirm";
      els.confirmBody.textContent = body || "";
      const onClose = () => {
        els.confirmDialog.removeEventListener("close", onClose);
        resolve(els.confirmDialog.returnValue === "ok");
      };
      els.confirmDialog.addEventListener("close", onClose, { once: true });
      els.confirmDialog.showModal();
    });
  }

  async function placeMark(payload, lane) {
    const result = await command({ op: "add_mark", ...payload });
    const name = (lane && lane.name) || result.lane_name || payload.shortcut || "mark";
    if (result && result.ask_note && result.mark_id) {
      const note = await askMarkNote(name, result.note || "");
      if (note != null) {
        await command({ op: "set_mark_note", mark_id: result.mark_id, note });
      }
    }
    showToast(`Marked ${name}`);
    return result;
  }

  async function editCueNote(mark) {
    const note = await askText(
      `Note · ${mark.lane_name || "mark"}`,
      mark.display_name || "",
    );
    if (note == null) return;
    await command({ op: "set_mark_note", mark_id: mark.id, note });
  }

  async function editCueId(mark) {
    if (!mark.cue_id_enabled) {
      showToast("Cue ID off for this type — enable Cue ID in Marks");
      return;
    }
    const cueId = await askText(
      `Cue ID · ${mark.lane_name || "mark"}`,
      mark.main_cue_id || "",
    );
    if (cueId == null) return;
    try {
      await command({ op: "set_mark_cue_id", mark_id: mark.id, cue_id: cueId });
    } catch (e) {
      showToast(String(e.message || e));
    }
  }

  const CUE_LONG_PRESS_MS = 480;
  const CUE_LONG_PRESS_MOVE_PX = 12;
  let cueLongPressTimer = null;
  let cueSuppressClick = false;

  function clearCueLongPress(btn) {
    if (cueLongPressTimer) {
      clearTimeout(cueLongPressTimer);
      cueLongPressTimer = null;
    }
    if (btn) btn.classList.remove("pressing");
  }

  function openCueActions(mark) {
    return new Promise((resolve) => {
      if (!els.cueActionDialog || !els.cueActionDialog.showModal) {
        resolve(null);
        return;
      }
      const label = mark.display_name || mark.main_cue_id || mark.lane_name || "mark";
      els.cueActionTitle.textContent = mark.lane_name || "Mark";
      els.cueActionBody.textContent =
        `${mark.time_display || formatClock(mark.time_seconds)} · ${label}`;
      els.cueActionList.innerHTML = "";
      const actions = [
        { id: "jump", label: "Jump" },
        { id: "note", label: "Edit Note" },
        {
          id: "cue_id",
          label: "Edit Cue ID",
          disabled: !mark.cue_id_enabled,
          title: mark.cue_id_enabled ? "" : "Cue ID off for this type",
        },
        { id: "delete", label: "Delete", danger: true },
      ];
      for (const a of actions) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "cue-action-btn" + (a.danger ? " danger" : "");
        b.textContent = a.label;
        if (a.disabled) {
          b.disabled = true;
          if (a.title) b.title = a.title;
        }
        b.addEventListener("click", (ev) => {
          ev.preventDefault();
          els.cueActionDialog.close(a.id);
        });
        els.cueActionList.appendChild(b);
      }
      const onClose = () => {
        els.cueActionDialog.removeEventListener("close", onClose);
        const v = els.cueActionDialog.returnValue;
        resolve(v && v !== "cancel" ? v : null);
      };
      els.cueActionDialog.addEventListener("close", onClose, { once: true });
      els.cueActionDialog.showModal();
    });
  }

  async function runCueAction(mark, action) {
    if (!mark || !action) return;
    if (action === "jump") {
      setSelectedMark(mark.id);
      await command({ op: "seek_mark", mark_id: mark.id });
      return;
    }
    if (action === "note") {
      await editCueNote(mark);
      return;
    }
    if (action === "cue_id") {
      await editCueId(mark);
      return;
    }
    if (action === "delete") {
      setSelectedMark(mark.id);
      await deleteSelectedMark();
    }
  }

  function showCueActionsForMark(mark) {
    setSelectedMark(mark.id);
    openCueActions(mark)
      .then((action) => runCueAction(mark, action))
      .catch((e) => showToast(String(e.message || e)));
  }

  function bindCueItemLongPress(btn, mark) {
    let startX = 0;
    let startY = 0;
    const onDown = (ev) => {
      if (ev.pointerType === "mouse" && ev.button !== 0) return;
      clearCueLongPress(btn);
      startX = ev.clientX;
      startY = ev.clientY;
      btn.classList.add("pressing");
      cueLongPressTimer = setTimeout(() => {
        cueLongPressTimer = null;
        btn.classList.remove("pressing");
        cueSuppressClick = true;
        clearTimeout(consumeCueSuppressClick._clear);
        consumeCueSuppressClick._clear = setTimeout(() => {
          cueSuppressClick = false;
        }, 450);
        try {
          navigator.vibrate?.(12);
        } catch (_) {
          /* ignore */
        }
        showCueActionsForMark(mark);
      }, CUE_LONG_PRESS_MS);
    };
    const onMove = (ev) => {
      if (!cueLongPressTimer) return;
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if ((dx * dx) + (dy * dy) > CUE_LONG_PRESS_MOVE_PX * CUE_LONG_PRESS_MOVE_PX) {
        clearCueLongPress(btn);
      }
    };
    const onUp = () => clearCueLongPress(btn);
    btn.addEventListener("pointerdown", onDown);
    btn.addEventListener("pointermove", onMove);
    btn.addEventListener("pointerup", onUp);
    btn.addEventListener("pointercancel", onUp);
    btn.addEventListener("lostpointercapture", onUp);
    btn.addEventListener("contextmenu", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      cueSuppressClick = true;
      clearTimeout(consumeCueSuppressClick._clear);
      consumeCueSuppressClick._clear = setTimeout(() => {
        cueSuppressClick = false;
      }, 450);
      clearCueLongPress(btn);
      showCueActionsForMark(mark);
    });
  }

  function consumeCueSuppressClick(ev) {
    if (!cueSuppressClick) return false;
    ev.preventDefault();
    ev.stopPropagation();
    cueSuppressClick = false;
    clearTimeout(consumeCueSuppressClick._clear);
    return true;
  }

  async function renumberCueIds() {
    const ok = await askConfirm(
      "Renumber Cue IDs",
      "Renumber Cue IDs for all Cue List types to 1, 2, 3… in time order?\nExisting Cue IDs will be overwritten.",
    );
    if (!ok) return;
    try {
      const result = await command({ op: "renumber_cue_ids" });
      if (result && result.unchanged) showToast("Cue IDs already 1, 2, 3…");
      else showToast(`Renumbered ${result.count || ""} cues`);
    } catch (e) {
      showToast(String(e.message || e));
    }
  }

  function renderMarkButtons(lanes) {
    const usable = (lanes || []).filter((l) => l.shortcut && l.shortcut >= "1" && l.shortcut <= "9");
    const sig = JSON.stringify(usable.map((l) => [
      l.index, l.shortcut, l.name, l.visible, l.locked, l.color, l.prompt_note_on_mark,
    ]));
    if (sig === lastLanesSig) return;
    lastLanesSig = sig;
    els.markButtons.innerHTML = "";
    const byShortcut = new Map(usable.map((l) => [l.shortcut, l]));
    for (let d = 1; d <= 9; d++) {
      const key = String(d);
      const lane = byShortcut.get(key);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "mbtn";
      btn.innerHTML = `<span class="key">${key}</span><span class="label"></span>`;
      if (!lane) {
        btn.disabled = true;
        btn.querySelector(".label").textContent = "—";
      } else {
        btn.querySelector(".label").textContent = lane.name;
        btn.style.borderLeft = `3px solid ${lane.color || "#444"}`;
        btn.disabled = !lane.visible || lane.locked;
        btn.addEventListener("click", () => {
          placeMark({ shortcut: key }, lane).catch((e) => showToast(String(e.message || e)));
        });
      }
      els.markButtons.appendChild(btn);
    }
  }

  function renderToggles(toggles) {
    const map = toggles || {};
    for (const chip of els.toggles.querySelectorAll(".chip")) {
      const key = chip.dataset.key;
      chip.classList.toggle("on", Boolean(map[key]));
    }
  }

  function renderMarkManager(lanes) {
    const list = lanes || [];
    const sig = JSON.stringify(list.map((l) => [
      l.index, l.name, l.visible, l.now, l.shortcut, l.cue_id_enabled, l.cue_list_enabled,
      l.pause_on_mark, l.prompt_note_on_mark, l.show_note_on_wave, l.show_cue_id_on_wave, l.color,
    ]));
    if (sig === lastMgrLanesSig && els.markMgrBody.children.length) return;
    lastMgrLanesSig = sig;
    els.markMgrBody.innerHTML = "";
    for (const lane of list) {
      const row = document.createElement("div");
      row.className = "mgr-row";
      row.innerHTML =
        `<span class="mgr-swatch"></span>` +
        `<input type="text" class="mgr-name" />` +
        `<label><input type="checkbox" class="mgr-vis" /> Eye</label>` +
        `<select class="mgr-now"><option value="off">Off</option><option value="primary">Primary</option><option value="secondary">Secondary</option></select>` +
        `<select class="mgr-key"><option value="">—</option>${[1,2,3,4,5,6,7,8,9].map((n) => `<option value="${n}">${n}</option>`).join("")}</select>` +
        `<div class="mgr-flags">` +
          `<label class="mgr-flag" title="Show marks in Cue List">Cue List<input type="checkbox" class="mgr-cuelist" /></label>` +
          `<label class="mgr-flag">Cue ID<input type="checkbox" class="mgr-cueid" /></label>` +
          `<label class="mgr-flag">Pause<input type="checkbox" class="mgr-pause" /></label>` +
          `<label class="mgr-flag">Ask Note<input type="checkbox" class="mgr-ask" /></label>` +
          `<label class="mgr-flag">Wave Note<input type="checkbox" class="mgr-wnote" /></label>` +
          `<label class="mgr-flag">Wave Cue<input type="checkbox" class="mgr-wcue" /></label>` +
        `</div>`;
      row.querySelector(".mgr-swatch").style.background = lane.color || "#666";
      const name = row.querySelector(".mgr-name");
      name.value = lane.name || "";
      const vis = row.querySelector(".mgr-vis");
      vis.checked = Boolean(lane.visible);
      const now = row.querySelector(".mgr-now");
      now.value = lane.now || "off";
      const key = row.querySelector(".mgr-key");
      key.value = lane.shortcut || "";
      const cueList = row.querySelector(".mgr-cuelist");
      cueList.checked = lane.cue_list_enabled !== false;
      const cueId = row.querySelector(".mgr-cueid");
      cueId.checked = Boolean(lane.cue_id_enabled);
      const pause = row.querySelector(".mgr-pause");
      pause.checked = Boolean(lane.pause_on_mark);
      const ask = row.querySelector(".mgr-ask");
      ask.checked = Boolean(lane.prompt_note_on_mark);
      const wnote = row.querySelector(".mgr-wnote");
      wnote.checked = Boolean(lane.show_note_on_wave);
      const wcue = row.querySelector(".mgr-wcue");
      wcue.checked = Boolean(lane.show_cue_id_on_wave);

      const save = () => {
        const payload = {
          op: "update_lane",
          lane_index: lane.index,
          name: name.value,
          visible: vis.checked,
          now: now.value,
          shortcut: key.value,
          cue_list_enabled: cueList.checked,
          cue_id_enabled: cueId.checked,
          pause_on_mark: pause.checked,
          prompt_note_on_mark: ask.checked,
          show_note_on_wave: wnote.checked,
          show_cue_id_on_wave: wcue.checked,
        };
        lane.name = name.value;
        lane.visible = vis.checked;
        lane.now = now.value;
        lane.shortcut = key.value;
        lane.cue_list_enabled = cueList.checked;
        lane.cue_id_enabled = cueId.checked;
        lane.pause_on_mark = pause.checked;
        lane.prompt_note_on_mark = ask.checked;
        lane.show_note_on_wave = wnote.checked;
        lane.show_cue_id_on_wave = wcue.checked;
        lastMgrLanesSig = JSON.stringify((stateCache && stateCache.lanes || list).map((l) => [
          l.index, l.name, l.visible, l.now, l.shortcut, l.cue_id_enabled, l.cue_list_enabled,
          l.pause_on_mark, l.prompt_note_on_mark, l.show_note_on_wave, l.show_cue_id_on_wave, l.color,
        ]));
        command(payload).catch((e) => showToast(String(e.message || e)));
      };
      name.addEventListener("change", save);
      vis.addEventListener("change", save);
      now.addEventListener("change", save);
      key.addEventListener("change", save);
      cueList.addEventListener("change", save);
      cueId.addEventListener("change", save);
      pause.addEventListener("change", save);
      ask.addEventListener("change", save);
      wnote.addEventListener("change", save);
      wcue.addEventListener("change", save);
      els.markMgrBody.appendChild(row);
    }
  }

  function viewSpan() {
    return Math.max(0.05, viewEnd - viewStart);
  }

  function setWaveFollowSuspended(on) {
    waveFollowSuspended = Boolean(on);
    if (els.waveFollowBtn) els.waveFollowBtn.hidden = !waveFollowSuspended;
  }

  function followWavePlayhead(pos) {
    if (!syncPlaying || scrubbing || panning || pinching) return false;
    if (waveFollowSuspended) return false;
    const span = viewSpan();
    if (span >= syncDur - 0.05) return false;
    const margin = Math.min(span * 0.22, Math.max(0.15, span * 0.15));
    if (pos >= viewStart + margin && pos <= viewEnd - margin) return false;
    const half = span / 2;
    viewStart = pos - half;
    viewEnd = pos + half;
    clampView();
    scheduleWaveDetail();
    return true;
  }

  function clampView() {
    const span = viewSpan();
    if (span >= syncDur) {
      viewStart = 0;
      viewEnd = syncDur;
      return;
    }
    if (viewStart < 0) {
      viewStart = 0;
      viewEnd = span;
    }
    if (viewEnd > syncDur) {
      viewEnd = syncDur;
      viewStart = Math.max(0, syncDur - span);
    }
  }

  function zoomAt(factor, anchorSec) {
    const span = viewSpan();
    const next = Math.min(syncDur, Math.max(0.12, span * factor));
    const anchor = anchorSec == null ? (viewStart + viewEnd) / 2 : anchorSec;
    const ratio = span > 1e-6 ? (anchor - viewStart) / span : 0.5;
    viewStart = anchor - next * ratio;
    viewEnd = viewStart + next;
    clampView();
    setWaveFollowSuspended(true);
    scheduleWaveDetail();
    drawWave(true);
  }

  function activeWave() {
    const detail = waveDetail;
    if (
      detail
      && detail.ready
      && detail.song_id === syncSongId
      && Number(detail.end) > Number(detail.start)
      && viewStart >= Number(detail.start) - 1e-3
      && viewEnd <= Number(detail.end) + 1e-3
    ) {
      return detail;
    }
    return waveOverview || wave;
  }

  function scheduleWaveDetail() {
    clearTimeout(waveDetailTimer);
    waveDetailTimer = setTimeout(() => {
      ensureWaveDetail().catch(() => {});
    }, 90);
  }

  function resizeCanvas() {
    const canvas = els.waveCanvas;
    const rect = els.waveWrap.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.floor(rect.width * dpr));
    const h = Math.max(1, Math.floor(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      return true;
    }
    return false;
  }

  function drawWave(force) {
    const now = performance.now();
    if (!force && !scrubbing && !panning && now - lastWaveDrawMs < 32) return;
    lastWaveDrawMs = now;
    const canvas = els.waveCanvas;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    resizeCanvas();
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#0a0a0a";
    ctx.fillRect(0, 0, w, h);

    const src = activeWave();
    const ready = src && src.ready && src.mins && src.mins.length;
    els.waveEmpty.classList.toggle("hidden", Boolean(ready));
    els.waveRange.textContent = `${formatClock(viewStart)} – ${formatClock(viewEnd)}`;
    if (!ready) return;

    const mid = h * 0.5;
    const amp = h * 0.42;
    const n = src.mins.length;
    const waveStart = Number(src.start != null ? src.start : 0);
    const waveEnd = Number(src.end != null ? src.end : (src.duration || syncDur));
    const waveSpan = Math.max(0.05, waveEnd - waveStart);
    const v0 = viewStart;
    const v1 = Math.max(v0 + 0.05, viewEnd);
    const viewSpanSec = v1 - v0;

    // Map visible time → source bucket range.
    const i0 = Math.max(0, Math.floor(((v0 - waveStart) / waveSpan) * n));
    const i1 = Math.min(n, Math.ceil(((v1 - waveStart) / waveSpan) * n));

    ctx.fillStyle = waveColor || "#616161";
    ctx.beginPath();
    for (let i = i0; i < i1; i++) {
      const t0 = waveStart + (i / n) * waveSpan;
      const t1 = waveStart + ((i + 1) / n) * waveSpan;
      const x0 = ((t0 - v0) / viewSpanSec) * w;
      const x1 = ((t1 - v0) / viewSpanSec) * w;
      const yMax = mid - Number(src.maxs[i]) * amp;
      const yMin = mid - Number(src.mins[i]) * amp;
      const top = Math.min(yMax, yMin);
      const bot = Math.max(yMax, yMin);
      ctx.rect(x0, top, Math.max(1, x1 - x0), Math.max(1, bot - top));
    }
    ctx.fill();

    const marks = (stateCache && stateCache.marks) || [];
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const labelPx = Math.max(9, Math.round((waveLabelFontPx || 11) * dpr));
    ctx.textBaseline = "top";
    ctx.font = `700 ${labelPx}px "Segoe UI", "Helvetica Neue", sans-serif`;
    for (const m of marks) {
      let t = Number(m.time_seconds);
      if (markDragging && markDragging.id === m.id && markDragging.liveSeconds != null) {
        t = Number(markDragging.liveSeconds);
      }
      if (t < v0 || t > v1) continue;
      const x = ((t - v0) / viewSpanSec) * w;
      const dragging = markDragging && markDragging.id === m.id;
      const selected = selectedMarkId && selectedMarkId === m.id;
      ctx.strokeStyle = m.color || "#888";
      ctx.globalAlpha = dragging || selected ? 1 : 0.9;
      ctx.lineWidth = Math.max(
        dragging || selected ? 2.8 : 1,
        w / (dragging || selected ? 480 : 900),
      );
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
      if (selected && !dragging) {
        ctx.globalAlpha = 0.18;
        ctx.fillStyle = m.color || "#888";
        ctx.fillRect(x - 4 * dpr, 0, 8 * dpr, h);
        ctx.globalAlpha = 1;
      } else {
        ctx.globalAlpha = 1;
      }

      const showNote = Boolean(m.show_note_on_wave);
      const showCue = Boolean(m.show_cue_id_on_wave) && Boolean(m.cue_id_enabled);
      const cueLabel = showCue ? String(m.main_cue_id || "").trim() : "";
      const noteText = showNote ? String(m.display_name || "").trim() : "";
      if (!cueLabel && !noteText && !dragging) continue;
      ctx.fillStyle = m.color || "#ccc";
      let textY = 4 * dpr;
      const maxW = Math.max(40 * dpr, Math.min(160 * dpr, w - x - 8 * dpr));
      if (cueLabel) {
        ctx.fillText(`Cue ${cueLabel}`, x + 5 * dpr, textY, maxW);
        textY += labelPx + 2 * dpr;
      }
      if (noteText) {
        ctx.fillText(noteText, x + 5 * dpr, textY, maxW);
        textY += labelPx + 2 * dpr;
      }
      if (dragging) {
        ctx.fillText(formatClock(t), x + 5 * dpr, textY, maxW);
      }
    }

    let pos = livePosition();
    if (scrubbing && scrubbing.seconds != null) pos = scrubbing.seconds;
    if (pos >= v0 && pos <= v1) {
      const x = ((pos - v0) / viewSpanSec) * w;
      ctx.strokeStyle = playheadColor || "#3dd68c";
      ctx.lineWidth = Math.max(2, w / 450);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
  }

  async function ensureWaveform(songId) {
    if (!songId) {
      wave = null;
      waveOverview = null;
      waveDetail = null;
      drawWave(true);
      return;
    }
    if (waveOverview && waveOverview.song_id === songId && waveOverview.ready) {
      wave = waveOverview;
      scheduleWaveDetail();
      return;
    }
    if (waveLoading) return;
    waveLoading = true;
    try {
      const data = await api("/api/waveform?buckets=3200");
      waveOverview = data;
      wave = data;
      if (!data.ready) {
        setTimeout(() => {
          if (lastSongId === songId) {
            waveOverview = null;
            wave = null;
            ensureWaveform(songId);
          }
        }, 1200);
      } else {
        scheduleWaveDetail();
      }
      drawWave(true);
    } catch (_) {
      /* keep */
    } finally {
      waveLoading = false;
    }
  }

  async function ensureWaveDetail() {
    const songId = syncSongId || lastSongId;
    if (!songId || !waveOverview || !waveOverview.ready) return;
    const span = viewSpan();
    // Fully zoomed out — overview is enough.
    if (span >= syncDur * 0.92) {
      waveDetail = null;
      return;
    }
    // Modest pad so panning doesn't constantly refetch, but keep density high.
    const pad = Math.max(0.02, span * 0.2);
    const a = Math.max(0, viewStart - pad);
    const b = Math.min(syncDur, viewEnd + pad);
    const paddedSpan = Math.max(0.05, b - a);
    const cssW = Math.max(1, (els.waveWrap && els.waveWrap.clientWidth) || 800);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const px = Math.max(800, Math.round(cssW * dpr));
    // Request enough columns so the *visible* span has ~3 samples/pixel after pad.
    const need = Math.round(px * (paddedSpan / span) * 3);
    const buckets = Math.max(1200, Math.min(10000, need));
    const densityOk = (
      waveDetail
      && waveDetail.ready
      && waveDetail.song_id === songId
      && a >= Number(waveDetail.start) - 1e-4
      && b <= Number(waveDetail.end) + 1e-4
      && Number(waveDetail.buckets) >= buckets * 0.85
    );
    if (densityOk) return;

    const req = ++waveDetailReq;
    waveDetailLoading = true;
    try {
      const q = new URLSearchParams({
        start: String(a),
        end: String(b),
        buckets: String(buckets),
      });
      const data = await api(`/api/waveform?${q.toString()}`);
      if (req !== waveDetailReq) return;
      if (data && data.ready) {
        waveDetail = data;
        drawWave(true);
      }
    } catch (_) {
      /* keep overview */
    } finally {
      if (req === waveDetailReq) waveDetailLoading = false;
    }
  }

  function tickFrame() {
    const pos = livePosition();
    const clock = formatClock(pos);
    if (clock !== lastDrawnClock) {
      lastDrawnClock = clock;
      els.clock.textContent = clock;
    }
    if (displayPrefs.timecode !== false) {
      const tc = liveTimecode();
      if (tc !== lastDrawnTc) {
        lastDrawnTc = tc;
        els.timecode.textContent = tc;
      }
    }
    updateNowCards(pos);
    updateCueFollow(pos, false);
    const waveScrolled = followWavePlayhead(pos);
    if (syncPlaying || scrubbing || panning || waveScrolled || markDragging) drawWave(false);
    requestAnimationFrame(tickFrame);
  }

  function applyState(state) {
    const drag = markDragging;
    stateCache = state;
    if (drag && stateCache && stateCache.marks) {
      const m = stateCache.marks.find((x) => x.id === drag.id);
      if (m && drag.liveSeconds != null) {
        m.time_seconds = Number(drag.liveSeconds);
        m.time_display = formatClock(drag.liveSeconds);
      }
    }
    const song = state.song || {};
    els.songTitle.textContent = song.in_setlist === false || song.index < 0 ? "(no song)" : (song.name || "—");
    syncFromServer(state.position, state.duration, state.playing, song.id || "");
    const tcOn = state.tc_active != null
      ? Boolean(state.tc_active)
      : Boolean(state.tc_status && state.tc_status !== "TC off");
    syncTimecode(state.timecode, state.position, song.fps, tcOn);
    els.duration.textContent = `/ ${state.duration_clock || formatClock(state.duration)}`;
    els.tcStatus.textContent = state.tc_status || "TC off";
    els.timecode.textContent = liveTimecode();
    lastDrawnTc = els.timecode.textContent;
    tcAccent = state.tc_accent || state.playhead_color || "#3dd68c";
    document.documentElement.style.setProperty("--ok", tcAccent);
    els.timecode.style.color = tcActive ? tcAccent : "#52525b";
    playheadColor = state.playhead_color || "#3dd68c";
    waveColor = state.waveform_color || "#616161";
    waveLabelFontPx = Number(state.wave_label_font_px) || 11;
    if (state.pc_muted != null) {
      pcMuted = Boolean(state.pc_muted);
      updateMutePcBtn();
    }
    applyDisplayPrefs(state.display || state.now || displayPrefs);
    updateNowCards(livePosition());

    renderToggles(state.output_toggles);
    const playing = Boolean(state.playing);
    els.playBtn.disabled = playing;
    els.pauseBtn.disabled = !playing;
    els.pauseBtn.classList.toggle("active", playing);

    const songId = song.id || "";
    if (songId !== lastSongId) {
      lastSongId = songId;
      wave = null;
      waveOverview = null;
      waveDetail = null;
      ensureWaveform(songId);
    } else if (!waveOverview || !waveOverview.ready) {
      ensureWaveform(songId);
    }

    renderSetlist(state.setlist || []);
    renderCues(cueListMarks(state));
    renderMarkButtons(state.lanes || []);
    // Drop selection if that mark no longer exists after a refresh/delete.
    if (selectedMarkId) {
      const still = (state.marks || []).some((m) => m.id === selectedMarkId);
      if (!still) setSelectedMark("");
      else setSelectedMark(selectedMarkId);
    }
    // Never rebuild Mark Manager while open — native <select> pickers close on DOM replace.
    if (!els.markMgrDialog.open) lastMgrLanesSig = "";
    drawWave(true);
  }

  async function command(body) {
    const result = await api("/api/command", { method: "POST", body: JSON.stringify(body) });
    if (body.op === "play") {
      syncPlaying = true;
      syncEpochMs = performance.now();
      els.playBtn.disabled = true;
      els.pauseBtn.disabled = false;
      els.pauseBtn.classList.add("active");
      setWaveFollowSuspended(false);
    } else if (body.op === "pause") {
      syncPos = livePosition();
      syncPlaying = false;
      syncEpochMs = performance.now();
      els.playBtn.disabled = false;
      els.pauseBtn.disabled = true;
      els.pauseBtn.classList.remove("active");
    } else if (body.op === "stop") {
      syncPlaying = false;
      syncPos = 0;
      syncEpochMs = performance.now();
      els.playBtn.disabled = false;
      els.pauseBtn.disabled = true;
      els.pauseBtn.classList.remove("active");
      setCueFollowSuspended(false);
      cueFollowLeftViewport = false;
    } else if (body.op === "seek" && body.seconds != null) {
      syncPos = Number(body.seconds);
      syncEpochMs = performance.now();
      setCueFollowSuspended(false);
      cueFollowLeftViewport = false;
    } else if (body.op === "seek_mark") {
      setCueFollowSuspended(false);
      cueFollowLeftViewport = false;
      api("/api/state").then(applyState).catch(() => {});
    } else if (
      body.op === "toggle_folder"
      || body.op === "update_lane"
      || body.op === "set_output_toggle"
      || body.op === "set_display"
      || body.op === "set_mark_note"
      || body.op === "set_mark_cue_id"
      || body.op === "move_mark"
      || body.op === "delete_marks"
      || body.op === "set_pc_mute"
      || body.op === "renumber_cue_ids"
      || body.op === "add_mark"
    ) {
      api("/api/state").then(applyState).catch(() => {});
    } else if (body.op === "toggle") {
      if (syncPlaying) {
        syncPos = livePosition();
        syncPlaying = false;
      } else syncPlaying = true;
      syncEpochMs = performance.now();
    }
    return result;
  }

  async function pollState() {
    try {
      const state = await api("/api/state");
      failCount = 0;
      applyState(state);
    } catch (err) {
      failCount += 1;
      if (failCount === 1 || failCount % 8 === 0) {
        showToast(err.message === "unauthorized" ? "Password required" : "Waiting for CuePlayer…");
      }
    } finally {
      setTimeout(pollState, syncPlaying ? 500 : 700);
    }
  }

  async function pollClock() {
    try {
      const clock = await api("/api/clock");
      if (clock && clock.ok !== false) {
        syncFromServer(clock.position, clock.duration, clock.playing, clock.song_id || syncSongId);
        const tcOn = clock.tc_active != null
          ? Boolean(clock.tc_active)
          : Boolean(clock.tc_status && clock.tc_status !== "TC off");
        syncTimecode(clock.timecode, clock.position, clock.fps, tcOn);
        if (clock.tc_status) els.tcStatus.textContent = clock.tc_status;
        else if (clock.tc_active === false) els.tcStatus.textContent = "TC off";
        if (clock.tc_accent) {
          tcAccent = clock.tc_accent;
        }
        els.timecode.style.color = tcActive ? tcAccent : "#52525b";
        const playing = Boolean(clock.playing);
        els.playBtn.disabled = playing;
        els.pauseBtn.disabled = !playing;
        els.pauseBtn.classList.toggle("active", playing);
      }
    } catch (_) {
      /* ignore */
    } finally {
      setTimeout(pollClock, syncPlaying ? 80 : 350);
    }
  }

  function timeFromClientX(clientX) {
    const rect = els.waveWrap.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)));
    return viewStart + ratio * viewSpan();
  }

  function hitTestMark(clientX) {
    const marks = (stateCache && stateCache.marks) || [];
    if (!marks.length) return null;
    const rect = els.waveWrap.getBoundingClientRect();
    const span = viewSpan();
    const pxPerSec = rect.width / Math.max(0.05, span);
    const hitSlop = Math.max(0.025, 16 / Math.max(1, pxPerSec)); // ~16 CSS px
    const t = timeFromClientX(clientX);
    let best = null;
    let bestDist = hitSlop;
    for (const m of marks) {
      if (m.lane_visible === false) continue;
      if (m.lane_locked) continue;
      const liveT = (markDragging && markDragging.id === m.id && markDragging.liveSeconds != null)
        ? Number(markDragging.liveSeconds)
        : Number(m.time_seconds);
      const d = Math.abs(liveT - t);
      if (d <= bestDist) {
        best = m;
        bestDist = d;
      }
    }
    return best;
  }

  function selectedMark() {
    if (!selectedMarkId || !stateCache || !stateCache.marks) return null;
    return stateCache.marks.find((m) => m.id === selectedMarkId) || null;
  }

  function setSelectedMark(markId) {
    selectedMarkId = markId ? String(markId) : "";
    if (els.deleteMarkBtn) {
      els.deleteMarkBtn.hidden = !selectedMarkId;
    }
    // Highlight matching cue-list row when present.
    if (els.cueList) {
      for (const row of els.cueList.querySelectorAll(".cue-item")) {
        row.classList.toggle("selected-mark", Boolean(selectedMarkId) && row.dataset.markId === selectedMarkId);
      }
    }
    drawWave(true);
  }

  async function deleteSelectedMark() {
    const mark = selectedMark();
    if (!mark) {
      showToast("Select a mark on the wave first");
      return;
    }
    const label = mark.display_name || mark.main_cue_id || mark.lane_name || "mark";
    const ok = await askConfirm(
      "Delete Mark",
      `Delete this mark?\n${mark.time_display || formatClock(mark.time_seconds)} · ${label}`,
    );
    if (!ok) return;
    try {
      const result = await command({
        op: "delete_marks",
        mark_ids: [mark.id],
      });
      setSelectedMark("");
      showToast(`Deleted ${result.removed || 1} mark`);
    } catch (e) {
      showToast(String(e.message || e));
    }
  }

  els.playBtn.addEventListener("click", () => {
    setWaveFollowSuspended(false);
    command({ op: "play" }).catch(() => {});
  });
  els.pauseBtn.addEventListener("click", () => command({ op: "pause" }).catch(() => {}));
  els.stopBtn.addEventListener("click", () => {
    setWaveFollowSuspended(false);
    command({ op: "stop" }).catch(() => {});
  });
  els.prevSong.addEventListener("click", () => command({ op: "prev_song" }).catch(() => {}));
  els.nextSong.addEventListener("click", () => command({ op: "next_song" }).catch(() => {}));
  els.zoomIn.addEventListener("click", () => zoomAt(0.7, livePosition()));
  els.zoomOut.addEventListener("click", () => zoomAt(1.4, livePosition()));
  els.zoomFit.addEventListener("click", () => {
    viewStart = 0;
    viewEnd = syncDur;
    setWaveFollowSuspended(false);
    waveDetail = null;
    drawWave(true);
  });
  if (els.waveFollowBtn) {
    els.waveFollowBtn.addEventListener("click", () => {
      setWaveFollowSuspended(false);
      const pos = livePosition();
      const span = viewSpan();
      if (span < syncDur - 0.05) {
        viewStart = pos - span / 2;
        viewEnd = pos + span / 2;
        clampView();
      }
      scheduleWaveDetail();
      drawWave(true);
    });
  }
  if (els.deleteMarkBtn) {
    els.deleteMarkBtn.hidden = true;
    els.deleteMarkBtn.addEventListener("click", () => {
      deleteSelectedMark().catch((e) => showToast(String(e.message || e)));
    });
  }
  if (els.renumberCueBtn) {
    els.renumberCueBtn.addEventListener("click", () => {
      renumberCueIds().catch((e) => showToast(String(e.message || e)));
    });
  }

  for (const chip of els.toggles.querySelectorAll(".chip")) {
    chip.addEventListener("click", () => {
      const key = chip.dataset.key;
      const enabled = !chip.classList.contains("on");
      command({ op: "set_output_toggle", key, enabled })
        .then((r) => {
          if (!r.ok) showToast(r.error === "midi_port_required" ? "Set MIDI port on PC first" : (r.error || "Toggle failed"));
        })
        .catch((e) => showToast(String(e.message || e)));
    });
  }

  let scrubPointerX = null;
  let scrubEdgeRaf = null;
  let scrubLastPanMs = 0;
  let scrubDetailAt = 0;

  function stopScrubEdgeLoop() {
    if (scrubEdgeRaf != null) {
      cancelAnimationFrame(scrubEdgeRaf);
      scrubEdgeRaf = null;
    }
    scrubLastPanMs = 0;
  }

  function scrubEdgeZone(clientX) {
    const rect = els.waveWrap.getBoundingClientRect();
    const w = Math.max(1, rect.width);
    const local = clientX - rect.left;
    const edge = Math.min(72, Math.max(36, w * 0.12));
    return { rect, w, local, edge, left: local < edge, right: local > w - edge };
  }

  function updateScrubPlayhead(clientX) {
    const zone = scrubEdgeZone(clientX);
    const ratio = Math.min(1, Math.max(0, zone.local / zone.w));
    const seconds = Math.min(syncDur, Math.max(0, viewStart + ratio * viewSpan()));
    scrubbing = { seconds, clientX };
    scrubPointerX = clientX;
    drawWave(true);
    return zone;
  }

  function panScrubEdge(clientX, dt) {
    const zone = scrubEdgeZone(clientX);
    const span = viewSpan();
    if (!(span < syncDur - 0.02) || dt <= 0) return zone.left || zone.right;
    // ~22%–75% of the visible window per second (between “too fast” and “too slow”).
    let t = 0;
    if (zone.left) t = Math.min(1, Math.max(0, (zone.edge - zone.local) / zone.edge));
    else if (zone.right) t = Math.min(1, Math.max(0, (zone.local - (zone.w - zone.edge)) / zone.edge));
    else return false;
    const viewportsPerSec = 0.22 + 0.53 * t;
    const delta = Math.min(span * 0.05, span * viewportsPerSec * dt);
    if (zone.left) {
      viewStart -= delta;
      viewEnd -= delta;
    } else {
      viewStart += delta;
      viewEnd += delta;
    }
    clampView();
    setWaveFollowSuspended(true);
    const now = performance.now();
    if (now - scrubDetailAt > 180) {
      scrubDetailAt = now;
      scheduleWaveDetail();
    }
    return true;
  }

  function startScrubEdgeLoop() {
    if (scrubEdgeRaf != null) return;
    scrubLastPanMs = performance.now();
    const tick = (now) => {
      scrubEdgeRaf = null;
      if (!scrubbing || scrubPointerX == null) return;
      const zone = scrubEdgeZone(scrubPointerX);
      if (!(zone.left || zone.right)) {
        scrubLastPanMs = 0;
        return;
      }
      const dt = Math.min(0.05, Math.max(0.008, (now - (scrubLastPanMs || now)) / 1000));
      scrubLastPanMs = now;
      panScrubEdge(scrubPointerX, dt);
      updateScrubPlayhead(scrubPointerX);
      scrubEdgeRaf = requestAnimationFrame(tick);
    };
    scrubEdgeRaf = requestAnimationFrame(tick);
  }

  els.waveWrap.addEventListener("pointerdown", (ev) => {
    if (ev.pointerType === "touch" && els.waveWrap.hasPointerCapture?.(ev.pointerId)) return;
    // Two-finger gestures handled in touchstart.
    if (ev.isPrimary === false) return;
    panning = null;
    pinching = null;
    const hit = hitTestMark(ev.clientX);
    if (hit) {
      markPointer = {
        id: hit.id,
        startX: ev.clientX,
        startY: ev.clientY,
        startSeconds: Number(hit.time_seconds),
        pointerId: ev.pointerId,
      };
      markDragging = null;
      scrubbing = false;
      scrubPointerX = null;
      stopScrubEdgeLoop();
      els.waveWrap.setPointerCapture(ev.pointerId);
      return;
    }
    markPointer = null;
    markDragging = null;
    if (selectedMarkId) setSelectedMark("");
    els.waveWrap.setPointerCapture(ev.pointerId);
    const zone = updateScrubPlayhead(ev.clientX);
    if (zone.left || zone.right) startScrubEdgeLoop();
  });
  els.waveWrap.addEventListener("pointermove", (ev) => {
    if (markPointer && markPointer.pointerId === ev.pointerId && !markDragging) {
      const dist = Math.hypot(ev.clientX - markPointer.startX, ev.clientY - markPointer.startY);
      if (dist >= 10) {
        // Promote tap to drag once the finger moves enough.
        markDragging = {
          id: markPointer.id,
          startSeconds: markPointer.startSeconds,
          liveSeconds: markPointer.startSeconds,
          pointerId: markPointer.pointerId,
        };
        markPointer = null;
        setSelectedMark(markDragging.id);
        setWaveFollowSuspended(true);
      } else {
        return;
      }
    }
    if (markDragging && markDragging.pointerId === ev.pointerId) {
      const seconds = Math.min(syncDur, Math.max(0, timeFromClientX(ev.clientX)));
      markDragging.liveSeconds = seconds;
      // Optimistic local update so cue list / NOW feel live while dragging.
      if (stateCache && stateCache.marks) {
        const m = stateCache.marks.find((x) => x.id === markDragging.id);
        if (m) {
          m.time_seconds = seconds;
          m.time_display = formatClock(seconds);
        }
      }
      drawWave(true);
      return;
    }
    if (!scrubbing) return;
    scrubPointerX = ev.clientX;
    const zone = updateScrubPlayhead(ev.clientX);
    if (zone.left || zone.right) startScrubEdgeLoop();
    else stopScrubEdgeLoop();
  });
  els.waveWrap.addEventListener("pointerup", async (ev) => {
    if (markPointer && markPointer.pointerId === ev.pointerId && !markDragging) {
      const tapId = markPointer.id;
      markPointer = null;
      // Tap: jump to mark time + select (Delete stays available).
      setSelectedMark(tapId);
      setWaveFollowSuspended(false);
      try {
        await command({ op: "seek_mark", mark_id: tapId });
      } catch (_) { /* ignore */ }
      drawWave(true);
      return;
    }
    if (markDragging && markDragging.pointerId === ev.pointerId) {
      const drag = markDragging;
      markDragging = null;
      markPointer = null;
      const seconds = Math.min(
        syncDur,
        Math.max(0, drag.liveSeconds != null ? Number(drag.liveSeconds) : timeFromClientX(ev.clientX)),
      );
      try {
        await command({ op: "move_mark", mark_id: drag.id, seconds });
        setSelectedMark(drag.id);
      } catch (err) {
        // Revert optimistic time on failure.
        if (stateCache && stateCache.marks) {
          const m = stateCache.marks.find((x) => x.id === drag.id);
          if (m) {
            m.time_seconds = drag.startSeconds;
            m.time_display = formatClock(drag.startSeconds);
          }
        }
        showToast(String(err.message || err));
      }
      setWaveFollowSuspended(false);
      scheduleWaveDetail();
      drawWave(true);
      return;
    }
    if (!scrubbing) return;
    const seconds = scrubbing.seconds != null ? Number(scrubbing.seconds) : timeFromClientX(ev.clientX);
    scrubbing = false;
    scrubPointerX = null;
    stopScrubEdgeLoop();
    setWaveFollowSuspended(false);
    try { await command({ op: "seek", seconds }); } catch (_) {}
    scheduleWaveDetail();
    drawWave(true);
  });
  els.waveWrap.addEventListener("pointercancel", () => {
    if (markDragging) {
      const drag = markDragging;
      markDragging = null;
      if (stateCache && stateCache.marks) {
        const m = stateCache.marks.find((x) => x.id === drag.id);
        if (m) {
          m.time_seconds = drag.startSeconds;
          m.time_display = formatClock(drag.startSeconds);
        }
      }
    }
    markPointer = null;
    scrubbing = false;
    scrubPointerX = null;
    stopScrubEdgeLoop();
    drawWave(true);
  });

  els.waveWrap.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const anchor = timeFromClientX(ev.clientX);
    zoomAt(ev.deltaY > 0 ? 1.2 : 0.8, anchor);
  }, { passive: false });

  els.waveWrap.addEventListener("touchstart", (ev) => {
    if (ev.touches.length === 2) {
      const a = ev.touches[0];
      const b = ev.touches[1];
      const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      const midX = (a.clientX + b.clientX) / 2;
      pinching = {
        dist: Math.max(1, dist),
        span: viewSpan(),
        // Time under the finger midpoint — keep this fixed while zooming.
        anchor: timeFromClientX(midX),
      };
      scrubbing = false;
      scrubPointerX = null;
      stopScrubEdgeLoop();
      setWaveFollowSuspended(true);
    }
  }, { passive: true });
  els.waveWrap.addEventListener("touchmove", (ev) => {
    if (!pinching || ev.touches.length !== 2) return;
    const a = ev.touches[0];
    const b = ev.touches[1];
    const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
    const midX = (a.clientX + b.clientX) / 2;
    const factor = pinching.dist / Math.max(1, dist);
    const next = Math.min(syncDur, Math.max(0.12, pinching.span * factor));
    const rect = els.waveWrap.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (midX - rect.left) / Math.max(1, rect.width)));
    // Keep the original pinch-mid time under the current finger midpoint.
    viewStart = pinching.anchor - next * ratio;
    viewEnd = viewStart + next;
    clampView();
    const span = viewSpan();
    if (span < syncDur - 1e-6) {
      const idealStart = pinching.anchor - span * ratio;
      if (idealStart >= 0 && idealStart + span <= syncDur + 1e-9) {
        viewStart = idealStart;
        viewEnd = idealStart + span;
      }
    }
    drawWave(true);
  }, { passive: true });
  els.waveWrap.addEventListener("touchend", (ev) => {
    if (ev.touches.length < 2 && pinching) {
      pinching = null;
      scheduleWaveDetail();
    }
  });
  els.waveWrap.addEventListener("touchcancel", () => {
    if (pinching) {
      pinching = null;
      scheduleWaveDetail();
    }
  });

  function layoutStacked() {
    return window.matchMedia("(max-width: 980px)").matches;
  }

  function applyLayoutCols() {
    if (!els.layout) return;
    els.layout.style.setProperty("--col-setlist", `${Math.round(colSetlist)}px`);
    els.layout.style.setProperty("--col-monitor", `${Math.round(colMonitor)}px`);
  }

  function loadLayoutCols() {
    try {
      const raw = localStorage.getItem(LAYOUT_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (Number(data.setlist) > 80) colSetlist = Number(data.setlist);
      if (Number(data.monitor) > 160) colMonitor = Number(data.monitor);
    } catch (_) { /* ignore */ }
  }

  function saveLayoutCols() {
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify({
        setlist: Math.round(colSetlist),
        monitor: Math.round(colMonitor),
      }));
    } catch (_) { /* ignore */ }
  }

  function bindSplitter(handle, which) {
    if (!handle) return;
    let drag = null;
    const onMove = (ev) => {
      if (!drag || layoutStacked()) return;
      const dx = ev.clientX - drag.startX;
      const total = els.layout.clientWidth;
      const minSet = 120;
      const minMon = 200;
      const minStage = 240;
      const splitW = 16;
      if (which === "setlist") {
        let next = drag.startSet + dx;
        const maxSet = total - colMonitor - minStage - splitW;
        next = Math.max(minSet, Math.min(maxSet, next));
        colSetlist = next;
      } else {
        let next = drag.startMon - dx;
        const maxMon = total - colSetlist - minStage - splitW;
        next = Math.max(minMon, Math.min(maxMon, next));
        colMonitor = next;
      }
      applyLayoutCols();
      drawWave(true);
    };
    const onUp = () => {
      if (!drag) return;
      drag = null;
      handle.classList.remove("active");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      saveLayoutCols();
      drawWave(true);
    };
    handle.addEventListener("pointerdown", (ev) => {
      if (layoutStacked()) return;
      ev.preventDefault();
      drag = { startX: ev.clientX, startSet: colSetlist, startMon: colMonitor };
      handle.classList.add("active");
      handle.setPointerCapture?.(ev.pointerId);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    });
  }

  loadLayoutCols();
  applyLayoutCols();
  bindSplitter(els.splitSetlist, "setlist");
  bindSplitter(els.splitMonitor, "monitor");

  if (els.confirmYes) {
    els.confirmYes.addEventListener("click", (ev) => {
      ev.preventDefault();
      els.confirmDialog.close("ok");
    });
  }
  if (els.confirmNo) {
    els.confirmNo.addEventListener("click", (ev) => {
      ev.preventDefault();
      els.confirmDialog.close("cancel");
    });
  }
  if (els.cueActionCancel) {
    els.cueActionCancel.addEventListener("click", (ev) => {
      ev.preventDefault();
      els.cueActionDialog.close("cancel");
    });
  }

  els.cueList.addEventListener("scroll", () => {
    clearCueLongPress(els.cueList.querySelector(".cue-item.pressing"));
    if (ignoreCueScroll || cueUserScrolling) return;
    cueUserScrolling = true;
    setCueFollowSuspended(true);
    requestAnimationFrame(() => {
      const current = els.cueList.querySelector(".cue-item.current");
      if (current && !cueRowVisible(current)) cueFollowLeftViewport = true;
      else if (current && cueRowVisible(current) && cueFollowLeftViewport) {
        setCueFollowSuspended(false);
        cueFollowLeftViewport = false;
      }
      cueUserScrolling = false;
    });
  }, { passive: true });

  if (els.cueFollowBtn) {
    els.cueFollowBtn.addEventListener("click", () => {
      setCueFollowSuspended(false);
      cueFollowLeftViewport = false;
      updateCueFollow(livePosition(), true);
    });
  }

  if (els.dispBtn) {
    els.dispBtn.addEventListener("click", openDisp);
  }
  if (els.listenBtn) {
    updateListenBtn();
    els.listenBtn.addEventListener("click", () => {
      setListenOn(!listenOn);
    });
  }
  if (els.previewBtn) {
    updatePreviewBtn();
    els.previewBtn.addEventListener("click", () => {
      setPreviewOn(!previewOn);
    });
  }
  if (els.mutePcBtn) {
    updateMutePcBtn();
    els.mutePcBtn.addEventListener("click", () => {
      setPcMute(!pcMuted)
        .then((muted) => showToast(muted ? "PC music muted" : "PC music unmuted"))
        .catch((e) => showToast(String(e.message || e)));
    });
  }
  if (els.dispClose) {
    els.dispClose.addEventListener("click", () => els.dispDialog.close());
  }
  const dispBindings = [
    [els.dispPrimary, "primary"],
    [els.dispSecondary, "secondary"],
    [els.dispTimecode, "timecode"],
    [els.dispToggles, "toggles"],
  ];
  for (const [input, key] of dispBindings) {
    if (!input) continue;
    input.addEventListener("change", () => saveDispField(key, input.checked));
  }

  els.markMgrBtn.addEventListener("click", () => {
    lastMgrLanesSig = "";
    renderMarkManager((stateCache && stateCache.lanes) || []);
    if (els.markMgrDialog.showModal) els.markMgrDialog.showModal();
  });
  els.markMgrClose.addEventListener("click", () => {
    els.markMgrDialog.close();
    lastMgrLanesSig = "";
  });

  els.authBtn.addEventListener("click", openAuth);
  els.savePassword.addEventListener("click", (ev) => {
    ev.preventDefault();
    token = els.passwordInput.value || "";
    localStorage.setItem(TOKEN_KEY, token);
    els.authDialog.close();
    showToast(token ? "Password saved" : "Password cleared");
  });

  if (els.noteSave) {
    els.noteSave.addEventListener("click", (ev) => {
      ev.preventDefault();
      if (els.noteDialog) {
        els.noteDialog.close("ok");
      }
    });
  }
  if (els.noteCancel) {
    els.noteCancel.addEventListener("click", (ev) => {
      ev.preventDefault();
      if (els.noteDialog) {
        els.noteDialog.close("cancel");
      }
    });
  }
  if (els.noteInput) {
    els.noteInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        if (els.noteDialog) els.noteDialog.close("ok");
      }
    });
  }

  window.addEventListener("keydown", (ev) => {
    if (ev.repeat) return;
    const t = ev.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
    if (els.noteDialog && els.noteDialog.open) return;
    if (ev.code === "Space") {
      ev.preventDefault();
      command({ op: "toggle" }).catch(() => {});
      return;
    }
    if (ev.key >= "1" && ev.key <= "9") {
      const lane = ((stateCache && stateCache.lanes) || []).find((l) => l.shortcut === ev.key);
      placeMark({ shortcut: ev.key }, lane).catch(() => {});
    }
  });

  window.addEventListener("resize", () => drawWave(true));

  // iPad Safari: suppress long-press callout / text selection chrome,
  // and block accidental double-tap page zoom outside text fields.
  document.addEventListener("contextmenu", (ev) => {
    const t = ev.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
    ev.preventDefault();
  });
  document.addEventListener("selectstart", (ev) => {
    const t = ev.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
    ev.preventDefault();
  });
  let lastTouchEnd = 0;
  document.addEventListener("touchend", (ev) => {
    const t = ev.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
    const now = Date.now();
    if (now - lastTouchEnd < 320) {
      ev.preventDefault();
    }
    lastTouchEnd = now;
  }, { passive: false });
  document.addEventListener("gesturestart", (ev) => ev.preventDefault());
  document.addEventListener("gesturechange", (ev) => ev.preventDefault());
  document.addEventListener("gestureend", (ev) => ev.preventDefault());

  requestAnimationFrame(tickFrame);
  pollState();
  pollClock();
})();

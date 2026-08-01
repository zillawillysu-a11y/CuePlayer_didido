(() => {
  const TOKEN_KEY = "cueplayer_web_remote_token";

  const els = {
    projectName: document.getElementById("projectName"),
    songTitle: document.getElementById("songTitle"),
    clock: document.getElementById("clock"),
    duration: document.getElementById("duration"),
    timecode: document.getElementById("timecode"),
    nowPrimary: document.getElementById("nowPrimary"),
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
    toast: document.getElementById("toast"),
    authBtn: document.getElementById("authBtn"),
    authDialog: document.getElementById("authDialog"),
    passwordInput: document.getElementById("passwordInput"),
    savePassword: document.getElementById("savePassword"),
  };

  let token = localStorage.getItem(TOKEN_KEY) || "";
  let scrubbing = false;
  let lastMarksSig = "";
  let lastSongsSig = "";
  let lastLanesSig = "";
  let failCount = 0;
  let lastSongId = "";
  let wave = null;
  let waveLoading = false;
  let stateCache = null;
  let playheadColor = "#3dd68c";
  let waveColor = "#616161";

  // Smooth local playhead (rAF) — corrected by /api/clock + /api/state.
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
  let rafId = 0;
  let lastWaveDrawMs = 0;

  function headers(json) {
    const h = {};
    if (json) h["Content-Type"] = "application/json";
    if (token) {
      h["Authorization"] = `Bearer ${token}`;
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
    if (!res.ok) {
      throw new Error(data.error || `http_${res.status}`);
    }
    return data;
  }

  function showToast(msg) {
    els.toast.hidden = false;
    els.toast.textContent = msg;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => {
      els.toast.hidden = true;
    }, 2200);
  }

  function openAuth() {
    els.passwordInput.value = token;
    if (typeof els.authDialog.showModal === "function") {
      els.authDialog.showModal();
    }
  }

  function formatClock(seconds) {
    const totalCs = Math.max(0, Math.round(Number(seconds) * 100));
    const hours = Math.floor(totalCs / 360000);
    const minutes = Math.floor((totalCs % 360000) / 6000);
    const secs = Math.floor((totalCs % 6000) / 100);
    const cs = totalCs % 100;
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(hours)}:${pad(minutes)}:${pad(secs)}.${pad(cs)}`;
  }

  function livePosition() {
    if (scrubbing && scrubbing.seconds != null) return scrubbing.seconds;
    if (!syncPlaying) return syncPos;
    const elapsed = (performance.now() - syncEpochMs) / 1000;
    return Math.min(syncDur, Math.max(0, syncPos + elapsed));
  }

  function syncFromServer(position, duration, playing, songId) {
    const nextPlaying = Boolean(playing);
    const nextPos = Math.max(0, Number(position) || 0);
    const nextDur = Math.max(0.1, Number(duration) || 0.1);
    const songChanged = songId && songId !== syncSongId;
    if (songChanged) {
      syncSongId = songId;
      cueFollowSuspended = false;
      cueFollowLeftViewport = false;
      lastPlayheadCueId = "";
    }
    // Large seek jump → snap + resume cue follow.
    if (Math.abs(nextPos - livePosition()) > 0.45) {
      cueFollowSuspended = false;
      cueFollowLeftViewport = false;
    }
    syncPlaying = nextPlaying;
    syncPos = nextPos;
    syncDur = nextDur;
    syncEpochMs = performance.now();
  }

  function formatNow(items) {
    if (!items || !items.length) return "—";
    return items
      .map((m) => {
        const bits = [];
        if (m.main_cue_id) bits.push(`Cue ${m.main_cue_id}`);
        bits.push(m.lane_name || "");
        if (m.display_name) bits.push(m.display_name);
        return bits.filter(Boolean).join(" · ");
      })
      .join("\n");
  }

  function renderSongs(songs) {
    const sig = JSON.stringify(songs.map((s) => [s.id, s.name, s.active, s.setlist_number]));
    if (sig === lastSongsSig) return;
    lastSongsSig = sig;
    els.songList.innerHTML = "";
    if (!songs.length) {
      els.songList.textContent = "Empty setlist";
      return;
    }
    for (const s of songs) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "song-item" + (s.active ? " active" : "");
      btn.innerHTML = `<span class="num">${Number(s.setlist_number)}</span><span class="name"></span>`;
      btn.querySelector(".name").textContent = s.name;
      btn.addEventListener("click", () => {
        command({ op: "select_song", index: s.index }).catch(() => {});
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
    const sig = JSON.stringify(
      marks.map((m) => [m.id, m.display_name, m.main_cue_id, m.time_display || m.time_seconds, m.color])
    );
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
      btn.dataset.time = String(m.time_seconds);
      const time = m.time_display || formatClock(m.time_seconds);
      const cue = m.main_cue_id ? `Cue ${m.main_cue_id}` : "";
      btn.innerHTML =
        `<span class="meta"></span>` +
        `<span class="lane"></span>` +
        `<span class="note"></span>`;
      btn.querySelector(".meta").textContent = time;
      btn.querySelector(".lane").textContent = [cue, m.lane_name].filter(Boolean).join(" · ");
      btn.querySelector(".note").textContent = m.display_name || "(no note)";
      btn.style.borderLeft = `3px solid ${m.color || "#444"}`;
      btn.addEventListener("click", () => {
        command({ op: "seek_mark", mark_id: m.id }).catch(() => {});
      });
      els.cueList.appendChild(btn);
    }
    lastPlayheadCueId = "";
    updateCueFollow(livePosition(), true);
  }

  function cueRowVisible(el) {
    const list = els.cueList;
    const top = el.offsetTop;
    const bottom = top + el.offsetHeight;
    const viewTop = list.scrollTop;
    const viewBottom = viewTop + list.clientHeight;
    return bottom > viewTop && top < viewBottom;
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
        cueFollowSuspended = false;
        cueFollowLeftViewport = false;
      } else if (!cueRowVisible(currentEl)) {
        cueFollowLeftViewport = true;
      }
    }
    const changed = id !== lastPlayheadCueId;
    lastPlayheadCueId = id;
    if (!cueFollowSuspended && (changed || forceScroll)) {
      currentEl.scrollIntoView({ block: "nearest", behavior: changed ? "smooth" : "auto" });
    }
  }

  function renderMarkButtons(lanes) {
    const usable = (lanes || []).filter((l) => l.shortcut && l.shortcut >= "1" && l.shortcut <= "9");
    const sig = JSON.stringify(usable.map((l) => [l.index, l.shortcut, l.name, l.visible, l.locked, l.color]));
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
          command({ op: "add_mark", shortcut: key })
            .then(() => showToast(`Marked ${lane.name}`))
            .catch((e) => showToast(String(e.message || e)));
        });
      }
      els.markButtons.appendChild(btn);
    }
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
    if (!force && !scrubbing && now - lastWaveDrawMs < 32) return;
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

    const ready = wave && wave.ready && wave.mins && wave.mins.length;
    els.waveEmpty.classList.toggle("hidden", Boolean(ready));
    if (!ready) return;

    const mid = h * 0.5;
    const amp = h * 0.42;
    const n = wave.mins.length;
    ctx.fillStyle = waveColor || "#616161";
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const x0 = (i / n) * w;
      const x1 = ((i + 1) / n) * w;
      const yMax = mid - Number(wave.maxs[i]) * amp;
      const yMin = mid - Number(wave.mins[i]) * amp;
      const top = Math.min(yMax, yMin);
      const bot = Math.max(yMax, yMin);
      ctx.rect(x0, top, Math.max(1, x1 - x0), Math.max(1, bot - top));
    }
    ctx.fill();

    const marks = (stateCache && stateCache.marks) || [];
    const dur = Math.max(0.1, syncDur || Number((stateCache && stateCache.duration) || wave.duration || 1));
    for (const m of marks) {
      const x = (Number(m.time_seconds) / dur) * w;
      ctx.strokeStyle = m.color || "#888";
      ctx.globalAlpha = 0.85;
      ctx.lineWidth = Math.max(1, w / 900);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    let ratio = null;
    if (scrubbing && scrubbing.ratio != null) ratio = scrubbing.ratio;
    else ratio = livePosition() / dur;
    if (ratio != null) {
      const x = Math.min(w - 1, Math.max(0, ratio * w));
      ctx.strokeStyle = playheadColor || "#3dd68c";
      ctx.lineWidth = Math.max(2, w / 450);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
  }

  function tickFrame() {
    const pos = livePosition();
    const clock = formatClock(pos);
    if (clock !== lastDrawnClock) {
      lastDrawnClock = clock;
      els.clock.textContent = clock;
    }
    updateCueFollow(pos, false);
    if (syncPlaying || scrubbing) drawWave(false);
    rafId = requestAnimationFrame(tickFrame);
  }

  async function ensureWaveform(songId) {
    if (!songId) {
      wave = null;
      drawWave(true);
      return;
    }
    if (wave && wave.song_id === songId && wave.ready) return;
    if (waveLoading) return;
    waveLoading = true;
    try {
      const data = await api("/api/waveform");
      wave = data;
      if (!data.ready) {
        setTimeout(() => {
          if (lastSongId === songId) {
            wave = null;
            ensureWaveform(songId);
          }
        }, 1200);
      }
      drawWave(true);
    } catch (_) {
      /* keep previous */
    } finally {
      waveLoading = false;
    }
  }

  function applyState(state) {
    stateCache = state;
    els.projectName.textContent = state.project_name || "—";
    const song = state.song || {};
    els.songTitle.textContent = song.in_setlist === false || song.index < 0
      ? "(no song)"
      : song.name || "—";
    syncFromServer(state.position, state.duration, state.playing, song.id || "");
    els.duration.textContent = `/ ${state.duration_clock || formatClock(state.duration)}`;
    els.timecode.textContent = state.timecode || "—";
    els.nowPrimary.textContent = formatNow(state.now && state.now.primary);
    els.nowSecondary.textContent = formatNow(state.now && state.now.secondary);
    playheadColor = state.playhead_color || "#3dd68c";
    waveColor = state.waveform_color || "#616161";

    const playing = Boolean(state.playing);
    els.playBtn.disabled = playing;
    els.pauseBtn.disabled = !playing;
    els.playBtn.classList.toggle("active", false);
    els.pauseBtn.classList.toggle("active", playing);

    const songId = song.id || "";
    if (songId !== lastSongId) {
      lastSongId = songId;
      wave = null;
      ensureWaveform(songId);
    } else if (!wave || !wave.ready) {
      ensureWaveform(songId);
    }

    renderSongs(state.songs || []);
    renderCues(cueListMarks(state));
    renderMarkButtons(state.lanes || []);
    drawWave(true);
  }

  async function command(body) {
    const result = await api("/api/command", { method: "POST", body: JSON.stringify(body) });
    // Optimistic local sync for transport so the clock does not wait for poll.
    if (body.op === "play") {
      syncPlaying = true;
      syncEpochMs = performance.now();
      els.playBtn.disabled = true;
      els.pauseBtn.disabled = false;
      els.pauseBtn.classList.add("active");
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
      cueFollowSuspended = false;
    } else if (body.op === "seek" && body.seconds != null) {
      syncPos = Number(body.seconds);
      syncEpochMs = performance.now();
      cueFollowSuspended = false;
    } else if (body.op === "seek_mark") {
      cueFollowSuspended = false;
    } else if (body.op === "toggle") {
      if (syncPlaying) {
        syncPos = livePosition();
        syncPlaying = false;
      } else {
        syncPlaying = true;
      }
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
      if (token !== undefined) {
        const clock = await api("/api/clock");
        if (clock && clock.ok !== false) {
          if (clock.song_id && lastSongId && clock.song_id !== lastSongId) {
            // Full state will catch song switch.
          } else {
            syncFromServer(clock.position, clock.duration, clock.playing, clock.song_id || syncSongId);
            const playing = Boolean(clock.playing);
            els.playBtn.disabled = playing;
            els.pauseBtn.disabled = !playing;
            els.pauseBtn.classList.toggle("active", playing);
          }
        }
      }
    } catch (_) {
      /* full state poll handles errors */
    } finally {
      setTimeout(pollClock, syncPlaying ? 100 : 400);
    }
  }

  function seekFromClientX(clientX) {
    const rect = els.waveWrap.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)));
    const dur = Math.max(0, syncDur);
    return { seconds: ratio * dur, x: clientX - rect.left, ratio };
  }

  els.playBtn.addEventListener("click", () => {
    command({ op: "play" }).catch(() => {});
  });
  els.pauseBtn.addEventListener("click", () => {
    command({ op: "pause" }).catch(() => {});
  });
  els.stopBtn.addEventListener("click", () => {
    command({ op: "stop" }).catch(() => {});
  });
  els.prevSong.addEventListener("click", () => {
    command({ op: "prev_song" }).catch(() => {});
  });
  els.nextSong.addEventListener("click", () => {
    command({ op: "next_song" }).catch(() => {});
  });

  function onWavePointerDown(ev) {
    scrubbing = seekFromClientX(ev.clientX);
    els.waveWrap.setPointerCapture(ev.pointerId);
    drawWave(true);
  }
  function onWavePointerMove(ev) {
    if (!scrubbing) return;
    scrubbing = seekFromClientX(ev.clientX);
    drawWave(true);
  }
  async function onWavePointerUp(ev) {
    if (!scrubbing) return;
    const target = seekFromClientX(ev.clientX);
    scrubbing = false;
    try {
      await command({ op: "seek", seconds: target.seconds });
    } catch (_) {}
    drawWave(true);
  }
  els.waveWrap.addEventListener("pointerdown", onWavePointerDown);
  els.waveWrap.addEventListener("pointermove", onWavePointerMove);
  els.waveWrap.addEventListener("pointerup", onWavePointerUp);
  els.waveWrap.addEventListener("pointercancel", () => {
    scrubbing = false;
    drawWave(true);
  });

  els.cueList.addEventListener(
    "scroll",
    () => {
      if (cueUserScrolling) return;
      cueUserScrolling = true;
      cueFollowSuspended = true;
      requestAnimationFrame(() => {
        const current = els.cueList.querySelector(".cue-item.current");
        if (current && !cueRowVisible(current)) cueFollowLeftViewport = true;
        else if (current && cueRowVisible(current) && cueFollowLeftViewport) {
          cueFollowSuspended = false;
          cueFollowLeftViewport = false;
        }
        cueUserScrolling = false;
      });
    },
    { passive: true }
  );

  els.authBtn.addEventListener("click", openAuth);
  els.savePassword.addEventListener("click", (ev) => {
    ev.preventDefault();
    token = els.passwordInput.value || "";
    localStorage.setItem(TOKEN_KEY, token);
    els.authDialog.close();
    showToast(token ? "Password saved" : "Password cleared");
  });

  window.addEventListener("keydown", (ev) => {
    if (ev.repeat) return;
    const t = ev.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
    if (ev.code === "Space") {
      ev.preventDefault();
      command({ op: "toggle" }).catch(() => {});
      return;
    }
    if (ev.key >= "1" && ev.key <= "9") {
      command({ op: "add_mark", shortcut: ev.key })
        .then(() => showToast(`Marked ${ev.key}`))
        .catch(() => {});
    }
  });

  window.addEventListener("resize", () => drawWave(true));
  rafId = requestAnimationFrame(tickFrame);
  pollState();
  pollClock();
})();

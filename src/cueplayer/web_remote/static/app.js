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
    markMgrBtn: document.getElementById("markMgrBtn"),
    markMgrDialog: document.getElementById("markMgrDialog"),
    markMgrClose: document.getElementById("markMgrClose"),
    markMgrBody: document.getElementById("markMgrBody"),
  };

  let token = localStorage.getItem(TOKEN_KEY) || "";
  let scrubbing = false;
  let lastSetlistSig = "";
  let lastMarksSig = "";
  let lastLanesSig = "";
  let failCount = 0;
  let lastSongId = "";
  let wave = null;
  let waveLoading = false;
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
  let lastWaveDrawMs = 0;

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

  function livePosition() {
    if (scrubbing && scrubbing.seconds != null) return scrubbing.seconds;
    if (!syncPlaying) return syncPos;
    const elapsed = (performance.now() - syncEpochMs) / 1000;
    return Math.min(syncDur, Math.max(0, syncPos + elapsed));
  }

  function syncFromServer(position, duration, playing, songId) {
    const nextPos = Math.max(0, Number(position) || 0);
    const nextDur = Math.max(0.1, Number(duration) || 0.1);
    const songChanged = songId && songId !== syncSongId;
    if (songChanged) {
      syncSongId = songId;
      cueFollowSuspended = false;
      cueFollowLeftViewport = false;
      lastPlayheadCueId = "";
      viewStart = 0;
      viewEnd = nextDur;
    }
    if (Math.abs(nextPos - livePosition()) > 0.45) {
      cueFollowSuspended = false;
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
  }

  function formatNowBody(items) {
    if (!items || !items.length) return "—";
    return items.map((m) => {
      const bits = [];
      bits.push(m.lane_name || "");
      if (m.main_cue_id) bits.push(`Cue ${m.main_cue_id}`);
      if (m.display_name) bits.push(m.display_name);
      return bits.filter(Boolean).join(" · ");
    }).join("\n");
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
      btn.innerHTML = `<span class="num"></span><span class="name"></span>`;
      btn.querySelector(".num").textContent = Number(row.setlist_number);
      btn.querySelector(".name").textContent = row.name;
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
    const sig = JSON.stringify(marks.map((m) => [m.id, m.display_name, m.main_cue_id, m.time_display, m.color, m.lane_name]));
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
      btn.querySelector(".cue-id").textContent = m.main_cue_id || "";
      btn.querySelector(".note").textContent = m.display_name || "";
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
      // nearest keeps the page from jumping; only the cue list scrolls.
      currentEl.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "auto" });
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

  function renderToggles(toggles) {
    const map = toggles || {};
    for (const chip of els.toggles.querySelectorAll(".chip")) {
      const key = chip.dataset.key;
      chip.classList.toggle("on", Boolean(map[key]));
    }
  }

  function renderMarkManager(lanes) {
    els.markMgrBody.innerHTML = "";
    for (const lane of lanes || []) {
      const row = document.createElement("div");
      row.className = "mgr-row";
      row.innerHTML =
        `<span class="mgr-swatch"></span>` +
        `<input type="text" class="mgr-name" />` +
        `<label><input type="checkbox" class="mgr-vis" /> Eye</label>` +
        `<select class="mgr-now"><option value="off">Off</option><option value="primary">Primary</option><option value="secondary">Secondary</option></select>` +
        `<select class="mgr-key"><option value="">—</option>${[1,2,3,4,5,6,7,8,9].map((n) => `<option value="${n}">${n}</option>`).join("")}</select>`;
      row.querySelector(".mgr-swatch").style.background = lane.color || "#666";
      const name = row.querySelector(".mgr-name");
      name.value = lane.name || "";
      const vis = row.querySelector(".mgr-vis");
      vis.checked = Boolean(lane.visible);
      const now = row.querySelector(".mgr-now");
      now.value = lane.now || "off";
      const key = row.querySelector(".mgr-key");
      key.value = lane.shortcut || "";

      const save = () => {
        command({
          op: "update_lane",
          lane_index: lane.index,
          name: name.value,
          visible: vis.checked,
          now: now.value,
          shortcut: key.value,
        }).catch((e) => showToast(String(e.message || e)));
      };
      name.addEventListener("change", save);
      vis.addEventListener("change", save);
      now.addEventListener("change", save);
      key.addEventListener("change", save);
      els.markMgrBody.appendChild(row);
    }
  }

  function viewSpan() {
    return Math.max(0.05, viewEnd - viewStart);
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
    const next = Math.min(syncDur, Math.max(0.5, span * factor));
    const anchor = anchorSec == null ? (viewStart + viewEnd) / 2 : anchorSec;
    const ratio = span > 1e-6 ? (anchor - viewStart) / span : 0.5;
    viewStart = anchor - next * ratio;
    viewEnd = viewStart + next;
    clampView();
    drawWave(true);
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

    const ready = wave && wave.ready && wave.mins && wave.mins.length;
    els.waveEmpty.classList.toggle("hidden", Boolean(ready));
    els.waveRange.textContent = `${formatClock(viewStart)} – ${formatClock(viewEnd)}`;
    if (!ready) return;

    const mid = h * 0.5;
    const amp = h * 0.42;
    const n = wave.mins.length;
    const dur = Math.max(0.1, Number(wave.duration) || syncDur);
    const v0 = viewStart;
    const v1 = Math.max(v0 + 0.05, viewEnd);
    const i0 = Math.max(0, Math.floor((v0 / dur) * n));
    const i1 = Math.min(n, Math.ceil((v1 / dur) * n));

    ctx.fillStyle = waveColor || "#616161";
    ctx.beginPath();
    for (let i = i0; i < i1; i++) {
      const t0 = (i / n) * dur;
      const t1 = ((i + 1) / n) * dur;
      const x0 = ((t0 - v0) / (v1 - v0)) * w;
      const x1 = ((t1 - v0) / (v1 - v0)) * w;
      const yMax = mid - Number(wave.maxs[i]) * amp;
      const yMin = mid - Number(wave.mins[i]) * amp;
      const top = Math.min(yMax, yMin);
      const bot = Math.max(yMax, yMin);
      ctx.rect(x0, top, Math.max(1, x1 - x0), Math.max(1, bot - top));
    }
    ctx.fill();

    const marks = (stateCache && stateCache.marks) || [];
    for (const m of marks) {
      const t = Number(m.time_seconds);
      if (t < v0 || t > v1) continue;
      const x = ((t - v0) / (v1 - v0)) * w;
      ctx.strokeStyle = m.color || "#888";
      ctx.globalAlpha = 0.9;
      ctx.lineWidth = Math.max(1, w / 900);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    let pos = livePosition();
    if (scrubbing && scrubbing.seconds != null) pos = scrubbing.seconds;
    if (pos >= v0 && pos <= v1) {
      const x = ((pos - v0) / (v1 - v0)) * w;
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
    if (syncPlaying || scrubbing || panning) drawWave(false);
    requestAnimationFrame(tickFrame);
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
      /* keep */
    } finally {
      waveLoading = false;
    }
  }

  function applyState(state) {
    stateCache = state;
    const song = state.song || {};
    els.songTitle.textContent = song.in_setlist === false || song.index < 0 ? "(no song)" : (song.name || "—");
    syncFromServer(state.position, state.duration, state.playing, song.id || "");
    els.duration.textContent = `/ ${state.duration_clock || formatClock(state.duration)}`;
    els.tcStatus.textContent = state.tc_status || "TC off";
    els.timecode.textContent = state.timecode || "—";
    tcAccent = state.tc_accent || state.playhead_color || "#3dd68c";
    document.documentElement.style.setProperty("--ok", tcAccent);
    els.timecode.style.color = tcAccent;
    playheadColor = state.playhead_color || "#3dd68c";
    waveColor = state.waveform_color || "#616161";

    const primary = (state.now && state.now.primary) || [];
    const secondary = (state.now && state.now.secondary) || [];
    els.nowPrimaryLabel.textContent = primary[0] ? `PRIMARY · ${primary[0].lane_name}` : "PRIMARY";
    els.nowPrimary.textContent = formatNowBody(primary);
    els.nowSecondaryLabel.textContent = secondary[0] ? `SECONDARY · ${secondary[0].lane_name}` : "SECONDARY";
    els.nowSecondary.textContent = formatNowBody(secondary);

    renderToggles(state.output_toggles);
    const playing = Boolean(state.playing);
    els.playBtn.disabled = playing;
    els.pauseBtn.disabled = !playing;
    els.pauseBtn.classList.toggle("active", playing);

    const songId = song.id || "";
    if (songId !== lastSongId) {
      lastSongId = songId;
      wave = null;
      ensureWaveform(songId);
    } else if (!wave || !wave.ready) {
      ensureWaveform(songId);
    }

    renderSetlist(state.setlist || []);
    renderCues(cueListMarks(state));
    renderMarkButtons(state.lanes || []);
    if (els.markMgrDialog.open) renderMarkManager(state.lanes || []);
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
    } else if (body.op === "seek_mark" || body.op === "toggle_folder" || body.op === "update_lane" || body.op === "set_output_toggle") {
      // Full state poll will refresh; nudge a quick refresh.
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
        const playing = Boolean(clock.playing);
        els.playBtn.disabled = playing;
        els.pauseBtn.disabled = !playing;
        els.pauseBtn.classList.toggle("active", playing);
      }
    } catch (_) {
      /* ignore */
    } finally {
      setTimeout(pollClock, syncPlaying ? 100 : 400);
    }
  }

  function timeFromClientX(clientX) {
    const rect = els.waveWrap.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)));
    return viewStart + ratio * viewSpan();
  }

  els.playBtn.addEventListener("click", () => command({ op: "play" }).catch(() => {}));
  els.pauseBtn.addEventListener("click", () => command({ op: "pause" }).catch(() => {}));
  els.stopBtn.addEventListener("click", () => command({ op: "stop" }).catch(() => {}));
  els.prevSong.addEventListener("click", () => command({ op: "prev_song" }).catch(() => {}));
  els.nextSong.addEventListener("click", () => command({ op: "next_song" }).catch(() => {}));
  els.zoomIn.addEventListener("click", () => zoomAt(0.7, livePosition()));
  els.zoomOut.addEventListener("click", () => zoomAt(1.4, livePosition()));
  els.zoomFit.addEventListener("click", () => {
    viewStart = 0;
    viewEnd = syncDur;
    drawWave(true);
  });

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

  els.waveWrap.addEventListener("pointerdown", (ev) => {
    if (ev.pointerType === "touch" && els.waveWrap.hasPointerCapture?.(ev.pointerId)) return;
    scrubbing = { seconds: timeFromClientX(ev.clientX) };
    panning = null;
    els.waveWrap.setPointerCapture(ev.pointerId);
    drawWave(true);
  });
  els.waveWrap.addEventListener("pointermove", (ev) => {
    if (scrubbing) {
      scrubbing = { seconds: timeFromClientX(ev.clientX) };
      drawWave(true);
    }
  });
  els.waveWrap.addEventListener("pointerup", async (ev) => {
    if (!scrubbing) return;
    const seconds = timeFromClientX(ev.clientX);
    scrubbing = false;
    try { await command({ op: "seek", seconds }); } catch (_) {}
    drawWave(true);
  });
  els.waveWrap.addEventListener("pointercancel", () => {
    scrubbing = false;
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
      pinching = { dist, span: viewSpan(), mid: (viewStart + viewEnd) / 2 };
      scrubbing = false;
    }
  }, { passive: true });
  els.waveWrap.addEventListener("touchmove", (ev) => {
    if (!pinching || ev.touches.length !== 2) return;
    const a = ev.touches[0];
    const b = ev.touches[1];
    const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
    if (pinching.dist < 1) return;
    const factor = pinching.dist / Math.max(1, dist);
    const next = Math.min(syncDur, Math.max(0.5, pinching.span * factor));
    viewStart = pinching.mid - next / 2;
    viewEnd = pinching.mid + next / 2;
    clampView();
    drawWave(true);
  }, { passive: true });
  els.waveWrap.addEventListener("touchend", () => { pinching = null; });

  els.cueList.addEventListener("scroll", () => {
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
  }, { passive: true });

  els.markMgrBtn.addEventListener("click", () => {
    renderMarkManager((stateCache && stateCache.lanes) || []);
    if (els.markMgrDialog.showModal) els.markMgrDialog.showModal();
  });
  els.markMgrClose.addEventListener("click", () => els.markMgrDialog.close());

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
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
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
  requestAnimationFrame(tickFrame);
  pollState();
  pollClock();
})();

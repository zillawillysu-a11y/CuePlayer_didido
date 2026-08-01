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
  let pollMs = 250;
  let failCount = 0;
  let lastSongId = "";
  let wave = null;
  let waveLoading = false;
  let stateCache = null;
  let playheadColor = "#3dd68c";
  let waveColor = "#616161";

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

  function renderCues(marks) {
    const sig = JSON.stringify(
      marks.map((m) => [m.id, m.display_name, m.main_cue_id, m.time_display || m.time_seconds])
    );
    if (sig === lastMarksSig) return;
    lastMarksSig = sig;
    els.cueList.innerHTML = "";
    if (!marks.length) {
      els.cueList.textContent = "No marks";
      return;
    }
    for (const m of marks) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cue-item";
      const time = m.time_display || "00:00:00.00";
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
    }
  }

  function drawWave() {
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

    // Mark tick lines + playhead share song duration.
    const marks = (stateCache && stateCache.marks) || [];
    const dur = Math.max(0.1, Number((stateCache && stateCache.duration) || wave.duration || 1));
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
    if (scrubbing && scrubbing.ratio != null) {
      ratio = scrubbing.ratio;
    } else if (stateCache) {
      ratio = Math.max(0, Number(stateCache.position) || 0) / dur;
    }
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

  async function ensureWaveform(songId) {
    if (!songId) {
      wave = null;
      drawWave();
      return;
    }
    if (wave && wave.song_id === songId && wave.ready) return;
    if (waveLoading) return;
    waveLoading = true;
    try {
      const data = await api("/api/waveform");
      wave = data;
      if (!data.ready) {
        // Audio may still be loading on the PC — retry shortly.
        setTimeout(() => {
          if (lastSongId === songId) {
            wave = null;
            ensureWaveform(songId);
          }
        }, 1200);
      }
      drawWave();
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
    els.clock.textContent = state.clock || "00:00:00.00";
    els.duration.textContent = `/ ${state.duration_clock || "00:00:00.00"}`;
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
    renderCues(state.marks || []);
    renderMarkButtons(state.lanes || []);
    drawWave();
  }

  async function command(body) {
    return api("/api/command", { method: "POST", body: JSON.stringify(body) });
  }

  async function poll() {
    try {
      const state = await api("/api/state");
      failCount = 0;
      pollMs = 250;
      applyState(state);
    } catch (err) {
      failCount += 1;
      pollMs = Math.min(2000, 250 * failCount);
      if (failCount === 1 || failCount % 8 === 0) {
        showToast(err.message === "unauthorized" ? "Password required" : "Waiting for CuePlayer…");
      }
    } finally {
      setTimeout(poll, pollMs);
    }
  }

  function seekFromClientX(clientX) {
    const rect = els.waveWrap.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)));
    const dur = Math.max(0, Number((stateCache && stateCache.duration) || (wave && wave.duration) || 0));
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
    drawWave();
  }
  function onWavePointerMove(ev) {
    if (!scrubbing) return;
    scrubbing = seekFromClientX(ev.clientX);
    drawWave();
  }
  async function onWavePointerUp(ev) {
    if (!scrubbing) return;
    const target = seekFromClientX(ev.clientX);
    scrubbing = false;
    try {
      await command({ op: "seek", seconds: target.seconds });
    } catch (_) {}
    drawWave();
  }
  els.waveWrap.addEventListener("pointerdown", onWavePointerDown);
  els.waveWrap.addEventListener("pointermove", onWavePointerMove);
  els.waveWrap.addEventListener("pointerup", onWavePointerUp);
  els.waveWrap.addEventListener("pointercancel", () => {
    scrubbing = false;
    drawWave();
  });

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

  window.addEventListener("resize", () => drawWave());
  poll();
})();

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
    stopBtn: document.getElementById("stopBtn"),
    prevSong: document.getElementById("prevSong"),
    nextSong: document.getElementById("nextSong"),
    seekBar: document.getElementById("seekBar"),
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
    const sig = JSON.stringify(marks.map((m) => [m.id, m.display_name, m.main_cue_id, m.time_seconds]));
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
      const cue = m.main_cue_id ? `Cue ${m.main_cue_id} · ` : "";
      btn.innerHTML = `<span class="meta"></span><span class="note"></span>`;
      btn.querySelector(".meta").textContent = `${cue}${m.lane_name} @ ${m.time_seconds.toFixed(2)}s`;
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

  function applyState(state) {
    els.projectName.textContent = state.project_name || "—";
    const song = state.song || {};
    els.songTitle.textContent = song.in_setlist === false || song.index < 0
      ? "(no song)"
      : song.name || "—";
    els.clock.textContent = state.clock || "00:00.000";
    els.duration.textContent = `/ ${state.duration_clock || "00:00.000"}`;
    els.timecode.textContent = state.timecode || "—";
    els.nowPrimary.textContent = formatNow(state.now && state.now.primary);
    els.nowSecondary.textContent = formatNow(state.now && state.now.secondary);
    els.playBtn.textContent = state.playing ? "⏸" : "▶";
    els.playBtn.classList.toggle("playing", Boolean(state.playing));
    if (!scrubbing) {
      const dur = Math.max(0.001, Number(state.duration) || 0.001);
      const pos = Math.max(0, Number(state.position) || 0);
      els.seekBar.value = String(Math.round((pos / dur) * 1000));
    }
    renderSongs(state.songs || []);
    renderCues(state.marks || []);
    renderMarkButtons(state.lanes || []);
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

  els.playBtn.addEventListener("click", () => {
    command({ op: "toggle" }).catch(() => {});
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

  els.seekBar.addEventListener("pointerdown", () => { scrubbing = true; });
  els.seekBar.addEventListener("pointerup", async () => {
    scrubbing = false;
    try {
      const state = await api("/api/state");
      const dur = Math.max(0, Number(state.duration) || 0);
      const ratio = Number(els.seekBar.value) / 1000;
      await command({ op: "seek", seconds: ratio * dur });
    } catch (_) {}
  });
  els.seekBar.addEventListener("change", async () => {
    if (scrubbing) return;
    try {
      const state = await api("/api/state");
      const dur = Math.max(0, Number(state.duration) || 0);
      const ratio = Number(els.seekBar.value) / 1000;
      await command({ op: "seek", seconds: ratio * dur });
    } catch (_) {}
  });

  els.authBtn.addEventListener("click", openAuth);
  els.savePassword.addEventListener("click", (ev) => {
    ev.preventDefault();
    token = els.passwordInput.value || "";
    localStorage.setItem(TOKEN_KEY, token);
    els.authDialog.close();
    showToast(token ? "Password saved" : "Password cleared");
  });

  // Digits on physical keyboard (iPad Magic Keyboard).
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

  poll();
})();

const PAGE_SIZE = 24;

class PrintTimelapseBase extends HTMLElement {
  _init() {
    if (this.started) return;
    this.started = true;
    this.attachShadow({ mode: "open" });
    this._renderShell();
    this._load();
  }

  _el(tag, text, cls) {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }

  _formatDate(s) {
    if (!s) return "Not recorded";
    const d = new Date(s);
    if (isNaN(d)) return s;
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  _duration(s) {
    const m = Math.round(s / 60);
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
  }

  async _signed(path, expires = 300) {
    if (!/^([a-zA-Z0-9_.-]+\/)*[a-zA-Z0-9_.-]+$/.test(path) || path.split("/").includes("..")) {
      throw new Error("Invalid archive path");
    }
    const r = await this._hass.callWS({
      type: "auth/sign_path",
      path: `/media/local/${this._mediaPrefix}/${path}`,
      expires,
    });
    return this._hass.hassUrl(r.path);
  }

  _renderShell() {
    const root = this.shadowRoot;
    const style = this._el("style");
    const pad = this._isCard ? "4px" : "0 12px 24px";
    const headPad = this._isCard ? "12px 8px" : "24px 8px 20px";
    style.textContent = `
      :host{display:block;padding:${pad};box-sizing:border-box;color:var(--primary-text-color)}
      .head{padding:${headPad}}
      .intro{max-width:760px;line-height:1.5;color:var(--secondary-text-color);font-size:14px}
      .tools{display:flex;gap:12px;align-items:center;margin-top:18px;flex-wrap:wrap}
      input{background:var(--card-background-color);border:1px solid var(--divider-color);color:inherit;border-radius:12px;padding:12px 14px;font:inherit;min-width:190px;flex:1}
      button{border:1px solid var(--divider-color);border-radius:10px;background:var(--card-background-color);color:inherit;padding:10px 14px;cursor:pointer;font:inherit}
      button:hover{border-color:var(--primary-color)}
      button.primary{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:transparent}
      .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr));gap:20px}
      .card{overflow:hidden;background:var(--ha-card-background,var(--card-background-color));border:1px solid var(--divider-color);border-radius:18px;box-shadow:var(--ha-card-box-shadow)}
      .poster{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;background:#101820}
      .body{padding:20px}
      .job{font-size:21px;font-weight:600;margin-bottom:8px}
      .filename{font-size:12px;overflow-wrap:anywhere;color:var(--secondary-text-color);line-height:1.45;margin-bottom:16px}
      .stats{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0}
      .label{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--secondary-text-color);margin-bottom:5px}
      .value{font-size:16px}
      .times{font-size:13px;line-height:1.7}
      .actions{display:flex;gap:10px;margin-top:20px;flex-wrap:wrap}
      .note{font-size:12px;color:var(--secondary-text-color);line-height:1.5;margin-top:18px}
      .foot{font-size:12px;line-height:1.6;padding:22px 8px;color:var(--secondary-text-color)}
      dialog{max-width:1000px;width:calc(100% - 40px);padding:18px;border:1px solid var(--divider-color);border-radius:16px;background:var(--card-background-color,#fff);color:inherit}
      dialog::backdrop{background:rgba(0,0,0,.8)}
      video{width:100%;max-height:72vh;background:#000;margin-top:12px}
      .dialoghead{display:flex;justify-content:space-between;align-items:center;gap:12px}
      .more{display:block;margin:24px auto 0}`;
    root.append(style);
    this._head = this._el("div", undefined, "head");
    this._status = this._el("div", "Loading archive...", "intro");
    this._head.append(this._status);
    const tools = this._el("div", undefined, "tools");
    this._search = this._el("input");
    this._search.type = "search";
    this._search.placeholder = "Search job or file name";
    this._search.setAttribute("aria-label", "Search archived prints");
    const refresh = this._el("button", "Refresh");
    refresh.onclick = () => this._load(true);
    tools.append(this._search, refresh);
    this._head.append(tools);
    root.append(this._head);
    this._grid = this._el("div", undefined, "grid");
    root.append(this._grid);
    this._foot = this._el("div", undefined, "foot");
    root.append(this._foot);
    this._search.oninput = () => {
      clearTimeout(this._debounce);
      this._debounce = setTimeout(() => this._load(true), 250);
    };
  }

  async _load(reset) {
    if (reset) {
      this._jobs = [];
      this._offset = 0;
      this._total = 0;
    }
    try {
      const data = await this._hass.callWS({
        type: "print_timelapse/list",
        query: this._search.value || undefined,
        offset: this._offset,
        limit: PAGE_SIZE,
      });
      this._mediaPrefix = data.media_prefix || "print_timelapse_archive";
      this._jobs = (this._jobs || []).concat(data.jobs);
      this._total = data.total;
      this._offset = this._jobs.length;
      this._status.textContent = `${data.total} saved prints · Updated ${this._formatDate(data.updated_at)}`;
      this._renderJobs();
      this._foot.textContent = `${data.retention || ""} · ${((data.free_bytes || 0) / 1073741824).toFixed(1)} GiB free.`;
    } catch (e) {
      this._status.textContent = `Archive unavailable. ${e.message || e}`;
    }
  }

  _renderJobs() {
    this._grid.replaceChildren();
    for (const j of this._jobs) {
      const card = this._el("article", undefined, "card");
      if (j.poster) {
        const img = this._el("img", undefined, "poster");
        img.alt = `Last saved frame for print job ${j.job_id}`;
        img.loading = "lazy";
        this._signed(j.poster).then((u) => (img.src = u)).catch(() => {});
        card.append(img);
      }
      const body = this._el("div", undefined, "body");
      body.append(
        this._el("div", `Print job ${j.job_id}`, "job"),
        this._el("div", j.file_name || "Original file name was not saved", "filename")
      );
      const stats = this._el("div", undefined, "stats");
      for (const [a, b] of [
        ["Saved frames", (j.frames || 0).toLocaleString()],
        ["Capture span", this._duration(j.span_seconds || 0)],
        ["Gaps over 2 min", String(j.gaps_over_2min || 0)],
        ["Largest such gap", j.largest_gap_seconds ? this._duration(j.largest_gap_seconds) : "None"],
      ]) {
        const d = this._el("div");
        d.append(this._el("div", a, "label"), this._el("div", b, "value"));
        stats.append(d);
      }
      body.append(stats);
      const times = this._el("div", undefined, "times");
      times.append(
        this._el("div", `First saved: ${this._formatDate(j.first_capture)}`),
        this._el("div", `Last saved: ${this._formatDate(j.last_capture)}`)
      );
      body.append(times);
      const actions = this._el("div", undefined, "actions");
      for (const res of ["720p", "1080p"]) {
        if (j.videos && j.videos[res]) {
          const b = this._el("button", `Play ${res}`, res === "720p" ? "primary" : "");
          b.onclick = () => this._play(j, res);
          actions.append(b);
        }
      }
      body.append(actions, this._el("div", j.coverage_note || "", "note"));
      card.append(body);
      this._grid.append(card);
    }
    if (!this._jobs.length) {
      this._grid.append(this._el("div", "No matching prints.", "intro"));
    }
    const old = this.shadowRoot.querySelector(".more");
    if (old) old.remove();
    if (this._jobs.length < this._total) {
      const more = this._el("button", `Show more (${this._jobs.length} of ${this._total})`, "more");
      more.onclick = () => this._load(false);
      this.shadowRoot.append(more);
    }
  }

  async _play(job, res) {
    const d = this._el("dialog");
    const h = this._el("div", undefined, "dialoghead");
    const close = this._el("button", "Close");
    h.append(this._el("strong", `Print job ${job.job_id} · ${res}`), close);
    d.append(h);
    const video = this._el("video");
    video.controls = true;
    video.playsInline = true;
    video.preload = "metadata";
    d.append(video);
    const n = this._el("div", "Loading video...", "note");
    d.append(n);
    this.shadowRoot.append(d);
    const end = () => {
      video.pause();
      video.removeAttribute("src");
      video.load();
      d.remove();
    };
    close.onclick = () => d.close();
    d.addEventListener("close", end, { once: true });
    d.showModal();
    try {
      video.src = await this._signed(job.videos[res].path, 3600);
      video.onloadedmetadata = () =>
        (n.textContent = "Saved interval timelapse. Not proof of print success or complete coverage.");
      video.onerror = () =>
        (n.textContent = "Playback failed. Close and reopen, or try the other resolution.");
      await video.play().catch(() => {});
    } catch (e) {
      n.textContent = e.message;
    }
  }
}

class PrintTimelapsePanel extends PrintTimelapseBase {
  set hass(hass) {
    this._hass = hass;
    this._init();
  }
}

class PrintTimelapseCard extends PrintTimelapseBase {
  constructor() {
    super();
    this._isCard = true;
  }

  setConfig(config) {
    this._config = config;
    if (this._hass) this._init();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._config) this._init();
  }

  getCardSize() {
    return 6;
  }
}

if (!customElements.get("print-timelapse-panel")) {
  customElements.define("print-timelapse-panel", PrintTimelapsePanel);
}
if (!customElements.get("print-timelapse-card")) {
  customElements.define("print-timelapse-card", PrintTimelapseCard);
}


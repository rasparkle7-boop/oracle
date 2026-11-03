const API_BASE = "https://oracle-api-k6xr.onrender.com";
const ORACLE_STREAM_URL = `${API_BASE}/api/stream`;
/* ORACLE mission control */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v, d = 1) => v == null || Number.isNaN(Number(v)) ? "—" : `${(Number(v) * 100).toFixed(d)}%`;
  const pctRaw = (v, d = 1) => v == null ? "—" : `${Number(v).toFixed(d)}%`;
  const num = (v, d = 2) => v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const initials = (name) => String(name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  const fmtKick = (iso) => {
    if (!iso) return "TBC";
    const d = new Date(iso);
    return d.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" });
  };
  const fmtDate = (iso) => {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString(undefined, { day: "2-digit", month: "short" });
  };
  const fmtDay = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    const today = new Date();
    const diff = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(today.getFullYear(), today.getMonth(), today.getDate())) / 86400000);
    if (diff === 0) return "TODAY";
    if (diff === 1) return "TOMORROW";
    if (diff === -1) return "YESTERDAY";
    return d.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short" }).toUpperCase();
  };
  const timeAgo = (iso) => {
    if (!iso) return "never";
    const sec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (sec < 60) return `${Math.floor(sec)}s ago`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    return `${Math.floor(sec / 86400)}d ago`;
  };
  const countdown = (iso) => {
    if (!iso) return "—";
    let sec = Math.floor((new Date(iso).getTime() - Date.now()) / 1000);
    if (sec <= 0) return "due";
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };
  const crest = (team, sport = "football", logo = null, cls = "") => {
    if (logo) return `<img class="crest ${cls}" src="${esc(logo)}" alt="" loading="lazy" onerror="this.style.display='none'" />`;
    return `<div class="crest crest-fallback ${cls}" aria-hidden="true">${esc(initials(team))}</div>`;
  };
  const confClass = (label) => (label === "HIGH" ? "HIGH" : label === "MEDIUM" ? "MEDIUM" : "LOW");
  const sideColor = (side) => (side === "home" ? "cyan" : side === "away" ? "magenta" : "amber");

  const ICON = {
    search: `<svg viewBox="0 0 24 24"><path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM16.5 16.5 21 21"/></svg>`,
    star: `<svg viewBox="0 0 24 24"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/></svg>`,
    arrow: `<svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></svg>`,
    close: `<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>`,
    download: `<svg viewBox="0 0 24 24"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>`,
    refresh: `<svg viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v5h-5"/></svg>`,
    copy: `<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>`,
    external: `<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M10 5H5a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h13a1 1 0 0 0 1-1v-5"/></svg>`,
    activity: `<svg viewBox="0 0 24 24"><path d="M3 12h4l2-7 4 14 2-7h6"/></svg>`,
    brain: `<svg viewBox="0 0 24 24"><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-1 5.8A3 3 0 0 0 8 18a2.5 2.5 0 0 0 4 1V4.5A2.5 2.5 0 0 0 9 4zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 1 5.8A3 3 0 0 1 16 18a2.5 2.5 0 0 1-4 1V4.5A2.5 2.5 0 0 1 15 4z"/></svg>`,
    shield: `<svg viewBox="0 0 24 24"><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/></svg>`,
  };

  const state = {
    route: "mission",
    overview: null,
    fixtures: [],
    total: 0,
    filters: { sport: "", days: 7, q: "", sort: "kickoff", conf: 0, depth: "", watch: false },
    limit: 36,
    loading: false,
    reqSeq: 0,
    backtest: null,
    backtestLoading: false,
    slip: null,
    automation: null,
    active: null,
    dossierTab: "verdict",
    paletteOpen: false,
    paletteSel: 0,
    paletteItems: [],
    paletteSeq: 0,
    paletteLoading: false,
    orbRAF: 0,
    pollTimer: null,
    lastRoute: "mission",
  };

  // ------------------------------------------------------------------ api
  async function api(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    if (!response.ok) {
      let msg = `${response.status} ${response.statusText}`;
      try {
        const data = await response.json();
        msg = data.detail || data.message || msg;
      } catch (e) { /* response was not JSON */ }
      throw new Error(msg);
    }
    return response.json();
  }

  function toast(message, type = "ok") {
    const root = $("#toasts");
    const el = document.createElement("div");
    el.className = `toast ${type === "err" ? "err" : ""}`;
    el.textContent = message;
    root.appendChild(el);
    setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(6px)"; el.style.transition = ".3s"; }, 3600);
    setTimeout(() => el.remove(), 4100);
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); toast("Copied to clipboard"); }
    catch (e) { toast("Clipboard unavailable", "err"); }
  }

  // ------------------------------------------------------------------ routing
  const ROUTES = {
    mission: "MISSION CONTROL",
    fixtures: "FIXTURE GRID",
    research: "RESEARCH SIGNALS",
    lab: "MODEL LABORATORY",
    slip: "SLIP LAB",
    automation: "AUTOMATION",
    review: "POST-MATCH REVIEW",
    watch: "WATCHLIST",
  };

  function parseHash() {
    const raw = (location.hash || "#/mission").replace(/^#\/?/, "");
    const [route, ...rest] = raw.split("/");
    return { route: route || "mission", arg: rest.join("/") };
  }

  async function route() {
    const { route: r, arg } = parseHash();
    state.lastRoute = state.route;
    if (r === "match" && arg) {
      state.route = "match";
      $("#crumb").textContent = "MATCH DOSSIER";
      await openDossier(decodeURIComponent(arg), false);
      return;
    }
    if (r === "team" && arg) {
      state.route = "team";
      $("#crumb").textContent = "TEAM PROFILE";
      closeModal();
      $$(".rail-item").forEach((b) => b.classList.remove("active"));
      await renderTeam(decodeURIComponent(arg));
      return;
    }
    state.route = ROUTES[r] ? r : "mission";
    closeModal();
    $$(".rail-item").forEach((b) => b.classList.toggle("active", b.dataset.route === state.route));
    $("#crumb").textContent = ROUTES[state.route] || "MISSION CONTROL";
    stopPolling();
    if (state.route === "mission") await renderMission();
    if (state.route === "fixtures") await renderFixtures();
    if (state.route === "research") await renderResearch();
    if (state.route === "lab") await renderLab();
    if (state.route === "slip") await renderSlip();
    if (state.route === "automation") await renderAutomation();
    if (state.route === "review") await renderReview();
    if (state.route === "watch") await renderWatch();
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  function navigate(path) { location.hash = path; }

  // ------------------------------------------------------------------ shell
  function startClock() {
    const tick = () => {
      const d = new Date();
      $("#clock").textContent = d.toLocaleTimeString([], { hour12: false });
      $$("[data-countdown]").forEach((el) => { el.textContent = countdown(el.dataset.countdown); });
      const at = state.overview?.last_sync?.at;
      if (at) $("#syncAge").textContent = timeAgo(at);
    };
    tick();
    setInterval(tick, 1000);
  }

  function updateTicker(items) {
    const track = $("#tickerTrack");
    if (!items || !items.length) { track.innerHTML = `<span>Engine online · independent probabilities · zero market inputs</span>`; return; }
    const html = items.map((s) => {
      const edge = Number(s.edge || 0);
      return `<span><b>${esc(s.home_name)}</b> v <b>${esc(s.away_name)}</b> → ${esc(s.pick)} ${pct(s.pick_prob)} · edge ${edge >= 0 ? "+" : ""}${(edge * 100).toFixed(1)}pp</span>`;
    }).join("");
    track.innerHTML = html + html;
  }

  async function loadOverview(silent = false) {
    try {
      state.overview = await api("/api/overview");
      updateTicker(state.overview.signals || []);
      if (!silent) updateSyncPill();
      return state.overview;
    } catch (e) {
      if (!silent) toast(`Overview failed: ${e.message}`, "err");
      return null;
    }
  }

  function updateSyncPill() {
    const at = state.overview?.last_sync?.at;
    $("#syncAge").textContent = at ? timeAgo(at) : "never";
  }

  // ------------------------------------------------------------------ orb
  function startOrb() {
    const canvas = $("#orbCanvas");
    if (!canvas) return;
    cancelAnimationFrame(state.orbRAF);
    const ctx = canvas.getContext("2d");
    let w = 0, h = 0, dpr = Math.min(2, window.devicePixelRatio || 1);
    const resize = () => {
      const rect = canvas.parentElement.getBoundingClientRect();
      w = Math.max(240, rect.width); h = Math.max(220, rect.height);
      canvas.width = w * dpr; canvas.height = h * dpr;
      canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize); ro.observe(canvas.parentElement);
    const N = 190, pts = [];
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const theta = i * 2.399963;
      pts.push({ x: Math.cos(theta) * r, y, z: Math.sin(theta) * r, s: 0.6 + Math.random() * 1.4 });
    }
    let t = 0;
    const draw = () => {
      if (!document.body.contains(canvas)) return;
      ctx.clearRect(0, 0, w, h);
      const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.31;
      t += 0.0035;
      const cos = Math.cos(t), sin = Math.sin(t);
      const tilt = -0.28;
      const proj = pts.map((p) => {
        let x = p.x * cos - p.z * sin;
        let z = p.x * sin + p.z * cos;
        let y = p.y * Math.cos(tilt) - z * Math.sin(tilt);
        z = p.y * Math.sin(tilt) + z * Math.cos(tilt);
        const depth = (z + 1) / 2;
        return { x: cx + x * R, y: cy + y * R, z, depth, s: p.s };
      });
      // rings
      for (let r = 0; r < 3; r++) {
        ctx.beginPath();
        const rr = R * (1.18 + r * 0.13);
        ctx.ellipse(cx, cy, rr, rr * (0.28 + r * 0.06), t * (0.4 + r * 0.2), 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(111,247,255,${0.10 - r * 0.02})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      // connections
      for (let i = 0; i < proj.length; i++) {
        for (let j = i + 1; j < proj.length; j++) {
          const dx = proj[i].x - proj[j].x, dy = proj[i].y - proj[j].y;
          const d2 = dx * dx + dy * dy;
          if (d2 < 2100) {
            ctx.beginPath();
            ctx.moveTo(proj[i].x, proj[i].y);
            ctx.lineTo(proj[j].x, proj[j].y);
            ctx.strokeStyle = `rgba(111,247,255,${0.16 * (1 - d2 / 2100) * (proj[i].depth + proj[j].depth) / 2})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }
      // points
      for (const p of proj) {
        const a = 0.25 + p.depth * 0.75;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.s * (0.7 + p.depth * 0.9), 0, Math.PI * 2);
        ctx.fillStyle = p.depth > 0.65 ? `rgba(184,255,92,${a})` : `rgba(111,247,255,${a})`;
        ctx.fill();
        if (p.depth > 0.82) {
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.s * 4, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(111,247,255,${0.05 * a})`;
          ctx.fill();
        }
      }
      // equator glow
      const grad = ctx.createRadialGradient(cx, cy, R * 0.1, cx, cy, R * 1.5);
      grad.addColorStop(0, "rgba(111,247,255,0.06)");
      grad.addColorStop(0.65, "rgba(255,92,207,0.02)");
      grad.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);
      state.orbRAF = requestAnimationFrame(draw);
    };
    draw();
    state._orbObserver = ro;
  }

  // ------------------------------------------------------------------ mission
  async function renderMission() {
    const view = $("#view");
    view.innerHTML = missionSkeleton();
    const ov = await loadOverview();
    if (!ov) { view.innerHTML = errorState("Could not reach the intelligence API."); return; }
    const c = ov.counts || {};
    const depth = ov.depth || {};
    const full = depth.full || 0, enhanced = depth.enhanced || 0;
    const signals = ov.signals || [];
    const comps = ov.top_competitions || [];
    const maxComp = Math.max(1, ...comps.map((x) => x.n));
    const last = ov.last_sync || {};
    const stats = last.stats || {};
    const modelMatches = stats.models?.football_matches || 0;

    view.innerHTML = `
      <div class="hero">
        <section class="panel hero-main">
          <div>
            <div class="hero-kicker">INDEPENDENT SPORTS INTELLIGENCE · NO MARKET INPUTS</div>
            <h1 class="hero-title">THE MARKET<br/>IS NOISE.<br/><span>THE MODEL IS SIGNAL.</span></h1>
            <p class="hero-copy">ORACLE ingests the global fixture grid, researches availability and conditions, then prices every match with its own Dixon–Coles and Monte Carlo engines. Nothing here is copied from a bookmaker.</p>
          </div>
          <div class="hero-actions">
            <button class="btn btn-primary" onclick="location.hash='#/fixtures'">${ICON.arrow} EXPLORE ${c.fixtures_window || 0} FIXTURES</button>
            <button class="btn" id="heroSync">${ICON.refresh} RUN AUTONOMOUS CYCLE</button>
          </div>
        </section>
        <aside class="panel hero-aside">
          <div class="orb-wrap">
            <canvas id="orbCanvas"></canvas>
            <div class="orb-overlay"><div class="orb-core"><strong>${c.predictions || 0}</strong><span>PREDICTIONS ARMED</span></div></div>
          </div>
          <div class="orb-legend">
            <span><i style="background:var(--cyan)"></i>${c.competitions_window || 0} competitions</span>
            <span><i style="background:var(--lime)"></i>${full} full dossiers</span>
            <span><i style="background:var(--magenta)"></i>${enhanced} enhanced</span>
          </div>
        </aside>
      </div>

      <div class="kpi-grid">
        ${kpi("FIXTURES / 7D", c.fixtures_window ?? "—", "in the rolling window", "cyan")}
        ${kpi("COMPETITIONS", c.competitions_window ?? "—", "football + cricket", "magenta")}
        ${kpi("PREDICTIONS", c.predictions ?? "—", "independently generated", "lime")}
        ${kpi("FULL RESEARCH", full, "news + availability + venue", "amber")}
        ${kpi("AVG CONFIDENCE", `${c.avg_confidence ?? 0}<small>/100</small>`, "model conviction", "cyan")}
        ${kpi("MODEL TRAINED", modelMatches.toLocaleString(), "finished matches", "lime")}
      </div>

      <div class="dashboard-grid">
        <div class="stack">
          <section class="panel">
            <div class="panel-head">
              <span class="panel-title">// SIGNAL BOARD · HIGHEST CONVICTION</span>
              <button class="btn btn-ghost" onclick="location.hash='#/fixtures'">ALL FIXTURES ${ICON.arrow}</button>
            </div>
            <div style="overflow-x:auto">
              <table class="signal-table">
                <thead><tr><th>FIXTURE</th><th>KICKOFF</th><th>ORACLE PICK</th><th>PROB</th><th>MODEL Δ</th><th>CONVICTION</th><th>DEPTH</th></tr></thead>
                <tbody>
                  ${signals.length ? signals.map((s) => `
                    <tr onclick="ORACLE.open('${esc(s.id)}')">
                      <td><div class="match-cell"><b>${esc(s.home_name)} <span class="faint">v</span> ${esc(s.away_name)}</b><span>${esc(s.id.split(":")[0].toUpperCase())} · ${esc(s.competition_name || "—")}</span></div></td>
                      <td class="mono tiny muted">${fmtKick(s.kickoff_utc)}</td>
                      <td><span class="pick-chip ${Number(s.edge) > 0.06 ? "" : "amber"}">${esc(s.pick)}</span></td>
                      <td><div class="prob-num">${pct(s.pick_prob)}</div><div class="prob-mini"><span style="width:${clamp(Number(s.pick_prob) * 100, 0, 100)}%"></span></div></td>
                      <td class="mono ${Number(s.edge) >= 0 ? "lime" : "muted"}">${Number(s.edge) >= 0 ? "+" : ""}${(Number(s.edge) * 100).toFixed(1)}pp</td>
                      <td><span class="conf"><i class="conf-dot ${confClass(Number(s.confidence) >= 72 ? "HIGH" : Number(s.confidence) >= 55 ? "MEDIUM" : "LOW")}"></i>${Math.round(Number(s.confidence) || 0)}</span></td>
                      <td><span class="tag">${esc(s.data_depth || "model")}</span></td>
                    </tr>`).join("") : `<tr><td colspan="7">${emptyInline("No predictions yet. Run a cycle to arm the engine.")}</td></tr>`}
                </tbody>
              </table>
            </div>
            <div class="note-box" style="margin:0 18px 16px">MODEL Δ = pick probability minus the competition's historical base rate. It is a model deviation, not a bookmaker edge. No market price is used.</div>
          </section>

          <section class="panel">
            <div class="panel-head"><span class="panel-title">// COVERAGE MATRIX · TOP COMPETITIONS IN WINDOW</span><span class="mono tiny faint">${(ov.sports?.football || 0)} football · ${(ov.sports?.cricket || 0)} cricket</span></div>
            <div class="panel-body bars">
              ${comps.length ? comps.map((x) => `
                <div class="bar-row">
                  <span title="${esc(x.name)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(x.name)}</span>
                  <div class="bar"><span style="width:${Math.max(4, (x.n / maxComp) * 100)}%"></span></div>
                  <span class="v">${x.n}</span>
                </div>`).join("") : emptyInline("No competition data yet.")}
            </div>
          </section>
        </div>

        <div class="stack">
          <section class="panel">
            <div class="panel-head"><span class="panel-title">// ENGINE STATUS</span><span class="mono tiny green"><span class="pulse-dot"></span>ONLINE</span></div>
            <div class="panel-body">
              <div class="metric-grid">
                <div class="metric"><div class="l">Last cycle</div><div class="v" style="font-size:14px">${last.at ? timeAgo(last.at) : "never"}</div></div>
                <div class="metric"><div class="l">Next cycle</div><div class="v" style="font-size:14px" data-countdown="${esc(ov.engine?.next_sync || "")}">${countdown(ov.engine?.next_sync)}</div></div>
                <div class="metric"><div class="l">Analysed</div><div class="v">${stats.analysed ?? "—"}</div></div>
                <div class="metric"><div class="l">Elapsed</div><div class="v">${stats.elapsed_seconds ? stats.elapsed_seconds + "s" : "—"}</div></div>
                <div class="metric"><div class="l">Football comps</div><div class="v">${stats.models?.football_competitions ?? "—"}</div></div>
                <div class="metric"><div class="l">Cricket teams</div><div class="v">${stats.models?.cricket_teams ?? "—"}</div></div>
              </div>
              <div class="note-box">MODEL ${esc(ov.engine?.model || "")} · market inputs: <b class="lime">0</b> · every probability is derived from match data, fitted ratings and bounded context adjustments.</div>
              <div style="display:flex;gap:6px;margin-top:12px;flex-wrap:wrap">
                <button class="btn" onclick="location.hash='#/automation'">${ICON.activity} AUTOMATION</button>
                <button class="btn" onclick="ORACLE.runSync()">${ICON.refresh} SYNC NOW</button>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head"><span class="panel-title">// RESEARCH CORE</span><span class="mono tiny faint">A / B / C GRADES</span></div>
            <div class="panel-body">
              ${researchDepthBars(depth, c.fixtures_window || 1)}
              <div class="note-box" style="margin-top:14px">Structured availability comes from match-centre feeds. News signals are linked and time-stamped. Nothing is upgraded to “fact” without a source.</div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head"><span class="panel-title">// MODEL STACK</span><span class="mono tiny faint">4 LAYERS</span></div>
            <div class="panel-body" style="display:flex;flex-direction:column;gap:8px">
              ${stackRow("Dixon–Coles", "time-decayed attack/defence + low-score rho", "01")}
              ${stackRow("Monte Carlo", "ball-by-ball T20/ODI, session Test model", "02")}
              ${stackRow("Context engine", "injuries, fatigue, weather, venue", "03")}
              ${stackRow("Reasoning core", "edge thesis, risks, adversarial check", "04")}
            </div>
          </section>
        </div>
      </div>`;

    startOrb();
    $("#heroSync")?.addEventListener("click", () => runSync());
  }

  function missionSkeleton() {
    return `<div class="hero"><div class="panel hero-main"><div class="skeleton" style="height:16px;width:40%"></div><div class="skeleton" style="height:52px;width:90%;margin-top:18px"></div><div class="skeleton" style="height:52px;width:70%;margin-top:8px"></div></div><div class="panel hero-aside"><div class="skeleton" style="height:260px;margin:16px"></div></div></div>
      <div class="kpi-grid">${Array(6).fill('<div class="panel kpi"><div class="skeleton" style="height:10px;width:60%"></div><div class="skeleton" style="height:28px;width:40%;margin-top:10px"></div></div>').join("")}</div>`;
  }

  function kpi(label, value, sub, color) {
    return `<div class="panel kpi"><div class="kpi-label">${esc(label)}</div><div class="kpi-value ${color}">${value}</div><div class="kpi-sub">${esc(sub)}</div></div>`;
  }

  function stackRow(title, desc, n) {
    return `<div style="display:flex;gap:10px;align-items:flex-start;padding:7px 0;border-bottom:1px solid rgba(118,226,255,.06)">
      <span class="mono tiny faint">${n}</span><div><div style="font-size:12px;font-weight:600">${esc(title)}</div><div class="tiny muted">${esc(desc)}</div></div>
    </div>`;
  }

  function researchDepthBars(depth, total) {
    const entries = [["full", "A · full dossier", "var(--lime)"], ["enhanced", "B · news enhanced", "var(--cyan)"], ["model", "C · model only", "var(--amber)"], ["partial", "D · sparse", "var(--red)"]];
    return entries.map(([k, label, color]) => {
      const n = depth[k] || 0;
      return `<div class="bar-row"><span>${label}</span><div class="bar"><span style="width:${Math.max(2, (n / total) * 100)}%;background:${color}"></span></div><span class="v">${n}</span></div>`;
    }).join("");
  }

  // ------------------------------------------------------------------ fixtures
  async function renderFixtures() {
    const view = $("#view");
    const f = state.filters;
    view.innerHTML = `
      <div class="page-head">
        <div><div class="eyebrow">GLOBAL FIXTURE GRID</div><h1 class="page-title">Every match. One independent model.</h1><p class="page-sub">Football and cricket, ${f.days}-day rolling window. Filter the grid, open a dossier, inspect the exact evidence behind the probability.</p></div>
        <div class="page-actions">
          <a class="btn" href="/api/export?sport=${encodeURIComponent(f.sport)}&days=${f.days}">${ICON.download} EXPORT CSV</a>
          <button class="btn btn-primary" id="fixturesSync">${ICON.refresh} SYNC</button>
        </div>
      </div>
      <div class="filterbar">
        <div class="seg" id="sportSeg">
          ${[["", "ALL"], ["football", "FOOTBALL"], ["cricket", "CRICKET"]].map(([v, l]) => `<button class="${f.sport === v ? "active" : ""}" data-sport="${v}">${l}</button>`).join("")}
        </div>
        <div class="seg" id="daySeg">
          ${[[1, "TODAY"], [3, "3 DAYS"], [7, "7 DAYS"], [30, "30 DAYS"]].map(([v, l]) => `<button class="${Number(f.days) === v ? "active" : ""}" data-days="${v}">${l}</button>`).join("")}
        </div>
        <div class="filter-search">${ICON.search}<input id="fxSearch" placeholder="Search team or competition…" value="${esc(f.q)}" /></div>
        <select class="select" id="sortSel">
          ${[["kickoff", "SORT: KICKOFF"], ["confidence", "SORT: CONFIDENCE"], ["edge", "SORT: EDGE"], ["importance", "SORT: IMPORTANCE"], ["probability", "SORT: PROBABILITY"]].map(([v, l]) => `<option value="${v}" ${f.sort === v ? "selected" : ""}>${l}</option>`).join("")}
        </select>
        <select class="select" id="confSel">
          ${[[0, "ANY CONFIDENCE"], [50, "50+ CONFIDENCE"], [60, "60+ CONFIDENCE"], [70, "70+ CONFIDENCE"]].map(([v, l]) => `<option value="${v}" ${Number(f.conf) === v ? "selected" : ""}>${l}</option>`).join("")}
        </select>
        <select class="select" id="depthSel">
          ${[["", "ANY DEPTH"], ["full", "A · FULL"], ["enhanced", "B · ENHANCED"], ["model", "C · MODEL"]].map(([v, l]) => `<option value="${v}" ${f.depth === v ? "selected" : ""}>${l}</option>`).join("")}
        </select>
        <button class="btn btn-ghost" id="watchToggle" title="Only watchlist">${ICON.star} WATCH</button>
      </div>
      <div class="result-line"><span>Showing <b id="fxCount">—</b> of <b id="fxTotal">—</b> fixtures</span><span id="fxWindow">${f.days}-day window · ${f.sport || "all sports"}</span></div>
      <div id="fixtureGrid" class="fixture-grid">${fixtureSkeletons(9)}</div>
      <div class="load-more" id="loadMoreWrap"></div>`;
    bindFixtureFilters();
    $("#fixturesSync")?.addEventListener("click", () => runSync());
    await loadFixtures(true);
  }

  function bindFixtureFilters() {
    $$("#sportSeg button").forEach((b) => b.addEventListener("click", () => {
      state.filters.sport = b.dataset.sport; state.limit = 36; renderFixtures();
    }));
    $$("#daySeg button").forEach((b) => b.addEventListener("click", () => {
      state.filters.days = Number(b.dataset.days); state.limit = 36; renderFixtures();
    }));
    $("#sortSel")?.addEventListener("change", (e) => { state.filters.sort = e.target.value; state.limit = 36; loadFixtures(true); });
    $("#confSel")?.addEventListener("change", (e) => { state.filters.conf = Number(e.target.value); state.limit = 36; loadFixtures(true); });
    $("#depthSel")?.addEventListener("change", (e) => { state.filters.depth = e.target.value; state.limit = 36; loadFixtures(true); });
    $("#watchToggle")?.addEventListener("click", () => {
      state.filters.watch = !state.filters.watch;
      $("#watchToggle").classList.toggle("active", state.filters.watch);
      $("#watchToggle").style.color = state.filters.watch ? "var(--amber)" : "";
      state.limit = 36; loadFixtures(true);
    });
    let t;
    $("#fxSearch")?.addEventListener("input", (e) => {
      clearTimeout(t);
      t = setTimeout(() => { state.filters.q = e.target.value; state.limit = 36; loadFixtures(true); }, 280);
    });
  }

  async function loadFixtures(reset = false) {
    const seq = ++state.reqSeq;
    const f = { ...state.filters };
    const params = new URLSearchParams({
      days: String(f.days), sort: f.sort, limit: String(state.limit), offset: "0",
      min_confidence: String(f.conf || 0),
    });
    if (f.sport) params.set("sport", f.sport);
    if (f.q) params.set("q", f.q);
    if (f.depth) params.set("depth", f.depth);
    if (f.watch) params.set("watchlist", "true");
    try {
      const data = await api(`/api/fixtures?${params}`);
      if (seq !== state.reqSeq) return;
      state.fixtures = data.items || [];
      state.total = data.total || 0;
      const grid = $("#fixtureGrid");
      if (grid) grid.innerHTML = state.fixtures.length ? state.fixtures.map(fxCard).join("") : emptyState("No fixtures match this filter.", "Try widening the window or clearing the search.");
      const count = $("#fxCount"), total = $("#fxTotal");
      if (count) count.textContent = state.fixtures.length;
      if (total) total.textContent = state.total;
      const more = $("#loadMoreWrap");
      if (more) more.innerHTML = state.fixtures.length < state.total ? `<button class="btn" id="loadMore">LOAD ${Math.min(48, state.total - state.fixtures.length)} MORE ${ICON.arrow}</button>` : "";
      $("#loadMore")?.addEventListener("click", () => { state.limit += 48; loadFixtures(false); });
    } catch (e) {
      toast(`Fixture load failed: ${e.message}`, "err");
    } finally {
      state.loading = false;
    }
  }

  function fxCard(f) {
    const probs = [Number(f.home_prob) || 0, Number(f.draw_prob) || 0, Number(f.away_prob) || 0];
    const sum = probs.reduce((a, b) => a + b, 0) || 1;
    const hp = (probs[0] / sum) * 100, dp = (probs[1] / sum) * 100, ap = (probs[2] / sum) * 100;
    const flags = Array.isArray(f.flags) ? f.flags : [];
    const conf = Number(f.confidence) || 0;
    const confLabel = conf >= 72 ? "HIGH" : conf >= 55 ? "MEDIUM" : "LOW";
    const edge = Number(f.edge) || 0;
    const homeLogo = f.sport === "football" ? `https://images.fotmob.com/image_resources/logo/teamlogo/${String(f.id).includes("fb:") ? "" : ""}` : "";
    return `<article class="fx-card" onclick="ORACLE.open('${esc(f.id)}')">
      <div class="fx-top">
        <div class="fx-comp">${f.competition_logo ? `<img src="${esc(f.competition_logo)}" onerror="this.style.display='none'" alt="" />` : ""}<span>${esc(f.competition_name || "—")}</span></div>
        <div class="fx-time">${fmtDay(f.kickoff_utc)} · ${fmtKick(f.kickoff_utc)}</div>
      </div>
      <div class="fx-teams">
        <div class="fx-team">${crest(f.home_name, f.sport, f.home_logo)}<span>${esc(f.home_name)}</span></div>
        <div class="fx-team">${crest(f.away_name, f.sport, f.away_logo)}<span>${esc(f.away_name)}</span></div>
      </div>
      <div class="fx-split"><span class="h" style="width:${hp}%"></span><span class="d" style="width:${dp}%"></span><span class="a" style="width:${ap}%"></span></div>
      <div class="fx-probs"><span>H ${pct(f.home_prob)}</span><span>D ${pct(f.draw_prob)}</span><span>A ${pct(f.away_prob)}</span></div>
      <div class="fx-bottom">
        <span class="pick-chip ${f.pick_side === "away" ? "magenta" : f.pick_side === "draw" ? "amber" : "cyan"}">${esc(f.pick || "—")}</span>
        <span class="fx-edge ${edge < 0 ? "neg" : ""}">${edge >= 0 ? "+" : ""}${(edge * 100).toFixed(1)}pp</span>
        <span class="conf"><i class="conf-dot ${confLabel}"></i>${conf.toFixed(0)}</span>
        <button class="star-btn ${f.watchlisted ? "on" : ""}" title="Watchlist" onclick="event.stopPropagation();ORACLE.watch('${esc(f.id)}',this)">${ICON.star}</button>
      </div>
      ${flags.length ? `<div class="fx-tags">${flags.slice(0, 3).map((x) => `<span class="tag ${/injur|absence|suspens/i.test(x) ? "inj" : /weather|rain|heat|dew|congestion/i.test(x) ? "hot" : ""}">${esc(x)}</span>`).join("")}</div>` : ""}
    </article>`;
  }

  function fixtureSkeletons(n) {
    return Array(n).fill(`<div class="panel" style="padding:16px"><div class="skeleton" style="height:10px;width:50%"></div><div class="skeleton" style="height:18px;width:80%;margin-top:14px"></div><div class="skeleton" style="height:18px;width:65%;margin-top:8px"></div><div class="skeleton" style="height:5px;width:100%;margin-top:14px"></div></div>`).join("");
  }

  // ------------------------------------------------------------------ dossier
  async function openDossier(id, push = true) {
    if (push) { location.hash = `#/match/${encodeURIComponent(id)}`; return; }
    const root = $("#modalRoot");
    root.innerHTML = `<div class="modal-backdrop" id="modalBackdrop"><div class="dossier"><div class="dossier-head"><div class="skeleton" style="height:12px;width:30%"></div><div class="skeleton" style="height:34px;width:60%;margin-top:12px"></div></div><div class="dossier-body"><div class="skeleton" style="height:220px"></div></div></div></div>`;
    try {
      const data = await api(`/api/fixtures/${encodeURIComponent(id)}`);
      state.active = data;
      state.dossierTab = "verdict";
      renderDossier(data);
    } catch (e) {
      root.innerHTML = "";
      toast(`Dossier failed: ${e.message}`, "err");
    }
  }

  function closeModal() {
    const root = $("#modalRoot");
    if (root) root.innerHTML = "";
    state.active = null;
    if (state.route === "match") { state.route = state.lastRoute && state.lastRoute !== "match" ? state.lastRoute : "mission"; }
  }

  function renderDossier(data) {
    const f = data.fixture || {};
    const p = data.prediction || {};
    const r = data.research || {};
    const a = p.analysis || {};
    const isCricket = f.sport === "cricket";
    const probs = [Number(p.home_prob) || 0, Number(p.draw_prob) || 0, Number(p.away_prob) || 0];
    const sum = probs.reduce((x, y) => x + y, 0) || 1;
    const hp = (probs[0] / sum) * 100, dp = (probs[1] / sum) * 100, ap = (probs[2] / sum) * 100;
    const conf = Number(p.confidence) || 0;
    const confLabel = conf >= 72 ? "HIGH" : conf >= 55 ? "MEDIUM" : "LOW";
    const edgeQ = a.edge_quality || (Math.abs(Number(p.edge) || 0) >= 0.08 ? "STRONG" : Math.abs(Number(p.edge) || 0) >= 0.04 ? "MODERATE" : "THIN");
    const root = $("#modalRoot");
    root.innerHTML = `
      <div class="modal-backdrop" id="modalBackdrop">
        <div class="dossier">
          <div class="dossier-head">
            <button class="icon-btn dossier-close" id="dossierClose">${ICON.close}</button>
            <div class="dossier-kicker">${esc(f.competition_name || "—")} · ${esc(f.sport || "")} · ${esc(f.round || "fixture")}</div>
            <div class="dossier-teams">
              <div class="dossier-team">${crest(f.home_name, f.sport, f.home_logo)}${esc(f.home_name)}</div>
              <div class="dossier-vs">VS</div>
              <div class="dossier-team">${crest(f.away_name, f.sport, f.away_logo)}${esc(f.away_name)}</div>
            </div>
            <div class="dossier-meta">
              <span>${fmtDay(f.kickoff_utc)} · ${fmtKick(f.kickoff_utc)} ${esc(Intl.DateTimeFormat().resolvedOptions().timeZone || "local")}</span>
              <span>${esc(f.venue || "venue TBC")}${f.city ? " · " + esc(f.city) : ""}</span>
              <span>research grade ${esc(a.research_grade || "C")}</span>
              <span>model ${esc(p.model_version || "oracle")}</span>
            </div>
          </div>
          <div class="dossier-tabs" id="dossierTabs">
            ${[["verdict", "VERDICT"], ["teams", "TEAMS"], ["lineups", "LINEUPS"], ["markets", "MARKETS"], ["benchmark", "ODDS BENCH"], ["tactical", "TACTICAL"], ["research", "RESEARCH"], ["protocol", "PROTOCOL"], ["model", "MODEL TRACE"]].map(([k, l]) => `<button class="${state.dossierTab === k ? "active" : ""}" data-tab="${k}">${l}</button>`).join("")}
          </div>
          <div class="dossier-body" id="dossierBody">${dossierTab(data, state.dossierTab, { hp, dp, ap, conf, confLabel, edgeQ, isCricket })}</div>
        </div>
      </div>`;
    $("#dossierClose")?.addEventListener("click", closeDossier);
    $("#modalBackdrop")?.addEventListener("click", (e) => { if (e.target.id === "modalBackdrop") closeDossier(); });
    $$("#dossierTabs button").forEach((b) => b.addEventListener("click", () => {
      state.dossierTab = b.dataset.tab;
      $$("#dossierTabs button").forEach((x) => x.classList.toggle("active", x === b));
      $("#dossierBody").innerHTML = dossierTab(data, state.dossierTab, { hp, dp, ap, conf, confLabel, edgeQ, isCricket });
      bindDossierActions(data);
      if (state.dossierTab === "verdict" && !isCricket) drawHeatmap();
      if (state.dossierTab === "benchmark") loadBenchmark(data.fixture.id);
    }));
    bindDossierActions(data);
    if (!isCricket) setTimeout(drawHeatmap, 40);
  }

  function closeDossier() {
    if (location.hash.startsWith("#/match/")) {
      history.replaceState(null, "", `#/${state.lastRoute && state.lastRoute !== "match" ? state.lastRoute : "mission"}`);
      closeModal();
      route();
    } else {
      closeModal();
    }
  }

  function dossierTab(data, tab, m) {
    const f = data.fixture || {}, p = data.prediction || {}, r = data.research || {}, a = p.analysis || {};
    if (tab === "verdict") return verdictTab(data, m);
    if (tab === "teams") return teamsTab(data);
    if (tab === "lineups") return lineupsTab(data);
    if (tab === "markets") return marketsTab(p, f);
    if (tab === "benchmark") return benchmarkTab(f);
    if (tab === "tactical") return tacticalTab(a, p, f);
    if (tab === "research") return researchTab(r, f);
    if (tab === "protocol") return protocolTab(data);
    return modelTab(p, r, a, f, m);
  }

  function verdictTab(data, m) {
    const f = data.fixture || {}, p = data.prediction || {}, a = p.analysis || {}, r = data.research || {};
    const isCricket = f.sport === "cricket";
    const summary = p.summary || (p.score_grid && p.score_grid.summary) || {};
    const q = a.protocol || {};
    const usage = q.model_usage || {};
    const secondary = p.secondary || [];
    return `<div class="dossier-grid">
      <div>
        ${(a.research_grade === "C" || a.research_grade === "D") ? `<div class="note-box" style="border-left-color:var(--amber);margin:0 0 12px">MODEL-ONLY DOSSIER · This fixture was priced from historical results and team ratings. No verified news or structured availability was available at analysis time. Re-analyze after line-ups.</div>` : ""}
        <div class="verdict-box">
          <div class="verdict-text">${esc(a.verdict || p.analysis?.verdict || "No verdict recorded. Re-analyze this fixture.")}</div>
          ${a.confidence_note ? `<div class="verdict-sub mono">${esc(a.confidence_note)}</div>` : ""}
        </div>
        <div class="section-title">WHY THIS SIDE</div>
        <ul class="thesis">${(a.edge_thesis || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>Model-only output. No verified context was available.</li>"}</ul>
        ${a.key_battles?.length ? `<div class="section-title">KEY BATTLES</div><ul class="thesis">${a.key_battles.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        <div class="section-title">WHY THIS PREDICTION? · MODEL INPUTS</div>
        <ul class="thesis">${(usage.used || []).map((x) => `<li><b>${esc(x.input)}</b> <span class="tag">${esc(x.role || "")}</span> — ${esc(x.evidence || "")}</li>`).join("") || "<li>Model input trace unavailable; re-analyze this dossier.</li>"}</ul>
        ${(q.goal_totals || []).length ? `<div class="section-title">GOAL / TOTAL PROBABILITIES</div><div class="market-group">${(q.goal_totals || []).map((x) => `<div class="market-row"><span class="lbl">${esc(x.label)}</span><span class="p">${pct(x.probability)}</span><span class="o">fair ${num(x.fair_odds)}</span></div>`).join("")}</div>` : ""}
        ${(usage.context_only || []).length ? `<details style="margin-top:8px"><summary class="mono tiny faint" style="cursor:pointer">Context shown but not used by the core model</summary><ul class="thesis" style="margin-top:8px">${usage.context_only.map((x) => `<li><b>${esc(x.input)}</b> — ${esc(x.reason)}</li>`).join("")}</ul></details>` : ""}
        <div class="note-box">Prediction generated ${esc(p.generated_at || "—")} · model ${esc(p.model_version || "—")}. The evidence list above comes from stored model inputs; no feature importance is invented.</div>
        <div class="section-title">PROBABILITY SPLIT</div>
        <div class="prob-stack"><span class="h" style="width:${m.hp}%"></span><span class="d" style="width:${m.dp}%"></span><span class="a" style="width:${m.ap}%"></span></div>
        <div class="prob-legend"><span class="cyan">${esc(f.home_name)} ${pct(p.home_prob)}</span><span class="muted">${Number(p.draw_prob) > 0 ? `DRAW ${pct(p.draw_prob)}` : `TIE ${pct((p.score_grid && p.score_grid.summary && p.score_grid.summary.tie) || 0)}`}</span><span class="magenta">${esc(f.away_name)} ${pct(p.away_prob)}</span></div>
        ${!isCricket ? `<div class="metric-grid" style="margin-top:12px">${metric("HOME XG", num(summary.home_xg ?? p.expected_home ?? 0, 2), "cyan")}${metric("AWAY XG", num(summary.away_xg ?? p.expected_away ?? 0, 2), "magenta")}${metric("TOTAL XG", num((Number(summary.home_xg ?? p.expected_home ?? 0) + Number(summary.away_xg ?? p.expected_away ?? 0)), 2), "lime")}</div>` : ""}
        ${!isCricket ? `<div class="section-title">MOST LIKELY SCORELINES</div><div class="market-group">${((summary.top_scores || p.score_grid?.top_scores || [])).slice(0, 5).map((x) => `<div class="market-row"><span class="lbl">${esc(x.score)}</span><span class="p">${pct(x.probability)}</span><span class="o">${num(x.fair_odds)}</span></div>`).join('') || '<div class="muted tiny">No scorelines available.</div>'}</div>` : ""}
        ${!isCricket ? `<div class="section-title">GOAL DIFFERENCE</div><div class="market-group">${Object.entries(summary.goal_difference_probs || {}).map(([diff, prob]) => `<div class="market-row"><span class="lbl">${diff > 0 ? `Home +${diff}` : diff < 0 ? `Away ${diff}` : 'Draw 0-0'} </span><span class="p">${pct(prob)}</span><span class="o">—</span></div>`).join('') || '<div class="muted tiny">No goal-difference distribution.</div>'}</div>` : ""}
        ${isCricket ? cricketProjection(summary, f) : `<div class="section-title">SCORELINE HEATMAP</div>${heatmapBlock(f)}`}
        <div class="section-title">RISK FACTORS</div>
        <ul class="risk-list">${(a.risks || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>No risk factors recorded.</li>"}</ul>
        ${a.why_not ? `<div class="section-title">ADVERSARIAL CHECK</div><div class="verdict-box" style="padding:14px"><div class="verdict-sub" style="margin:0">${esc(a.why_not)}</div></div>` : ""}
      </div>
      <aside class="pick-card">
        <div class="pick-label">ORACLE PICK</div>
        <div class="pick-name">${esc(p.pick || "—")}</div>
        <div class="pick-prob-big">${pct(p.pick_prob)}</div>
        <div class="pick-fair">fair odds ${num(p.pick_fair)} · edge ${Number(p.edge) >= 0 ? "+" : ""}${(Number(p.edge) * 100).toFixed(1)}pp</div>
        <div class="edge-badge ${m.edgeQ}">${m.edgeQ} EDGE</div>
        <div style="margin-top:12px;display:flex;justify-content:center;gap:10px;align-items:center">
          <div class="grade-badge">RESEARCH <b>${esc(a.research_grade || "C")}</b></div>
          <div class="conf"><i class="conf-dot ${m.confLabel}"></i>${m.conf.toFixed(0)} / 100</div>
        </div>
        <div class="pick-actions">
          <button class="btn" data-act="copy">${ICON.copy} COPY</button>
          <button class="btn" data-act="watch">${ICON.star} ${data.watchlisted ? "SAVED" : "WATCH"}</button>
          <button class="btn" data-act="reanalyze">${ICON.refresh} RE-ANALYZE</button>
        </div>
        <div style="margin-top:10px"><a class="btn btn-ghost" href="/api/export?sport=${esc(f.sport)}&days=7" target="_blank" style="width:100%;justify-content:center">${ICON.download} EXPORT WINDOW</a></div>
        ${secondary.length ? `<div class="section-title" style="margin-top:16px">SECONDARY LEANS</div>${secondary.slice(0, 4).map((x) => `<div class="market-row"><span class="lbl">${esc(x.label)}</span><span class="p">${pct(x.probability)}</span><span class="o">${num(x.fair_odds)}</span></div>`).join("")}` : ""}
        <div class="note-box">Fair odds = 1 / ORACLE probability. No bookmaker price is used anywhere in this dossier.</div>
      </aside>
    </div>`;
  }

  function heatmapBlock(f) {
    return `<div class="heatmap-wrap"><canvas class="heatmap" id="scoreHeatmap" width="460" height="360"></canvas><div class="heatmap-legend"><span>LOW</span><span class="bar"></span><span>HIGH</span><div style="margin-top:10px;color:var(--muted)">Rows: ${esc(f.home_name)} goals<br/>Cols: ${esc(f.away_name)} goals</div></div></div>`;
  }

  function cricketProjection(summary, f) {
    const h = summary.projected_home || {}, a = summary.projected_away || {};
    const rows = [
      [f.home_name, h, "cyan"],
      [f.away_name, a, "magenta"],
    ];
    return `<div class="section-title">PROJECTED SCORE BANDS</div>
      ${rows.map(([name, v, color]) => `<div style="margin:8px 0 12px"><div style="display:flex;justify-content:space-between;font-size:11px"><span>${esc(name)}</span><span class="mono ${color}">${num(v.mean, 1)} runs <span class="faint">(p10–p90 ${num(v.p10, 0)}–${num(v.p90, 0)})</span></span></div><div class="prob-stack" style="height:8px;margin-top:6px"><span class="${color === "cyan" ? "h" : "a"}" style="width:${clamp((Number(v.mean) / 260) * 100, 3, 100)}%"></span></div></div>`).join("")}
      <div class="metric-grid" style="margin-top:10px">
        <div class="metric"><div class="l">Format</div><div class="v" style="font-size:15px">${esc(summary.format || (p.score_grid && p.score_grid.format) || "—")}</div></div>
        <div class="metric"><div class="l">Simulations</div><div class="v" style="font-size:15px">${summary.simulations || "—"}</div></div>
        <div class="metric"><div class="l">First inns</div><div class="v" style="font-size:15px">${num((summary.projected_first_innings || {}).mean, 0)}</div></div>
      </div>
      ${(summary.total_markets || []).length ? `<div class="section-title">TOTAL RUNS</div>${summary.total_markets.map((x) => `<div class="market-row"><span class="lbl">${esc(x.label)}</span><span class="p">${pct(x.probability)}</span><span class="o">${num(x.fair_odds)}</span></div>`).join("")}` : ""}`;
  }

  function resultChips(seq) {
    return String(seq || "").split("").map((x) => `<span class="form-chip ${x}">${x}</span>`).join("");
  }

  function teamsTab(data) {
    const f = data.fixture || {}, c = data.comparison || {};
    const h = c.home || {}, a = c.away || {};
    const h5 = h.overall_5 || {}, h10 = h.overall_10 || {}, hsplit = h.split_10 || {};
    const a5 = a.overall_5 || {}, a10 = a.overall_10 || {}, asplit = a.split_10 || {};
    const row = (label, hv, av, note = "") => `<tr><td><b>${esc(label)}</b>${note ? `<div class="tiny faint">${esc(note)}</div>` : ""}</td><td>${hv}</td><td>${av}</td></tr>`;
    const teamRecent = (block, team) => `<div class="tac-card"><h4>${esc(team)} · last 5</h4>${(block.recent || []).slice(0,5).map((m) => `<div class="market-row"><span class="lbl"><b>${m.venue === "H" ? "vs" : "@"} ${esc(m.opponent)}</b><br/><span class="tiny muted">${fmtDate(m.date)} · ${esc(m.competition || "")}</span></span><span class="mono tiny">${esc(m.score)}</span><span class="form-chip ${m.result}">${m.result}</span></div>`).join("") || `<div class="muted tiny">No completed matches.</div>`}</div>`;
    return `<div class="note-box" style="margin-top:0">Comparable periods are computed from the local results warehouse before kickoff. Sample sizes and date ranges are shown. xG and shot volume are <b>not</b> substituted with goals; they are marked unavailable.</div>
      <div class="compare-grid" style="margin-top:14px">
        <div class="compare-team"><div class="mono tiny faint">HOME</div><h3>${esc(f.home_name)}</h3><div class="form-chips">${resultChips(h5.sequence)}</div></div>
        <div class="compare-team"><div class="mono tiny faint">AWAY</div><h3>${esc(f.away_name)}</h3><div class="form-chips">${resultChips(a5.sequence)}</div></div>
      </div>
      <div style="overflow-x:auto;margin-top:12px"><table class="signal-table compare-table">
        <thead><tr><th>METRIC</th><th>${esc(f.home_name)}</th><th>${esc(f.away_name)}</th></tr></thead>
        <tbody>
          ${row("Last 5 · record", `${h5.wins || 0}W-${h5.draws || 0}D-${h5.losses || 0}`, `${a5.wins || 0}W-${a5.draws || 0}D-${a5.losses || 0}`, `${h5.matches || 0} vs ${a5.matches || 0} matches`)}
          ${c.sport === "football" ? row("Last 5 · scored / conceded per match", `${num(h5.scored_per_match)} / ${num(h5.conceded_per_match)}`, `${num(a5.scored_per_match)} / ${num(a5.conceded_per_match)}`, "goals per match") : row("Runs / wickets comparison", `<span class="muted">Unavailable</span>`, `<span class="muted">Unavailable</span>`, "cricket innings totals are not normalized in the public feed")}
          ${row("Last 5 · PPG", num(h5.ppg), num(a5.ppg))}
          ${row("Last 10 · record", `${h10.wins || 0}W-${h10.draws || 0}D-${h10.losses || 0}`, `${a10.wins || 0}W-${a10.draws || 0}D-${a10.losses || 0}`, `${h10.matches || 0} vs ${a10.matches || 0} matches`)}
          ${c.sport === "football" ? row("Last 10 · scored / conceded per match", `${num(h10.scored_per_match)} / ${num(h10.conceded_per_match)}`, `${num(a10.scored_per_match)} / ${num(a10.conceded_per_match)}`) : ""}
          ${row("Home / away split · record", `${hsplit.wins || 0}W-${hsplit.draws || 0}D-${hsplit.losses || 0}`, `${asplit.wins || 0}W-${asplit.draws || 0}D-${asplit.losses || 0}`, "home form for home team · away form for away team")}
          ${c.sport === "football" ? row("Split · scored / conceded per match", `${num(hsplit.scored_per_match)} / ${num(hsplit.conceded_per_match)}`, `${num(asplit.scored_per_match)} / ${num(asplit.conceded_per_match)}`) : ""}
          ${row("Rest days", h.rest_days != null ? h.rest_days + "d" : "—", a.rest_days != null ? a.rest_days + "d" : "—", "since previous completed match")}
          ${row("Historical xG / xGA", `<span class="muted">Unavailable</span>`, `<span class="muted">Unavailable</span>`, "feed does not provide historical xG")}
          ${row("Shots / shots on target", `<span class="muted">Unavailable</span>`, `<span class="muted">Unavailable</span>`, "feed does not provide shot volume")}
          ${row("Date range", h10.date_from ? `${fmtDate(h10.date_from)} – ${fmtDate(h10.date_to)}` : "—", a10.date_from ? `${fmtDate(a10.date_from)} – ${fmtDate(a10.date_to)}` : "—")}
        </tbody>
      </table></div>
      <div class="two-col" style="margin-top:14px">${teamRecent(h5, f.home_name)}${teamRecent(a5, f.away_name)}</div>
      <div class="note-box" style="margin-top:12px">Source: ${esc(c.source || "ORACLE local results warehouse")} · as of ${esc(c.as_of || "—")}. ${esc((c.limits || {}).xg || "")} ${esc((c.limits || {}).competitions || "")}</div>`;
  }

  function lineupsTab(data) {
    const ctx = (data.research || {}).raw || {};
    const lu = ctx.lineups || {};
    const inj = (data.research || {}).injury_signals || {};
    const confirmed = !!lu.available;
    const teamBlock = (team, starters, unavailable, formation) => `<div class="tac-card"><h4>${esc(team)} ${formation ? `<span class="mono tiny faint">${esc(formation)}</span>` : ""}</h4>
      ${starters && starters.length ? `<div class="section-title" style="margin-top:6px">CONFIRMED STARTERS</div>${starters.map((p) => `<div class="injury-row"><span class="nm">${esc(p.name)}</span><span class="tag">${esc(p.position || "")}</span>${p.shirt ? `<span class="ret">#${esc(p.shirt)}</span>` : ""}</div>`).join("")}` : `<div class="muted tiny" style="padding:4px 0 8px">Expected starting XI unavailable — no source connected. This is not an inferred lineup.</div>`}
      <div class="section-title">UNAVAILABLE / DOUBTFUL</div>
      ${(unavailable || []).length ? (unavailable || []).map((p) => `<div class="injury-row"><span class="nm">${esc(p.name)}</span><span class="ty">${esc(p.type || "out")}</span><span class="ret">${esc(p.expected_return || "")}</span></div>`).join("") : `<div class="muted tiny">No structured absences in the feed.</div>`}
    </div>`;
    return `${!confirmed ? `<div class="note-box" style="border-left-color:var(--amber);margin-top:0"><b class="amber">LINEUPS NOT CONFIRMED.</b> The prediction may change when the official XI is published. Expected lineups are not invented.</div>` : `<div class="note-box" style="border-left-color:var(--green);margin-top:0"><b class="green">CONFIRMED LINEUPS.</b> Source: FotMob match centre · ${esc(lu.fetched_at || "")}. The prediction shown was generated before/after this update as recorded in the prediction history.</div>`}
      <div class="two-col" style="margin-top:14px">
        ${teamBlock(data.fixture.home_name, lu.home_starters, inj.home, lu.home_formation)}
        ${teamBlock(data.fixture.away_name, lu.away_starters, inj.away, lu.away_formation)}
      </div>
      <div class="note-box" style="margin-top:12px">Expected lineups are unavailable unless a provider publishes them. Confirmed and reported information are visually distinct; absences come from structured match-centre data. Source timestamps are in the Data/Protocol tab.</div>`;
  }

  function protocolTab(data) {
    const f = data.fixture || {}, p = data.prediction || {}, a = p.analysis || {};
    const q = a.protocol || {};
    const dq = q.data_quality || a.data_quality || [];
    const script = q.expected_script || {};
    const players = q.key_players || [];
    const factors = q.factors || [];
    const scenarios = q.scenarios || [];
    const gaps = q.data_gaps || a.data_gaps || [];
    const improve = q.what_would_increase_confidence || [];
    return `
      <div class="note-box" style="border-left-color:var(--cyan);margin-top:0">
        <b class="cyan">MARKET-FREE FORECAST</b> · data cutoff ${esc(q.data_cutoff || p.generated_at || "—")} · policy ${esc(q.market_policy || "market-free")} · no bookmaker odds are read.
      </div>
      <div class="section-title" style="margin-top:14px">DATA QUALITY AUDIT</div>
      <div style="overflow-x:auto"><table class="signal-table">
        <thead><tr><th>CATEGORY</th><th>STATUS</th><th>PROVIDER</th><th>FRESHNESS</th><th>NOTES / MISSING</th></tr></thead>
        <tbody>${dq.length ? dq.map((x) => `<tr><td><b>${esc(x.category)}</b></td><td><span class="tag ${/confirmed|verified|structured|sourced|forecast|assigned/i.test(x.status) ? "" : "inj"}">${esc(x.status)}</span></td><td class="mono tiny">${esc(x.provider || "—")}</td><td><span class="tag">${esc(x.freshness || "unknown")}</span><div class="tiny faint">${x.last_updated ? timeAgo(x.last_updated) : "no timestamp"}</div></td><td class="tiny muted">${esc(x.notes || "")}${x.missing ? ` · <span class="amber">missing: ${esc(x.missing)}</span>` : ""}</td></tr>`).join("") : `<tr><td colspan="5" class="muted tiny">No data-quality audit stored; this dossier predates the protocol upgrade. Re-analyze.</td></tr>`}</tbody>
      </table></div>
      <div class="two-col" style="margin-top:16px">
        <div>
          <div class="section-title" style="margin-top:0">EXPECTED GAME SCRIPT</div>
          <div class="metric-grid">
            ${metric("EXPECTED TOTAL", script.expected_total ?? "—", "cyan")}
            ${metric("EXPECTED MARGIN", script.expected_margin ?? "—", "magenta")}
            ${metric("PACE", script.pace_label || "—", "")}
          </div>
          <ul class="thesis" style="margin-top:10px">
            <li><b>Likely:</b> ${esc(script.likely_scenario || "—")}</li>
            <li><b>Alternative:</b> ${esc(script.alternative_scenario || "—")}</li>
            <li><b>Upset path:</b> ${esc(script.main_upset_risk || "—")}</li>
            <li><b>Officials/weather:</b> ${esc(script.referee_weather_impact || "—")}</li>
          </ul>
        </div>
        <div>
          <div class="section-title" style="margin-top:0">SCENARIOS</div>
          ${scenarios.length ? scenarios.map((x) => `<div class="market-row" style="align-items:flex-start"><span class="lbl"><b>${esc(x.name)}</b><br/><span class="tiny muted">${esc(x.effect)}</span></span><span class="o">${esc(x.probability)}</span></div>`).join("") : `<div class="muted tiny">No scenario table stored.</div>`}
        </div>
      </div>
      <div class="section-title">KEY PLAYER AVAILABILITY</div>
      ${players.length ? `<div style="overflow-x:auto"><table class="signal-table"><thead><tr><th>TEAM</th><th>PLAYER</th><th>STATUS</th><th>RETURN</th><th>IMPACT</th><th>EVIDENCE</th></tr></thead><tbody>${players.map((x) => `<tr><td>${esc(x.team)}</td><td><b>${esc(x.player)}</b></td><td><span class="tag inj">${esc(x.status)}</span></td><td class="mono tiny">${esc(x.expected_return || "—")}</td><td class="mono tiny">${num(x.impact, 3)}</td><td class="tiny muted">${esc(x.evidence)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="note-box">${esc(q.player_projection_note || "No confirmed player-level data available.")}</div>`}
      <div class="section-title">PLAYER CORRELATIONS</div>
      <ul class="thesis">${(q.player_correlations || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>No player-correlation table stored.</li>"}</ul>
      <div class="section-title">FACTOR ATTRIBUTION</div>
      ${factors.length ? factors.map((x) => `<div class="trace-row" style="align-items:flex-start"><span class="l" style="min-width:180px"><b>${esc(x.factor)}</b><br/><span class="tiny muted">${esc(x.evidence)}</span></span><span class="tag" style="margin-left:auto">${esc(x.direction)}</span><span class="tag">${esc(x.size)}</span><span class="mono tiny faint">${esc(x.confidence)}</span></div>`).join("") : `<div class="muted tiny">No factor table stored.</div>`}
      <div class="two-col" style="margin-top:16px">
        <div><div class="section-title" style="margin-top:0">DATA GAPS</div><ul class="risk-list">${gaps.map((x) => `<li>${esc(x)}</li>`).join("") || "<li>No gaps recorded.</li>"}</ul></div>
        <div><div class="section-title" style="margin-top:0">WHAT WOULD INCREASE CONFIDENCE</div><ul class="thesis">${improve.map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul></div>
      </div>
      <div class="section-title">FINAL ASSESSMENT</div>
      <div class="verdict-box" style="padding:14px"><div class="verdict-sub" style="margin:0">${esc(q.final_assessment || a.verdict || "—")}</div></div>
      <div class="note-box" style="margin-top:14px;border-left-color:var(--amber)">${esc(q.responsible_gambling || a.responsible_gambling || "This is a probabilistic research forecast, not financial advice or a guaranteed outcome.")}</div>`;
  }

  function marketsTab(p, f) {
    const groups = {};
    for (const m of p.markets || []) (groups[m.group] ||= []).push(m);
    const labels = { result: "MATCH RESULT", double_chance: "DOUBLE CHANCE", totals: "GOALS OVER / UNDER", btts: "BOTH TEAMS TO SCORE", asian_handicap: "ASIAN HANDICAP", team_totals: "TEAM TOTALS", special: "SPECIALS", winner: "MATCH WINNER" };
    return `<div class="two-col"><div>
      ${Object.keys(groups).length ? Object.entries(groups).map(([g, ms]) => `<div class="market-group"><h4>${esc(labels[g] || g)}</h4>${ms.map((m) => `<div class="market-row"><span class="lbl">${esc(m.label)}</span><div class="mini"><span style="width:${clamp(Number(m.probability) * 100, 0, 100)}%"></span></div><span class="p">${pct(m.probability)}</span><span class="o">${num(m.fair_odds)}</span></div>`).join("")}</div>`).join("") : emptyInline("No markets generated.")}
    </div><div>
      <div class="panel" style="padding:14px"><div class="section-title" style="margin-top:0">FAIR ODDS, NOT BOOKMAKER ODDS</div><div class="verdict-sub">Every number on this page is <b>1 / P(ORACLE)</b>. A fair-odds table is a probability translation, not a market quote. ORACLE does not read or import bookmaker prices.</div></div>
      <div class="section-title">TOP CORRECT SCORES</div>
      ${((p.score_grid && p.score_grid.top_scores) || []).slice(0, 9).map((x) => `<div class="market-row"><span class="lbl mono">${esc(x.score)}</span><span class="p">${pct(x.probability)}</span><span class="o">${num(x.fair_odds)}</span></div>`).join("") || `<div class="muted tiny">Cricket dossier: projected score bands are on the Verdict tab.</div>`}
      <div class="note-box">Asian handicap probabilities are push-adjusted. Over/under lines are derived from the full score grid (0–10 goals per side).</div>
    </div></div>`;
  }

  function benchmarkTab(f) {
    return `<div class="note-box" style="border-left-color:var(--magenta);margin-top:0">
      <b class="magenta">BENCHMARK LAYER</b> · real bookmaker odds are shown for comparison only. All amounts are NPR. The core ORACLE forecast stays market-free and is not changed by these prices.
    </div>
    <div class="slip-controls" style="margin:14px 0">
      <label>STAKE<input class="input" id="benchStake" type="number" min="1" step="10" value="100" /></label>
      <button class="btn" id="benchRefresh">${ICON.refresh} REFRESH ODDS</button>
      <span class="mono tiny faint" id="benchMeta"></span>
    </div>
    <div id="benchmarkBody"><div class="skeleton" style="height:180px"></div></div>`;
  }

  async function loadBenchmark(fixtureId) {
    const stake = Math.max(1, Number($("#benchStake")?.value || 100));
    try {
      const d = await api(`/api/benchmark/${encodeURIComponent(fixtureId)}?stake=${stake}`);
      renderBenchmark(d);
    } catch (e) {
      $("#benchmarkBody").innerHTML = errorState(`Benchmark failed: ${e.message}`);
    }
    $("#benchRefresh")?.addEventListener("click", async () => {
      const b = $("#benchRefresh"); b.disabled = true; b.innerHTML = `${ICON.refresh} FETCHING…`;
      try {
        const d = await api(`/api/benchmark/${encodeURIComponent(fixtureId)}/refresh?stake=${stake}`, { method: "POST" });
        renderBenchmark(d);
      } catch (e) { toast(e.message, "err"); }
      finally { b.disabled = false; b.innerHTML = `${ICON.refresh} REFRESH ODDS`; }
    });
  }

  function renderBenchmark(d) {
    const body = $("#benchmarkBody");
    if (!body) return;
    $("#benchMeta").textContent = d.available ? `${d.provider || "book"} · ${d.source || ""} · ${d.fetched_at ? timeAgo(d.fetched_at) : ""}` : "";
    if (!d.available) {
      body.innerHTML = `<div class="panel" style="padding:18px"><div class="note-box" style="margin:0">${esc(d.message || "No benchmark odds available.")}</div></div>`;
      return;
    }
    const rows = d.rows || [];
    const best = d.best_return, bal = d.best_balanced, high = d.highest_odds, ml = d.most_likely;
    const valClass = (v) => v === "HIGH VALUE" ? "lime" : v === "MODERATE VALUE" ? "cyan" : v === "NO VALUE" || v === "INSUFFICIENT DATA" ? "muted" : "amber";
    body.innerHTML = `
      <div class="slip-summary" style="margin-bottom:14px">
        ${ml ? metric("MOST LIKELY 1X2", `${esc(ml.selection)} · ${pct(ml.model_prob)}`, "cyan") : ""}
        ${best ? metric("BEST RETURN", `${esc(best.selection)} · ${num(best.decimal, 2)}`, "cyan") : ""}
        ${best ? metric("RETURN / PROFIT", `रू ${num(best.potential_return, 2)} / रू ${num(best.potential_profit, 2)}`, "lime") : ""}
        ${bal ? metric("BEST BALANCED", `${esc(bal.selection)} · EV रू ${num(bal.ev, 2)}`, "lime") : ""}
        ${high ? metric("HIGHEST ODDS", `${esc(high.selection)} · ${num(high.decimal, 2)}`, "magenta") : ""}
        ${d.slip ? metric("ONE-LEG SLIP", `${esc(d.slip.legs[0].selection)} · ${pct(d.slip.combined_probability)} · ${num(d.slip.combined_odds, 2)}`, "lime") : ""}
      </div>
      <div class="note-box" style="margin:0 0 12px">${esc(d.note || "")}</div>
      ${d.slip ? `<div class="note-box" style="margin:0 0 12px;border-left-color:var(--lime)"><b>BENCHMARK ONE-LEG SLIP (bookmaker odds):</b> ${esc(d.slip.legs[0].selection)} at ${num(d.slip.combined_odds, 2)} · combined model probability ${pct(d.slip.combined_probability)} · रू ${num(d.stake, 0)} → रू ${num(d.slip.potential_return, 2)} return / रू ${num(d.slip.potential_profit, 2)} profit · ${d.slip.meets_threshold ? "meets 80% model threshold" : "does not meet 80% model threshold"}. This is one leg, not a padded parlay. The core Slip Lab remains model-fair-odds only.</div>` : ""}
      <div style="overflow-x:auto"><table class="signal-table">
        <thead><tr><th>MARKET</th><th>SELECTION</th><th>ODDS</th><th>IMPLIED</th><th>DE-VIG</th><th>AI P</th><th>STAKE</th><th>EDGE</th><th>EV</th><th>RETURN</th><th>PROFIT</th><th>VALUE</th><th>RISK</th></tr></thead>
        <tbody>${rows.map((r) => `<tr>
          <td class="tiny muted">${esc(r.market)}</td>
          <td><b>${esc(r.selection)}</b><div class="tiny faint">${esc(r.basis)}</div></td>
          <td class="mono">${num(r.decimal, 2)}</td>
          <td class="mono tiny">${pct(r.implied)}</td>
          <td class="mono tiny">${pct(r.devig)}</td>
          <td class="mono tiny cyan">${pct(r.model_prob)}</td>
          <td class="mono tiny">रू ${num(r.stake, 0)}</td>
          <td class="mono tiny ${Number(r.edge) >= 0 ? "lime" : "red"}">${r.edge != null ? (Number(r.edge) * 100).toFixed(1) + "pp" : "—"}</td>
          <td class="mono tiny ${Number(r.ev) >= 0 ? "lime" : "red"}">${r.ev != null ? "$" + num(r.ev, 2) : "—"}</td>
          <td class="mono tiny">रू ${num(r.potential_return, 2)}</td>
          <td class="mono tiny">रू ${num(r.potential_profit, 2)}</td>
          <td class="tiny ${valClass(r.value)}">${esc(r.value)}</td>
          <td class="tiny">${esc(r.risk)}</td>
        </tr>`).join("")}</tbody>
      </table></div>
      ${high ? `<div class="note-box" style="margin-top:12px;border-left-color:var(--magenta)"><b>HIGHEST ODDS OPTION:</b> ${esc(high.selection)} at ${num(high.decimal, 2)}. Higher odds mean a larger potential payout but a substantially lower probability of winning.</div>` : ""}
      <div class="note-box" style="margin-top:10px">EV is model probability × profit − loss probability × stake. Negative EV is not a recommendation. This benchmark does not change the market-free dossier.</div>
      <div class="note-box" style="margin-top:8px">${esc(d.selection_rule || "")}<br/>${esc(d.devig_note || "")}<br/>${esc(d.precision_note || "")}</div>`;
    $("#benchStake")?.addEventListener("change", () => loadBenchmark(d.fixture.id));
  }

  function tacticalTab(a, p, f) {
    const t = a.tactical || {};
    const home = t.home || { team: f.home_name, pros: [], cons: [] };
    const away = t.away || { team: f.away_name, pros: [], cons: [] };
    return `<div class="two-col">
      <div class="tac-card"><h4>${esc(home.team)}</h4><div class="tac-col pros"><h5>PROS</h5><ul>${(home.pros || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul></div><div class="tac-col cons"><h5>CONS</h5><ul>${(home.cons || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul></div></div>
      <div class="tac-card"><h4>${esc(away.team)}</h4><div class="tac-col pros"><h5>PROS</h5><ul>${(away.pros || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul></div><div class="tac-col cons"><h5>CONS</h5><ul>${(away.cons || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul></div></div>
    </div>
    <div class="section-title">KEY BATTLES</div><ul class="thesis">${(a.key_battles || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>No key battles recorded.</li>"}</ul>
    <div class="note-box">Tactical pros/cons are generated from the fitted match model, verified availability and the current form index. They are hypotheses to test, not scouting reports.</div>`;
  }

  function researchTab(r, f) {
    const inj = r.injury_signals || {};
    const news = r.raw?.news || {};
    const weather = r.weather || {};
    const pitch = r.pitch || {};
    const fatigue = r.fatigue || {};
    const citations = r.citations || [];
    return `<div class="research-grid">
      <div>
        <div class="section-title" style="margin-top:0">AVAILABILITY · ${esc(f.home_name)}</div>
        ${injuryList(inj.home || [])}
        <div class="section-title">AVAILABILITY · ${esc(f.away_name)}</div>
        ${injuryList(inj.away || [])}
        <div class="section-title">MATCH CONDITIONS</div>
        <div class="metric-grid">
          <div class="metric"><div class="l">Weather</div><div class="v" style="font-size:14px">${esc(weather.description || "—")}</div><div class="tiny muted">${weather.temperature_c != null ? weather.temperature_c + "°C" : ""} ${weather.wind_kph != null ? "· " + weather.wind_kph + " kph" : ""}</div></div>
          <div class="metric"><div class="l">${f.sport === "cricket" ? "Dew risk" : "Rain chance"}</div><div class="v" style="font-size:14px">${f.sport === "cricket" ? pct(pitch.dew_risk || 0) : pctRaw(weather.precip_chance, 0)}</div><div class="tiny muted">${esc((pitch.flags || []).join(", ") || "no advisory")}</div></div>
          <div class="metric"><div class="l">Venue</div><div class="v" style="font-size:14px">${esc((r.raw?.venue?.stats?.avg_first_innings) || "—")}</div><div class="tiny muted">avg first inns</div></div>
        </div>
        <div class="section-title">FATIGUE / REST</div>
        <div class="metric-grid">
          <div class="metric"><div class="l">${esc(f.home_name)} rest</div><div class="v" style="font-size:16px">${fatigue.home?.rest_days != null ? fatigue.home.rest_days + "d" : "—"}</div><div class="tiny muted">${fatigue.home?.matches_21d ?? 0} in 21d</div></div>
          <div class="metric"><div class="l">${esc(f.away_name)} rest</div><div class="v" style="font-size:16px">${fatigue.away?.rest_days != null ? fatigue.away.rest_days + "d" : "—"}</div><div class="tiny muted">${fatigue.away?.matches_21d ?? 0} in 21d</div></div>
        </div>
      </div>
      <div>
        <div class="section-title" style="margin-top:0">NEWS SIGNALS</div>
        ${newsList(news.home, f.home_name)}
        ${newsList(news.away, f.away_name)}
        <div class="section-title">CITATIONS</div>
        <div style="display:flex;flex-direction:column;gap:6px;max-height:220px;overflow:auto">
          ${citations.length ? citations.slice(0, 14).map((c) => `<a class="source-pill" href="${esc(c.url)}" target="_blank" rel="noopener" style="justify-content:space-between">${esc(c.source || "source")} · ${esc(c.title || "link")} ${ICON.external}</a>`).join("") : `<span class="muted tiny">No citations recorded for this fixture.</span>`}
        </div>
      </div>
    </div>
    <div class="note-box">Research grade ${esc(r.depth || "model")}. Structured availability is authoritative when present; news-derived signals are weaker and labelled. Re-analyze after confirmed line-ups.</div>`;
  }

  function injuryList(players) {
    if (!players || !players.length) return `<div class="muted tiny" style="padding:4px 0 8px">No confirmed absences in the structured feed.</div>`;
    return players.map((p) => `<div class="injury-row"><span class="nm">${esc(p.name)}</span><span class="ty">${esc(p.type || "out")}</span><span class="ret">${esc(p.expected_return || "")}</span></div>`).join("");
  }

  function newsList(items, team) {
    if (!items || !items.length) return `<div class="muted tiny" style="padding:4px 0 10px">No recent injury/tactical signal found for ${esc(team)}.</div>`;
    return items.slice(0, 4).map((n) => `<div class="news-item"><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a><div class="news-meta"><span>${esc(n.source || "news")}</span><span>${n.published ? timeAgo(n.published) : ""}</span>${(n.tags || []).slice(0, 2).map((t) => `<span class="news-tag">${esc(t)}</span>`).join("")}</div></div>`).join("");
  }

  function modelTab(p, r, a, f, m) {
    const feats = p.features || {};
    const grid = p.score_grid || {};
    const trace = a.model_trace || [];
    const maxTrace = Math.max(1, ...trace.map((x) => Math.abs(parseFloat(String(x.value).split(" ")[0]) || 0)));
    return `<div class="metric-hero">
      ${metric("HOME PROB", pct(p.home_prob), "cyan")}
      ${metric("DRAW PROB", pct(p.draw_prob), "muted")}
      ${metric("AWAY PROB", pct(p.away_prob), "magenta")}
      ${metric("CONFIDENCE", `${m.conf.toFixed(0)}/100`, confColor(m.conf))}
    </div>
    <div class="metric-grid" style="margin-top:8px">
      ${metric("CALIBRATION WEIGHT", feats.confidence_detail?.calibration != null ? Number(feats.confidence_detail.calibration).toFixed(2) : "—", "")}
      ${metric("MARKETS GENERATED", (p.markets || []).length, "")}
      ${metric("EDGE QUALITY", esc(a.edge_quality || "—"), "")}
    </div>
    <div class="two-col" style="margin-top:16px">
      <div>
        <div class="section-title" style="margin-top:0">MODEL INPUTS</div>
        <div class="metric-grid">
          ${metric("HOME xG", num(p.expected_home), "")}
          ${metric("AWAY xG", num(p.expected_away), "")}
          ${metric("HOME ATTACK", num(feats.home_attack), "")}
          ${metric("HOME DEFENCE", num(feats.home_defence), "")}
          ${metric("AWAY ATTACK", num(feats.away_attack), "")}
          ${metric("AWAY DEFENCE", num(feats.away_defence), "")}
          ${metric("HOME ADV", num(feats.home_advantage), "")}
          ${metric("RHO", num(feats.rho), "")}
          ${metric(f.sport === "cricket" ? "FORMAT" : "LEAGUE AVG", f.sport === "cricket" ? esc(feats.format || "—") : num(feats.league_goals_avg), "")}
        </div>
        <div class="section-title">TRACE</div>
        ${trace.map((x) => {
          const v = parseFloat(String(x.value).split(" ")[0]) || 0;
          return `<div class="trace-row"><span class="l">${esc(x.label)}</span><span class="v">${esc(x.value)}</span><div class="bar"><span style="width:${clamp((Math.abs(v) / maxTrace) * 100, 2, 100)}%"></span></div></div>`;
        }).join("") || `<div class="muted tiny">No trace recorded.</div>`}
      </div>
      <div>
        <div class="section-title" style="margin-top:0">ENGINE PROVENANCE</div>
        <div class="verdict-box" style="padding:14px"><div class="mono tiny muted">MODEL</div><div style="font-size:13px;margin-bottom:8px">${esc(p.model_version || "oracle-dc-mc")}</div><div class="mono tiny muted">GENERATED</div><div style="font-size:13px;margin-bottom:8px">${esc(p.generated_at || "—")}</div><div class="mono tiny muted">DATA DEPTH</div><div style="font-size:13px">${esc(p.data_depth || "model")} · grade ${esc(a.research_grade || "C")}</div></div>
        <div class="section-title">PREDICTION HISTORY</div>
        ${(() => { const hist = state.active?.history || []; return hist.length ? `<div style="overflow-x:auto"><table class="signal-table"><thead><tr><th>CREATED</th><th>MODEL</th><th>H / D / A</th><th>PICK</th><th>LINEUPS</th></tr></thead><tbody>${hist.map((x) => `<tr><td class="mono tiny">${esc((x.created_at || "").replace("T", " ").slice(0, 16))}</td><td class="mono tiny">${esc(x.model_version || "")}</td><td class="mono tiny">${pct(x.home_prob)} / ${pct(x.draw_prob)} / ${pct(x.away_prob)}</td><td class="tiny">${esc(x.pick || "—")} <span class="faint">${pct(x.pick_prob)}</span></td><td><span class="tag">${esc(x.lineups_status || "—")}</span></td></tr>`).join("")}</tbody></table></div><div class="note-box">Revisions are appended, not overwritten. The latest row is the current prediction; older rows preserve the inputs and probabilities at that time.</div>` : `<div class="muted tiny">No revision history stored yet.</div>`; })()}
        <div class="section-title">WHAT THIS MODEL DOES NOT DO</div>
        <ul class="risk-list">
          <li>It does not read, scrape or infer bookmaker odds.</li>
          <li>It does not treat an unconfirmed news rumour as a confirmed absence.</li>
          <li>It does not guarantee a result. Probabilities are calibrated beliefs, not certainties.</li>
          <li>It does not use a market-implied prior anywhere in the pipeline.</li>
        </ul>
        <div class="section-title">PROBABILITY GRID</div>
        <div class="market-row"><span class="lbl">Score grid cells</span><span class="p">${grid.grid ? `${grid.grid.length} × ${grid.grid[0]?.length || 0}` : "—"}</span></div>
        <div class="market-row"><span class="lbl">Top scoreline</span><span class="p">${esc((grid.top_scores || [])[0]?.score || "—")}</span></div>
        <div class="market-row"><span class="lbl">Markets generated</span><span class="p">${(p.markets || []).length}</span></div>
      </div>
    </div>`;
  }

  function metric(l, v, color) {
    return `<div class="metric"><div class="l">${esc(l)}</div><div class="v ${color || ""}">${v ?? "—"}</div></div>`;
  }

  function confColor(c) { return c >= 72 ? "green" : c >= 55 ? "amber" : "red"; }

  function bindDossierActions(data) {
    $$("[data-act]").forEach((b) => {
      b.onclick = async () => {
        const act = b.dataset.act;
        const p = data.prediction || {};
        if (act === "copy") {
          const txt = `ORACLE · ${data.fixture.home_name} v ${data.fixture.away_name} · ${p.pick} ${pct(p.pick_prob)} (fair ${num(p.pick_fair)}) · ${data.fixture.kickoff_utc}`;
          copyText(txt);
        }
        if (act === "watch") {
          const r = await api(`/api/watch/${encodeURIComponent(data.fixture.id)}`, { method: "POST" });
          data.watchlisted = r.watchlisted;
          b.innerHTML = `${ICON.star} ${r.watchlisted ? "SAVED" : "WATCH"}`;
          b.style.color = r.watchlisted ? "var(--amber)" : "";
          toast(r.watchlisted ? "Added to watchlist" : "Removed from watchlist");
        }
        if (act === "reanalyze") {
          b.disabled = true; b.innerHTML = `${ICON.refresh} ANALYSING…`;
          try {
            await api(`/api/fixtures/${encodeURIComponent(data.fixture.id)}/analyze`, { method: "POST" });
            const fresh = await api(`/api/fixtures/${encodeURIComponent(data.fixture.id)}`);
            state.active = fresh;
            renderDossier(fresh);
            toast("Dossier refreshed with the latest research");
            loadOverview(true);
          } catch (e) { toast(`Re-analysis failed: ${e.message}`, "err"); b.disabled = false; b.innerHTML = `${ICON.refresh} RE-ANALYZE`; }
        }
      };
    });
  }

  function drawHeatmap() {
    const canvas = $("#scoreHeatmap");
    const data = state.active;
    if (!canvas || !data) return;
    const grid = data.prediction?.score_grid?.grid;
    if (!grid || !grid.length) return;
    const ctx = canvas.getContext("2d");
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = canvas.clientWidth || 460, H = canvas.clientHeight || 360;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = grid.length;
    const padL = 30, padB = 24, padT = 8, padR = 8;
    const cw = (W - padL - padR) / n, ch = (H - padB - padT) / n;
    const max = Math.max(...grid.flat()) || 1;
    ctx.clearRect(0, 0, W, H);
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const v = grid[i][j] / max;
        ctx.fillStyle = colorScale(v);
        ctx.fillRect(padL + j * cw, padT + i * ch, cw - 1, ch - 1);
        if (v > 0.55) {
          ctx.fillStyle = "rgba(4,8,14,.85)";
          ctx.font = `${Math.max(7, Math.min(10, cw * 0.42))}px "JetBrains Mono", monospace`;
          ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.fillText((grid[i][j] * 100).toFixed(1), padL + j * cw + cw / 2, padT + i * ch + ch / 2);
        }
      }
    }
    ctx.fillStyle = "rgba(127,149,171,.8)";
    ctx.font = '8px "JetBrains Mono", monospace';
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (let j = 0; j < n; j++) ctx.fillText(String(j), padL + j * cw + cw / 2, H - padB + 6);
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (let i = 0; i < n; i++) ctx.fillText(String(i), padL - 8, padT + i * ch + ch / 2);
    ctx.save();
    ctx.translate(10, H / 2); ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center"; ctx.fillStyle = "rgba(111,247,255,.6)";
    ctx.fillText(data.fixture.home_name, 0, 0);
    ctx.restore();
    ctx.save();
    ctx.translate(W - 2, H / 2); ctx.rotate(Math.PI / 2);
    ctx.textAlign = "center"; ctx.fillStyle = "rgba(255,92,207,.6)";
    ctx.fillText(data.fixture.away_name, 0, 0);
    ctx.restore();
  }

  function colorScale(v) {
    v = clamp(v, 0, 1);
    if (v < 0.5) {
      const t = v / 0.5;
      return `rgb(${Math.round(7 + t * 25)},${Math.round(14 + t * 80)},${Math.round(22 + t * 110)})`;
    }
    const t = (v - 0.5) / 0.5;
    return `rgb(${Math.round(32 + t * 190)},${Math.round(94 + t * 130)},${Math.round(132 + t * 90)})`;
  }

  // ------------------------------------------------------------------ research view
  async function renderResearch() {
    const view = $("#view");
    view.innerHTML = `<div class="page-head"><div><div class="eyebrow">RESEARCH SIGNALS</div><h1 class="page-title">Evidence, not vibes.</h1><p class="page-sub">Availability, news, weather, pitch and fatigue signals attached to the highest-priority fixtures. Every signal is bounded and sourced.</p></div><div class="page-actions"><button class="btn" onclick="ORACLE.runSync()">${ICON.refresh} REFRESH RESEARCH</button></div></div>
      <div class="panel" style="padding:18px;margin-bottom:16px"><div class="metric-grid">
        <div class="metric"><div class="l">Full dossiers</div><div class="v" id="rFull">—</div></div>
        <div class="metric"><div class="l">Enhanced</div><div class="v" id="rEnh">—</div></div>
        <div class="metric"><div class="l">Model only</div><div class="v" id="rMod">—</div></div>
      </div></div>
      <div id="researchGrid" class="fixture-grid">${fixtureSkeletons(6)}</div>`;
    try {
      const [ov, data] = await Promise.all([loadOverview(true), api("/api/fixtures?days=7&sort=importance&limit=60")]);
      const d = ov?.depth || {};
      $("#rFull").textContent = d.full || 0; $("#rEnh").textContent = d.enhanced || 0; $("#rMod").textContent = d.model || 0;
      const items = (data.items || []).filter((x) => (Array.isArray(x.flags) && x.flags.length) || x.data_depth === "full" || x.data_depth === "enhanced").slice(0, 24);
      $("#researchGrid").innerHTML = items.length ? items.map((f) => {
        const flags = Array.isArray(f.flags) ? f.flags : [];
        return `<article class="fx-card" onclick="ORACLE.open('${esc(f.id)}')">
          <div class="fx-top"><div class="fx-comp"><span>${esc(f.competition_name || "—")}</span></div><div class="fx-time">${fmtDay(f.kickoff_utc)}</div></div>
          <div class="fx-teams"><div class="fx-team">${crest(f.home_name, f.sport, f.home_logo)}<span>${esc(f.home_name)}</span></div><div class="fx-team">${crest(f.away_name, f.sport, f.away_logo)}<span>${esc(f.away_name)}</span></div></div>
          <div class="fx-tags">${flags.map((x) => `<span class="tag ${/injur|absence|suspens/i.test(x) ? "inj" : "hot"}">${esc(x)}</span>`).join("") || `<span class="tag">${esc(f.data_depth || "model")}</span>`}</div>
          <div class="fx-bottom"><span class="mono tiny muted">${esc(f.headline || "")}</span><span class="conf"><i class="conf-dot ${Number(f.confidence) >= 60 ? "HIGH" : "MEDIUM"}"></i>${Math.round(Number(f.confidence) || 0)}</span></div>
        </article>`;
      }).join("") : emptyState("No enriched research yet.", "Run a cycle to populate availability, news and venue signals.");
    } catch (e) {
      $("#researchGrid").innerHTML = errorState(e.message);
    }
  }

  // ------------------------------------------------------------------ team page
  async function renderTeam(teamId) {
    const view = $("#view");
    view.innerHTML = `<div class="panel" style="padding:20px"><div class="skeleton" style="height:70px"></div><div class="skeleton" style="height:180px;margin-top:14px"></div></div>`;
    try {
      const d = await api(`/api/teams/${encodeURIComponent(teamId)}`);
      const t = d.team || {}, c = d.card || {}, r = d.rating || {}, form = c.form || {};
      const seq = form.sequence || "";
      const next = d.upcoming || [];
      const recent = d.recent || [];
      view.innerHTML = `
        <div class="panel team-hero">
          ${crest(t.name, t.sport, t.logo, "team-crest")}
          <div style="flex:1;min-width:220px">
            <div class="eyebrow">${esc(t.sport || "")}${t.country ? " · " + esc(t.country) : ""}</div>
            <h1>${esc(t.name)}</h1>
            <div class="form-chips" style="margin-top:8px">${seq.split("").map((x) => `<span class="form-chip ${x}">${x}</span>`).join("") || `<span class="muted tiny">No recent form</span>`}</div>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn" onclick="ORACLE.searchGrid('${esc(t.name).replace(/'/g, "\\'")}')">${ICON.search} FIXTURES</button>
            <button class="btn" onclick="history.back()">${ICON.arrow} BACK</button>
          </div>
        </div>
        <div class="metric-grid" style="margin:16px 0">
          ${metric("ELO", r.elo != null ? Math.round(r.elo) : "—", "cyan")}
          ${metric("ATTACK", num(r.attack, 3), "")}
          ${metric("DEFENCE", num(r.defence, 3), "")}
          ${metric("MATCHES", r.matches ?? "—", "")}
          ${metric("W-D-L", `${form.wins || 0}-${form.draws || 0}-${form.losses || 0}`, "")}
          ${metric("NEXT", next.length ? fmtDay(next[0].kickoff_utc) : "—", "")}
        </div>
        <div class="dashboard-grid">
          <section class="panel"><div class="panel-head"><span class="panel-title">// UPCOMING FIXTURES</span><span class="mono tiny faint">${next.length}</span></div><div class="panel-body" style="display:flex;flex-direction:column;gap:8px">
            ${next.length ? next.map((x) => `<div class="market-row" style="cursor:pointer" onclick="ORACLE.open('${esc(x.id)}')"><span class="lbl"><b>${esc(x.home_name)} v ${esc(x.away_name)}</b><br/><span class="tiny muted">${esc(x.competition_name || "")} · ${fmtKick(x.kickoff_utc)}</span></span><span class="p">${esc(x.pick || "—")}</span><span class="o">${pct(x.pick_prob)}</span><span class="tag">${esc(x.data_depth || "")}</span></div>`).join("") : `<div class="muted tiny">No upcoming fixtures in the current window.</div>`}
          </div></section>
          <section class="panel"><div class="panel-head"><span class="panel-title">// RECENT RESULTS</span><span class="mono tiny faint">${recent.length}</span></div><div class="panel-body" style="display:flex;flex-direction:column;gap:8px">
            ${recent.length ? recent.map((x) => `<div class="market-row"><span class="lbl"><b>${esc(x.home_name)} v ${esc(x.away_name)}</b><br/><span class="tiny muted">${esc(x.competition_name || "")} · ${fmtDate(x.kickoff_utc)}</span></span><span class="o">${x.home_score_num != null ? `${x.home_score_num}–${x.away_score_num}` : esc(x.score_detail || "—")}</span></div>`).join("") : `<div class="muted tiny">No completed fixtures.</div>`}
          </div></section>
        </div>
        <div class="section-title">COMPETITIONS</div>
        <div class="fx-tags">${(d.competitions || []).map((x) => `<span class="tag">${esc(x.name)} · ${x.n}</span>`).join("") || `<span class="tag">none</span>`}</div>`;
    } catch (e) {
      view.innerHTML = errorState(`Team not found: ${e.message}`);
    }
  }

  // ------------------------------------------------------------------ review
  async function renderReview() {
    const view = $("#view");
    view.innerHTML = `<div class="page-head"><div><div class="eyebrow">POST-MATCH REVIEW</div><h1 class="page-title">Did the process survive contact?</h1><p class="page-sub">Every settled forecast is compared with the stored pre-match prediction. No post-match information enters the forecast. This is the calibration ledger, not a highlight reel.</p></div><div class="page-actions"><button class="btn btn-primary" id="settleNow">${ICON.refresh} SETTLE FINISHED</button><a class="btn" href="/api/review" target="_blank">${ICON.external} RAW JSON</a></div></div><div id="reviewContent">${labSkeleton()}</div>`;
    $("#settleNow")?.addEventListener("click", async () => {
      const b = $("#settleNow"); b.disabled = true; b.innerHTML = `${ICON.refresh} SETTLING…`;
      try { const r = await api("/api/settle", { method: "POST" }); toast(`Settled ${r.settled} forecasts`); await renderReview(); }
      catch (e) { toast(e.message, "err"); b.disabled = false; b.innerHTML = `${ICON.refresh} SETTLE FINISHED`; }
    });
    try {
      const d = await api("/api/review?limit=40");
      const o = d.overall || {};
      const sportRows = Object.entries(d.by_sport || {});
      const confRows = Object.entries(d.by_confidence || {});
      const cal = d.calibration || [];
      const base = d.baseline || {};
      const dr = d.date_range || {};
      $("#reviewContent").innerHTML = `
        <div class="metric-hero" style="margin-bottom:16px">
          ${metric("SETTLED", d.settled ?? 0, "cyan")}
          ${metric("GUARDED", d.valid ?? 0, "lime")}
          ${metric("LEGACY", d.legacy ?? 0, "amber")}
          ${metric("ACCURACY", o.accuracy != null ? pct(o.accuracy) : "—", "lime")}
          ${metric("BRIER", o.brier != null ? num(o.brier, 4) : "—", "magenta")}
          ${metric("LOG LOSS", o.log_loss != null ? num(o.log_loss, 4) : "—", "cyan")}
          ${metric("HOME BASELINE", base.home_always_accuracy != null ? pct(base.home_always_accuracy) : "—", "muted")}
          ${metric("PENDING", d.pending ?? 0, "amber")}
        </div>
        <div class="note-box" style="margin:-6px 0 16px">Evaluation window (${esc(dr.basis || "—")}): ${dr.from ? fmtDate(dr.from) : "—"} → ${dr.to ? fmtDate(dr.to) : "—"} · ${esc(base.definition || "Baseline definition unavailable.")} · History-guarded rows: ${d.guarded ?? 0}; legacy/unguarded: ${d.legacy ?? 0}. Legacy rows predate the pre-kickoff revision guard and are excluded from live calibration.</div>
        ${!(d.valid) ? `<div class="panel" style="padding:20px;margin-bottom:16px"><div class="note-box" style="margin:0">No <b>history-guarded</b> settlements yet. ${d.legacy ? `${d.legacy} legacy rows are shown for audit only and are excluded from headline metrics because no pre-kickoff revision snapshot exists.` : "ORACLE only settles matches after they finish; it does not retroactively rewrite the pre-match call."} As new matches settle with the pre-kickoff history guard, the metrics and calibration fill automatically.</div></div>` : ""}
        <div class="lab-grid">
          <div class="stack">
            <section class="panel"><div class="panel-head"><span class="panel-title">// RECENT SETTLEMENTS</span><span class="mono tiny faint">${d.recent?.length || 0} rows</span></div><div class="panel-body" style="overflow-x:auto">
              <table class="signal-table"><thead><tr><th>FIXTURE</th><th>ACTUAL</th><th>PICK</th><th>P(ACTUAL)</th><th>RESULT</th><th>BRIER</th><th>DEPTH</th></tr></thead><tbody>
                ${(d.recent || []).length ? d.recent.map((x) => `<tr><td><div class="match-cell"><b>${esc(x.home)} <span class="faint">v</span> ${esc(x.away)}</b><span>${esc(x.competition || "—")} · ${x.kickoff ? timeAgo(x.kickoff) : ""}</span></div></td><td><span class="tag">${esc(x.actual)}</span></td><td>${esc(x.pick || "—")}</td><td class="mono">${pct(x.model_prob)}</td><td>${x.excluded ? `<span class="tag">EXCLUDED</span>` : x.legacy ? `<span class="tag">LEGACY</span>` : x.pick_correct ? `<span class="lime mono tiny">CORRECT</span>` : `<span class="red mono tiny">MISS</span>`}</td><td class="mono tiny">${x.brier != null ? num(x.brier, 3) : "—"}</td><td><span class="tag">${esc(x.depth || "—")}</span></td></tr>`).join("") : `<tr><td colspan="7" class="muted tiny">No settlements yet.</td></tr>`}
              </tbody></table>
            </div></section>
            <section class="panel"><div class="panel-head"><span class="panel-title">// BY COMPETITION</span><span class="mono tiny faint">TOP SAMPLE</span></div><div class="panel-body"><div class="market-group">
              ${(d.by_competition || []).length ? d.by_competition.map((x) => `<div class="market-row"><span class="lbl">${esc(x.competition)}</span><span class="p">${x.n}</span><span class="o">${x.accuracy != null ? pct(x.accuracy, 0) : "—"}</span><span class="o">B ${x.brier != null ? num(x.brier, 3) : "—"}</span></div>`).join("") : `<div class="muted tiny">No settled sample.</div>`}
            </div></div></section>
          </div>
          <div class="stack">
            <section class="panel"><div class="panel-head"><span class="panel-title">// BY SPORT</span></div><div class="panel-body"><div class="market-group">
              ${sportRows.length ? sportRows.map(([k, v]) => `<div class="market-row"><span class="lbl">${esc(k)}</span><span class="p">${v.n}</span><span class="o">${v.accuracy != null ? pct(v.accuracy, 0) : "—"}</span><span class="o">B ${v.brier != null ? num(v.brier, 3) : "—"}</span></div>`).join("") : `<div class="muted tiny">—</div>`}
            </div></div></section>
            <section class="panel"><div class="panel-head"><span class="panel-title">// BY CONFIDENCE</span></div><div class="panel-body"><div class="market-group">
              ${confRows.length ? confRows.map(([k, v]) => `<div class="market-row"><span class="lbl">${esc(k)}</span><span class="p">${v.n}</span><span class="o">${v.accuracy != null ? pct(v.accuracy, 0) : "—"}</span><span class="o">B ${v.brier != null ? num(v.brier, 3) : "—"}</span></div>`).join("") : `<div class="muted tiny">—</div>`}
            </div></div></section>
            <section class="panel"><div class="panel-head"><span class="panel-title">// CALIBRATION · PICK PROBABILITY VS REALISED</span><span class="mono tiny faint">${cal.length} bins</span></div><div class="panel-body">
              ${cal.length ? cal.map((x) => `<div class="bar-row"><span>${(x.bin_low * 100).toFixed(0)}–${(x.bin_high * 100).toFixed(0)}% <span class="faint">(${x.n})</span></span><div class="bar"><span style="width:${clamp(x.accuracy * 100, 2, 100)}%"></span><i style="left:${clamp(x.avg_pred * 100, 0, 99)}%"></i></div><span class="v">${pct(x.accuracy, 0)}</span></div>`).join("") : `<div class="muted tiny">Calibration begins with new settlements that store the pick probability. Older rows cannot be reconstructed without using post-match information.</div>`}
              <div class="mono tiny faint" style="margin-top:6px">bar = realised accuracy · white marker = mean predicted pick probability. Live calibration starts with new settlements; the 8,004-match walk-forward calibration is in the Model Lab.</div>
            </div></section>
            <section class="panel"><div class="panel-head"><span class="panel-title">// HONESTY NOTE</span></div><div class="panel-body"><div class="note-box" style="margin:0">${esc(d.sample_warning || "Small samples are noisy.")}</div><div class="note-box" style="margin-top:10px">${esc(d.note || "")}</div></div></section>
          </div>
        </div>`;
    } catch (e) { $("#reviewContent").innerHTML = errorState(e.message); }
  }

  // ------------------------------------------------------------------ watch
  async function renderWatch() {
    const view = $("#view");
    view.innerHTML = `<div class="page-head"><div><div class="eyebrow">WATCHLIST</div><h1 class="page-title">Your board.</h1><p class="page-sub">Fixtures you are tracking across the rolling window. Re-analyze any dossier after line-ups drop.</p></div><div class="page-actions"><a class="btn" href="/api/export?days=30">${ICON.download} EXPORT</a></div></div><div id="watchGrid" class="fixture-grid">${fixtureSkeletons(3)}</div>`;
    try {
      const data = await api("/api/fixtures?watchlist=true&days=30&limit=100&sort=kickoff");
      $("#watchGrid").innerHTML = (data.items || []).length ? data.items.map(fxCard).join("") : emptyState("Watchlist is empty.", "Open any dossier and press WATCH to pin it here.");
    } catch (e) { $("#watchGrid").innerHTML = errorState(e.message); }
  }

  // ------------------------------------------------------------------ slip lab
  async function renderSlip() {
    const view = $("#view");
    view.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">MODEL SLIP LAB · FAIR ODDS ONLY</div><h1 class="page-title">Build the slip the model can defend.</h1><p class="page-sub">All amounts are in Nepali rupees (NPR). This builder uses ORACLE model probabilities and fair odds = 1 / P. It never reads bookmaker odds, never pads legs to inflate payout, and never fakes a 90% slip.</p></div><div class="page-actions"><button class="btn" onclick="location.hash='#/lab'">${ICON.activity} MODEL LAB</button></div></div>
      <div class="panel slip-hero">
        <div class="slip-controls">
          <label>STAKE<input class="input" id="slipStake" type="number" min="1" step="10" value="${state.slip?.stake || 100}" /></label>
          <label>TARGET PROBABILITY<select class="select" id="slipThreshold">${[70,80,85,90,95].map((x) => `<option value="${x}" ${Math.round((state.slip?.threshold || 0.9) * 100) === x ? "selected" : ""}>${x}%</option>`).join("")}</select></label>
          <label>SPORT<select class="select" id="slipSport"><option value="">ALL</option><option value="football">FOOTBALL</option><option value="cricket">CRICKET</option></select></label>
          <label>WINDOW<select class="select" id="slipDays">${[1,3,7,14].map((x) => `<option value="${x}" ${x === 7 ? "selected" : ""}>${x}D</option>`).join("")}</select></label>
          <button class="btn btn-primary" id="buildSlip">${ICON.activity} BUILD SLIP</button>
        </div>
        <div class="note-box" style="margin:0;max-width:340px">All amounts are NPR. Fair odds are a probability translation, not a bookmaker quote. Market implied probability, de-vig, CLV and market EV are unavailable by policy.</div>
      </div>
      <div id="slipContent" style="margin-top:16px">${slipSkeleton()}</div>`;
    $("#buildSlip")?.addEventListener("click", buildSlip);
    $$(".slip-controls input, .slip-controls select").forEach((el) => el.addEventListener("change", buildSlip));
    if (!state.slip) await buildSlip();
    else renderSlipContent();
  }

  function slipSkeleton() {
    return `<div class="panel" style="padding:20px"><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:80px;margin-top:12px"></div></div>`;
  }

  async function buildSlip() {
    const stake = Math.max(1, Number($("#slipStake")?.value || 100));
    const threshold = Number($("#slipThreshold")?.value || 90);
    const sport = $("#slipSport")?.value || "";
    const days = Number($("#slipDays")?.value || 7);
    const btn = $("#buildSlip");
    if (btn) { btn.disabled = true; btn.innerHTML = `${ICON.refresh} BUILDING…`; }
    try {
      const params = new URLSearchParams({ stake, threshold, days });
      if (sport) params.set("sport", sport);
      state.slip = await api(`/api/slip?${params}`);
      renderSlipContent();
    } catch (e) {
      $("#slipContent").innerHTML = errorState(`Slip failed: ${e.message}`);
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = `${ICON.activity} BUILD SLIP`; }
    }
  }

  function renderSlipContent() {
    const s = state.slip;
    if (!s) return;
    const legs = s.legs || [];
    const weakest = s.weakest_leg || {};
    $("#slipContent").innerHTML = `
      ${legs.length ? "" : `<div class="panel" style="padding:20px;margin-bottom:14px"><div class="note-box" style="margin:0">${esc(s.message || "No slip available.")}</div></div>`}
      ${legs.length && !s.meets_threshold ? `<div class="panel" style="padding:16px;margin-bottom:14px;border-color:rgba(255,200,87,.35)"><div class="note-box" style="margin:0;border-left-color:var(--amber)"><b class="amber">THRESHOLD NOT MET.</b> ${esc(s.message)}</div></div>` : ""}
      ${legs.length ? `
      <div class="panel"><div class="panel-head"><span class="panel-title">// SLIP LEGS</span><span class="mono tiny faint">${legs.length} leg${legs.length === 1 ? "" : "s"} · minimum needed for this target</span></div><div class="panel-body">
        ${legs.map((l, i) => `<div class="slip-leg"><div><div class="match">${i + 1}. ${esc(l.match)}</div><div class="meta">${esc(l.competition || "")} · ${esc(l.market)} · ${fmtKick(l.kickoff)}</div><div class="meta">${esc(l.reason)}</div></div><div><div class="mono tiny faint">SELECTION</div><div style="font-size:13px;font-weight:600">${esc(l.selection)}</div></div><div><div class="mono tiny faint">MODEL P</div><div class="num cyan">${pct(l.probability)}</div></div><div><div class="mono tiny faint">FAIR ODDS</div><div class="num">${num(l.fair_odds, 2)}</div></div></div>`).join("")}
      </div></div>
      <div class="panel" style="margin-top:16px"><div class="panel-head"><span class="panel-title">// SLIP MATHEMATICS</span><span class="mono tiny ${s.meets_threshold ? "green" : "amber"}">${s.meets_threshold ? "THRESHOLD MET" : "THRESHOLD NOT MET"}</span></div><div class="panel-body">
        <div class="slip-summary">
          ${metric("LEGS", legs.length, "cyan")}
          ${metric("COMBINED P", pct(s.combined_probability), "lime")}
          ${metric("TOTAL FAIR ODDS", num(s.combined_fair_odds, 2), "magenta")}
          ${metric("STAKE", `रू ${num(s.stake, 0)}`, "")}
          ${metric("POTENTIAL RETURN", `रू ${num(s.potential_return, 2)}`, "cyan")}
          ${metric("POTENTIAL PROFIT", `रू ${num(s.potential_profit, 2)}`, "lime")}
          ${metric("TARGET", `${Math.round((s.threshold || 0) * 100)}%`, "")}
          ${metric("RISK", esc(s.risk || "—"), "amber")}
        </div>
        <div class="two-col" style="margin-top:14px">
          <div><div class="section-title" style="margin-top:0">WHY THIS SLIP</div><ul class="thesis">
            <li>Each leg is the model's highest research-weighted result probability for its fixture.</li>
            <li>Adding legs multiplies the probability down; this builder does not pad the slip to raise payout.</li>
            <li>${s.meets_threshold ? "The combined model probability meets your target." : `No combination can exceed the best single leg (${pct(weakest.probability)}), so the ${Math.round((s.threshold || 0) * 100)}% target is not met.`}</li>
            <li>Weakest leg: ${esc(weakest.match || "—")} · ${pct(weakest.probability)}.</li>
          </ul></div>
          <div><div class="section-title" style="margin-top:0">RISK & DATA</div><ul class="risk-list">
            <li>Combined probability is a product, not a guarantee.</li>
            <li>Research depth mix: ${Object.entries(s.data_quality || {}).filter(([, v]) => v).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"}.</li>
            <li>${esc(s.market_note || "No bookmaker odds used.")}</li>
            <li>Lineup, injury, weather or market changes can invalidate this slip. Re-run before acting.</li>
          </ul></div>
        </div>
        <div class="note-box" style="margin-top:14px;border-left-color:var(--amber)">This slip is based on probability, not certainty. Even a 90% estimated probability means the slip may still lose roughly 1 in 10 times over a large sample. Never wager more than you can afford to lose.</div>
      </div></div>` : ""}
    `;
  }

  // ------------------------------------------------------------------ lab
  async function renderLab() {
    const view = $("#view");
    view.innerHTML = `<div class="page-head"><div><div class="eyebrow">MODEL LABORATORY</div><h1 class="page-title">Measure the model, not the marketing.</h1><p class="page-sub">Out-of-sample walk-forward evaluation of the football engine. Hold-out window: the last 30 days of finished matches.</p></div><div class="page-actions"><button class="btn btn-primary" id="runBacktest">${ICON.activity} RUN BACKTEST</button></div></div>
      <div id="labContent">${labSkeleton()}</div>`;
    $("#runBacktest")?.addEventListener("click", () => runBacktest(true));
    if (!state.backtest) await runBacktest(false);
    else renderLabContent();
  }

  function labSkeleton() {
    return `<div class="lab-grid"><div class="panel" style="padding:20px"><div class="skeleton" style="height:90px"></div><div class="skeleton" style="height:160px;margin-top:14px"></div></div><div class="panel" style="padding:20px"><div class="skeleton" style="height:240px"></div></div></div>`;
  }

  async function runBacktest(showToast) {
    state.backtestLoading = true;
    const btn = $("#runBacktest");
    if (btn) { btn.disabled = true; btn.innerHTML = `${ICON.refresh} RUNNING…`; }
    try {
      state.backtest = await api("/api/backtest?days=30");
      renderLabContent();
      if (showToast) toast("Backtest completed");
    } catch (e) {
      $("#labContent").innerHTML = errorState(`Backtest failed: ${e.message}`);
    } finally {
      state.backtestLoading = false;
      if (btn) { btn.disabled = false; btn.innerHTML = `${ICON.activity} RUN BACKTEST`; }
    }
  }

  function renderLabContent() {
    const b = state.backtest;
    if (!b) return;
    const cal = b.calibration || [];
    const maxN = Math.max(1, ...cal.map((x) => x.n || 0));
    $("#labContent").innerHTML = `
      <div class="lab-grid">
        <div class="stack">
          <section class="panel"><div class="panel-head"><span class="panel-title">// OUT-OF-SAMPLE SCORECARD</span><span class="mono tiny faint">${b.test_matches} test matches · ${b.training_matches} training</span></div><div class="panel-body">
            <div class="metric-hero">
              ${metric("BRIER SCORE", num(b.brier, 4), "cyan")}
              ${metric("LOG LOSS", num(b.log_loss, 4), "magenta")}
              ${metric("ACCURACY", pct(b.accuracy), "lime")}
              ${metric("HOME BASELINE", pct(b.home_baseline_accuracy), "muted")}
            </div>
            <div class="note-box">Lower Brier and log loss are better. Accuracy is measured against the 1X2 argmax. The home baseline always picks the home side; beating it is the minimum bar.</div>
          </div></section>
          <section class="panel"><div class="panel-head"><span class="panel-title">// CALIBRATION · CONFIDENCE VS REALISED FREQUENCY</span><span class="mono tiny faint">1X2</span></div><div class="panel-body">
            ${cal.length ? `<div class="bars">${cal.map((x) => `<div class="bar-row"><span>${(x.bin_low * 100).toFixed(0)}–${(x.bin_high * 100).toFixed(0)}% <span class="faint">(${x.n})</span></span><div class="bar"><span style="width:${clamp(x.accuracy * 100, 2, 100)}%"></span><i style="left:${clamp(x.avg_pred * 100, 0, 99)}%"></i></div><span class="v">${pct(x.accuracy, 0)}</span></div>`).join("")}</div><div class="mono tiny faint" style="margin-top:6px">bar = realised frequency · white marker = mean predicted probability</div>` : `<div class="muted tiny">Calibration buckets are available after a successful backtest.</div>`}
            <div class="section-title">BY COMPETITION</div>
            <div class="market-group">${(b.by_competition || []).slice(0, 8).map((x) => `<div class="market-row"><span class="lbl">${esc(x.competition || x.competition_id)}</span><span class="p">${x.matches}</span><span class="o">B ${num(x.brier, 3)}</span></div>`).join("") || `<div class="muted tiny">—</div>`}</div>
          </div></section>
        </div>
        <div class="stack">
          <section class="panel"><div class="panel-head"><span class="panel-title">// ARCHITECTURE</span><span class="mono tiny faint">V2</span></div><div class="panel-body" style="display:flex;flex-direction:column;gap:12px">
            ${stackRow("Dixon–Coles goal model", "Per-competition attack/defence, time decay, low-score rho, empirical-Bayes shrinkage", "01")}
            ${stackRow("Cricket Monte Carlo", "Vectorised ball-by-ball T20/ODI; session-level Test model with draw mass", "02")}
            ${stackRow("Context adjustment", "Bounded injury, fatigue, weather and venue multipliers", "03")}
            ${stackRow("Reasoning core", "Deterministic thesis, tactical pros/cons, risk list, adversarial check", "04")}
          </div></section>
          <section class="panel"><div class="panel-head"><span class="panel-title">// DATA CONTRACT</span><span class="mono tiny green">MARKET-FREE</span></div><div class="panel-body">
            <div class="metric-grid">
              <div class="metric"><div class="l">Bookmaker inputs</div><div class="v lime">0</div></div>
              <div class="metric"><div class="l">Model version</div><div class="v" style="font-size:13px">oracle-dc-mc-2.0</div></div>
              <div class="metric"><div class="l">Evaluation</div><div class="v" style="font-size:13px">walk-forward</div></div>
            </div>
            <div class="note-box">This lab is deliberately uncomfortable: it reports out-of-sample error and calibration, not a highlight reel. A model that cannot beat the home baseline is not ready for money.</div>
          </div></section>
        </div>
      </div>`;
  }

  // ------------------------------------------------------------------ automation
  async function renderAutomation() {
    const view = $("#view");
    view.innerHTML = `<div class="page-head"><div><div class="eyebrow">AUTOMATION</div><h1 class="page-title">The engine runs itself.</h1><p class="page-sub">Rolling 7-day discovery, automatic fixture deduplication, model refresh, research queue and prediction regeneration.</p></div><div class="page-actions"><button class="btn btn-primary" onclick="ORACLE.runSync()">${ICON.refresh} RUN FULL CYCLE</button></div></div>
      <div id="autoContent">${automationSkeleton()}</div>`;
    await loadAutomation();
    startPolling(() => { if (state.route === "automation") loadAutomation(); }, 8000);
  }

  async function loadAutomation() {
    try {
      const [a, jobs] = await Promise.all([api("/api/automation"), api("/api/jobs?limit=12")]);
      state.automation = a;
      const s = a.scheduler || {};
      const last = s.last_sync || {};
      const stats = last.stats || {};
      const logs = a.logs || [];
      const sources = a.sources || {};
      const runs = jobs.items || [];
      $("#autoContent").innerHTML = `
        <div class="metric-hero" style="margin-bottom:16px">
          ${metric("SCHEDULER", s.running ? "RUNNING" : s.enabled ? "ARMED" : "OFF", s.running ? "green" : "amber")}
          ${metric("NEXT CYCLE", `<span data-countdown="${esc(s.next_sync || "")}">${countdown(s.next_sync)}</span>`, "cyan")}
          ${metric("WINDOW", `${s.window_days || 7} DAYS`, "lime")}
          ${metric("TICK", `${s.tick_seconds || 45}s`, "muted")}
        </div>
        <div class="lab-grid">
          <div class="stack">
            <section class="panel"><div class="panel-head"><span class="panel-title">// CYCLE HISTORY</span><span class="mono tiny faint">${runs.length} jobs</span></div><div class="panel-body"><div class="job-list">
              ${runs.length ? runs.map((j) => `<div class="job"><span class="st ${esc(j.status)}">${esc(String(j.status || "").toUpperCase())}</span><span class="msg" title="${esc(j.message || "")}">${esc(j.kind)} · ${esc(j.message || "")}</span><span class="prog"><span style="width:${Math.round((Number(j.progress) || 0) * 100)}%"></span></span><span class="mono tiny muted">${j.started_at ? timeAgo(j.started_at) : ""}</span></div>`).join("") : `<div class="muted tiny">No jobs yet.</div>`}
            </div></div></section>
            <section class="panel"><div class="panel-head"><span class="panel-title">// EVENT LOG</span><span class="mono tiny green"><span class="pulse-dot"></span>LIVE</span></div><div class="panel-body"><div class="log-list">
              ${logs.length ? logs.map((l) => `<div class="log-line ${esc(l.level)}"><span class="t">${esc((l.ts || "").slice(11, 19))}</span><span class="s">${esc(l.scope || "")}</span><span class="m">${esc(l.message || "")}</span></div>`).join("") : `<div class="muted tiny">Log is empty.</div>`}
            </div></div></section>
          </div>
          <div class="stack">
            <section class="panel"><div class="panel-head"><span class="panel-title">// LAST CYCLE</span><span class="mono tiny faint">${last.at ? timeAgo(last.at) : "never"}</span></div><div class="panel-body"><div class="metric-grid">
              <div class="metric"><div class="l">Analysed</div><div class="v">${stats.analysed ?? "—"}</div></div>
              <div class="metric"><div class="l">Full depth</div><div class="v">${stats.depth_full ?? "—"}</div></div>
              <div class="metric"><div class="l">Elapsed</div><div class="v">${stats.elapsed_seconds ? stats.elapsed_seconds + "s" : "—"}</div></div>
              <div class="metric"><div class="l">News teams</div><div class="v">${stats.news_teams ?? "—"}</div></div>
            </div>
            <div class="note-box">${stats.football_fixtures ? `${stats.football_fixtures.fixtures || 0} football fixtures · ${stats.cricket_fixtures?.fixtures || 0} cricket fixtures · ${stats.models?.football_matches || 0} training matches.` : "No cycle recorded yet."}</div>
            </div></section>
            <section class="panel"><div class="panel-head"><span class="panel-title">// SOURCES</span><span class="mono tiny green">CONNECTED</span></div><div class="panel-body"><div class="source-grid">
              ${Object.entries(sources).map(([k, v]) => `<div class="source-card"><div class="nm">${esc(k.replace(/_/g, " "))}</div><div class="ds">${esc(v)}</div><div class="st"><span class="pulse-dot"></span>ACTIVE</div></div>`).join("")}
            </div></div></section>
            <section class="panel"><div class="panel-head"><span class="panel-title">// CLI</span><span class="mono tiny faint">LOCAL</span></div><div class="panel-body"><div class="note-box" style="font-size:10px">python -m oracle.cli serve<br/>python -m oracle.cli sync<br/>python -m oracle.cli backtest --days 30</div></div></section>
          </div>
        </div>`;
    } catch (e) {
      $("#autoContent").innerHTML = errorState(e.message);
    }
  }

  function automationSkeleton() {
    return `<div class="lab-grid"><div class="panel" style="padding:20px"><div class="skeleton" style="height:240px"></div></div><div class="panel" style="padding:20px"><div class="skeleton" style="height:180px"></div></div></div>`;
  }

  // ------------------------------------------------------------------ sync
  async function runSync() {
    const btn = $("#syncBtn") || $("#heroSync") || $("#fixturesSync");
    if (btn) { btn.classList.add("busy"); btn.disabled = true; btn.innerHTML = `${ICON.refresh} QUEUING…`; }
    try {
      const r = await api("/api/sync", { method: "POST" });
      toast("Autonomous cycle queued");
      pollJob(r.job_id, btn);
    } catch (e) {
      toast(`Sync failed: ${e.message}`, "err");
      if (btn) { btn.classList.remove("busy"); btn.disabled = false; btn.innerHTML = `${ICON.refresh} RUN CYCLE`; }
    }
  }

  async function pollJob(id, btn) {
    let alive = true;
    const started = Date.now();
    while (alive && Date.now() - started < 15 * 60 * 1000) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const j = await api(`/api/jobs/${id}`);
        if (btn) btn.innerHTML = `${ICON.refresh} ${j.status === "running" ? Math.round((j.progress || 0) * 100) + "%" : j.status.toUpperCase()}`;
        if (j.status === "completed") {
          toast(`Cycle complete · ${j.stats?.analysed || "—"} fixtures analysed`);
          if (btn) { btn.classList.remove("busy"); btn.disabled = false; btn.innerHTML = `${ICON.refresh} RUN CYCLE`; }
          await loadOverview(true);
          if (state.route === "mission") await renderMission();
          if (state.route === "fixtures") await loadFixtures(true);
          if (state.route === "automation") await loadAutomation();
          if (state.route === "watch") await renderWatch();
          return;
        }
        if (j.status === "failed") {
          toast(`Cycle failed: ${j.message || "unknown error"}`, "err");
          if (btn) { btn.classList.remove("busy"); btn.disabled = false; btn.innerHTML = `${ICON.refresh} RUN CYCLE`; }
          return;
        }
      } catch (e) { /* keep polling */ }
    }
    if (btn) { btn.classList.remove("busy"); btn.disabled = false; btn.innerHTML = `${ICON.refresh} RUN CYCLE`; }
  }

  // ------------------------------------------------------------------ polling
  function startPolling(fn, ms) {
    stopPolling();
    state.pollTimer = setInterval(fn, ms);
  }
  function stopPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  // ------------------------------------------------------------------ palette
  const PALETTE_BASE = [
    { label: "Mission Control", hint: "overview", action: () => navigate("#/mission") },
    { label: "Fixture Grid", hint: "all matches", action: () => navigate("#/fixtures") },
    { label: "Research Signals", hint: "evidence", action: () => navigate("#/research") },
    { label: "Model Laboratory", hint: "backtest", action: () => navigate("#/lab") },
    { label: "Model Slip Lab", hint: "fair odds", action: () => navigate("#/slip") },
    { label: "Automation", hint: "engine", action: () => navigate("#/automation") },
    { label: "Post-match Review", hint: "calibration", action: () => navigate("#/review") },
    { label: "Watchlist", hint: "saved", action: () => navigate("#/watch") },
    { label: "Run autonomous cycle", hint: "sync", action: () => runSync() },
  ];

  function openPalette() {
    state.paletteOpen = true;
    state.paletteSeq = 0;
    $("#palette").hidden = false;
    const input = $("#paletteInput");
    input.value = "";
    renderPalette("");
    setTimeout(() => input.focus(), 30);
  }
  function closePalette() {
    state.paletteOpen = false;
    $("#palette").hidden = true;
  }
  function renderPaletteList(items, query, loading) {
    let html = "";
    let last = "";
    items.forEach((x, i) => {
      if (x.sect && x.sect !== last) { html += `<div class="palette-sect">${esc(x.sect)}</div>`; last = x.sect; }
      html += `<div class="palette-item ${i === 0 ? "sel" : ""}" data-i="${i}"><span>${esc(x.label)}</span><span class="k">${esc(x.hint || "")}</span></div>`;
    });
    if (loading) html += `<div class="palette-item muted">Searching the global warehouse…</div>`;
    if (!items.length && !loading) {
      html += `<div class="palette-item muted">No team, league or fixture found for “${esc(query)}”.</div>`;
      html += `<div class="palette-item" onclick="ORACLE.searchGrid('${esc(query)}')"><span>Search the fixture grid instead</span><span class="k">grid</span></div>`;
    }
    $("#paletteList").innerHTML = html;
    $$("#paletteList .palette-item[data-i]").forEach((el) => {
      el.addEventListener("click", () => { const i = Number(el.dataset.i); if (items[i]) { closePalette(); items[i].action(); } });
    });
  }
  function renderPalette(q) {
    const query = String(q || "").trim();
    const seq = ++state.paletteSeq;
    const nav = PALETTE_BASE.filter((x) => !query || x.label.toLowerCase().includes(query.toLowerCase()) || x.hint.includes(query.toLowerCase()))
      .map((x) => ({ ...x, sect: "NAVIGATION" }));
    state.paletteItems = nav;
    state.paletteSel = 0;
    renderPaletteList(nav, query, query.length >= 2);
    if (query.length < 2) return;
    state.paletteLoading = true;
    setTimeout(async () => {
      if (seq !== state.paletteSeq || !state.paletteOpen) return;
      try {
        const d = await api(`/api/search?q=${encodeURIComponent(query)}&limit=8`);
        if (seq !== state.paletteSeq || !state.paletteOpen) return;
        const items = [...nav];
        (d.teams || []).forEach((t) => items.push({
          label: t.name, hint: `${t.sport}${t.country ? " · " + t.country : ""}`, sect: "TEAMS",
          action: () => navigate(`#/team/${encodeURIComponent(t.id)}`),
        }));
        (d.competitions || []).forEach((c) => items.push({
          label: c.name, hint: `competition · ${c.country || c.sport || ""}`, sect: "COMPETITIONS",
          action: () => { state.filters = { ...state.filters, q: c.name, sport: "", days: 30 }; navigate("#/fixtures"); },
        }));
        (d.fixtures || []).forEach((f) => items.push({
          label: `${f.home_name} vs ${f.away_name}`, hint: `${f.competition_name || ""} · ${fmtDay(f.kickoff_utc)}`, sect: "FIXTURES",
          action: () => openDossier(f.id),
        }));
        state.paletteItems = items;
        state.paletteSel = 0;
        renderPaletteList(items, query, false);
      } catch (e) {
        if (seq === state.paletteSeq) {
          $("#paletteList").innerHTML = `<div class="palette-item muted">Search failed: ${esc(e.message)}</div>`;
        }
      } finally {
        state.paletteLoading = false;
      }
    }, 180);
  }
  function movePalette(delta) {
    const items = state.paletteItems;
    if (!items.length) return;
    state.paletteSel = (state.paletteSel + delta + items.length) % items.length;
    $$("#paletteList .palette-item[data-i]").forEach((el) => el.classList.toggle("sel", Number(el.dataset.i) === state.paletteSel));
    const sel = $(`#paletteList .palette-item[data-i="${state.paletteSel}"]`);
    sel?.scrollIntoView({ block: "nearest" });
  }
  function choosePalette() {
    const item = state.paletteItems[state.paletteSel];
    if (item) { closePalette(); item.action(); return; }
    const input = $("#paletteInput");
    if (input && input.value.trim().length >= 2) {
      closePalette();
      state.filters = { ...state.filters, q: input.value.trim() };
      navigate("#/fixtures");
    }
  }
  function movePalette(delta) {
    const items = state.paletteItems;
    if (!items.length) return;
    state.paletteSel = (state.paletteSel + delta + items.length) % items.length;
    $$("#paletteList .palette-item").forEach((el, i) => el.classList.toggle("sel", i === state.paletteSel));
    const sel = $$("#paletteList .palette-item")[state.paletteSel];
    sel?.scrollIntoView({ block: "nearest" });
  }
  function choosePalette() {
    const item = state.paletteItems[state.paletteSel];
    if (item) { closePalette(); item.action(); }
  }

  // ------------------------------------------------------------------ helpers
  function emptyState(title, sub = "") {
    return `<div class="empty" style="grid-column:1/-1"><div class="empty-mark">◎</div><h3>${esc(title)}</h3><div class="tiny">${esc(sub)}</div></div>`;
  }
  function emptyInline(msg) { return `<div class="muted tiny" style="padding:14px 0">${esc(msg)}</div>`; }
  function errorState(msg) { return `<div class="empty"><div class="empty-mark">!</div><h3>Engine error</h3><div class="tiny">${esc(msg)}</div></div>`; }

  // ------------------------------------------------------------------ events
  function bindShell() {
    $$(".rail-item").forEach((b) => b.addEventListener("click", () => navigate(`#/${b.dataset.route}`)));
    $("#searchTrigger")?.addEventListener("click", openPalette);
    $("#mobileSearch")?.addEventListener("click", openPalette);
    $("#paletteClose")?.addEventListener("click", closePalette);
    $("#paletteSearchBtn")?.addEventListener("click", () => renderPalette($("#paletteInput").value));
    $("#palette")?.addEventListener("click", (e) => { if (e.target.id === "palette") closePalette(); });
    $("#paletteInput")?.addEventListener("input", (e) => renderPalette(e.target.value));
    $("#syncBtn")?.addEventListener("click", runSync);
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); state.paletteOpen ? closePalette() : openPalette(); return; }
      if (e.key === "Escape") { if (state.paletteOpen) closePalette(); else if ($("#modalRoot").innerHTML) closeDossier(); return; }
      if (state.paletteOpen) {
        if (e.key === "ArrowDown") { e.preventDefault(); movePalette(1); }
        if (e.key === "ArrowUp") { e.preventDefault(); movePalette(-1); }
        if (e.key === "Enter") { e.preventDefault(); choosePalette(); }
      }
    });
    window.addEventListener("hashchange", route);
  }

  // ------------------------------------------------------------------ sse
  function connectStream() {
    if (!("EventSource" in window)) return;
    try {
      const es = new EventSource(ORACLE_STREAM_URL);
      es.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data);
          if (d.counts) {
            if (state.overview) {
              state.overview.counts = { ...(state.overview.counts || {}), ...d.counts };
              state.overview.sports = d.sports || state.overview.sports;
              state.overview.depth = d.depth || state.overview.depth;
            }
            if (d.last_sync) $("#syncAge").textContent = timeAgo(d.last_sync);
          }
        } catch (e) { /* ignore malformed stream messages */ }
      };
      es.onerror = () => { /* EventSource retries automatically */ };
    } catch (e) { /* EventSource unavailable */ }
  }

  // ------------------------------------------------------------------ dev live reload
  async function connectDevReload() {
    if (!/^(127\.0\.0\.1|localhost)$/.test(location.hostname)) return;
    try {
      const r = await fetch("/api/dev/status");
      if (!r.ok) return;
      const d = await r.json();
      if (!d.enabled) return;
    } catch (e) { return; }
    let hadError = false;
    const es = new EventSource("/api/dev/reload");
    es.onopen = () => {
      if (hadError) {
        hadError = false;
        location.reload();
      }
    };
    es.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data);
        if (d.version) location.reload();
      } catch (e) { /* ignore malformed reload messages */ }
    };
    es.onerror = () => { hadError = true; };
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    bindShell();
    startClock();
    try {
      await loadOverview(true);
      const ov = state.overview;
      const counts = ov?.counts || {};
      $("#bootLog").textContent = `${counts.fixtures_window || 0} fixtures in window · ${counts.predictions || 0} independent predictions · zero market inputs`;
    } catch (e) { /* noop */ }
    await route();
    setTimeout(() => {
      $("#boot").classList.add("done");
      $("#app").hidden = false;
      if (!new URLSearchParams(location.search).has("nostream")) connectStream();
      connectDevReload();
    }, 650);
  }

  window.ORACLE = {
    open: (id) => { location.hash = `#/match/${encodeURIComponent(id)}`; if (state.route === "match") route(); },
    watch: async (id, btn) => {
      try {
        const r = await api(`/api/watch/${encodeURIComponent(id)}`, { method: "POST" });
        if (btn) { btn.classList.toggle("on", r.watchlisted); }
        toast(r.watchlisted ? "Pinned to watchlist" : "Removed from watchlist");
      } catch (e) { toast(e.message, "err"); }

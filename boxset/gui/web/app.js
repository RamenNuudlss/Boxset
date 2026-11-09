"use strict";

/* ===================================================================== plumbing */
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let S = null;              // engine state
let view = "films";
let openRow = null;        // expanded film row
let hot = null;            // film highlighted by hover
let manifest = null;       // rendered menus
let removeArmed = null;    // installed theme waiting for a second click to remove
let removeTimer = 0;
let menusDirty = false;    // edits since the last menu render
let pending = false;       // a re-render waiting for an input to lose focus
const sim = { menu: null, sel: null, stack: [], card: null, flash: null };
const buildOpts = loadOpts();

async function call(name, ...args) {
  const r = await fetch("/api/" + name, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Boxset-Token": TOKEN },
    body: JSON.stringify({ args }),
  });
  const j = await r.json();
  if (!j.ok) {
    if (j.error === "NO_DIALOG") return { __nodialog: true };
    throw new Error(j.error);
  }
  return j.result;
}

async function act(name, ...args) {
  try {
    const res = await call(name, ...args);
    if (res && res.__nodialog) return res;
    if (res && res.project) { S = res; render(); }
    return res;
  } catch (e) {
    toast(e.message, "error");
    return null;
  }
}

function editAct(name, ...args) {
  menusDirty = true;
  return act(name, ...args);
}

function loadOpts() {
  try { return Object.assign({ iso: true, fast: false }, JSON.parse(localStorage.getItem("boxset.build") || "{}")); }
  catch { return { iso: true, fast: false }; }
}
function saveOpts() { try { localStorage.setItem("boxset.build", JSON.stringify(buildOpts)); } catch {} }

/* ===================================================================== formatting */
const fmtRun = (s) => { if (!s) return "–"; const m = Math.round(s / 60); return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`; };
const fmtLong = (s) => { const m = Math.round((s || 0) / 60); const h = Math.floor(m / 60); return h ? `${h} hr ${m % 60} min` : `${m} min`; };
const gb = (b) => (b / 1e9).toFixed(1);
// whole percentages are too coarse at the start of a day-long build
const pctText = (f) => { const p = (f || 0) * 100; return (p > 0 && p < 10 ? p.toFixed(1) : Math.floor(p)) + "%"; };
function fmtEta(s) {
  if (s == null || !isFinite(s)) return "";
  if (s < 60) return "under a minute left";
  const m = Math.round(s / 60);
  return m < 60 ? `about ${m} min left` : `about ${Math.floor(m / 60)} hr ${m % 60} min left`;
}
const SAVE_SPACE_QUALITY = "Slightly below your files";
const SAVE_SPACE_HELP = "Films take a third to a half less space. The cost: fine grain is smoothed over, and dark scenes, smoke and fast motion can show soft blocks or banding. Hardest to spot with downloads that were already heavily compressed; easiest with high-quality rips.";

function quality(kbps) {
  const m = kbps / 1000;
  if (m >= 20) return ["Close to a retail disc", 1];
  if (m >= 12) return ["Excellent", .82];
  if (m >= 8) return ["Very good", .66];
  if (m >= 5) return ["Good", .48];
  if (m >= 3) return ["Fair, some softness", .3];
  return ["Heavily compressed", .14];
}
function menuLabel(id) {
  let m;
  if (id === "main") return "Main menu";
  if ((m = id.match(/^main(\d+)$/))) return `Main menu, ${filmTitle(+m[1])} in front`;
  if (/^(films|board|list)$/.test(id)) return "Film list";
  if ((m = id.match(/^film(\d+)$/))) return `Film ${+m[1]}: ${filmTitle(+m[1])}`;
  if ((m = id.match(/^(?:ch|sc)(\d+)p(\d+)$/))) return `Film ${+m[1]} scenes, page ${m[2]}`;
  return id;
}
const filmTitle = (n) => (S && S.project.films[n - 1] ? S.project.films[n - 1].title : `Film ${n}`);

function filmColor(i, n) {
  const h = 252 - (n > 1 ? (i * 74) / (n - 1) : 0);
  return `hsl(${h.toFixed(0)} 52% ${i % 2 ? 54 : 46}%)`;
}

/* ===================================================================== toasts */
function toast(msg, level = "info", ms = 5000) {
  const t = document.createElement("div");
  t.className = "toast " + level;
  t.innerHTML = `<div>${esc(msg)}</div><button class="icon-btn" aria-label="Dismiss">${ICON.x}</button>`;
  t.querySelector("button").onclick = () => t.remove();
  $("#toasts").appendChild(t);
  if (level !== "error") setTimeout(() => t.remove(), ms);
}

const ICON = {
  x: '<svg viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/></svg>',
  grip: '<svg viewBox="0 0 12 16"><g fill="currentColor"><circle cx="3.5" cy="3" r="1.3"/><circle cx="8.5" cy="3" r="1.3"/><circle cx="3.5" cy="8" r="1.3"/><circle cx="8.5" cy="8" r="1.3"/><circle cx="3.5" cy="13" r="1.3"/><circle cx="8.5" cy="13" r="1.3"/></g></svg>',
  chev: '<svg viewBox="0 0 16 16"><path d="M5 6l3 3 3-3" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  up: '<svg viewBox="0 0 12 12"><path d="M2.5 8l3.5-4 3.5 4" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  down: '<svg viewBox="0 0 12 12"><path d="M2.5 4l3.5 4 3.5-4" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  left: '<svg viewBox="0 0 12 12"><path d="M8 2.5L4 6l4 3.5" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  right: '<svg viewBox="0 0 12 12"><path d="M4 2.5L8 6l-4 3.5" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  ok: '<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="3.2" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>',
};

/* ===================================================================== the disc */
// Blu-ray geometry in mm: 7.5 centre hole, data from 24 to 58, rim at 60. Data is
// written from the inside out at constant density, so a film's share of the disc
// is an annulus whose AREA matches its size.
function discSvg({ segments, capacity, reserve, written = null, highlight = null, size = 400 }) {
  const c = size / 2, k = (size / 2 - 2) / 60;
  const R = 60 * k, Rd = 58 * k, r0 = 24 * k, hole = 7.5 * k, clamp = 22 * k;
  const rad = (f) => Math.sqrt(r0 * r0 + Math.min(f, 1.04) * (Rd * Rd - r0 * r0));
  const ring = (a, b, fill, extra = "") => {
    const p = (r) => `M${c - r},${c}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0Z`;
    return `<path d="${p(b)}${p(a)}" fill="${fill}" fill-rule="evenodd" ${extra}/>`;
  };
  let out = `<svg viewBox="0 0 ${size} ${size}" role="img" aria-label="Disc space used by each film">`;
  out += `<defs><filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.4"/></filter></defs>`;
  out += `<circle cx="${c}" cy="${c}" r="${R}" fill="#2A2C32" stroke="#3B3E46" stroke-width="1"/>`;
  // grooves across the empty data area
  for (let r = r0 + 2; r < Rd; r += 3.2) out += `<circle cx="${c}" cy="${c}" r="${r.toFixed(1)}" fill="none" stroke="#fff" stroke-opacity=".035" stroke-width="1"/>`;
  out += `<circle cx="${c}" cy="${c}" r="${Rd}" fill="none" stroke="#3B3E46" stroke-width="1"/>`;
  let f = 0;
  if (reserve) {
    const b = reserve / capacity;
    out += ring(rad(0), rad(b), "#4A4D57", `opacity="${written == null || written > 0 ? 1 : .35}"`);
    f = b;
  }
  const total = segments.reduce((a, s) => a + s.bytes, 0) + (reserve || 0);
  segments.forEach((s, i) => {
    const a = f, b = f + s.bytes / capacity;
    let op = 1;
    if (highlight != null) op = s.index === highlight ? 1 : .32;
    if (written != null) {
      const wf = written;                                   // fraction of disc written
      if (wf <= a) op = .13; else if (wf < b) op = 1;
    }
    out += ring(rad(a), rad(b), s.color, `opacity="${op}"`);
    if (written != null && written > a && written < b) {
      // the part not yet written fades back
      out += ring(rad(written), rad(b), "#2A2C32", 'opacity=".82"');
    }
    out += `<circle cx="${c}" cy="${c}" r="${rad(b).toFixed(2)}" fill="none" stroke="#2A2C32" stroke-width=".9"/>`;
    f = b;
  });
  if (total > capacity) {
    out += ring(Rd + 1, R - .5, "url(#over)", "");
    out = out.replace("<defs>", `<defs><pattern id="over" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#3A2729"/><rect width="3" height="6" fill="#EF5A5F"/></pattern>`);
  }
  // clamping zone and centre hole
  out += `<circle cx="${c}" cy="${c}" r="${clamp}" fill="#33363D"/>`;
  out += `<circle cx="${c}" cy="${c}" r="${clamp * .72}" fill="none" stroke="#3E414A" stroke-width="1"/>`;
  out += `<circle cx="${c}" cy="${c}" r="${hole}" fill="#1C1D21"/>`;
  if (written != null && written > 0 && written < 1) {
    const r = rad(written);
    out += `<circle cx="${c}" cy="${c}" r="${r.toFixed(2)}" fill="none" stroke="#8F86FF" stroke-width="3" filter="url(#glow)"/>`;
    out += `<circle cx="${c}" cy="${c}" r="${r.toFixed(2)}" fill="none" stroke="#D9D5FF" stroke-width="1.2"/>`;
  }
  return out + "</svg>";
}

function filmSegments() {
  const films = S.project.films, plan = S.plan;
  return films.map((f, i) => {
    const m = S.meta[f.file] || {};
    const dur = m.duration || 0;
    const est = plan && plan.films ? plan.films[f.file] : null;
    let bytes = 0;
    if (est) bytes = est.bytes;
    else if (plan && dur) bytes = ((plan.video_kbps + plan.audio_kbps) * 1000 * dur / 8) * (1 + plan.overhead);
    return { index: i, bytes, title: f.title, color: filmColor(i, films.length), exact: !!(est && est.measured) };
  });
}

/* ===================================================================== header */
function renderHeader() {
  const name = $("#projectName");
  if (document.activeElement !== name) name.value = S.project.name || "Untitled collection";
  const where = $("#projectWhere");
  where.textContent = S.folder ? S.folder_display : "Not saved yet. Adding a film saves it in Documents, in a Boxset folder.";
  where.title = S.folder || "";
  const n = S.project.films.length;
  $("#filmCount").textContent = n ? n : "";
  $$(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.view === view)));
  $$(".view").forEach((v) => (v.hidden = v.id !== "view-" + view));
  const btn = $("#primaryAction");
  if (S.job.running) {
    btn.textContent = S.job.kind === "menus" ? "Cancel rendering" : "Cancel build";
    btn.className = "btn danger";
    btn.disabled = false;
  } else {
    btn.textContent = "Build disc";
    btn.className = "btn primary";
    btn.disabled = !n || hasProblems();
  }
  const rl = $("#recentList");
  const recent = (S.recent || []).filter((r) => r.exists && r.path !== S.path);
  $("#recentSep").hidden = !recent.length;
  rl.innerHTML = recent.length ? `<div class="menu-heading">Recent</div>` + recent.map((r) =>
    `<button role="menuitem" data-open="${esc(r.path)}">${esc(r.name)}<span class="recent-path">${esc(r.path)}</span></button>`).join("") : "";
}

function hasProblems() {
  return S.project.films.some((f) => { const m = S.meta[f.file]; return m && m.error; });
}

/* ===================================================================== films */
function renderFilms() {
  const el = $("#view-films");
  const films = S.project.films;
  let left;
  if (!films.length) {
    el.classList.add("is-empty");
    el.innerHTML = `<div class="empty"><div class="empty-inner">
      ${discSvg({ segments: [], capacity: 1, reserve: 0, size: 240 })}
      <h2>Add your movies</h2>
      <p>Drop video files or a whole folder anywhere in this window. Boxset reads each film's length, chapters and audio, and fills in the title and year from the file name.</p>
      <div class="row"><button class="btn primary" data-do="pick-files">Choose files</button><button class="btn" data-do="pick-folder">Choose a folder</button></div>
    </div></div>`;
    return;
  }
  el.classList.remove("is-empty");
  {
    const totalDur = films.reduce((a, f) => a + ((S.meta[f.file] || {}).duration || 0), 0);
    left = `<div class="films-pane">
      <div class="pane-head"><div><h2>Films</h2><div class="sub">Disc order, top to bottom. Drag the handle to reorder. ${films.length} films, ${fmtLong(totalDur)}.</div></div>
      <div class="pane-tools"><button class="btn small" data-do="pick-files">Add files</button><button class="btn small" data-do="pick-folder">Add folder</button></div></div>
      <div class="film-table" id="filmTable">
        <div class="film-head"><span></span><span class="num">#</span><span>Title</span><span class="num">Year</span><span class="num">Length</span><span class="num">Chap.</span><span>Audio</span><span></span></div>
        ${films.map(filmRow).join("")}
      </div></div>`;
  }
  el.innerHTML = left + `<aside class="disc-pane" id="discPane">${discPane()}</aside>`;
}

function filmRow(f, i) {
  const m = S.meta[f.file];
  let status = "";
  if (!m) status = `<span class="status-dot st-wait" title="Reading the file"></span>`;
  else if (m.error) status = `<span class="status-dot st-err" title="${esc(m.error)}"></span>`;
  else if (m.problems && m.problems.length) status = `<span class="status-dot st-warn" title="${esc(m.problems.join("; "))}"></span>`;
  const open = openRow === i;
  let row = `<div class="film-row ${open ? "open" : ""} ${hot === i ? "hot" : ""}" data-i="${i}">
    <span class="grip" title="Drag to reorder" data-grip>${ICON.grip}</span>
    <span class="order">${i + 1}</span>
    <input class="cell-input title-input" data-field="title" value="${esc(f.title)}" aria-label="Title of film ${i + 1}" spellcheck="false">
    <input class="cell-input year-input" data-field="year" value="${esc(f.year ?? "")}" inputmode="numeric" maxlength="4" placeholder="—" aria-label="Year">
    <span class="dim-cell">${m && !m.error ? fmtRun(m.duration) : ""}</span>
    <span class="dim-cell">${m && !m.error ? m.chapters : ""}</span>
    <span class="audio-cell">${m && !m.error ? esc(m.audio) : (m && m.error ? '<span class="problem err">Can\'t use</span>' : '<span class="faint">Reading…</span>')}</span>
    <button class="icon-btn" data-toggle aria-label="More about this film" aria-expanded="${open}">${status || ICON.chev}</button>
  </div>`;
  if (open) row += filmDetail(f, i, m);
  return row;
}

function filmDetail(f, i, m) {
  const theme = currentTheme();
  const extra = (theme && theme.film_fields) || [];
  const probs = m ? [m.error, ...(m.problems || [])].filter(Boolean) : [];
  return `<div class="film-detail" data-i="${i}">
    <div class="field"><label for="place${i}">Setting or tagline</label><input id="place${i}" class="text-input" data-field="place" value="${esc(f.place || "")}" placeholder="Shown on the film's page by some themes"></div>
    <div class="field"><label class="switch"><input type="checkbox" data-field="spinoff" ${f.spinoff ? "checked" : ""}><span class="track"></span><span>Mark as a spin-off</span></label></div>
    ${extra.map((x) => `<div class="field"><label for="x${i}${esc(x.key)}">${esc(x.label)}</label><input id="x${i}${esc(x.key)}" class="text-input" data-field="x_${esc(x.key)}" value="${esc(f[x.key] || "")}"></div>`).join("")}
    ${probs.length ? `<div class="full">${probs.map((p) => `<div class="problem ${m.error ? "err" : ""}">${esc(p)}</div>`).join("")}</div>` : ""}
    <div class="full detail-actions"><span class="file-path">${esc(f.file)}${m && !m.error ? `<br>${m.width}×${m.height}, ${esc(m.fps)} fps, ${gb(m.size)} GB` : ""}</span>
    <button class="btn small danger" data-remove="${i}">Remove from disc</button></div>
  </div>`;
}

function discPane() {
  const plan = S.plan;
  const sizes = S.sizes;
  const segs = S.project.films.length ? filmSegments() : [];
  const cap = sizes[S.project.disc_size];
  const used = segs.reduce((a, s) => a + s.bytes, 0) + (plan ? plan.reserve : 0);
  const over = used > cap;
  // when the films need less than the limit everywhere, the disc isn't what limits the picture
  const save = !!S.project.save_space;
  let [qWord, qFrac] = !plan ? ["", 0] : plan.limited < 0.1 ? (save ? [SAVE_SPACE_QUALITY, .86] : ["Same as your files", 1]) : quality(plan.video_kbps);
  if (plan && save && plan.limited >= 0.1) qFrac = Math.min(qFrac, .86);
  const measuring = plan ? plan.measuring : 0;
  return `<div class="disc-figure">${discSvg({ segments: segs, capacity: cap, reserve: plan ? plan.reserve : 0, highlight: hot })}</div>
    <div class="capacity-line"><div class="capacity-big ${over ? "over" : ""}">${plan ? gb(used) : "0.0"}<small>of ${gb(cap)} GB</small></div>
      <div class="capacity-free">${plan ? (over ? `${gb(used - cap)} GB too much` : `${gb(cap - used)} GB free`) : "Add films to see the fit"}</div></div>
    ${measuring ? `<div class="capacity-hint"><span class="spin" aria-hidden="true"></span>Measuring ${measuring === 1 ? "1 film" : measuring + " films"} for an accurate size</div>` : ""}
    <div class="segmented" role="group" aria-label="Disc type">${Object.entries(sizes).map(([k, v]) =>
      `<button aria-pressed="${k === S.project.disc_size}" data-size="${k}"><strong>${k}</strong><span>${gb(v)} GB</span></button>`).join("")}</div>
    <div class="save-space">
      <label class="switch"><input type="checkbox" data-save-space ${save ? "checked" : ""}><span class="track"></span><span>Save space</span></label>
      <p>${SAVE_SPACE_HELP}</p>
    </div>
    ${plan ? `<dl class="facts">
      <dt>Video limit per film</dt><dd>${(plan.video_kbps / 1000).toFixed(1)} Mbps</dd>
      <dt>Picture quality</dt><dd>${qWord}</dd>
      <div class="quality-meter"><i style="width:${(qFrac * 100).toFixed(0)}%"></i></div>
      <dt>Encoding speed</dt><dd>${plan.speed === "gpu" && S.gpu_checked && !S.gpu ? "Faster (no graphics card)" : (SPEEDS.find((x) => x.id === plan.speed) || SPEEDS[0]).label}</dd>
      <dt>Running time</dt><dd>${fmtLong(plan.total_seconds)}</dd>
      <dt>Audio</dt><dd>Dolby Digital, ${plan.audio_kbps} kbps</dd>
    </dl>` : ""}
    ${plan && plan.warning ? `<div class="note warn">Only ${(plan.video_kbps / 1000).toFixed(1)} Mbps per film fits. ${S.project.disc_size !== "BD-100" ? "A bigger disc type would look noticeably better." : "Consider splitting the collection across two discs."}</div>` : ""}
    ${S.project.disc_size === "BD-100" && S.project.films.length ? `<div class="note">BD-100 discs need a player that supports BDXL. Most players from the last decade do; check yours before burning.</div>` : ""}
    ${segs.length ? `<div class="legend">${segs.map((s) => `<div class="legend-row ${hot === s.index ? "hot" : ""}" data-hot="${s.index}"><i style="background:${s.color}"></i><span>${esc(s.title)}</span><span class="gb" ${s.bytes && !s.exact ? 'title="A rough figure until the film has been measured"' : ""}>${s.bytes ? (s.exact ? "" : "about ") + gb(s.bytes) + " GB" : ""}</span></div>`).join("")}</div>` : ""}`;
}

function setHot(i) {
  if (hot === i) return;
  hot = i;
  $$(".film-row").forEach((r) => r.classList.toggle("hot", +r.dataset.i === i));
  const pane = $("#discPane");
  if (pane && view === "films") pane.innerHTML = discPane();
}

/* ===================================================================== menu view */
const currentTheme = () => S.themes.find((t) => t.id === S.project.theme);

function renderMenu() {
  const el = $("#view-menu");
  const theme = currentTheme();
  const nFilms = S.project.films.length;
  const cards = S.themes.map((t) => {
    const lim = t.limits || {};
    const bad = nFilms && ((lim.max_films && nFilms > lim.max_films) || (lim.min_films && nFilms < lim.min_films));
    const where = t.source === "installed" ? "Installed theme pack" : t.source === "project" ? "From the project's themes folder" : "";
    const armed = removeArmed === t.id;
    return `<div class="theme-item">
      <button class="theme-card" aria-pressed="${t.id === S.project.theme}" data-theme="${esc(t.id)}">
      ${t.preview_url ? `<img src="${t.preview_url}" alt="">` : `<div class="noimg"></div>`}
      <div class="tname">${esc(t.name)}</div>
      <div class="tdesc">${esc(t.description || "")}</div>
      ${bad ? `<div class="tbadge" style="color:#F1D3A1">Fits ${lim.min_films}–${lim.max_films} films</div>` : (where ? `<div class="tbadge">${where}</div>` : "")}
      </button>
      ${t.source === "installed" ? `<button class="theme-remove ${armed ? "armed" : ""}" data-remove-theme="${esc(t.id)}"
          aria-label="${armed ? "Click again to remove" : "Remove"} ${esc(t.name)}">${armed ? "Remove?" : "Remove"}</button>` : ""}
    </div>`;
  }).join("");
  const screens = manifest ? manifest.menus.map((m) => `<option value="${esc(m.id)}" ${m.id === sim.menu ? "selected" : ""}>${esc(menuLabel(m.id))}</option>`).join("") : "";
  const rendering = S.job.running && S.job.kind === "menus";
  const stale = manifest && (menusDirty || manifest.theme !== S.project.theme);
  el.innerHTML = `
    <div class="theme-pane">
      <div class="pane-head"><div><h2>Theme</h2><div class="sub">The look of every screen on the disc</div></div></div>
      <div class="theme-list">${cards}</div>
      <div class="theme-foot"><button class="btn" data-do="install-theme">Install theme pack</button></div>
    </div>
    <div class="stage-pane">
      <div class="stage-bar">
        <div class="left">${manifest ? `<select class="select" id="screenPick" aria-label="Screen">${screens}</select>` : ""}
          ${manifest ? (stale ? `<span class="stale">Changed since last render</span>` : `<span class="fresh">${manifest.menus.length} screens</span>`) : ""}</div>
        <div class="stage-actions">
          ${manifest && !rendering ? `<button class="btn" data-do="clear-menus" title="Delete the rendered menus; the next render starts from nothing">Clear menus</button>` : ""}
          ${rendering
            ? `<button class="btn danger" data-do="stop-render">Stop rendering</button>`
            : `<button class="btn ${manifest && !stale ? "" : "primary"}" data-do="render" ${!nFilms || hasProblems() ? "disabled" : ""}>${manifest ? "Render again" : "Render menus"}</button>`}
        </div>
      </div>
      <div class="screen-wrap"><div class="screen" id="screen"></div></div>
      <div class="remote">
        <div class="remote-keys"><div class="dpad">
          <span></span><button data-key="up" aria-label="Up">${ICON.up}</button><span></span>
          <button data-key="left" aria-label="Left">${ICON.left}</button><button data-key="enter" aria-label="OK">${ICON.ok}</button><button data-key="right" aria-label="Right">${ICON.right}</button>
          <span></span><button data-key="down" aria-label="Down">${ICON.down}</button><span></span>
        </div>
        <button class="btn small" data-key="back">Back</button><button class="btn small" data-key="top">Top menu</button></div>
        <span>Use the arrow keys, <span class="kbd">Enter</span> and <span class="kbd">Backspace</span> like a remote</span>
      </div>
    </div>
    <div class="options-pane">${theme ? optionsPanel(theme) : ""}</div>`;
  buildScreen();
}

function buildScreen() {
  const scr = $("#screen");
  if (!scr) return;
  const theme = currentTheme();
  const rendering = S.job.running && S.job.kind === "menus";
  if (!manifest || !sim.menu) {
    const cur = S.job.current && S.job.current.stage === "menus" ? S.job.current : null;
    scr.innerHTML = `${theme && theme.preview_url ? `<img class="bg" src="${theme.preview_url}" alt="">` : ""}
      <div class="ghost"><div>
        <strong>${rendering ? "Rendering your menus" : S.project.films.length ? "See your own menus" : "Add films to render menus"}</strong>
        <p>${rendering ? esc(cur ? cur.label || "" : "Starting…") : "Render once to click through every screen with the remote, using your films and chapters."}</p>
      </div></div>
      ${rendering ? `<div class="spinner-line" style="width:${((cur && cur.pct) || 0) * 100}%"></div>` : ""}`;
    return;
  }
  const m = manifest.menus.find((x) => x.id === sim.menu);
  scr.innerHTML = (m.video
    ? `<video class="bg" src="${m.background_url}" autoplay muted loop playsinline></video>`
    : `<img class="bg" src="${m.background_url}" alt="">`)
    + m.buttons.map((b) => `<img class="btnimg" data-b="${esc(b.id)}" alt="${esc(b.id)}" style="left:${b.x / 19.2}%;top:${b.y / 10.8}%;width:${b.w / 19.2}%">`).join("")
    + (sim.card ? playCard() : "");
  updateButtons();
}

function updateButtons() {
  const m = manifest && manifest.menus.find((x) => x.id === sim.menu);
  if (!m) return;
  $$("#screen .btnimg").forEach((img) => {
    const b = m.buttons.find((x) => x.id === img.dataset.b);
    const st = b.id === sim.sel ? (sim.flash === b.id ? "activated" : "selected") : "normal";
    const url = b[st + "_url"];
    if (img.getAttribute("src") !== url) img.setAttribute("src", url);
  });
}

function playCard() {
  const c = sim.card;
  return `<div class="play-card"><div><b>${esc(c.text)}</b><div class="faint">On the disc this starts playback. Afterwards the player returns to ${esc(menuLabel(c.after))}.</div></div>
    <button class="btn small" data-do="finish-film">Finish film</button></div>`;
}

function simGo(menuId, button) {
  const m = manifest.menus.find((x) => x.id === menuId);
  if (!m) return;
  if (sim.menu && sim.menu !== menuId) sim.stack.push(sim.menu);
  sim.menu = menuId;
  sim.sel = button && m.buttons.some((b) => b.id === button) ? button : m.default_button;
  sim.card = null;
  buildScreen();
  const pick = $("#screenPick");
  if (pick) pick.value = menuId;
}

function simMove(dir) {
  const m = manifest && manifest.menus.find((x) => x.id === sim.menu);
  if (!m || sim.card) return;
  const cur = m.buttons.find((b) => b.id === sim.sel);
  if (!cur) return;
  let target = cur.nav && cur.nav[dir];
  if (!target) {
    // like a player: the nearest button in that direction
    const cx = cur.x + cur.w / 2, cy = cur.y + cur.h / 2;
    let best = null, bestScore = Infinity;
    for (const b of m.buttons) {
      if (b.id === cur.id) continue;
      const dx = b.x + b.w / 2 - cx, dy = b.y + b.h / 2 - cy;
      const ok = { up: dy < -4, down: dy > 4, left: dx < -4, right: dx > 4 }[dir];
      if (!ok) continue;
      const score = dir === "up" || dir === "down" ? Math.abs(dy) + 2.2 * Math.abs(dx) : Math.abs(dx) + 2.2 * Math.abs(dy);
      if (score < bestScore) { best = b; bestScore = score; }
    }
    target = best && best.id;
  }
  if (target) {
    sim.sel = target;
    updateButtons();
    // an auto button acts the moment it's selected, as it will on the disc
    const t = m.buttons.find((b) => b.id === target);
    if (t && t.auto) setTimeout(() => runAction(t.action), 120);
  }
}

function simEnter(bid) {
  const m = manifest && manifest.menus.find((x) => x.id === sim.menu);
  if (!m) return;
  if (bid) sim.sel = bid;
  const b = m.buttons.find((x) => x.id === sim.sel);
  if (!b) return;
  sim.flash = b.id;
  updateButtons();
  setTimeout(() => { sim.flash = null; runAction(b.action); }, 160);
}

function runAction(a) {
  const p = a.split(":");
  const home = manifest.start;
  if (p[0] === "menu") return simGo(p[1], p[2]);
  if (p[0] === "lastmenu") return simBack();
  let text = a, after = home;
  if (p[0] === "title") { text = `Plays ${filmTitle(+p[1])}`; after = manifest.title_ends[p[1]] || home; }
  else if (p[0] === "chapter") { text = `Plays ${filmTitle(+p[1])} from chapter ${p[2]}`; after = manifest.title_ends[p[1]] || home; }
  else if (p[0] === "playlist") {
    const ids = manifest.playlists[p[1]] || [];
    text = `Plays ${ids.length} films in this order: ${ids.join(", ")}`;
    after = manifest.playlist_ends[p[1]] || home;
  } else if (p[0] === "playall") text = "Plays every film in disc order";
  sim.card = { text, after: after.replace(/^menu:/, "").split(":")[0], afterBtn: after.split(":")[2] };
  buildScreen();
}

function simBack() {
  if (sim.card) { sim.card = null; buildScreen(); return; }
  const prev = sim.stack.pop();
  if (prev) { const m = manifest.menus.find((x) => x.id === prev); sim.menu = prev; sim.sel = m.default_button; buildScreen(); const pick = $("#screenPick"); if (pick) pick.value = prev; }
}

function optionsPanel(t) {
  const o = S.project.theme_options || {};
  const val = (x) => (o[x.key] !== undefined && o[x.key] !== null ? o[x.key] : x.default);
  const rows = (t.options || []).map((x) => {
    const v = val(x);
    const hint = x.help ? `<div class="hint">${esc(x.help)}</div>` : "";
    const id = "opt_" + x.key;
    if (x.type === "text") return `<div class="opt"><label for="${id}">${esc(x.label)}</label><input id="${id}" class="text-input" data-opt="${esc(x.key)}" value="${esc(v ?? "")}">${hint}</div>`;
    if (x.type === "bool") return `<div class="opt"><label class="switch"><input type="checkbox" data-opt="${esc(x.key)}" ${v ? "checked" : ""}><span class="track"></span><span>${esc(x.label)}</span></label>${hint}</div>`;
    if (x.type === "color") return `<div class="opt"><span class="opt-label">${esc(x.label)}</span><div class="swatches">
      ${(x.choices || []).map((c) => `<button class="swatch" style="background:${esc(c)}" data-color="${esc(x.key)}" data-value="${esc(c)}" aria-label="${esc(c)}" aria-pressed="${String(c).toLowerCase() === String(v).toLowerCase()}"></button>`).join("")}
      <input type="color" class="color-input" data-opt="${esc(x.key)}" value="${esc(v || "#ffffff")}" aria-label="Custom colour"></div>${hint}</div>`;
    if (x.type === "choice") return `<div class="opt"><label for="${id}">${esc(x.label)}</label><select id="${id}" class="select" data-opt="${esc(x.key)}">${(x.choices || []).map((c) => `<option ${c === v ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>${hint}</div>`;
    if (x.type === "file") return `<div class="opt"><span class="opt-label">${esc(x.label)}</span><div class="file-pick">
      <span class="fname">${v ? esc(String(v).split(/[\\/]/).pop()) : "None"}</span>
      <button class="btn small" data-pickfile="${esc(x.key)}" data-kind="${esc(x.filter || "")}">Choose</button>
      ${v ? `<button class="btn small quiet" data-clear="${esc(x.key)}">Clear</button>` : ""}</div>${hint}</div>`;
    if (x.type === "order") return orderControl(x, v, hint);
    return "";
  }).join("");
  return `<h3>${esc(t.name)}</h3><div class="by">${esc(t.author ? `By ${t.author}, version ${t.version}` : `Version ${t.version || "1.0"}`)}</div>${rows || '<p class="faint">This theme has no settings.</p>'}`;
}

function orderControl(x, v, hint) {
  const films = S.project.films;
  const on = Array.isArray(v) && v.length === films.length;
  const order = on ? v : films.map((_, i) => i + 1);
  return `<div class="opt"><label class="switch"><input type="checkbox" data-order-toggle="${esc(x.key)}" ${on ? "checked" : ""}><span class="track"></span><span>${esc(x.label)}</span></label>${hint}
    ${on ? `<div class="order-list" style="margin-top:10px">${order.map((n, i) => `<div class="order-item"><span class="on">${i + 1}</span><span>${esc(filmTitle(n))}</span>
      <span class="moves"><button class="icon-btn" data-order-move="${esc(x.key)}" data-i="${i}" data-d="-1" aria-label="Earlier" ${i === 0 ? "disabled" : ""}>${ICON.up}</button><button class="icon-btn" data-order-move="${esc(x.key)}" data-i="${i}" data-d="1" aria-label="Later" ${i === order.length - 1 ? "disabled" : ""}>${ICON.down}</button></span></div>`).join("")}</div>` : ""}</div>`;
}

/* ===================================================================== build view */
function renderBuild() {
  const el = $("#view-build");
  const j = S.job;
  const films = S.project.films;
  const isBuild = j.kind === "build" || j.kind === "iso";
  const segs = films.length ? filmSegments() : [];
  const cap = S.sizes[S.project.disc_size];
  const reserve = S.plan ? S.plan.reserve : 0;
  let written = null;
  if (isBuild && (j.running || j.result)) {
    if (j.result && !j.running) written = 1;
    else {
      let w = reserve;
      segs.forEach((s, i) => { const fp = j.films[String(i + 1)]; w += s.bytes * (fp ? fp.pct || 0 : 0); });
      written = Math.max(0.0001, w / cap);
    }
  }
  const encoding = j.stages.encode && j.stages.encode.status === "start";
  const etaAll = encoding ? overallEta() : null;
  let caption;
  if (j.running && isBuild) caption = `<div class="big">${encoding ? pctText(j.overall) : esc(stageLabel())}</div><div class="sub">${encoding ? esc(fmtEta(etaAll) || "Encoding films") : "Working"}</div>`;
  else if (j.result && isBuild) caption = `<div class="big">Disc ready</div><div class="sub">${j.result.bytes ? gb(j.result.bytes) + " GB, " : ""}${j.result.titles || films.length} films, ${j.result.chapters || ""} chapters</div>`;
  else if (j.error && isBuild) caption = `<div class="big">${j.error === "Cancelled" ? "Build stopped" : "Build failed"}</div><div class="sub">${j.error === "Cancelled" ? "Finished films are kept and won't be encoded again." : "See the details on the right."}</div>`;
  else caption = `<div class="big">${films.length ? gb(segs.reduce((a, s) => a + s.bytes, 0) + reserve) + " GB" : "Nothing to build yet"}</div><div class="sub">${films.length ? `${films.length} films on a ${S.project.disc_size}` : "Add films first"}</div>`;

  el.innerHTML = `<div class="burn-stage">
      <div class="disc-figure big">${discSvg({ segments: segs, capacity: cap, reserve, written, size: 400 })}</div>
      <div class="burn-caption">${caption}</div>
    </div>
    <div class="steps-pane">${stepsPanel(segs)}</div>`;
  swingGauge();
}

function stageLabel() {
  const st = S.job.stages;
  for (const k of ["iso", "assemble", "encode", "menus", "check"]) if (st[k] && st[k].status === "start") return st[k].label;
  return "Starting";
}

function overallEta() {
  const j = S.job;
  const cur = Object.values(j.films).find((f) => f.status === "encoding" || (f.pct > 0 && f.pct < 1));
  if (!cur || !cur.speed) return null;
  let left = 0;
  S.project.films.forEach((f, i) => {
    const fp = j.films[String(i + 1)];
    const d = (S.meta[f.file] || {}).duration || 0;
    const done = fp ? fp.pct || 0 : 0;
    const enc = j.stages.encode;
    if (fp || enc) left += d * (1 - done);
  });
  return left / cur.speed;
}

/* ===================================================================== speed */
const SPEEDS = [
  { id: "quality", label: "Best quality", angle: -62 },
  { id: "fast", label: "Faster", angle: 4 },
  { id: "gpu", label: "Graphics card", angle: 74 },
];

// A small rev gauge: the needle swings with the choice and buries itself in the
// red zone (with a little shudder) when the graphics card is picked.
function speedGauge(speed) {
  const s = SPEEDS.find((x) => x.id === speed) || SPEEDS[0];
  const cx = 30, cy = 30, r = 24;
  const pt = (deg, rr) => { const a = (deg - 90) * Math.PI / 180; return [cx + rr * Math.cos(a), cy + rr * Math.sin(a)]; };
  const arc = (a0, a1, rr) => { const [x0, y0] = pt(a0, rr), [x1, y1] = pt(a1, rr); return `M${x0.toFixed(2)},${y0.toFixed(2)}A${rr},${rr} 0 0,1 ${x1.toFixed(2)},${y1.toFixed(2)}`; };
  let ticks = "";
  for (let d = -90; d <= 90; d += 22.5) {
    const [x0, y0] = pt(d, r - 1), [x1, y1] = pt(d, r - (d % 45 === 0 ? 7 : 4.5));
    ticks += `<line x1="${x0.toFixed(2)}" y1="${y0.toFixed(2)}" x2="${x1.toFixed(2)}" y2="${y1.toFixed(2)}" class="${d >= 56 ? "g-tick red" : "g-tick"}"/>`;
  }
  return `<svg class="gauge ${s.id === "gpu" ? "maxed" : ""}" viewBox="0 0 60 36" aria-hidden="true">
    <path d="${arc(-90, 56, r)}" class="g-arc"/>
    <path d="${arc(56, 90, r)}" class="g-red"/>
    ${ticks}
    <g class="g-needle" data-to="${s.angle}" style="transform: rotate(${gaugeAngle ?? s.angle}deg)"><path d="M${cx - 1.4},${cy} L${cx},${cy - r + 5} L${cx + 1.4},${cy} Z"/></g>
    <circle cx="${cx}" cy="${cy}" r="3.2" class="g-hub"/>
  </svg>`;
}

let gaugeAngle = null;          // where the needle was drawn last, so a change swings it
function swingGauge() {
  const n = document.querySelector(".g-needle[data-to]");
  if (!n) return;
  const to = +n.dataset.to;
  if (gaugeAngle !== to) {
    void n.getBoundingClientRect();                     // start from the old angle…
    requestAnimationFrame(() => { n.style.transform = `rotate(${to}deg)`; });  // …and swing
  }
  gaugeAngle = to;
}

// what the whole disc would hold at a speed, as shown under its button
function speedSize(id) {
  const z = (S.speed_sizes || {})[id];
  if (!z) return id === "gpu" ? (S.gpu_checked ? "Not available" : "Checking…") : "&nbsp;";
  return `${z.exact ? "" : "about "}${gb(z.bytes)} GB`;
}

// the difference a speed makes, in GB, against Best quality
function speedDelta(id) {
  const z = S.speed_sizes || {};
  if (!z[id] || !z.quality || id === "quality") return "";
  const d = z[id].bytes - z.quality.bytes;
  if (Math.abs(d) < 0.05e9) return "";
  return ` ${d > 0 ? `${gb(d)} GB more` : `${gb(-d)} GB less`} than Best quality`;
}

function speedHelp(speed) {
  const gpu = S.gpu;
  const z = (S.speed_sizes || {})[speed];
  const total = z && S.project.films.length ? ` These films will take ${z.exact ? "" : "about "}${gb(z.bytes)} GB of the ${S.project.disc_size.replace("-", "\u2011")}${speedDelta(speed)}.` : "";
  if (speed === "fast") return "About 2½ times faster than Best quality. Files come out a little smaller, with slightly less fine detail." + total;
  if (speed === "gpu") {
    if (!S.gpu_checked) return "Checking this PC's graphics card…";
    if (!gpu) return "No graphics card encoder works on this PC, so films are encoded with Faster instead.";
    return `Uses your ${esc(gpu.name)}. Usually several times faster, and your PC is left mostly free. The costs: films take about 30% more space for the same picture, and graphics cards have no Blu-ray mode, so a few players may refuse the disc. Try a BD-RE in yours first.${total}`;
  }
  return "Slowest, with the best picture for the space. Uses your processor at full load." + total;
}

function speedControl() {
  const speed = S.project.speed || "quality";
  const noGpu = S.gpu_checked && !S.gpu;
  return `<div class="speed">
    <div class="speed-row">
      ${speedGauge(speed)}
      <div class="segmented speed-seg" role="group" aria-label="Encoding speed">${SPEEDS.map((x) =>
        `<button aria-pressed="${x.id === speed}" data-speed="${x.id}" ${x.id === "gpu" && noGpu && speed !== "gpu" ? 'disabled title="No graphics card encoder works on this PC"' : ""}><strong>${x.label}</strong><span>${speedSize(x.id)}</span></button>`).join("")}</div>
    </div>
    <p class="speed-help">${speedHelp(speed)}</p>
  </div>`;
}

/* ===================================================================== burner */
function burnerPicker() {
  if (!S.windows) return "";
  const b = S.burners || {};
  const drives = b.drives || [];
  const looking = b.drives == null || b.checking;
  const pick = drives.length
    ? `<select class="select burner-select" data-burner aria-label="Burner" ${looking ? "disabled" : ""}>${drives.map((d) =>
        `<option value="${esc(d.id)}" ${d.id === b.chosen ? "selected" : ""} ${d.bd ? "" : "disabled"}>${esc(d.name)}${d.bd ? "" : " (can't write Blu-ray)"}</option>`).join("")}</select>`
    : `<div class="burner-none">${looking ? "Looking for burners…" : "No disc burners found"}</div>`;
  return `<div class="burner">
    <div class="burner-label">Burner</div>
    <div class="burner-row">${pick}<button class="btn small" data-do="refresh-burners" ${looking ? "disabled" : ""}>${looking ? "Looking…" : "Refresh"}</button></div>
    ${b.message && !looking ? `<div class="burner-msg ${esc(b.level || "")}"><i></i>${esc(b.message)}</div>` : ""}
  </div>`;
}

function stepsPanel(segs) {
  const j = S.job, films = S.project.films;
  const isBuild = j.kind === "build" || j.kind === "iso";
  const st = isBuild ? j.stages : {};
  const cls = (k) => !st[k] ? "" : st[k].status === "start" ? "active" : st[k].status === "skipped" ? "done skipped" : "done";
  const sub = (k, idle) => (st[k] && st[k].label) || idle;
  const showIso = S.windows && (buildOpts.iso || st.iso);
  const filmRows = films.map((f, i) => {
    const fp = (isBuild && j.films[String(i + 1)]) || {};
    const p = fp.pct || 0;
    const state = p >= 1 || fp.status === "done" ? "done" : (p > 0 ? "cur" : "");
    const right = state === "done" ? "Done" : p > 0 ? `${Math.floor(p * 100)}%` : "";
    return `<div class="fp-row ${state}"><span class="t">${i + 1}. ${esc(f.title)}</span><span class="p">${right}${state === "cur" && fp.speed ? `, ${fp.speed}×` : ""}</span>
      <div class="bar"><i style="width:${(p * 100).toFixed(1)}%"></i></div></div>`;
  }).join("");
  const idle = !j.running && !(isBuild && j.result);
  const res = isBuild && j.result && !j.running ? j.result : null;
  const log = (j.log || []).map((l) => `<div class="${l.level === "warn" ? "w" : l.level === "error" ? "e" : ""}">${esc(l.message)}</div>`).join("");
  return `
    ${idle ? `<div class="pane-head" style="padding:0"><div><h2>Build</h2><div class="sub">Everything from here is automatic. Leave Boxset open and it will show when the disc is ready.</div></div></div>
      <div class="build-opts">
        ${speedControl()}
        ${S.windows ? `<label class="switch"><input type="checkbox" data-bopt="iso" ${buildOpts.iso ? "checked" : ""}><span class="track"></span><span>Also make a disc image (.iso) for burning</span></label>` : ""}
        <label class="switch"><input type="checkbox" data-bopt="fast" ${buildOpts.fast ? "checked" : ""}><span class="track"></span><span>Quick test build, low quality</span></label>
        ${buildOpts.iso ? burnerPicker() : ""}
        <button class="btn primary" data-do="build" ${!films.length || hasProblems() ? "disabled" : ""}>Build disc</button>
      </div>` : ""}
    ${res ? `<div class="result"><h3>Your disc is ready</h3>
      <div class="faint">${esc(res.folder || "")}</div>
      <div class="row"><button class="btn" data-do="open-disc">Show disc folder</button>
      ${S.windows && !res.iso ? `<button class="btn" data-do="make-iso">Make disc image</button>` : ""}
      ${S.windows && res.iso ? `<button class="btn primary" data-do="burn" ${(S.burners || {}).level === "stop" ? "disabled" : ""}>Burn to disc</button>` : ""}</div>
      ${S.windows && res.iso ? burnerPicker() : ""}
      ${S.windows ? "" : `<div class="faint">Burn the disc folder with your usual Blu-ray burning app.</div>`}
      <div class="faint">Try a rewritable BD-RE in your player before burning a write-once disc.</div></div>` : ""}
    ${j.error && isBuild && j.error !== "Cancelled" ? `<div class="note warn">${esc(j.error)}</div>` : ""}
    <ol class="steps">
      <li class="step ${cls("check")}"><span class="mark-s"></span><div><div class="s-title">Check films</div><div class="s-sub">${esc(sub("check", "Read every file and plan the disc space"))}</div></div><span class="s-right"></span></li>
      <li class="step ${cls("menus")}"><span class="mark-s"></span><div><div class="s-title">Render menus</div><div class="s-sub">${esc(sub("menus", "Skipped when nothing changed"))}</div></div><span class="s-right"></span></li>
      <li class="step ${cls("encode")}"><span class="mark-s"></span><div><div class="s-title">Encode films</div><div class="s-sub">${esc(sub("encode", "The long part. Finished films are kept if you stop."))}</div>
        <div class="film-progress">${filmRows}</div></div><span class="s-right">${st.encode && st.encode.status === "start" ? pctText(j.overall) : ""}</span></li>
      <li class="step ${cls("assemble")}"><span class="mark-s"></span><div><div class="s-title">Write the disc</div><div class="s-sub">${esc(sub("assemble", "Menus, chapters and playlists into a Blu-ray folder"))}</div></div><span class="s-right"></span></li>
      ${showIso ? `<li class="step ${cls("iso")}"><span class="mark-s"></span><div><div class="s-title">Disc image</div><div class="s-sub">${esc(sub("iso", "One .iso file, ready to burn"))}</div></div><span class="s-right"></span></li>` : ""}
    </ol>
    ${log ? `<details ${j.error ? "open" : ""}><summary>Details</summary><div class="log">${log}</div></details>` : ""}`;
}

/* ===================================================================== render all */
function render() {
  if (!S) return;
  const active = document.activeElement;
  const typing = active && active.matches && active.matches("input.cell-input, input.text-input") && active.closest(".view");
  renderHeader();
  if (typing) { pending = true; return; }
  pending = false;
  if (view === "films") renderFilms();
  else if (view === "menu") renderMenu();
  else renderBuild();
}

let raf = 0;
function renderSoon() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; render(); }); }

document.addEventListener("focusout", () => setTimeout(() => { if (pending) render(); }, 0));

/* ===================================================================== events from the engine */
function applyJobEvent(e) {
  const st = S.job;
  if (e.type === "stage") st.stages[e.stage] = { status: e.status, label: e.label || "" };
  else if (e.type === "progress") {
    if (e.stage === "encode") { st.films[String(e.film)] = Object.assign(st.films[String(e.film)] || {}, { pct: e.pct, eta: e.eta, speed: e.speed }); st.overall = e.overall ?? st.overall; }
    st.current = e;
  } else if (e.type === "film") {
    const cur = st.films[String(e.film)] = st.films[String(e.film)] || {};
    cur.status = e.status;
    if (e.status === "done") cur.pct = 1;
  } else if (e.type === "log") st.log = [...(st.log || []), e].slice(-200);
}

let lastFrame = 0;
function onEvent(e) {
  if (!S) return;
  switch (e.type) {
    case "meta":
      S.meta[e.file] = e.meta;
      call("state").then((st) => { S = st; renderSoon(); });
      break;
    case "films":
      call("state").then((st) => { S = st; menusDirty = true; render(); if (e.added) toast(`Added ${e.added} film${e.added > 1 ? "s" : ""}`); });
      break;
    case "gpu":
    case "burners":
      call("state").then((st) => { S = st; renderSoon(); });
      break;
    case "themes":
      call("state").then((st) => { S = st; render(); });
      break;
    case "toast":
      toast(e.message, e.level || "info");
      break;
    case "job":
      call("state").then(async (st) => {
        S = st;
        if (e.status === "done" && e.kind === "menus") {
          await loadManifest(true);
          menusDirty = false;
          toast(`Rendered ${e.result.screens} screens`);
        } else if (e.status === "done" && e.kind === "build") {
          await loadManifest(false);
          menusDirty = false;
          if (view !== "build") toast("Your disc is ready");
        } else if (e.status === "done" && e.kind === "iso") toast("Disc image saved");
        else if (e.status === "error") toast(e.message, "error");
        else if (e.status === "cancelled") toast("Stopped");
        render();
      });
      break;
    default:
      applyJobEvent(e);
      if (performance.now() - lastFrame > 120) {
        lastFrame = performance.now();
        if (view === "build") renderBuild();
        else if (view === "menu" && S.job.kind === "menus" && !manifest) buildScreen();
        renderHeader();
      }
  }
}

async function loadManifest(reset) {
  try {
    manifest = await call("manifest");
  } catch { manifest = null; }
  if (manifest && (reset || !sim.menu || !manifest.menus.some((m) => m.id === sim.menu))) {
    sim.menu = manifest.start; sim.stack = []; sim.card = null;
    sim.sel = manifest.menus.find((m) => m.id === sim.menu).default_button;
  }
}

/* ===================================================================== interactions */
async function addByPrompt(kind) {
  const p = prompt(kind === "folder" ? "Full path of a folder of movies:" : "Full path of a movie file (or several, separated by | ):");
  if (p) await act("add_paths", p.split("|").map((s) => s.trim()).filter(Boolean));
}

async function doThing(what, el) {
  switch (what) {
    case "pick-files": { const r = await act("pick_files"); if (r && r.__nodialog) addByPrompt("file"); break; }
    case "pick-folder": { const r = await act("pick_folder"); if (r && r.__nodialog) addByPrompt("folder"); break; }
    case "render": await act("render_menus", true); break;        // pressed on purpose: always render
    case "stop-render": await act("cancel_render"); break;
    case "clear-menus": {
      const r = await act("clear_menus");
      if (r) { manifest = null; sim.menu = null; sim.stack = []; menusDirty = true; render(); }
      break;
    }
    case "build": await startBuild(); break;
    case "install-theme": {
      const r = await act("install_theme");
      if (r && r.__nodialog) { const p = prompt("Full path of a .boxtheme file:"); if (p) { const s = await act("install_theme", p); if (s && s.installed) toast("Theme installed"); } }
      else if (r && r.installed) toast("Theme installed");
      break;
    }
    case "open-disc": act("open_folder", "disc"); break;
    case "make-iso": await act("make_iso"); break;
    case "burn": act("burn"); break;
    case "refresh-burners": act("refresh_burners"); break;
    case "finish-film": { const c = sim.card; sim.card = null; simGo(c.after, c.afterBtn); break; }
  }
}

async function startBuild() {
  view = "build";
  const r = await act("build", { iso: buildOpts.iso, fast: buildOpts.fast });
  if (!r) render();
}

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button, [data-hot], .theme-card");
  if (!t) {
    if (!ev.target.closest("#projectMenu, #projectMenuBtn")) $("#projectMenu").hidden = true;
    return;
  }
  if (t.id !== "projectMenuBtn" && !t.closest("#projectMenu")) $("#projectMenu").hidden = true;
  if (t.matches(".tab")) { view = t.dataset.view; if (view === "menu" && !manifest) await loadManifest(true); render(); return; }
  if (t.id === "primaryAction") { if (S.job.running) act("cancel"); else startBuild(); return; }
  if (t.id === "projectMenuBtn") { const m = $("#projectMenu"); m.hidden = !m.hidden; t.setAttribute("aria-expanded", String(!m.hidden)); return; }
  if (t.closest("#projectMenu")) {
    $("#projectMenu").hidden = true;
    const a = t.dataset.act;
    if (t.dataset.open) { const r = await act("open_project", t.dataset.open); if (r) { manifest = null; openRow = null; await loadManifest(true); render(); } return; }
    if (a === "new") { await act("new_project"); manifest = null; openRow = null; render(); }
    if (a === "open") { const r = await act("open_project"); if (r && r.__nodialog) { const p = prompt("Full path of a .boxset project:"); if (p) await act("open_project", p); } manifest = null; await loadManifest(true); render(); }
    if (a === "saveas") { const r = await act("save_project_as"); if (r && r.__nodialog) { const p = prompt("Save the project as (full path):"); if (p) await act("save_project_as", p); } }
    if (a === "folder") act("open_folder", "project");
    return;
  }
  if (t.dataset.removeTheme) {
    const id = t.dataset.removeTheme;
    clearTimeout(removeTimer);
    if (removeArmed === id) {
      removeArmed = null;
      const r = await act("remove_theme", id);
      if (r) { menusDirty = true; render(); }
    } else {
      removeArmed = id; render();
      removeTimer = setTimeout(() => { removeArmed = null; if (view === "menu") render(); }, 4000);
    }
    return;
  }
  if (t.dataset.do) return doThing(t.dataset.do, t);
  if (t.dataset.size) return editAct("set", "disc_size", t.dataset.size);
  if (t.dataset.speed) return act("set", "speed", t.dataset.speed);
  if (t.hasAttribute("data-toggle")) { const i = +t.closest(".film-row").dataset.i; openRow = openRow === i ? null : i; render(); return; }
  if (t.dataset.remove != null) { openRow = null; return editAct("remove_film", +t.dataset.remove); }
  if (t.dataset.theme) { if (t.dataset.theme !== S.project.theme) { await editAct("set", "theme", t.dataset.theme); } return; }
  if (t.dataset.color) return editAct("set_option", t.dataset.color, t.dataset.value);
  if (t.dataset.pickfile) {
    const r = await act("pick_option_file", t.dataset.pickfile, t.dataset.kind || "audio");
    if (r && r.__nodialog) { const p = prompt("Full path of the file:"); if (p) await editAct("set_option", t.dataset.pickfile, p); }
    else if (r) menusDirty = true;
    return;
  }
  if (t.dataset.clear) return editAct("set_option", t.dataset.clear, null);
  if (t.dataset.orderMove) {
    const key = t.dataset.orderMove, i = +t.dataset.i, d = +t.dataset.d;
    const cur = (S.project.theme_options || {})[key] || S.project.films.map((_, k) => k + 1);
    const next = [...cur]; [next[i], next[i + d]] = [next[i + d], next[i]];
    return editAct("set_option", key, next);
  }
  if (t.dataset.key) return remote(t.dataset.key);
  if (t.matches(".btnimg")) return;
});

document.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.id === "projectName") return act("set", "name", t.value);
  if (t.id === "screenPick") { sim.stack = []; simGo(t.value); return; }
  if (t.dataset.field) {
    const i = +t.closest("[data-i]").dataset.i;
    const v = t.type === "checkbox" ? t.checked : t.value;
    return editAct("update_film", i, { [t.dataset.field]: v });
  }
  if (t.dataset.opt) return editAct("set_option", t.dataset.opt, t.type === "checkbox" ? t.checked : t.value);
  if (t.dataset.orderToggle) return editAct("set_option", t.dataset.orderToggle, t.checked ? S.project.films.map((_, k) => k + 1) : null);
  if (t.dataset.bopt) { buildOpts[t.dataset.bopt] = t.checked; saveOpts(); renderBuild(); }
  if (t.matches("[data-save-space]")) return act("set", "save_space", t.checked);
  if (t.matches("[data-burner]")) return act("set_burner", t.value);
});

document.addEventListener("keydown", (ev) => {
  const t = ev.target;
  if (t.matches && t.matches("input.cell-input, #projectName") && ev.key === "Enter") { t.blur(); return; }
  if (t.matches && t.matches("input, select, textarea")) return;
  if (view !== "menu" || !manifest) return;
  const map = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Enter: "enter", Backspace: "back", Escape: "back", Home: "top" };
  if (map[ev.key]) { ev.preventDefault(); remote(map[ev.key]); }
});

function remote(k) {
  if (!manifest) return;
  if (k === "enter") return sim.card ? doThing("finish-film") : simEnter();
  if (k === "back") return simBack();
  if (k === "top") { sim.stack = []; return simGo(manifest.start); }
  simMove(k);
}

// clicking a button on the simulated screen selects and presses it
document.addEventListener("mousedown", (ev) => {
  const img = ev.target.closest && ev.target.closest("#screen .btnimg");
  if (img) { ev.preventDefault(); simEnter(img.dataset.b); }
});
document.addEventListener("mouseover", (ev) => {
  const img = ev.target.closest && ev.target.closest("#screen .btnimg");
  if (img && !sim.card && img.dataset.b !== sim.sel) { sim.sel = img.dataset.b; updateButtons(); }
  if (view !== "films") return;
  const row = ev.target.closest && (ev.target.closest(".film-row, .film-detail") || ev.target.closest("[data-hot]"));
  const i = row ? +(row.dataset.i ?? row.dataset.hot) : null;
  setHot(Number.isNaN(i) ? null : i);
});

/* ------------------------------------------------- film reordering by dragging */
let dragFrom = null;
document.addEventListener("mousedown", (ev) => {
  const g = ev.target.closest && ev.target.closest("[data-grip]");
  if (g) g.closest(".film-row").draggable = true;
});
document.addEventListener("dragstart", (ev) => {
  const row = ev.target.closest && ev.target.closest(".film-row");
  if (!row) return;
  dragFrom = +row.dataset.i;
  row.classList.add("dragging");
  ev.dataTransfer.effectAllowed = "move";
  ev.dataTransfer.setData("text/x-boxset-row", String(dragFrom));
});
document.addEventListener("dragend", () => {
  $$(".film-row").forEach((r) => { r.draggable = false; r.classList.remove("dragging", "drop-before", "drop-after"); });
  dragFrom = null;
});

/* ------------------------------------------------- dropping files from Explorer */
let veilTimer = 0;
const hasFiles = (ev) => ev.dataTransfer && [...(ev.dataTransfer.types || [])].includes("Files");
document.addEventListener("dragover", (ev) => {
  if (dragFrom != null) {
    const row = ev.target.closest && ev.target.closest(".film-row");
    $$(".film-row").forEach((r) => r.classList.remove("drop-before", "drop-after"));
    if (row) {
      ev.preventDefault();
      const r = row.getBoundingClientRect();
      row.classList.add(ev.clientY < r.top + r.height / 2 ? "drop-before" : "drop-after");
    }
    return;
  }
  if (!hasFiles(ev)) return;
  ev.preventDefault();
  $("#dropVeil").hidden = false;
  clearTimeout(veilTimer);
  veilTimer = setTimeout(() => ($("#dropVeil").hidden = true), 250);
});
document.addEventListener("drop", (ev) => {
  if (dragFrom != null) {
    const row = ev.target.closest && ev.target.closest(".film-row");
    if (row) {
      ev.preventDefault();
      const r = row.getBoundingClientRect();
      let to = +row.dataset.i + (ev.clientY < r.top + r.height / 2 ? 0 : 1);
      if (to > dragFrom) to -= 1;
      if (to !== dragFrom) { openRow = null; editAct("move_film", dragFrom, to); }
    }
    return;
  }
  if (!hasFiles(ev)) return;
  ev.preventDefault();
  $("#dropVeil").hidden = true;
  // In the desktop app the window hands dropped files (with their full paths) to the engine.
  if (!S.native) toast("Dragging files in works in the desktop app. Use Add files here.", "info");
});

/* ===================================================================== start */
async function boot() {
  try {
    S = await call("state");
  } catch (e) {
    document.body.innerHTML = `<div class="empty"><div class="empty-inner"><h2>Boxset couldn't start</h2><p>${esc(e.message)}</p></div></div>`;
    return;
  }
  await loadManifest(true);
  render();
  const es = new EventSource("/events?t=" + encodeURIComponent(TOKEN));
  es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (err) { console.error(err); } };
}
boot();

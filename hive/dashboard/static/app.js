// The Hive dashboard: plain JS, no build step, no external libraries (so exports work offline).
"use strict";

const app = document.getElementById("app");
const EXPORT = window.HIVE_EXPORT || null;
const STAGES = ["scout", "build", "fix", "review"];
const STAGE_NAMES = { queen: "👑 Queen", scout: "🔎 Scouts", build: "🔨 Builders", fix: "🩹 Fixes", review: "🧐 Independent review" };
const COLORS = { queen: "var(--queen)", scout: "var(--scout)", build: "var(--build)", fix: "var(--fix)", review: "var(--review)" };
let stream = null;
let livePoll = null;

// --- helpers ---------------------------------------------------------------

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (x) => (x == null ? "–" : x >= 0.995 ? `$${x.toFixed(2)}` : `$${x.toFixed(3)}`);
const kTok = (n) => (n == null ? "–" : n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n));
const secs = (ms) => (ms == null ? "–" : ms < 120000 ? `${Math.round(ms / 1000)}s` : `${(ms / 60000).toFixed(1)}m`);
const when = (ts) => new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const clock = (ts, t0) => { const s = Math.max(0, Math.round(ts - t0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const total = (t) => (t ? (t.input || 0) + (t.output || 0) + (t.cache_read || 0) + (t.cache_write || 0) : 0);
const passPill = (p) => (p === true ? '<span class="pill ok">passed</span>' : p === false ? '<span class="pill bad">failed</span>' : '<span class="pill">–</span>');

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

function closeStreams() {
  if (stream) { stream.close(); stream = null; }
  if (livePoll) { clearInterval(livePoll); livePoll = null; }
}

function bars(rows, { format = usd, legend = null } = {}) {
  // rows: [{label, value, color} | {label, parts:[{value,color,name}], value}]
  const max = Math.max(...rows.map((r) => r.value || 0), 1e-9);
  const body = rows.map((r) => {
    const parts = r.parts || [{ value: r.value, color: r.color }];
    const segs = parts.map((p) => `<div class="bar" title="${esc(p.name || r.label)}: ${esc(format(p.value))}" style="width:${(100 * (p.value || 0)) / max}%;background:${p.color}"></div>`).join("");
    return `<div class="bar-row"><div>${r.label}</div><div class="bar-track">${segs}</div><div class="bar-val">${esc(format(r.value))}</div></div>`;
  }).join("");
  const leg = legend ? `<div class="legend">${legend.map(([name, color]) => `<span><i style="background:${color}"></i>${esc(name)}</span>`).join("")}</div>` : "";
  return `<div class="bars">${body}</div>${leg}`;
}

// --- event log → run state ------------------------------------------------------

function reconstruct(events) {
  const run = { start: null, briefs: new Map(), order: [], checks: [], queen: [], cost: null, acceptance: [], end: null, timeline: [] };
  for (const e of events) {
    switch (e.kind) {
      case "run_start": run.start = e; break;
      case "dispatch": {
        const brief = { ...e, status: "running", reports: [] };
        run.briefs.set(e.id, brief); run.order.push(e.id);
        run.timeline.push({ ts: e.ts, text: `👑 → ${esc(e.agent.split(":").pop())} <b>${esc(e.label)}</b> ${esc(e.description.slice(e.label.length))}` });
        break;
      }
      case "report": {
        const b = run.briefs.get(e.id);
        if (b) { b.reports.push(e.text); b.status = e.ok ? "reported" : "failed"; }
        run.timeline.push({ ts: e.ts, text: `🐝 <b>${esc(e.label)}</b> ${e.ok ? "reported" : "failed"}` });
        break;
      }
      case "bee_done": { const b = run.briefs.get(e.id); if (b && e.status !== "completed") b.status = e.status; break; }
      case "check": run.checks.push(e); run.timeline.push({ ts: e.ts, text: `👑 🔍 <code>${esc(e.command.slice(0, 120))}</code> ${e.ok ? "✅" : "❌"}` }); break;
      case "queen_text": run.queen.push(e.text); break;
      case "turn_end": run.cost = e.cost_usd; break;
      case "acceptance": run.acceptance.push(e); break;
      case "run_end": run.end = e; run.timeline.push({ ts: e.ts, text: `🍯 finished: ${esc(e.status)}` }); break;
    }
  }
  // A brief dispatched again under the same label is a return: count it on the latest dispatch.
  const counts = {};
  for (const id of run.order) { const b = run.briefs.get(id); counts[b.label] = (counts[b.label] || 0) + 1; b.attempt = counts[b.label]; }
  return run;
}

function beeCard(b) {
  const status = b.status === "reported" ? '<span class="pill ok">reported</span>'
    : b.status === "failed" ? '<span class="pill bad">failed</span>' : '<span class="pill run"><span class="dot live-dot"></span>working</span>';
  const again = b.attempt > 1 ? ` <span class="pill bad">return ${b.attempt - 1}</span>` : "";
  const doneWhen = (b.prompt || "").split("\n").find((l) => /^done when/i.test(l.trim()));
  const report = b.reports.length ? `<details><summary>report</summary><pre>${esc(b.reports[b.reports.length - 1])}</pre></details>` : "";
  return `<article class="bee ${b.stage}">
    <header><span class="label">${esc(b.label)}</span><span>${status}${again}</span></header>
    <div class="desc">${esc(b.description.slice(b.label.length).trim())}</div>
    ${doneWhen ? `<div class="mono muted" style="margin-top:4px">${esc(doneWhen.trim())}</div>` : ""}
    <details><summary>brief</summary><pre>${esc(b.prompt || "")}</pre></details>${report}
  </article>`;
}

function runTree(run) {
  const groups = STAGES.map((stage) => {
    const bees = run.order.map((id) => run.briefs.get(id)).filter((b) => b.stage === stage);
    if (!bees.length) return "";
    return `<section class="stage"><div class="stage-title">${STAGE_NAMES[stage]} · ${bees.length}</div><div class="bees">${bees.map(beeCard).join("")}</div></section>`;
  }).join("");
  const lastQueen = run.queen.length ? run.queen[run.queen.length - 1].replace(/```hive-summary[\s\S]*?```/, "").trim() : "";
  return `<div class="panel queen"><div class="stage-title">${STAGE_NAMES.queen}</div>
      <div class="answer">${esc(lastQueen || "planning…")}</div></div>
    ${groups || '<p class="muted">No bees dispatched yet.</p>'}`;
}

function statsSection(record) {
  const hive = record.hive;
  const stageRows = Object.entries(hive.by_stage || {}).sort(([a], [b]) => ["queen", ...STAGES].indexOf(a) - ["queen", ...STAGES].indexOf(b));
  const tokenBars = bars(stageRows.map(([stage, d]) => ({ label: STAGE_NAMES[stage] || stage, value: total(d.tokens), color: COLORS[stage] })), { format: kTok });
  const costBars = bars(stageRows.map(([stage, d]) => ({ label: STAGE_NAMES[stage] || stage, value: d.cost_usd_est, color: COLORS[stage] })));

  const variants = [{ label: `🐝 Hive <span class="muted">(${esc(record.queen.name)} + ${esc(record.workers.name)})</span>`, value: hive.cost_usd, color: "var(--accent)", passed: record.acceptance.passed, kind: "measured" }];
  for (const c of record.compare || []) variants.push({ label: `⚖️ ${esc(c.name)} alone`, value: c.cost_usd, color: "var(--solo)", passed: c.passed, kind: "measured", time: c.duration_ms, tokens: c.tokens });
  for (const e of record.estimates || []) variants.push({ label: `≈ ${esc(e.name)} alone <span class="muted">(estimate)</span>`, value: e.cost_usd, color: "color-mix(in srgb, var(--solo) 45%, transparent)", kind: "estimate" });

  const rows = variants.map((v) => `<tr><td>${v.label}</td><td>${v.kind === "estimate" ? "" : passPill(v.passed)}</td>
      <td class="num">${v.kind === "estimate" ? "" : kTok(total(v.tokens || hive.tokens))}</td><td class="num">${usd(v.value)}</td>
      <td class="num">${v.kind === "estimate" ? "" : secs(v.time ?? hive.duration_ms)}</td></tr>`).join("");
  const review = (record.summary || {}).review || {};
  const acc = (record.acceptance.results || []).map((r) => `<li>${r.ok ? "✅" : "❌"} <code>${esc(r.command)}</code></li>`).join("");
  return `
    <h2>Comparison</h2>
    <div class="panel">${bars(variants.map((v) => ({ label: v.label, value: v.value || 0, color: v.color })))}
      <p class="muted" style="font-size:13px;margin:10px 0 0">Estimates reprice the hive's own tokens at each model's price; only ⚖️ rows are real runs.</p></div>
    <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>variant</th><th>acceptance</th><th class="num">tokens</th><th class="num">cost</th><th class="num">time</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="grid" style="margin-top:12px">
      <div class="panel"><div class="stage-title">Tokens by stage</div>${tokenBars}</div>
      <div class="panel"><div class="stage-title">Cost by stage (≈)</div>${costBars}</div>
      <div class="panel"><div class="stage-title">Acceptance</div>${acc ? `<ul style="margin:0;padding-left:0;list-style:none">${acc}</ul>` : '<p class="muted">no acceptance command</p>'}
        <div class="stage-title" style="margin-top:12px">Review</div>
        <p style="margin:0">lenses: ${esc((review.lenses || []).join(", ") || "–")}<br>confirmed ${review.confirmed ?? 0} · fixed ${review.fixed ?? 0} · dismissed ${review.dismissed ?? 0}</p>
        ${(review.open || []).length ? `<p class="muted">open: ${esc(review.open.join("; "))}</p>` : ""}
        ${(review.suggestions || []).length ? `<p class="muted">suggestions: ${esc(review.suggestions.join("; "))}</p>` : ""}</div>
    </div>`;
}

function renderRun(data, { live = false } = {}) {
  const run = reconstruct(data.events);
  const record = data.record;
  const start = run.start || {};
  const t0 = start.ts || 0;
  const cost = record ? record.hive.cost_usd : run.cost;
  const exportBtn = record && !EXPORT ? `<a href="/api/runs/${encodeURIComponent(data.project)}/${encodeURIComponent(data.id)}/export"><button>Export as HTML</button></a>` : "";
  const status = record ? `<span class="pill ${record.status === "done" ? "ok" : "bad"}">${esc(record.status)}</span>` : '<span class="pill run"><span class="dot live-dot"></span>running</span>';
  const timeline = run.timeline.slice(-40).map((i) => `<li><span class="t">${clock(i.ts, t0)}</span><span>${i.text}</span></li>`).join("");
  app.innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:start">
      <div><h1>${esc(start.goal || record?.goal || "run")}</h1>
      <p class="sub">${status} · ${esc((start.folders || record?.folders || [""])[0])} · mode ${esc(start.mode || record?.mode)} · ${start.ts ? when(start.ts) : ""}</p></div>
      ${exportBtn}
    </div>
    <div class="tiles">
      <div class="tile"><div class="k">Queen</div><div class="v" style="font-size:16px">${esc(record?.queen.name || start.queen)}</div></div>
      <div class="tile"><div class="k">Cost</div><div class="v">${usd(cost)}</div></div>
      <div class="tile"><div class="k">Briefs</div><div class="v">${run.order.length}</div></div>
      <div class="tile"><div class="k">Checks</div><div class="v">${run.checks.filter((c) => c.ok).length}/${run.checks.length}</div></div>
    </div>
    ${runTree(run)}
    ${record ? statsSection(record) : ""}
    <h2>Timeline</h2><div class="panel"><ul class="timeline">${timeline || '<li class="muted">nothing yet</li>'}</ul></div>`;
  if (live && !record) follow(data);
}

function follow(data) {
  // The stream replays the whole log from the start, then follows new lines.
  closeStreams();
  const events = [];
  stream = new EventSource(`/api/runs/${encodeURIComponent(data.project)}/${encodeURIComponent(data.id)}/stream`);
  let pending = false;
  stream.onmessage = (msg) => {
    events.push(JSON.parse(msg.data));
    if (!pending) { pending = true; setTimeout(() => { pending = false; renderRun({ ...data, events }); }, 250); }
  };
  stream.addEventListener("end", async () => {
    closeStreams();
    renderRun(await api(`/api/runs/${encodeURIComponent(data.project)}/${encodeURIComponent(data.id)}`));
  });
}

// --- views -----------------------------------------------------------------

async function viewLive() {
  const runs = await api("/api/runs");
  const live = runs.find((r) => r.live);
  if (!live) {
    app.innerHTML = `<div class="empty"><div class="big">🐝</div><p>No hive is working right now.</p>
      <p>Start one in a terminal, for example <code>hive "Fix the failing tests" -d ~/project</code>. This page picks it up automatically.</p>
      ${runs[0] ? `<p><a href="#/run/${encodeURIComponent(runs[0].project)}/${encodeURIComponent(runs[0].id)}">See the last run →</a></p>` : ""}</div>`;
    livePoll = setInterval(async () => { if ((await api("/api/runs")).some((r) => r.live)) route(); }, 3000);
    return;
  }
  renderRun(await api(`/api/runs/${encodeURIComponent(live.project)}/${encodeURIComponent(live.id)}`), { live: true });
}

async function viewRuns() {
  const runs = await api("/api/runs");
  if (!runs.length) { app.innerHTML = `<div class="empty"><div class="big">🍯</div><p>No runs yet.</p></div>`; return; }
  const projects = [...new Set(runs.map((r) => r.project))];
  const queens = [...new Set(runs.map((r) => r.queen?.name).filter(Boolean))];
  const opt = (values, label) => `<option value="">${label}</option>` + values.map((v) => `<option>${esc(v)}</option>`).join("");
  app.innerHTML = `<h1>Runs</h1><p class="sub">${runs.length} runs across ${projects.length} projects</p>
    <div class="filters"><select id="fp">${opt(projects, "all projects")}</select><select id="fq">${opt(queens, "all Queens")}</select>
      <select id="fs"><option value="">any result</option><option value="pass">passed</option><option value="fail">failed</option></select></div>
    <div class="table-wrap"><table><thead><tr><th>when</th><th>goal</th><th>project</th><th>Queen</th><th>mode</th><th>acceptance</th><th class="num">cost</th><th class="num">saved</th></tr></thead><tbody id="rows"></tbody></table></div>`;
  const draw = () => {
    const [p, q, s] = ["fp", "fq", "fs"].map((id) => document.getElementById(id).value);
    document.getElementById("rows").innerHTML = runs.filter((r) => (!p || r.project === p) && (!q || r.queen?.name === q)
      && (!s || (s === "pass" ? r.passed === true : r.passed === false))).map((r) => {
      const saved = r.baseline && r.cost_usd ? 1 - r.cost_usd / r.baseline.cost_usd : null;
      return `<tr class="click" data-href="#/run/${encodeURIComponent(r.project)}/${encodeURIComponent(r.id)}">
        <td>${r.live ? '<span class="dot live-dot"></span>' : ""}${when(r.started_at)}</td><td>${esc(r.goal.slice(0, 90))}</td>
        <td>${esc(r.root.split("/").pop())}</td><td>${esc(r.queen?.name || "")}</td><td>${esc(r.mode)}</td>
        <td>${r.live ? '<span class="pill run">running</span>' : passPill(r.passed)}</td><td class="num">${usd(r.cost_usd)}</td>
        <td class="num">${saved == null ? "" : `${Math.round(saved * 100)}%${r.baseline.measured ? "" : "≈"}`}</td></tr>`;
    }).join("");
  };
  ["fp", "fq", "fs"].forEach((id) => document.getElementById(id).addEventListener("change", draw));
  document.getElementById("rows").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-href]"); if (tr) location.hash = tr.dataset.href; });
  draw();
}

function trendChart(runs) {
  const done = runs.filter((r) => r.cost_usd != null && !r.live).sort((a, b) => a.started_at - b.started_at).slice(-40);
  if (done.length < 2) return '<p class="muted">The trend appears after two finished runs.</p>';
  const W = 900, H = 220, P = 34;
  const max = Math.max(...done.map((r) => Math.max(r.cost_usd, r.baseline?.cost_usd || 0)), 0.001);
  const x = (i) => P + (i * (W - 2 * P)) / (done.length - 1);
  const y = (v) => H - P - (v * (H - 2 * P)) / max;
  const line = (vals, color, dash = "") => `<polyline fill="none" stroke="${color}" stroke-width="2" ${dash} points="${vals.map((v, i) => (v == null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ")}"/>`;
  const dots = done.map((r, i) => `<circle cx="${x(i)}" cy="${y(r.cost_usd)}" r="4" fill="${r.passed === false ? "var(--bad)" : "var(--accent)"}"><title>${esc(r.goal.slice(0, 60))} · ${usd(r.cost_usd)}</title></circle>`).join("");
  return `<svg class="trend" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Cost per run">
    <line x1="${P}" y1="${H - P}" x2="${W - P}" y2="${H - P}" stroke="var(--line)"/>
    <text x="4" y="${y(max) + 4}">${usd(max)}</text><text x="4" y="${H - P + 4}">$0</text>
    ${line(done.map((r) => r.baseline?.cost_usd ?? null), "var(--solo)", 'stroke-dasharray="5 4"')}
    ${line(done.map((r) => r.cost_usd), "var(--accent)")}${dots}</svg>
    <div class="legend"><span><i style="background:var(--accent)"></i>hive cost per run (red dot: acceptance failed)</span><span><i style="background:var(--solo)"></i>same Queen alone (measured or estimated)</span></div>`;
}

async function viewCompare() {
  const runs = await api("/api/runs");
  const compared = runs.filter((r) => r.compare && !r.live);
  const byQueen = {};
  for (const r of runs.filter((r) => r.cost_usd != null && !r.live)) {
    const q = (byQueen[r.queen?.name || "?"] ||= { n: 0, cost: 0, passed: 0, judged: 0, savings: [] });
    q.n++; q.cost += r.cost_usd;
    if (r.passed != null) { q.judged++; q.passed += r.passed ? 1 : 0; }
    if (r.baseline) q.savings.push(1 - r.cost_usd / r.baseline.cost_usd);
  }
  const queenRows = Object.entries(byQueen).map(([name, q]) => `<tr><td>${esc(name)}</td><td class="num">${q.n}</td><td class="num">${usd(q.cost / q.n)}</td>
    <td class="num">${q.judged ? Math.round((100 * q.passed) / q.judged) + "%" : "–"}</td>
    <td class="num">${q.savings.length ? Math.round((100 * q.savings.reduce((a, b) => a + b, 0)) / q.savings.length) + "%" : "–"}</td></tr>`).join("");
  app.innerHTML = `<h1>Compare</h1><p class="sub">The hive against single models doing the whole job alone.</p>
    <div class="panel">${trendChart(runs)}</div>
    <h2>By Queen</h2><div class="table-wrap"><table><thead><tr><th>Queen</th><th class="num">runs</th><th class="num">avg cost</th><th class="num">pass rate</th><th class="num">avg saving vs alone</th></tr></thead><tbody>${queenRows || '<tr><td colspan="5" class="muted">no finished runs</td></tr>'}</tbody></table></div>
    <h2>Runs with a real side-by-side (--compare)</h2>
    ${compared.length ? `<div class="table-wrap"><table><tbody>${compared.map((r) => `<tr class="click" data-href="#/run/${encodeURIComponent(r.project)}/${encodeURIComponent(r.id)}"><td>${when(r.started_at)}</td><td>${esc(r.goal.slice(0, 90))}</td><td>${passPill(r.passed)}</td><td class="num">${usd(r.cost_usd)}</td></tr>`).join("")}</tbody></table></div>`
      : '<p class="muted">None yet. Run a goal with <code>--compare</code> to measure single models on the same job.</p>'}`;
  app.querySelectorAll("tr[data-href]").forEach((tr) => tr.addEventListener("click", () => (location.hash = tr.dataset.href)));
}

async function viewProjects() {
  const projects = await api("/api/projects");
  if (!projects.length) { app.innerHTML = `<div class="empty"><div class="big">📂</div><p>No projects yet. Run <code>hive init DIR</code>.</p></div>`; return; }
  app.innerHTML = `<h1>Projects</h1><p class="sub">Hive memory lives in ~/.hive, never inside your projects.</p>
    ${projects.map((p, i) => `<div class="panel" style="margin-bottom:12px"><strong>${esc(p.root.split("/").pop() || p.id)}</strong>
      <span class="muted"> · ${esc(p.root)} · ${p.runs} runs</span>
      <div class="memory-tabs" data-i="${i}">${Object.keys(p.files).map((f, j) => `<button data-f="${esc(f)}" class="${j ? "" : "active"}">${esc(f)}</button>`).join("")}</div>
      <pre id="mem-${i}">${esc(p.files["profile.md"])}</pre><p class="muted mono" style="margin:8px 0 0">${esc(p.path)}</p></div>`).join("")}`;
  app.querySelectorAll(".memory-tabs").forEach((tabs) => tabs.addEventListener("click", (e) => {
    const btn = e.target.closest("button"); if (!btn) return;
    const i = tabs.dataset.i;
    tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
    document.getElementById(`mem-${i}`).textContent = projects[i].files[btn.dataset.f];
  }));
}

async function viewModels() {
  const data = await api("/api/models");
  const access = (a) => (!a ? '<span class="pill">not checked</span>' : a.ok ? '<span class="pill ok">available</span>' : `<span class="pill bad" title="${esc(a.error)}">no access</span>`);
  app.innerHTML = `<h1>Models</h1><p class="sub">Prices per million tokens, as of ${esc(data.prices_as_of)}. Last Queen: ${esc(data.last_queen || "–")}.</p>
    <div class="table-wrap"><table><thead><tr><th>model</th><th>id</th><th>role</th><th class="num">input</th><th class="num">output</th><th class="num">cache read</th><th>access</th></tr></thead><tbody>
    ${data.models.map((m) => `<tr><td>${esc(m.name)}<div class="muted" style="font-size:12px">${esc(m.note)}</div></td><td class="mono">${esc(m.id)}</td><td>${m.role === "queen" ? "👑 Queen" : "🐝 bees"}</td>
      <td class="num">$${m.input}</td><td class="num">$${m.output}</td><td class="num">$${m.cache_read}</td><td>${access(m.access)}</td></tr>`).join("")}
    </tbody></table></div><p style="margin-top:12px"><button class="primary" id="recheck">Re-check access</button> <span class="muted" id="recheck-note">sends one tiny request per model</span></p>`;
  document.getElementById("recheck").addEventListener("click", async (e) => {
    e.target.disabled = true; document.getElementById("recheck-note").textContent = "checking…";
    await api("/api/models/check", { method: "POST" }); viewModels();
  });
}

// --- router ----------------------------------------------------------------

async function route() {
  closeStreams();
  const parts = (location.hash.replace(/^#\/?/, "") || "live").split("/").map(decodeURIComponent);
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === (parts[0] === "run" ? "runs" : parts[0])));
  try {
    if (parts[0] === "run") renderRun(await api(`/api/runs/${encodeURIComponent(parts[1])}/${encodeURIComponent(parts[2])}`), { live: true });
    else if (parts[0] === "runs") await viewRuns();
    else if (parts[0] === "compare") await viewCompare();
    else if (parts[0] === "projects") await viewProjects();
    else if (parts[0] === "models") await viewModels();
    else await viewLive();
  } catch (err) {
    app.innerHTML = `<div class="empty"><div class="big">⚠️</div><p>${esc(err.message)}</p></div>`;
  }
}

if (EXPORT) {
  document.getElementById("nav").remove();
  renderRun(EXPORT);
} else {
  window.addEventListener("hashchange", route);
  route();
}

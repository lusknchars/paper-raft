const D = window.RAFT_DATA;
const app = document.getElementById("app");
const drawer = document.getElementById("drawer");
const COLORS = ["#7aa2ff", "#ffb86b", "#7ee0a1", "#ff7a90", "#c792ea", "#5fd7d7"];
const AXIS = { ticks: { color: "#8b9099" }, grid: { color: "#24272d" } };
let charts = [];

function safeUrl(u) {
  return typeof u === "string" && /^https:\/\//.test(u) ? u : null;
}

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) n.append(kid.nodeType ? kid : String(kid));
  return n;
}
const fmt = (x) => (x == null ? "—" : x !== 0 && Math.abs(x) < 1e-3 ? x.toExponential(2) : x.toFixed(4));
const badge = (s) => el("span", { class: "badge " + s.replace(" ", "-") }, s);
const same = (a, b) => String(a) === String(b);
const CHECKER = {
  "approved": (c) => `checker approved after ${c.rounds} attack round${c.rounds === 1 ? "" : "s"}`,
  "approved-before-attacks": () => "checker approved before attack rounds existed",
  "stale": () => "checker changed since approval",
  "missing": () => "checker not approved",
};
const checkerLine = (s) => s.checker ? el("p", { class: "muted" }, CHECKER[s.checker.state](s.checker)) : null;

let flowHandle = null;
function clear() {
  charts.forEach((c) => c.destroy()); charts = [];
  if (flowHandle) { flowHandle.destroy(); flowHandle = null; }
}

function mountFlowInto(box, data, opts) {
  import("./flow/flow.js")
    .then((m) => { if (box.isConnected) flowHandle = m.mountFlow(box, data, opts); })
    .catch(() => box.replaceChildren(el("p", { class: "muted" },
      "The flow view needs the site served over http (for example `uv run raft watch`).")));
}

function draftsAsOthers() {
  return Object.values(D.flows || {}).filter((f) => f.paper.draft)
    .map((f) => ({ title: f.paper.title, note: "draft · nothing extracted yet" }));
}

function flowView(id) {
  const data = D.flows[id];
  const study = D.studies.find((s) => s.id === id);
  app.append(...(study ? studyNav(study) : [el("nav", {}, el("a", { href: "#" }, "← all studies")), el("h2", {}, data.paper.title)]));
  const box = el("div", { class: "flow-box" });
  app.append(box);
  mountFlowInto(box, data, {});
}

function route() {
  clear();
  app.replaceChildren();
  if (!D) { app.append(el("p", {}, "No data.js found. Run `uv run raft compare` first.")); return; }
  const [view, id, sub] = location.hash.slice(1).split("/");
  const study = D.studies.find((s) => s.id === id);
  if (view === "flow" && D.flows && Object.hasOwn(D.flows, id)) flowView(id);
  else if (view === "study" && study) (sub === "extraction" ? extractionView : compareView)(study);
  else if (view === "bench") benchView();
  else overview();
}

function overview() {
  if (!D.studies.length) { app.append(el("p", {}, "No studies yet.")); return; }
  const head = D.flows && D.flows[D.studies[0].id];
  if (head) {
    const box = el("div", { class: "flow-box" });
    app.append(el("p", { class: "muted" }, "How the headline study is built, from the paper to the runs. ",
      el("a", { href: `#flow/${D.studies[0].id}` }, "Open the flow")), box);
    mountFlowInto(box, head, { others: draftsAsOthers() });
  }
  app.append(el("a", { class: "card", href: "#bench" },
    el("h2", {}, "Bench: bring your agent"), el("p", { class: "muted" }, benchSummary())));
  for (const s of D.studies) {
    app.append(el("a", { class: "card", href: `#study/${s.id}` },
      el("h2", {}, s.paper.title || s.id),
      el("p", { class: "muted" }, s.reference.citation),
      checkerLine(s),
      el("p", {}, ["verified", "unverified", "failed", "no run"].map((k) =>
        el("span", { class: "count" }, badge(k), " ", s.counts[k] || 0)))));
  }
}

function paramValues(study) {
  const values = {};
  for (const m of study.methods) for (const r of m.runs) for (const [k, v] of Object.entries(r.params)) {
    (values[k] ||= new Set()).add(v);
  }
  return Object.fromEntries(Object.entries(values).map(([k, s]) => [k, [...s].sort((a, b) => a - b)]));
}

function studyNav(study) {
  return [
    el("nav", {}, el("a", { href: "#" }, "← all studies"), " · ",
      el("a", { href: `#study/${study.id}` }, "results"), " · ",
      el("a", { href: `#flow/${study.id}` }, "flow"), " · ",
      el("a", { href: `#study/${study.id}/extraction` }, "extraction")),
    el("h2", {}, study.paper.title || study.id),
    el("p", { class: "muted" }, study.reference.citation, " · ",
      el("a", { href: `https://doi.org/${study.reference.doi}`, target: "_blank", rel: "noopener noreferrer" }, "DOI"),
      safeUrl(study.paper.brief_url) && [" · ",
        el("a", { href: study.paper.brief_url, target: "_blank", rel: "noopener noreferrer" }, "Read the brief on Paperraft")]),
    checkerLine(study),
    study.paper.experiment && el("p", { class: "experiment" }, study.paper.experiment),
  ];
}

function compareView(study) {
  const values = paramValues(study);
  const sel = {};
  for (const [k, vs] of Object.entries(values)) sel[k] = k in study.headline ? study.headline[k] : vs[0];
  const controls = el("div", { class: "controls" });
  const body = el("div");
  app.append(...studyNav(study), controls, body);
  for (const [k, vs] of Object.entries(values)) {
    const s = el("select", { "aria-label": k, onchange: (e) => { sel[k] = e.target.value; render(); } },
      vs.map((v) => { const o = el("option", { value: v }, v); o.selected = same(v, sel[k]); return o; }));
    controls.append(el("label", {}, k, " ", s));
  }

  function render() {
    clear();
    body.replaceChildren();
    const rows = study.methods.map((m) => ({ m, run: m.runs.find((r) => Object.keys(sel).every((k) => same(r.params[k], sel[k]))) }));
    if (!rows.some((r) => r.run)) { body.append(el("p", {}, "No runs for this combination.")); return; }
    const ok = rows.filter((r) => r.run && r.run.results.status === "ok");

    const grid = el("div", { class: "charts" });
    body.append(grid);
    // Methods graded against different claims report different keys: show the union, each method where it has data.
    const union = (pick) => [...new Set(ok.flatMap((r) => Object.keys(pick(r.run.results) || {})))];
    for (const key of union((res) => res.samples)) {
      const has = ok.filter((r) => r.run.results.samples[key]);
      const canvas = el("canvas", { role: "img", "aria-label": `${key} by method against the paper` });
      grid.append(el("figure", {}, el("figcaption", {}, key), canvas));
      const datasets = has.map((r) => {
        const color = COLORS[ok.indexOf(r) % COLORS.length];
        return { label: r.m.name, data: r.run.results.samples[key].map(([x, y]) => ({ x, y })),
          borderColor: color, backgroundColor: color, showLine: true, pointRadius: r.run.results.samples[key].length > 40 ? 0 : 2, borderWidth: 1.5 };
      });
      const ref = has[0].run.results.reference_samples?.[key];
      if (ref) datasets.push({ label: "paper", data: ref.map(([x, y]) => ({ x, y })), borderColor: "#e6e6e6",
        backgroundColor: "#e6e6e6", showLine: false, pointRadius: 4, pointStyle: "crossRot" });
      charts.push(new Chart(canvas, { type: "scatter", data: { datasets },
        options: { animation: false, scales: { x: AXIS, y: AXIS }, plugins: { legend: { labels: { color: "#e6e6e6" } } } } }));
    }

    const errKeys = union((res) => res.errors);
    const tols = [...new Set(ok.map((r) => r.run.results.tolerance))];
    const tbody = el("tbody", {}, rows.map(({ m, run }) => {
      if (!run) return el("tr", {}, el("td", {}, m.name), el("td", { colspan: errKeys.length + 3, class: "muted" }, "no run"));
      const r = run.results;
      return el("tr", {}, el("td", {}, m.name),
        errKeys.map((k) => el("td", { class: "num" }, fmt(r.errors?.[k]))),
        el("td", {}, r.status === "ok" ? (r.pass ? "yes" : "no") + (tols.length > 1 ? ` (≤ ${r.tolerance})` : "") : "—"),
        el("td", { class: "wrap" }, badge(run.status), r.reason ? " " + r.reason : ""),
        el("td", {}, el("button", { onclick: () => openDrawer(study, m, run) }, "provenance")));
    }));
    const tol = tols.length === 1 ? tols[0] : null;
    body.append(el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "method"), errKeys.map((k) => el("th", {}, k)),
        el("th", {}, tol != null ? `≤ ${tol}` : "pass"), el("th", {}, "status"), el("th", {}, ""))), tbody)));

    const withFields = ok.filter((r) => r.run.results.fields_coarse);
    for (const field of withFields.length ? Object.keys(withFields[0].run.results.fields_coarse) : []) {
      const base = el("select", { "aria-label": `${field} baseline` }, el("option", { value: "" }, "none"),
        withFields.map((r) => el("option", { value: r.m.name }, r.m.name)));
      const maps = el("div", { class: "maps" });
      const draw = () => {
        maps.replaceChildren();
        const b = withFields.find((r) => r.m.name === base.value);
        for (const r of withFields) {
          const f = r.run.results.fields_coarse[field];
          const diff = b && b !== r;
          const g = diff ? f.map((row, j) => row.map((v, i) => v - b.run.results.fields_coarse[field][j][i])) : f;
          maps.append(el("figure", {}, heatmap(g, `${r.m.name} ${field}`), el("figcaption", {}, diff ? `${r.m.name} − ${b.m.name}` : `${r.m.name} ${field}`)));
        }
      };
      base.addEventListener("change", draw);
      body.append(el("h3", {}, field), el("label", {}, "difference from ", base), maps);
      draw();
    }
  }
  render();
}

function heatmap(f, label) {
  const n = f.length, m = f[0].length;
  const c = el("canvas", { width: m, height: n, class: "heat", role: "img", "aria-label": label });
  const ctx = c.getContext("2d");
  const img = ctx.createImageData(m, n);
  const max = Math.max(1e-12, ...f.flat().map(Math.abs));
  for (let j = 0; j < n; j++) for (let i = 0; i < m; i++) {
    const t = f[j][i] / max, k = ((n - 1 - j) * m + i) * 4;
    const [r, g, b] = t >= 0 ? [255, 170, 80] : [90, 140, 255];
    const a = Math.abs(t);
    img.data[k] = 20 + (r - 20) * a; img.data[k + 1] = 20 + (g - 20) * a; img.data[k + 2] = 24 + (b - 24) * a; img.data[k + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

function openDrawer(study, m, run) {
  const body = document.getElementById("drawer-body");
  const items = new Map((study.extraction?.items || []).map((i) => [i.id, i]));
  const rv = m.review, man = run.manifest;
  body.replaceChildren(
    el("h3", {}, `${m.name} · ${run.run_id}`), badge(run.status),
    run.code_url ? el("p", {}, el("a", { href: run.code_url, target: "_blank", rel: "noopener" }, "solver code at this commit ↗"))
      : el("p", { class: "muted" }, "No code link (no remote, or the run was dirty)."),
    el("h4", {}, "Paper pages behind it"),
    el("ul", {}, (m.method?.implements || []).map((id) => {
      const it = items.get(id);
      return el("li", {}, it ? `p. ${it.page}: ${it.text}` : `${id} (not in extraction)`, " ",
        it?.missing ? el("span", { class: "badge missing" }, "missing in paper") : null);
    })),
    el("h4", {}, "Review"),
    rv ? el("div", {},
      el("p", {}, `${rv.verdict} by ${rv.reviewer_agent} at ${rv.reviewed_sha.slice(0, 10)}`),
      rv.summary ? el("p", {}, rv.summary) : null,
      rv.reviewed_sha !== man.method_sha ? el("p", { class: "warn" }, "This review is for a different solver commit than this run.") : null,
      el("ul", {}, rv.discrepancies.map((d) => el("li", {}, `[${d.severity}] ${d.file}:${d.line} vs p. ${d.page} (${d.extraction_id}): ${d.description}`))))
      : el("p", { class: "muted" }, "Not reviewed yet."),
    el("h4", {}, "Manifest"), el("pre", {}, JSON.stringify(man, null, 2)));
  drawer.hidden = false;
  document.getElementById("drawer-close").focus();
}

function extractionView(study) {
  app.append(...studyNav(study));
  const items = study.extraction?.items;
  if (!items) { app.append(el("p", {}, "No extraction yet.")); return; }
  app.append(el("div", { class: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ["id", "kind", "page", "statement", "quote / assumption"].map((h) => el("th", {}, h)))),
    el("tbody", {}, items.map((i) => el("tr", {}, el("td", {}, i.id), el("td", {}, i.kind), el("td", { class: "num" }, i.page),
      el("td", { class: "wrap" }, i.text),
      el("td", { class: "wrap" }, i.missing ? [el("span", { class: "badge missing" }, "missing in paper"), " ", i.assumption] : `“${i.quote}”`)))))));
}

document.getElementById("drawer-close").addEventListener("click", () => { drawer.hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") drawer.hidden = true; });
function benchSummary() {
  const b = D.bench || {};
  const n = Object.values(b).reduce((a, r) => a + r.full.length + r.partial.length, 0);
  if (!n) return "No entries yet. Give a paper to your Claude Code or Codex setup and see how it scores.";
  const tops = Object.values(b).map((r) => r.full[0] && `${r.full[0].entrant} ${r.full[0].passed}/${r.full[0].expected}`).filter(Boolean);
  return `${n} ${n === 1 ? "entry" : "entries"}. ` + (tops.length ? `Top: ${tops.join(" · ")}` : "Partial entries only so far.");
}

const money = (x) => (x == null ? "—" : "$" + x.toFixed(2));
const kTokens = (r) => (r.input_tokens == null || r.output_tokens == null ? "—" : Math.round((r.input_tokens + r.output_tokens) / 1000) + "k");
const minutes = (s) => Math.round(s / 60) + " min";

function benchTable(rows, ranked) {
  return el("div", { class: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ["#", "agent", "setup", "score", "time", "tokens*", "cost*", "code"].map((h) => el("th", {}, h)))),
    el("tbody", {}, rows.map((r, i) => el("tr", {},
      el("td", {}, ranked ? String(i + 1) : "—"),
      el("td", {}, r.entrant),
      el("td", { class: "wrap" }, r.label || "—"),
      el("td", { class: "num" }, `${r.passed}/${r.expected}`),
      el("td", { class: "num" }, minutes(r.wall_s)),
      el("td", { class: "num" }, kTokens(r)),
      el("td", { class: "num" }, money(r.cost_usd)),
      el("td", {}, safeUrl(r.url) ? el("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, "code") : "—"))))));
}

function benchView() {
  const first = D.studies[0] ? D.studies[0].id : "<study>";
  app.append(el("nav", {}, el("a", { href: "#" }, "← all studies")), el("h2", {}, "Bench"),
    el("p", {}, "Bring your agent setup: a model, an AGENTS.md or CLAUDE.md, your skills. Paper Raft gives it a study ",
      "in a blind workspace, with no answers and no grader in it, then grades its code with the study's own measure ",
      "in a copy the agent never touched."),
    el("pre", {}, `uv run raft bench --study ${first} --agent codex --setup ./my-setup --label "my setup"`),
    el("p", { class: "muted" }, "Entries are graded automatically and not reviewed; ranking uses the score only. * Reported by the agent's tool, not verified."));
  const bench = D.bench || {};
  if (!Object.keys(bench).length) { app.append(el("p", {}, "No entries yet.")); return; }
  for (const [sid, r] of Object.entries(bench)) {
    const s = D.studies.find((x) => x.id === sid);
    app.append(el("h3", {}, s ? s.paper.title || sid : sid));
    if (r.full.length) app.append(el("p", { class: "muted" }, "Every method attempted"), benchTable(r.full, true));
    if (r.partial.length) app.append(el("p", { class: "muted" }, "Some methods attempted (not ranked)"), benchTable(r.partial, false));
  }
}

window.addEventListener("hashchange", route);
route();

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

function clear() { charts.forEach((c) => c.destroy()); charts = []; }

function route() {
  clear();
  app.replaceChildren();
  if (!D) { app.append(el("p", {}, "No data.js found. Run `uv run raft compare` first.")); return; }
  const [view, id, sub] = location.hash.slice(1).split("/");
  const study = D.studies.find((s) => s.id === id);
  if (view === "study" && study) (sub === "extraction" ? extractionView : compareView)(study);
  else overview();
}

function overview() {
  if (!D.studies.length) { app.append(el("p", {}, "No studies yet.")); return; }
  for (const s of D.studies) {
    app.append(el("a", { class: "card", href: `#study/${s.id}` },
      el("h2", {}, s.paper.title || s.id),
      el("p", { class: "muted" }, s.reference.citation),
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
      el("a", { href: `#study/${study.id}/extraction` }, "extraction")),
    el("h2", {}, study.paper.title || study.id),
    el("p", { class: "muted" }, study.reference.citation, " · ",
      el("a", { href: `https://doi.org/${study.reference.doi}`, target: "_blank", rel: "noopener noreferrer" }, "DOI"),
      safeUrl(study.paper.brief_url) && [" · ",
        el("a", { href: study.paper.brief_url, target: "_blank", rel: "noopener noreferrer" }, "Read the brief on Paperraft")]),
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
window.addEventListener("hashchange", route);
route();

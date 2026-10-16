// The Paper Raft app: the lab's own files, in Paperraft's design. Copy buttons only: it never starts a run.
const app = document.getElementById("app");
const LABELS = { testar: "Test it", observar: "Watch", nao_aplica: "Not applicable" };
const TABS = ["overview", "results", "flow", "checker", "gaps", "bench"];
let mounted = [];
let gen = 0;  // the current page; a view that finishes after the user moved on draws nothing
const STALE = Symbol("stale");
function guard() {
  const g = gen;
  return (p) => Promise.resolve(p).then((v) => { if (g !== gen) throw STALE; return v; });
}
let home = null;

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) n.append(kid.nodeType ? kid : String(kid));
  return n;
}
function put(parent, ...kids) {  // like append, but empty values (null, false) add nothing
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) parent.append(kid.nodeType ? kid : String(kid));
}
const safeUrl = (u) => (typeof u === "string" && /^https:\/\//.test(u) ? u : null);
const ext = (href, text) => (safeUrl(href) ? el("a", { href, target: "_blank", rel: "noopener noreferrer" }, text) : null);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

export function parseId(text) {
  const m = String(text || "").trim().match(/(?:^|arxiv:|\/papers\/|\/abs\/|\/pdf\/)(\d{4}\.\d{4,5})(?:v\d+)?\/?$/i);
  return m ? m[1] : null;
}

function cmd(text) {
  const button = el("button", { type: "button" }, "Copy");
  button.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); button.textContent = "Copied"; }
    catch { button.textContent = "Select it"; }
    setTimeout(() => { button.textContent = "Copy"; }, 1600);
  });
  return el("div", { class: "cmd", "data-copy": text }, el("code", {}, text), button);
}

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

function gates(stages) {
  return el("ul", { class: "gates", "aria-label": "Gates" }, stages.map((s) =>
    el("li", { class: "gate " + (s.ok === true ? "ok" : s.ok === false ? "bad" : ""), title: `${s.name}: ${s.text}` },
      (s.ok === true ? "✓ " : s.ok === false ? "✗ " : "· ") + s.name)));
}

function studyCard(s) {
  return el("article", { class: "card study-card" },
    el("p", {}, s.draft ? el("span", { class: "tag draft" }, "draft") : null,
      s.arxiv ? el("span", { class: "tag" }, `arXiv ${s.arxiv}`) : null),
    el("a", { class: "title", href: `#/study/${s.id}/overview` }, el("h3", {}, s.title)),
    gates(s.stages),
    s.last_stop ? el("p", { class: "stop" }, `Last stop: ${s.last_stop.headline}`) : null,
    s.error ? el("p", { class: "stop" }, s.error) : null,
    cmd(s.next));
}

function setNav(view) {
  for (const a of document.querySelectorAll("[data-nav]")) {
    if (a.dataset.nav === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
}

function clear() {
  for (const m of mounted) { try { m.destroy(); } catch { /* already gone */ } }
  mounted = [];
  app.replaceChildren();
}

async function loadHome(force = false) {
  if (!home || force) home = await getJSON("/app.json");
  return home;
}

async function homeView() {
  const wait = guard();
  const d = await wait(loadHome(true));
  const c = d.counts;
  const blocked = (s) => s.stages.find((g) => g.ok === false);
  const first = d.studies.find((s) => !s.draft && blocked(s))
    || d.studies.find((s) => blocked(s) && blocked(s).name !== "paper") || d.studies.find(blocked);
  put(app, 
    el("p", { class: "eyebrow" }, `Your lab · ${d.today}`),
    el("h1", {}, `${plural(c.studies, "study", "studies")}, ${c.running} running.`),
    el("p", { class: "deck" }, first ? `Next for ${first.title}:` : "Every study is up to date. Find a paper to bring in next."),
    first ? cmd(first.next) : null,
    d.warning ? el("p", { class: "warning" }, d.warning) : null,
    el("div", { class: "stats" },
      [["Studies", c.studies], ["Verified runs", c.verified_runs ?? "—"], ["Bench entries", c.bench_entries], ["Open gaps", c.open_gaps]]
        .map(([k, v]) => el("div", { class: "stat" }, el("b", {}, k), el("span", {}, v)))));
  const running = d.sessions.filter((s) => s.state === "running");
  if (running.length) {
    const box = el("div", { class: "grid running" });
    put(app, el("p", { class: "section-title" }, "Running now"), box);
    const live = await wait(import("/flow/live.js"));
    for (const s of running) {
      const slot = el("div", { class: "dark" });
      put(box, el("a", { href: "#/running", class: "card", "aria-label": `${s.study}, running` }, slot));
      mounted.push(live.mountLive(slot, { url: "/live.json", compact: true, study: s.study }));
    }
  }
  put(app, el("p", { class: "section-title" }, "Studies"),
    d.studies.length ? el("div", { class: "grid" }, d.studies.map(studyCard))
      : el("p", { class: "muted" }, "No studies yet. Paste an arXiv id above to start one."));
}

async function runningView() {
  const wait = guard();
  put(app, el("p", { class: "eyebrow" }, "Live sessions"), el("h2", {}, "Running"),
    el("p", { class: "deck" }, "What prepare and bench are doing on this machine. Start a run in your terminal with --watch."));
  const slot = el("div", { class: "dark" });
  put(app, slot);
  const live = await wait(import("/flow/live.js"));
  mounted.push(live.mountLive(slot, { url: "/live.json" }));
}

function benchTable(rows) {
  return el("div", { class: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ["Agent", "Setup", "Score", "Time", "Code"].map((h) => el("th", {}, h)))),
    el("tbody", {}, rows.map((r) => el("tr", {}, el("td", {}, r.entrant), el("td", {}, r.label || "—"),
      el("td", {}, `${r.passed}/${r.expected}`), el("td", {}, `${Math.round(r.wall_s / 60)} min`),
      el("td", {}, ext(r.url, "code") || "—"))))));
}

async function benchView() {
  const d = await guard()(loadHome(true));
  put(app, el("p", { class: "eyebrow" }, "Bring your agent"), el("h2", {}, "Bench"),
    el("p", { class: "deck" }, "Your agent works blind; the study's own grader scores its code in a copy it never touched."),
    cmd(`uv run raft bench --study ${d.studies.find((s) => !s.draft)?.id || "<study>"} --agent <claude-code|codex> --watch`));
  const studies = Object.entries(d.bench);
  if (!studies.length) { put(app, el("p", { class: "muted" }, "No bench entries on this machine yet.")); return; }
  for (const [sid, r] of studies) {
    put(app, el("p", { class: "section-title" }, sid));
    if (r.full.length) put(app, benchTable(r.full));
    if (r.partial.length) put(app, el("p", { class: "muted" }, "Some methods only (not ranked)"), benchTable(r.partial));
  }
}

function paperForm() {
  put(app, el("p", { class: "eyebrow" }, "Paperraft"), el("h2", {}, "Find a paper"),
    el("p", { class: "deck" }, "Paste an arXiv id or a paperaft.vercel.app link in the search bar above. You'll see Paperraft's brief next to what your lab has for it."));
}

async function paperView(id) {
  const [ans, d] = await guard()(Promise.all([getJSON(`/paperraft/${id}.json`), loadHome()]));
  const b = ans.brief;
  const mine = d.studies.find((s) => s.arxiv === id);
  put(app, el("p", { class: "eyebrow" }, `arXiv ${id}` + (b && b.as_of ? ` · brief as of ${b.as_of}` : "")));
  const brief = el("section", { class: "block pr-brief" }, el("p", { class: "label" }, "Paperraft's brief"));
  if (b) {
    put(brief, el("h2", {}, b.title || `arXiv ${id}`),
      ans.stale ? el("p", { class: "warning" }, "Paperraft can't be reached; this is the copy saved on this machine.") : null,
      b.recommendation ? el("p", {}, el("span", { class: "tag" }, `Paperraft says: ${LABELS[b.recommendation] || b.recommendation}`)) : null,
      b.summary ? el("p", { class: "deck" }, b.summary) : null,
      (b.claims || []).some((c) => c && c.statement)
        ? el("ul", {}, b.claims.filter((c) => c && c.statement).slice(0, 6).map((c) => el("li", {}, c.statement))) : null,
      (b.minimum_test || []).length ? el("div", {}, el("h3", {}, "Minimum test"),
        el("ul", {}, b.minimum_test.filter(Boolean).map((t) => el("li", {}, typeof t === "string" ? t : t.statement || t.step || JSON.stringify(t))))) : null,
      el("p", { class: "links" }, ext(b.brief_url, "Read the brief on Paperraft"), ext(b.source_url, "arXiv")));
    for (const r of (b.lab_reproductions || []).filter(Boolean)) {
      put(brief, el("div", { class: "card" }, el("h3", {}, r.title || "Reproduction"), el("p", {}, r.summary || ""),
        r.methods_total ? el("p", { class: "muted" }, `${r.methods_verified}/${r.methods_total} methods verified`) : null));
    }
  } else {
    put(brief, el("h2", {}, `arXiv ${id}`), el("p", { class: "muted" }, ans.offline
      ? "Paperraft can't be reached and there is no saved copy of its brief."
      : `Paperraft has no brief for arXiv:${id}.`));
  }
  const lab = el("section", { class: "block lab-block" }, el("p", { class: "label" }, "In your lab"));
  if (mine) put(lab, studyCard(mine));
  else put(lab, el("p", {}, "No study yet. Bring it in:"), cmd(`uv run raft prepare --arxiv ${id} --agent <claude-code|codex> --watch`));
  put(app, brief, lab);
}

function overviewTab(s, body) {
  put(body, gates(s.stages),
    el("div", { class: "table-wrap" }, el("table", {}, el("tbody", {}, s.stages.map((g) =>
      el("tr", {}, el("td", {}, g.name), el("td", {}, g.text)))))),
    el("p", { class: "section-title" }, "Next"), cmd(s.next),
    s.last_stop ? el("p", { class: "stop" }, `Last stop: ${s.last_stop.headline} (${s.last_stop.at.slice(0, 16).replace("T", " ")})`) : null,
    s.experiment ? el("div", { class: "note" }, el("p", { class: "section-title" }, "Experiment"), el("p", {}, s.experiment)) : null);
}

const num = (x) => (typeof x !== "number" ? "—" : x !== 0 && Math.abs(x) < 1e-3 ? x.toExponential(2) : String(Number(x.toPrecision(4))));

function resultsTab(s, body) {
  if (s.results === null) { put(body, el("p", { class: "warning" }, s.warning || "Results could not be read.")); return; }
  if (!s.results.length) { put(body, el("p", { class: "muted" }, "No methods or runs yet.")); return; }
  put(body, el("div", { class: "table-wrap" }, el("table", { class: "results-table" },
    el("thead", {}, el("tr", {}, ["Method", "Status", "Errors (headline run)", "Runs passing", "Review", "Code"].map((h) => el("th", {}, h)))),
    el("tbody", {}, s.results.map((r) => el("tr", {}, el("td", {}, r.name),
      el("td", {}, el("span", { class: "status " + r.status.replace(" ", "-") }, r.status)),
      el("td", {}, Object.keys(r.errors || {}).length
        ? Object.entries(r.errors).map(([k, v]) => el("div", {}, `${k} ${num(v)}`)).concat(
          r.tolerance != null ? [el("div", { class: "muted" }, `tolerance ${num(r.tolerance)}`)] : [])
        : "—"),
      el("td", {}, r.total ? `${r.passed}/${r.total}` : "—"),
      el("td", {}, r.verdict ? `${r.verdict} by ${r.reviewer}` : "not reviewed"),
      el("td", {}, ext(r.code_url, "solver") || "—")))))));
}

async function flowTab(s, body, wait) {
  if (!s.flow) { put(body, el("p", { class: "muted" }, "The flow could not be drawn for this study.")); return; }
  const box = el("div", { class: "flow-box dark" });
  put(body, box);
  const m = await wait(import("/flow/flow.js"));
  mounted.push(m.mountFlow(box, s.flow, {}));
}

function notePart(part) {
  // Plain markdown, read as text: headings, paragraphs and "- " lists (never parsed as HTML).
  const out = [], lines = part.trim().split("\n");
  let para = [], items = [];
  const flush = () => {
    if (para.length) out.push(el("p", {}, para.join(" "))); para = [];
    if (items.length) out.push(el("ul", {}, items.map((t) => el("li", {}, t)))); items = [];
  };
  for (const line of lines) {
    const t = line.trim();
    if (/^#+\s/.test(t)) { flush(); out.push(el("h3", {}, t.replace(/^#+\s*/, ""))); }
    else if (/^[-*]\s/.test(t)) { if (para.length) { out.push(el("p", {}, para.join(" "))); para = []; } items.push(t.slice(2)); }
    else if (t) { if (items.length && /^\s/.test(line)) items[items.length - 1] += " " + t; else { if (items.length) flush(); para.push(t); } }
  }
  flush();
  return out;
}

function checkerTab(s, body) {
  const c = s.checker;
  const state = { approved: "approved", "approved-before-attacks": "approved before decoy testing existed",
    stale: "changed since approval", missing: "not approved", invalid: "approval file is invalid" }[c.approval.state] || c.approval.state;
  put(body, el("p", {}, el("span", { class: "tag" }, `Approval: ${state}`)));
  if (c.note) {
    put(body, el("div", { class: "note card" }, c.note.split(/\n\s*\n/).map(notePart)));
  } else put(body, el("p", { class: "muted" }, "No checker note yet."));
  put(body, el("p", { class: "section-title" }, "Decoy rounds"));
  if (!c.rounds.length) put(body, el("p", { class: "muted" }, "No decoy rounds recorded."));
  for (const r of c.rounds) {
    const blocked = r.attacks.filter((a) => a.blocked).length;
    put(body, el("div", { class: "card block" }, el("h3", {}, `Round ${r.round}: ${blocked}/${r.attacks.length} caught`),
      el("ul", {}, r.attacks.map((a) => el("li", {}, `${a.blocked ? "caught" : "passed the grader"}: ${a.name} (${a.idea})`)))));
  }
  if (c.decoys.length) put(body, el("p", { class: "muted" }, `Decoys on file: ${c.decoys.join(", ")}`));
}

function letterBox(text) {
  // The letter keeps its lines; it is long, so it opens on request. Copy takes the whole text.
  const box = cmd(text);
  box.classList.add("letter-copy");
  box.querySelector("code").textContent = "The letter to the authors, ready to paste into an email";
  return el("details", { class: "letter block" }, el("summary", {}, "Show the letter to the authors"),
    el("pre", {}, text), box);
}

function gapsTab(s, body) {
  const g = s.gaps_file;
  if (!g) {
    put(body, el("p", { class: "muted" }, "No gaps listed yet."), cmd(`uv run raft gaps --study ${s.id}`));
    return;
  }
  if (s.letter) put(body, letterBox(s.letter));
  put(body, el("div", { class: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ["Page", "Question", "Status", "Answer"].map((h) => el("th", {}, h)))),
    el("tbody", {}, g.gaps.map((x) => el("tr", {}, el("td", {}, x.page), el("td", {}, x.question,
      x.blocks ? el("p", { class: "muted" }, `Blocks: ${x.blocks}`) : null),
      el("td", {}, x.status.replace("_", " ")),
      el("td", {}, x.status === "answered" && x.answer ? [el("p", {}, x.answer.text), el("p", { class: "muted" }, `— ${x.answer.by}, ${x.answer.source}`)]
        : x.answer && x.answer.note ? `Our note: ${x.answer.note}` : "—")))))));
}

function benchTab(s, body) {
  const rows = [...s.bench.full, ...s.bench.partial];
  if (!rows.length) {
    put(body, el("p", { class: "muted" }, "No bench entries for this study on this machine."),
      s.draft ? null : cmd(`uv run raft bench --study ${s.id} --agent <claude-code|codex> --watch`));
    return;
  }
  put(body, benchTable(rows));
}

async function studyView(id, tab) {
  tab = TABS.includes(tab) ? tab : "overview";
  const wait = guard();
  const s = await wait(getJSON(`/app/study/${id}.json`));
  put(app, 
    el("p", { class: "eyebrow" }, [s.draft ? "draft" : "study", s.arxiv ? `arXiv ${s.arxiv}` : s.doi].filter(Boolean).join(" · ")),
    el("h2", {}, s.title),
    s.authors.length ? el("p", { class: "muted" }, s.authors.join(", ")) : null,
    el("p", { class: "links" }, s.arxiv ? ext(`https://arxiv.org/abs/${s.arxiv}`, "arXiv") : null,
      s.doi ? ext(`https://doi.org/${s.doi}`, "DOI") : null, ext(s.brief_url, "Paperraft brief"),
      s.arxiv ? el("a", { href: `#/paper/${s.arxiv}` }, "Paperraft view") : null),
    s.warning ? el("p", { class: "warning" }, s.warning) : null,
    el("nav", { class: "tabs", "aria-label": "Study" }, TABS.map((t) =>
      el("a", { href: `#/study/${id}/${t}`, "aria-current": t === tab ? "page" : null }, t[0].toUpperCase() + t.slice(1)))));
  const body = el("section", { class: "tab-body" });
  put(app, body);
  await ({ overview: overviewTab, results: resultsTab, flow: flowTab, checker: checkerTab, gaps: gapsTab, bench: benchTab })[tab](s, body, wait);
}

async function route() {
  gen += 1;
  clear();
  const [view = "", id, tab] = location.hash.replace(/^#\/?/, "").split("/");
  setNav(view === "study" ? "" : view);
  try {
    if (view === "running") await runningView();
    else if (view === "bench") await benchView();
    else if (view === "paper" && id) {
      if (!parseId(id)) throw new Error(`not an arXiv id: ${id}`);
      await paperView(parseId(id));
    } else if (view === "paper") paperForm();
    else if (view === "study" && id) await studyView(id, tab);
    else await homeView();
  } catch (e) {
    if (e === STALE) return;  // the user already moved on
    put(app, el("p", { class: "warning" }, `This page could not load: ${e.message}`));
  }
  app.focus({ preventScroll: true });
}

document.getElementById("search").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = document.getElementById("q");
  const id = parseId(q.value);
  if (id) { location.hash = `#/paper/${id}`; q.value = ""; }
  else { q.setCustomValidity("Paste an arXiv id like 2608.27428 or a Paperraft link"); q.reportValidity(); q.setCustomValidity(""); }
});
window.addEventListener("hashchange", route);
route();

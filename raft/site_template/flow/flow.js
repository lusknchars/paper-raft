// Paper Raft flow view: paper → extracted items → methods → runs, drawn as glowing cables.
// One plain ES module shared by the Paper Raft site, `raft watch` and Paperraft's demo.
// The page provides an import map for "three" and "three/addons/". Data text only ever reaches the DOM
// through textContent.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

export const PALETTE = ["#f2b24c", "#ef7a62", "#b98cf0", "#4fc9e0", "#6fd9a0", "#e98fc4", "#c9d36a", "#8fa8f0"];
const PAPER = "#efe1c6";
const BG = 0x030305;
const KINDS = ["equation", "method", "parameter", "boundary_condition", "result"];
const HUGE = 1e299; // raft writes inf/NaN errors as 1e300 so its JSON stays valid
const SEG = 40;

const FORMATS = {
  sigma: (v) => v.toFixed(1) + "σ",
  drop_percent: (v) => (v <= 1 ? "−" + Math.round(100 * (1 - v)) + "%" : "+" + Math.round(100 * (v - 1)) + "%"),
  sci: (v) => v.toExponential(1),
  kept_percent: (v) => (100 * (1 + v)).toFixed(1) + "%",
  percent: (v) => (100 * v).toFixed(1) + "%",
  number: (v) => String(Number(v.toPrecision(3))),
};
const AGG = { max: (a) => Math.max(...a), min: (a) => Math.min(...a), mean: (a) => a.reduce((x, y) => x + y, 0) / a.length };

export function formatMetric(format, v) {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  if (!Number.isFinite(v) || Math.abs(v) >= HUGE) return "∞";
  return (FORMATS[format] || FORMATS.number)(v);
}

export const pct = (n, d) => (d ? Math.round((100 * n) / d) + "%" : "—");

/** The chain's numbers for a selection: { method?: name, case?: key }. */
export function chain(data, sel = {}) {
  const ms = data.methods.filter((m) => !sel.method || m.name === sel.method);
  const names = new Set(ms.map((m) => m.name));
  const runs = data.runs.filter((r) => names.has(r.method) && (!sel.case || r.case === sel.case));
  const ids = new Set(data.items.map((i) => i.id));
  const used = new Set(ms.flatMap((m) => m.implements).filter((id) => ids.has(id)));
  const metrics = data.metrics.map((m) => {
    const vals = runs.filter((r) => r.status !== "stale").flatMap((r) => r.metrics.filter((x) => x.key === m.key).map((x) => x.value));
    return { ...m, text: vals.length ? formatMetric(m.format, AGG[m.agg](vals)) : "—" };
  });
  return {
    items: data.items.length, implemented: used.size,
    methodsTotal: ms.length, methodsVerified: ms.filter((m) => m.status === "verified").length,
    runsExpected: runs.length, runsPassing: runs.filter((r) => r.pass && r.status !== "stale").length,
    metrics,
  };
}

function h(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function seeded(seed) {
  let s = seed;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

function hasWebGL() {
  // Ask a throwaway canvas first: three.js logs console errors when it fails to get a context itself.
  try {
    const c = document.createElement("canvas");
    return Boolean(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function makeGL() {
  if (!hasWebGL()) throw new Error("WebGL is not available");
  const renderer = new THREE.WebGLRenderer({ antialias: true }); // throws without WebGL
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 1);
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(0, 1, 1, 0, -10, 10);
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.45, 0.2, 0.15);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());
  return { renderer, scene, camera, composer, bloom, lines: null, pos: null, col: null, U: null, C: null };
}

const STATUS_TEXT = { verified: "✓ verified", unverified: "✓ passes · not reviewed", failed: "✗ failed", stale: "stale", missing: "not run" };

export function mountFlow(root, data, opts = {}) {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const force2d = opts.force2d || new URLSearchParams(window.location.search).has("flow2d");
  const sel = { method: null, case: null };
  const mcolor = Object.fromEntries(data.methods.map((m) => [m.name, PALETTE[m.color % PALETTE.length]]));
  const caseLabel = Object.fromEntries(data.cases.map((c) => [c.key, c.label]));
  const draft = data.paper.draft || data.items.length === 0;

  root.classList.add("rf");
  root.replaceChildren();
  const bar = h("div", "rf-bar"), stage = h("div", "rf-stage"), labels = h("div", "rf-labels"), results = h("div", "rf-results");
  stage.append(labels);
  root.append(bar, stage, results);
  if (opts.note) root.append(h("p", "rf-note", opts.note));

  // chooser
  const chips = [];
  const group = (label, key, options) => {
    const g = h("div", "rf-chips");
    g.append(h("span", "rf-chips-label", label));
    for (const [value, text, c] of options) {
      const b = h("button", "rf-chip", text);
      b.type = "button";
      if (c) b.style.setProperty("--c", c);
      b.dataset.rfKey = key;
      b.dataset.rfValue = value ?? "";
      b.addEventListener("click", () => { sel[key] = value; refresh(); });
      chips.push(b);
      g.append(b);
    }
    bar.append(g);
  };
  if (data.methods.length > 1) group("method", "method", [[null, "all"], ...data.methods.map((m) => [m.name, m.name, mcolor[m.name]])]);
  if (data.cases.length > 1) group("case", "case", [[null, "all"], ...data.cases.map((c) => [c.key, c.label])]);

  // renderer
  let gl = null;
  if (!force2d) { try { gl = makeGL(); } catch { gl = null; } }
  const canvas = gl ? gl.renderer.domElement : document.createElement("canvas");
  const ctx = gl ? null : canvas.getContext("2d");
  root.dataset.rfRenderer = gl ? "webgl" : "2d";
  canvas.className = "rf-canvas";
  stage.prepend(canvas);
  if (!reduce) { canvas.style.opacity = "0"; requestAnimationFrame(() => requestAnimationFrame(() => { canvas.style.opacity = "1"; })); }

  let W = 0, H = 0, cables = [], rows = [], heads = {}, methodEls = {};
  let progress = {}, liveRun = null, raf = 0, timer = null, destroyed = false;

  function cable(a, b, o, rnd) {
    const dx = (b.x - a.x) * (0.45 + rnd() * 0.15);
    cables.push({ ...o, a, b, c1: { x: a.x + dx, y: a.y }, c2: { x: b.x - dx, y: b.y },
      rgb: new THREE.Color(o.color), w: 0.55 + rnd() * 0.45, ph: rnd(), f: 1, ft: 1, live: false });
  }

  function layout() {
    W = stage.clientWidth; H = stage.clientHeight;
    labels.replaceChildren(); cables = []; rows = []; heads = {}; methodEls = {};
    const rnd = seeded(2608), phone = W < 720, top = phone ? 58 : 70, bottom = H - 14;
    const X = phone ? [W * 0.08, W * 0.30, W * 0.52, W * 0.86] : [W * 0.17, W * 0.38, W * 0.58, W * 0.74];
    const put = (el, x, y) => { el.style.left = x + "px"; el.style.top = y + "px"; labels.append(el); return el; };

    const headDefs = [["paper", "paper", "paper", Math.max(60, X[0] - W * 0.08)],
      ["implemented", "extracted → implemented", "implemented", X[1]],
      ["methods", "methods verified", "verified", X[2]], ["runs", "runs", "runs", Math.min(W - 70, X[3] + 60)]];
    const quarter = [0.125, 0.375, 0.625, 0.875];
    headDefs.forEach(([key, title, short, x0], i) => {
      const x = phone ? W * quarter[i] : x0;
      const d = h("div", "rf-head"); d.dataset.rf = key;
      d.append(h("div", "t", phone ? ["paper", "items", "verified", "runs"][i] : title), h("div", "p", "—"), h("div", "s", ""));
      heads[key] = put(d, x, 4);
      if (phone) heads[key].style.maxWidth = (W / 4 - 6) + "px";
    });

    const py = top + (bottom - top) * 0.45;
    const paper = h("div", "rf-paper", data.paper.title);
    paper.append(h("small", null, draft ? (data.paper.draft ? "draft · nothing extracted yet" : "nothing extracted yet") : data.paper.authors_short));
    put(paper, 8, py - 36).style.maxWidth = (phone ? W * 0.45 : X[0] - 12) + "px";
    cable({ x: 8, y: py }, { x: X[0], y: py }, { color: PAPER, lead: true, layer: 0 }, rnd);
    (opts.others || []).forEach((o, i) => {
      const oy = Math.min(bottom - 20, py + 80 + i * 56);
      const d = h("div", "rf-paper rf-other", o.title); d.append(h("small", null, o.note));
      put(d, 8, oy - 36).style.maxWidth = (phone ? W * 0.45 : X[0] - 12) + "px";
      cable({ x: 8, y: oy }, { x: X[0], y: oy }, { color: PAPER, lead: true, dim: true, layer: 0 }, rnd);
    });
    if (draft) return;

    // items, grouped by kind (one node per kind on phones)
    const kinds = [...KINDS.filter((k) => data.items.some((i) => i.kind === k)),
      ...new Set(data.items.map((i) => i.kind).filter((k) => !KINDS.includes(k)))];
    const nodes = [];
    if (phone) {
      kinds.forEach((k, i) => nodes.push({ kind: k, ids: data.items.filter((it) => it.kind === k).map((it) => it.id),
        y: top + 20 + (i + 0.5) * (bottom - top - 30) / kinds.length }));
    } else {
      const gap = 12, step = (bottom - top - 20 - gap * (kinds.length - 1)) / Math.max(1, data.items.length);
      let y = top + 20;
      for (const k of kinds) {
        put(h("div", "rf-kind", k.replace("_", " ")), X[1] + 10, y - 7);
        for (const it of data.items.filter((i) => i.kind === k)) { nodes.push({ kind: k, ids: [it.id], y }); y += step; }
        y += gap;
      }
    }
    if (phone) nodes.forEach((n) => put(h("div", "rf-kind", n.kind.replace("_", " ")), X[1] + 6, n.y - 7).style.maxWidth = (X[2] - X[1] - 10) + "px");
    const strands = phone ? 3 : data.items.length > 200 ? 1 : 2;
    for (const n of nodes) for (let s = 0; s < strands; s++)
      cable({ x: X[0], y: py + (rnd() - 0.5) * 4 }, { x: X[1], y: n.y }, { color: PAPER, layer: 0, ids: n.ids }, rnd);

    const mY = {};
    data.methods.forEach((m, i) => {
      mY[m.name] = data.methods.length === 1 ? (top + bottom) / 2 : top + 40 + i * (bottom - top - 70) / (data.methods.length - 1);
      const d = h("div", "rf-method", m.name); d.style.color = mcolor[m.name];
      methodEls[m.name] = put(d, X[2] + 10, mY[m.name]);
      if (phone) Object.assign(d.style, { maxWidth: (X[3] - X[2] - 16) + "px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });
      const impl = new Set(m.implements);
      for (const n of nodes) if (n.ids.some((id) => impl.has(id)))
        for (let s = 0; s < (phone ? 2 : strands); s++)
          cable({ x: X[1] + 4, y: n.y }, { x: X[2], y: mY[m.name] + (rnd() - 0.5) * 6 }, { color: mcolor[m.name], layer: 1, method: m.name }, rnd);
    });

    data.runs.forEach((r, i) => {
      const y = data.runs.length === 1 ? (top + bottom) / 2 : top + 16 + i * (bottom - top - 24) / (data.runs.length - 1);
      const d = h("div", "rf-run");
      const name = h("span", null, `${r.method} · ${caseLabel[r.case] ?? r.case} `), state = h("b", null, "");
      const barEl = h("div", "bar"), fill = h("i"); fill.style.background = mcolor[r.method]; barEl.append(fill);
      const met = h("small", null, "");
      if (phone) d.append(state); else d.append(name, state, barEl, met);
      put(d, X[3] + 10, y).style.maxWidth = (W - X[3] - 16) + "px";
      rows.push({ run: r, el: d, state, fill, met, name: `${r.method} · ${caseLabel[r.case] ?? r.case}` });
      for (let s = 0; s < 4; s++)
        cable({ x: X[2] + 4, y: mY[r.method] + (rnd() - 0.5) * 4 }, { x: X[3], y: y + (rnd() - 0.5) * 3 },
          { color: mcolor[r.method], layer: 2, method: r.method, run: i }, rnd);
    });
  }

  function point(c, u) {
    const s = 1 - u;
    return { x: s * s * s * c.a.x + 3 * s * s * u * c.c1.x + 3 * s * u * u * c.c2.x + u * u * u * c.b.x,
             y: s * s * s * c.a.y + 3 * s * s * u * c.c1.y + 3 * s * u * u * c.c2.y + u * u * u * c.b.y };
  }

  function geometry() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (!gl) { canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); return; }
    gl.renderer.setSize(W, H, false);
    gl.composer.setSize(W, H);
    Object.assign(gl.camera, { left: 0, right: W, top: H, bottom: 0 });
    gl.camera.updateProjectionMatrix();
    if (gl.lines) { gl.scene.remove(gl.lines); gl.lines.geometry.dispose(); gl.lines.material.dispose(); }
    const n = cables.length * SEG * 2;
    gl.pos = new Float32Array(n * 3); gl.col = new Float32Array(n * 3); gl.U = new Float32Array(n); gl.C = new Uint32Array(n);
    cables.forEach((c, ci) => {
      for (let k = 0; k < SEG; k++) for (let e = 0; e < 2; e++) {
        const v = (ci * SEG + k) * 2 + e, u = (k + e) / SEG, p = point(c, u);
        gl.pos[v * 3] = p.x; gl.pos[v * 3 + 1] = H - p.y; gl.U[v] = u; gl.C[v] = ci;
      }
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(gl.pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(gl.col, 3));
    gl.lines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    gl.scene.add(gl.lines);
  }

  const baseAlpha = (c) => (c.lead ? (c.dim ? 0.18 : 0.45) : 0.03 * c.w) * c.f;

  function paint(t, pulsing) {
    if (gl) {
      const { col, U, C } = gl;
      for (let v = 0; v < U.length; v++) {
        const c = cables[C[v]];
        let a = baseAlpha(c);
        if (pulsing && c.live) { const d = U[v] - ((t * 0.5 + c.ph) % 1); a += 0.16 * Math.exp(-(d * d) / 0.002) * c.f; }
        col[v * 3] = c.rgb.r * a; col[v * 3 + 1] = c.rgb.g * a; col[v * 3 + 2] = c.rgb.b * a;
      }
      gl.lines.geometry.attributes.color.needsUpdate = true;
      gl.composer.render();
      return;
    }
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "#030305"; ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = "lighter";
    ctx.lineWidth = 1;
    for (const c of cables) {
      const a = Math.min(1, baseAlpha(c) * (c.lead ? 1.5 : 6) * (c.live ? 2.5 : 1));
      ctx.strokeStyle = `rgba(${Math.round(c.rgb.r * 255)},${Math.round(c.rgb.g * 255)},${Math.round(c.rgb.b * 255)},${a})`;
      ctx.beginPath(); ctx.moveTo(c.a.x, c.a.y); ctx.bezierCurveTo(c.c1.x, c.c1.y, c.c2.x, c.c2.y, c.b.x, c.b.y); ctx.stroke();
    }
  }

  function frame(ms) {
    raf = 0;
    let moving = false;
    for (const c of cables) {
      const d = c.ft - c.f;
      if (Math.abs(d) > 0.004 && !reduce) { c.f += d * 0.14; moving = true; } else c.f = c.ft;
    }
    const pulsing = !reduce && liveRun != null && !!gl;
    paint(ms / 1000, pulsing);
    if (moving || pulsing) kick();
  }
  function kick() { if (!destroyed && !raf) raf = requestAnimationFrame(frame); }

  function updateRows() {
    if (destroyed) return;
    liveRun = null;
    for (const [i, row] of rows.entries()) {
      const p = progress[row.run.run_id];
      let text = STATUS_TEXT[row.run.status] ?? row.run.status, width = row.run.status === "missing" ? 0 : 100;
      if (p && p.state === "running") {
        liveRun = i;
        if (typeof p.fraction === "number") { width = Math.round(100 * p.fraction); text = width + "%"; }
        else { width = 0; text = `running · ${Math.max(0, Math.round((Date.now() - Date.parse(p.started_at)) / 60000))} min`; }
      } else if (p && p.state === "finished") { width = 100; text = p.pass ? "✓ passes (local)" : "✗ fails (local)"; }
      if (W < 720) {
        const short = /^\d+%$/.test(text) ? text : /^running/.test(text) ? "…" : /✓/.test(text) ? "✓" : /✗/.test(text) ? "✗"
          : row.run.status === "stale" && !(p && p.state === "finished") ? "!" : row.run.status === "missing" && !p ? "–" : text;
        row.el.title = `${row.name}: ${text}`;
        text = short;
      } else row.el.title = "";
      row.state.textContent = text;
      row.fill.style.width = width + "%";
      const m = data.metrics.find((s) => row.run.metrics.some((x) => x.key === s.key));
      row.met.textContent = m ? `${m.label} ${formatMetric(m.format, row.run.metrics.find((x) => x.key === m.key).value)}` : "";
    }
    const run = liveRun == null ? null : rows[liveRun].run;
    for (const c of cables) c.live = !!run && ((c.layer === 2 && c.run === liveRun) || (c.layer === 1 && c.method === run.method));
    kick();
  }

  function refresh() {
    for (const b of chips) b.setAttribute("aria-pressed", String((b.dataset.rfValue || null) === sel[b.dataset.rfKey]));
    const k = chain(data, sel);
    const setHead = (key, p, s) => { heads[key].querySelector(".p").textContent = p; heads[key].querySelector(".s").textContent = s; };
    setHead("paper", data.paper.reference_checked ? "checked" : "not checked", "reference against the PDF");
    setHead("implemented", draft ? "—" : pct(k.implemented, k.items),
      draft ? "nothing extracted yet" : `${k.implemented} of ${k.items} items used by ${sel.method ?? "the methods"}`);
    setHead("methods", pct(k.methodsVerified, k.methodsTotal), `${k.methodsVerified} of ${k.methodsTotal} passed independent review`);
    setHead("runs", pct(k.runsPassing, k.runsExpected), `${k.runsPassing} of ${k.runsExpected} reproduce the claim`);

    results.replaceChildren();
    const cell = (key, v, l, d) => { const c = h("div", "rf-cell"); c.dataset.rf = key; c.append(h("div", "v", v), h("div", "l", l), h("div", "d", d)); results.append(c); };
    cell("claims", pct(k.runsPassing, k.runsExpected), "claims reproduced", `${k.runsPassing} of ${k.runsExpected} runs pass`);
    for (const m of k.metrics) cell(m.key, m.text, m.label, m.note);
    cell("coverage", draft ? "—" : pct(k.implemented, k.items), "paper coverage", "extracted items implemented");

    const impl = sel.method ? new Set((data.methods.find((m) => m.name === sel.method)?.implements ?? [])) : null;
    for (const c of cables) {
      let on = true;
      if (c.method && sel.method && c.method !== sel.method) on = false;
      if (c.run != null && sel.case && data.runs[c.run].case !== sel.case) on = false;
      if (c.ids && impl && !c.ids.some((id) => impl.has(id))) on = false;
      c.ft = on ? 1 : 0.12;
    }
    for (const [name, el] of Object.entries(methodEls)) el.style.opacity = !sel.method || name === sel.method ? "1" : "0.3";
    for (const row of rows) {
      const on = (!sel.method || row.run.method === sel.method) && (!sel.case || row.run.case === sel.case);
      row.el.style.opacity = on ? "1" : "0.25";
    }
    kick();
  }

  function rebuild() { layout(); geometry(); updateRows(); refresh(); }
  rebuild();

  let resizeTimer = 0;
  const ro = new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (stage.clientWidth !== W || stage.clientHeight !== H) rebuild(); }, 150);
  });
  ro.observe(stage);

  if (opts.live) {
    const poll = async () => {
      if (destroyed) return;
      try {
        const r = await fetch(opts.live.url, { cache: "no-store" });
        if (r.ok) {
          const j = await r.json();
          if (destroyed) return;
          if (j && typeof j === "object" && !Array.isArray(j)) { progress = j; updateRows(); }
        }
      } catch { /* the server went away; keep the last state */ }
    };
    poll();
    timer = setInterval(poll, opts.live.interval || 1000);
  }

  return {
    select(next = {}) {
      if ("method" in next) sel.method = data.methods.some((m) => m.name === next.method) ? next.method : null;
      if ("case" in next) sel.case = data.cases.some((c) => c.key === next.case) ? next.case : null;
      refresh();
    },
    destroy() {
      destroyed = true;
      ro.disconnect(); clearTimeout(resizeTimer);
      if (timer) clearInterval(timer);
      if (raf) cancelAnimationFrame(raf);
      if (gl) { if (gl.lines) { gl.lines.geometry.dispose(); gl.lines.material.dispose(); } gl.composer.dispose?.(); gl.renderer.dispose(); gl.renderer.forceContextLoss(); }
      root.replaceChildren(); root.classList.remove("rf");
    },
  };
}

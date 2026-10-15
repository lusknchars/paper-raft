// Paper Raft live view: what `raft prepare` and `raft bench` are doing right now, as a glowing step network.
// Served only by `raft watch` on 127.0.0.1. Data text only ever reaches the DOM through textContent.
import * as THREE from "three";
import { makeGL } from "./flow.js";

const COLOR = { done: "#6fd9a0", running: "#f2b24c", failed: "#ef7a62", pending: "#3a3631",
                blocked: "#6fd9a0", through: "#ef7a62", paper: "#efe1c6" };
const SEG = 28;

function h(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

export function percent(s) {
  const { done, total } = s.units;
  return total > 0 ? Math.min(100, Math.floor((100 * done) / total)) : 0;
}

export function graph(s) {
  const chain = [{ id: "paper", label: s.arxiv ? `arXiv:${s.arxiv}` : s.study, state: "paper", children: [] }];
  const byId = {};
  for (const st of s.steps) {
    if (st.id.startsWith("run-")) continue;
    const n = { id: st.id, label: st.label, state: st.state, children: [] };
    chain.push(n);
    byId[st.id] = n;
  }
  for (const r of (s.results && s.results.rounds) || []) {
    const n = byId[`attack-${r.round}`];
    if (n) n.children = r.attacks.map((a) => ({ label: a.name, state: a.blocked ? "blocked" : "through" }));
  }
  for (const st of s.steps) {
    if (!st.id.startsWith("run-")) continue;
    const n = byId[`implement-${st.method}`];
    if (n) n.children.push({ label: st.label, state: st.state });
  }
  if (s.state === "running" && !s.steps.some((st) => st.state === "running")) {
    chain.push({ id: "next", label: "…", state: "pending", children: [] });
  }
  return chain;
}

function fmt(sec) {
  sec = Math.max(0, Math.round(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : m ? `${m}m ${s}s` : `${s}s`;
}

function curve(a, b, bend) {
  const pts = [];
  for (let k = 0; k <= SEG; k++) {
    const u = k / SEG, s = 1 - u;
    const c1 = { x: a.x + (b.x - a.x) * bend, y: a.y }, c2 = { x: b.x - (b.x - a.x) * bend, y: b.y };
    pts.push({ x: s * s * s * a.x + 3 * s * s * u * c1.x + 3 * s * u * u * c2.x + u * u * u * b.x,
               y: s * s * s * a.y + 3 * s * s * u * c1.y + 3 * s * u * u * c2.y + u * u * u * b.y, u });
  }
  return pts;
}

function ring(c, r) {
  const pts = [];
  for (let k = 0; k <= SEG; k++) { const t = (k / SEG) * Math.PI * 2; pts.push({ x: c.x + r * Math.cos(t), y: c.y + r * Math.sin(t), u: k / SEG }); }
  return pts;
}

export function mountLive(root, opts = {}) {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const force2d = opts.force2d || new URLSearchParams(window.location.search).has("flow2d");
  root.classList.add("lv");
  if (opts.compact) root.classList.add("lv-compact");
  const side = h("nav", "lv-side"), main = h("section", "lv-main");
  const head = h("header", "lv-head"), stage = h("div", "lv-stage"), labels = h("div", "lv-labels");
  const bar = h("div", "lv-bar"), track = h("div", "lv-track"), fill = h("i"), pct = h("span", "lv-pct");
  const timer = h("div", "lv-timer"), who = h("div", "lv-who"), act = h("ul", "lv-activity");
  const stderr = h("pre", "lv-stderr"), results = h("div", "lv-results"), end = h("p", "lv-end");
  track.append(fill); bar.append(track, pct); stage.append(labels);
  main.append(head, stage, bar, timer, who, act, stderr, results, end);
  root.replaceChildren(...(opts.compact ? [main] : [side, main]));

  let gl = null;
  if (!force2d) { try { gl = makeGL(); } catch { gl = null; } }
  const canvas = gl ? gl.renderer.domElement : document.createElement("canvas");
  const ctx = gl ? null : canvas.getContext("2d");
  canvas.className = "lv-canvas";
  stage.prepend(canvas);
  root.dataset.lvRenderer = gl ? "webgl" : "2d";

  let sessions = [], picked = null, strokes = [], shape = "", sideShape = "", W = 0, H = 0, raf = 0, timerId = null, destroyed = false;

  function current() {
    const list = opts.study ? sessions.filter((s) => s.study === opts.study) : sessions;
    return list.find((s) => s.id === picked) || list.find((s) => s.state === "running") || list[0] || null;
  }

  function layout(s) {
    W = stage.clientWidth; H = stage.clientHeight;
    const nodes = graph(s), n = nodes.length, x0 = W * 0.07, dx = n > 1 ? (W * 0.86) / (n - 1) : 0, y = H * 0.36;
    strokes = []; labels.replaceChildren();
    nodes.forEach((node, i) => {
      node.p = { x: x0 + i * dx, y };
      const color = COLOR[node.state] || COLOR.pending;
      if (i) strokes.push({ pts: curve(nodes[i - 1].p, node.p, 0.4), color, live: s.state === "running" && node.state === "running", a: node.state === "pending" ? 0.25 : 0.8 });
      strokes.push({ pts: ring(node.p, node.id === "paper" ? 9 : 7), color, live: s.state === "running" && node.state === "running", ring: true, a: 1 });
      const lab = h("div", "lv-label", node.label);
      lab.dataset.s = node.state;
      lab.style.left = `${node.p.x}px`; lab.style.top = `${y + 14}px`;
      lab.style.maxWidth = `${Math.max(48, dx - 6)}px`;
      labels.append(lab);
      const k = node.children.length, gap = Math.min(16, (dx || W * 0.5) / Math.max(1, k));
      node.children.forEach((c, j) => {
        const p = { x: node.p.x + (j - (k - 1) / 2) * gap, y: H * 0.8 };
        const cc = COLOR[c.state] || COLOR.pending;
        strokes.push({ pts: curve(node.p, p, 0.1), color: cc, live: s.state === "running" && c.state === "running", a: 0.35 });
        strokes.push({ pts: ring(p, 3.5), color: cc, live: s.state === "running" && c.state === "running", ring: true, a: 1 });
      });
    });
    for (const st of strokes) st.rgb = new THREE.Color(st.color);
    geometry();
  }

  function geometry() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (!gl) { canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); return; }
    gl.renderer.setSize(W, H, false); gl.composer.setSize(W, H);
    Object.assign(gl.camera, { left: 0, right: W, top: H, bottom: 0 }); gl.camera.updateProjectionMatrix();
    if (gl.lines) { gl.scene.remove(gl.lines); gl.lines.geometry.dispose(); gl.lines.material.dispose(); }
    const n = strokes.reduce((t, st) => t + (st.pts.length - 1) * 2, 0);
    gl.pos = new Float32Array(n * 3); gl.col = new Float32Array(n * 3); gl.U = new Float32Array(n); gl.C = new Uint32Array(n);
    let v = 0;
    strokes.forEach((st, si) => {
      for (let k = 0; k < st.pts.length - 1; k++) for (const p of [st.pts[k], st.pts[k + 1]]) {
        gl.pos[v * 3] = p.x; gl.pos[v * 3 + 1] = H - p.y; gl.U[v] = p.u; gl.C[v] = si; v++;
      }
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(gl.pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(gl.col, 3));
    gl.lines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending }));
    gl.scene.add(gl.lines);
  }

  function paint(t) {
    const pulse = reduce ? 0 : 1;
    if (gl) {
      const { col, U, C } = gl;
      for (let v = 0; v < U.length; v++) {
        const st = strokes[C[v]];
        let a = st.a * 0.55;
        if (st.live && pulse) {
          if (st.ring) a *= 0.6 + 0.4 * Math.sin(t * 4);
          else { const d = U[v] - ((t * 0.6) % 1); a += 0.9 * Math.exp(-(d * d) / 0.003); }
        }
        col[v * 3] = st.rgb.r * a; col[v * 3 + 1] = st.rgb.g * a; col[v * 3 + 2] = st.rgb.b * a;
      }
      gl.lines.geometry.attributes.color.needsUpdate = true;
      gl.composer.render();
      return;
    }
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "#030305"; ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = "lighter";
    ctx.lineWidth = 1.2;
    for (const st of strokes) {
      const a = st.live && pulse && st.ring ? st.a * (0.6 + 0.4 * Math.sin(t * 4)) : st.a;
      ctx.strokeStyle = `rgba(${Math.round(st.rgb.r * 255)},${Math.round(st.rgb.g * 255)},${Math.round(st.rgb.b * 255)},${a})`;
      ctx.shadowColor = st.color; ctx.shadowBlur = 8;
      ctx.beginPath(); ctx.moveTo(st.pts[0].x, st.pts[0].y);
      for (const p of st.pts.slice(1)) ctx.lineTo(p.x, p.y);
      ctx.stroke();
    }
  }

  function frame(ms) {
    raf = 0;
    if (destroyed || !strokes.length) return;
    paint(ms / 1000);
    if (!reduce && strokes.some((st) => st.live)) raf = requestAnimationFrame(frame);
  }
  function kick() { if (!destroyed && !raf) raf = requestAnimationFrame(frame); }

  function cell(label, value) {
    const c = h("div", "lv-cell");
    c.append(h("div", "l", label), h("div", "v", value));
    return c;
  }

  function render() {
    const s = current();
    const list = opts.study ? sessions.filter((x) => x.study === opts.study) : sessions;
    // Rebuild the list only when it changed, so buttons keep focus and stay clickable across polls.
    const sideKey = JSON.stringify(list.map((x) => [x.id, x.kind, x.study, x.state, percent(x), x.started_at]));
    if (sideKey !== sideShape) {
      sideShape = sideKey;
      side.replaceChildren();
      for (const x of list) {
        const b = h("button", null, `${x.kind} · ${x.study}`);
        b.type = "button";
        b.append(h("small", null, `${x.state} · ${percent(x)}% · ${x.started_at.slice(0, 16).replace("T", " ")}`));
        b.dataset.id = x.id;
        b.addEventListener("click", () => { picked = x.id; render(); });
        side.append(b);
      }
    }
    for (const b of side.children) b.setAttribute("aria-pressed", String(!!s && b.dataset.id === s.id));
    root.hidden = !!opts.compact && !(s && s.state === "running");
    if (!s) {
      main.replaceChildren(h("p", "lv-empty", "No prepare or bench sessions on this machine yet. Start one with `uv run raft prepare --arxiv <id> --agent claude-code --watch`."));
      strokes = []; return;
    }
    if (main.firstChild?.className === "lv-empty") main.replaceChildren(head, stage, bar, timer, who, act, stderr, results, end);

    head.replaceChildren();
    const h1 = h("h1");
    if (s.arxiv) { const a = h("a", null, s.title || s.study); a.href = `https://arxiv.org/abs/${encodeURIComponent(s.arxiv)}`; a.target = "_blank"; a.rel = "noopener"; h1.append(a); }
    else h1.textContent = s.title || s.study;
    const chips = h("div", "lv-chips");
    const state = h("span", "lv-chip lv-state", s.state); state.dataset.s = s.state;
    chips.append(state, h("span", "lv-chip", s.kind === "bench" ? `bench · ${s.study}` : `prepare · ${s.study}`));
    for (const [role, a] of Object.entries(s.agents)) chips.append(h("span", "lv-chip", `${role}: ${a.tool}${a.model ? " · " + a.model : ""}`));
    head.append(h1, chips);

    const key = JSON.stringify([s.id, s.state, s.steps.map((st) => [st.id, st.state]), s.results.rounds, stage.clientWidth, stage.clientHeight]);
    if (key !== shape) { shape = key; layout(s); }
    kick();

    const p = percent(s);
    fill.style.width = `${p}%`;
    fill.style.background = s.state === "stopped" || s.state === "lost" ? "var(--lv-bad)" : p === 100 ? "var(--lv-ok)" : "var(--lv-run)";
    pct.textContent = `${p}% · ${+s.units.done.toFixed(2)} / ${s.units.total} steps`;

    const run = [...s.steps].reverse().find((st) => st.state === "running");
    const last = run || [...s.steps].reverse().find((st) => st.activity.length || st.stderr_tail);
    if (run && s.state === "running") {
      const el = (Date.now() - Date.parse(run.started_at)) / 1000;
      timer.textContent = `${run.label} · ${fmt(el)}` + (run.timeout_s ? ` of ${fmt(run.timeout_s)}` : "");
    } else timer.textContent = "";
    const role = last && last.agent && s.agents[last.agent];
    who.textContent = last && last.activity.length ? `${role ? role.tool : "agent"} says (its own words, not a result)` : "";
    act.replaceChildren(...(last ? last.activity.map((a) => h("li", null, a.text)) : []));
    stderr.hidden = !(last && last.stderr_tail);
    stderr.textContent = last && last.stderr_tail ? last.stderr_tail : "";

    results.replaceChildren();
    const r = s.results || {};
    if (s.kind === "prepare") {
      if (r.holes != null) results.append(cell("checker holes", String(r.holes)));
      for (const rd of r.rounds || []) results.append(cell(`round ${rd.round}`, `${rd.blocked}/${rd.tried} blocked`));
    } else if (r.expected != null) {
      results.append(cell("passed", `${r.passed} / ${r.expected}`), cell("failed", String(r.failed)),
                     cell("score", `${Math.round(100 * r.score)}%`));
    }

    end.textContent = s.state === "finished" ? `Next: ${s.next}` : s.state === "stopped" ? s.message || "stopped"
      : s.state === "lost" ? "The terminal running this session is gone; rerun the command to resume." : "";
  }

  async function poll() {
    if (destroyed) return;
    try {
      const r = await fetch(opts.url || "/live.json", { cache: "no-store" });
      if (r.ok) { const j = await r.json(); if (Array.isArray(j)) { sessions = j; render(); } }
    } catch { /* the server went away; keep the last state */ }
  }
  poll();
  timerId = setInterval(poll, opts.interval || 1000);
  const ro = new ResizeObserver(() => { shape = ""; if (current()) render(); });
  ro.observe(stage);

  return {
    destroy() {
      destroyed = true; clearInterval(timerId); ro.disconnect();
      if (raf) cancelAnimationFrame(raf);
      if (gl) { if (gl.lines) { gl.lines.geometry.dispose(); gl.lines.material.dispose(); } gl.renderer.dispose(); gl.renderer.forceContextLoss(); }
      root.replaceChildren(); root.classList.remove("lv", "lv-compact");
    },
  };
}

// Headless check of the flow view on the built site: no console errors, numbers match the committed study,
// the 2D fallback works, a phone-width page never scrolls sideways, and huge errors print as ∞.
// Usage: node scripts/check_flow.mjs site
import { chromium } from "playwright";
import { inflateSync } from "node:zlib";
import { spawn } from "node:child_process";

const site = process.argv[2] ?? "site";
const port = 8790 + Math.floor(Math.random() * 100);
const server = spawn("python3", ["-m", "http.server", String(port), "--bind", "127.0.0.1", "--directory", site], { stdio: "ignore" });
await new Promise((r) => setTimeout(r, 900));
const base = `http://127.0.0.1:${port}/`;
const fail = (m) => { console.error("✗ " + m); process.exitCode = 1; };
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
function pngMean(buf) { // mean of R,G,B in an 8-bit non-interlaced RGBA/RGB PNG
  let o = 8, w = 0, h = 0, ch = 4; const idat = [];
  while (o < buf.length) {
    const len = buf.readUInt32BE(o), type = buf.toString("ascii", o + 4, o + 8), d = buf.subarray(o + 8, o + 8 + len);
    if (type === "IHDR") { w = d.readUInt32BE(0); h = d.readUInt32BE(4); ch = d[9] === 6 ? 4 : 3; }
    if (type === "IDAT") idat.push(d);
    o += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(idat)), stride = w * ch, out = Buffer.alloc(stride * h);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (stride + 1)];
    for (let i = 0; i < stride; i++) {
      const x = raw[y * (stride + 1) + 1 + i], a = i >= ch ? out[y * stride + i - ch] : 0;
      const b = y ? out[(y - 1) * stride + i] : 0, c = i >= ch && y ? out[(y - 1) * stride + i - ch] : 0;
      const pa = Math.abs(b - c), pb = Math.abs(a - c), pc = Math.abs(a + b - 2 * c);
      const v = f === 0 ? x : f === 1 ? x + a : f === 2 ? x + b : f === 3 ? x + ((a + b) >> 1) : x + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c);
      out[y * stride + i] = v & 255;
    }
  }
  let sum = 0, n = 0;
  for (let p = 0; p < w * h; p++) for (let k = 0; k < 3; k++) { sum += out[p * ch + k]; n++; }
  return sum / n;
}
const text = async (page, sel) => (await page.textContent(sel)).trim();
try {
  const cases = [["webgl", "#flow/transduced-lm-2026", 1440], ["2d", "?flow2d=1#flow/transduced-lm-2026", 1440],
    ["phone", "#flow/transduced-lm-2026", 390], ["overview", "#", 1440]];
  for (const [name, url, width] of cases) {
    const page = await browser.newPage({ viewport: { width, height: 860 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await page.goto(base + url);
    await page.waitForSelector('[data-rf="implemented"] .p', { timeout: 20000 });
    await page.waitForTimeout(800);
    const renderer = await page.getAttribute(".rf", "data-rf-renderer");
    const wantRenderer = name === "2d" ? "2d" : "webgl";
    if (renderer !== wantRenderer) fail(`${name}: renderer is ${renderer}, expected ${wantRenderer}`);
    if (errors.length) fail(`${name}: console errors ${JSON.stringify(errors)}`);
    const implemented = await text(page, '[data-rf="implemented"] .p');
    if (implemented !== "65%") fail(`${name}: implemented shows ${implemented}, expected 65%`);
    if (width < 720) {
      const sw = await page.evaluate(() => document.scrollingElement.scrollWidth);
      if (sw > width) fail(`${name}: page scrolls sideways (${sw}px wide)`);
      const layoutProblems = await page.evaluate(() => {
        const out = [];
        const count = (s) => document.querySelectorAll(s).length;
        if (count(".rf-head") < 4) out.push(`only ${count(".rf-head")} .rf-head`);
        if (count(".rf-run") < 1) out.push("no .rf-run");
        if (count(".rf-method") < 1) out.push("no .rf-method");
        for (const m of document.querySelectorAll(".rf-method")) for (const row of document.querySelectorAll(".rf-run")) {
          const a = m.getBoundingClientRect(), b = row.getBoundingClientRect();
          if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) out.push(`method ${m.textContent} overlaps a run row`);
        }
        for (const p of document.querySelectorAll(".rf-head .p")) if (p.scrollWidth > p.clientWidth) out.push(`head value truncated: ${p.textContent}`);
        const heads = [...document.querySelectorAll(".rf-head")].map((e) => e.getBoundingClientRect());
        for (let i = 1; i < heads.length; i++) if (heads[i].left < heads[i - 1].right) out.push(`header ${i} overlaps header ${i - 1}`);
        for (const row of document.querySelectorAll(".rf-run")) {
          const r = row.getBoundingClientRect(), b = row.querySelector("b").getBoundingClientRect();
          if (b.width === 0 || b.right > r.right + 0.5 || b.left < r.left - 0.5) out.push(`run status hidden: ${row.textContent.slice(0, 40)}`);
        }
        return out;
      });
      if (layoutProblems.length) fail(`${name}: ${layoutProblems.join("; ")}`);
    } else if (name === "webgl") {
      const box = await page.evaluate(() => { const r = document.querySelector(".rf-stage").getBoundingClientRect(); return { x: r.left + scrollX + 8, y: r.bottom + scrollY - 28, width: 20, height: 20 }; });
      const mean = pngMean(await page.screenshot({ clip: box, fullPage: true }));
      if (!(mean < 12)) fail(`${name}: stage background mean ${mean.toFixed(1)}, expected < 12 (haze)`);
    }
    if (width >= 720 && name !== "overview") {
      if ((await text(page, '[data-rf="claims"] .v')) !== "100%") fail(`${name}: claims not 100%`);
      if ((await text(page, '[data-rf="bias"] .v')) !== "2.4σ") fail(`${name}: bias not 2.4σ`);
      await page.click('[data-rf-value="smc-rb"]');
      await page.waitForTimeout(300);
      const one = await text(page, '[data-rf="implemented"] .p');
      if (one !== "24%") fail(`${name}: smc-rb shows ${one}, expected 24%`);
      if ((await page.getAttribute('[data-rf-value="smc-rb"]', "aria-pressed")) !== "true") fail(`${name}: chip not pressed`);
      const inf = await page.evaluate(async () => (await import("./flow/flow.js")).formatMetric("sigma", 1e300));
      if (inf !== "∞") fail(`${name}: 1e300 formats as ${inf}`);
    }
    await page.close();
    if (!process.exitCode) console.log(`✓ ${name}`);
  }
  const page = await browser.newPage();
  await page.goto("file://" + process.cwd() + "/" + site + "/index.html#flow/transduced-lm-2026");
  await page.waitForTimeout(1500);
  const msg = await page.textContent("main");
  if (!/served over http/.test(msg)) fail("file://: no 'served over http' message");
  else console.log("✓ file:// fallback message");
} finally {
  await browser.close();
  server.kill();
}

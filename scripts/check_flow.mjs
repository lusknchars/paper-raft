// Headless check of the flow view on the built site: no console errors, numbers match the committed study,
// the 2D fallback works, a phone-width page never scrolls sideways, and huge errors print as ∞.
// Usage: node scripts/check_flow.mjs site
import { chromium } from "playwright";
import { spawn } from "node:child_process";

const site = process.argv[2] ?? "site";
const port = 8790 + Math.floor(Math.random() * 100);
const server = spawn("python3", ["-m", "http.server", String(port), "--bind", "127.0.0.1", "--directory", site], { stdio: "ignore" });
await new Promise((r) => setTimeout(r, 900));
const base = `http://127.0.0.1:${port}/`;
const fail = (m) => { console.error("✗ " + m); process.exitCode = 1; };
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
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
    if (errors.length) fail(`${name}: console errors ${JSON.stringify(errors)}`);
    const implemented = await text(page, '[data-rf="implemented"] .p');
    if (implemented !== "65%") fail(`${name}: implemented shows ${implemented}, expected 65%`);
    if (width < 720) {
      const sw = await page.evaluate(() => document.scrollingElement.scrollWidth);
      if (sw > width) fail(`${name}: page scrolls sideways (${sw}px wide)`);
      const layoutProblems = await page.evaluate(() => {
        const out = [];
        const heads = [...document.querySelectorAll(".rf-head")].map((e) => e.getBoundingClientRect());
        for (let i = 1; i < heads.length; i++) if (heads[i].left < heads[i - 1].right) out.push(`header ${i} overlaps header ${i - 1}`);
        for (const row of document.querySelectorAll(".rf-run")) {
          const r = row.getBoundingClientRect(), b = row.querySelector("b").getBoundingClientRect();
          if (b.width === 0 || b.right > r.right + 0.5 || b.left < r.left - 0.5) out.push(`run status hidden: ${row.textContent.slice(0, 40)}`);
        }
        return out;
      });
      if (layoutProblems.length) fail(`${name}: ${layoutProblems.join("; ")}`);
    } else if (name !== "overview") {
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

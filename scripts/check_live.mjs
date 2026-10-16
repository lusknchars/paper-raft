// Headless check of the live page (raft watch): it renders fixture sessions, the percentage and the agent's
// activity, switches sessions, falls back to 2D, never scrolls sideways on a phone, and logs no console errors.
// Usage: node scripts/check_live.mjs
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { cpSync, mkdtempSync, copyFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "raft-live-"));
cpSync("raft/site_template", dir, { recursive: true });
copyFileSync("tests/fixtures/live-sessions.json", join(dir, "live.json"));
copyFileSync(join(dir, "flow", "live.html"), join(dir, "index.html"));
const port = 8990 + Math.floor(Math.random() * 100);
const server = spawn("python3", ["-m", "http.server", String(port), "--bind", "127.0.0.1", "--directory", dir], { stdio: "ignore" });
await new Promise((r) => setTimeout(r, 900));
const base = `http://127.0.0.1:${port}/`;
const fail = (m) => { console.error("✗ " + m); process.exitCode = 1; };
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
try {
  for (const [name, query, width] of [["live", "", 1440], ["live-2d", "?flow2d", 1440], ["live-phone", "", 390]]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await page.goto(base + query);
    await page.waitForSelector(".lv-head h1", { timeout: 5000 });
    const title = (await page.textContent(".lv-head h1"))?.trim();
    if (!title?.startsWith("Multimodal Alignment")) fail(`${name}: title is ${title}`);
    const pct = (await page.textContent(".lv-pct"))?.trim();
    if (!pct?.startsWith("50%")) fail(`${name}: percentage is ${pct}`);
    if ((await page.$$(".lv-activity li")).length !== 2) fail(`${name}: expected 2 activity lines`);
    if (!(await page.textContent(".lv-stderr"))?.includes("code-mode host")) fail(`${name}: stderr tail missing`);
    if ((await page.$$(".lv-label")).length < 6) fail(`${name}: expected a node label per step`);
    const renderer = await page.getAttribute(".lv", "data-lv-renderer");
    if (renderer !== (query ? "2d" : "webgl")) fail(`${name}: renderer is ${renderer}`);
    const items = await page.$$(".lv-side button");
    if (items.length !== 3) fail(`${name}: expected 3 sessions in the list, got ${items.length}`);
    await items[1].click();
    await page.waitForTimeout(200);
    if (!(await page.textContent(".lv-end"))?.includes("extraction still fails")) fail(`${name}: stopped message missing`);
    await items[2].click();
    await page.waitForTimeout(200);
    if (!(await page.textContent(".lv-results"))?.includes("50%")) fail(`${name}: bench score missing`);
    const sw = await page.evaluate(() => document.scrollingElement.scrollWidth);
    if (sw > width) fail(`${name}: page scrolls sideways (${sw}px wide)`);
    if (errors.length) fail(`${name}: console errors ${JSON.stringify(errors)}`);
    await page.close();
    if (!process.exitCode) console.log(`✓ ${name}`);
  }
  {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(base);
    await page.waitForSelector(".lv-head h1", { timeout: 5000 });
    for (const [study, visible] of [["wu-2026-multimodal", true], ["transduced-lm-2026", false]]) {
      const shown = await page.evaluate(async (study) => {
        const { mountLive } = await import("/flow/live.js");
        const el = document.createElement("div");
        document.body.append(el);
        const m = mountLive(el, { url: "/live.json", compact: true, study });
        await new Promise((r) => setTimeout(r, 600));
        const ok = el.getBoundingClientRect().height > 0;
        m.destroy(); el.remove();
        return ok;
      }, study);
      if (shown !== visible) fail(`compact ${study}: visible=${shown}, expected ${visible}`);
    }
    await page.close();
    if (!process.exitCode) console.log("✓ compact");
  }
  {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(base);
    await page.waitForSelector(".lv-head h1", { timeout: 5000 });
    await page.route("**/live.json", (r) => r.abort());
    // Wait for the page's two missed polls instead of sleeping: CI runners are slower than laptops.
    const gone = page.locator(".lv-gone");
    await gone.waitFor({ state: "visible", timeout: 10000 }).catch(() => {});
    if (!(await gone.isVisible())) fail("disconnected: the line is not visible");
    else if (!(await gone.textContent())?.includes("raft is no longer serving this page")) fail("disconnected: wrong text");
    if ((await page.textContent(".lv-timer"))?.trim()) fail("disconnected: timer text is not empty");
    await page.unroute("**/live.json");
    await gone.waitFor({ state: "hidden", timeout: 10000 }).catch(() => {});
    if (await gone.isVisible()) fail("disconnected: the line stays after the server is back");
    await page.close();
    if (!process.exitCode) console.log("✓ disconnected");
  }
} finally {
  await browser.close();
  server.kill();
}

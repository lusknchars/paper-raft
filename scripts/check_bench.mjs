// Headless check of the Bench page on the built site: it renders, the overview links to it, no console errors.
// Usage: node scripts/check_bench.mjs site
import { chromium } from "playwright";
import { spawn } from "node:child_process";

const site = process.argv[2] ?? "site";
const port = 8890 + Math.floor(Math.random() * 100);
const server = spawn("python3", ["-m", "http.server", String(port), "--bind", "127.0.0.1", "--directory", site], { stdio: "ignore" });
await new Promise((r) => setTimeout(r, 900));
const base = `http://127.0.0.1:${port}/`;
const fail = (m) => { console.error("✗ " + m); process.exitCode = 1; };
const browser = await chromium.launch();
try {
  for (const [name, url, width] of [["bench", "#bench", 1440], ["bench-phone", "#bench", 390], ["overview", "#", 1440]]) {
    const page = await browser.newPage({ viewport: { width, height: 860 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await page.goto(base + url);
    await page.waitForTimeout(800);
    if (name === "overview") {
      if (!(await page.$('a.card[href="#bench"]'))) fail("overview: no Bench card");
    } else {
      const h = (await page.textContent("main h2"))?.trim();
      if (h !== "Bench") fail(`${name}: heading is ${h}`);
      const sw = await page.evaluate(() => document.scrollingElement.scrollWidth);
      if (sw > width) fail(`${name}: page scrolls sideways (${sw}px wide)`);
    }
    if (errors.length) fail(`${name}: console errors ${JSON.stringify(errors)}`);
    await page.close();
    if (!process.exitCode) console.log(`✓ ${name}`);
  }
} finally {
  await browser.close();
  server.kill();
}

// Headless check of a study's Gaps page on the built site: one row per gap, the counts line matches gaps.json,
// published answers show with their credit, private ones show only their status and note, phone width never
// scrolls sideways, no console errors.
// Usage: node scripts/check_gaps.mjs site
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";

const site = process.argv[2] ?? "site";
const data = JSON.parse(readFileSync(`${site}/data.json`, "utf8"));
const study = data.studies.find((s) => s.gaps && s.gaps.gaps.length >= 2);
if (!study) { console.error("✗ no study with at least two gaps in data.json"); process.exit(1); }
const port = 8990 + Math.floor(Math.random() * 100);
const server = spawn("python3", ["-m", "http.server", String(port), "--bind", "127.0.0.1", "--directory", site], { stdio: "ignore" });
await new Promise((r) => setTimeout(r, 900));
const base = `http://127.0.0.1:${port}/`;
const fail = (m) => { console.error("✗ " + m); process.exitCode = 1; };
const live = study.gaps.gaps.filter((g) => g.status !== "resolved").length;
// A copy of the data with one published and one private answer, to check what each one shows.
const fake = structuredClone(data);
const fg = fake.studies.find((s) => s.id === study.id).gaps.gaps;
fg[0] = { ...fg[0], status: "answered", answer: { text: "We used corpus X.", by: "A. Author", source: "email, 2026-10-20", recorded_on: "2026-10-21" } };
fg[1] = { ...fg[1], status: "answered_private", answer: { by: "B. Author", source: "email", recorded_on: "2026-10-21", note: "our assumption matched" } };
const browser = await chromium.launch();
try {
  for (const [name, width, swap] of [["gaps", 1440, false], ["gaps-phone", 390, false], ["gaps-answers", 1440, true]]) {
    const page = await browser.newPage({ viewport: { width, height: 860 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    if (swap) await page.route("**/data.js", (r) => r.fulfill({ contentType: "application/javascript",
      body: "window.RAFT_DATA = " + JSON.stringify(fake) + ";\n" }));
    await page.goto(`${base}#study/${study.id}/gaps`);
    await page.waitForSelector("table.gaps", { timeout: 5000 }).catch(() => {});
    const rows = await page.$$eval("table.gaps tbody tr", (t) => t.length);
    if (rows !== study.gaps.gaps.length) fail(`${name}: ${rows} rows, expected ${study.gaps.gaps.length}`);
    const line = ((await page.textContent(".gaps-line").catch(() => "")) || "").trim();
    if (!line.startsWith(`${live} detail`)) fail(`${name}: counts line is "${line}"`);
    if (swap) {
      const a = await page.textContent(`tr[data-gap="${fg[0].id}"]`);
      if (!a.includes("We used corpus X.") || !a.includes("A. Author, email, 2026-10-20")) fail("gaps-answers: published answer or credit missing");
      const b = await page.textContent(`tr[data-gap="${fg[1].id}"]`);
      if (!b.includes("answered privately") || !b.includes("our assumption matched")) fail("gaps-answers: private answer not shown as private with its note");
    }
    const sw = await page.evaluate(() => document.scrollingElement.scrollWidth);
    if (sw > width) fail(`${name}: page scrolls sideways (${sw}px wide)`);
    if (errors.length) fail(`${name}: console errors ${JSON.stringify(errors)}`);
    await page.close();
    if (!process.exitCode) console.log(`✓ ${name}`);
  }
} finally {
  await browser.close();
  server.kill();
}

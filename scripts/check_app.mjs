// Headless check of `raft app` on this repo: home, every study tab, the paper page (Paperraft answers come from a
// fixture), search, phone width, no console errors. Starts its own server and a fake running session, then cleans up.
// Usage: node scripts/check_app.mjs
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

const port = 9190 + Math.floor(Math.random() * 100);
const base = `http://127.0.0.1:${port}/app.html`;
const fail = (m) => { console.error("✗ " + m); process.exitCode = 1; };
const session = JSON.parse(readFileSync("tests/fixtures/live-sessions.json", "utf8")).find((s) => s.state === "running");
const liveFile = `.raft/live/app-check-${process.pid}.json`;
let server = null, browser = null;
function cleanup() {  // runs on success, failure and Ctrl-C: never leave a server or a fake session behind
  try { server?.kill(); } catch { /* already gone */ }
  rmSync(liveFile, { force: true });
}
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { cleanup(); process.exit(130); });
mkdirSync(".raft/live", { recursive: true });
const { id: _id, ...fields } = session;  // the server adds `id` from the file name; the file itself has none
writeFileSync(liveFile, JSON.stringify({ ...fields, pid: process.pid }));
server = spawn("uv", ["run", "raft", "app", "--no-open", "--port", String(port)], { stdio: "ignore" });
const fixture = readFileSync("tests/fixtures/paperraft-2608.27428.json", "utf8");
let data = null;
for (let i = 0; i < 60 && !data; i++) {
  try { const r = await fetch(`http://127.0.0.1:${port}/app.json`); if (r.ok) data = await r.json(); } catch { /* not up yet */ }
  if (!data) await new Promise((r) => setTimeout(r, 500));
}
browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
async function open(hash, width = 1440) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await page.route("**/paperraft/2608.27428.json", (r) => r.fulfill({ contentType: "application/json", body: fixture }));
  await page.route("**/paperraft/2601.00001.json", (r) => r.fulfill({ contentType: "application/json",
    body: JSON.stringify({ found: false, brief: null, offline: false, stale: false }) }));
  await page.goto(base + hash);
  await page.waitForTimeout(1200);
  return { page, errors };
}
async function done(name, { page, errors }, width = 1440) {
  const text = await page.evaluate(() => document.getElementById("app").innerText);
  if (/(^|\s)(null|undefined)(\s|$)/.test(text)) fail(`${name}: the page shows "null" or "undefined"`);
  const sw = await page.evaluate(() => document.scrollingElement.scrollWidth);
  if (sw > width) fail(`${name}: page scrolls sideways (${sw}px wide)`);
  if (errors.length) fail(`${name}: console errors ${JSON.stringify(errors)}`);
  await page.close();
  if (!process.exitCode) console.log(`✓ ${name}`);
}
try {
  if (!data) throw new Error("the app server did not start");
  for (const width of [1440, 390]) {
    const p = await open("#/", width);
    const cards = await p.page.$$eval(".study-card", (n) => n.length);
    if (cards !== data.studies.length) fail(`home@${width}: ${cards} study cards, expected ${data.studies.length}`);
    if ((await p.page.$$eval(".stats .stat", (n) => n.length)) !== 4) fail(`home@${width}: stats row`);
    if (!(await p.page.$(".running .lv"))) fail(`home@${width}: no running panel`);
    const lead = data.studies.find((s) => !s.draft && s.stages.some((g) => g.ok === false))
      || data.studies.find((s) => s.stages.some((g) => g.ok === false && g.name !== "paper"));
    if (lead && !(await p.page.textContent(".deck")).includes(lead.title)) fail(`home@${width}: the headline should lead with ${lead.id}`);
    const copy = await p.page.$eval("[data-copy]", (n) => n.dataset.copy);
    if (!copy.startsWith("uv run raft") && !copy.startsWith("Put the paper")) fail(`home@${width}: copy holds ${copy}`);
    await done(`home@${width}`, p, width);
  }
  const study = data.studies.find((s) => !s.draft) || data.studies[0];
  for (const tab of ["overview", "results", "flow", "checker", "gaps", "bench"]) {
    const p = await open(`#/study/${study.id}/${tab}`);
    if (!(await p.page.$(".tab-body"))) fail(`study ${tab}: no tab body`);
    if (tab === "gaps" && (await p.page.$(".letter"))) {
      const kept = await p.page.$eval(".letter pre", (n) => n.textContent.includes("\n\n"));
      const copy = await p.page.$eval(".letter [data-copy]", (n) => n.dataset.copy);
      if (!kept || !copy.startsWith("Dear ")) fail("study gaps: the letter lost its lines or its copy text");
    }
    await done(`study ${tab}`, p);
  }
  const draft = data.studies.find((s) => s.draft);
  if (draft) for (const tab of ["overview", "results", "checker", "gaps", "bench"]) await done(`draft ${tab}`, await open(`#/study/${draft.id}/${tab}`));
  for (const width of [1440, 390]) {
    const p = await open("#/paper/2608.27428", width);
    const title = (await p.page.textContent(".pr-brief h2"))?.trim();
    if (title !== "Stochastic Estimation of Transduced Language Models") fail(`paper@${width}: title ${title}`);
    const mine = data.studies.find((s) => s.arxiv === "2608.27428");
    const lab = await p.page.textContent(".lab-block");
    if (mine ? !lab.includes(mine.title) : !lab.includes("raft prepare --arxiv 2608.27428")) fail(`paper@${width}: lab block`);
    await done(`paper@${width}`, p, width);
  }
  const u = await open("#/paper/2601.00001");
  if (!(await u.page.textContent(".pr-brief")).includes("has no brief")) fail("unknown paper: message");
  if (!(await u.page.$eval(".lab-block [data-copy]", (n) => n.dataset.copy)).includes("raft prepare --arxiv 2601.00001")) fail("unknown paper: command");
  await done("unknown paper", u);
  // A slow page must never draw over the next one: open a study whose data is delayed, then go to Bench at once.
  const race = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const raceErrors = [];
  race.on("pageerror", (e) => raceErrors.push(String(e)));
  await race.route("**/app/study/*.json", async (r) => { await new Promise((ok) => setTimeout(ok, 900)); await r.continue(); });
  await race.goto(`${base}#/study/${study.id}/overview`);
  await race.waitForTimeout(100);
  await race.evaluate(() => { location.hash = "#/bench"; });
  await race.waitForTimeout(1800);
  if (await race.$(".tabs")) fail("race: the slow study page drew over the Bench page");
  if ((await race.textContent("main h2"))?.trim() !== "Bench") fail("race: Bench is not the page shown");
  await done("race", { page: race, errors: raceErrors });
  // The flow tab on a machine without WebGL: the 2D fallback, and no console errors.
  const noGL = await chromium.launch({ args: ["--disable-3d-apis", "--disable-gpu"] });
  try {
    const page = await noGL.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await page.goto(`${base}#/study/${study.id}/flow`);
    await page.waitForTimeout(1500);
    if (errors.length) fail(`flow without WebGL: console errors ${JSON.stringify(errors)}`);
    else console.log("✓ flow without WebGL");
  } finally { await noGL.close(); }
  const s = await open("#/");
  await s.page.fill("#q", "https://paperaft.vercel.app/papers/2608.27428/");
  await s.page.press("#q", "Enter");
  await s.page.waitForTimeout(300);
  if ((await s.page.evaluate(() => location.hash)) !== "#/paper/2608.27428") fail("search: did not open the paper");
  await done("search", s);
} catch (e) {
  fail(String(e));
} finally {
  await browser?.close();
  cleanup();
}

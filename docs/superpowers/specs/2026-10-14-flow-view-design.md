# Flow view: design

**Date:** 2026-10-14 · **Status:** draft, awaiting owner review · **Repos:** paper-raft (this repo), ai-radar (Paperraft)

## Purpose

Paper Raft's evidence (extracted items, methods, runs, reviews) sits in JSON files that only a careful reader opens.
The flow view draws one study as a chain of glowing cables: **paper → items extracted from it → methods built from
those items → runs → results**, with a percentage at each link and the results stated in terms an ML engineer
reads at a glance. It is the thing that makes a visitor want to use Paper Raft.

Three places show it, all fed by the same data and the same renderer:

1. **Demo on Paperraft** (first): on the paper's page (`/papers/2608.27428/`), inside the existing
   "Reproduced in Paper Raft" section. Static: it shows the committed runs.
2. **Flow tab on the Paper Raft site** (GitHub Pages): every study, with the chooser.
3. **`raft watch`** (local): the same view on localhost while someone runs a study, with live run progress.

## What the owner asked for (from the brainstorm)

- The whole chain at once, like the reference image: cables fanning out, crossing, landing.
- Dim, not hazy. No squares or particles: cables, layers and connections only.
- Colours per paper and per method, not only blue.
- No pointer play and no layer-by-layer reveal. The view fades in once; selection is by explicit buttons.
- Percentages for each link of the chain that follow what the user chooses (study, method, case).
- Results that mean something to AI/ML engineers, in the same visual language.
- A local view people can keep open while they work.

Approved direction: sketch v4 (`.superpowers/brainstorm/…/flow-webgl-v4.html`).

## Honesty rules

- Every number comes from committed files. No simulated values anywhere outside `raft watch`, and there only
  live progress read from the machine's own run.
- A layer whose data is missing says so ("draft · nothing extracted yet"); it never shows 0% as if measured.
- The Paperraft demo keeps Paperraft's editorial line: it is the lab's result, shown in the lab's section, with the
  lab's commit and date. It does not change the brief's editorial status and does not go in a deep report.

## Data: `flow.json`

Built by paper-raft from committed files only, one file per study. Schema: `raft/contracts/flow.schema.json`.

```json
{
  "study": "transduced-lm-2026",
  "source": { "repo": "https://github.com/lusknchars/paper-raft", "commit": "<sha>", "built_at": "<iso>" },
  "paper": { "title": "...", "authors_short": "Snæbjarnarson et al. 2026", "reference_checked": true, "draft": false },
  "items": [ { "id": "ht-estimator", "kind": "equation" } ],
  "methods": [ { "name": "smc-rb", "implements": ["..."], "status": "verified", "color": 2 } ],
  "cases": ["worst", "bigram"],
  "runs": [ { "method": "smc-rb", "params": { "case": "bigram" }, "status": "verified", "pass": true,
              "finished_at": "<iso>", "metrics": [ { "key": "bias", "value": 2.137, "text": "bias 2.1σ of 4σ allowed" } ] } ],
  "metrics": [ { "key": "bias", "label": "worst bias test", "note": "limit 4σ over 128 seeds", "agg": "max", "format": "sigma" } ]
}
```

`methods[].status` and `runs[].status` use the existing `raft.status.derive_status` rule (verified = passes, clean,
reviewed at the method's commit). `color` is an index into a fixed palette, assigned by method order.

### Which results to show: `metrics` in `paper.yaml`

`measure.py` error keys differ per study, so each study names the ones worth showing, in `paper.yaml` (outside
`problem/`, so adding it does not make runs stale):

```yaml
metrics:
  - { key: bias, from: max_z, claims: [unbiased], label: "worst bias test", note: "limit 4σ over 128 seeds", agg: max, format: sigma }
  - { key: error_drop, from: worst_rmse_ratio, claims: [unbiased], label: "error as budget grows", note: "relative RMSE, M 16 → 256, weakest method", agg: max, format: drop_percent }
  - { key: exact_error, from: max_abs_log_error, claims: [exact, top_m_share], label: "exact-case error", note: "log Ẑ vs closed form, limit 1e-9", agg: max, format: sci }
  - { key: lower_bound, from: max_overshoot, claims: [lower_bound], label: "never overestimates", note: "share of the true value kept", agg: max, format: kept_percent }
```

Formats are a closed set in `raft/flow.py` (`sigma`, `drop_percent`, `sci`, `kept_percent`, `percent`, `number`),
so a study can label but not inject markup. A study without `metrics` shows only "claims reproduced" and coverage.
For a future training study the same slots carry loss, accuracy, or share of the paper's score reached.

### Chain percentages (recomputed for the current selection)

| Link | Value | Definition |
|---|---|---|
| Paper | `checked` / `not checked` | `reference.json` `verified_against_pdf`. A flag, not a percentage. |
| Extracted → implemented | % | items named in at least one selected method's `implements`, over all items |
| Methods verified | % | selected methods whose status is `verified` |
| Runs | % | selected runs that pass and are not stale, over the runs the study's `RUN_MATRIX` expects |
| Results | per `metrics` | aggregated over the selected runs with `agg` |

Plus two fixed results: **claims reproduced** (passing runs / expected runs) and **paper coverage** (same as the
extracted → implemented link).

## Renderer: `raft/site_template/flow/flow.js`

One plain-JavaScript ES module, no build step, used unchanged in all three places. Dependencies: three.js 0.186.1
(MIT) and its post-processing addons for a light bloom. **No GSAP**: the view has no pointer animation left, and
the few transitions (fade in, dim on selection) are a small easing helper. This also keeps a free-but-not-open
licence out of both repos.

- API: `mountFlow(element, flowData, { live: null | progressSource })`.
- Look (from v4): black background, bloom 0.45 / radius 0.2 / threshold 0.15; cables 1 px additive lines; paper colour
  for paper → item cables, method colour from item → method onward; a slow pulse runs only along cables feeding a run
  that is in progress (`raft watch`) — the static views have no motion after the fade-in.
- Layers left to right: paper · extracted (grouped by kind) · methods · runs; layer headings carry the percentages;
  the results row sits at the bottom right.
- Chooser: study (where more than one), method, case. Selection dims the rest to 12% and recomputes every number.
- Fallbacks: no WebGL → the same layout drawn with 2D canvas, no bloom. `prefers-reduced-motion` → no fade, no
  pulse. Below 720 px wide the items layer collapses to one cable per kind, and labels shorten.
- Limits: one strand per cable above 200 items; palette of 8 method colours, then repeat.

## Place 1: Paperraft demo (ai-radar)

- `content/reproductions/2608.27428.json` gains an optional `flow` field: the path of a committed copy of
  `flow.json`, e.g. `content/reproductions/2608.27428.flow.json`, plus the source commit it was exported from.
  `LabReproduction` validates the file against a copy of the schema and checks its study id.
- `site.py` renders, inside "Reproduced in Paper Raft", a fixed-height container (about 520 px desktop, 420 px phone)
  with the chooser, the view, and the link "Open the full view in Paper Raft →" (the study page on the Pages site).
  The text summary already in that section stays above it, so the section reads fine without JavaScript.
- Scripts are served by Paperraft itself, like D3 today: `assets/flow-<version>.js`, `assets/three-0.186.1/…`
  (the module, its core file and the four post-processing files), with three.js's MIT licence file next to them.
  An import map on that page only. No CDN.
- Updating the demo is a deliberate act: `raft flow export --study transduced-lm-2026 --out <dir>` in paper-raft,
  then a commit in ai-radar. The page shows "Lab data from commit <sha>, <date>".
- Nothing deploys without the owner's go.

## Place 2: Flow tab on the Paper Raft site

`raft compare` also writes `site/flow/<study>.json` and copies `flow.js`. The site gets a "Flow" view in its router,
linked from each study and from the overview; the overview shows the flow of the headline study. Drafts appear as a
dim paper with "draft · nothing extracted yet" and no cables. The site already loads Chart.js from a CDN; three.js
loads from jsDelivr, pinned to 0.186.1.

## Place 3: `raft watch` (local)

- `raft watch [--study s] [--port 8765]` serves the flow view on `127.0.0.1` only, with the study's `flow.json`
  rebuilt from disk, and opens the browser.
- Live progress: while `raft run` works it writes `runs/.progress/<run_id>.json` (gitignored): queued, started,
  fraction, finished, pass. The view polls once a second.
- Progress inside a run: the runner passes `progress(fraction)` to `solve` **only if** `solve`'s signature asks for
  it (same pattern as `measure(…, method)`). `problem/` is untouched, so no run goes stale. Methods that do not
  report show "running · 12 min" instead of a percentage.
- The view marks itself "local · not committed": numbers from uncommitted or dirty runs are labelled as such.

## Testing

- paper-raft (pytest): `flow.json` for transduced-lm-2026 validates against the schema; coverage is 46/71;
  selection maths (per method, per case) on a small fixture study; each metric format, including NaN/inf from
  `_finite`; a draft study gives no items and `draft: true`; a stale run counts as not passing; the runner writes
  progress files and passes `progress` only when asked; `raft watch` serves on 127.0.0.1 and returns the JSON.
- paper-raft (headless check, local and CI): Playwright opens the built site's Flow view and the 2D fallback,
  checks there are no console errors and that the headline numbers in the DOM match `flow.json`.
- ai-radar (pytest): the `flow` field validates (wrong study id fails, missing file fails); the page renders the
  container, the import map and the link; `build_vercel` copies the assets; the full suite stays green.

## Out of scope

The checker work (grader library, checker roles, cheat tests, approval gate) has its own spec. Also out: screening
papers in ai-radar, containers, and running on other machines.

## Open questions for review

1. Demo height on the paper page: 520 px is a guess; it can be taller if the section should lead with it.
2. Whether Paperraft's home page should also show a small teaser of the flow, later.

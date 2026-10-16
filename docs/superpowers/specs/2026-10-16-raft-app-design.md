# The Paper Raft app: a local dashboard in Paperraft's design

**Date:** 2026-10-16 · **Status:** draft, awaiting owner review · **Repo:** paper-raft

## Purpose

Someone clones Paper Raft, runs a paper or benches their agent, and then wants to see what happened. Today that means
reading terminal output, opening JSON files, or building the public site with `raft compare`. The public site is a
developer dashboard: monospace, dark, dense. The live view (`raft watch`) shows only running sessions.

`raft app` is the product front end people get when they download the repo:

- **One place for their own lab:** every study they have (drafts included), where each stands, the next command,
  results, the checker, gaps, bench entries, and what's running now.
- **Paperraft's look and voice,** so the lab reads as part of Paperraft and not a separate tool:
  - Be Vietnam Pro, the serif wordmark, rose accents and mono labels;
  - the pink dither field, the big headline type, and the search bar.
- **A door to Paperraft's papers.** Paste an arXiv id or a Paperraft link, and the app shows Paperraft's brief for
  that paper next to what the lab knows about it, with the command to bring it into the lab.
- **What agents open for the user.** When an agent in the repo is asked to look up a paper or show results, it runs
  `raft paper <id>` for itself and `raft app` for the user, so people see a well-made page, not a JSON dump.

## Command

```
uv run raft app                         # opens http://127.0.0.1:8765/app.html
uv run raft app --study wu-2026-multimodal
uv run raft app --paper 2608.27428      # or a paperaft.vercel.app/papers/… link
uv run raft paper 2608.27428            # plain text, for agents and terminals
```

`raft app` uses the same local server as `raft watch`: 127.0.0.1 only, the same Host check, and it only reads
files. `raft watch` keeps working as it does today, and the app links to it.

## 1. What the app shows

The app is a single page with hash routes. Every page works at phone width with no sideways scroll.

### Home (`#/`)

- **Header:** the "Paper Raft" wordmark in Paperraft's serif, with a small "a Paperraft lab" link to
  paperaft.vercel.app. Navigation: Studies · Running · Bench · Find a paper.
- **Search bar,** styled like Paperraft's: "Paste an arXiv id or a Paperraft link". It opens the paper page below.
- **Hero:** a mono eyebrow line ("YOUR LAB · <date>") and a big headline built from real counts, such as "3 studies,
  1 running." The deck line names the next thing to do, taken from `raft status`.
- **Stats row,** like Paperraft's: studies, verified runs, bench entries, open gaps.
- **Running now:** live sessions as compact panels (the live view's existing `compact` mode). Each opens the full
  live view.
- **Studies:** a card per study, drafts included and marked. Each card has the title, arXiv id, the gate strip
  (paper · extraction · checker · tested · approval · gaps · runs as ✓/✗/· from `studystate.stages`, quick mode),
  the last stop if any, and the next command with a copy button.

### Study (`#/study/<id>`)

- **Header** in the style of Paperraft's paper page: a mono status line ("DRAFT · ARXIV 2608.04234 · UPDATED …"),
  the title in display type, and authors and links (arXiv, DOI, the Paperraft brief).
- **Tabs:**
  - **Overview:** the gates with their text, the next command (copy), the experiment paragraph, and the last stop
    with its problem headline.
  - **Results:** a row per method with headline status (verified / unverified / failed / no run), errors against
    the tolerance, the reviewer verdict, and a link to the solver code. A draft says "no runs yet".
  - **Flow:** the existing three.js flow view of the study, which already falls back to 2D.
  - **Checker:**
    - `checker/NOTE.md` rendered as plain paragraphs;
    - the approval state;
    - the decoy rounds (tried / blocked, each decoy's idea);
    - the builder's own decoys.
  - **Gaps:**
    - the questions with page, status and published answers;
    - a "copy the letter" button holding the text of `raft gaps --letter`;
    - the counts line.
  - **Bench:** this study's local bench entries (score, agent, time).

### Running (`#/running`)

Every live session, newest first, in the live view's full layout, inside a dark card so the network view keeps its
look. A stopped session shows its message and next command.

### Bench (`#/bench`)

The local scoreboard (`benchboard.board`), restyled, with the command to bench a study (copy).

### Find a paper (`#/paper/<arxiv id>`)

- **Paperraft's brief:** title, summary, recommendation, minimum test, claims, and links to the brief and the PDF on
  arXiv.
- **"In your lab":** if a study has that arXiv id, its gate strip and next command. If not, the command to start
  one: `uv run raft prepare --arxiv <id> --agent <claude-code|codex>` (copy).
- **The reproduction:** Paperraft's own `lab_reproductions` field, when the brief has one.
- **Offline or unknown paper:** the page says so and still shows "in your lab" and the prepare command.

**Copy buttons, not run buttons.** The app never starts `prepare`, `bench` or any agent. Those spend the user's quota
and belong in their terminal, where `--watch` already opens the live view.

## 2. Data

`raft/app.py` builds the data, and the server serves it:

- **`/app.json`:** generated time, repo root name, and today's date. Plus:
  - `studies`: every study including drafts, each with
    - its paper fields;
    - `stages` and `next` from `studystate` (quick mode, so the grader never runs);
    - the last stop;
    - gaps counts;
    - method and run counts with headline statuses.
  - `sessions`: `live.sessions`.
  - `bench`: `benchboard.board`.
- **`/app/study/<id>.json`:** one study in full:
  - `stages` (quick);
  - the methods with runs and reviews, reusing what `compare.build` computes per study (drafts get none);
  - `checker/NOTE.md` text, the approval state, and review rounds;
  - `gaps.json`;
  - local bench entries;
  - the flow (`flow.build_flow`).
- **`/paperraft/<arxiv id>.json`:** see §3.

Ids are checked against the study list and the arXiv id pattern. Anything else is a 404. No path from the browser
ever reaches the filesystem.

## 3. Paperraft lookup

New module `raft/paperraft.py`:

- `lookup(arxiv_id, *, cache_dir, fetch) -> dict | None` fetches `https://paperaft.vercel.app/papers/<id>/index.json`.
  The id must match `^\d{4}\.\d{4,5}(v\d+)?$`, and Paperraft links are reduced to their id first.
- The answer is cached in `.raft/paperraft/<id>.json` for 24 hours, and stale copies are used when offline.
- It returns only the fields the app shows: `arxiv_id`, `title`, `summary`, `recommendation`, `minimum_test`,
  `claims`, `source_url`, `lab_reproductions`, `as_of`, and `brief_url`.
- The browser never calls Paperraft directly (there's no CORS there). The local server fetches it.
- `raft paper <id>` prints the same brief as plain text, then the lab's view (study or prepare command). This is what
  agents read.

## 4. Look

- **Fonts:** Be Vietnam Pro 300 and 500 are vendored as WOFF2 under `raft/site_template/app/fonts/`, with their OFL
  licence. They're decoded from the same Google Fonts builds Paperraft embeds. The wordmark uses Paperraft's
  editorial serif stack (Iowan Old Style, Palatino, Georgia). Labels use the system mono stack.
- **Colours, as tokens on `:root`:**
  - the paper background and ink;
  - the rose accent of Paperraft's buttons;
  - muted greys;
  - status colours (verified green, failed red, warn amber), matched to the existing flow view.
- **Background:** the ordered-dither field. It's a small canvas script, adapted from Paperraft's `background.js`
  (the owner's own code), kept behind content, and still when the user prefers reduced motion.
- **Components:** the pill search bar, sheen buttons, mono eyebrow lines, the stats row with hairline dividers, and
  cards with soft borders.
- **Light only for v1.** Paperraft is light, and the live and flow views keep their dark cards.

## 5. Agents

- **`AGENTS.md` gains two rows:**
  - "look up a paper: `uv run raft paper <arxiv id>`";
  - "show the user a study, a paper or results: `uv run raft app [--study S | --paper ID]`".
- **One rule:** "When the user asks to see results or a paper, open the app for them instead of pasting JSON."
- **The `reproduce-paper` skill** ends with "Show the user: `uv run raft app --study <study>`".

## Honesty rules

- Every number on the app comes from the lab's own files or Paperraft's published brief, and each one says which.
  "Paperraft's brief" and "In your lab" are separate, labelled blocks.
- The app never shows a run as verified unless `derive_status` says so, and never shows a percentage it didn't
  read from a session file.
- Nothing leaves the machine except the lookup request to paperaft.vercel.app for the paper id the user asked about.

## Testing

- **`app.py`:**
  - `/app.json` includes drafts, with stages from quick mode, which never runs the grader;
  - study detail for a draft and for a study with runs;
  - unknown ids give 404;
  - the Host check refuses other hosts.
- **`paperraft.py`:**
  - id parsing (plain id, versioned id, a Paperraft URL, junk);
  - fetch with a fake fetcher;
  - the cache is used within 24 hours, refetched after, and a stale copy is used when offline;
  - an unknown paper gives None;
  - only the listed fields pass through.
- **`raft paper`:** text output for a paper in the lab and a paper not in it, with a fake fetcher.
- **Browser check (`scripts/check_app.mjs`):** run against a local server over a fixture repo with a draft study, a
  study with runs, a live session and a Paperraft fixture (route intercept). It checks that:
  - home renders the studies, the running panel and the stats;
  - each study tab renders;
  - the paper page shows both blocks;
  - copy buttons hold the right command;
  - phone width has no sideways scroll;
  - there are no console errors.
- **Screenshots:** home, study, paper, at desktop and phone width, for the owner's review.

## Out of scope

- Buttons that run commands.
- A dark theme.
- Changing the public GitHub Pages site (it may reuse the app's CSS later).
- Searching Paperraft's whole collection by text: there's no public index file yet. Lookup is by id or link, and a
  search index is an ai-radar change for later.
- Accounts, sharing and hosting.

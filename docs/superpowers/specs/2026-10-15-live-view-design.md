# Live view: watch an agent work through a paper

**Date:** 2026-10-15 · **Status:** draft, awaiting owner review · **Repo:** paper-raft

## Purpose

`raft prepare` and `raft bench` run agents for minutes to hours, and all you see is a few terminal lines
(`• extract: codex …`). The owner asked for a "neural network" style view of the training:

- which paper and which agent (tool + model) are working;
- the results as they come in;
- how far along it is, as a percentage.

It's also the screen people will record for launch posts ("Codex attacking Claude Code's checker, live").

## What exists today

`raft watch --study S` serves the flow view on 127.0.0.1. That's the three.js network of paper → extracted
items → methods → runs, with glowing cables. It's live only for `raft run`, which writes
`runs/.progress/<run>.json`. It doesn't help here:

- it needs a committed study with methods and runs, which a draft study in `prepare` doesn't have;
- `bench` grades in a temporary copy, so its progress files never reach the study.

## Command

```
uv run raft prepare --arxiv 2608.04234 --agent claude-code --attacker codex --watch
uv run raft bench --study transduced-lm-2026 --agent codex --watch
uv run raft watch                 # live page: every prepare/bench session on this machine
uv run raft watch --study S       # unchanged flow view, now with the live panel on top when S has a session
```

`--watch` starts the same local server in a background thread for the length of the command and opens the
browser. Without `--watch`, both commands print one line: `watch live: uv run raft watch`.

## 1. The live file

`prepare` and `bench` each write one session file, `.raft/live/<session>.json` at the repo root (gitignored, never
published). The session id is `<kind>-<study>-<UTC time>`. The file is rewritten atomically (write to a temp file,
then rename) at most twice a second, whenever something changes. Schema: `raft/contracts/live.schema.json`.

```json
{
  "kind": "prepare", "study": "wu-2026-multimodal", "title": "Multimodal Alignment Through …",
  "arxiv": "2608.04234", "pid": 4242, "started_at": "…", "updated_at": "…",
  "state": "running",                      // running | finished | stopped (failed) | lost (pid gone)
  "agents": {"builder": {"tool": "claude-code", "model": null}, "attacker": {"tool": "codex", "model": null}},
  "units": {"done": 3, "total": 6},       // the percentage, see §2
  "steps": [
    {"id": "intake", "label": "Intake", "state": "done", "detail": "studies/wu-2026-multimodal"},
    {"id": "extract-1", "label": "Extract", "agent": "builder", "state": "done", "wall_s": 412},
    {"id": "build-1", "label": "Build checker", "agent": "builder", "state": "running", "timeout_s": 2700,
     "activity": [{"t": "…", "text": "Writing problem/measure.py"}], "stderr_tail": null}
  ],
  "results": {"holes": 2, "rounds": [{"round": 1, "tried": 3, "blocked": 3}]},
  "message": null                          // the SystemExit text when state is stopped
}
```

`bench` uses the same shape. Its steps are one agent step per method (`implement <m>`) and then one step per graded
run (`run <run id>`), with `"fraction"` taken from the runner's progress reports when the solver gives them. Its
`results` are `{"passed": n, "failed": n, "expected": n, "score": n/expected}` so far.

A session whose `pid` is no longer alive and whose state is still `running` is shown as `lost`, so a killed
terminal doesn't look like work in progress forever.

## 2. The percentage, honestly

The percentage is **finished work units / total work units**. It's never a guess about how far an agent is inside
its step.

- `prepare`: intake 1, extract 1, build 1, one unit per attack round (up to `--rounds`). Steps already passed on a
  resumed run count as done. A retry adds a unit to `total`, so the bar can step back once. That's what really
  happened, and the step list says why ("Extract, try 2"). When a round is fully blocked, the rounds left are
  dropped from `total` and the bar reaches 100%.
- `bench`: one unit per method's agent step plus one per graded run. A running graded run counts its runner
  `fraction` (0–1) when the solver reports one.
- Inside a running agent step the page shows elapsed time against the step's timeout, as a thin separate line,
  never folded into the percentage.

## 3. What the agent is doing now

While an agent step runs, `prepare` and `bench` tail the agent's JSON event stream, the same transcript file they
already keep, once a second. The newest few events become `activity` lines:

- `claude-code`: assistant text and tool calls (`Edit problem/measure.py`, `Bash: uv run raft validate`);
- `codex`: `agent_message` text and `command_execution` commands;
- `command`: none (unknown format); the step shows only elapsed time.

Each line is cut to 160 characters. The last 3 lines of the agent's stderr go in `stderr_tail`, so a broken tool
shows on the page right away (today's case: Codex printing `timed out negotiating with the code-mode host` three
times while the step still looked like it was running). Parsers are tested on recorded sample streams of each tool.
Malformed lines are skipped.

## 4. The page

`raft watch` with no `--study` serves `live.html`. The visual language matches the flow view (dark background,
glowing cables, the same three.js and bloom setup, `flow.css` colours), built as its own module
`raft/site_template/flow/live.js` so `flow.js` stays as it is.

- **Top line:** the paper title and arXiv id, linked to the paper, plus the agents as chips
  (`builder: claude-code · attacker: codex · model: default`).
- **The network:** one node per step, in order, left to right, wired by cables. Done nodes are solid, the running
  node pulses and its cable carries moving light, pending nodes are dim, and failed nodes are red. Attack rounds
  fan out from the checker node, one small node per attack: green when blocked, red when it got through. For bench,
  method nodes fan out into their run nodes, coloured pass/fail as they finish.
- **Under it:** the percentage bar with `done / total` units, the running step's elapsed time against its timeout,
  the activity lines, and `stderr_tail` in amber when present.
- **Results box:** for prepare, validate holes and rounds (tried / blocked); for bench, passed / failed / expected
  and the score so far.
- **Several sessions:** a list on the left, newest first; the running one is selected by default.
- **When it ends:** finished shows the next command (`uv run raft approve --study …`, or the bench entry path);
  stopped shows `message` in full.
- The page polls `/live.json` every second. If WebGL is missing it falls back to the same layout drawn with plain
  HTML (the flow view already handles this case).

`raft watch --study S` shows the same panel above the flow view when S has a running session.

## 5. Server

`raft/watch.py` gains `/live.json` (every session file, newest first, with `lost` worked out from the pid) and
`/live.html`. It's the same server, still 127.0.0.1 only with the same Host check, and still reads files only. A draft
study no longer makes `raft watch` fail: without `--study`, the flow isn't built at all.

## Honesty rules

- The page shows only what the harness itself recorded: step states, its own validate and grading results, and
  the agent's own words labelled as the agent's. Nothing the agent says counts as a result.
- No fake progress: see §2.
- Live files stay on this machine. Nothing is committed or published, and the public site doesn't change.

## Testing

- `live.py` unit tests: units and percentage for prepare (fresh, resumed, a retry, an early fully blocked round) and
  for bench; atomic writes; `lost` when the pid is gone.
- `prepare` and `bench` with the existing fake agents: the session file walks through the expected states and ends
  `finished` or `stopped` with the message; it validates against the schema at every write in the test.
- Transcript tailing: recorded claude-code and codex streams (including Codex's code-mode error lines) give the
  expected activity lines; junk lines are skipped.
- Server: `/live.json` lists sessions and marks a dead pid as lost; the Host check still refuses other hosts.
- Headless browser check (`scripts/check_live.mjs`, like `check_bench.mjs`): the page renders a fixture session
  (running, finished, stopped), shows the percentage and the activity lines, and has no console errors.
- One real run by the owner: `raft prepare --study wu-2026-multimodal --agent claude-code --attacker codex --watch`.

## Out of scope

A terminal panel (the owner chose the browser page), showing live sessions on the public site, real loss curves
from solvers (studies can add those later through the runner's `progress`), and controls on the page (stop,
retry). The page only watches.

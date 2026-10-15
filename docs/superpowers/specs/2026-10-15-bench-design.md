# Bench: bring your agent, reproduce a paper, get a score

**Date:** 2026-10-15 · **Status:** draft, awaiting owner review · **Repo:** paper-raft

## Purpose

Developers who use Claude Code or Codex already tune their own setup: a model, an `AGENTS.md` or `CLAUDE.md`,
skills, prompting habits. They have no honest way to know whether that setup does real research work better.
Paper Raft already has papers turned into graded problems. The bench lets anyone point their own agent and setup
at a study, get a score graded by the study's own yardstick, and publish it on a public scoreboard next to everyone
else's.

The scoreboard is the launch hook ("I gave the same paper to Claude Code and Codex"), and the thing people come
back to: change your setup, rerun, and see if the score moved.

## What the owner asked for

- Traction among Claude Code and Codex users first.
- They use the papers to get different results with *their own* solution (their model, config, technique).
- Model-agnostic: the same study runs on different models, including local ones.
- Ready to launch this week.

## Words

- **Entrant:** one agent setup: a tool (`claude-code`, `codex`, or `command`), an optional model, and an optional
  *setup folder* (the user's own `AGENTS.md`, `CLAUDE.md`, `.claude/skills/`, `.codex/` and so on).
- **Entry:** one bench run of one entrant on one study: its code, its graded runs and its numbers.

## Command

```
uv run raft bench --study transduced-lm-2026 --agent codex [--model gpt-5-codex] [--setup ./my-setup] \
                  [--methods smc-rb,beam-swor] [--label "my AGENTS.md v2"] [--timeout 30m]
uv run raft bench --agent command --cmd "my-agent --prompt-file {brief}" ...   # any other tool
uv run raft bench --verify bench/results/transduced-lm-2026/<entry>          # rerun an entry's code, check the numbers
uv run raft bench --table [--study s]                                          # markdown scoreboard for README/posts
```

Codex with a local model is `--agent codex --model <ollama model> --oss`, so a free entry needs no API key.

## How a bench run works

1. **Blind workspace.** The harness exports the study at `HEAD` into a temporary folder with **no git history**
   (so `git log` cannot show the lab's solutions) and without `methods/`, `runs/`, `reviews/`, `site/`, `bench/`,
   `problem/measure.py` and `problem/reference.json`. The agent gets `extraction.json`, `problem/setup.py`,
   `paper.yaml`, the PDF if present locally, the raft package, and a fresh `git init` so it can commit if its
   habits require it. The yardstick is not on disk, so it cannot be read, imported or copied.
2. **Overlay.** The setup folder, if given, is copied onto the workspace root. This is where "their solution" lives.
3. **Agent, one method at a time.** For each method, the harness renders a new role `roles/bench-implementer.md`
   (the implementer role minus the yardstick steps: write only `methods/<m>/`, check with the problem's own
   invariants, do not run `raft run`) and starts the tool headless in the workspace:
   - `claude-code`: `claude -p <brief> --output-format json` with `--model` when given, edit and bash tools
     allowed, web tools disallowed.
   - `codex`: `codex exec <brief> --json --sandbox workspace-write` (network off by default) with `-m` when given.
   - `command`: the user's command with `{brief}` (a file path) and `{workspace}` filled in.
   Each method has a wall-clock timeout (default 30 min). Methods run one after another so entrants are compared
   on equal terms.
4. **Grading, outside the agent's reach.** The harness copies each `methods/<m>/` into a clean grading checkout of
   the study (yardstick restored), runs the guard, then the same runner `raft run` uses, over the study's full run
   matrix. Nothing the agent printed or claimed counts; only the harness's own runs.
5. **Entry written** to `bench/results/<study>/<entry-id>/` (entry id: `<date>-<agent>-<model>-<short hash>`):
   - `entry.json`: entrant (tool, tool version, model, label, setup-folder hash and file list), raft commit,
     machine, per method: agent exit status, wall time, tokens and cost **as reported by the tool** (marked
     self-reported; cost only where the tool gives it), guard result, and per run: pass/fail, status, metrics.
   - `methods/<m>/`: the agent's code, so anyone can read it and `--verify` it.
   - `transcript/<m>.jsonl`: the tool's JSON event stream, trimmed to 2 MB per method.
   Schema: `raft/contracts/bench-entry.schema.json`.

## Score

- **Score** = passing runs / runs the study's run matrix expects, over the methods attempted. A method the agent
  did not finish, that fails the guard, or that crashes counts as failing all its runs.
- Shown with it: methods attempted, the study's metrics (same `metrics:` from `paper.yaml` as the flow view),
  total wall time, total tokens, cost where known.
- A full entry attempts every method; a partial one (`--methods`) is labelled partial and ranked separately.
- Bench entries are graded automatically and **not reviewed**. The scoreboard says so. The lab's own reviewed
  methods are not on the scoreboard; they were made under different conditions.

## Scoreboard

- `raft compare` adds a **Bench** page to the site: one table per study, full entries ranked by score, then lower
  cost, then lower wall time; partial entries below. Each row links to its code and transcript on GitHub.
- The overview gets a small "Bench" box with the top entries per study.
- `raft bench --table` prints the same as markdown for the README and launch posts.

## Submitting an entry

A pull request that adds one `bench/results/<study>/<entry-id>/` folder. CI runs `raft bench --verify` on every
entry: the schema validates, the guard passes on the code, and rerunning the code reproduces the recorded
pass/fail and metrics. Tokens, cost and time cannot be verified and stay marked self-reported. CONTRIBUTING.md
gets a short "Submit a bench entry" section.

## Honesty rules

- Grading uses only the harness's own runs of the agent's code, in a checkout the agent never touched.
- Failures are published like passes. No tolerance changes for the bench.
- Self-reported fields are labelled on every surface that shows them.
- Known limit, stated on the scoreboard: an agent with network access could look up the public repo; the
  claude-code adapter disallows web tools and codex runs with network off by default, and each entry records
  whether network was available.

## Testing

- pytest with a tiny fixture study and a fake agent (`--agent command` running a script that writes a known
  solver): the workspace has no history and no yardstick; the setup overlay lands; grading uses a clean
  checkout; a solver that reads a forbidden path fails the guard; a timeout records a failed method; the entry
  validates against the schema; `--verify` passes on an untouched entry and fails after a metric is edited;
  `--table` ranks full before partial and breaks ties by cost.
- Adapters: command lines built for claude-code and codex (with and without `--model`, `--oss`) checked as data;
  token and cost parsing from recorded sample outputs of each tool.
- Site: the Playwright check opens the Bench page with a fixture entry, no console errors.
- One real smoke run per tool on one method, run by the owner on their own accounts before launch.

## Out of scope

Reviewer agents in the bench, a second study (separate work; needed before launch), Gemini CLI and OpenCode
adapters (covered by `--agent command` for now), parallel methods, hosted runners, a launch post (drafted
separately).

# Paper Raft: notes for coding agents

Paper Raft is a harness where agents reproduce research papers and the harness, not the agent, decides what passed.
Everything runs through the `raft` CLI. Set up with `uv sync` and run Python only through `uv run`.

If `raft prepare` or `raft bench` started you, the brief you were given is your whole task. This file adds nothing
to it.

## Find your task

Each job has a brief. Print it, then follow it exactly.

| You were asked to | Run |
|---|---|
| turn a study's paper into `extraction.json` | `uv run raft extract --study <study>` |
| implement one method of a study | `uv run raft implement <method> --study <study>` |
| run a method and record its results | `uv run raft run <method> --study <study>` |
| review someone else's method | `uv run raft review <method> --study <study>` |
| build a new study's checker | `uv run raft build-checker --study <study>` |
| attack a checker | `uv run raft attack --study <study>` |
| check a checker | `uv run raft validate --study <study>` |
| add a grader to a checker | `uv run raft grader add <checks\|table\|claims> --study <study>` |
| say which missing detail keeps a check out of the grader | `uv run raft gaps --study <study> --blocks <id> "<check>"` |
| build the site | `uv run raft compare` (writes `site/`) |

These commands start other agents and spend the user's quota. Ask the user before you run any of them:
`uv run raft prepare` (from an arXiv id to a checker waiting for approval) and `uv run raft bench` (scores an agent
setup on a study). Add `--watch` to either for a live page on 127.0.0.1. `uv run raft watch` lists every session
running on this machine.

## Rules

- Never run `raft approve`, and never create or edit `checker-approval.json`. Only the owner approves, in their own
  terminal.
- Never record, edit or invent an author's answer in `gaps.json`. Only the owner records answers, in their own
  terminal (`raft gaps --answer` refuses inside agent sessions).
- Never lower a tolerance to make something pass. If the paper's number can't be met, say so and record the failure.
- Once a study has runs, its `problem/` folder is frozen. Before that, only the checker builder writes there.
- If you implement a method, write only inside `studies/<study>/methods/<method>/`. Never open `problem/measure.py`,
  `problem/reference.json`, `checker/`, `runs/` or `reviews/`.
- Never review a method you implemented.
- A failed reproduction is a result. Commit it, with the reason.
- Never commit PDFs; `papers/` is gitignored. Fetch arXiv papers only through `raft new --arxiv` (official
  endpoints only), never from mirrors.
- Never edit a bench `entry.json` by hand. `.raft/` holds this machine's live sessions; never commit it.

## Before you finish

Run what CI runs, and say in your final message what passed and what didn't:

```bash
uv run pytest -q
uv run raft extract --validate --all-studies
uv run raft review --validate --all-studies
uv run raft repro --all-studies   # reruns every committed result, about 5 minutes
```

## Layout

- `raft/`: the CLI and harness. `raft/contracts/` holds the JSON schemas every file is checked against.
- `roles/`: the brief templates that `raft <command>` fills in.
- `studies/<study>/`: `paper.yaml`, `extraction.json`, `problem/` (setup and grader), `checker/` (the checker's
  evidence), `methods/`, `runs/`, `reviews/`.
- `bench/results/`: where `raft bench` writes scoreboard entries; `raft bench --verify` reruns them.
- `adapters/claude-code/`: the source of `.claude/` (the Claude Code subagents and the `reproduce-paper` skill).

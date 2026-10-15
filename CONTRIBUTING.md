# Contributing to Paper Raft

## Add a method to an existing study
1. Read the brief with `uv run raft implement <your-method> --study <study>`.
2. Write `studies/<study>/methods/<your-method>/solver.py` and `method.json`, touching nothing outside that folder.
3. Run `uv run pytest -q`. The guard test must pass.
4. Commit the folder, then run `uv run raft run <your-method> --study <study>` (add study parameters such as `--case bigram` to narrow it) and commit `runs/<your-method>-*`.
5. Open a PR. A maintainer or a different agent reviews it with `uv run raft review <your-method>`; you can't review your own method (`--study <study>` as above).

## Add a study (a new paper)
Start with `uv run raft new <id> --title "…" --doi "…"`. That creates a draft folder, which `--all-studies` and the site skip until you remove `draft: true` from `paper.yaml`. Fill in:
- `paper.yaml`: `title`, `authors`, `citation`, `doi`, `pdf` (a local path under `papers/`; never commit the PDF), `experiment`
- `problem/setup.py`: `make_setup(params)`, `expand(params)`, `HEADLINE`, optional `REPRO_RTOL`, and a docstring that defines the `solve(setup)` interface
- `problem/measure.py`: `measure(setup, fields, reference)` (give it a parameter named `method` if methods are graded against different claims) returning `samples`, `reference_samples`, `errors`, `tolerance`, `pass`, and optionally `fields_coarse`
- `problem/reference.json`: the paper's numbers, with table and page references and a citation

Then run the extractor (`uv run raft extract --study <id>`) and continue as above. Copy `studies/transduced-lm-2026/` as a worked example: it shows a study whose methods are graded against different claims.

## Submit a bench entry
1. Run `uv run raft bench --study <study> --agent <claude-code|codex|command> …` (see the README). It writes `bench/results/<study>/<entry-id>/`.
2. Read `transcript/` in that folder before you share it: it is your agent's full session and may show paths or settings from your machine. Delete nothing else.
3. Commit only that folder and open a PR. CI runs `uv run raft bench --verify` on every entry: your code is rerun and must reproduce the recorded results.
4. Do not edit `entry.json` by hand; verification will fail.

## Ground rules
- Never lower a tolerance to make something pass.
- Failed reproductions are welcome: commit them, with the reason.
- Never commit paper PDFs.

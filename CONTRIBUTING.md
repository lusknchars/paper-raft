# Contributing to Paper Raft

## Add a method to an existing study
1. Read the brief with `uv run raft implement <your-method>`.
2. Write `studies/<study>/methods/<your-method>/solver.py` and `method.json`, touching nothing outside that folder.
3. Run `uv run pytest -q`. The guard test must pass.
4. Commit the folder, then run `uv run raft run <your-method> --re 100` and commit `runs/<your-method>-*`.
5. Open a PR. A maintainer or a different agent reviews it with `uv run raft review <your-method>`; you can't review your own method.

## Add a study (a new paper)
Start with `uv run raft new <id> --title "…" --doi "…"`. That creates a draft folder, which `--all-studies` and the site skip until you remove `draft: true` from `paper.yaml`. Fill in:
- `paper.yaml`: `title`, `authors`, `citation`, `doi`, `pdf` (a local path under `papers/`; never commit the PDF), `experiment`
- `problem/setup.py`: `make_setup(params)`, `expand(params)`, `HEADLINE`, optional `REPRO_RTOL`, and a docstring that defines the `solve(setup)` interface
- `problem/measure.py`: `measure(setup, fields, reference)` (add a `method` parameter if methods are graded against different claims) returning `samples`, `reference_samples`, `errors`, `tolerance`, `pass`, and optionally `fields_coarse`
- `problem/reference.json`: the paper's numbers, with table and page references and a citation

Then run the extractor (`uv run raft extract --study <id>`) and continue as above. Copy `studies/ghia-1982/` as a worked example.

## Ground rules
- Never lower a tolerance to make something pass.
- Failed reproductions are welcome: commit them, with the reason.
- Never commit paper PDFs.

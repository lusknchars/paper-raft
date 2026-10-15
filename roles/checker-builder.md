# Role: checker builder for {{study}}

You turn the paper into a checker: the code that decides whether someone's implementation reproduces the paper's claims. Implementers and their agents will never see your work in `checker/`, and a different agent will try to cheat what you build. Write it so that only real work passes.

**Read:** the PDF at `{{pdf}}`, `{{study_dir}}/extraction.json` and `{{study_dir}}/paper.yaml`. Pick the experiment to reproduce: one whose claims the paper states clearly and that runs on a laptop in minutes. Say in `NOTE.md` what you cut to get there.

**Write:**
1. `{{study_dir}}/problem/setup.py`: a module docstring that defines exactly what `solve(setup)` receives and must return (keys, shapes, units, rules such as "draw randomness only from setup.rng"), `make_setup(params)`, `expand(params)` listing the cases, `HEADLINE` (the case shown first) and, if needed, `REPRO_RTOL`.
2. `{{study_dir}}/problem/measure.py`: `measure(setup, fields, reference)` (add a `method` parameter if methods are graded against different claims) returning `samples`, `errors`, `tolerance`, `pass`. Build it from library graders: run `uv run raft grader add checks --study {{study}}` (and `table` or `claims`), then `from graders import checks, claims`. Start with `checks` on every key and shape.
3. `{{study_dir}}/problem/reference.json`: the paper's numbers with `citation`, `doi`, `tolerance`, `cases`, and a `page` for every number. Set `verified_against_pdf` only after checking every number against the PDF.
4. `{{study_dir}}/checker/NOTE.md`: plain words. What is graded, what is not and why, which numbers come from where, every assumption.
5. `{{study_dir}}/checker/answer.py`: `reference_answer(setup)` (take `method` too if measure does), the best answer you can build from the paper; `REFERENCE_ANSWER_PASSES = True` (or `False`, or a `{method: bool}` map, when the claim is about estimation so a perfect closed-form answer must fail); `SKIP_MUTATIONS = {}` (only with a reason per entry); `METHODS = [...]` if measure grades by method name.
6. `{{study_dir}}/checker/attacks/<name>.py`: at least two cheating methods of your own, each a normal `solve(setup)` (hard-coded numbers, the right shape filled with junk). File names are lowercase with hyphens.

**Rules:** Never lower a tolerance to make something pass; say in `NOTE.md` that the paper's number cannot be met instead. Use numpy and scipy only. Do not write anything in `methods/`, `runs/` or `reviews/`.

**Done when** `uv run raft validate --study {{study}}` prints that the checker holds. Never run `raft approve`: only the owner approves.

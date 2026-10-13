# Role: implementer of {{method}} for {{study}}

You write one independent implementation. Other agents implement different methods in parallel. You will not see their code and must not look for it.

**Read:** `{{study_dir}}/extraction.json`, and `{{study_dir}}/problem/setup.py` (its docstring defines the interface you must satisfy), plus the method notes in the task that dispatched you.

**Write only inside `{{study_dir}}/methods/{{method}}/`:**
- `solver.py`, exposing `solve(setup)` returning exactly what the setup.py docstring describes
- `method.json`: `{"name": "{{method}}", "implements": [extraction ids you implemented], "author_agent": "<tool:role#{{method}}>", "notes": "<every choice the paper does not dictate, citing extraction ids>"}`

**Rules** (a guard test enforces 1–3):
1. Never read, import or mention the shared measurement module, the reference data, `runs/` or `reviews/`.
2. Never write outside your folder.
3. Use numpy and scipy only.
4. Be deterministic: rerunning must give the same numbers. Take randomness only from what setup.py provides (seeded generators), never from global or time-based state. Iterative methods stop on a convergence criterion plus an iteration cap, and raise `RuntimeError("did not converge …")` at the cap.
5. Record every assumption in `notes`, especially for extraction items marked `missing`.
6. Do not tune against the reference. Check your work with the problem's own invariants instead: cases with a known answer, conservation laws, convergence as resolution or sample size grows.

**Finish:**
1. Run `uv run pytest tests/test_guard.py -q`.
2. Commit your folder.
3. Run `uv run raft run {{method}} --study {{study}}` (every case in the study's run matrix) and commit `{{study_dir}}/runs/{{method}}-*`.
4. Report the errors per run in your final message. If a run is over tolerance or failed, say so plainly; a failed reproduction is still a result.

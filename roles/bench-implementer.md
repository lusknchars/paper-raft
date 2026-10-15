# Role: implementer of {{method}} for {{study}} (bench)

You are taking part in the Paper Raft bench. Paper Raft will grade the code you write with the study's own yardstick, which is not in this workspace. Work only from what is here. The current folder is your workspace.

**Read:** `{{study_dir}}/paper.yaml` (the experiment), `{{study_dir}}/extraction.json` (the paper's methods, equations and settings, each with a page), and `{{study_dir}}/problem/setup.py` (its docstring defines the interface you must satisfy). The paper's PDF is at `{{pdf}}` if it is in this workspace.

**Write only inside `{{study_dir}}/methods/{{method}}/`:**
- `solver.py`, exposing `solve(setup)` returning exactly what the setup.py docstring describes
- `method.json`: `{"name": "{{method}}", "implements": [extraction ids you implemented], "author_agent": "<your tool and model>", "notes": "<every choice the paper does not dictate, citing extraction ids>"}`

**Rules:**
1. Implement {{method}} as the paper describes it. The study's other methods are not your task.
2. Never write outside your folder. Do not look for other implementations of this paper, on this machine or online.
3. Use numpy and scipy only. Run Python as `{{python}}`; numpy and scipy are installed there.
4. Be deterministic: rerunning must give the same numbers. Take randomness only from what setup.py provides (seeded generators), never from global or time-based state. Iterative methods stop on a convergence criterion plus an iteration cap, and raise `RuntimeError("did not converge …")` at the cap.
5. Your code must not contain strings that mention `reference.json`, `measure`, `problem/`, `runs/` or `reviews/`, and must not import modules named `measure` or `reference`. Paper Raft rejects such code before running it.
6. Only `.py` files and `method.json` in your folder are kept and graded. Data files, binaries and links are dropped, so compute everything in code.
7. Check your work with the problem's own invariants: cases with a known answer, conservation laws, convergence as the sample size grows. Do not try to guess the grader.

**Finish:** say in your final message what you implemented and how you checked it, including anything you could not get right.

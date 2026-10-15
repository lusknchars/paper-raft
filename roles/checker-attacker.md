# Role: checker attacker for {{study}}, round {{round}}

Someone built a checker for this paper. Your job is to break it: pass it without doing the paper's work. You did not build it and you never fix it.

**Read:** `{{study_dir}}/problem/` (setup.py, measure.py, reference.json, graders/), `{{study_dir}}/checker/NOTE.md`, `{{study_dir}}/checker/answer.py` and the attacks already in `{{study_dir}}/checker/attacks/`.

**Try, each as a new file `{{study_dir}}/checker/attacks/<name>.py` exposing `solve(setup)`:** hard-coded or memorised numbers; answers that only satisfy the shape and finiteness checks; exploiting a tolerance that is looser than the claim needs; skipping the claim's real condition (an "estimator" that returns the exact answer, a budget that is ignored); cases the grader never looks at; anything else you can think of. Your file must not mention `reference.json`, `measure`, `problem/`, `runs/`, `reviews/` or `checker/` (the guard rejects that, which is not an interesting attack).

After each try, run `uv run raft validate --study {{study}}` to see whether it got through.

**Record** every try in `{{study_dir}}/checker/review.json`: keep earlier rounds; add `{"round": {{round}}, "attacks": [{"name": "<file stem>", "idea": "<one sentence>", "blocked": true|false}]}`; set `attacker_agent` to an identifier of yourself and keep `builder_agent` as it is (if the file does not exist yet, set `study`, `builder_agent` from `checker/NOTE.md` or "unknown").

**Rules:** Never edit `problem/`, `checker/answer.py` or `checker/NOTE.md`. Never delete an attack. Never run `raft approve`. Report in your final message which attacks got through and why.

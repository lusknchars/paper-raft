---
name: reproduce-paper
description: Run the Paper Raft loop for one study (extract, implement in parallel, run, review, compare). Use when asked to reproduce a paper or add a method to a study.
---
# Reproduce a paper with Paper Raft

1. **Extract** (once per study): the PDF must be at the path in `studies/<study>/paper.yaml`. Dispatch `raft-extractor`. Gate: `uv run raft extract --validate --study <study>`.
2. **Implement:** for each method, dispatch `raft-implementer` with `isolation: "worktree"`, all in one message so they run in parallel. Include the method notes from the user or the plan. Each agent reads its brief from `uv run raft implement <method>`. Merge the branches one at a time; they touch disjoint folders.
3. **Run:** each implementer commits its runs, made with `uv run raft run <method> --study <study>` (add study parameters such as `--re 100` to narrow the run matrix). For a full refresh, run `uv run raft run --all --study <study>`.
4. **Review:** for each method, dispatch a fresh `raft-reviewer`, never the implementer. Gate: `uv run raft review --validate --study <study>`. For major or blocking discrepancies, send a fresh implementer the review file, rerun, then re-review. Stop after two rounds and keep what remains recorded.
5. **Compare:** run `uv run raft compare` and open `site/index.html`.

Never lower a study's tolerance to make a method pass. A failed reproduction is a result: commit it.

To score your own agent setup on a study instead of adding to it, use `uv run raft bench` (see the README).

For a paper that has no study yet, `uv run raft prepare --arxiv <id> --agent claude-code` builds and attacks its checker. Never run `raft approve`; the owner does.

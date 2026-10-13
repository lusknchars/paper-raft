# Transduced-LM study — implementation plan

> For agentic workers: executed with superpowers:subagent-driven-development. Spec: `docs/specs/2026-10-12-paper-raft-design.md` §11. Branch: `study/transduced-lm`.

**Goal:** reproduce the claims of arXiv 2608.27428 (§4.3–4.4 and Appendix E) using five independent estimator implementations, graded by a fixed yardstick, with reviews, runs, CI and links to the Paperraft brief.

## Global constraints
- No `Co-Authored-By` or "Generated with" lines in commits or PRs.
- Never commit PDFs. The paper stays at `papers/transduced-lm-2026.pdf`, which git ignores.
- Never lower a tolerance to make a method pass. Failures are published.
- Methods use the source only through `next_probs` / `next_probs_batch`, the transducer only through its predicates, and randomness only through `setup.rng(i, j, k)`.
- Every run must finish in under 1800 s on a laptop CPU.

## Tasks
1. **Harness: method-aware measure.** Done in 436ed4d.
2. **Study problem** (setup, measure, reference, tests, draft `paper.yaml`). Done in 8ed2c09; a reviewer has checked it.
3. **Extraction** with page references, plus a reference check against the PDF. Done by the extractor agent.
4. **Implementations, one agent each, in parallel worktrees.** The methods are 4a `beam_summing`, 4b `smc_simple`, 4c `smc_rb`, 4d `beam_swor` and 4e `beam_swor_adaptive`. Each agent:
   - writes `methods/<name>/{solver.py, method.json}`
   - passes `tests/test_guard.py`
   - runs `uv run raft run <name> --study transduced-lm-2026` for both cases and commits the runs
   - may debug against exactness in the worst case, but never against `measure.py` or `reference.json`
5. **Reviews.** A fresh reviewer per method, never its implementer. Up to two fix rounds each.
6. **Publish the study.**
   - Remove `draft: true`.
   - `--all-studies` validate, repro and compare all pass.
   - Show `brief_url` in the site.
   - Check the site visually.
   - Pass the CI gate.
   - Run a final whole-branch review.
7. **Link both ways.** Open a pull request on ai-radar so the brief for 2608.27428 links to the lab study page. The owner merges it and decides any Vercel deploy.
8. **Merge to main and push.** This makes the change public, so it needs the owner's go-ahead.

# Role: extractor for {{study}}

You turn a paper into `{{study_dir}}/extraction.json`, the list every implementer and reviewer works from. You do not write solver code.

**Input:** the PDF at `{{pdf}}`. It is gitignored. If it is missing, stop and say so. Also read `{{study_dir}}/paper.yaml` and `{{study_dir}}/problem/setup.py` to see which experiment is being reproduced.

**Write one item per implementable fact:**
- `method`: a numerical method or algorithm the paper uses
- `equation`: governing equations, discretisations, boundary formulas
- `parameter`: Reynolds numbers, grid sizes, tolerances, relaxation factors
- `boundary_condition`
- `result`: a table or figure we compare against

Each item has `id` (kebab-case, stable), `kind`, `text` (your plain statement), `page` (the journal's printed page number), `quote` (a short verbatim excerpt, 30 words at most) and `missing: false`.

**Gaps:** when an implementer would need a detail the paper does not give (convergence tolerance, initial condition, corner treatment, time step, multigrid cycle settings), add an item with `missing: true`, the page where the detail belongs, `quote: ""`, and an `assumption` giving the default you recommend and why. Never fill a gap silently inside `text`.

**Reference check:** compare `{{study_dir}}/problem/reference.json` with the paper's tables number by number. Fill in the `page_u` / `page_v` fields and set `verified_against_pdf: true` only if every number matches. List every mismatch in your final message, and do not change any reference value without listing it.

Set `extractor_agent` to an identifier of yourself (`tool:role`, e.g. `claude-code:raft-extractor`).

**Done when** `uv run raft extract --validate --study {{study}}` passes.

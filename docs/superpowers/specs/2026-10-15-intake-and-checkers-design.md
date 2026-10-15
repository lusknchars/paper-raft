# From an arXiv id to a trusted checker: design

**Date:** 2026-10-15 · **Status:** draft, awaiting owner review · **Repo:** paper-raft

## Purpose

Today a new paper becomes a study only by hand: `raft new` writes stubs that raise `NotImplementedError`, and a
person writes `problem/setup.py`, `measure.py` and `reference.json`. That is the step that keeps Paper Raft from
running on its own. This spec makes it autonomous up to one human decision:

```
uv run raft prepare --arxiv 2608.27428 --agent codex --attacker claude-code
```

fetches the paper, extracts it, has one agent build the checker (the grader), has a different agent attack it, loops
until the checker holds or three rounds pass, and stops at a single screen where the owner approves or rejects it.
After approval, `raft bench` and `raft run` work on the new paper with any agent and setup.

## Where this sits (the whole pipeline the owner asked for)

| Step | What | Spec |
|---|---|---|
| 1. Find good papers | rank Paperraft's collection by how testable each paper is | later: *discover* |
| 2. Turn a paper into a test | intake + checker build + attack + approval | **this spec** |
| 3. Test it | `raft bench` / `raft run` with different agents, models, setups | done |
| 4. Results | scoreboard, flow view | done |
| 5. Overview: what happened, what to do better | per-study report over every composition (agent × model × setup × method), failure reasons from runs, reviews and transcripts, and suggested next tries | later: *overview* |
| 6. Compare pursuits | the same overview across studies and topics | later: *overview* |

*Discover* and *overview* each get their own spec after this one ships. `raft auto` (steps 1–3 in one command)
comes with *discover*.

## Decisions already taken (2026-10-13)

- Checker sign-off is option A: an agent builds the checker, a different agent attacks it, the owner approves.
- Graders are a library; each study keeps its own copy, and `raft validate` reports copies that are behind.
- Existing studies keep their `problem/` untouched (editing it would make every run stale).

## 1. Intake: `raft new --arxiv <id>`

- Fetches the record from arXiv's official OAI-PMH endpoint
  (`https://export.arxiv.org/oai2?verb=GetRecord&identifier=oai:arXiv.org:<id>&metadataPrefix=arXiv`):
  title, authors, abstract, first-version date, licence, and the DOI `10.48550/arXiv.<id>`.
- Downloads the PDF from `https://arxiv.org/pdf/<id>v<n>` into `papers/<study>.pdf` (gitignored; never committed).
  No other source, ever. One request at a time, at least 3 s apart, with a User-Agent naming Paper Raft.
- Writes the draft study as `raft new` does today, with `paper.yaml` filled in: `title`, `authors`, `citation`,
  `doi`, `pdf`, `pdf_url`, `license`, `abstract`, `arxiv: <id>`, `draft: true`, and `brief_url` when the owner
  passes `--brief <url>` (Paperraft papers).
- Study id: `--id` if given, else `<first-author-surname>-<year>-<first title word over 3 letters>`, lowercased
  ASCII, e.g. `snaebjarnarson-2026-stochastic`. Refuses if it exists.
- Errors are one line each: unknown id, network down, PDF too large (> 50 MB), not a PDF.
- `raft new <id> --title … --doi …` keeps working for non-arXiv papers.

## 2. Grader library: `raft/graders/`

Each grader is one small module with a version, written once from the two studies we have, and tested, including
against cheats:

- `table.py`: points compared with a paper's table within a tolerance (max and RMS error), from Ghia.
- `claims.py`: `exact` (within a tolerance of a closed form), `unbiased` (z-test over seeds against the true value),
  `error_falls` (relative RMSE drops as the budget grows), `lower_bound` (never above the truth), `within_budget`
  (a reported resource never exceeds its limit), from transduced-LM.
- `checks.py`: shape, finiteness and key checks every `measure.py` starts with.

`raft grader add <name> --study <s>` copies a grader into `studies/<s>/problem/graders/<name>.py` with a header
line `# raft-grader <name> v<version> sha256:<hash of the library file>`. `raft validate` reports any copy whose
version is behind the library or whose body no longer matches its header. Copies, not imports, so a library change
never silently changes a published study's grading. The two existing studies are not converted.

## 3. The checker folder: `studies/<s>/checker/`

Outside `problem/`, so adding evidence never makes runs stale. The bench workspace never includes it, the
implementer role gains a rule never to read it, and the guard forbids method code from mentioning `checker/`.
Reviewers may read it.

- `NOTE.md`: written by the builder, in plain words: what is graded, what is not and why, which paper numbers are
  used, and every assumption.
- `answer.py`: `reference_answer(setup) -> fields`, the best answer the builder can build from the paper (used only
  by validation), plus `REFERENCE_ANSWER_PASSES = True | False` (False when the claim is about estimation, so a
  perfect closed-form answer must fail) and `SKIP_MUTATIONS = {name: reason}`.
- `attacks/<name>.py`: cheating methods, each a normal `solve(setup)` that passes the guard (a cheat the guard
  already stops is not interesting). The builder writes the first ones; the attacker adds more every round.
- `review.json`: the attacker's record per round: each attack's idea, file, and whether it was blocked.
  Schema `checker-review.schema.json`.

## 4. `raft validate --study <s>` (checker part)

1. Schemas and grader copies (above).
2. **Positive control:** `reference_answer` through `measure` for every case passes if `REFERENCE_ANSWER_PASSES`,
   fails otherwise.
3. **Mutations** of `reference_answer`, all of which must fail every case: `nan` (one value NaN), `inf`,
   `wrong_shape` (drop the last entry of each array), `zeros`, `scaled` (× 1.5), `shuffled` (permute each array).
   A mutation may be skipped only through `SKIP_MUTATIONS` with a reason; the approval screen shows each skip.
4. **Attacks:** every file in `checker/attacks/` runs through the normal runner (guard included) in a temporary
   copy of the study, like bench grading. Any attack that passes any case fails validation, with its name.
5. Output: one line per check, then `✓ checker holds` or `✗` lines naming each hole.

## 5. Roles and the loop

New roles in `roles/`, rendered by commands that print them like `raft extract` does:

- `raft build-checker --study <s>` → `roles/checker-builder.md`: read the PDF, `extraction.json` and `paper.yaml`;
  write `problem/setup.py` (interface docstring, cases, `make_setup`, `expand`, `HEADLINE`), `problem/measure.py`
  from library graders (`raft grader add`), `problem/reference.json` with page references, and `checker/`
  (`NOTE.md`, `answer.py`, first attacks). Prefer a study that runs on a laptop in minutes; say in `NOTE.md` what
  was cut to get there. Done when `raft validate` passes.
- `raft attack --study <s>` → `roles/checker-attacker.md`: a different agent. Try to pass the checker without doing
  the paper's work: hard-code numbers, exploit loose tolerances, skip the claim's real condition, satisfy shape
  checks with junk, exploit cases the grader never looks at. Write each try to `checker/attacks/`, run
  `raft validate`, record it in `review.json`. Never edit `problem/`.

`raft prepare` drives this headless with the bench's adapters (`raft/agents.py`), in the repository itself, not a
blind workspace:

1. `raft new --arxiv` (skipped with `--study` for an existing draft).
2. Extractor agent → `raft extract --validate` must pass (one retry with the errors appended).
3. Builder agent → `raft validate` must pass (one retry).
4. Attacker agent (`--attacker`, default: the same tool in a fresh session; a different tool is recommended and
   recorded) → `raft validate`. If any attack got through, the builder gets the failing attacks and fixes
   `problem/`, then the attacker goes again. At most 3 rounds.
5. Stops and prints the approval command. It never approves. Every agent session's transcript is kept in
   `checker/transcripts/` (trimmed to 2 MB each, same rule as bench).

Each agent call has a timeout (default 45 min) and the same process-group kill as bench. A failed step stops
`prepare` with what to do next; rerunning `prepare --study <s>` resumes at the first step whose gate fails.

## 6. Approval: `raft approve --study <s>`

- One screen: `NOTE.md`, the validate result, each attack round (tried / blocked), each skipped mutation with its
  reason, and which agents built and attacked.
- Requires an interactive terminal (`stdin` is a TTY) and the owner typing the study id. Agents run commands
  without a TTY, so they cannot approve; this is a lock, not only a rule. There is no `--yes`.
- Writes `studies/<s>/checker-approval.json` (schema `checker-approval.schema.json`): the hash of `problem/` (same
  tracked-files hash as bench), the hash of `checker/`, approver (git `user.name` and `user.email`), time, builder
  and attacker agents, rounds, and `attacks: null` when approved with `--without-attacks`.
- `--without-attacks` exists for the two existing studies only (made before the gate) and is shown as such on the
  site.
- If `raft validate` fails, approval is refused.

## 7. The gate

- `raft run`, `raft bench` and `raft implement` refuse a study whose `checker-approval.json` is missing or whose
  hashes no longer match `problem/` and `checker/`, with one line saying what changed and to rerun attack and
  approval.
- `raft repro` and `raft bench --verify` do not check approval: they recheck history.
- After this ships the owner runs `raft approve --study transduced-lm-2026 --without-attacks` once (reading the
  screen first). Ghia stays a draft.
- The site and flow view show the checker state per study: approved (with rounds), approved before attacks, or
  not approved.

## Honesty rules

- A checker the agents built is never trusted without the owner's approval, and the approval screen shows every
  hole that was tried and every check that was skipped.
- `NOTE.md` says what the study does **not** test; the site shows it next to the results.
- Failed attacks and the rounds it took are published with the study.
- Never lower a tolerance to make a positive control pass; the builder says so in `NOTE.md` instead.

## Testing

- Intake: recorded OAI-PMH XML and a tiny PDF served by a fake opener (no network in tests): fields, id slug,
  licence, refusal on existing id, unknown id, non-PDF, size limit, 3 s spacing between requests.
- Graders: each grader against hand-made honest and cheating inputs; the two existing studies' numbers reproduced
  by the library graders in tests (without touching their `problem/`).
- Validate: tiny study with an `answer.py`; each mutation fails; a deliberately weak `measure.py` (no shape check,
  loose tolerance) is caught by named mutations and by an attack; a stale grader copy is reported.
- Prepare: fake agents (`--agent command`) that write good, broken or slow outputs: resume after failure, the 3-round
  stop, transcripts kept, never approves.
- Approve: refuses without a TTY, refuses on failing validate, writes the record; the gate blocks run/bench/implement
  after a change in `problem/` or `checker/`.
- One real `prepare` by the owner on a laptop-sized arXiv paper before calling it done.

## Out of scope

*Discover*, `raft auto`, the *overview* report and cross-study comparison (next specs, in that order); converting
the existing studies to library graders; containers; GPU studies.

# Gaps: ask the authors for what the paper leaves out

**Date:** 2026-10-16 · **Status:** draft, awaiting owner review · **Repo:** paper-raft

## Purpose

What limits Paper Raft's results most is missing details in the papers, more than the agents. The extractor already
flags every detail a paper leaves out (`"missing": true` in `extraction.json`, with the `assumption` we used instead),
and then nothing happens with it. In the transduced-LM study, 13 of 71 items are missing. Two of them, the unnamed DNA
corpus and the unlisted targets, are why the study checks the paper's claims and not its Table 2 numbers.

`raft gaps` turns those items into a short, page-referenced list of questions for the authors. The owner sends it.
Paper Raft never contacts anyone. It also records each answer with its source. Published answers can then feed a
stricter version of the study, which goes through the usual checker attack and approval.

What it's for:

- **researchers** get reproductions graded against the paper's actual numbers, not only its claims;
- **authors** get an exact list of what readers can't reproduce, each item with its page;
- **the project** gets a public record that grows study by study ("the authors answered; it now checks Table 2").

## Command

```
uv run raft gaps --study transduced-lm-2026                 # write/refresh gaps.json, print the list
uv run raft gaps --study transduced-lm-2026 --letter        # print a letter to the authors (blocking questions first)
uv run raft gaps --study transduced-lm-2026 --mark-asked    # record that the open questions were sent today
uv run raft gaps --study transduced-lm-2026 --answer dna-targets --from answer.txt \
    --by "Tim Vieira" --source "email, 2026-10-20" --publish
uv run raft gaps --study transduced-lm-2026 --answer rng-and-seeds --by "…" --source "…" --private
uv run raft gaps --study transduced-lm-2026 --decline dna-training-corpus --by "…" --source "…"
uv run raft gaps                                            # every study: open / asked / answered counts
uv run raft gaps --validate --all-studies                   # CI
```

## 1. The gaps file

`studies/<study>/gaps.json` is committed and public, since every question only quotes or paraphrases the paper. Its
schema is `raft/contracts/gaps.schema.json`.

```json
{
  "study": "transduced-lm-2026",
  "gaps": [
    {
      "id": "dna-targets",                       // the extraction item id
      "page": 14,
      "kind": "parameter",
      "question": "The amino-acid targets of the DNA experiments are not listed … Which strings did you use?",
      "assumption": "Use setup's three length-10 targets …",   // copied from extraction: what we do today
      "blocks": "Grading against Table 2's numbers (today only the paper's claims are checked).",
      "status": "answered",                      // open | asked | answered | answered_private | declined | resolved
      "asked_on": "2026-10-17",
      "answer": {"text": "…", "by": "Tim Vieira", "source": "email, 2026-10-20", "recorded_on": "2026-10-21"}
    }
  ]
}
```

- **Building it.** `raft gaps --study S` creates one entry per missing extraction item. The question comes from the
  item's `text` (the extractor already writes it as "the paper does not say …") followed by one direct question:
  "What did you use?" for a parameter, "How is this done?" for a method or equation, and "What happens here?" for a
  boundary condition. It ends with "We assumed: <assumption>. Is that right?" The command is deterministic, with no
  agent and nothing to approve.
- **Rerunning it.** A rerun keeps every status, date and answer. A newly missing item is added as `open`. An entry
  whose item is no longer missing in the extraction becomes `resolved` (the extraction itself now answers it), and its
  history is kept.
- **`blocks`** (optional) names the check the missing detail keeps out of the grader. Gaps with `blocks` are the ones
  worth an author's time, and they go first. They're filled in two ways:
  - The checker builder fills them for new studies. `roles/checker-builder.md` gains one line: for each missing item
    that kept a check out of `problem/`, add its `blocks` line with `raft gaps --study S --blocks <id> "<check>"`.
    That flag is the only one agents may use.
  - For existing studies, the owner or a maintainer fills them the same way.
- **Validation.** `raft gaps --validate` checks the schema, that every id is a missing (or once missing) extraction
  item, that answered entries carry `by`, `source` and `recorded_on`, and that `answered_private` entries carry no
  text.

## 2. The letter

`raft gaps --letter` prints plain text for the owner to paste into an email. It is addressed to the authors by name
from `paper.yaml`. Paper Raft never looks up an email address.

- **Opening.** Two sentences on what Paper Raft did with the paper, with links to the study page and its flow on the
  site.
- **"What blocks a stricter check."** The open gaps with `blocks`, each with its page, question, our assumption and
  what an answer unlocks.
- **"Smaller details, if you have time."** The rest. When there are more than 8, the letter lists the first 8 and
  links to the full list on the site.
- **Closing.** One line: "With your permission we'll publish your answers in the study, credited to you. If you'd
  rather not, we'll use them only to check our own assumptions." The answer is the author's to give, and the owner
  records which it was.

`--letter` changes nothing. `--mark-asked` sets `asked` and today's date on every open gap the letter included.

## 3. Answers

Answers are recorded by the owner, in their own terminal. `--answer`, `--decline` and `--mark-asked` refuse to run
inside an agent session, using the same check as `raft approve` (`AGENT_ENV`). An answer is a claim by a person, and
an agent must never be able to invent one.

- **`--publish`:** the author agreed to publication. The text from `--from <file>` is stored in `gaps.json`, and the
  status becomes `answered`.
- **`--private`:** the author answered but didn't agree to publication. The status becomes `answered_private`, and only
  `by`, `source` and the date are stored, never the text. A private answer can't feed a check, because a check nobody
  else can rerun from the repository isn't reproducible. The owner can still use it to see whether our assumption was
  right, and may write that down in their own words with `--note "our assumption matched"`, which is published.
- **`--decline`:** the author can't or won't share it, for example a private corpus. That is recorded too, and it is
  worth knowing.

## 4. From an answer to a stricter check

The `problem/` folder of a study with runs never changes, and that rule stands. Answers that change grading go into a
**new version of the study**:

```
uv run raft new --from transduced-lm-2026 --id transduced-lm-2026-table2
uv run raft prepare --study transduced-lm-2026-table2 --agent claude-code --attacker codex --watch
```

- `raft new --from S` copies `paper.yaml` (adding `version_of: S`), with `draft: true` as usual. It does not copy the
  `problem/` or `checker/` folders.
- The extractor brief for the new version gets the published answers from S's `gaps.json`. An answered item is
  re-extracted as not missing. It gains `"answer": "gaps.json#<id>"` in place of a quote (a new optional field in the
  extraction schema), and it keeps the page of the gap it answers.
- From there it is the ordinary route: build the checker, attack it, and wait for the owner's approval. The author's
  answer is input to the checker. It never counts as a result.
- The old study keeps its results, which stay true against the checker they were graded with. The site shows the new
  version as "stricter version of S, using N author answers" and links both ways.

## 5. Where it shows

- **Site:** each study page gets a **Gaps** section showing "13 details the paper leaves out · 2 asked · 1 answered".
  It lists each gap with its page, status and our assumption, plus the answer and its credit when it's published.
  Declined and private answers show their status only.
- **`raft prepare`:** when it reaches the approval step, it also prints `N gaps (K block a check): uv run raft gaps
  --study S`.
- **`AGENTS.md`:** one table row for `--blocks`, and one rule: never record, edit or invent an author's answer.

## Honesty rules

- Questions only describe what the paper says and doesn't say, with its page. They never criticise it.
- An answer is stored exactly as given and credited with its source. Only answers the author agreed to publish are
  published or used in grading.
- Paper Raft never sends anything and never looks up contact details. The owner sends every letter.

## Testing

- **Generation:** from the transduced-LM extraction, 13 entries with the right ids, pages and question endings. The
  file validates against the schema. A rerun keeps statuses and answers, adds a new missing item, and marks a no
  longer missing item `resolved`.
- **Letter:** blocking gaps come before the rest, the cap of 8 holds, the author names come from `paper.yaml`, and
  the letter contains no email addresses. `--letter` leaves the file unchanged.
- **Answers:** `--publish` stores the text; `--private` stores none; `--decline` and `--mark-asked` set their statuses;
  an unknown id is refused. All four refuse with `CLAUDECODE=1` set, while `--blocks` works there.
- **New version:** `raft new --from` copies `paper.yaml` with `version_of` and no `problem/`. The extractor brief
  includes published answers and leaves out private ones. The extraction schema accepts `answer` in place of a quote.
- **Site:** the Gaps section renders the counts and hides private text (a check in `scripts/check_flow.mjs` style).
  CI runs `raft gaps --validate --all-studies`.
- **First real use:** the owner fills in `blocks` for the transduced-LM study's corpus, targets, M grid and seeds, runs
  `--letter`, and decides whether to send it.

## Out of scope

Sending email, looking up author contacts, tracking replies automatically, Paperraft (ai-radar) showing gaps (a
later `flow-export` field), and agents drafting answers or follow-up questions.

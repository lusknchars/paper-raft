# Paper Raft

Agents reproduce research papers in a controlled environment, and every result shows how far to trust it.

A paper goes in. Out come independent implementations of its methods, measured with the same tools against the paper's own numbers, checked by a separate reviewer, and browsable in a static site where every number links to its code, its run and its page in the paper.

> **Status (October 2026):** one study published. Five independent agents reproduced the claims of *Stochastic Estimation of Transduced Language Models* (arXiv:2608.27428): all five methods pass and were verified by separate reviewers. A second study, Ghia 1982, is parked as a draft until its paper is available.

## Quickstart

```bash
uv sync
uv run raft repro --all-studies  # rerun every committed result and check it matches (about 5 minutes)
uv run raft compare              # builds site/; open site/index.html
```

No API key is needed to rerun and check results.

## Bench: bring your agent

How well does *your* agent setup reproduce a real paper? Point Claude Code or Codex, with your own model,
`AGENTS.md`/`CLAUDE.md` and skills, at a study:

    uv run raft bench --study transduced-lm-2026 --agent codex --setup ./my-setup --label "my AGENTS.md v2"
    uv run raft bench --study transduced-lm-2026 --agent claude-code --model opus
    uv run raft bench --study transduced-lm-2026 --agent codex --oss --model gpt-oss:20b   # local model via Ollama, no API key
    uv run raft bench --agent command --cmd "my-agent --task {brief}"                    # any other tool

The agent works in a blind workspace: the paper's extraction and the problem's interface, with no git history,
no existing solutions, and no grader or reference numbers in it. Paper Raft then grades its code with the
study's own measure in a copy the agent never touched, and writes an entry to `bench/results/<study>/`. Nothing the
agent says counts, only what its code does.

- `uv run raft bench --table` prints the scoreboard; the site has a **Bench** page.
- `uv run raft bench --verify` reruns every entry's code and checks its recorded numbers (CI does this on every PR).
- To join the scoreboard, read your transcript, then open a pull request with your entry folder.

Entries are graded automatically and not reviewed, and the ranking uses only the score: tokens, cost and time are
reported by the agent's tool and are not verified. Know the limits: the agent runs on your machine, where this
repository (its solutions and its grader) is on disk, and neither Claude Code nor Codex stops it reading files
outside the workspace. The brief tells it not to look, Claude Code runs without web tools, Codex runs in its
workspace sandbox, bench refuses to grade if the repository changed while the agent ran, and code that closely
matches the lab's own solver is marked copied. That last check is a tripwire, not a guarantee; maintainers read
every entry's code before merging it.

## Add a paper with one command

    uv run raft prepare --arxiv 2608.27428 --agent codex --attacker claude-code

Paper Raft fetches the record and PDF from arXiv (official endpoints only; the PDF stays in `papers/`, never
committed), has an agent extract the paper and build its checker (the grader, in `problem/`, plus a plain
`checker/NOTE.md` on what is and is not tested), and has a second agent attack that checker for up to three rounds.
Paper Raft itself checks every checker: the paper's own answer must pass (or fail, when the claim is about
estimation), broken copies of it (NaN, wrong shape, zeros, scaled, shuffled) must fail, and every saved attack must
fail. It stops at your approval:

    uv run raft approve --study <study>

which only works in your own terminal (not inside an agent session), where you read the note, the flags, the
checks and the attack rounds and type the study id. Commit the approval it writes: the gate only accepts a committed
one. This is a speed bump and a record, not a lock; `prepare` also stops if an agent touches the approval. After
that, `raft bench` and `raft run` work on the new paper, and they refuse to run if the checker changes until it is
attacked and approved again. Step by step instead: `raft new --arxiv`, `raft extract`, `raft build-checker`,
`raft validate`, `raft attack`, `raft approve`. Graders come from a small library: `raft grader add <checks|table|claims>`.

Before the first step, `prepare` checks your tools: installed, logged in, and able to run one shell command
(`uv run raft doctor --agent codex --try` does the same by hand; the result is remembered for 12 hours, and
`--no-try` skips it). If a tool fails during a step (a refused brief, a broken shell tool, an error), `prepare` says
so in plain words, stops without a wasted retry, and prints the command to continue, often with the other tool.
`uv run raft status --study <study>` shows where a study stands and what to run next. Saved transcripts never hold
your home path.

## Ask the authors

Papers leave things out. The extractor flags each missing detail with the assumption used instead, and `raft gaps`
turns them into questions for the authors, each with its page:

    uv run raft gaps --study transduced-lm-2026            # the list, kept in studies/<study>/gaps.json
    uv run raft gaps --study transduced-lm-2026 --letter   # a letter to paste into an email; blocking questions first

Paper Raft never sends anything or looks up an address: you send the letter (`--mark-asked` records that you did).
Record each reply in your own terminal: `--answer <id> --from reply.txt --by … --source … --publish` (or `--private`,
which keeps no text), or `--decline <id>`. Agents can't. Only answers the authors agreed to publish are kept and used:
they go into a stricter version of the study, `uv run raft new --from <study> --id <new-id>`, which is built, attacked
and approved like any other, while the old study keeps its results. Each study on the site has a **Gaps** page.

## Flow view

Every study is also drawn as a chain: the paper, the items extracted from it, the methods built from those items,
and the runs, with a percentage at each link and the results in plain terms (bias in σ, how much the error falls as
the budget grows, the exact-case error). Open it from any study's **flow** link on the site.

While you run a study, keep its flow open on your machine:

    uv run raft watch --study transduced-lm-2026

It serves on 127.0.0.1 only and shows each run's progress as it happens; a method can report progress inside a
run by taking `solve(setup, progress)` and calling `progress(fraction)`. `raft flow-export --study <s> --out <file>`
writes a committed study's flow for other sites, such as Paperraft. Without `--study`, `raft watch` shows live
sessions instead (see below).

### Watch it live

Add `--watch` to `raft prepare` or `raft bench` and a local page opens while it runs:

    uv run raft prepare --arxiv 2608.04234 --agent claude-code --attacker codex --watch

It shows the paper and the agents, each step as a node in a glowing network, the percentage (finished steps out of
all steps, never a guess inside a step), what the agent is doing right now in its own words, any errors from the
tool, and results so far: checker holes and attack rounds for `prepare`, passed runs and score for `bench`.
`uv run raft watch` shows every session on this machine. It all stays on 127.0.0.1; session files are in
`.raft/live/` and are never committed.

## How it works

| Stage | Who | Writes | Gate |
|---|---|---|---|
| Extract | extractor agent | `extraction.json`: methods, equations, settings, each with a page; gaps flagged `missing` | `raft extract --validate` |
| Implement | one agent per method, in parallel | `methods/<name>/`, and nothing else | guard test: no peeking at the reference |
| Run | `raft run` | `runs/<id>/manifest.json` + `results.json` | `raft repro` reruns from a clean checkout |
| Review | a different agent per method | `reviews/<name>.json` | `raft review --validate` |
| Compare | `raft compare` | `site/` | |

Working with many papers: `uv run raft new <id> --title … --doi …` starts a study, and `uv run raft repro --all-studies` reruns every committed result in every study. CI does the same on every push.

A result shows as **verified** only when it is within tolerance, a reviewer verified the exact solver commit that produced it, and the run was made from committed code. Everything else shows as **unverified** or **failed**, and failures are published too.

## Studies

**Stochastic Estimation of Transduced Language Models** (`studies/transduced-lm-2026/`). Prefix probabilities of amino-acid strings under a DNA language model passed through the genetic code. Five estimators, one agent each: beam summing, `smc_simple`, `smc_rb`, `beam_swor` and `beam_swor_adaptive`. Each is graded against the claim the paper makes for it: exactness in the Appendix E worst case, and unbiasedness with error falling as the particle count M grows on a DNA bigram. The paper does not name its DNA corpus or list its targets, so this study checks the paper's claims, not its Table 2 numbers. The text and GPT-2 experiments are not covered. The paper is from the [Paperraft](https://paperaft.vercel.app/papers/2608.27428/) collection. Values and quotes are reproduced with attribution: Snæbjarnarson, V., Kiegeland, S., de Prada Corral, M., Cotterell, R., & Vieira, T. (2026), arXiv:2608.27428, licensed CC BY-SA 4.0. The paper itself is not in this repository.

**Ghia, Ghia & Shin (1982)** (`studies/ghia-1982/`, draft). Lid-driven cavity flow at Re = 100, scored against the paper's centreline velocity tables (max error ≤ 0.01), with three planned methods: stream-function/vorticity, projection, and lattice Boltzmann. It is parked until the paper is available for extraction. The reference values are reproduced with attribution: Ghia, U., Ghia, K. N., & Shin, C. T. (1982), *J. Comput. Phys.* 48, 387–411, doi:10.1016/0021-9991(82)90058-4.

## Using it with your agent tool

Agents that open this repository read [AGENTS.md](AGENTS.md) (Claude Code reads it through `CLAUDE.md`): which brief to print for each job, the rules, and the checks to run before finishing. The roles in `roles/` are plain markdown, and `raft extract | implement <m> | review <m>` prints them filled in for a study, so any tool can follow them. Claude Code users get ready-made agents and a `reproduce-paper` skill in `.claude/` (source: `adapters/claude-code/`). To compare setups, use `raft bench` (above).

## Add a study or a method

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Apache-2.0. See [LICENSE](LICENSE). To cite Paper Raft, use [CITATION.cff](CITATION.cff).

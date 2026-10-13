# Paper Raft

Agents reproduce research papers in a controlled environment, and every result shows how far to trust it.

A paper goes in. Out come independent implementations of its methods, measured with the same tools against the paper's own numbers, checked by a separate reviewer, and browsable in a static site where every number links to its code, its run and its page in the paper.

![Comparison view](docs/screenshots/site-comparison.png)

## Quickstart

```bash
uv sync
uv run raft run --all --re 100   # every method, every grid, Re = 100
uv run raft compare              # builds site/; open site/index.html
```

No API key is needed to rerun and check results.

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

## First study: Ghia, Ghia & Shin (1982)

Lid-driven cavity flow at Re = 100, scored against the paper's centreline velocity tables (max error ≤ 0.01), using three independent methods: stream-function/vorticity, projection, and lattice Boltzmann. The reference values are reproduced with attribution: Ghia, U., Ghia, K. N., & Shin, C. T. (1982), *J. Comput. Phys.* 48, 387–411, doi:10.1016/0021-9991(82)90058-4. The paper itself is not in this repository.

## Using it with your agent tool

The roles in `roles/` are plain markdown, and `raft extract | implement <m> | review <m>` prints them filled in for a study, so any tool can follow them. Claude Code users get ready-made agents and a `reproduce-paper` skill in `.claude/` (source: `adapters/claude-code/`).

## Add a study or a method

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Apache-2.0. See [LICENSE](LICENSE). To cite Paper Raft, use [CITATION.cff](CITATION.cff).

---
name: raft-implementer
description: Implements one method of a Paper Raft study inside methods/<name>/ only, from extraction.json and the shared setup. Dispatch one per method, in parallel worktrees.
tools: Read, Write, Edit, Bash, Grep, Glob
---
Run `uv run raft implement <method> --study <study>` and follow the brief it prints exactly. Never open the shared measurement module, the reference data, runs/ or reviews/. Report the per-grid errors honestly, failures included.

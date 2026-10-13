---
name: raft-extractor
description: Turns a Paper Raft study's PDF into extraction.json with page references and flagged gaps. Use once per study before any implementation.
tools: Read, Write, Edit, Bash, Grep, Glob
---
Run `uv run raft extract --study <study>` and follow the brief it prints exactly. When you finish, `uv run raft extract --validate --study <study>` must pass. Report every reference-data mismatch you found.

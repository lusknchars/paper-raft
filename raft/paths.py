"""Find the Paper Raft checkout and its studies."""
import os
from pathlib import Path

import yaml


def repo_root() -> Path:
    env = os.environ.get("RAFT_ROOT")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / "studies").is_dir() and (d / "pyproject.toml").is_file():
            return d
    raise SystemExit("raft: run this inside a Paper Raft checkout (no studies/ folder found), or set RAFT_ROOT")


def _is_draft(paper: Path) -> bool:
    return bool((yaml.safe_load(paper.read_text()) or {}).get("draft"))


def studies(root: Path, include_drafts: bool = False) -> list[str]:
    base = root / "studies"
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir()
                  if (d / "paper.yaml").is_file() and (include_drafts or not _is_draft(d / "paper.yaml")))


def resolve_study(root: Path, name: str | None) -> str:
    if name:
        have = studies(root, include_drafts=True)
        if name not in have:
            raise SystemExit(f"raft: unknown study {name!r} (have: {', '.join(have) or 'none'})")
        return name
    have = studies(root)
    if len(have) == 1:
        return have[0]
    raise SystemExit(f"raft: pass --study or --all-studies (have: {', '.join(have) or 'none'})")

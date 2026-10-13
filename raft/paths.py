"""Find the Paper Raft checkout and its studies."""
import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("RAFT_ROOT")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / "studies").is_dir() and (d / "pyproject.toml").is_file():
            return d
    raise SystemExit("raft: run this inside a Paper Raft checkout (no studies/ folder found), or set RAFT_ROOT")


def studies(root: Path) -> list[str]:
    base = root / "studies"
    return sorted(d.name for d in base.iterdir() if (d / "paper.yaml").is_file()) if base.is_dir() else []


def resolve_study(root: Path, name: str | None) -> str:
    have = studies(root)
    if name:
        if name not in have:
            raise SystemExit(f"raft: unknown study {name!r} (have: {', '.join(have) or 'none'})")
        return name
    if len(have) == 1:
        return have[0]
    raise SystemExit(f"raft: pass --study (have: {', '.join(have) or 'none'})")

"""The grader library. Studies copy a grader into problem/graders/ (`raft grader add`); copies never change silently.

A copy starts with `# raft-grader <name> v<version> sha256:<hash of the library file>`, followed by the library
file verbatim. `status` reports copies that were edited or are behind the library.
"""
import hashlib
import re
from importlib.resources import files
from pathlib import Path

NAMES = ("checks", "table", "claims")
HEADER = re.compile(r"^# raft-grader (\w+) v(\d+) sha256:([0-9a-f]{64})$")


def library_text(name: str) -> str:
    if name not in NAMES:
        raise SystemExit(f"raft: no grader named {name!r} (have: {', '.join(NAMES)})")
    return files("raft.graders").joinpath(f"{name}.py").read_text()


def version(name: str) -> int:
    return int(re.search(r"^VERSION = (\d+)$", library_text(name), re.M).group(1))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def add(study_dir: Path, name: str, force: bool = False) -> Path:
    text = library_text(name)
    d = Path(study_dir) / "problem" / "graders"
    target = d / f"{name}.py"
    if target.exists() and not force:
        raise SystemExit(f"raft: {target} already exists; pass --force to replace it with the library's version")
    d.mkdir(parents=True, exist_ok=True)
    init = d / "__init__.py"
    if not init.exists():
        init.write_text('"""Graders copied from raft/graders (`raft grader add`). Do not edit; copy again instead."""\n')
    target.write_text(f"# raft-grader {name} v{version(name)} sha256:{_sha(text)}\n{text}")
    return target


def status(study_dir: Path) -> list[str]:
    problems = []
    d = Path(study_dir) / "problem" / "graders"
    for f in sorted(d.glob("*.py")) if d.is_dir() else []:
        if f.name == "__init__.py":
            continue
        rel = f"problem/graders/{f.name}"
        head, _, body = f.read_text().partition("\n")
        m = HEADER.match(head)
        if not m:
            problems.append(f"{rel}: no raft-grader header; copy it with `raft grader add`")
            continue
        name, ver, sha = m.group(1), int(m.group(2)), m.group(3)
        if name not in NAMES or f.stem != name:
            problems.append(f"{rel}: unknown grader {name!r}")
        elif _sha(body) != sha:
            problems.append(f"{rel}: edited after copying; copy it again with --force")
        elif ver < version(name):
            problems.append(f"{rel}: behind the library (v{ver} → v{version(name)}); copy it again with --force")
    return problems

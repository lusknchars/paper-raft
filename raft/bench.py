"""raft bench: hand a study to someone's agent in a blind workspace, grade its code out of its reach, write an entry.

The workspace holds only the study's paper.yaml, extraction.json, problem/setup.py, an empty methods/ folder, the
PDF if it is here, and the entrant's setup folder, with a fresh git history. The yardstick (measure.py,
reference.json), the lab's methods, runs and reviews are not in it. Grading copies the agent's method folders into
a fresh copy of the study's problem/ and runs them with the same runner `raft run` uses. Nothing the agent says
counts.
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from . import briefs, provenance

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".git")


def _study_dir(root: Path, study: str) -> Path:
    return Path(root) / "studies" / study


def _paper(sd: Path) -> dict:
    return yaml.safe_load((sd / "paper.yaml").read_text()) or {}


def problem_hash(sd: Path) -> str:
    return provenance.inputs_hash({}, Path(sd) / "problem")


def require_clean(root: Path, study: str) -> None:
    sd = _study_dir(root, study)
    if provenance.is_dirty(root, [sd / "problem", sd / "paper.yaml", sd / "extraction.json"]):
        raise SystemExit(f"raft: studies/{study} has uncommitted changes in problem/, paper.yaml or "
                         "extraction.json; commit them first")


def _setup_files(setup: Path) -> list[Path]:
    return sorted(p for p in setup.rglob("*")
                  if p.is_file() and not {".git", "__pycache__"} & set(p.relative_to(setup).parts))


def setup_info(setup: Path | None) -> dict | None:
    if setup is None:
        return None
    setup = Path(setup)
    h = hashlib.sha256()
    files = _setup_files(setup)
    for p in files:
        h.update(p.relative_to(setup).as_posix().encode() + b"\0")
        h.update(p.read_bytes())
    return {"hash": h.hexdigest(), "files": [p.relative_to(setup).as_posix() for p in files][:200]}


def make_workspace(root: Path, study: str, ws: Path, setup: Path | None) -> Path:
    root, ws = Path(root), Path(ws)
    if setup is not None:
        setup = Path(setup)
        if not setup.is_dir():
            raise SystemExit(f"raft: --setup {setup} is not a folder")
        if (setup / "studies").exists():
            raise SystemExit("raft: the --setup folder must not contain studies/; it is copied onto the workspace root")
    sd = _study_dir(root, study)
    wsd = ws / "studies" / study
    (wsd / "problem").mkdir(parents=True)
    (wsd / "methods").mkdir()
    shutil.copyfile(sd / "paper.yaml", wsd / "paper.yaml")
    if (sd / "extraction.json").is_file():
        shutil.copyfile(sd / "extraction.json", wsd / "extraction.json")
    shutil.copyfile(sd / "problem" / "setup.py", wsd / "problem" / "setup.py")
    pdf = _paper(sd).get("pdf")
    if pdf and not Path(pdf).is_absolute() and ".." not in Path(pdf).parts and (root / pdf).is_file():
        (ws / pdf).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / pdf, ws / pdf)
    if setup is not None:
        shutil.copytree(setup, ws, dirs_exist_ok=True, ignore=_IGNORE)
    for args in (("init", "-q", "-b", "main"), ("add", "-A"),
                 ("-c", "user.name=raft-bench", "-c", "user.email=bench@paper-raft.invalid",
                  "-c", "commit.gpgsign=false", "commit", "-qm", "workspace")):
        subprocess.run(["git", *args], cwd=ws, check=True, capture_output=True)
    return ws


def render_brief(root: Path, study: str, method: str) -> str:
    return briefs.render(Path(root), "bench-implementer", study, method).replace("{{python}}", sys.executable)

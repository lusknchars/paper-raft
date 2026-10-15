"""A tiny, fast study used to test the generic machinery without any fluids."""
import json
import subprocess
from pathlib import Path

import pytest

SETUP = '''
from dataclasses import dataclass

HEADLINE = {"n": 8}


@dataclass(frozen=True)
class Setup:
    n: int


def make_setup(params):
    if int(params["n"]) < 2:
        raise ValueError("n must be at least 2")
    return Setup(n=int(params["n"]))


def expand(params):
    ns = [params["n"]] if "n" in params else [4, 8]
    out = [{"n": n} for n in ns]
    for c in out:
        make_setup(c)
    return out
'''

MEASURE = '''
import numpy as np


def measure(setup, fields, reference):
    y = np.asarray(fields["y"], dtype=float)
    if y.shape != (setup.n,):
        raise ValueError(f"y has shape {y.shape}, expected ({setup.n},)")
    if not np.all(np.isfinite(y)):
        raise ValueError("non-finite values in y")
    x = np.linspace(0, 1, setup.n)
    ref = x**2
    err = float(np.max(np.abs(y - ref)))
    pairs = lambda a, b: [[float(p), float(q)] for p, q in zip(a, b)]
    return {"samples": {"y": pairs(x, y)}, "reference_samples": {"y": pairs(x, ref)},
            "errors": {"y_max": err}, "tolerance": reference["tolerance"],
            "pass": bool(err <= reference["tolerance"])}
'''

EXACT = '''
import numpy as np


def solve(setup):
    x = np.linspace(0, 1, setup.n)
    return {"y": x**2}
'''


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def commit_all(root: Path, msg="commit"):
    git(root, "add", "-A")
    git(root, "commit", "-qm", msg)


def add_method(study_dir: Path, name: str, code: str, implements=("tiny-method",)):
    d = study_dir / "methods" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "solver.py").write_text(code)
    (d / "method.json").write_text(json.dumps(
        {"name": name, "implements": list(implements), "author_agent": f"test:implementer#{name}"}))
    return d


def make_tiny_study(root: Path, git_repo: bool = False) -> Path:
    (root / "pyproject.toml").write_text("[project]\nname = 'tiny'\n")
    (root / ".gitignore").write_text("__pycache__/\n")
    (root / "roles").mkdir()
    for role in ("extractor", "implementer", "reviewer"):
        (root / "roles" / f"{role}.md").write_text(f"# {role} for {{{{study}}}} {{{{method}}}} at {{{{study_dir}}}} pdf {{{{pdf}}}}\n")
    (root / "roles" / "bench-implementer.md").write_text(
        "# bench {{study}} {{method}} at {{study_dir}} python {{python}}\n")
    sd = root / "studies" / "tiny"
    (sd / "problem").mkdir(parents=True)
    (sd / "paper.yaml").write_text("title: Tiny\ncitation: Tiny test study\ndoi: 10.0000/tiny\npdf: papers/tiny.pdf\n")
    (sd / "problem" / "setup.py").write_text(SETUP)
    (sd / "problem" / "measure.py").write_text(MEASURE)
    (sd / "problem" / "reference.json").write_text(json.dumps(
        {"citation": "Tiny test study", "doi": "10.0000/tiny", "tolerance": 1e-9, "cases": {}}))
    (sd / "extraction.json").write_text(json.dumps({"study": "tiny", "items": [
        {"id": "tiny-method", "kind": "method", "text": "square x", "page": 1, "quote": "y = x^2", "missing": False}]}))
    add_method(sd, "exact", EXACT)
    if git_repo:
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "t@example.com")
        git(root, "config", "user.name", "t")
        commit_all(root, "tiny study")
    return sd


@pytest.fixture
def tiny_study(tmp_path):
    return make_tiny_study(tmp_path)


@pytest.fixture
def tiny_git_study(tmp_path):
    return make_tiny_study(tmp_path, git_repo=True)

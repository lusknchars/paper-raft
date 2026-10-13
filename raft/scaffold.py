"""Start a new study folder. It stays a draft (skipped by --all-studies and the site) until filled in."""
import json
import re
from pathlib import Path

import yaml

SETUP = '''"""Shared problem setup for {study_id}. Read-only for implementers.

Describe here, precisely, what solve(setup) receives and what it must return.
"""
RUN_MATRIX = {{}}
HEADLINE = {{}}


def make_setup(params: dict):
    raise NotImplementedError("define the experiment's parameters in studies/{study_id}/problem/setup.py")


def expand(params: dict) -> list[dict]:
    raise NotImplementedError("list the runs to make in studies/{study_id}/problem/setup.py")
'''

MEASURE = '''"""Shared measurement for {study_id}. Read-only; methods never import or read it."""


def measure(setup, fields, reference: dict) -> dict:
    raise NotImplementedError("compare fields with reference.json in studies/{study_id}/problem/measure.py")
'''


def new_study(root: Path, study_id: str, title: str, doi: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", study_id):
        raise SystemExit(f"raft: study id must be lowercase letters, digits and hyphens, got {study_id!r}")
    d = root / "studies" / study_id
    if d.exists():
        raise SystemExit(f"raft: study {study_id!r} already exists at {d}")
    (d / "problem").mkdir(parents=True)
    paper = {"title": title, "authors": [], "citation": "", "doi": doi,
             "pdf": f"papers/{study_id}.pdf", "experiment": "", "draft": True}
    (d / "paper.yaml").write_text(yaml.safe_dump(paper, sort_keys=False, allow_unicode=True))
    (d / "problem" / "setup.py").write_text(SETUP.format(study_id=study_id))
    (d / "problem" / "measure.py").write_text(MEASURE.format(study_id=study_id))
    (d / "problem" / "reference.json").write_text(json.dumps(
        {"citation": title, "doi": doi, "tolerance": 0.01, "cases": {}}, indent=2) + "\n")
    return d

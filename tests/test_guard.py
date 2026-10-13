from pathlib import Path

import pytest

from raft import guard

ROOT = Path(__file__).resolve().parents[1]
REAL_METHODS = sorted(p for p in ROOT.glob("studies/*/methods/*") if p.is_dir())


def write(tmp_path, code):
    (tmp_path / "solver.py").write_text(code)
    return tmp_path


def test_clean_method(tmp_path):
    assert guard.scan_method(write(tmp_path, '"""Uses the reference velocity of the lid."""\nimport numpy as np\n')) == []


@pytest.mark.parametrize("code, hit", [
    ('import json\nref = json.load(open("../../problem/reference.json"))\n', "reference.json"),
    ("from measure import measure\n", "measure"),
    ("import importlib\nm = importlib.import_module('measure')\n", "measure"),
    ('p = "problem/setup.py"\n', "problem/"),
    ('runs = "../runs/projection-grid33-re100"\n', "runs/"),
])
def test_forbidden(tmp_path, code, hit):
    found = guard.scan_method(write(tmp_path, code))
    assert found and hit in found[0]


def test_syntax_error_is_reported(tmp_path):
    assert "syntax error" in guard.scan_method(write(tmp_path, "def (:\n"))[0]


@pytest.mark.parametrize("method_dir", REAL_METHODS, ids=[p.name for p in REAL_METHODS])
def test_real_methods_are_clean(method_dir):
    assert guard.scan_method(method_dir) == []

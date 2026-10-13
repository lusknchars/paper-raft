import json

import pytest

from conftest import add_method, commit_all
from raft import runner, schema


def test_run_id():
    assert runner.run_id("projection", {"re": 100, "grid": 129}) == "projection-grid129-re100"


def test_methods_and_expand(tiny_study):
    add_method(tiny_study, "zzz", "def solve(s):\n    return {}\n")
    assert runner.methods(tiny_study) == ["exact", "zzz"]
    assert runner.expand(tiny_study, {}) == [{"n": 4}, {"n": 8}]


def test_run_one_writes_valid_files(tiny_git_study):
    manifest, results = runner.run_one(tiny_git_study, "exact", {"n": 8}, timeout=60)
    out = tiny_git_study / "runs" / "exact-n8"
    assert schema.load("manifest", out / "manifest.json") == manifest
    assert schema.load("results", out / "results.json") == results
    assert results["status"] == "ok" and results["pass"] is True
    assert manifest["dirty"] is False and manifest["method_sha"] == manifest["git_sha"]
    assert manifest["repro_rtol"] == 1e-8 and manifest["seed"] == 0


@pytest.mark.parametrize("name, code, reason", [
    ("broken", "def solve(s):\n    raise RuntimeError('boom')\n", "RuntimeError: boom"),
    ("nan", "import numpy as np\ndef solve(s):\n    return {'y': np.full(s.n, np.nan)}\n", "measure: non-finite values in y"),
    ("shape", "import numpy as np\ndef solve(s):\n    return {'y': np.zeros(s.n + 1)}\n", "measure: y has shape"),
    ("none", "def solve(s):\n    return None\n", "measure: TypeError"),
    ("peeker", "import json\nREF = 'reference.json'\ndef solve(s):\n    return {}\n", "guard: solver.py:2: string mentions 'reference.json'"),
    ("tamper", "from pathlib import Path\ndef solve(s):\n    (Path(__file__).parents[2] / ('prob' + 'lem') / 'x.txt').write_text('x')\n"
               "    import numpy as np\n    return {'y': np.linspace(0, 1, s.n) ** 2}\n", "problem/ was modified during the run"),
])
def test_failures_are_written(tiny_study, name, code, reason):
    add_method(tiny_study, name, code)
    manifest, results = runner.run_one(tiny_study, name, {"n": 4}, timeout=60)
    assert results["status"] == "failed" and results["reason"].startswith(reason)
    saved = json.loads((tiny_study / "runs" / f"{name}-n4" / "results.json").read_text())
    assert saved["status"] == "failed"


def test_timeout(tiny_study):
    add_method(tiny_study, "slow", "import time\ndef solve(s):\n    time.sleep(30)\n")
    _, results = runner.run_one(tiny_study, "slow", {"n": 4}, timeout=1)
    assert results["reason"] == "timeout after 1s"


def test_unknown_method_is_a_clean_error(tiny_study):
    with pytest.raises(SystemExit, match="no method 'nope'"):
        runner.run_one(tiny_study, "nope", {"n": 4}, timeout=5)


def test_outside_git_is_dirty(tiny_study):
    manifest, _ = runner.run_one(tiny_study, "exact", {"n": 4}, timeout=60)
    assert manifest["git_sha"] == "unknown" and manifest["method_sha"] is None and manifest["dirty"] is True


def test_repro_passes_then_detects_changed_solver(tiny_git_study):
    runner.run_one(tiny_git_study, "exact", {"n": 4}, timeout=60)
    assert runner.repro(tiny_git_study, {}, timeout=60) == []
    solver = tiny_git_study / "methods" / "exact" / "solver.py"
    solver.write_text(solver.read_text().replace("x**2", "x**2 + 1e-3"))
    commit_all(tiny_git_study.parents[1], "change solver")
    problems = runner.repro(tiny_git_study, {}, timeout=60)
    assert any("solver changed since this run" in p for p in problems)
    assert any("results differ" in p for p in problems)


def test_repro_filters(tiny_git_study):
    runner.run_one(tiny_git_study, "exact", {"n": 4}, timeout=60)
    assert runner.repro(tiny_git_study, {"n": 99}, timeout=60) == ["no runs match the filter {'n': 99}"]

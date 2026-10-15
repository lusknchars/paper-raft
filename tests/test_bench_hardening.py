"""Final-review findings: forged entries, path leaks, stray files, tampering, ignored files, symlinks, ranking."""
import json
import os
import shlex
import shutil
import subprocess
import sys

import pytest
from conftest import commit_all

from raft import bench, benchboard

GOOD = ("import numpy as np\n\n\ndef solve(setup):\n"
        "    xs = np.array([i / (setup.n - 1) for i in range(setup.n)])\n    return {'y': xs * xs}\n")

AGENT = r'''
import os, sys
from pathlib import Path
brief, ws, method = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
d = ws / "studies" / "tiny" / "methods" / method
d.mkdir(parents=True, exist_ok=True)
(d / "solver.py").write_text(os.environ["AGENT_CODE"])
if os.environ.get("AGENT_BRIEF_COPY"):
    Path(os.environ["AGENT_BRIEF_COPY"]).write_text(brief.read_text())
if os.environ.get("AGENT_EXTRA") == "npy":
    (d / "answer.npy").write_bytes(b"precomputed")
if os.environ.get("AGENT_EXTRA") == "symlink":
    os.symlink(os.environ["AGENT_SECRET"], d / "notes.txt")
if os.environ.get("AGENT_TAMPER"):
    p = Path(os.environ["AGENT_TAMPER"])
    p.write_text(p.read_text() + "\n# tampered\n")
'''


@pytest.fixture
def run(tiny_git_study, tmp_path, monkeypatch):
    root = tiny_git_study.parents[1]
    agent = tmp_path / "agent.py"
    agent.write_text(AGENT)
    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(agent))} {{brief}} {{workspace}} {{method}}"
    monkeypatch.setenv("AGENT_CODE", GOOD)

    def go(**kw):
        return bench.run_bench(root, "tiny", "command", cmd=cmd, log=lambda s: None, **kw)
    return root, go


def test_verify_rejects_a_method_the_study_does_not_have(run):
    root, go = run
    d = go()
    e = json.loads((d / "entry.json").read_text())
    shutil.copytree(d / "methods" / "exact", d / "methods" / "exact-b")
    extra = json.loads(json.dumps(e["methods"][0]))
    extra["name"] = "exact-b"
    for r in extra["runs"]:
        r["run_id"] = r["run_id"].replace("exact", "exact-b", 1)
    e["methods"].append(extra)
    e["score"] = benchboard.score_counts(e["methods"])
    (d / "entry.json").write_text(json.dumps(e))
    problems = bench.verify(root, d, 60)
    assert any("exact-b is not a method of studies/tiny" in p for p in problems)


def test_verify_rejects_a_method_listed_twice(run):
    root, go = run
    d = go()
    e = json.loads((d / "entry.json").read_text())
    e["methods"].append(e["methods"][0])
    e["score"] = benchboard.score_counts(e["methods"])
    (d / "entry.json").write_text(json.dumps(e))
    assert any("exact is listed more than once" in p for p in bench.verify(root, d, 60))


def test_brief_does_not_name_the_repo(run, tmp_path, monkeypatch):
    root, go = run
    copy = tmp_path / "brief-copy.md"
    monkeypatch.setenv("AGENT_BRIEF_COPY", str(copy))
    go()
    text = copy.read_text()
    assert str(root) not in text and str(sys.executable) not in text
    assert text.strip().rsplit("python ", 1)[1].endswith("/bin/python")


def test_python_shim_runs_numpy_and_scipy(tmp_path):
    python = bench.python_shim(tmp_path / "bin")
    assert subprocess.run([str(python), "-c", "import numpy, scipy"], capture_output=True).returncode == 0


def test_only_code_files_are_graded_and_kept(run, monkeypatch):
    root, go = run
    monkeypatch.setenv("AGENT_EXTRA", "npy")
    monkeypatch.setenv("AGENT_CODE", "from pathlib import Path\n\n\ndef solve(setup):\n"
                       "    return {'y': (Path(__file__).parent / 'answer.npy').read_bytes()}\n")
    d = go()
    e = json.loads((d / "entry.json").read_text())
    assert e["score"]["passed"] == 0
    assert not (d / "methods" / "exact" / "answer.npy").exists()


def test_verify_rejects_stray_files_in_an_entry(run):
    root, go = run
    d = go()
    (d / "methods" / "exact" / "answer.npy").write_bytes(b"x")
    assert any("only .py files and method.json" in p for p in bench.verify(root, d, 60))


def test_symlinks_are_never_followed_or_kept(run, tmp_path, monkeypatch):
    root, go = run
    secret = tmp_path / "secret.txt"
    secret.write_text("SSH KEY")
    monkeypatch.setenv("AGENT_EXTRA", "symlink")
    monkeypatch.setenv("AGENT_SECRET", str(secret))
    d = go()
    kept = [p for p in d.rglob("*") if p.is_file()]
    assert all("SSH KEY" not in p.read_text(errors="replace") for p in kept)
    assert not (d / "methods" / "exact" / "notes.txt").exists()


def test_tampering_with_the_repo_during_the_run_is_refused(run, monkeypatch):
    root, go = run
    monkeypatch.setenv("AGENT_TAMPER", str(root / "studies" / "tiny" / "problem" / "measure.py"))
    with pytest.raises(SystemExit, match="changed while the agent ran"):
        go()


def test_ignored_files_do_not_change_the_problem_hash(tiny_git_study):
    root = tiny_git_study.parents[1]
    (root / ".gitignore").write_text("__pycache__/\n.DS_Store\n")
    commit_all(root, "ignore DS_Store")
    before = bench.problem_hash(tiny_git_study)
    (tiny_git_study / "problem" / ".DS_Store").write_bytes(b"finder")
    assert bench.problem_hash(tiny_git_study) == before


def test_ranking_ignores_self_reported_cost():
    from test_benchboard import entry, method
    lab = ["a"]
    pricey = entry("e1", methods=[method("a", [True], cost=9.0)])
    free = entry("e2", methods=[method("a", [True], cost=0.0)])
    assert [e["id"] for e in benchboard.ranked([free, pricey], lab)["full"]] == ["e1", "e2"]

from conftest import EXACT

from raft import bench

AGENT_EXACT = '''
import numpy as np


def solve(setup):
    xs = np.array([i / (setup.n - 1) for i in range(setup.n)])
    return {"y": xs * xs}
'''

WRONG = '''
import numpy as np


def solve(setup):
    return {"y": np.zeros(setup.n)}
'''

CHEAT = '''
import json


def solve(setup):
    return json.load(open("reference.json"))
'''


def code(tmp_path, method, text):
    d = tmp_path / "code" / method
    d.mkdir(parents=True)
    (d / "solver.py").write_text(text)
    return tmp_path / "code"


def test_good_code_passes_every_case(tiny_git_study, tmp_path):
    out = bench.grade(tiny_git_study.parents[1], "tiny", code(tmp_path, "exact", AGENT_EXACT), ["exact"], 60)
    (m,) = out
    assert m["name"] == "exact" and m["guard"] == [] and m["copied_from_lab"] is False
    assert [r["run_id"] for r in m["runs"]] == ["exact-n4", "exact-n8"]
    assert all(r["pass"] and r["status"] == "ok" and r["reason"] is None for r in m["runs"])
    assert set(m["runs"][0]["errors"]) == {"y_max"}


def test_wrong_code_is_recorded_as_failing(tiny_git_study, tmp_path):
    (m,) = bench.grade(tiny_git_study.parents[1], "tiny", code(tmp_path, "exact", WRONG), ["exact"], 60)
    assert [r["pass"] for r in m["runs"]] == [False, False]
    assert m["runs"][0]["status"] == "ok" and m["runs"][0]["errors"]["y_max"] > 0


def test_guard_catches_a_reader(tiny_git_study, tmp_path):
    (m,) = bench.grade(tiny_git_study.parents[1], "tiny", code(tmp_path, "exact", CHEAT), ["exact"], 60)
    assert m["guard"] and "reference.json" in m["guard"][0]
    assert all(r["status"] == "failed" and r["reason"].startswith("guard:") for r in m["runs"])


def test_missing_solver_fails_every_run(tiny_git_study, tmp_path):
    (tmp_path / "code").mkdir()
    (m,) = bench.grade(tiny_git_study.parents[1], "tiny", tmp_path / "code", ["exact"], 60)
    assert [r["reason"] for r in m["runs"]] == ["no solver.py", "no solver.py"]


def test_copy_of_lab_code_is_flagged(tiny_git_study, tmp_path):
    (m,) = bench.grade(tiny_git_study.parents[1], "tiny", code(tmp_path, "exact", EXACT), ["exact"], 60)
    assert m["copied_from_lab"] is True
    assert all(not r["pass"] and r["reason"] == "matches the lab's own code" for r in m["runs"])


def test_lab_overlap_scale(tiny_git_study, tmp_path):
    lab = tiny_git_study / "methods" / "exact"
    assert bench.lab_overlap(lab, lab) == 1.0
    assert bench.lab_overlap(lab, tmp_path / "missing") == 0.0
    assert bench.lab_overlap(lab, code(tmp_path, "exact", AGENT_EXACT) / "exact") < bench.OVERLAP


def test_grading_ignores_a_tampered_workspace_problem(tiny_git_study, tmp_path):
    codedir = code(tmp_path, "exact", AGENT_EXACT)
    # the agent's workspace copy of problem/ is not used: grading reads the repo's own problem/
    tampered = tmp_path / "ws" / "studies" / "tiny" / "problem"
    tampered.mkdir(parents=True)
    (tampered / "setup.py").write_text("raise SystemExit('tampered')\n")
    (m,) = bench.grade(tiny_git_study.parents[1], "tiny", codedir, ["exact"], 60)
    assert all(r["pass"] for r in m["runs"])

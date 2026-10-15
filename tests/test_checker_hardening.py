"""Final-review findings: junk reference answers, hidden flags, untracked files, forged approvals, silent attackers,
deleted evidence, unnamed measure errors."""
import json

import pytest
from conftest import commit_all

from raft import checker, prepare
from test_checker_approval import Tty, ready
from test_checker_validate import ANSWER, with_answer
from test_prepare import env, run  # noqa: F401  (env is a fixture)

ZERO_ANSWER = '''
import numpy as np

REFERENCE_ANSWER_PASSES = False


def reference_answer(setup):
    return {"y": np.zeros(setup.n)}
'''

LAX_MEASURE = '''
import numpy as np
from graders import checks


def measure(setup, fields, reference):
    y = checks.array(checks.require_keys(fields, ["y"]), "y", (setup.n,))
    return {"samples": {}, "errors": {"y_max": float(np.abs(y).max())}, "tolerance": 0.0, "pass": bool(np.any(y != 0))}
'''

RAISING_MEASURE = '''
def measure(setup, fields, reference):
    return {"pass": fields["ybad"]}
'''


def quiet(root, study="tiny"):
    return checker.validate(root, study, 60, log=lambda s: None)


def test_a_junk_answer_that_must_fail_cannot_hide_a_lax_measure(tiny_study):
    from raft import graders
    graders.add(tiny_study, "checks")
    (tiny_study / "problem" / "measure.py").write_text(LAX_MEASURE)
    with_answer(tiny_study, ZERO_ANSWER)
    holes = quiet(tiny_study.parents[1])
    assert any("must also define passing_answer" in h for h in holes)


def test_mutations_that_change_nothing_are_holes(tiny_study):
    with_answer(tiny_study, ANSWER.replace("np.linspace(0, 1, setup.n) ** 2", "np.zeros(setup.n)")
                .replace("REFERENCE_ANSWER_PASSES = True", "REFERENCE_ANSWER_PASSES = False\n\n\n"
                         "def passing_answer(setup):\n    return {'y': np.zeros(setup.n)}"))
    holes = quiet(tiny_study.parents[1])
    assert any("mutation 'zeros' has no effect" in h for h in holes)


def test_mutations_are_applied_to_the_passing_answer(tiny_study):
    with_answer(tiny_study, ANSWER.replace("REFERENCE_ANSWER_PASSES = True", "REFERENCE_ANSWER_PASSES = False")
                .replace("def reference_answer(setup):", "def passing_answer(setup):\n"
                         "    return {'y': np.linspace(0, 1, setup.n) ** 2}\n\n\ndef reference_answer(setup):")
                .replace("return {\"y\": np.linspace(0, 1, setup.n) ** 2}\n", "return {\"y\": np.ones(setup.n)}\n"))
    assert quiet(tiny_study.parents[1]) == []


def test_measure_errors_are_named(tiny_study):
    with_answer(tiny_study)
    (tiny_study / "problem" / "measure.py").write_text(RAISING_MEASURE)
    holes = quiet(tiny_study.parents[1])
    assert any("the reference answer fails (expected it to pass): measure raised KeyError" in h for h in holes)


def test_approval_screen_shows_flags_and_problem_files(tiny_git_study):
    root = ready(tiny_git_study)
    shown = []
    checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "tiny", out=shown.append, run_timeout=60)
    screen = "\n".join(shown)
    assert "REFERENCE_ANSWER_PASSES: True" in screen and "problem/ files: measure.py, reference.json, setup.py" in screen
    assert "✓ attack zeros blocked" in screen


def test_approve_refuses_inside_an_agent_session(tiny_git_study, monkeypatch):
    root = ready(tiny_git_study)
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(SystemExit, match="inside an agent session"):
        checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "tiny", out=lambda s: None)


def test_gate_refuses_untracked_files_in_problem(tiny_git_study):
    root = tiny_git_study.parents[1]
    checker.gate(root, "tiny")
    (tiny_git_study / "problem" / "graders").mkdir()
    (tiny_git_study / "problem" / "graders" / "__init__.py").write_text("PASS = True\n")
    with pytest.raises(SystemExit, match="uncommitted or untracked files"):
        checker.gate(root, "tiny")


def test_gate_refuses_an_uncommitted_approval(tiny_git_study):
    root = tiny_git_study.parents[1]
    p = tiny_git_study / "problem" / "setup.py"
    p.write_text(p.read_text() + "\n# v2\n")
    commit_all(root, "v2")
    checker.record_approval(root, "tiny", approved_by={"name": "agent", "email": "a@b"})
    with pytest.raises(SystemExit, match="commit studies/tiny/checker-approval.json"):
        checker.gate(root, "tiny")
    commit_all(root, "approval")
    checker.gate(root, "tiny")


def test_prepare_stops_when_an_agent_touches_the_approval(env, monkeypatch):  # noqa: F811
    root, cmd = env
    monkeypatch.setenv("FAKE_MODE", "forge")
    with pytest.raises(SystemExit, match="changed checker-approval.json"):
        run(root, cmd)


def test_prepare_stops_when_the_attacker_records_nothing(env, monkeypatch):  # noqa: F811
    root, cmd = env
    monkeypatch.setenv("FAKE_MODE", "silent-attacker")
    with pytest.raises(SystemExit, match="the attack step recorded no new round and attack") as e:
        run(root, cmd)
    assert "raft prepare --study tiny" in str(e.value)


def test_prepare_stops_when_the_builder_deletes_evidence(env, monkeypatch):  # noqa: F811
    root, cmd = env
    monkeypatch.setenv("FAKE_MODE", "holes-delete")
    with pytest.raises(SystemExit, match="removed or changed attack evidence"):
        run(root, cmd)

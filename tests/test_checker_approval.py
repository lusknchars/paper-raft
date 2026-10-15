import json

import pytest
from conftest import commit_all

from raft import checker, cli, schema
from test_checker_validate import ATTACK_ZEROS, with_answer


class Tty:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


def ready(sd):
    """A tiny study with a checker that holds, one attack round, everything committed."""
    with_answer(sd)
    (sd / "checker" / "attacks").mkdir()
    (sd / "checker" / "attacks" / "zeros.py").write_text(ATTACK_ZEROS)
    (sd / "checker" / "NOTE.md").write_text("Grades y = x^2 at n = 4 and 8.")
    (sd / "checker" / "review.json").write_text(json.dumps({
        "study": "tiny", "builder_agent": "codex:checker-builder", "attacker_agent": "claude-code:checker-attacker",
        "rounds": [{"round": 1, "attacks": [{"name": "zeros", "idea": "return zeros", "blocked": True}]}]}))
    commit_all(sd.parents[1], "checker")
    return sd.parents[1]


def test_fixture_study_is_approved(tiny_git_study):
    assert checker.approval_state(tiny_git_study.parents[1], "tiny")["state"] == "approved-before-attacks"


def test_approve_needs_a_terminal(tiny_git_study):
    root = ready(tiny_git_study)
    with pytest.raises(SystemExit, match="interactive terminal"):
        checker.approve(root, "tiny", stdin=Tty(False), read=lambda p: "tiny", out=lambda s: None)


def test_approve_needs_the_study_id_typed(tiny_git_study):
    root = ready(tiny_git_study)
    with pytest.raises(SystemExit, match="not approved"):
        checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "yes", out=lambda s: None)


def test_approve_writes_the_record(tiny_git_study):
    root = ready(tiny_git_study)
    shown = []
    path = checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "tiny", out=shown.append, run_timeout=60)
    rec = schema.load("checker-approval", path)
    assert rec["rounds"] == 1 and rec["attacks"] == {"tried": 1, "blocked": 1}
    assert rec["attacker_agent"] == "claude-code:checker-attacker" and rec["approved_by"]["name"] == "t"
    screen = "\n".join(shown)
    assert "Grades y = x^2" in screen and "round 1: 1 tried, 1 blocked" in screen
    assert checker.approval_state(root, "tiny") == {"state": "approved", "rounds": 1, "approved_at": rec["approved_at"]}


def test_approve_refuses_uncommitted_changes(tiny_git_study):
    root = ready(tiny_git_study)
    (tiny_git_study / "checker" / "NOTE.md").write_text("changed")
    with pytest.raises(SystemExit, match="commit them first"):
        checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "tiny", out=lambda s: None)


def test_approve_refuses_a_checker_with_holes(tiny_git_study):
    root = ready(tiny_git_study)
    (tiny_git_study / "checker" / "answer.py").write_text(
        (tiny_git_study / "checker" / "answer.py").read_text().replace("= True", "= False"))
    commit_all(root, "break")
    with pytest.raises(SystemExit, match="does not hold"):
        checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "tiny", out=lambda s: None, run_timeout=60)


def test_approve_without_attack_rounds_is_refused(tiny_git_study):
    root = tiny_git_study.parents[1]
    with_answer(tiny_git_study)
    commit_all(root, "answer")
    with pytest.raises(SystemExit, match="no attack rounds"):
        checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "tiny", out=lambda s: None, run_timeout=60)


def test_without_attacks_needs_committed_runs(tiny_git_study):
    root = tiny_git_study.parents[1]
    with pytest.raises(SystemExit, match="only for a study with committed runs"):
        checker.approve(root, "tiny", without_attacks=True, stdin=Tty(True), read=lambda p: "tiny",
                        out=lambda s: None)


def test_gate_blocks_after_a_change(tiny_git_study, monkeypatch):
    root = tiny_git_study.parents[1]
    monkeypatch.chdir(root)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["run", "exact", "--n", "4"]) == 0
    p = tiny_git_study / "problem" / "setup.py"
    p.write_text(p.read_text() + "\n# v2\n")
    commit_all(root, "v2")
    assert checker.approval_state(root, "tiny")["state"] == "stale"
    for argv in (["run", "exact", "--n", "4"], ["implement", "exact"]):
        with pytest.raises(SystemExit, match="changed since the checker was approved"):
            cli.main(argv)


def test_gate_blocks_without_approval(tiny_git_study, monkeypatch):
    root = tiny_git_study.parents[1]
    (tiny_git_study / checker.APPROVAL).unlink()
    commit_all(root, "no approval")
    monkeypatch.chdir(root)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    with pytest.raises(SystemExit, match="has no approved checker"):
        cli.main(["run", "exact", "--n", "4"])
    from raft import bench
    with pytest.raises(SystemExit, match="has no approved checker"):
        bench.run_bench(root, "tiny", "command", cmd="x {brief}", log=lambda s: None)


def test_cli_approve_refuses_without_tty(tiny_git_study, monkeypatch):
    monkeypatch.chdir(ready(tiny_git_study))
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    with pytest.raises(SystemExit, match="interactive terminal"):
        cli.main(["approve"])

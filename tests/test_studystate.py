"""raft status: where a study stands, gate by gate, and the one command to run next."""
import json

import pytest

from conftest import commit_all
from raft import checker, cli, live, scaffold, studystate

REVIEW = {"study": "tiny", "builder_agent": "a", "attacker_agent": "b",
          "rounds": [{"round": 1, "attacks": [{"name": "zeros-1", "idea": "zeros", "blocked": True}]}]}


def pdf(root, study="tiny"):
    p = root / "papers" / f"{study}.pdf"
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(b"%PDF-1.4\n")


def by(st):
    return {s.name: s for s in st}


def test_a_fresh_draft_needs_extracting(tiny_study):
    root = tiny_study.parents[1]
    scaffold.new_study(root, "fresh", "Fresh", "10.1/x")
    pdf(root, "fresh")
    st = studystate.stages(root, "fresh", quick=True)
    assert by(st)["paper"].ok and by(st)["extraction"].ok is False and by(st)["extraction"].text == "not extracted"
    assert by(st)["approval"].text == "—"
    assert studystate.next_step(root, "fresh", st, (None, None)) == \
        "uv run raft prepare --study fresh --agent <claude-code|codex>"


def test_no_pdf(tiny_study):
    root = tiny_study.parents[1]
    (tiny_study / "extraction.json").unlink()  # the PDF is needed only to extract
    st = studystate.stages(root, "tiny", quick=True)
    assert by(st)["paper"].ok is False
    assert studystate.next_step(root, "tiny", st, (None, None)) == "Put the paper's PDF at papers/tiny.pdf"


def test_tested_but_not_approved(tiny_study):
    root = tiny_study.parents[1]
    pdf(root)
    (tiny_study / "checker").mkdir(exist_ok=True)
    (tiny_study / "checker" / "review.json").write_text(json.dumps(REVIEW))
    (tiny_study / checker.APPROVAL).unlink()
    st = studystate.stages(root, "tiny", quick=True)
    assert by(st)["checker"].ok is None and by(st)["tested"].ok
    assert by(st)["approval"].ok is False and by(st)["approval"].text == "not approved"
    assert studystate.next_step(root, "tiny", st, (None, None)).startswith("uv run raft approve --study tiny")


def test_approved_and_committed_with_methods_but_no_runs(tiny_git_study):
    root = tiny_git_study.parents[1]
    pdf(root)
    (tiny_git_study / "checker").mkdir(exist_ok=True)
    (tiny_git_study / "checker" / "review.json").write_text(json.dumps(REVIEW))
    checker.record_approval(root, "tiny", approved_by={"name": "t", "email": "t@example.com"})
    commit_all(root, "approve")
    st = studystate.stages(root, "tiny", quick=True)
    assert by(st)["approval"].ok and by(st)["gaps"].text == "none"
    assert by(st)["runs"].ok is False and by(st)["runs"].text == "1 method(s), 0 run(s)"
    assert studystate.next_step(root, "tiny", st, (None, None)) == "uv run raft run --all --study tiny"


def test_the_last_stop_switches_the_refused_tool(tiny_study):
    root = tiny_study.parents[1]
    pdf(root)
    (tiny_study / checker.APPROVAL).unlink()  # a new study: never approved, never tested
    s = live.Session(root, "prepare", "tiny", agents={"builder": {"tool": "codex", "model": None},
                                                      "attacker": {"tool": "codex", "model": None}}, total=4)
    s.set_problem({"kind": "refused", "tool": "codex", "role": "attacker", "detail": "flagged",
                   "headline": "Codex refused the attack brief (its content filter flagged it)"})
    s.stop("raft: Codex refused the attack brief")
    assert studystate.tools(root, "tiny") == ("codex", "claude-code")
    text = studystate.report(root, "tiny", quick=True)
    assert "last stop: Codex refused the attack brief (its content filter flagged it)" in text
    assert text.rstrip().endswith("Next: uv run raft prepare --study tiny --agent codex --attacker claude-code")


def test_quick_never_runs_the_grader(tiny_study, monkeypatch):
    root = tiny_study.parents[1]
    pdf(root)
    monkeypatch.setattr(checker, "validate", lambda *a, **k: pytest.fail("ran the grader"))
    studystate.stages(root, "tiny", quick=True)
    monkeypatch.setattr(checker, "validate", lambda *a, **k: [])
    assert by(studystate.stages(root, "tiny"))["checker"].text.startswith("validates")


def test_cli_status(tiny_git_study, monkeypatch, capsys):
    pdf(tiny_git_study.parents[1])
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["status", "--study", "tiny", "--quick"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("tiny") and "✓ paper" in out and "Next: " in out
    assert cli.main(["status"]) == 0
    assert capsys.readouterr().out.startswith("tiny: ")


def test_an_extracted_study_does_not_need_its_pdf(tiny_study):
    root = tiny_study.parents[1]  # a fresh clone: papers/ is gitignored, the extraction is committed
    st = studystate.stages(root, "tiny", quick=True)
    assert by(st)["paper"].ok is True and "needed only to extract again" in by(st)["paper"].text
    assert not studystate.next_step(root, "tiny", st, (None, None)).startswith("Put the paper's PDF")


def test_a_study_approved_before_decoy_testing_counts_as_tested(tiny_study):
    root = tiny_study.parents[1]  # the fixture's approval has no attack rounds, like transduced-lm-2026
    assert checker.approval_state(root, "tiny")["state"] == "approved-before-attacks"
    st = studystate.stages(root, "tiny", quick=True)
    assert by(st)["tested"].ok is True and by(st)["tested"].text == "approved before decoy testing existed"

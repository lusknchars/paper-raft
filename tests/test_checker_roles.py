import re
from pathlib import Path

import pytest

from raft import cli, guard

ROOT = Path(__file__).resolve().parents[1]


def test_builder_role_names_every_deliverable():
    text = (ROOT / "roles" / "checker-builder.md").read_text()
    for needle in ("problem/setup.py", "problem/measure.py", "problem/reference.json", "raft grader add",
                   "checker/NOTE.md", "checker/answer.py", "REFERENCE_ANSWER_PASSES", "checker/attacks/",
                   "raft validate", "Never lower a tolerance"):
        assert needle in text, needle


def test_attacker_role_names_its_limits():
    text = (ROOT / "roles" / "checker-attacker.md").read_text()
    for needle in ("{{round}}", "checker/attacks/", "checker/review.json", "raft validate", "Never edit",
                   "raft approve"):
        assert needle in text, needle


def test_implementer_role_forbids_the_checker_folder():
    assert "checker/" in (ROOT / "roles" / "implementer.md").read_text()


def test_guard_forbids_mentioning_the_checker(tmp_path):
    (tmp_path / "solver.py").write_text('PATH = "../checker/answer.py"\n')
    (problem,) = guard.scan_method(tmp_path)
    assert "checker/" in problem


def test_cli_prints_briefs(tiny_git_study, monkeypatch, capsys):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["build-checker"]) == 0
    assert capsys.readouterr().out.startswith("# checker-builder for tiny")
    assert cli.main(["attack", "--round", "2"]) == 0
    assert capsys.readouterr().out.startswith("# checker-attacker for tiny")


FLAGGED = re.compile(r"\b(attack|break|exploit|cheat|hack)\w*", re.I)


def _prose(text: str) -> str:
    return re.sub(r"`[^`]*`", "", text)  # file names and commands in backticks stay as they are


@pytest.mark.parametrize("role", ["checker-attacker", "checker-builder"])
def test_the_grader_briefs_avoid_words_that_trip_content_filters(role):
    found = FLAGGED.findall(_prose((ROOT / "roles" / f"{role}.md").read_text()))
    assert not found, found

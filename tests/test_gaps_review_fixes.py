"""Final-review fixes: a second letter asks only what was not asked yet, questions can be reworded before they are
sent, and conflicting actions are refused instead of silently ignored."""
import json

import pytest

from raft import cli, gaps
from test_gaps import ITEMS, with_missing


@pytest.fixture
def root(tiny_study):
    with_missing(tiny_study, *ITEMS, *[(f"extra-{n}", "parameter", 20 + n) for n in range(10)])
    gaps.refresh(tiny_study.parents[1], "tiny")
    return tiny_study.parents[1]


def test_a_second_letter_asks_the_rest_and_keeps_the_first_dates(root):
    first = gaps.mark_asked(root, "tiny", today="2026-10-17")
    text = gaps.letter(root, "tiny")
    assert not any(f"the {gid}." in text for gid in first)
    second = gaps.mark_asked(root, "tiny", today="2026-11-01")
    assert len(first) == 8 and len(second) == 5 and not set(first) & set(second)
    dates = {g["id"]: g["asked_on"] for g in gaps.load(root / "studies" / "tiny")["gaps"]}
    assert {dates[g] for g in first} == {"2026-10-17"} and {dates[g] for g in second} == {"2026-11-01"}


def test_reword_keeps_the_new_question_across_refreshes(root):
    gaps.reword(root, "tiny", "corpus", "  Which DNA corpus trained the bigram source?  ")
    gaps.refresh(root, "tiny")
    g = gaps.load(root / "studies" / "tiny")["gaps"][0]
    assert g["question"] == "Which DNA corpus trained the bigram source?" and g["reworded"] is True
    assert gaps.validate(root / "studies" / "tiny") == []


def test_reword_refuses_a_question_already_sent(root):
    gaps.mark_asked(root, "tiny")
    with pytest.raises(SystemExit, match="already asked"):
        gaps.reword(root, "tiny", "corpus", "New words")


def test_reword_refuses_blank_text(root):
    with pytest.raises(SystemExit, match="needs the new question"):
        gaps.reword(root, "tiny", "corpus", "   ")


def test_the_extractor_brief_keeps_internal_notes_out():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "roles" / "extractor.md").read_text()
    assert "authors may read `text` and `assumption`" in text


@pytest.fixture
def in_tiny(tiny_git_study, monkeypatch):
    with_missing(tiny_git_study, *ITEMS)
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["gaps", "--study", "tiny"]) == 0
    return tiny_git_study


@pytest.mark.parametrize("argv", [
    ["--answer", "corpus", "--decline", "ties", "--by", "a", "--source", "b", "--publish"],
    ["--letter", "--mark-asked"],
    ["--blocks", "corpus", "x", "--letter"],
    ["--reword", "corpus", "x", "--mark-asked"],
])
def test_conflicting_actions_are_refused(in_tiny, argv):
    before = (in_tiny / "gaps.json").read_text()
    with pytest.raises(SystemExit) as e:
        cli.main(["gaps", "--study", "tiny", *argv])
    assert e.value.code == 2
    assert (in_tiny / "gaps.json").read_text() == before


def test_cli_reword(in_tiny, capsys):
    assert cli.main(["gaps", "--study", "tiny", "--reword", "corpus", "Which corpus?"]) == 0
    assert "✓ corpus: reworded" in capsys.readouterr().out
    assert json.loads((in_tiny / "gaps.json").read_text())["gaps"][0]["question"] == "Which corpus?"

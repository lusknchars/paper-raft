"""The letter to the authors: blocking questions first, a cap on the rest, names from paper.yaml, no addresses."""
import re

import pytest
import yaml

from raft import cli, gaps
from test_gaps import ITEMS, with_missing


def authors(sd, names):
    p = sd / "paper.yaml"
    paper = yaml.safe_load(p.read_text())
    paper["authors"] = names
    p.write_text(yaml.safe_dump(paper, allow_unicode=True))


@pytest.fixture
def study(tiny_study):
    with_missing(tiny_study, *ITEMS)
    authors(tiny_study, ["Vésteinn Snæbjarnarson", "Tim Vieira"])
    gaps.refresh(tiny_study.parents[1], "tiny")
    gaps.set_blocks(tiny_study.parents[1], "tiny", "corpus", "Grading against Table 2")
    return tiny_study


def test_blocking_questions_come_first_and_nothing_changes(study):
    before = (study / "gaps.json").read_bytes()
    text = gaps.letter(study.parents[1], "tiny", "https://github.com/lusknchars/paper-raft")
    assert text.startswith("Dear Vésteinn Snæbjarnarson and Tim Vieira,")
    i = text.index
    assert i("What blocks a stricter check") < i("the corpus.") < i("Grading against Table 2") \
        < i("Smaller details, if you have time") < i("the ties.") < i("the edge.")
    assert "p. 14" in text and "https://lusknchars.github.io/paper-raft/#study/tiny" in text
    assert "With your permission we'll publish your answers in the study, credited to you." in text
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w", text)
    assert (study / "gaps.json").read_bytes() == before


def test_the_smaller_details_are_capped_at_eight(study):
    with_missing(study, *[(f"extra-{n}", "parameter", 20 + n) for n in range(10)])
    gaps.refresh(study.parents[1], "tiny")
    text = gaps.letter(study.parents[1], "tiny", "https://github.com/o/r")
    small = text.split("Smaller details, if you have time")[1]
    assert len(re.findall(r"^\d+\. p\. ", small, re.M)) == 8
    assert "and 4 more: https://o.github.io/r/#study/tiny/gaps" in small


def test_without_authors_or_a_site(study, monkeypatch):
    authors(study, [])
    monkeypatch.delenv("RAFT_SITE_URL", raising=False)
    text = gaps.letter(study.parents[1], "tiny", None)
    assert text.startswith("Dear authors,") and "http" not in text


def test_site_url():
    assert gaps.site_url("https://github.com/Lusk/paper-raft") == "https://lusk.github.io/paper-raft/"
    assert gaps.site_url(None) is None


def test_site_url_override(monkeypatch):
    monkeypatch.setenv("RAFT_SITE_URL", "https://example.org/raft")
    assert gaps.site_url("https://github.com/o/r") == "https://example.org/raft/"


def test_mark_asked_marks_exactly_what_the_letter_lists(study):
    with_missing(study, *[(f"extra-{n}", "parameter", 20 + n) for n in range(10)])
    gaps.refresh(study.parents[1], "tiny")
    ids = gaps.mark_asked(study.parents[1], "tiny", today="2026-10-17")
    data = gaps.load(study)
    asked = [g["id"] for g in data["gaps"] if g["status"] == "asked"]
    assert ids == asked and len(asked) == 9 and asked[0] == "corpus"
    assert {g["asked_on"] for g in data["gaps"] if g["status"] == "asked"} == {"2026-10-17"}
    assert sum(g["status"] == "open" for g in data["gaps"]) == 4


def test_mark_asked_refuses_inside_an_agent_session(study, monkeypatch):
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    with pytest.raises(SystemExit, match="inside an agent session"):
        gaps.mark_asked(study.parents[1], "tiny")


def test_nothing_to_ask(study):
    data = gaps.load(study)
    for g in data["gaps"]:
        g.update(status="declined", answer={"by": "a", "source": "b", "recorded_on": "2026-10-20"})
    gaps.save(study, data)
    with pytest.raises(SystemExit, match="no unanswered gaps"):
        gaps.letter(study.parents[1], "tiny")


def test_letter_before_any_gaps_file(tiny_study):
    with pytest.raises(SystemExit, match="raft gaps --study tiny"):
        gaps.letter(tiny_study.parents[1], "tiny")
    with pytest.raises(SystemExit, match="raft gaps --study tiny"):
        gaps.mark_asked(tiny_study.parents[1], "tiny")


def test_cli_letter_and_mark_asked(tiny_git_study, monkeypatch, capsys):
    with_missing(tiny_git_study, *ITEMS)
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["gaps", "--study", "tiny"]) == 0
    capsys.readouterr()
    assert cli.main(["gaps", "--study", "tiny", "--letter"]) == 0
    assert capsys.readouterr().out.startswith("Dear authors,")
    assert cli.main(["gaps", "--study", "tiny", "--mark-asked"]) == 0
    assert "✓ marked 3 questions asked" in capsys.readouterr().out

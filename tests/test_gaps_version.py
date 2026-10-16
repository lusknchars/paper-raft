"""A stricter version of a study: a fresh draft whose extractor gets the authors' published answers."""
import json

import pytest
import yaml

from raft import briefs, cli, gaps, scaffold, validate
from test_gaps import ITEMS, with_missing


@pytest.fixture
def answered(tiny_study):
    root = tiny_study.parents[1]
    with_missing(tiny_study, *ITEMS)
    gaps.refresh(root, "tiny")
    gaps.answer(root, "tiny", "corpus", by="A. Author", source="email, 2026-10-20", publish=True,
                text="We used GRCh38.")
    gaps.answer(root, "tiny", "ties", by="B. Author", source="email", publish=False)
    return root


def test_new_version_is_a_fresh_draft_that_names_its_source(answered):
    d = scaffold.new_version(answered, "tiny", "tiny-v2")
    paper = yaml.safe_load((d / "paper.yaml").read_text())
    src = yaml.safe_load((answered / "studies" / "tiny" / "paper.yaml").read_text())
    assert paper["version_of"] == "tiny" and paper["draft"] is True
    assert paper["title"] == src["title"] and paper["pdf"] == src["pdf"]
    assert "NotImplementedError" in (d / "problem" / "setup.py").read_text()  # fresh stubs, nothing copied
    assert not (d / "checker").exists() and not (d / "methods").exists() and not (d / "extraction.json").exists()


def test_new_version_refuses_bad_ids(answered):
    with pytest.raises(SystemExit, match="unknown study 'nope'"):
        scaffold.new_version(answered, "nope", "x-v2")
    with pytest.raises(SystemExit, match="already exists"):
        scaffold.new_version(answered, "tiny", "tiny")


def test_the_extractor_brief_carries_only_published_answers(answered):
    scaffold.new_version(answered, "tiny", "tiny-v2")
    text = briefs.render(answered, "extractor", "tiny-v2")
    section = text.split("**Author answers.**")[1]
    assert "`corpus` (p. 14), answered by A. Author (email, 2026-10-20): We used GRCh38." in section
    assert '"answer": "tiny/gaps.json#corpus"' in section
    assert "ties" not in section


def test_no_section_without_published_answers(tiny_study):
    root = tiny_study.parents[1]
    scaffold.new_version(root, "tiny", "tiny-v2")
    assert "Author answers" not in briefs.render(root, "extractor", "tiny-v2")


def write_extraction(sd, item):
    (sd / "extraction.json").write_text(json.dumps({"study": sd.name, "items": [item]}))


ITEM = {"id": "corpus", "kind": "parameter", "text": "GRCh38", "page": 14, "quote": "", "missing": False}


@pytest.mark.parametrize("answer, missing, problem", [
    ("tiny/gaps.json#corpus", False, None),
    ("tiny/gaps.json#ties", False, "not a published answer"),
    ("tiny/gaps.json#nope", False, "no gap 'nope'"),
    ("gone/gaps.json#corpus", False, "no studies/gone/gaps.json"),
    ("tiny/gaps.json#corpus", True, "is missing but cites an answer"),
])
def test_extraction_answers_must_point_at_published_answers(answered, answer, missing, problem):
    d = scaffold.new_version(answered, "tiny", "tiny-v2")
    write_extraction(d, {**ITEM, "answer": answer, "missing": missing,
                         **({"assumption": "x"} if missing else {})})
    found = validate.extraction(d)
    assert found == [] if problem is None else any(problem in f for f in found), found


def test_the_schema_rejects_a_malformed_reference(answered):
    d = scaffold.new_version(answered, "tiny", "tiny-v2")
    write_extraction(d, {**ITEM, "answer": "somewhere else"})
    assert any("answer" in f for f in validate.extraction(d))


def test_cli_new_from(answered, monkeypatch, capsys):
    monkeypatch.chdir(answered)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["new", "--from", "tiny", "--id", "tiny-v2"]) == 0
    out = capsys.readouterr().out
    assert "draft version of tiny" in out and "1 published answer" in out
    with pytest.raises(SystemExit):
        cli.main(["new", "--from", "tiny"])  # no --id

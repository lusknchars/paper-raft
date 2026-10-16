"""raft gaps: questions to the authors for the details a paper leaves out, built from extraction.json."""
import json

import pytest

from raft import cli, gaps

ITEMS = [("corpus", "parameter", 14), ("ties", "method", 4), ("edge", "boundary_condition", 13)]


def with_missing(sd, *items):
    path = sd / "extraction.json"
    ext = json.loads(path.read_text())
    ext["items"] += [{"id": i, "kind": k, "text": f"The paper does not give the {i}.", "page": p, "quote": "",
                      "missing": True, "assumption": f"Use the default {i}"} for i, k, p in items]
    path.write_text(json.dumps(ext))


def drop_items(sd, *ids):
    path = sd / "extraction.json"
    ext = json.loads(path.read_text())
    ext["items"] = [i for i in ext["items"] if i["id"] not in ids]
    path.write_text(json.dumps(ext))


def edit(sd, fn):
    path = sd / "gaps.json"
    data = json.loads(path.read_text())
    fn({g["id"]: g for g in data["gaps"]})
    path.write_text(json.dumps(data))


@pytest.fixture
def study(tiny_study):
    with_missing(tiny_study, *ITEMS)
    return tiny_study


def test_refresh_makes_one_open_question_per_missing_item(study):
    data = gaps.refresh(study.parents[1], "tiny", today="2026-10-16")
    by = {g["id"]: g for g in data["gaps"]}
    assert [g["id"] for g in data["gaps"]] == ["corpus", "ties", "edge"]
    assert {g["status"] for g in data["gaps"]} == {"open"}
    assert by["corpus"]["question"] == ("The paper does not give the corpus. What did you use? "
                                        "We assumed: Use the default corpus. Is that right?")
    assert "How is this done?" in by["ties"]["question"] and "What happens here?" in by["edge"]["question"]
    assert by["corpus"]["page"] == 14 and by["corpus"]["assumption"] == "Use the default corpus"
    assert json.loads((study / "gaps.json").read_text()) == data
    assert gaps.validate(study) == []


def test_rerun_keeps_history_adds_new_items_and_resolves_filled_ones(study):
    root = study.parents[1]
    gaps.refresh(root, "tiny", today="2026-10-16")
    sent = gaps.load(study)["gaps"][0]["question"]

    def ask(by):
        by["corpus"].update(status="asked", asked_on="2026-10-17")
        by["ties"]["blocks"] = "Table 2"
    edit(study, ask)
    ext = json.loads((study / "extraction.json").read_text())
    for i in ext["items"]:
        if i["id"] == "corpus":
            i["text"] = "Reworded by a later extraction."
    (study / "extraction.json").write_text(json.dumps(ext))
    with_missing(study, ("seeds", "parameter", 11))
    drop_items(study, "edge")
    by = {g["id"]: g for g in gaps.refresh(root, "tiny", today="2026-10-20")["gaps"]}
    assert by["corpus"]["status"] == "asked" and by["corpus"]["asked_on"] == "2026-10-17"
    assert by["corpus"]["question"] == sent  # what was sent stays as sent
    assert by["ties"]["blocks"] == "Table 2" and by["seeds"]["status"] == "open"
    assert by["edge"]["status"] == "resolved" and by["edge"]["resolved_on"] == "2026-10-20"
    assert gaps.validate(study) == []


def test_an_answered_gap_keeps_its_status_when_its_item_is_filled(study):
    root = study.parents[1]
    gaps.refresh(root, "tiny")
    edit(study, lambda by: by["corpus"].update(status="answered", answer={
        "text": "We used GRCh38.", "by": "A. Author", "source": "email", "recorded_on": "2026-10-20"}))
    drop_items(study, "corpus")
    by = {g["id"]: g for g in gaps.refresh(root, "tiny")["gaps"]}
    assert by["corpus"]["status"] == "answered" and by["corpus"]["answer"]["text"] == "We used GRCh38."


def test_refresh_stops_on_a_broken_file_and_leaves_it(study):
    (study / "gaps.json").write_text('{"study": "tiny", "gaps": [{"id": "corpus"}]}')
    with pytest.raises(SystemExit, match="gaps.json"):
        gaps.refresh(study.parents[1], "tiny")
    assert (study / "gaps.json").read_text() == '{"study": "tiny", "gaps": [{"id": "corpus"}]}'


def test_refresh_needs_an_extraction(study):
    (study / "extraction.json").unlink()
    with pytest.raises(SystemExit, match="no extraction.json"):
        gaps.refresh(study.parents[1], "tiny")


@pytest.mark.parametrize("change, expect", [
    (lambda d: d.update(study="other"), "study is 'other'"),
    (lambda d: d["gaps"][0].update(id="nowhere"), "'nowhere' is open but is not a missing item"),
    (lambda d: d["gaps"][0].update(id="corpus-dup") or d["gaps"].append(dict(d["gaps"][0])), "duplicate gap"),
    (lambda d: d["gaps"][0].update(status="answered", answer={"by": "a", "source": "b", "recorded_on": "2026-10-20"}),
     "text"),
    (lambda d: d["gaps"][0].update(status="answered_private",
                                   answer={"text": "secret", "by": "a", "source": "b", "recorded_on": "2026-10-20"}),
     "answer"),
])
def test_validate_names_each_problem(study, change, expect):
    gaps.refresh(study.parents[1], "tiny")
    data = json.loads((study / "gaps.json").read_text())
    change(data)
    (study / "gaps.json").write_text(json.dumps(data))
    assert any(expect in p for p in gaps.validate(study)), gaps.validate(study)


def test_blocks_creates_the_file_and_names_the_check(study):
    gaps.set_blocks(study.parents[1], "tiny", "corpus", "Grading against Table 2")
    assert gaps.load(study)["gaps"][0]["blocks"] == "Grading against Table 2"
    with pytest.raises(SystemExit, match="no gap 'nope'"):
        gaps.set_blocks(study.parents[1], "tiny", "nope", "x")


def test_blocks_works_inside_an_agent_session(study, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    gaps.set_blocks(study.parents[1], "tiny", "ties", "Exact tie order")
    assert gaps.load(study)["gaps"][1]["blocks"] == "Exact tie order"


def test_counts(study):
    data = gaps.refresh(study.parents[1], "tiny")
    data["gaps"][0]["blocks"] = "Table 2"
    data["gaps"][2].update(status="resolved", resolved_on="2026-10-20")
    c = gaps.counts(data)
    assert (c["gaps"], c["open"], c["resolved"], c["blocking"]) == (2, 2, 1, 1)
    assert gaps.count_line(c) == "2 gaps · 2 open · 0 asked · 0 answered · 1 blocking a stricter check"


@pytest.fixture
def in_tiny(tiny_git_study, monkeypatch):
    with_missing(tiny_git_study, *ITEMS)
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    return tiny_git_study


def test_cli_lists_validates_summarises_and_sets_blocks(in_tiny, capsys):
    assert cli.main(["gaps", "--study", "tiny"]) == 0
    out = capsys.readouterr().out
    assert "p. 14" in out and "corpus" in out and "3 gaps · 3 open" in out and "--letter" in out
    assert cli.main(["gaps", "--study", "tiny", "--blocks", "corpus", "Table 2"]) == 0
    assert "blocks: Table 2" in capsys.readouterr().out
    assert cli.main(["gaps", "--validate", "--all-studies"]) == 0
    assert cli.main(["gaps"]) == 0
    assert "tiny: 3 gaps" in capsys.readouterr().out


def test_cli_summary_without_any_gaps_file(tiny_git_study, monkeypatch, capsys):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["gaps"]) == 0
    assert "no study has a gaps.json yet" in capsys.readouterr().out

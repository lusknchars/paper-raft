"""Paperraft lookup: one public JSON per paper, cached locally, never required to use the lab."""
import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from raft import cli, paperraft, studystate

T0 = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
BRIEF = {"arxiv_id": "2608.27428", "title": "Stochastic Estimation of Transduced Language Models",
         "summary": "Unbiased prefix probabilities.", "recommendation": "testar", "minimum_test": [],
         "claims": [{"claim_id": "claim-01", "statement": "Unbiased."}], "source_url": "https://arxiv.org/abs/2608.27428",
         "lab_reproductions": [], "as_of": "2026-10-16", "stars": 3, "builder_plan": {"secret": 1}}


class Fetch:
    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, url):
        self.calls.append(url)
        if isinstance(self.result, Exception):
            raise self.result
        return json.dumps(self.result).encode()


@pytest.mark.parametrize("text, want", [
    ("2608.27428", "2608.27428"), ("2608.27428v2", "2608.27428"), ("arXiv:2608.27428", "2608.27428"),
    ("https://paperaft.vercel.app/papers/2608.27428/", "2608.27428"), ("https://arxiv.org/abs/2608.27428v1", "2608.27428"),
    ("../2608.27428", None), ("hello", None), ("", None), ("2608.274", None),
])
def test_parse_id(text, want):
    assert paperraft.parse_id(text) == want


def test_a_brief_is_fetched_filtered_and_cached(tmp_path):
    f = Fetch(BRIEF)
    a = paperraft.answer("2608.27428", cache_dir=tmp_path, fetch=f, now=T0)
    assert a["found"] and not a["offline"] and not a["stale"]
    assert f.calls == ["https://paperaft.vercel.app/papers/2608.27428/index.json"]
    assert set(a["brief"]) == {"arxiv_id", "title", "summary", "recommendation", "minimum_test", "claims",
                               "source_url", "lab_reproductions", "as_of", "brief_url"}
    assert a["brief"]["brief_url"] == "https://paperaft.vercel.app/papers/2608.27428/"
    assert paperraft.answer("2608.27428", cache_dir=tmp_path, fetch=f, now=T0 + timedelta(hours=23))["found"]
    assert len(f.calls) == 1
    paperraft.answer("2608.27428", cache_dir=tmp_path, fetch=f, now=T0 + timedelta(hours=25))
    assert len(f.calls) == 2


def test_offline_uses_a_stale_copy(tmp_path):
    paperraft.answer("2608.27428", cache_dir=tmp_path, fetch=Fetch(BRIEF), now=T0)
    a = paperraft.answer("2608.27428", cache_dir=tmp_path, fetch=Fetch(urllib.error.URLError("down")),
                         now=T0 + timedelta(days=3))
    assert a["found"] and a["stale"] and a["offline"]


def test_offline_without_a_copy(tmp_path):
    a = paperraft.answer("2608.27428", cache_dir=tmp_path, fetch=Fetch(OSError("no network")), now=T0)
    assert a == {"found": False, "brief": None, "offline": True, "stale": False}


def test_an_unknown_paper(tmp_path):
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    assert paperraft.answer("2601.00001", cache_dir=tmp_path, fetch=Fetch(err), now=T0) == \
        {"found": False, "brief": None, "offline": False, "stale": False}


def test_a_broken_cache_file_is_refetched(tmp_path):
    (tmp_path / "2608.27428.json").write_text("{not json")
    assert paperraft.answer("2608.27428", cache_dir=tmp_path, fetch=Fetch(BRIEF), now=T0)["found"]


def test_text_for_a_paper_in_the_lab(tiny_study):
    root = tiny_study.parents[1]
    p = tiny_study / "paper.yaml"
    p.write_text(yaml.safe_dump({**yaml.safe_load(p.read_text()), "arxiv": "2608.27428"}))
    assert studystate.find_arxiv(root, "2608.27428") == "tiny"
    assert studystate.arxiv_of({"doi": "10.48550/arXiv.2608.27428"}) == "2608.27428"
    a = {"found": True, "brief": {**BRIEF, "brief_url": "https://paperaft.vercel.app/papers/2608.27428/"},
         "offline": False, "stale": False}
    out = paperraft.text(root, "2608.27428", a)
    assert out.startswith("Stochastic Estimation of Transduced Language Models\n")
    assert "Paperraft says: Test it" in out and "In your lab: studies/tiny" in out
    assert "See it: uv run raft app --paper 2608.27428" in out and "Next: " in out


def test_text_for_a_paper_not_in_the_lab_and_offline(tiny_study):
    out = paperraft.text(tiny_study.parents[1], "2601.00001",
                         {"found": False, "brief": None, "offline": True, "stale": False})
    assert "Paperraft can't be reached and there is no saved copy of its brief." in out
    assert "In your lab: no study yet" in out
    assert "Next: uv run raft prepare --arxiv 2601.00001 --agent <claude-code|codex>" in out


def test_cli_paper(tiny_git_study, monkeypatch, capsys):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    monkeypatch.setattr(paperraft, "default_fetch", Fetch(BRIEF))
    assert cli.main(["paper", "https://paperaft.vercel.app/papers/2608.27428/"]) == 0
    assert "Paperraft says: Test it" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["paper", "not-an-id"])

"""Final-review fixes: a malformed paper.yaml never takes the app down; a results failure never shows as "no run";
the Results tab carries errors against the tolerance."""
import pytest

from raft import app, compare, paperraft, runner, scaffold, studystate


@pytest.fixture
def lab(tiny_git_study):
    root = tiny_git_study.parents[1]
    scaffold.new_study(root, "fresh", "Fresh Draft", "10.1/fresh")
    return root


def test_a_malformed_paper_yaml_shows_as_an_error_card(lab):
    (lab / "studies" / "fresh" / "paper.yaml").write_text("title: [unclosed\n")
    d = app.app_data(lab)
    fresh = next(s for s in d["studies"] if s["id"] == "fresh")
    assert fresh["error"] and "paper.yaml" in fresh["error"]
    assert studystate.find_arxiv(lab, "2608.27428") is None  # skips the broken study instead of crashing
    assert "In your lab: no study yet" in paperraft.text(lab, "2608.27428",
                                                         {"found": False, "brief": None, "offline": True, "stale": False})


def test_unreadable_results_are_unknown_not_no_run(lab, monkeypatch):
    runner.run_one(lab / "studies" / "tiny", "exact", {"n": 8}, timeout=60)
    monkeypatch.setattr(compare, "build", lambda *a, **k: (_ for _ in ()).throw(ValueError("broken reference.json")))
    d = app.app_data(lab)
    assert d["warning"] and d["counts"]["verified_runs"] is None
    t = app.study_detail(lab, "tiny")
    assert t["results"] is None and t["warning"]


def test_results_carry_errors_against_the_tolerance(lab):
    runner.run_one(lab / "studies" / "tiny", "exact", {"n": 8}, timeout=60)
    (r,) = app.study_detail(lab, "tiny")["results"]
    assert "y_max" in r["errors"] and r["tolerance"] == 1e-9

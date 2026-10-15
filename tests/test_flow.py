import json

import pytest

from conftest import commit_all
from raft import flow, runner


def _review(sd, sha, method="exact"):
    (sd / "reviews").mkdir(exist_ok=True)
    (sd / "reviews" / f"{method}.json").write_text(json.dumps({
        "method": method, "reviewed_sha": sha, "reviewer_agent": f"test:reviewer#{method}",
        "verdict": "verified", "discrepancies": []}))


def _root(sd):
    return sd.parents[1]


def test_flow_of_tiny_study_lists_missing_and_verified_runs(tiny_git_study):
    sd = tiny_git_study
    manifest, _ = runner.run_one(sd, "exact", {"n": 8}, timeout=60)
    _review(sd, manifest["method_sha"])
    commit_all(_root(sd), "run n=8")
    f = flow.build_flow(_root(sd), "tiny", "https://github.com/acme/raft")
    assert f["study"] == "tiny" and f["schema"] == 1
    assert f["items"] == [{"id": "tiny-method", "kind": "method"}]
    assert f["cases"] == [{"key": "n=4", "label": "4"}, {"key": "n=8", "label": "8"}]
    runs = {r["case"]: r for r in f["runs"]}
    assert runs["n=4"]["status"] == "missing" and runs["n=4"]["pass"] is False
    assert runs["n=8"]["status"] == "verified" and runs["n=8"]["pass"] is True
    assert f["methods"] == [{"name": "exact", "implements": ["tiny-method"], "status": "unverified", "color": 0}]
    assert f["paper"] == {"title": "Tiny", "authors_short": "", "reference_checked": False, "draft": False}


def test_method_is_verified_when_every_expected_run_is(tiny_git_study):
    sd = tiny_git_study
    for n in (4, 8):
        manifest, _ = runner.run_one(sd, "exact", {"n": n}, timeout=60)
    _review(sd, manifest["method_sha"])
    commit_all(_root(sd), "runs")
    assert flow.build_flow(_root(sd), "tiny")["methods"][0]["status"] == "verified"


def test_run_is_stale_when_problem_changes_after_it(tiny_git_study):
    sd = tiny_git_study
    manifest, _ = runner.run_one(sd, "exact", {"n": 8}, timeout=60)
    _review(sd, manifest["method_sha"])
    measure = sd / "problem" / "measure.py"
    measure.write_text(measure.read_text() + "\n# changed\n")
    commit_all(_root(sd), "edit problem after the run")
    run = next(r for r in flow.build_flow(_root(sd), "tiny")["runs"] if r["case"] == "n=8")
    assert run["status"] == "stale" and run["pass"] is False


def test_metrics_come_from_paper_yaml_and_respect_where(tiny_git_study):
    sd = tiny_git_study
    (sd / "paper.yaml").write_text((sd / "paper.yaml").read_text() + (
        "metrics:\n"
        "  - {key: err, from: y_max, label: max error, note: vs x squared, agg: max, format: sci, where: {n: 8}}\n"))
    for n in (4, 8):
        runner.run_one(sd, "exact", {"n": n}, timeout=60)
    f = flow.build_flow(_root(sd), "tiny")
    runs = {r["case"]: r for r in f["runs"]}
    assert runs["n=4"]["metrics"] == []
    assert runs["n=8"]["metrics"][0]["key"] == "err" and runs["n=8"]["metrics"][0]["value"] < 1e-12
    assert f["metrics"] == [{"key": "err", "label": "max error", "note": "vs x squared", "agg": "max", "format": "sci"}]


@pytest.mark.parametrize("bad", [
    [{"key": "a", "from": "x", "label": "l", "note": "n", "agg": "max", "format": "html"}],
    [{"key": "a", "from": "x", "label": "l", "note": "n", "agg": "median", "format": "sci"}],
    [{"key": "a", "from": "x", "label": "l", "note": "n", "agg": "max", "format": "sci", "extra": 1}],
    [{"key": "A b", "from": "x", "label": "l", "note": "n", "agg": "max", "format": "sci"}],
    [{"key": "a", "from": "x", "label": "l", "note": "n", "agg": "max", "format": "sci", "where": [1]}],
    "not a list",
])
def test_bad_metric_specs_are_rejected(bad):
    with pytest.raises(ValueError):
        flow.metric_specs({"metrics": bad})


def test_draft_study_has_no_items(tiny_git_study):
    sd = tiny_git_study
    (sd / "paper.yaml").write_text((sd / "paper.yaml").read_text() + "draft: true\n")
    (sd / "extraction.json").unlink()
    f = flow.build_flow(_root(sd), "tiny")
    assert f["paper"]["draft"] is True and f["items"] == []
    assert f["methods"][0]["implements"] == []


def test_failed_run_never_counts_as_passing(tiny_git_study):
    from conftest import add_method
    sd = tiny_git_study
    add_method(sd, "broken", "def solve(setup):\n    raise RuntimeError('boom')\n")
    runner.run_one(sd, "broken", {"n": 8}, timeout=60)
    run = next(r for r in flow.build_flow(_root(sd), "tiny")["runs"]
               if r["method"] == "broken" and r["case"] == "n=8")
    assert run["status"] == "failed" and run["pass"] is False


def test_authors_short():
    assert flow.authors_short({"authors": ["Vésteinn Snæbjarnarson", "Samuel Kiegeland"],
                               "citation": "Snæbjarnarson, V. (2026). Stochastic ..."}) == "Snæbjarnarson et al. 2026"
    assert flow.authors_short({"authors": ["U. Ghia"], "citation": "(1982) JCP"}) == "Ghia 1982"
    assert flow.authors_short({}) == ""


def test_broken_problem_fails_unless_draft(tiny_git_study):
    sd = tiny_git_study
    setup = sd / "problem" / "setup.py"
    setup.write_text(setup.read_text() + "\ndef expand(params):\n    raise RuntimeError('broken')\n")
    with pytest.raises(RuntimeError, match="broken"):
        flow.build_flow(_root(sd), "tiny")
    (sd / "paper.yaml").write_text((sd / "paper.yaml").read_text() + "draft: true\n")
    assert flow.build_flow(_root(sd), "tiny")["runs"] == []

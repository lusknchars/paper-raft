import json

import pytest

from raft import schema

SHA = "a" * 40
HASH = "b" * 64

VALID = {
    "extraction": {
        "study": "ghia-1982",
        "extractor_agent": "claude-code:raft-extractor",
        "items": [
            {"id": "vorticity-transport", "kind": "equation", "text": "w_t + u w_x + v w_y = (1/Re) lap w",
             "page": 389, "quote": "vorticity transport equation", "missing": False},
            {"id": "convergence-tolerance", "kind": "parameter", "text": "stopping tolerance",
             "page": 392, "quote": "", "missing": True, "assumption": "stop when max residual < 1e-7"},
        ],
    },
    "method": {"name": "projection", "implements": ["vorticity-transport"], "author_agent": "claude-code:raft-implementer#projection"},
    "manifest": {
        "run_id": "projection-grid129-re100", "study": "ghia-1982", "method": "projection",
        "params": {"re": 100, "grid": 129}, "inputs_hash": HASH, "git_sha": SHA, "method_sha": SHA,
        "dirty": False, "python": "3.12.3", "packages": {"numpy": "2.1.0"}, "seed": 0,
        "started_at": "2026-10-12T18:00:00+00:00", "duration_s": 12.5, "repro_rtol": 1e-8,
    },
    "results": {
        "run_id": "projection-grid129-re100", "status": "ok",
        "samples": {"u_vertical": [[0.0, 0.0], [1.0, 1.0]]},
        "reference_samples": {"u_vertical": [[0.0, 0.0], [1.0, 1.0]]},
        "errors": {"u_max": 0.001}, "tolerance": 0.01, "pass": True,
        "fields_coarse": {"psi": [[0.0, 0.0], [0.0, -0.1]]},
    },
    "review": {
        "method": "projection", "reviewed_sha": SHA, "reviewer_agent": "claude-code:raft-reviewer#projection",
        "verdict": "verified", "summary": "matches", "discrepancies": [],
    },
    "reference": {"citation": "Ghia et al. 1982", "doi": "10.1016/0021-9991(82)90058-4", "tolerance": 0.01,
                  "cases": {"100": {"u_vertical": [[0, 0], [1, 1]], "v_horizontal": [[0, 0], [1, 0]]}}},
}


@pytest.mark.parametrize("name", schema.NAMES)
def test_valid_samples_pass(name):
    assert schema.errors(name, VALID[name]) == []


def test_extraction_item_needs_page():
    bad = json.loads(json.dumps(VALID["extraction"]))
    del bad["items"][0]["page"]
    assert any("page" in e for e in schema.errors("extraction", bad))


def test_missing_item_needs_assumption():
    bad = json.loads(json.dumps(VALID["extraction"]))
    del bad["items"][1]["assumption"]
    assert any("assumption" in e for e in schema.errors("extraction", bad))


def test_failed_results_need_reason_and_null_samples():
    bad = {"run_id": "x", "status": "failed", "samples": None, "errors": None, "tolerance": None, "pass": False}
    assert any("reason" in e for e in schema.errors("results", bad))
    good = {**bad, "reason": "timeout after 5s"}
    assert schema.errors("results", good) == []
    worse = {**good, "pass": True}
    assert schema.errors("results", worse) != []


def test_verified_review_allows_only_minor_discrepancies():
    bad = json.loads(json.dumps(VALID["review"]))
    bad["discrepancies"] = [{"file": "solver.py", "line": 3, "extraction_id": "x", "page": 1,
                             "description": "sign flipped", "severity": "major"}]
    assert schema.errors("review", bad) != []
    bad["verdict"] = "discrepancies"
    assert schema.errors("review", bad) == []


def test_discrepancies_verdict_needs_at_least_one():
    bad = {**VALID["review"], "verdict": "discrepancies"}
    assert schema.errors("review", bad) != []


def test_load_reports_path_and_errors(tmp_path):
    p = tmp_path / "method.json"
    p.write_text(json.dumps({"name": "x"}))
    with pytest.raises(schema.ContractError) as exc:
        schema.load("method", p)
    assert str(p) in str(exc.value) and "implements" in str(exc.value)


def test_load_reports_bad_json(tmp_path):
    p = tmp_path / "method.json"
    p.write_text("{not json")
    with pytest.raises(schema.ContractError, match="not valid JSON"):
        schema.load("method", p)

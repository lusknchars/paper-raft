import json

import pytest

from raft import benchboard, schema


def usage(cost=None, tin=None, tout=None):
    return {"input_tokens": tin, "cached_input_tokens": None, "output_tokens": tout, "cost_usd": cost, "turns": None}


def method(name, passes, wall=60.0, cost=None, tin=None, tout=None, errors=None):
    runs = [{"run_id": f"{name}-n{i}", "params": {"n": i}, "status": "ok", "pass": p, "reason": None,
             "errors": errors if errors is not None else {"y_max": 0.1 * (i + 1)}} for i, p in enumerate(passes)]
    return {"name": name, "agent_exit": 0, "timed_out": False, "wall_s": wall, "usage": usage(cost, tin, tout),
            "guard": [], "copied_from_lab": False, "runs": runs}


def entry(eid="2026-10-15-codex-default-aaaaaa", study="tiny", methods=None, label=None):
    methods = methods or [method("exact", [True, True])]
    return {"schema": 1, "id": eid, "study": study, "created_at": "2026-10-15T00:00:00+00:00",
            "raft_commit": "abc", "problem_hash": "0" * 64,
            "entrant": {"agent": "codex", "tool_version": "codex-cli 0.159.2", "model": None, "oss": False,
                        "label": label, "command": None, "isolation": "sandbox", "setup": None},
            "machine": {"os": "test", "python": "3.12"}, "methods": methods,
            "score": benchboard.score_counts(methods), "metrics": []}


def test_sample_entry_matches_schema():
    schema.check("bench-entry", entry())


def test_schema_rejects_unknown_agent():
    e = entry()
    e["entrant"]["agent"] = "gemini"
    assert schema.errors("bench-entry", e)


def test_score_counts():
    ms = [method("a", [True, False]), method("b", [True, True])]
    assert benchboard.score_counts(ms) == {"passed": 3, "expected": 4}


def test_aggregate_metrics_respects_where_and_agg():
    specs = [{"key": "worst", "from": "y_max", "label": "L", "note": "N", "agg": "max", "format": "sci",
              "where": {"n": 1}},
             {"key": "none", "from": "missing", "label": "L", "note": "N", "agg": "max", "format": "sci"}]
    ms = [method("a", [True, True]), method("b", [True, True], errors={"y_max": float("inf")})]
    out = benchboard.aggregate_metrics(specs, ms)
    assert out[0] == {"key": "worst", "label": "L", "note": "N", "format": "sci", "value": 1e300}
    assert out[1]["value"] is None


def test_totals_unknown_cost_stays_unknown():
    e = entry(methods=[method("a", [True], cost=0.5, tin=10, tout=5), method("b", [True], cost=None, tin=1, tout=1)])
    t = benchboard.totals(e)
    assert t["cost_usd"] is None and t["input_tokens"] == 11 and t["output_tokens"] == 6 and t["wall_s"] == 120.0


def test_ranked_by_score_then_id_and_full_before_partial():
    lab = ["a", "b"]
    best = entry("e1", methods=[method("a", [True, True], cost=2.0), method("b", [True, True], cost=2.0)])
    cheap = entry("e2", methods=[method("a", [True, True], cost=0.1), method("b", [True, False], cost=0.1)])
    cheaper_same = entry("e3", methods=[method("a", [True, True], cost=0.5), method("b", [True, True], cost=0.5)])
    partial = entry("e4", methods=[method("a", [True, True])])
    r = benchboard.ranked([cheap, partial, best, cheaper_same], lab)
    assert [e["id"] for e in r["full"]] == ["e1", "e3", "e2"]
    assert [e["id"] for e in r["partial"]] == ["e4"]


def test_full_follows_the_study_now():
    e = entry(methods=[method("a", [True])])
    assert benchboard.is_full(e, ["a"]) and not benchboard.is_full(e, ["a", "b"]) and not benchboard.is_full(e, [])


def write(root, e):
    d = root / "bench" / "results" / e["study"] / e["id"]
    d.mkdir(parents=True)
    (d / "entry.json").write_text(json.dumps(e))


def test_load_all_and_folder_mismatch(tmp_path):
    write(tmp_path, entry())
    assert list(benchboard.load_all(tmp_path)) == ["tiny"]
    bad = entry(eid="2026-10-15-codex-default-bbbbbb")
    d = tmp_path / "bench" / "results" / "tiny" / "wrong-name"
    d.mkdir(parents=True)
    (d / "entry.json").write_text(json.dumps(bad))
    with pytest.raises(schema.ContractError, match="do not match the folder"):
        benchboard.load_all(tmp_path)


def test_table_and_board(tiny_study):
    root = tiny_study.parents[1]
    assert benchboard.table(root) == "No bench entries yet."
    write(root, entry(label="my | AGENTS.md", methods=[method("exact", [True, False], cost=0.25, tin=1500, tout=500)]))
    text = benchboard.table(root)
    assert "| 1 | codex | my \\| AGENTS.md | 1/2 | 1 min | 2k | $0.25 |" in text
    assert "not verified" in text and "not reviewed" in text
    rows = benchboard.board(root, "https://github.com/o/r", "deadbeef")["tiny"]["full"]
    assert rows[0]["url"] == "https://github.com/o/r/tree/deadbeef/bench/results/tiny/2026-10-15-codex-default-aaaaaa"
    assert rows[0]["passed"] == 1 and rows[0]["expected"] == 2 and rows[0]["entrant"] == "codex"
    assert benchboard.board(root, None, "deadbeef")["tiny"]["full"][0]["url"] is None

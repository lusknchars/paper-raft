import pytest

from raft import bench, live, schema
from test_bench_cli import tiny  # noqa: F401  (fake agent fixture: one method `exact`, two runs)


def test_bench_session_counts_methods_and_runs(tiny):  # noqa: F811
    root, cmd = tiny
    seen = []
    dest = bench.run_bench(root, "tiny", "command", cmd=cmd, timeout=60, run_timeout=60,
                           out_dir=root / "out", log=lambda s: None, on_live=seen.append)
    for d in seen:
        schema.check("live", d)
    s = live.sessions(root)[0]
    assert s["kind"] == "bench" and s["state"] == "finished" and str(dest) in s["next"]
    methods = [st for st in s["steps"] if st["id"].startswith("implement-")]
    runs = [st for st in s["steps"] if st["id"].startswith("run-")]
    assert len(methods) == 1 and len(runs) == 2 and all(r["method"] == "exact" for r in runs)
    assert s["units"]["total"] == len(methods) + len(runs) == s["units"]["done"]
    r = s["results"]
    assert r["passed"] + r["failed"] == r["expected"] == len(runs) and 0 <= r["score"] <= 1


def test_bench_session_stops_when_the_study_changes(tiny, monkeypatch):  # noqa: F811
    root, cmd = tiny
    # clean while the pre-flight checks run; dirty once the session exists (i.e. after the agent ran)
    monkeypatch.setattr(bench.provenance, "is_dirty", lambda *a, **k: bool(live.sessions(root)))
    with pytest.raises(SystemExit):
        bench.run_bench(root, "tiny", "command", cmd=cmd, timeout=60, run_timeout=60, out_dir=root / "out",
                        log=lambda s: None)
    s = live.sessions(root)[0]
    assert s["state"] == "stopped" and "nothing was graded" in s["message"]

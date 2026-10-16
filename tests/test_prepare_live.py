import pytest

from raft import live, schema
from test_prepare import env, run  # noqa: F401  (env is a fixture)


def _one(root):
    got = live.sessions(root)
    assert len(got) == 1
    return got[0]


def test_prepare_session_ends_finished_at_100_percent(env):  # noqa: F811
    root, cmd = env
    seen = []
    run(root, cmd, on_live=seen.append)
    for d in seen:
        schema.check("live", d)
    s = _one(root)
    assert s["state"] == "finished" and s["next"] == "uv run raft approve --study tiny"
    assert s["units"]["done"] == s["units"]["total"]
    ids = [st["id"] for st in s["steps"]]
    assert ids == ["intake", "extract", "build-1", "attack-1"] and s["units"]["total"] == 4
    assert s["agents"] == {"builder": {"tool": "command", "model": None}, "attacker": {"tool": "command", "model": None}}
    assert s["results"]["holes"] == 0
    assert s["results"]["rounds"][0]["tried"] == s["results"]["rounds"][0]["blocked"] == 1
    assert any(st["state"] == "running" for d in seen for st in d["steps"])


def test_prepare_resume_counts_finished_steps_as_done(env):  # noqa: F811
    root, cmd = env
    run(root, cmd)
    run(root, cmd)
    s = live.sessions(root)[0]
    assert [st["id"] for st in s["steps"]] == ["intake", "extract", "build", "attack"]
    assert s["units"]["done"] == s["units"]["total"] == 4


def test_prepare_session_stops_with_the_message(env, monkeypatch):  # noqa: F811
    root, cmd = env
    monkeypatch.setenv("FAKE_MODE", "silent")
    with pytest.raises(SystemExit):
        run(root, cmd)
    s = _one(root)
    assert s["state"] == "stopped" and "does not hold after 2 builder tries" in s["message"]
    assert [st["id"] for st in s["steps"]][-2:] == ["build-1", "build-2"]
    assert s["steps"][-1]["state"] == "failed"
    assert s["units"]["total"] == 3 + 3 + 1  # intake, extract, build, 3 rounds, plus the retry


def test_prepare_session_stops_when_an_agent_tampers_mid_step(env, monkeypatch):  # noqa: F811
    root, cmd = env
    monkeypatch.setenv("FAKE_MODE", "forge")
    with pytest.raises(SystemExit):
        run(root, cmd)
    s = _one(root)
    assert s["state"] == "stopped" and "checker-approval.json" in s["message"]
    assert all(st["state"] != "running" for st in s["steps"])


def test_prepare_holes_rounds_and_fixes_are_recorded(env, monkeypatch):  # noqa: F811
    root, cmd = env
    monkeypatch.setenv("FAKE_MODE", "holes")
    with pytest.raises(SystemExit):
        run(root, cmd)
    s = _one(root)
    assert [r["blocked"] for r in s["results"]["rounds"]] == [0, 0, 0]
    assert [st["id"] for st in s["steps"] if st["id"].startswith("fix-")] == ["fix-1", "fix-2"]
    assert s["results"]["holes"] > 0

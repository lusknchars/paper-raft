import json
import shlex
import sys

import pytest
from conftest import commit_all

from raft import bench, cli, schema

FAKE = r'''
import os, sys, time
from pathlib import Path
brief, ws, method = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
mode = os.environ.get("FAKE_MODE", "good")
assert Path(brief).read_text().startswith("# bench")
d = ws / "studies" / "tiny" / "methods" / method
print('{"type": "note", "mode": "%s"}' % mode)
if mode == "sleep":
    time.sleep(60)
if mode in ("good", "cheat"):
    d.mkdir(parents=True, exist_ok=True)
    body = "    xs = np.array([i / (setup.n - 1) for i in range(setup.n)])\n    return {'y': xs * xs}\n"
    if mode == "cheat":
        body = "    return {'y': open('reference.json').read()}\n"
    (d / "solver.py").write_text("import numpy as np\n\n\ndef solve(setup):\n" + body)
'''


@pytest.fixture
def tiny(tiny_git_study, monkeypatch, tmp_path):
    root = tiny_git_study.parents[1]
    fake = tmp_path / "fake_agent.py"
    fake.write_text(FAKE)
    monkeypatch.chdir(root)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(fake))} {{brief}} {{workspace}} {{method}}"
    return root, cmd


def only_entry(root):
    (d,) = bench.entry_dirs(root)
    return d, json.loads((d / "entry.json").read_text())


def test_bench_writes_a_valid_entry(tiny, capsys):
    root, cmd = tiny
    assert cli.main(["bench", "--agent", "command", "--cmd", cmd, "--label", "fake v1"]) == 0
    assert "score 2/2" in capsys.readouterr().out
    d, e = only_entry(root)
    schema.check("bench-entry", e)
    assert d.parent == root / "bench" / "results" / "tiny" and d.name == e["id"]
    assert e["id"].startswith(e["created_at"][:10] + "-command-default-")
    assert e["entrant"]["label"] == "fake v1" and e["entrant"]["command"] == cmd
    assert e["score"] == {"passed": 2, "expected": 2}
    (m,) = e["methods"]
    assert m["agent_exit"] == 0 and m["timed_out"] is False and m["usage"]["cost_usd"] is None
    assert (d / "methods" / "exact" / "solver.py").is_file()
    assert '"mode": "good"' in (d / "transcript" / "exact.jsonl").read_text()


def test_verify_passes_then_catches_an_edit(tiny, capsys):
    root, cmd = tiny
    cli.main(["bench", "--agent", "command", "--cmd", cmd])
    d, e = only_entry(root)
    assert cli.main(["bench", "--verify"]) == 0
    assert cli.main(["bench", "--verify", str(d)]) == 0
    e["methods"][0]["runs"][0]["errors"]["y_max"] = 0.5
    (d / "entry.json").write_text(json.dumps(e))
    assert cli.main(["bench", "--verify", str(d)]) == 1
    assert "errors differ" in capsys.readouterr().out


def test_verify_catches_an_inflated_score(tiny, capsys):
    root, cmd = tiny
    cli.main(["bench", "--agent", "command", "--cmd", cmd])
    d, e = only_entry(root)
    for r in e["methods"][0]["runs"]:
        r["pass"] = False
    (d / "entry.json").write_text(json.dumps(e))
    assert cli.main(["bench", "--verify", str(d)]) == 1
    out = capsys.readouterr().out
    assert "rerun gives" in out and "score does not match" in out


def test_problem_changed_since_entry(tiny, capsys):
    root, cmd = tiny
    cli.main(["bench", "--agent", "command", "--cmd", cmd])
    sd = root / "studies" / "tiny"
    (sd / "problem" / "setup.py").write_text((sd / "problem" / "setup.py").read_text() + "\n# v2\n")
    commit_all(root, "problem v2")
    assert cli.main(["bench", "--verify"]) == 1
    assert "problem changed since this entry" in capsys.readouterr().out


def test_dirty_problem_refuses_to_start(tiny):
    root, cmd = tiny
    (root / "studies" / "tiny" / "problem" / "setup.py").write_text("# dirty\n")
    with pytest.raises(SystemExit, match="uncommitted changes"):
        cli.main(["bench", "--agent", "command", "--cmd", cmd])


def test_agent_that_writes_nothing_scores_zero(tiny, monkeypatch):
    root, cmd = tiny
    monkeypatch.setenv("FAKE_MODE", "nothing")
    assert cli.main(["bench", "--agent", "command", "--cmd", cmd]) == 0
    _, e = only_entry(root)
    assert e["score"] == {"passed": 0, "expected": 2}
    assert {r["reason"] for r in e["methods"][0]["runs"]} == {"no solver.py"}


def test_cheating_agent_fails_the_guard(tiny, monkeypatch):
    root, cmd = tiny
    monkeypatch.setenv("FAKE_MODE", "cheat")
    cli.main(["bench", "--agent", "command", "--cmd", cmd])
    _, e = only_entry(root)
    assert e["methods"][0]["guard"] and e["score"]["passed"] == 0


def test_timeout_is_recorded(tiny, monkeypatch):
    root, cmd = tiny
    monkeypatch.setenv("FAKE_MODE", "sleep")
    assert cli.main(["bench", "--agent", "command", "--cmd", cmd, "--timeout", "2s"]) == 0
    _, e = only_entry(root)
    assert e["methods"][0]["timed_out"] is True and e["methods"][0]["agent_exit"] is None


def test_table_prints_the_entry(tiny, capsys):
    root, cmd = tiny
    cli.main(["bench", "--agent", "command", "--cmd", cmd, "--label", "fake v1"])
    capsys.readouterr()
    assert cli.main(["bench", "--table"]) == 0
    assert "| 1 | command | fake v1 | 2/2 |" in capsys.readouterr().out


@pytest.mark.parametrize("argv, msg", [
    (["bench"], "bench needs --agent"),
    (["bench", "--agent", "command", "--cmd", "x {brief}", "--timeout", "soon"], "not a duration"),
])
def test_bench_usage_errors(tiny, argv, msg, capsys):
    with pytest.raises(SystemExit):
        cli.main(argv)
    assert msg in capsys.readouterr().err


def test_unknown_method_message(tiny):
    with pytest.raises(SystemExit, match="unknown method"):
        cli.main(["bench", "--agent", "command", "--cmd", "x {brief}", "--methods", "nope"])


def test_verify_with_no_entries(tiny, capsys):
    assert cli.main(["bench", "--verify"]) == 0
    assert "no bench entries" in capsys.readouterr().out

"""raft doctor: is each tool installed, logged in, and able to do a trivial task, before a long run starts."""
from datetime import datetime, timedelta, timezone

import pytest

from fake_tools import install
from raft import cli, doctor, prepare
from test_prepare import env, run  # noqa: F401  (env is a fixture)

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
CODEX = [("codex", None, False)]


def one(root, tools=CODEX, **kw):
    (c,) = doctor.check_tools(root, tools, **kw)
    return c


def test_a_working_tool_passes(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    checks = doctor.check_tools(tmp_path, [("codex", None, False), ("claude-code", None, False)], try_=True, now=T0)
    assert [c.ok for c in checks] == [True, True]
    assert "codex-cli 9.9.9" in checks[0].line and "9.9.9 (Claude Code)" in checks[1].line


def test_a_missing_tool(tmp_path, monkeypatch):
    b = install(tmp_path, monkeypatch, only=True)
    (b / "codex").unlink()
    c = one(tmp_path)
    assert not c.ok and "Codex: `codex` is not installed or not on PATH" in c.line


def test_not_logged_in(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_LOGIN", "0")
    c = one(tmp_path)
    assert not c.ok and "run `codex login`" in c.line
    assert "run `claude auth login`" in one(tmp_path, [("claude-code", None, False)]).line


def test_a_local_model_needs_no_login(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_LOGIN", "0")
    assert one(tmp_path, [("codex", "gpt-oss:20b", True)], now=T0).ok


@pytest.mark.parametrize("mode, expect", [("codemode", "Codex's shell tool is failing"),
                                          ("silent", "Codex printed nothing"),
                                          ("nochat", "did not run `echo raft-ok` and reply raft-ok")])
def test_try_failures(tmp_path, monkeypatch, mode, expect):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_TRY", mode)
    c = one(tmp_path, now=T0)
    assert not c.ok and expect in c.line


def test_a_hanging_tool_is_stopped_at_the_limit(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_TRY", "hang")
    c = one(tmp_path, try_timeout=2, now=T0)
    assert not c.ok and "did not finish the test task within 2s" in c.line


def test_without_try_only_install_and_login_are_checked(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_TRY", "silent")
    monkeypatch.setenv("FAKE_CALLS", str(tmp_path / "calls"))
    assert one(tmp_path, try_=False).ok and not (tmp_path / "calls").exists()


def test_a_pass_is_cached_for_twelve_hours_per_version(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    calls = tmp_path / "calls"
    monkeypatch.setenv("FAKE_CALLS", str(calls))
    count = lambda: calls.read_text().count("codex exec") if calls.exists() else 0  # noqa: E731
    one(tmp_path, now=T0)
    one(tmp_path, now=T0 + timedelta(hours=11))
    assert count() == 1
    one(tmp_path, now=T0 + timedelta(hours=13))
    assert count() == 2
    monkeypatch.setenv("FAKE_VERSION", "codex-cli 10.0.0")
    one(tmp_path, now=T0 + timedelta(hours=13, minutes=1))
    assert count() == 3


def test_a_corrupt_cache_is_ignored(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    (tmp_path / ".raft").mkdir()
    (tmp_path / ".raft" / "doctor.json").write_text("{not json")
    assert one(tmp_path, now=T0).ok


def test_command_agents_are_skipped(tmp_path):
    assert doctor.check_tools(tmp_path, [("command", None, False)]) == []


def test_preflight_stops_and_names_the_other_tool(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_TRY", "codemode")  # breaks codex's try; claude's fake has no code-mode line
    lines = []
    with pytest.raises(SystemExit) as e:
        doctor.preflight(tmp_path, CODEX, try_=True, log=lines.append, now=T0)
    msg = str(e.value)
    assert msg.startswith("raft: a tool check failed before any step ran")
    assert "Codex's shell tool is failing" in msg and "Or switch to Claude Code (installed and logged in)." in msg
    assert lines and lines[0].startswith("✗ ")


def test_prepare_runs_the_preflight(env, monkeypatch):  # noqa: F811
    root, cmd = env
    seen = []
    monkeypatch.setattr(doctor, "preflight", lambda root, tools, **kw: seen.append((tools, kw["try_"])))
    run(root, cmd)
    run(root, cmd, try_tools=False)
    assert seen[0][1] is True and seen[1][1] is False
    assert ("command", None, False) in seen[0][0]


def test_cli_doctor(tmp_path, tiny_git_study, monkeypatch, capsys):
    install(tmp_path, monkeypatch)
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["doctor", "--agent", "codex", "--try"]) == 0
    assert "✓ Codex: codex-cli 9.9.9" in capsys.readouterr().out
    assert cli.main(["doctor"]) == 0  # both tools, install and login only
    monkeypatch.setenv("FAKE_LOGIN", "0")
    assert cli.main(["doctor", "--agent", "codex"]) == 1


def test_cli_doctor_finds_home_paths_in_a_studys_transcripts(tiny_git_study, monkeypatch, capsys):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    monkeypatch.setenv("HOME", "/Users/someone")
    t = tiny_git_study / "checker" / "transcripts"
    t.mkdir(parents=True)
    (t / "build-1.jsonl").write_text('{"p": "/Users/someone/x"}\n')
    assert cli.main(["doctor", "--study", "tiny"]) == 1
    assert "studies/tiny/checker/transcripts/build-1.jsonl" in capsys.readouterr().out

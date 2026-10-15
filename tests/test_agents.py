import json
import os
import shlex
import sys
import time

import pytest

from raft import agents

CLAUDE_OUT = "\n".join([
    json.dumps({"type": "system", "subtype": "init"}),
    json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}}),
    json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 7, "total_cost_usd": 0.4213,
                "usage": {"input_tokens": 100, "cache_creation_input_tokens": 2000, "cache_read_input_tokens": 30000,
                          "output_tokens": 4500}}),
])
CODEX_OUT = "\n".join([
    json.dumps({"type": "thread.started", "thread_id": "t"}),
    json.dumps({"type": "turn.started"}),
    "not json at all",
    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1200, "cached_input_tokens": 800, "output_tokens": 300}}),
    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 50}}),
])


def test_claude_argv(tmp_path):
    args, stdin = agents.argv("claude-code", tmp_path, tmp_path / "b.md", "m", model="opus")
    assert args[:2] == ["claude", "-p"] and stdin is True
    assert args[args.index("--output-format") + 1] == "stream-json" and "--verbose" in args
    assert args[args.index("--disallowedTools") + 1] == "WebFetch,WebSearch"
    assert args[args.index("--model") + 1] == "opus"
    assert "--model" not in agents.argv("claude-code", tmp_path, tmp_path / "b.md", "m")[0]


def test_codex_argv(tmp_path):
    args, stdin = agents.argv("codex", tmp_path, tmp_path / "b.md", "m", model="gpt-oss:20b", oss=True)
    assert args[:3] == ["codex", "exec", "--json"] and stdin is True and args[-1] == "-"
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert args[args.index("-C") + 1] == str(tmp_path)
    assert args[args.index("-m") + 1] == "gpt-oss:20b" and "--oss" in args
    assert args[args.index("--local-provider") + 1] == "ollama"
    plain = agents.argv("codex", tmp_path, tmp_path / "b.md", "m")[0]
    assert "-m" not in plain and "--oss" not in plain


def test_command_argv_fills_placeholders(tmp_path):
    args, stdin = agents.argv("command", tmp_path / "ws", tmp_path / "b.md", "smc-rb",
                              cmd="my-agent --task {brief} --dir {workspace} --name {method}")
    assert args == ["my-agent", "--task", str(tmp_path / "b.md"), "--dir", str(tmp_path / "ws"), "--name", "smc-rb"]
    assert stdin is False


@pytest.mark.parametrize("kw, msg", [
    ({"agent": "gemini"}, "--agent must be one of"),
    ({"agent": "command"}, "--cmd goes with --agent command"),
    ({"agent": "codex", "cmd": "x {brief}"}, "--cmd goes with --agent command"),
    ({"agent": "claude-code", "oss": True}, "--oss works with --agent codex only"),
    ({"agent": "command", "cmd": "x"}, "must contain {brief}"),
])
def test_check_rejects(kw, msg):
    agent = kw.pop("agent")
    with pytest.raises(SystemExit, match=msg):
        agents.check(agent, **kw)


def test_parse_claude_usage():
    u = agents.parse_usage("claude-code", CLAUDE_OUT)
    assert u == {"input_tokens": 32100, "cached_input_tokens": 30000, "output_tokens": 4500, "cost_usd": 0.4213,
                 "turns": 7}


def test_parse_codex_usage():
    u = agents.parse_usage("codex", CODEX_OUT)
    assert u == {"input_tokens": 1300, "cached_input_tokens": 800, "output_tokens": 350, "cost_usd": None, "turns": 2}


def test_parse_nothing_reported():
    blank = {"input_tokens": None, "cached_input_tokens": None, "output_tokens": None, "cost_usd": None, "turns": None}
    assert agents.parse_usage("claude-code", "garbage\n") == blank
    assert agents.parse_usage("codex", "") == blank
    assert agents.parse_usage("command", CLAUDE_OUT) == blank


def py(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)} {{brief}}"


def test_run_records_exit_and_transcript(tmp_path):
    brief = tmp_path / "b.md"
    brief.write_text("task")
    r = agents.run("command", brief, tmp_path, "m", cmd=py("import sys; print(open(sys.argv[1]).read()); sys.exit(3)"),
                   timeout=30, transcript=tmp_path / "t.jsonl")
    assert r["exit"] == 3 and r["timed_out"] is False and r["wall_s"] >= 0
    assert (tmp_path / "t.jsonl").read_text().strip() == "task"
    assert (tmp_path / "t.stderr.txt").is_file()


def test_timeout_kills_the_whole_group(tmp_path):
    brief = tmp_path / "b.md"
    brief.write_text("task")
    pidfile = tmp_path / "child.pid"
    code = (f"import subprocess, sys, time; c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({str(pidfile)!r}, 'w').write(str(c.pid)); time.sleep(60)")
    r = agents.run("command", brief, tmp_path, "m", cmd=py(code), timeout=2, transcript=tmp_path / "t.jsonl")
    assert r["timed_out"] is True and r["exit"] is None and r["wall_s"] < 20
    child = int(pidfile.read_text())
    for _ in range(40):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the agent's child process outlived the timeout")


def test_missing_tool_is_a_clean_exit(tmp_path):
    brief = tmp_path / "b.md"
    brief.write_text("task")
    with pytest.raises(SystemExit, match="no-such-agent-xyz not found"):
        agents.run("command", brief, tmp_path, "m", cmd="no-such-agent-xyz {brief}", timeout=5,
                   transcript=tmp_path / "t.jsonl")

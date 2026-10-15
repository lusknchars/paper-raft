import json
import time

from raft import live

CLAUDE = "\n".join([
    json.dumps({"type": "system", "subtype": "init"}),
    json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "I'll read the paper first."},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "papers/x.pdf"}}]}}),
    "not json",
    json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "uv run raft validate --study x"}}]}}),
    json.dumps({"type": "result", "subtype": "success"}),
])
CODEX = "\n".join([
    json.dumps({"type": "thread.started", "thread_id": "t"}),
    json.dumps({"type": "item.completed", "item": {"id": "i0", "type": "agent_message", "text": "Checking the PDF."}}),
    json.dumps({"type": "item.started", "item": {"id": "i1", "type": "command_execution", "command": "ls papers"}}),
    json.dumps({"type": "item.completed", "item": {"id": "i1", "type": "command_execution", "command": "ls papers"}}),
    json.dumps({"type": "item.completed", "item": {"id": "i2", "type": "command_execution", "command": "cat a.json"}}),
])
CODEX_STDERR = "\n".join(["2026-10-15T21:01:20Z ERROR codex_core::tools::router: error=timed out negotiating with "
                          "the code-mode host"] * 3 + ["", ""])


def test_claude_lines():
    assert live.activity_lines("claude-code", CLAUDE) == [
        "I'll read the paper first.", "Read papers/x.pdf", "Bash uv run raft validate --study x"]


def test_codex_lines_once_per_command():
    assert live.activity_lines("codex", CODEX) == ["Checking the PDF.", "$ ls papers", "$ cat a.json"]


def test_command_agent_has_no_lines_and_long_lines_are_cut():
    assert live.activity_lines("command", CLAUDE) == []
    long = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "x" * 500}})
    assert len(live.activity_lines("codex", long)[0]) <= 160


def test_stderr_tail_keeps_last_three_lines():
    tail = live.stderr_tail(CODEX_STDERR)
    assert tail.count("code-mode host") == 3 and live.stderr_tail("\n \n") is None


def test_read_tail_reads_only_the_end(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("x" * 300_000 + "\n" + CODEX)
    assert live.activity_lines("codex", live.read_tail(p))[-1] == "$ cat a.json"
    assert live.read_tail(tmp_path / "missing") == ""


def test_watching_updates_the_step_while_it_runs(tmp_path):
    s = live.Session(tmp_path, "prepare", "tiny", agents={}, total=1, interval=0)
    s.begin("extract-1", "Extract")
    t = tmp_path / "t.jsonl"
    with live.watching(s, "extract-1", "codex", t, every=0.05):
        t.write_text(CODEX)
        t.with_suffix(".stderr.txt").write_text(CODEX_STDERR)
        time.sleep(0.3)
        assert s.data["steps"][0]["activity"][-1]["text"] == "$ cat a.json"
    assert "code-mode host" in s.data["steps"][0]["stderr_tail"]


def test_watching_progress_reads_the_runner_fraction(tmp_path):
    s = live.Session(tmp_path, "bench", "tiny", agents={}, total=2, interval=0)
    s.begin("run-a", "a")
    p = tmp_path / "a.json"
    with live.watching_progress(s, p, every=0.05):
        p.write_text(json.dumps({"state": "running", "fraction": 0.4}))
        time.sleep(0.3)
        assert s.data["units"]["done"] == 0.4
        p.write_text("{broken")
        time.sleep(0.15)

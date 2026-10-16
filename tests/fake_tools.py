"""Fake `codex` and `claude` executables, steered by environment variables:
FAKE_LOGIN=0 (not logged in), FAKE_TRY=ok|silent|codemode|hang, FAKE_VERSION, FAKE_CALLS=<file> (one line per run)."""
import os
import sys
from pathlib import Path

COMMON = r'''#!PYTHON
import json, os, sys, time
a = sys.argv[1:]
def calls(what):
    if os.environ.get("FAKE_CALLS"):
        with open(os.environ["FAKE_CALLS"], "a") as f:
            f.write(what + "\n")
def out(events):
    print("\n".join(json.dumps(e) for e in events))
'''

CODEX = COMMON + r'''
if a[:1] == ["--version"]:
    print(os.environ.get("FAKE_VERSION", "codex-cli 9.9.9")); sys.exit(0)
if a[:2] == ["login", "status"]:
    ok = os.environ.get("FAKE_LOGIN", "1") == "1"
    print("Logged in using ChatGPT" if ok else "Not logged in"); sys.exit(0 if ok else 1)
if a[:1] == ["exec"]:
    calls("codex exec"); sys.stdin.read()
    mode = os.environ.get("FAKE_TRY", "ok")
    if mode == "silent":
        sys.exit(0)
    if mode == "hang":
        time.sleep(60)
    if mode == "codemode":
        print("ERROR codex_core::tools::router: error=timed out negotiating with the code-mode host", file=sys.stderr)
    ev = [{"type": "thread.started"}, {"type": "turn.started"}]
    if mode == "ok":
        c = {"id": "c1", "type": "command_execution", "command": "echo raft-ok"}
        ev += [{"type": "item.started", "item": c}, {"type": "item.completed", "item": c},
               {"type": "item.completed", "item": {"id": "m1", "type": "agent_message", "text": "raft-ok"}}]
    out(ev + [{"type": "turn.completed", "usage": {}}]); sys.exit(0)
sys.exit(2)
'''

CLAUDE = COMMON + r'''
if a[:1] == ["--version"]:
    print(os.environ.get("FAKE_VERSION", "9.9.9 (Claude Code)")); sys.exit(0)
if a[:2] == ["auth", "status"]:
    sys.exit(0 if os.environ.get("FAKE_LOGIN", "1") == "1" else 1)
if "-p" in a:
    calls("claude -p"); sys.stdin.read()
    mode = os.environ.get("FAKE_TRY", "ok")
    if mode == "silent":
        sys.exit(0)
    if mode == "hang":
        time.sleep(60)
    ev = []
    if mode == "ok":
        ev = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
                                                             "input": {"command": "echo raft-ok"}}]}},
              {"type": "assistant", "message": {"content": [{"type": "text", "text": "raft-ok"}]}}]
    out(ev + [{"type": "result", "subtype": "success", "is_error": False, "result": "raft-ok"}]); sys.exit(0)
sys.exit(2)
'''


def install(tmp_path: Path, monkeypatch, only: bool = False) -> Path:
    """Put fake codex and claude first on PATH (or alone on it, with only=True). Returns the bin folder."""
    b = tmp_path / "fakebin"
    b.mkdir(exist_ok=True)
    for name, body in (("codex", CODEX), ("claude", CLAUDE)):
        p = b / name
        p.write_text(body.replace("#!PYTHON", "#!" + sys.executable))
        p.chmod(0o755)
    monkeypatch.setenv("PATH", str(b) if only else f"{b}{os.pathsep}{os.environ.get('PATH', '')}")
    return b

"""How raft bench starts each agent tool headless, and what it reads back about tokens and cost.

Tokens and cost are whatever the tool reports about itself; the bench labels them self-reported.
"""
import json
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

AGENTS = ("claude-code", "codex", "command")
EXE = {"claude-code": "claude", "codex": "codex"}
CLAUDE_TOOLS = "Bash,Read,Edit,Write,Glob,Grep"
ISOLATION = {
    "claude-code": "web tools disallowed; the shell is not network-isolated",
    "codex": "codex sandbox workspace-write (network off unless the user's codex config turns it on)",
    "command": "none enforced by raft",
}
NAMES = {"codex": "Codex", "claude-code": "Claude Code", "command": "your command"}
OTHER = {"codex": "claude-code", "claude-code": "codex"}
CODE_MODE = "timed out negotiating with the code-mode host"  # tests/fixtures/tool-failures/codex-code-mode.stderr.txt
REFUSED = "flagged for possible"  # tests/fixtures/tool-failures/codex-refused.jsonl


@dataclass(frozen=True)
class Problem:
    """What went wrong with the tool itself in a step, in plain words, with what to do."""
    kind: str  # refused | tool-broken | tool-error | no-output
    tool: str
    detail: str
    advice: str

    def headline(self, step: str) -> str:
        t = NAMES.get(self.tool, self.tool)
        return {"refused": f"{t} refused the {step} brief (its content filter flagged it)",
                "tool-broken": f"{t}'s shell tool is failing",
                "tool-error": f"{t} stopped with an error",
                "no-output": f"{t} printed nothing"}[self.kind]

    def as_dict(self, role: str, step: str) -> dict:
        return {"kind": self.kind, "tool": self.tool, "role": role, "detail": self.detail,
                "headline": self.headline(step)}


def _cut(text) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= 300 else s[:299] + "…"


def diagnose(agent: str, text: str, stderr: str, exit_code) -> "Problem | None":
    """Read a step's transcript and stderr. None when the tool itself looks fine (the step's files are judged
    elsewhere). Unknown tools (`command`) are never diagnosed."""
    if agent not in EXE:
        return None
    t = NAMES[agent]
    check = f"Check {t} with `uv run raft doctor --agent {agent} --try`, then run the command below."
    for line in stderr.splitlines():
        if CODE_MODE in line:
            return Problem("tool-broken", agent, _cut(line),
                           f"Update or restart {t}, then check it with `uv run raft doctor --agent {agent} --try`.")
    events = list(_events(text)) if exit_code is not None else []  # a timeout is reported as a timeout
    if agent == "codex":
        bad = [i for i, e in enumerate(events) if e.get("type") in ("error", "turn.failed")]
        if bad and not any(e.get("type") == "turn.completed" for e in events[bad[-1] + 1:]):
            e = events[bad[-1]]
            msg = str((e.get("message") if e["type"] == "error" else (e.get("error") or {}).get("message")) or e["type"])
            if REFUSED in msg:
                return Problem("refused", agent, _cut(msg), f"Run this step with {NAMES[OTHER[agent]]} instead.")
            return Problem("tool-error", agent, _cut(msg), check)
    else:
        results = [e for e in events if e.get("type") == "result"]
        if results and results[-1].get("is_error"):
            r = results[-1]
            return Problem("tool-error", agent, _cut(r.get("result") or r.get("subtype") or "error"), check)
    if exit_code is not None and not text.strip():
        last = stderr.strip().splitlines()[-1] if stderr.strip() else "no output at all"
        return Problem("no-output", agent, _cut(last), check)
    return None


def check(agent: str, *, model=None, oss=False, cmd=None) -> None:
    if agent not in AGENTS:
        raise SystemExit(f"raft: --agent must be one of {', '.join(AGENTS)}")
    if (agent == "command") != bool(cmd):
        raise SystemExit("raft: --cmd goes with --agent command, and only with it")
    if oss and agent != "codex":
        raise SystemExit("raft: --oss works with --agent codex only")
    if agent == "command" and "{brief}" not in cmd:
        raise SystemExit("raft: --cmd must contain {brief}, the path of the task file")


def argv(agent: str, workspace: Path, brief: Path, method: str, *, model=None, oss=False,
         cmd=None) -> tuple[list[str], bool]:
    if agent == "claude-code":
        args = ["claude", "-p", "--output-format", "stream-json", "--verbose",
                "--allowedTools", CLAUDE_TOOLS, "--disallowedTools", "WebFetch,WebSearch"]
        return args + (["--model", model] if model else []), True
    if agent == "codex":
        args = ["codex", "exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check",
                "-C", str(workspace)]
        return args + (["-m", model] if model else []) + (["--oss", "--local-provider", "ollama"] if oss else []) + ["-"], True
    fill = {"{brief}": str(brief), "{workspace}": str(workspace), "{method}": method}
    out = []
    for part in shlex.split(cmd):
        for k, v in fill.items():
            part = part.replace(k, v)
        out.append(part)
    return out, False


def tool_version(agent: str) -> str | None:
    if agent not in EXE:
        return None
    try:
        out = subprocess.run([EXE[agent], "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (out.stdout or out.stderr).strip().splitlines()
    return lines[0][:120] if lines else None


def _blank() -> dict:
    return {"input_tokens": None, "cached_input_tokens": None, "output_tokens": None, "cost_usd": None, "turns": None}


def _events(text: str):
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _int(v) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else 0


def parse_usage(agent: str, text: str) -> dict:
    u = _blank()
    if agent == "claude-code":
        result = None
        for e in _events(text):
            if e.get("type") == "result":
                result = e
        if result is not None:
            us = result.get("usage") or {}
            u["input_tokens"] = sum(_int(us.get(k)) for k in
                                    ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            u["cached_input_tokens"] = _int(us.get("cache_read_input_tokens"))
            u["output_tokens"] = _int(us.get("output_tokens"))
            cost = result.get("total_cost_usd")
            ok = isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0
            u["cost_usd"] = round(float(cost), 6) if ok else None
            u["turns"] = _int(result["num_turns"]) if "num_turns" in result else None
    elif agent == "codex":
        turns = [e for e in _events(text) if e.get("type") == "turn.completed"]
        if turns:
            for k in ("input_tokens", "cached_input_tokens", "output_tokens"):
                u[k] = sum(_int((e.get("usage") or {}).get(k)) for e in turns)
            u["turns"] = len(turns)
    return u


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def run(agent: str, brief: Path, workspace: Path, method: str, *, model=None, oss=False, cmd=None,
        timeout: float, transcript: Path) -> dict:
    """Start the tool in the workspace, feed it the brief, stop it at the timeout (with everything it started)."""
    args, on_stdin = argv(agent, Path(workspace), Path(brief), method, model=model, oss=oss, cmd=cmd)
    transcript = Path(transcript)
    timed_out = False
    t0 = time.monotonic()
    with open(transcript, "wb") as out, open(transcript.with_suffix(".stderr.txt"), "wb") as err:
        try:
            proc = subprocess.Popen(args, cwd=workspace, stdin=subprocess.PIPE if on_stdin else subprocess.DEVNULL,
                                    stdout=out, stderr=err, start_new_session=True)
        except FileNotFoundError:
            raise SystemExit(f"raft: {args[0]} not found; install it or choose another --agent") from None
        try:
            proc.communicate(input=Path(brief).read_bytes() if on_stdin else None, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(proc)
        except BaseException:
            _kill(proc)
            raise
        if not timed_out:
            try:  # the tool exited; stop anything it left running in its group
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    return {"exit": None if timed_out else proc.returncode, "timed_out": timed_out,
            "wall_s": round(time.monotonic() - t0, 1),
            "usage": parse_usage(agent, transcript.read_text(errors="replace"))}

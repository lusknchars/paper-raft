"""raft doctor: check the agent tools before a long run. Installed, logged in, and (with the try) able to run one
shell command and answer, which catches a broken tool before it costs a 45-minute step."""
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import agents, bench, live

CACHE = Path(".raft") / "doctor.json"
CACHE_FOR = timedelta(hours=12)
TRY_BRIEF = "Run `echo raft-ok` in the shell, then reply with exactly: raft-ok\n"
LOGIN = {"codex": ["codex", "login", "status"], "claude-code": ["claude", "auth", "status"]}
LOGIN_HINT = {"codex": "codex login", "claude-code": "claude auth login"}


@dataclass(frozen=True)
class Check:
    tool: str
    ok: bool
    line: str


def _load(root: Path) -> dict:
    try:
        data = json.loads((Path(root) / CACHE).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(root: Path, data: dict) -> None:
    try:
        (Path(root) / CACHE).parent.mkdir(parents=True, exist_ok=True)
        (Path(root) / CACHE).write_text(json.dumps(data, indent=1) + "\n")
    except OSError:
        pass  # the cache is a convenience; a read-only disk only means the try runs again


def _logged_in(agent: str) -> bool:
    try:
        return subprocess.run(LOGIN[agent], capture_output=True, text=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def try_tool(agent: str, model=None, oss: bool = False, timeout: float = 120.0) -> str | None:
    """Run the trivial task. None when it passed, else why not."""
    with tempfile.TemporaryDirectory(prefix="raft-doctor-") as tmp:
        brief, t = Path(tmp) / "brief.md", Path(tmp) / "t.jsonl"
        brief.write_text(TRY_BRIEF)
        ws = Path(tmp) / "ws"
        ws.mkdir()
        r = agents.run(agent, brief, ws, "doctor", model=model, oss=oss, timeout=timeout, transcript=t)
        text = t.read_text(errors="replace")
        err = t.with_suffix(".stderr.txt").read_text(errors="replace") if t.with_suffix(".stderr.txt").is_file() else ""
    if r["timed_out"]:
        return f"did not finish the test task within {timeout:.0f}s"
    problem = agents.diagnose(agent, text, err, r["exit"])
    if problem:
        return f"{problem.headline('test')}: {problem.detail}"
    lines = live.activity_lines(agent, text)
    ran = any("echo raft-ok" in x for x in lines)
    said = any("raft-ok" in x and "echo" not in x for x in lines)
    return None if r["exit"] == 0 and ran and said else "did not run `echo raft-ok` and reply raft-ok"


def _check(root: Path, agent: str, model, oss: bool, try_: bool, timeout: float, now) -> Check:
    name, exe = agents.NAMES[agent], agents.EXE[agent]
    if shutil.which(exe) is None:
        return Check(agent, False, f"{name}: `{exe}` is not installed or not on PATH")
    ver = agents.tool_version(agent) or "unknown version"
    if not oss and not _logged_in(agent):
        return Check(agent, False, f"{name}: {ver}, not logged in; run `{LOGIN_HINT[agent]}` in your terminal")
    who = "local model" if oss else "logged in"
    if not try_:
        return Check(agent, True, f"{name}: {ver}, {who}")
    key = f"{agent}|{ver}|{model or ''}|{'oss' if oss else ''}"
    cache = _load(root)
    when = cache.get(key)
    try:
        fresh = when and now - datetime.fromisoformat(when) < CACHE_FOR
    except (TypeError, ValueError):
        fresh = False
    if fresh:
        return Check(agent, True, f"{name}: {ver}, {who}, did the test task at {when[:16].replace('T', ' ')}")
    why = try_tool(agent, model, oss, timeout)
    if why:
        return Check(agent, False, f"{name}: {ver}, {who}, but {why}")
    cache[key] = now.isoformat(timespec="seconds")
    _save(root, cache)
    return Check(agent, True, f"{name}: {ver}, {who}, did the test task")


def check_tools(root, tools, *, try_: bool = True, try_timeout: float = 120.0, now=None) -> list[Check]:
    now = now or datetime.now(timezone.utc)
    seen, out = set(), []
    for agent, model, oss in tools:
        if agent not in agents.EXE or (agent, model, oss) in seen:
            continue
        seen.add((agent, model, oss))
        out.append(_check(Path(root), agent, model, bool(oss), try_, try_timeout, now))
    return out


def preflight(root, tools, *, try_: bool, log, now=None) -> None:
    """Before any agent step: stop with the reason (and a tool that would work) if a tool can't do the job."""
    checks = check_tools(root, tools, try_=try_, now=now)
    for c in checks:
        log(("✓ " if c.ok else "✗ ") + c.line)
    bad = [c for c in checks if not c.ok]
    if not bad:
        return
    used = {t for t, _, _ in tools}
    alts = []
    for c in bad:
        other = agents.OTHER.get(c.tool)
        if other and other not in used and all(x.ok for x in check_tools(root, [(other, None, False)], try_=False)):
            alts.append(f"Or switch to {agents.NAMES[other]} (installed and logged in).")
    raise SystemExit("raft: a tool check failed before any step ran:\n  " + "\n  ".join(c.line for c in bad)
                     + "".join("\n" + a for a in dict.fromkeys(alts))
                     + "\nSkip the test task with --no-try only if you know the tool works.")


def home_paths(root, study: str) -> list[Path]:
    root = Path(root)
    files = list((root / "studies" / study / "checker" / "transcripts").glob("*"))
    files += list((root / "bench" / "results" / study).glob("*/transcript/*"))
    return bench.transcripts_with_home(sorted(files))

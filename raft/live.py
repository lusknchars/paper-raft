"""Live sessions: what `raft prepare` and `raft bench` are doing right now, for `raft watch`.

Each session is one JSON file in .raft/live/ (gitignored, never published), rewritten atomically. The percentage is
finished work units over total work units; nothing here guesses how far an agent is inside a step.
"""
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import agents, schema

LIVE_DIR = Path(".raft") / "live"
KEEP = 20
LINE_MAX = 160
ACTIVITY_KEEP = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clip(text: str) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= LINE_MAX else s[:LINE_MAX - 1] + "…"


class Session:
    def __init__(self, root, kind: str, study: str, *, agents: dict, total: int, title=None, arxiv=None,
                 interval: float = 0.5, on_write=None):
        started = datetime.now(timezone.utc)
        self.path = Path(root) / LIVE_DIR / f"{kind}-{study}-{started:%Y%m%dT%H%M%S%fZ}.json"
        self.interval, self.on_write = interval, on_write
        self._lock = threading.RLock()
        self._last = 0.0
        self._done, self._partial, self._t0 = 0, 0.0, {}
        self.data = {"kind": kind, "study": study, "title": title, "arxiv": arxiv, "pid": os.getpid(),
                     "started_at": started.isoformat(timespec="seconds"), "updated_at": _now(), "state": "running",
                     "agents": agents, "units": {"done": 0, "total": total}, "steps": [], "results": {},
                     "message": None, "next": None}
        self._write(force=True)

    # writing
    def _write(self, force: bool = False) -> None:
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last < self.interval:
                return
            self._last = now
            self.data["updated_at"] = _now()
            self.data["units"]["done"] = round(self._done + self._partial, 3)
            tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(self.data, ensure_ascii=False))
                os.replace(tmp, self.path)
            except OSError:  # the live file is only a view: a full or read-only disk must never kill the run
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            if self.on_write:
                self.on_write(json.loads(json.dumps(self.data)))

    def _step(self, step_id: str) -> dict:
        return next(s for s in self.data["steps"] if s["id"] == step_id)

    # steps
    def begin(self, step_id: str, label: str, *, agent=None, method=None, timeout_s=None) -> None:
        with self._lock:
            self._t0[step_id] = time.monotonic()
            self.data["steps"].append({"id": step_id, "label": label, "state": "running", "agent": agent,
                                       "method": method, "timeout_s": timeout_s, "started_at": _now(),
                                       "wall_s": None, "detail": None, "activity": [], "stderr_tail": None})
            self._write(force=True)

    def end(self, step_id: str, state: str = "done", *, detail=None, unit: bool = True) -> None:
        with self._lock:
            s = self._step(step_id)
            s["state"], s["detail"] = state, detail
            s["wall_s"] = round(time.monotonic() - self._t0.pop(step_id, time.monotonic()), 1)
            self._partial = 0.0
            if unit:
                self._done += 1
            self._write(force=True)

    def skip(self, step_id: str, label: str, detail: str) -> None:
        self.begin(step_id, label)
        self.end(step_id, detail=detail)

    def add_total(self, n: int) -> None:
        with self._lock:
            u = self.data["units"]
            u["total"] = max(self._done, u["total"] + n)
            self._write(force=True)

    def set_partial(self, fraction: float) -> None:
        with self._lock:
            self._partial = min(0.999, max(0.0, float(fraction)))
            self._write()

    def set_activity(self, step_id: str, lines: list[str], stderr_tail) -> None:
        with self._lock:
            s = self._step(step_id)
            old = [a["text"] for a in s["activity"]]
            new = [clip(x) for x in lines][-ACTIVITY_KEEP:]
            if new != old:
                stamp = {a["text"]: a["t"] for a in s["activity"]}
                s["activity"] = [{"t": stamp.get(x, _now()), "text": x} for x in new]
            s["stderr_tail"] = stderr_tail
            self._write()

    def set_results(self, **kw) -> None:
        with self._lock:
            self.data["results"].update(kw)
            self._write(force=True)

    def set_problem(self, problem: dict) -> None:
        with self._lock:
            self.data["problem"] = problem
            self._write(force=True)

    # endings
    def finish(self, next_cmd) -> None:
        with self._lock:
            self.data["state"], self.data["next"] = "finished", next_cmd
            self._write(force=True)

    def stop(self, message: str) -> None:
        with self._lock:
            for s in self.data["steps"]:
                if s["state"] == "running":
                    s["state"] = "failed"
            self._partial = 0.0  # a stop never claims half-finished work
            u = self.data["units"]
            if self._done >= u["total"]:
                u["total"] = self._done + 1  # and is never shown as 100%
            self.data["state"], self.data["message"] = "stopped", message
            self._write(force=True)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sessions(root, study=None) -> list[dict]:
    """Every readable session, newest first (at most KEEP); a running one whose process is gone is `lost`."""
    out = []
    for p in (Path(root) / LIVE_DIR).glob("*.json"):
        try:
            s = json.loads(p.read_text())
        except (OSError, ValueError):  # unreadable, not UTF-8, or not JSON
            continue
        if not isinstance(s, dict) or schema.errors("live", s) or (study and s["study"] != study):
            continue
        if s["state"] == "running" and not _alive(s["pid"]):
            s["state"] = "lost"
        s["id"] = p.stem
        out.append(s)
    out.sort(key=lambda s: (s["started_at"], s["id"]), reverse=True)
    return out[:KEEP]


def _tool_line(name, args) -> str:
    args = args if isinstance(args, dict) else {}
    for k in ("command", "file_path", "path", "pattern", "url"):
        if isinstance(args.get(k), str):
            return f"{name} {args[k]}"
    return str(name)


def activity_lines(agent: str, text: str) -> list[str]:
    """The agent's own words and actions, newest last, from its JSON event stream (unknown formats give none)."""
    out, started = [], set()
    for e in agents._events(text):
        if agent == "claude-code" and e.get("type") == "assistant":
            for c in (e.get("message") or {}).get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text" and str(c.get("text", "")).strip():
                    out.append(c["text"])
                elif c.get("type") == "tool_use":
                    out.append(_tool_line(c.get("name"), c.get("input")))
        elif agent == "codex" and e.get("type") in ("item.started", "item.completed"):
            item = e.get("item") or {}
            if item.get("type") == "agent_message" and e["type"] == "item.completed" and str(item.get("text", "")).strip():
                out.append(item["text"])
            elif item.get("type") == "command_execution" and isinstance(item.get("command"), str):
                if e["type"] == "item.started":
                    started.add(item.get("id"))
                elif item.get("id") in started:
                    continue
                out.append("$ " + item["command"])
    return [clip(x) for x in out][-ACTIVITY_KEEP:]


def stderr_tail(text: str):
    lines = [clip(x) for x in text.splitlines() if x.strip()][-3:]
    return "\n".join(lines) or None


def read_tail(path: Path, limit: int = 262_144) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - limit))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _loop(every: float, tick):
    stop = threading.Event()

    def run():
        while not stop.wait(every):
            try:
                tick()
            except Exception:  # noqa: BLE001 (a bad read must never kill the run)
                pass
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return stop, t


@contextmanager
def watching(session: Session, step_id: str, agent: str, transcript: Path, every: float = 1.0):
    """While the agent runs, copy its newest events and stderr lines into the step."""
    transcript = Path(transcript)

    def tick():
        session.set_activity(step_id, activity_lines(agent, read_tail(transcript)),
                             stderr_tail(read_tail(transcript.with_suffix(".stderr.txt"), 8192)))
    stop, t = _loop(every, tick)
    try:
        yield
    finally:
        stop.set()
        t.join()
        try:
            tick()
        except Exception:  # noqa: BLE001 (the last look must never fail the run)
            pass


@contextmanager
def watching_progress(session: Session, path: Path, every: float = 0.5):
    """While a graded run goes, count the solver's own progress(fraction) reports as part of a unit."""
    def tick():
        try:
            f = json.loads(Path(path).read_text()).get("fraction")
        except (OSError, json.JSONDecodeError, AttributeError):
            return
        if isinstance(f, (int, float)) and not isinstance(f, bool):
            session.set_partial(f)
    stop, t = _loop(every, tick)
    try:
        yield
    finally:
        stop.set()
        t.join()

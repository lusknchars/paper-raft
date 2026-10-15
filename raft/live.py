"""Live sessions: what `raft prepare` and `raft bench` are doing right now, for `raft watch`.

Each session is one JSON file in .raft/live/ (gitignored, never published), rewritten atomically. The percentage is
finished work units over total work units; nothing here guesses how far an agent is inside a step.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import schema

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
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False))
            os.replace(tmp, self.path)
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
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(s, dict) or schema.errors("live", s) or (study and s["study"] != study):
            continue
        if s["state"] == "running" and not _alive(s["pid"]):
            s["state"] = "lost"
        s["id"] = p.stem
        out.append(s)
    out.sort(key=lambda s: (s["started_at"], s["id"]), reverse=True)
    return out[:KEEP]

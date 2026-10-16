"""Paperraft's public brief for one paper (paperaft.vercel.app/papers/<id>/index.json), cached locally.

The lab never needs it to work: offline, a saved copy is used, and without one the lab's own view still shows."""
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://paperaft.vercel.app/papers"
FIELDS = ("arxiv_id", "title", "summary", "recommendation", "minimum_test", "claims", "source_url",
          "lab_reproductions", "as_of")
LABELS = {"testar": "Test it", "observar": "Watch", "nao_aplica": "Not applicable"}
FRESH = timedelta(hours=24)
_ID = re.compile(r"(?:^|arxiv:|/papers/|/abs/|/pdf/)(\d{4}\.\d{4,5})(?:v\d+)?/?$", re.I)


def parse_id(text: str) -> str | None:
    m = _ID.search((text or "").strip())
    return m.group(1) if m else None


def default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "paper-raft (+https://github.com/lusknchars/paper-raft)"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


def _keep(raw: dict, arxiv_id: str) -> dict:
    return {**{k: raw.get(k) for k in FIELDS}, "brief_url": f"{BASE}/{arxiv_id}/"}


def answer(arxiv_id: str, *, cache_dir: Path, fetch=None, now=None) -> dict:
    """{found, brief, offline, stale}. Fresh cache first, then the network, then a stale cache."""
    if parse_id(arxiv_id) != arxiv_id:
        raise ValueError(f"not an arXiv id: {arxiv_id!r}")
    now = now or datetime.now(timezone.utc)
    path = Path(cache_dir) / f"{arxiv_id}.json"
    cached = None
    try:
        cached = json.loads(path.read_text())
        at = datetime.fromisoformat(cached["fetched_at"])
        if now - at < FRESH:
            return {"found": True, "brief": cached["brief"], "offline": False, "stale": False}
    except (OSError, ValueError, KeyError, TypeError):
        cached = None
    try:
        raw = json.loads((fetch or default_fetch)(f"{BASE}/{arxiv_id}/index.json"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"found": False, "brief": None, "offline": False, "stale": False}
        raw = None
    except (urllib.error.URLError, OSError, ValueError):
        raw = None
    if isinstance(raw, dict):
        brief = _keep(raw, arxiv_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"fetched_at": now.isoformat(timespec="seconds"), "brief": brief},
                                       ensure_ascii=False))
        except OSError:
            pass
        return {"found": True, "brief": brief, "offline": False, "stale": False}
    if cached:
        return {"found": True, "brief": cached["brief"], "offline": True, "stale": True}
    return {"found": False, "brief": None, "offline": True, "stale": False}


def text(root: Path, arxiv_id: str, ans: dict) -> str:
    """Plain text for agents and terminals: Paperraft's brief, then what the lab has."""
    from . import studystate
    out = []
    b = ans.get("brief")
    if b:
        out += [b.get("title") or f"arXiv:{arxiv_id}",
                f"arXiv:{arxiv_id} · Paperraft brief (as of {b.get('as_of') or 'unknown'}"
                + (", saved copy; Paperraft can't be reached" if ans.get("stale") else "") + f"): {b['brief_url']}"]
        rec = b.get("recommendation")
        if rec:
            out.append(f"Paperraft says: {LABELS.get(rec, rec)}")
        if b.get("summary"):
            out += ["", b["summary"]]
        for c in (b.get("claims") or [])[:5]:
            if isinstance(c, dict) and c.get("statement"):
                out.append(f"- {c['statement']}")
    elif ans.get("offline"):
        out.append("Paperraft can't be reached and there is no saved copy of its brief.")
    else:
        out.append(f"Paperraft has no brief for arXiv:{arxiv_id}.")
    out.append("")
    study = studystate.find_arxiv(root, arxiv_id)
    if study:
        st = studystate.stages(root, study, quick=True)
        first = next((s for s in st if s.ok is False), None)
        out += [f"In your lab: studies/{study} — " + (f"{first.name}: {first.text}" if first else "ready"),
                f"Next: {studystate.next_step(root, study, st, studystate.tools(root, study))}"]
    else:
        out += ["In your lab: no study yet",
                f"Next: uv run raft prepare --arxiv {arxiv_id} --agent <claude-code|codex>"]
    out.append(f"See it: uv run raft app --paper {arxiv_id}")
    return "\n".join(out)

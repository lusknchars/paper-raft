"""raft app: the data behind the local dashboard. Everything comes from the lab's own files; the grader never runs."""
import dataclasses
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from . import benchboard, checker, compare, flow, gaps, live, paths, provenance, runner, schema, studystate


def _paper(sd: Path) -> dict:
    return yaml.safe_load((sd / "paper.yaml").read_text()) or {}


def _site(root: Path) -> tuple[dict, str | None]:
    """compare.build for the non-draft studies; a broken study must not take the app down."""
    try:
        return compare.build(root, compare.repo_url(root)), None
    except Exception as e:  # noqa: BLE001
        return {"studies": [], "bench": benchboard.board(root, compare.repo_url(root), provenance.git_sha(root))}, \
            f"Results could not be read ({type(e).__name__}: {e}). Run `uv run raft compare` to see the error."


def _card(root: Path, study: str, lab: dict | None) -> dict:
    sd = root / "studies" / study
    p = _paper(sd)
    error = None
    try:
        st = studystate.stages(root, study, quick=True)
        nxt = studystate.next_step(root, study, st, studystate.tools(root, study))
    except Exception as e:  # noqa: BLE001
        st, nxt, error = [], f"uv run raft status --study {study}", f"{type(e).__name__}: {e}"
    try:
        g = gaps.load(sd)
        g = gaps.counts(g) if g else None
    except SystemExit:
        g = None
    methods = lab["methods"] if lab else []
    return {"id": study, "title": p.get("title") or study, "arxiv": studystate.arxiv_of(p),
            "doi": p.get("doi"), "authors": p.get("authors") or [], "citation": p.get("citation"),
            "draft": bool(p.get("draft")), "brief_url": p.get("brief_url"), "experiment": p.get("experiment") or "",
            "version_of": p.get("version_of"), "stages": [dataclasses.asdict(s) for s in st], "next": nxt,
            "last_stop": studystate.last_stop(root, study), "gaps": g,
            "methods": len(methods) if lab else len(runner.methods(sd)),
            "runs": sum(len(m["runs"]) for m in methods), "counts": lab["counts"] if lab else {}, "error": error}


def app_data(root) -> dict:
    root = Path(root).resolve()
    site, warning = _site(root)
    lab = {s["id"]: s for s in site["studies"]}
    cards = [_card(root, s, lab.get(s)) for s in paths.studies(root, include_drafts=True)]
    sessions = live.sessions(root)
    bench = site["bench"]
    verified = sum(r["status"] == "verified" for s in site["studies"] for m in s["methods"] for r in m["runs"])
    counts = {"studies": len(cards), "running": sum(s["state"] == "running" for s in sessions),
              "verified_runs": verified,
              "bench_entries": sum(len(v["full"]) + len(v["partial"]) for v in bench.values()),
              "open_gaps": sum((c["gaps"] or {}).get("open", 0) + (c["gaps"] or {}).get("asked", 0) for c in cards)}
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "today": date.today().isoformat(),
            "repo": root.name, "studies": cards, "sessions": sessions, "bench": bench, "counts": counts,
            "warning": warning}


def study_detail(root, study: str) -> dict:
    root = Path(root).resolve()
    sd = root / "studies" / study
    site, warning = _site(root)
    lab = next((s for s in site["studies"] if s["id"] == study), None)
    out = _card(root, study, lab)
    out["warning"] = warning
    out["results"] = []
    for m in (lab or {}).get("methods", []):
        head = next((r for r in m["runs"] if r["status"] == m["headline_status"]), m["runs"][0] if m["runs"] else None)
        rv = m["review"] or {}
        out["results"].append({"name": m["name"], "status": m["headline_status"], "verdict": rv.get("verdict"),
                               "reviewer": rv.get("reviewer_agent"),
                               "passed": sum(bool(r["results"].get("pass")) for r in m["runs"]), "total": len(m["runs"]),
                               "code_url": head["code_url"] if head else None})
    if not lab:
        out["results"] = [{"name": n, "status": "no run", "verdict": None, "reviewer": None, "passed": 0, "total": 0,
                           "code_url": None} for n in runner.methods(sd)] if not out["draft"] else []
    note = sd / "checker" / "NOTE.md"
    try:
        approval = checker.approval_state(root, study)
    except schema.ContractError:
        approval = {"state": "invalid", "rounds": None, "approved_at": None}
    try:
        rounds = schema.load("checker-review", sd / "checker" / "review.json")["rounds"]
    except schema.ContractError:
        rounds = []
    out["checker"] = {"note": note.read_text() if note.is_file() else None, "approval": approval, "rounds": rounds,
                      "decoys": sorted(p.stem for p in (sd / "checker" / "attacks").glob("*.py"))}
    try:
        out["gaps_file"] = gaps.load(sd)
    except SystemExit:
        out["gaps_file"] = None
    try:
        out["letter"] = gaps.letter(root, study, compare.repo_url(root)) if out["gaps_file"] else None
    except SystemExit:
        out["letter"] = None
    out["bench"] = site["bench"].get(study) or {"full": [], "partial": []}
    try:
        out["flow"] = flow.build_flow(root, study, compare.repo_url(root))
    except Exception:  # noqa: BLE001 (the flow tab says it could not be drawn)
        out["flow"] = None
    return out

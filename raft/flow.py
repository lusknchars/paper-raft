"""One study's flow: paper → extracted items → methods → runs, built from committed files only.

The flow view (raft/site_template/flow/flow.js) draws this shape. The Paper Raft site, `raft watch` and
Paperraft's demo all read it; raft/contracts/flow.schema.json checks it.
"""
import json
import re
import shutil
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import yaml

from . import provenance, runner, schema
from .status import derive_status

THREE = "three-0.186.1"
FORMATS = ("sigma", "drop_percent", "sci", "kept_percent", "percent", "number")
AGGS = ("max", "min", "mean")
_REQUIRED = {"key", "from", "label", "note", "agg", "format"}


def template_dir() -> Path:
    return Path(str(files("raft.site_template")))


def _load(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


def authors_short(paper: dict) -> str:
    authors = paper.get("authors") or []
    year = re.search(r"\b(?:19|20)\d{2}\b", paper.get("citation", ""))
    name = authors[0].split()[-1] + (" et al." if len(authors) > 1 else "") if authors else ""
    return " ".join(p for p in (name, year.group(0) if year else "") if p)


def metric_specs(paper: dict) -> list[dict]:
    """The `metrics` list of paper.yaml: which error keys the flow view shows, and how."""
    specs = paper.get("metrics") or []
    if not isinstance(specs, list):
        raise ValueError("paper.yaml: metrics must be a list")
    seen = set()
    for i, s in enumerate(specs):
        if not isinstance(s, dict) or not _REQUIRED <= set(s) or set(s) - _REQUIRED - {"where"}:
            raise ValueError(f"paper.yaml: metrics[{i}] needs exactly the keys {sorted(_REQUIRED)} (and optionally where)")
        if s["format"] not in FORMATS:
            raise ValueError(f"paper.yaml: metrics[{i}] format {s['format']!r} is not one of {FORMATS}")
        if s["agg"] not in AGGS:
            raise ValueError(f"paper.yaml: metrics[{i}] agg {s['agg']!r} is not one of {AGGS}")
        if not isinstance(s.get("where", {}), dict):
            raise ValueError(f"paper.yaml: metrics[{i}] where must map parameters to values")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(s["key"])) or s["key"] in seen:
            raise ValueError(f"paper.yaml: metrics[{i}] key {s['key']!r} must be a unique snake_case name")
        seen.add(s["key"])
    return specs


def case_key(params: dict) -> str:
    return ",".join(f"{k}={params[k]}" for k in sorted(params))


def case_label(params: dict) -> str:
    return " · ".join(str(params[k]) for k in sorted(params))


def _expected(sd: Path) -> list[dict]:
    try:
        return runner.expand(sd, {})
    except Exception:  # a draft's problem/ may not run yet
        return []


def _run(sd: Path, root: Path, name: str, params: dict, review, sha_now, specs) -> dict:
    rid = runner.run_id(name, params)
    run = {"run_id": rid, "method": name, "params": params, "case": case_key(params),
           "status": "missing", "pass": False, "started_at": None, "metrics": []}
    mpath = sd / "runs" / rid / "manifest.json"
    if not mpath.is_file():
        return run
    manifest = schema.load("manifest", mpath)
    results = schema.load("results", mpath.parent / "results.json")
    stale = (provenance.inputs_hash(manifest["params"], sd / "problem") != manifest["inputs_hash"]
             or sha_now != manifest["method_sha"])
    run["status"] = "stale" if stale else derive_status(results, manifest, review)
    run["pass"] = bool(results["pass"]) and not stale
    run["started_at"] = manifest["started_at"]
    errors = results.get("errors") or {}
    run["metrics"] = [{"key": s["key"], "value": float(errors[s["from"]])} for s in specs
                      if s["from"] in errors and all(params.get(k) == v for k, v in s.get("where", {}).items())]
    return run


def build_flow(root: Path, study: str, repo: str | None = None) -> dict:
    root = Path(root).resolve()
    sd = root / "studies" / study
    paper = yaml.safe_load((sd / "paper.yaml").read_text()) or {}
    specs = metric_specs(paper)
    reference = _load(sd / "problem" / "reference.json") or {}
    items = [{"id": i["id"], "kind": i["kind"]} for i in (_load(sd / "extraction.json") or {}).get("items", [])]
    ids = {i["id"] for i in items}
    names = runner.methods(sd)
    combos = _expected(sd) if names else []
    methods, runs = [], []
    for color, name in enumerate(names):
        mjson = _load(sd / "methods" / name / "method.json") or {}
        review = _load(sd / "reviews" / f"{name}.json")
        sha_now = provenance.method_sha(root, sd / "methods" / name)
        mine = [_run(sd, root, name, p, review, sha_now, specs) for p in combos]
        statuses = {r["status"] for r in mine}
        status = ("no run" if statuses <= {"missing"} else "failed" if "failed" in statuses
                  else "verified" if statuses == {"verified"} else "unverified")
        methods.append({"name": name, "implements": [i for i in mjson.get("implements", []) if i in ids],
                        "status": status, "color": color})
        runs += mine
    out = {
        "schema": 1, "study": study,
        "source": {"repo": repo, "commit": provenance.git_sha(root),
                   "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "paper": {"title": str(paper.get("title", study)), "authors_short": authors_short(paper),
                  "reference_checked": bool(reference.get("verified_against_pdf")), "draft": bool(paper.get("draft"))},
        "items": items, "methods": methods,
        "cases": [{"key": case_key(p), "label": case_label(p)} for p in combos],
        "runs": runs,
        "metrics": [{k: s[k] for k in ("key", "label", "note", "agg", "format")} for s in specs],
    }
    schema.check("flow", out)
    return out


def copy_assets(dest: Path) -> None:
    """flow.js, flow.css and three.js, laid out as Paperraft serves them: <dest>/paper-raft-flow, <dest>/three-…"""
    tpl = template_dir()
    shutil.copytree(tpl / "vendor" / THREE, Path(dest) / THREE, dirs_exist_ok=True)
    (Path(dest) / "paper-raft-flow").mkdir(parents=True, exist_ok=True)
    for name in ("flow.js", "flow.css"):
        shutil.copyfile(tpl / "flow" / name, Path(dest) / "paper-raft-flow" / name)


def export(root: Path, study: str, out: Path, assets: Path | None, repo: str | None) -> dict:
    """Write a committed study's flow to `out` (and the view's files to `assets`), for Paperraft."""
    if provenance.is_dirty(root, [root / "studies" / study]):
        raise SystemExit(f"raft: studies/{study} has uncommitted changes; commit them before exporting")
    data = build_flow(root, study, repo)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    if assets is not None:
        copy_assets(Path(assets))
    return data

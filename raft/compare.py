"""Collect every study's runs, reviews and extraction into one data file and a static site."""
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import yaml

from . import benchboard, checker, flow, paths, provenance, runner, schema
from .status import derive_status

SITE_FILES = ("index.html", "app.js", "style.css")


def repo_url(root: Path) -> str | None:
    url = os.environ.get("RAFT_REPO_URL")
    if not url:
        try:
            url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root,
                                 capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    m = re.match(r"^(?:git@github\.com:|https://github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return f"https://github.com/{m.group(1)}" if m else None


def _maybe(name: str, path: Path):
    return schema.load(name, path) if path.is_file() else None


def _code_url(url, manifest, root: Path, sd: Path, name: str):
    if not url or manifest["git_sha"] == "unknown" or manifest["dirty"]:
        return None
    rel = (sd / "methods" / name / "solver.py").relative_to(root)
    return f"{url}/blob/{manifest['git_sha']}/{rel.as_posix()}"


def build(root: Path, repo: str | None) -> dict:
    root = Path(root).resolve()
    data = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "repo_url": repo, "studies": []}
    for sd in (root / "studies" / s for s in paths.studies(root)):
        reference = schema.load("reference", sd / "problem" / "reference.json")
        headline = getattr(runner.load_module(sd / "problem" / "setup.py", f"raft_compare_{sd.name}"), "HEADLINE", {})
        methods = []
        for name in runner.methods(sd):
            review = _maybe("review", sd / "reviews" / f"{name}.json")
            runs = []
            for mpath in sorted((sd / "runs").glob("*/manifest.json")):
                manifest = schema.load("manifest", mpath)
                if manifest["method"] != name:
                    continue
                results = schema.load("results", mpath.parent / "results.json")
                runs.append({"run_id": manifest["run_id"], "params": manifest["params"], "manifest": manifest,
                             "results": results, "status": derive_status(results, manifest, review),
                             "code_url": _code_url(repo, manifest, root, sd, name)})
            head = next((r for r in runs if all(r["params"].get(k) == v for k, v in headline.items())), None)
            methods.append({"name": name, "method": _maybe("method", sd / "methods" / name / "method.json"),
                            "review": review, "runs": runs, "headline_status": head["status"] if head else "no run"})
        data["studies"].append({
            "id": sd.name, "paper": yaml.safe_load((sd / "paper.yaml").read_text()) or {},
            "extraction": _maybe("extraction", sd / "extraction.json"),
            "reference": {k: reference[k] for k in ("citation", "doi", "tolerance")},
            "headline": headline, "methods": methods,
            "counts": dict(Counter(m["headline_status"] for m in methods)),
            "checker": checker.approval_state(root, sd.name),
        })
    data["flows"] = {s: flow.build_flow(root, s, repo) for s in paths.studies(root, include_drafts=True)}
    data["bench"] = benchboard.board(root, repo, provenance.git_sha(root))
    return data


def write_site(data: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    template = files("raft.site_template")
    for name in SITE_FILES:
        with template.joinpath(name).open("rb") as src, open(out_dir / name, "wb") as dst:
            shutil.copyfileobj(src, dst)
    tpl = flow.template_dir()
    for tree in ("flow", "vendor"):
        if (tpl / tree).is_dir():
            shutil.copytree(tpl / tree, out_dir / tree, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("watch.html", "live.html", "live.js", "live.css"))
    (out_dir / "flows").mkdir(exist_ok=True)
    for sid, f in data.get("flows", {}).items():
        (out_dir / "flows" / f"{sid}.json").write_text(json.dumps(f, indent=1, ensure_ascii=False) + "\n")
    (out_dir / "data.json").write_text(json.dumps(data, indent=1) + "\n")
    (out_dir / "data.js").write_text("window.RAFT_DATA = " + json.dumps(data) + ";\n")

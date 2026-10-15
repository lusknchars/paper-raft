"""raft bench: hand a study to someone's agent in a blind workspace, grade its code out of its reach, write an entry.

The workspace holds only the study's paper.yaml, extraction.json, problem/setup.py, an empty methods/ folder, the
PDF if it is here, and the entrant's setup folder, with a fresh git history. The yardstick (measure.py,
reference.json), the lab's methods, runs and reviews are not in it. Grading copies the agent's method folders into
a fresh copy of the study's problem/ and runs them with the same runner `raft run` uses. Nothing the agent says
counts.
"""
import difflib
import hashlib
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from . import briefs, guard, provenance, runner

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".git")


def _study_dir(root: Path, study: str) -> Path:
    return Path(root) / "studies" / study


def _paper(sd: Path) -> dict:
    return yaml.safe_load((sd / "paper.yaml").read_text()) or {}


def problem_hash(sd: Path) -> str:
    return provenance.inputs_hash({}, Path(sd) / "problem")


def require_clean(root: Path, study: str) -> None:
    sd = _study_dir(root, study)
    if provenance.is_dirty(root, [sd / "problem", sd / "paper.yaml", sd / "extraction.json"]):
        raise SystemExit(f"raft: studies/{study} has uncommitted changes in problem/, paper.yaml or "
                         "extraction.json; commit them first")


def _setup_files(setup: Path) -> list[Path]:
    return sorted(p for p in setup.rglob("*")
                  if p.is_file() and not {".git", "__pycache__"} & set(p.relative_to(setup).parts))


def setup_info(setup: Path | None) -> dict | None:
    if setup is None:
        return None
    setup = Path(setup)
    h = hashlib.sha256()
    files = _setup_files(setup)
    for p in files:
        h.update(p.relative_to(setup).as_posix().encode() + b"\0")
        h.update(p.read_bytes())
    return {"hash": h.hexdigest(), "files": [p.relative_to(setup).as_posix() for p in files][:200]}


def make_workspace(root: Path, study: str, ws: Path, setup: Path | None) -> Path:
    root, ws = Path(root), Path(ws)
    if setup is not None:
        setup = Path(setup)
        if not setup.is_dir():
            raise SystemExit(f"raft: --setup {setup} is not a folder")
        if (setup / "studies").exists():
            raise SystemExit("raft: the --setup folder must not contain studies/; it is copied onto the workspace root")
    sd = _study_dir(root, study)
    wsd = ws / "studies" / study
    (wsd / "problem").mkdir(parents=True)
    (wsd / "methods").mkdir()
    shutil.copyfile(sd / "paper.yaml", wsd / "paper.yaml")
    if (sd / "extraction.json").is_file():
        shutil.copyfile(sd / "extraction.json", wsd / "extraction.json")
    shutil.copyfile(sd / "problem" / "setup.py", wsd / "problem" / "setup.py")
    pdf = _paper(sd).get("pdf")
    if pdf and not Path(pdf).is_absolute() and ".." not in Path(pdf).parts and (root / pdf).is_file():
        (ws / pdf).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / pdf, ws / pdf)
    if setup is not None:
        shutil.copytree(setup, ws, dirs_exist_ok=True, ignore=_IGNORE)
    for args in (("init", "-q", "-b", "main"), ("add", "-A"),
                 ("-c", "user.name=raft-bench", "-c", "user.email=bench@paper-raft.invalid",
                  "-c", "commit.gpgsign=false", "commit", "-qm", "workspace")):
        subprocess.run(["git", *args], cwd=ws, check=True, capture_output=True)
    return ws


def render_brief(root: Path, study: str, method: str) -> str:
    return briefs.render(Path(root), "bench-implementer", study, method).replace("{{python}}", sys.executable)


OVERLAP = 0.8  # an agent solver at least this similar to the lab's own solver counts as copied


def _code_lines(d: Path) -> list[str]:
    d = Path(d)
    if not d.is_dir():
        return []
    lines = []
    for p in sorted(d.rglob("*.py")):
        if "__pycache__" not in p.parts:
            lines += [s.strip() for s in p.read_text(errors="replace").splitlines() if s.strip()]
    return lines


def lab_overlap(lab_dir: Path, agent_dir: Path) -> float:
    a, b = _code_lines(lab_dir), _code_lines(agent_dir)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _finite(errors):
    if errors is None:
        return None
    return {k: (float(v) if math.isfinite(float(v)) else 1e300) for k, v in errors.items()}


def grade(root: Path, study: str, code_dir: Path, methods: list[str], run_timeout: float,
          log=lambda s: None) -> list[dict]:
    """Run the agent's method folders against a fresh copy of the study's committed problem/."""
    sd = _study_dir(root, study)
    with tempfile.TemporaryDirectory(prefix="raft-grade-") as tmp:
        g = Path(tmp) / "studies" / study
        shutil.copytree(sd / "problem", g / "problem", ignore=_IGNORE)
        shutil.copyfile(sd / "paper.yaml", g / "paper.yaml")
        (g / "methods").mkdir()
        combos = runner.expand(g, {})
        out = []
        for m in methods:
            src, dst = Path(code_dir) / m, g / "methods" / m
            has = (src / "solver.py").is_file()
            copied = has and lab_overlap(sd / "methods" / m, src) >= OVERLAP
            res = {"name": m, "guard": [], "copied_from_lab": copied, "runs": []}
            if has:
                shutil.copytree(src, dst, ignore=_IGNORE)
                res["guard"] = guard.scan_method(dst)
            for p in combos:
                rid = runner.run_id(m, p)
                if not has or copied:
                    run = {"run_id": rid, "params": p, "status": "failed", "pass": False,
                           "reason": "no solver.py" if not has else "matches the lab's own code", "errors": None}
                else:
                    _, r = runner.execute(g, m, p, run_timeout)
                    run = {"run_id": rid, "params": p, "status": r["status"], "pass": bool(r["pass"]),
                           "reason": r.get("reason"), "errors": _finite(r.get("errors"))}
                log(f"{'✓' if run['pass'] else '✗'} {rid}" + (f": {run['reason']}" if run["reason"] else ""))
                res["runs"].append(run)
            out.append(res)
        return out

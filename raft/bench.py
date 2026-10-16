"""raft bench: hand a study to someone's agent in a blind workspace, grade its code out of its reach, write an entry.

The workspace holds only the study's paper.yaml, extraction.json, problem/setup.py, an empty methods/ folder, the
PDF if it is here, and the entrant's setup folder, with a fresh git history. The yardstick (measure.py,
reference.json), the lab's methods, runs and reviews are not in it. Grading copies the agent's method folders into
a fresh copy of the study's problem/ and runs them with the same runner `raft run` uses. Nothing the agent says
counts.
"""
import difflib
import hashlib
import json
import math
import platform
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import agents, benchboard, briefs, flow, guard, live, provenance, runner, schema

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".git")


def _study_dir(root: Path, study: str) -> Path:
    return Path(root) / "studies" / study


def _paper(sd: Path) -> dict:
    return yaml.safe_load((sd / "paper.yaml").read_text()) or {}


CODE_LIMIT = 1_000_000  # bytes per file in a method folder


def problem_hash(sd: Path) -> str:
    """Hash of the git-tracked files in problem/, so ignored clutter (.DS_Store) never changes it."""
    return provenance.tracked_hash(Path(sd) / "problem")


def _guarded(root: Path, study: str) -> list[Path]:
    sd = _study_dir(root, study)
    return [sd / "problem", sd / "paper.yaml", sd / "extraction.json", Path(root) / "raft"]


def require_clean(root: Path, study: str) -> None:
    if provenance.is_dirty(root, _guarded(root, study)):
        raise SystemExit(f"raft: studies/{study} (problem/, paper.yaml, extraction.json) or raft/ has uncommitted "
                         "changes; commit them first")


def code_files(d: Path) -> list[Path]:
    """The files of a method folder that count: regular .py files and method.json, never symlinks."""
    d, out = Path(d), []
    if not d.is_dir() or d.is_symlink():
        return out
    for here, dirs, files in os.walk(d, followlinks=False):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__" and not os.path.islink(os.path.join(here, x)))
        for f in sorted(files):
            p = Path(here) / f
            if (not p.is_symlink() and p.is_file() and (p.suffix == ".py" or f == "method.json")
                    and p.stat().st_size <= CODE_LIMIT):
                out.append(p)
    return out


def stray_files(d: Path) -> list[str]:
    """Everything in a method folder that code_files() leaves out (data, binaries, links, oversized files)."""
    d = Path(d)
    keep = set(code_files(d))
    out = []
    for here, dirs, files in os.walk(d, followlinks=False):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for name in files + [x for x in dirs if os.path.islink(os.path.join(here, x))]:
            p = Path(here) / name
            if p not in keep and p.suffix != ".pyc":
                out.append(p.relative_to(d).as_posix())
    return sorted(out)


def copy_code(src: Path, dst: Path) -> None:
    for p in code_files(src):
        target = Path(dst) / p.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)


def python_shim(bin_dir: Path) -> Path:
    """A `python` outside the repo for the brief, so the brief does not hand the agent the repo's path."""
    p = Path(bin_dir) / "python"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n")
    p.chmod(0o755)
    return p


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


def render_brief(root: Path, study: str, method: str, python: str) -> str:
    return briefs.render(Path(root), "bench-implementer", study, method).replace("{{python}}", python)


OVERLAP = 0.8  # an agent solver at least this similar to the lab's own solver counts as copied


def _code_lines(d: Path) -> list[str]:
    lines = []
    for p in code_files(d):
        if p.suffix == ".py":
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
          log=lambda s: None, ls=None) -> list[dict]:
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
            has = (src / "solver.py") in code_files(src)
            copied = has and lab_overlap(sd / "methods" / m, src) >= OVERLAP
            res = {"name": m, "guard": [], "copied_from_lab": copied, "runs": []}
            if has:
                copy_code(src, dst)
                res["guard"] = guard.scan_method(dst)
            for p in combos:
                rid = runner.run_id(m, p)
                sid = f"run-{rid}"
                if ls:
                    ls.begin(sid, rid, method=m, timeout_s=run_timeout)
                if not has or copied:
                    run = {"run_id": rid, "params": p, "status": "failed", "pass": False,
                           "reason": "no solver.py" if not has else "matches the lab's own code", "errors": None}
                else:
                    pdir = Path(tmp) / "progress"
                    if ls:
                        with live.watching_progress(ls, pdir / f"{rid}.json"):
                            _, r = runner.execute(g, m, p, run_timeout, progress_dir=pdir)
                    else:
                        _, r = runner.execute(g, m, p, run_timeout)
                    run = {"run_id": rid, "params": p, "status": r["status"], "pass": bool(r["pass"]),
                           "reason": r.get("reason"), "errors": _finite(r.get("errors"))}
                log(f"{'✓' if run['pass'] else '✗'} {rid}" + (f": {run['reason']}" if run["reason"] else ""))
                res["runs"].append(run)
                if ls:
                    ls.end(sid, "done" if run["pass"] else "failed", detail=run["reason"])
                    graded = [x for o in out + [res] for x in o["runs"]]
                    passed = sum(x["pass"] for x in graded)
                    expected = len(methods) * len(combos)
                    ls.set_results(passed=passed, failed=len(graded) - passed, expected=expected,
                                   score=round(passed / expected, 4) if expected else 0.0)
            out.append(res)
        return out


TRANSCRIPT_LIMIT = 2_000_000


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-.") or "default"


def _code_hash(code_dir: Path, methods: list[str]) -> str:
    h = hashlib.sha256()
    for m in methods:
        d = Path(code_dir) / m
        for p in code_files(d):
            h.update(f"{m}/{p.relative_to(d).as_posix()}".encode() + b"\0")
            h.update(p.read_bytes())
    return h.hexdigest()


def redact(data: bytes) -> bytes:
    """Replace the user's home directory with ~ (only as a whole path component; never when HOME is unusable)."""
    home = os.path.expanduser("~").rstrip("/")
    if not home.startswith("/"):
        return data
    return re.sub(re.escape(home.encode()) + rb"(?=[/\"'\s\\]|$)", b"~", data)


def redact_file(path: Path) -> bool:
    path = Path(path)
    data = path.read_bytes()
    new = redact(data)
    if new == data:
        return False
    path.write_bytes(new)
    return True


def transcripts_with_home(paths) -> list[Path]:
    return [Path(p) for p in paths if Path(p).is_file() and redact(Path(p).read_bytes()) != Path(p).read_bytes()]


def trim_copy(src: Path, dst: Path, limit: int = TRANSCRIPT_LIMIT) -> None:
    data = redact(Path(src).read_bytes() if Path(src).is_file() else b"")
    if len(data) > limit:
        head = data[: limit // 2].rsplit(b"\n", 1)[0]
        tail = data[-(limit // 2):].split(b"\n", 1)[-1]
        marker = json.dumps({"raft_trimmed_bytes": len(data) - len(head) - len(tail)}).encode()
        data = head + b"\n" + marker + b"\n" + tail
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_bytes(data)


def run_bench(root: Path, study: str, agent: str, *, model=None, oss=False, setup=None, methods=None, label=None,
              cmd=None, timeout: float = 1800.0, run_timeout: float = 1800.0, out_dir=None, log=print, on_live=None) -> Path:
    root = Path(root).resolve()
    sd = _study_dir(root, study)
    agents.check(agent, model=model, oss=oss, cmd=cmd)
    lab = runner.methods(sd)
    chosen = list(methods) if methods else lab
    if not chosen:
        raise SystemExit(f"raft: {study} has no methods to bench")
    unknown = [m for m in chosen if m not in lab]
    if unknown:
        raise SystemExit(f"raft: unknown method(s) {', '.join(unknown)} (have: {', '.join(lab)})")
    require_clean(root, study)
    from . import checker
    checker.gate(root, study)
    setup = Path(setup).resolve() if setup else None
    specs = flow.metric_specs(_paper(sd))
    paper = _paper(sd)
    combos = runner.expand(sd, {})
    ls = live.Session(root, "bench", study, title=paper.get("title"),
                      arxiv=str(paper["arxiv"]) if paper.get("arxiv") else None,
                      agents={"agent": {"tool": agent, "model": model}},
                      total=len(chosen) * (1 + len(combos)), on_write=on_live)
    try:
        dest = _bench_body(root, study, sd, agent, chosen, ls, model=model, oss=oss, setup=setup, label=label,
                           cmd=cmd, timeout=timeout, run_timeout=run_timeout, out_dir=out_dir, log=log, specs=specs)
    except SystemExit as e:
        ls.stop(str(e.code if e.code is not None else "stopped"))
        raise
    except KeyboardInterrupt:
        ls.stop("interrupted (Ctrl-C)")
        raise
    except Exception as e:  # noqa: BLE001
        ls.stop(f"{type(e).__name__}: {e}")
        raise
    ls.finish(f"bench entry: {dest}")
    return dest


def _bench_body(root, study, sd, agent, chosen, ls, *, model, oss, setup, label, cmd, timeout, run_timeout,
                out_dir, log, specs) -> Path:
    with tempfile.TemporaryDirectory(prefix="raft-bench-") as tmp:
        ws = make_workspace(root, study, Path(tmp) / "ws", setup)
        logs = Path(tmp) / "logs"
        logs.mkdir()
        python = str(python_shim(Path(tmp) / "bin"))
        tried = {}
        for m in chosen:
            brief = logs / f"{m}.md"
            brief.write_text(render_brief(root, study, m, python))
            log(f"• {agent}: {m} …")
            sid = f"implement-{m}"
            ls.begin(sid, f"Implement {m}", agent="agent", method=m, timeout_s=timeout)
            with live.watching(ls, sid, agent, logs / f"{m}.jsonl"):
                t = tried[m] = agents.run(agent, brief, ws, m, model=model, oss=oss, cmd=cmd, timeout=timeout,
                                          transcript=logs / f"{m}.jsonl")
            ls.end(sid, "done" if t["exit"] == 0 and not t["timed_out"] else "failed",
                   detail="timed out" if t["timed_out"] else f"agent exited {t['exit']}")
            log(f"  {m}: " + ("timed out" if t["timed_out"] else f"agent exited {t['exit']}") + f" after {t['wall_s']:.0f}s")
        if provenance.is_dirty(root, _guarded(root, study)):
            raise SystemExit(f"raft: studies/{study} or raft/ changed while the agent ran; nothing was graded. "
                             "Check `git status`, restore the files, and run the bench again.")
        code = ws / "studies" / study / "methods"
        log("• grading in a fresh copy of problem/ …")
        graded = grade(root, study, code, chosen, run_timeout, log, ls=ls)
        out_methods = [{"name": g["name"], "agent_exit": tried[g["name"]]["exit"],
                        "timed_out": tried[g["name"]]["timed_out"], "wall_s": tried[g["name"]]["wall_s"],
                        "usage": tried[g["name"]]["usage"], "guard": g["guard"],
                        "copied_from_lab": g["copied_from_lab"], "runs": g["runs"]} for g in graded]
        now = datetime.now(timezone.utc)
        eid = f"{now:%Y-%m-%d}-{_slug(agent)}-{_slug(model or 'default')}-{_code_hash(code, chosen)[:6]}"
        entry = runner._plain({
            "schema": 1, "id": eid, "study": study, "created_at": now.isoformat(timespec="seconds"),
            "raft_commit": provenance.git_sha(root), "problem_hash": problem_hash(sd),
            "entrant": {"agent": agent, "tool_version": agents.tool_version(agent), "model": model, "oss": bool(oss),
                        "label": label, "command": cmd, "isolation": agents.ISOLATION[agent],
                        "setup": setup_info(setup)},
            "machine": {"os": platform.platform(), "python": platform.python_version()},
            "methods": out_methods, "score": benchboard.score_counts(out_methods),
            "metrics": benchboard.aggregate_metrics(specs, out_methods),
        })
        schema.check("bench-entry", entry)
        dest = (Path(out_dir) if out_dir else root / "bench" / "results" / study) / eid
        if dest.exists():
            raise SystemExit(f"raft: {dest} already exists")
        (dest / "methods").mkdir(parents=True)
        for m in chosen:
            copy_code(code / m, dest / "methods" / m)
            trim_copy(logs / f"{m}.jsonl", dest / "transcript" / f"{m}.jsonl")
            if (logs / f"{m}.stderr.txt").is_file() and (logs / f"{m}.stderr.txt").stat().st_size:
                trim_copy(logs / f"{m}.stderr.txt", dest / "transcript" / f"{m}.stderr.txt")
        (dest / "entry.json").write_text(json.dumps(entry, indent=1, ensure_ascii=False) + "\n")
    return dest


def entry_dirs(root: Path) -> list[Path]:
    return [p.parent for p in sorted((Path(root) / "bench" / "results").glob("*/*/entry.json"))]


def _close(a, b, rtol: float) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=rtol, abs_tol=1e-12)


def verify(root: Path, entry_dir: Path, run_timeout: float = 1800.0, log=lambda s: None) -> list[str]:
    """Rerun an entry's code against today's problem/ and check every recorded number."""
    root, entry_dir = Path(root).resolve(), Path(entry_dir).resolve()
    try:
        entry = schema.load("bench-entry", entry_dir / "entry.json")
    except schema.ContractError as e:
        return [str(e)]
    eid, study = entry["id"], entry["study"]
    if entry_dir.name != eid or entry_dir.parent.name != study:
        return [f"{entry_dir.name}: study and id do not match the folder"]
    sd = _study_dir(root, study)
    if not (sd / "paper.yaml").is_file():
        return [f"{eid}: unknown study {study!r}"]
    if problem_hash(sd) != entry["problem_hash"]:
        return [f"{eid}: studies/{study}/problem changed since this entry; rerun the bench"]
    names = [m["name"] for m in entry["methods"]]
    lab = runner.methods(sd)
    found = [f"{n} is listed more than once" for n in sorted(set(names)) if names.count(n) > 1]
    found += [f"{n} is not a method of studies/{study}" for n in sorted(set(names)) if n not in lab]
    on_disk = sorted(p.name for p in (entry_dir / "methods").iterdir()) if (entry_dir / "methods").is_dir() else []
    found += [f"methods/{n} is not in entry.json" for n in on_disk if n not in names]
    for n in sorted(set(names)):
        stray = stray_files(entry_dir / "methods" / n)
        if stray:
            found.append(f"methods/{n} may hold only .py files and method.json (found {', '.join(stray[:5])})")
    if found:
        return [f"{eid}: {p}" for p in found]
    graded = grade(root, study, entry_dir / "methods", names, run_timeout, log)
    setup_mod = runner.load_module(sd / "problem" / "setup.py", f"raft_bench_{study.replace('-', '_')}")
    rtol = float(getattr(setup_mod, "REPRO_RTOL", 1e-8))
    problems = []
    for old, new in zip(entry["methods"], graded):
        n = old["name"]
        if old["guard"] != new["guard"]:
            problems.append(f"{n}: guard result differs")
        if old["copied_from_lab"] != new["copied_from_lab"]:
            problems.append(f"{n}: copy check differs")
        o_runs = {r["run_id"]: r for r in old["runs"]}
        n_runs = {r["run_id"]: r for r in new["runs"]}
        if set(o_runs) != set(n_runs):
            problems.append(f"{n}: the run matrix differs")
            continue
        for rid, o in o_runs.items():
            x = n_runs[rid]
            if o["status"] != x["status"] or o["pass"] != x["pass"]:
                problems.append(f"{rid}: recorded {o['status']}/{'pass' if o['pass'] else 'fail'}, "
                                f"rerun gives {x['status']}/{'pass' if x['pass'] else 'fail'}")
            elif not runner._same(o["errors"], x["errors"], rtol):
                problems.append(f"{rid}: errors differ beyond rtol {rtol:g}")
    if entry["score"] != benchboard.score_counts(entry["methods"]):
        problems.append("score does not match the recorded runs")
    again = benchboard.aggregate_metrics(flow.metric_specs(_paper(sd)), entry["methods"])
    if ([m["key"] for m in again] != [m["key"] for m in entry["metrics"]]
            or not all(_close(a["value"], b["value"], rtol) for a, b in zip(again, entry["metrics"]))):
        problems.append("metrics do not match the recorded runs")
    return [f"{eid}: {p}" for p in problems]

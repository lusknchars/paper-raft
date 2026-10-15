"""Run a method on a study's shared problem in a child process and record everything."""
import importlib.util
import inspect
import json
import math
import multiprocessing as mp
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import guard, provenance, schema


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_measure(problem: Path):
    """problem/measure.py, with problem/ importable so it can use its copied graders (`from graders import …`)."""
    problem = str(Path(problem))
    for name in [n for n in sys.modules if n == "graders" or n.startswith("graders.")]:
        del sys.modules[name]
    sys.path.insert(0, problem)
    try:
        return load_module(Path(problem) / "measure.py", "raft_measure")
    finally:
        sys.path.remove(problem)


def _setup_module(study_dir: Path, tag: str):
    return load_module(Path(study_dir) / "problem" / "setup.py", f"raft_setup_{tag}")


def methods(study_dir: Path) -> list[str]:
    base = Path(study_dir) / "methods"
    return sorted(d.name for d in base.iterdir() if (d / "solver.py").is_file()) if base.is_dir() else []


def expand(study_dir: Path, params: dict) -> list[dict]:
    return _setup_module(study_dir, "expand").expand(params)


def run_id(method: str, params: dict) -> str:
    return method + "-" + "-".join(f"{k}{params[k]}" for k in sorted(params))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_progress(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")  # per-process: concurrent writers never share it
    tmp.write_text(json.dumps(obj))
    os.replace(tmp, path)


def _progress_writer(path: Path, started: str):
    """progress(fraction) for solve(): clamps to [0, 1], ignores junk, writes at most twice a second."""
    last = [0.0]

    def progress(fraction):
        try:
            f = float(fraction)
        except (TypeError, ValueError):
            return
        if not math.isfinite(f):
            return
        now = time.monotonic()
        if now - last[0] < 0.5 and f < 1:
            return
        last[0] = now
        _write_progress(path, {"state": "running", "fraction": min(1.0, max(0.0, f)),
                               "started_at": started, "updated_at": _now()})
    return progress


def _child(study_dir: str, method: str, params: dict, progress_path: str | None = None, started: str | None = None):
    sd = Path(study_dir)
    setup = _setup_module(sd, "child").make_setup(params)
    solver = load_module(sd / "methods" / method / "solver.py", f"raft_method_{method.replace('-', '_')}")
    if "progress" in inspect.signature(solver.solve).parameters:
        # repro and other callers without a progress path get a no-op, so the solver never sees a missing argument.
        report = _progress_writer(Path(progress_path), started) if progress_path else (lambda fraction: None)
        return solver.solve(setup, progress=report)
    return solver.solve(setup)


def _plain(obj):
    """Round-trip through JSON so numpy scalars become plain Python values."""
    def default(o):
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(f"not JSON serialisable: {type(o).__name__}")
    return json.loads(json.dumps(obj, default=default))


def execute(study_dir: Path, method: str, params: dict, timeout: float,
            progress_dir: Path | None = None) -> tuple[dict, dict]:
    sd = Path(study_dir).resolve()
    root = sd.parents[1]
    method_dir, problem = sd / "methods" / method, sd / "problem"
    if not (method_dir / "solver.py").is_file():
        raise SystemExit(f"raft: no method {method!r} in {sd / 'methods'} (have: {', '.join(methods(sd)) or 'none'})")
    rid = run_id(method, params)
    before = provenance.inputs_hash(params, problem)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ppath = Path(progress_dir) / f"{rid}.json" if progress_dir is not None else None
    if ppath is not None:
        _write_progress(ppath, {"state": "running", "fraction": None, "started_at": started, "updated_at": started})
    finished = False
    try:
        t0 = time.monotonic()
        fields, reason = None, None
        violations = guard.scan_method(method_dir)
        if violations:
            reason = "guard: " + "; ".join(violations)
        else:
            with mp.get_context("spawn").Pool(1) as pool:
                job = pool.apply_async(_child, (str(sd), method, params, str(ppath) if ppath else None, started))
                try:
                    fields = job.get(timeout=timeout)
                except mp.TimeoutError:
                    reason = f"timeout after {timeout:g}s"
                except Exception as e:  # the method's own failure, recorded as a result
                    reason = f"{type(e).__name__}: {e}"
        duration = time.monotonic() - t0
        if provenance.inputs_hash(params, problem) != before:
            fields, reason = None, "problem/ was modified during the run"
        results = {"run_id": rid, "status": "failed", "reason": reason, "samples": None,
                   "errors": None, "tolerance": None, "pass": False}
        setup_mod = _setup_module(sd, "parent")
        if reason is None:
            measure_mod = load_measure(problem)
            reference = json.loads((problem / "reference.json").read_text())
            try:
                # A study whose methods make different claims can take `method` and grade each by name.
                extra = {"method": method} if "method" in inspect.signature(measure_mod.measure).parameters else {}
                measured = measure_mod.measure(setup_mod.make_setup(params), fields, reference, **extra)
                results = {"run_id": rid, "status": "ok", **measured}
            except ValueError as e:
                results["reason"] = f"measure: {e}"
            except Exception as e:
                results["reason"] = f"measure: {type(e).__name__}: {e}"
        manifest = {
            "run_id": rid, "study": sd.name, "method": method, "params": params,
            "inputs_hash": before, "git_sha": provenance.git_sha(root),
            "method_sha": provenance.method_sha(root, method_dir),
            "dirty": provenance.is_dirty(root, [method_dir, problem]),
            "python": platform.python_version(), "packages": provenance.package_versions(),
            "seed": int(params.get("seed", 0)), "started_at": started, "duration_s": round(duration, 3),
            "repro_rtol": float(getattr(setup_mod, "REPRO_RTOL", 1e-8)),
        }
        manifest, results = _plain(manifest), _plain(results)
        schema.check("manifest", manifest)
        schema.check("results", results)
        if ppath is not None:
            _write_progress(ppath, {"state": "finished", "pass": bool(results["pass"]), "started_at": started,
                                    "finished_at": _now()})
        finished = True
        return manifest, results
    finally:
        if ppath is not None and not finished:  # an exception after the running file still ends it
            _write_progress(ppath, {"state": "finished", "pass": False, "started_at": started,
                                    "finished_at": _now()})


def run_one(study_dir: Path, method: str, params: dict, timeout: float) -> tuple[dict, dict]:
    manifest, results = execute(study_dir, method, params, timeout,
                                progress_dir=Path(study_dir) / "runs" / ".progress")
    out = Path(study_dir) / "runs" / manifest["run_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    return manifest, results


def summary(manifest: dict, results: dict) -> str:
    head = f"{manifest['method']} " + " ".join(f"{k}={v}" for k, v in sorted(manifest["params"].items()))
    if results["status"] == "failed":
        return f"✗ {head}: failed — {results['reason']}"
    errs = ", ".join(f"{k} {v:.2e}" for k, v in results["errors"].items())
    verdict = "pass" if results["pass"] else "over tolerance"
    return f"{'✓' if results['pass'] else '•'} {head}: {verdict} ({errs}) → runs/{manifest['run_id']}"


def _same(a: dict | None, b: dict | None, rtol: float) -> bool:
    if a is None or b is None:
        return a == b
    if set(a) != set(b):
        return False
    return all(np.allclose(np.asarray(a[k]), np.asarray(b[k]), rtol=rtol, atol=1e-12) for k in a)


def repro(study_dir: Path, filters: dict, timeout: float) -> list[str]:
    sd = Path(study_dir).resolve()
    root = sd.parents[1]
    problems, matched = [], 0
    for mpath in sorted((sd / "runs").glob("*/manifest.json")):
        old = schema.load("manifest", mpath)
        if any(old["params"].get(k) != v for k, v in filters.items()):
            continue
        matched += 1
        old_res = schema.load("results", mpath.parent / "results.json")
        rid = old["run_id"]
        if provenance.inputs_hash(old["params"], sd / "problem") != old["inputs_hash"]:
            problems.append(f"{rid}: shared problem inputs changed since this run")
        if provenance.method_sha(root, sd / "methods" / old["method"]) != old["method_sha"]:
            problems.append(f"{rid}: solver changed since this run (method_sha differs)")
        _, new_res = execute(sd, old["method"], old["params"], timeout)
        if new_res["status"] != old_res["status"]:
            problems.append(f"{rid}: status was {old_res['status']}, now {new_res['status']}")
        elif not (_same(old_res["samples"], new_res["samples"], old["repro_rtol"])
                  and _same(old_res["errors"], new_res["errors"], old["repro_rtol"])):
            problems.append(f"{rid}: results differ beyond rtol {old['repro_rtol']:g}")
        print(f"{'✗' if any(p.startswith(rid + ':') for p in problems) else '✓'} {rid}")
    if matched == 0:
        problems.append(f"no runs match the filter {filters}")
    return problems

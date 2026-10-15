"""A study's checker: validation (positive control, mutations, saved attacks, grader copies), approval and the gate.

The checker folder (studies/<s>/checker/) lives outside problem/, so adding evidence never makes runs stale:
NOTE.md, answer.py (reference_answer and flags), attacks/<name>.py, review.json, transcripts/.
"""
import inspect
import json
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np

from . import bench, flow, graders, guard, runner, schema

MUTATIONS = ("nan", "inf", "wrong_shape", "zeros", "scaled", "shuffled")
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def _study(root: Path, study: str) -> Path:
    return Path(root) / "studies" / study


def _numeric(a) -> bool:
    return isinstance(a, (int, float, np.ndarray, np.generic, list, tuple)) and not isinstance(a, bool)


def _one(a, kind: str):
    try:
        x = np.array(a, dtype=float)
    except (TypeError, ValueError):
        return a
    if kind == "wrong_shape":
        return x[..., :-1] if x.ndim >= 1 and x.shape[-1] > 0 else np.append(x.ravel(), x.ravel())
    if kind == "zeros":
        return np.zeros_like(x)
    if kind == "scaled":
        return x * 1.5
    if kind == "shuffled":
        flat = x.ravel().copy()
        np.random.default_rng(0).shuffle(flat)
        return flat.reshape(x.shape)
    if x.size:
        x.flat[0] = np.nan if kind == "nan" else np.inf
    return x


def mutate(fields, kind: str):
    """A broken copy of an answer: every numeric array (inside dicts) changed the same way."""
    if kind not in MUTATIONS:
        raise ValueError(f"unknown mutation {kind!r}")
    if isinstance(fields, dict):
        return {k: mutate(v, kind) for k, v in fields.items()}
    return _one(fields, kind) if _numeric(fields) else fields


def _same(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if _numeric(a) and _numeric(b):
        x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        return x.shape == y.shape and bool(np.array_equal(x, y, equal_nan=True))
    return a == b


def _call(fn, setup, method):
    return fn(setup, method=method) if method is not None and "method" in inspect.signature(fn).parameters else fn(setup)


def _passes(measure_mod, setup, fields, reference, method) -> bool:
    try:
        out = (measure_mod.measure(setup, fields, reference, method=method) if method is not None
               else measure_mod.measure(setup, fields, reference))
    except Exception:
        return False
    return bool(out.get("pass"))


def run_attacks(root: Path, study: str, run_timeout: float) -> list[dict]:
    """Every checker/attacks/<name>.py, run as a method through the normal runner (guard included)."""
    sd = _study(root, study)
    files = sorted((sd / "checker" / "attacks").glob("*.py"))
    out = []
    if not files:
        return out
    with tempfile.TemporaryDirectory(prefix="raft-attack-") as tmp:
        g = Path(tmp) / "studies" / study
        shutil.copytree(sd / "problem", g / "problem", ignore=bench._IGNORE)
        shutil.copyfile(sd / "paper.yaml", g / "paper.yaml")
        (g / "methods").mkdir()
        combos = runner.expand(g, {})
        for f in files:
            if not NAME.fullmatch(f.stem):
                out.append({"name": f.stem, "blocked": False, "passed": [], "guard": [],
                            "bad_name": True})
                continue
            d = g / "methods" / f.stem
            d.mkdir()
            shutil.copyfile(f, d / "solver.py")
            passed = []
            for p in combos:
                _, r = runner.execute(g, f.stem, p, run_timeout)
                if r["pass"]:
                    passed.append(flow.case_label(p))
            out.append({"name": f.stem, "blocked": not passed, "passed": passed, "guard": guard.scan_method(d)})
    return out


def validate(root: Path, study: str, run_timeout: float = 1800.0, log=print) -> list[str]:
    """Every hole in a study's checker. Empty means the checker holds."""
    sd = _study(root, study)
    holes = list(graders.status(sd))
    ans_path = sd / "checker" / "answer.py"
    if not ans_path.is_file():
        holes.append("checker/answer.py is missing: write reference_answer(setup) and REFERENCE_ANSWER_PASSES")
    else:
        holes += _answer_checks(sd, ans_path, log)
    for a in run_attacks(root, study, run_timeout):
        if a.get("bad_name"):
            holes.append(f"checker/attacks/{a['name']}.py: attack file names must be lowercase letters, digits and hyphens")
        elif not a["blocked"]:
            holes.append(f"attack {a['name']} passes: {', '.join(a['passed'])}")
        else:
            log(f"✓ attack {a['name']} blocked" + (" (by the guard)" if a["guard"] else ""))
    holes += _review_checks(sd)
    return holes


def _answer_checks(sd: Path, ans_path: Path, log) -> list[str]:
    holes = []
    answer = runner.load_module(ans_path, f"raft_answer_{sd.name.replace('-', '_')}")
    setup_mod = runner._setup_module(sd, "checker")
    measure_mod = runner.load_measure(sd / "problem")
    reference = json.loads((sd / "problem" / "reference.json").read_text())
    takes_method = "method" in inspect.signature(measure_mod.measure).parameters
    names = list(getattr(answer, "METHODS", [])) if takes_method else [None]
    if takes_method and not names:
        return ["checker/answer.py must list METHODS: measure.py grades by method name"]
    flag = getattr(answer, "REFERENCE_ANSWER_PASSES", True)
    skips = getattr(answer, "SKIP_MUTATIONS", {}) or {}
    for k, reason in skips.items():
        if k not in MUTATIONS:
            holes.append(f"SKIP_MUTATIONS: unknown mutation {k!r} (have: {', '.join(MUTATIONS)})")
        elif not str(reason).strip():
            holes.append(f"SKIP_MUTATIONS[{k!r}] needs a reason")
    for method in names:
        expect = bool(flag[method]) if isinstance(flag, dict) else bool(flag)
        for params in runner.expand(sd, {}):
            label = " ".join(x for x in (method, flow.case_label(params)) if x)
            try:
                base = _call(answer.reference_answer, setup_mod.make_setup(params), method)
            except Exception as e:
                holes.append(f"{label}: reference_answer failed: {type(e).__name__}: {e}")
                continue
            got = _passes(measure_mod, setup_mod.make_setup(params), base, reference, method)
            if got != expect:
                holes.append(f"{label}: the reference answer {'passes' if got else 'fails'} "
                             f"(expected it to {'pass' if expect else 'fail'})")
            for kind in MUTATIONS:
                if kind in skips:
                    continue
                bad = mutate(base, kind)
                if _same(bad, base):
                    log(f"• {label}: mutation {kind!r} has no effect on this answer")
                    continue
                if _passes(measure_mod, setup_mod.make_setup(params), bad, reference, method):
                    holes.append(f"{label}: mutation {kind!r} passes")
    if not holes:
        log("✓ positive control and mutations")
    return holes


def _review_checks(sd: Path) -> list[str]:
    path = sd / "checker" / "review.json"
    if not path.is_file():
        return []
    try:
        review = schema.load("checker-review", path)
    except schema.ContractError as e:
        return [str(e)]
    return [f"review.json names attack {a['name']!r} but checker/attacks/{a['name']}.py does not exist"
            for r in review["rounds"] for a in r["attacks"]
            if not (sd / "checker" / "attacks" / f"{a['name']}.py").is_file()]

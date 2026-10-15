"""A study's checker: validation (positive control, mutations, saved attacks, grader copies), approval and the gate.

The checker folder (studies/<s>/checker/) lives outside problem/, so adding evidence never makes runs stale:
NOTE.md, answer.py (reference_answer and flags), attacks/<name>.py, review.json, transcripts/.
"""
import inspect
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import bench, flow, graders, guard, provenance, runner, schema

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


APPROVAL = "checker-approval.json"


def fingerprints(sd: Path) -> dict:
    return {"problem": provenance.tracked_hash(Path(sd) / "problem"),
            "checker": provenance.tracked_hash(Path(sd) / "checker", exclude=("transcripts",))}


def record_approval(root: Path, study: str, *, approved_by: dict, builder=None, attacker=None, rounds=None,
                    attacks=None) -> Path:
    sd = _study(root, study)
    fp = fingerprints(sd)
    rec = {"schema": 1, "study": study, "problem_hash": fp["problem"], "checker_hash": fp["checker"],
           "approved_by": approved_by, "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "builder_agent": builder, "attacker_agent": attacker, "rounds": rounds, "attacks": attacks}
    schema.check("checker-approval", rec)
    path = sd / APPROVAL
    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    return path


def approval_state(root: Path, study: str) -> dict:
    sd = _study(root, study)
    path = sd / APPROVAL
    if not path.is_file():
        return {"state": "missing", "rounds": None, "approved_at": None}
    rec = schema.load("checker-approval", path)
    fp = fingerprints(sd)
    if (rec["problem_hash"], rec["checker_hash"]) != (fp["problem"], fp["checker"]):
        state = "stale"
    else:
        state = "approved-before-attacks" if rec["attacks"] is None else "approved"
    return {"state": state, "rounds": rec["rounds"], "approved_at": rec["approved_at"]}


def gate(root: Path, study: str) -> None:
    state = approval_state(root, study)["state"]
    if state == "missing":
        raise SystemExit(f"raft: {study} has no approved checker. Run `raft validate` and `raft attack` (or "
                         f"`raft prepare --study {study}`), then `raft approve --study {study}` in your terminal.")
    if state == "stale":
        raise SystemExit(f"raft: {study}'s problem/ or checker/ changed since the checker was approved. Validate and "
                         f"attack it again, then `raft approve --study {study}` in your terminal.")


def _git_user(root: Path) -> dict:
    return {"name": provenance._git(root, "config", "user.name") or "unknown",
            "email": provenance._git(root, "config", "user.email") or "unknown"}


def _screen(sd: Path, review: dict | None, without_attacks: bool) -> list[str]:
    lines = [f"── Checker for {sd.name}", ""]
    note = sd / "checker" / "NOTE.md"
    lines += (note.read_text().rstrip().splitlines() if note.is_file() else ["(no checker/NOTE.md)"]) + [""]
    if without_attacks:
        lines.append("Approving WITHOUT attack rounds: this study was made before the checker gate existed.")
    else:
        lines.append(f"Built by {review['builder_agent']}, attacked by {review['attacker_agent']}.")
        for r in review["rounds"]:
            blocked = sum(a["blocked"] for a in r["attacks"])
            lines.append(f"  round {r['round']}: {len(r['attacks'])} tried, {blocked} blocked")
            lines += [f"    {'✓' if a['blocked'] else '✗'} {a['name']}: {a['idea']}" for a in r["attacks"]]
        ans = sd / "checker" / "answer.py"
        if ans.is_file():
            skips = getattr(runner.load_module(ans, f"raft_answer_screen_{sd.name.replace('-', '_')}"),
                            "SKIP_MUTATIONS", {}) or {}
            lines += [f"  skipped mutation {k}: {v}" for k, v in skips.items()]
    return lines + [""]


def _is_tty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:  # pytest's captured stdin and closed streams are not terminals
        return False


def approve(root: Path, study: str, *, without_attacks: bool = False, stdin=None, read=input, out=print,
            run_timeout: float = 1800.0) -> Path:
    root = Path(root)
    sd = _study(root, study)
    if not _is_tty(sys.stdin if stdin is None else stdin):
        raise SystemExit("raft: approve needs you at an interactive terminal; agents cannot approve a checker")
    if provenance.is_dirty(root, [sd / "problem", sd / "checker"]):
        raise SystemExit(f"raft: studies/{study}/problem or checker has uncommitted changes; commit them first")
    review = None
    if without_attacks:
        if not any((sd / "runs").glob("*/manifest.json")):
            raise SystemExit("raft: --without-attacks is only for a study with committed runs made before the gate")
    else:
        path = sd / "checker" / "review.json"
        review = schema.load("checker-review", path) if path.is_file() else None
        if not review or not review["rounds"]:
            raise SystemExit(f"raft: no attack rounds in studies/{study}/checker/review.json; run "
                             f"`raft prepare --study {study}` or `raft attack` first")
        holes = validate(root, study, run_timeout, log=lambda s: None)
        if holes:
            for h in holes:
                out(f"✗ {h}")
            raise SystemExit("raft: the checker does not hold; approval refused")
    for line in _screen(sd, review, without_attacks):
        out(line)
    if read(f"Type {study} to approve this checker: ").strip() != study:
        raise SystemExit("raft: not approved")
    attacks = None
    if review:
        flat = [a for r in review["rounds"] for a in r["attacks"]]
        attacks = {"tried": len(flat), "blocked": sum(a["blocked"] for a in flat)}
    return record_approval(root, study, approved_by=_git_user(root),
                           builder=review["builder_agent"] if review else None,
                           attacker=review["attacker_agent"] if review else None,
                           rounds=len(review["rounds"]) if review else None, attacks=attacks)

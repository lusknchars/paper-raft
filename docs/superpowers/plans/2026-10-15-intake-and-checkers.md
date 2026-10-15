# Intake and Checkers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `raft prepare --arxiv <id>` takes a paper from arXiv to a checker that agents built, a different agent attacked, and Paper Raft validated, stopping at an approval only the owner can give at a terminal; after approval the existing `raft bench`/`raft run` work on it.

**Architecture:** Five new modules. `raft/arxiv.py` fetches the OAI-PMH record and PDF (official endpoints only) and writes a draft study. `raft/graders/` is a versioned library (`checks`, `table`, `claims`) copied into a study's `problem/graders/`. `raft/checker.py` validates a checker (positive control, mutations of the reference answer, saved attacks run through the normal runner, grader copies), records the owner's approval and enforces the gate. `raft/prepare.py` drives the extractor, builder and attacker agents headless with `raft/agents.py`. CLI, roles, guard, site and docs are wired around them.

**Tech Stack:** Python 3.11+ standard library (urllib, xml.etree, unicodedata, email.utils), numpy, jsonschema, pyyaml. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-15-intake-and-checkers-design.md`

## Global Constraints

- Work in `~/paper-raft` on branch `intake-checkers`. `uv run pytest -q` stays green after every task.
- No new dependencies.
- arXiv only through `https://export.arxiv.org/oai2` and `https://arxiv.org/pdf/`; one request at a time, at least 3 s apart, User-Agent naming Paper Raft. PDFs go to `papers/` (gitignored) and are never committed.
- Never edit `studies/transduced-lm-2026/problem/` or `studies/ghia-1982/problem/`; never change a tolerance.
- Commit messages are plain: **no `Co-Authored-By` or "Generated with" lines.**
- `raft approve` only works with an interactive terminal (stdin is a TTY) and the owner typing the study id. No `--yes`, no bypass.
- No network in tests: arXiv is reached through an injectable opener.

## Decisions beyond the spec (rulings)

1. **Graders load as a package:** `problem/graders/__init__.py` plus `problem/graders/<name>.py`; `measure.py` does `from graders import claims`. `runner.load_measure` puts `problem/` on `sys.path` while loading and drops any cached `graders` modules first, so two studies in one process never share a copy.
2. **`answer.py` for studies that grade by method name:** it lists `METHODS`; `reference_answer(setup)` may take `method`; `REFERENCE_ANSWER_PASSES` is a bool or a `{method: bool}` map.
3. **Attacks are files `checker/attacks/<name>.py`;** the stem is the method folder name they run under, so `smc-rb--hardcode.py` is graded as `smc-rb` by a study whose `measure` uses the `-suffix` rule. An attack is blocked when no case passes.
4. **A mutation that leaves the answer unchanged** (shuffling a constant array, scaling zeros) is skipped automatically and reported as "no effect".
5. **`--without-attacks` is allowed only for a study that already has committed runs** (the proxy for "made before the gate"), and it skips validation, which those studies cannot pass without an `answer.py`.
6. **The gate checks hashes only,** not the study name inside the record, so a copied study (tests copy `tiny` to `tiny2`) stays approved when its files are identical.
7. **Checker hash** = git-tracked files under `checker/` except `transcripts/`; approval requires `problem/` and `checker/` committed. `bench.problem_hash` moves to the shared `provenance.tracked_hash`.
8. **The test that library graders reproduce the existing studies' numbers is dropped:** their runs store results, not raw fields, so it would need re-running solvers. Graders are tested on synthetic honest and cheating inputs instead.

## Review Focus

1. arXiv unreachable, or replying with an HTML error page instead of XML → one-line exit, nothing created (Task 3 tests).
2. A `measure.py` that raises on the reference answer (a bug in the checker) → validate names the case and the error, no traceback (Task 4 test).
3. Two studies that both use `graders` in one process (`compare`, `repro --all-studies`) → each uses its own copy (Task 1 test).
4. An agent (no TTY) tries `raft approve`, or `problem/`/`checker/` has uncommitted changes → refused (Task 6 tests).
5. An agent in `prepare` writes nothing or times out → a clear stop naming the step and the next command, transcripts kept (Task 7 test).

---

### Task 1: Tracked-files hash and measure loading with graders

**Files:**
- Modify: `raft/provenance.py` (add `tracked_hash`)
- Modify: `raft/runner.py` (add `load_measure`, use it in `execute`)
- Modify: `raft/bench.py` (`problem_hash` uses `tracked_hash`)
- Test: `tests/test_tracked_and_measure.py`

**Interfaces:**
- Produces: `provenance.tracked_hash(path: Path, exclude: tuple[str, ...] = ()) -> str`; `runner.load_measure(problem: Path) -> module`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tracked_and_measure.py`:

```python
import shutil

from conftest import commit_all, make_tiny_study

from raft import provenance, runner

MEASURE_WITH_GRADER = '''
from graders import scale


def measure(setup, fields, reference):
    return {"samples": {}, "errors": {"k": scale.K}, "tolerance": 1.0, "pass": True}
'''


def test_tracked_hash_ignores_untracked_and_excluded(tiny_git_study):
    root = tiny_git_study.parents[1]
    (root / ".gitignore").write_text("__pycache__/\n.DS_Store\n")
    commit_all(root, "ignore")
    problem = tiny_git_study / "problem"
    before = provenance.tracked_hash(problem)
    (problem / ".DS_Store").write_bytes(b"x")
    assert provenance.tracked_hash(problem) == before
    (problem / "setup.py").write_text((problem / "setup.py").read_text() + "\n# edit\n")
    assert provenance.tracked_hash(problem) != before


def test_tracked_hash_excludes_a_top_level_folder(tiny_git_study):
    root = tiny_git_study.parents[1]
    checker = tiny_git_study / "checker"
    (checker / "transcripts").mkdir(parents=True)
    (checker / "NOTE.md").write_text("note")
    (checker / "transcripts" / "a.jsonl").write_text("1")
    commit_all(root, "checker")
    before = provenance.tracked_hash(checker, exclude=("transcripts",))
    (checker / "transcripts" / "a.jsonl").write_text("2")
    commit_all(root, "transcript")
    assert provenance.tracked_hash(checker, exclude=("transcripts",)) == before


def test_tracked_hash_without_git_uses_every_file(tiny_study):
    problem = tiny_study / "problem"
    before = provenance.tracked_hash(problem)
    (problem / "extra.py").write_text("x = 1\n")
    assert provenance.tracked_hash(problem) != before
    assert provenance.tracked_hash(tiny_study / "missing") == provenance.tracked_hash(tiny_study / "missing2")


def test_each_study_loads_its_own_graders(tmp_path):
    sd = make_tiny_study(tmp_path)
    other = sd.parent / "tiny2"
    shutil.copytree(sd, other)
    for d, k in ((sd, 1), (other, 2)):
        (d / "problem" / "graders").mkdir()
        (d / "problem" / "graders" / "__init__.py").write_text("")
        (d / "problem" / "graders" / "scale.py").write_text(f"K = {k}\n")
        (d / "problem" / "measure.py").write_text(MEASURE_WITH_GRADER)
    a = runner.load_measure(sd / "problem").measure(None, None, None)["errors"]["k"]
    b = runner.load_measure(other / "problem").measure(None, None, None)["errors"]["k"]
    assert (a, b) == (1, 2)


def test_runs_use_graders(tmp_path):
    sd = make_tiny_study(tmp_path)
    (sd / "problem" / "graders").mkdir()
    (sd / "problem" / "graders" / "__init__.py").write_text("")
    (sd / "problem" / "graders" / "scale.py").write_text("K = 7\n")
    (sd / "problem" / "measure.py").write_text(MEASURE_WITH_GRADER)
    _, results = runner.execute(sd, "exact", {"n": 4}, 60)
    assert results["status"] == "ok" and results["errors"] == {"k": 7}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tracked_and_measure.py -q`
Expected: FAIL with `AttributeError: module 'raft.provenance' has no attribute 'tracked_hash'`.

- [ ] **Step 3: Implement**

Append to `raft/provenance.py`:

```python
def tracked_hash(path: Path, exclude: tuple[str, ...] = ()) -> str:
    """sha256 over the git-tracked files under `path`, so ignored clutter (.DS_Store) never changes it.

    Falls back to every file (minus caches) outside git or when nothing under `path` is tracked yet.
    Top-level names in `exclude` are skipped.
    """
    path = Path(path)
    names = []
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--", "."], cwd=path, capture_output=True, check=True).stdout
        names = sorted(n for n in out.decode().split("\0") if n)
    except (OSError, subprocess.CalledProcessError):
        names = []
    if not names and path.is_dir():
        names = sorted(f.relative_to(path).as_posix() for f in path.rglob("*")
                       if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc")
    h = hashlib.sha256()
    for n in names:
        f = path / n
        if n.split("/")[0] in exclude or not f.is_file():
            continue
        h.update(n.encode() + b"\0")
        h.update(f.read_bytes())
    return h.hexdigest()
```

In `raft/runner.py` add `import sys` to the imports, and after `load_module` add:

```python
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
```

In `execute`, replace `measure_mod = load_module(problem / "measure.py", "raft_measure")` with:

```python
            measure_mod = load_measure(problem)
```

In `raft/bench.py`, replace the body of `problem_hash` (the whole function) with:

```python
def problem_hash(sd: Path) -> str:
    """Hash of the git-tracked files in problem/, so ignored clutter (.DS_Store) never changes it."""
    return provenance.tracked_hash(Path(sd) / "problem")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_tracked_and_measure.py -q && uv run pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add raft/provenance.py raft/runner.py raft/bench.py tests/test_tracked_and_measure.py
git commit -m "Tracked-files hash; measure.py can import its copied graders"
```

---

### Task 2: Grader library and `raft grader add`

**Files:**
- Create: `raft/graders/__init__.py`, `raft/graders/checks.py`, `raft/graders/table.py`, `raft/graders/claims.py`
- Modify: `raft/cli.py` (`grader add`)
- Test: `tests/test_graders.py`

**Interfaces:**
- Produces: `graders.NAMES = ("checks", "table", "claims")`; `graders.library_text(name) -> str`; `graders.version(name) -> int`; `graders.add(study_dir: Path, name: str, force=False) -> Path`; `graders.status(study_dir: Path) -> list[str]` (problems; empty when every copy is current).
  `checks.require_keys(fields, keys)`, `checks.array(fields, key, shape, allow_neg_inf=False) -> np.ndarray`;
  `table.match(values, reference, tolerance, name="value") -> {"errors": {...}, "pass": bool}`;
  `claims.exact`, `claims.unbiased`, `claims.error_falls`, `claims.lower_bound`, `claims.within_budget`, each returning `{"errors": {...}, "pass": bool}`.
  CLI: `raft grader add <name> --study <s> [--force]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_graders.py`:

```python
import numpy as np
import pytest

from raft import cli, graders
from raft.graders import checks, claims, table


def test_checks_reject_junk():
    with pytest.raises(ValueError, match="keys"):
        checks.require_keys([1, 2], ["y"])
    with pytest.raises(ValueError, match="shape"):
        checks.array({"y": [1, 2]}, "y", (3,))
    with pytest.raises(ValueError, match="non-finite"):
        checks.array({"y": [1, np.nan]}, "y", (2,))
    assert checks.array({"y": [0, -np.inf]}, "y", (2,), allow_neg_inf=True)[1] == -np.inf
    with pytest.raises(ValueError, match="non-finite"):
        checks.array({"y": [0, np.inf]}, "y", (2,), allow_neg_inf=True)


def test_table_match():
    ok = table.match([1.0, 2.0], [1.0, 2.005], 0.01, name="u")
    assert ok["pass"] and ok["errors"]["u_max"] == pytest.approx(0.005)
    assert not table.match([1.0, 2.0], [1.0, 2.5], 0.01)["pass"]
    assert not table.match([np.nan, 2.0], [1.0, 2.0], 0.01)["pass"]
    with pytest.raises(ValueError, match="shape"):
        table.match([1.0], [1.0, 2.0], 0.01)


def test_exact_and_lower_bound():
    assert claims.exact([1.0, 2.0], [1.0, 2.0 + 1e-12], 1e-9)["pass"]
    assert not claims.exact([1.0, 2.1], [1.0, 2.0], 1e-9)["pass"]
    assert not claims.exact([np.inf], [1.0], 1e-9)["pass"]
    assert claims.lower_bound([0.9, 1.0], [1.0, 1.0], 1e-9)["pass"]
    assert not claims.lower_bound([1.1], [1.0], 1e-9)["pass"]


def test_unbiased_accepts_honest_noise_and_rejects_bias_and_constant():
    rng = np.random.default_rng(0)
    truth = np.array([2.0, 3.0])
    honest = truth[:, None] * rng.lognormal(-0.02, 0.2, size=(2, 256))
    assert claims.unbiased(honest, truth, 4.0)["pass"]
    biased = honest * 1.2
    assert not claims.unbiased(biased, truth, 4.0)["pass"]
    perfect = np.repeat(truth[:, None], 8, axis=1)
    assert claims.unbiased(perfect, truth, 4.0)["pass"]
    assert not claims.unbiased(perfect, truth, 4.0, min_rel_sd=1e-6)["pass"]
    with pytest.raises(ValueError, match="2 seeds"):
        claims.unbiased(truth[:, None], truth, 4.0)


def test_error_falls():
    rng = np.random.default_rng(1)
    truth = np.array([1.0])
    m = np.array([16, 256])
    good = 1 + rng.normal(size=(1, 2, 64)) / np.sqrt(m)[None, :, None]
    assert claims.error_falls(good, truth)["pass"]
    flat = 1 + rng.normal(size=(1, 2, 64)) * 0.1
    flat[:, 1] = flat[:, 0] * 1.5 - 0.5
    assert not claims.error_falls(flat, truth)["pass"]


def test_within_budget():
    assert claims.within_budget([4, 8], [4, 8])["pass"]
    out = claims.within_budget([5, 8], [4, 8])
    assert not out["pass"] and out["errors"]["max_over_budget"] == 1


def test_add_copies_with_header_and_status(tiny_study):
    path = graders.add(tiny_study, "claims")
    first = path.read_text().splitlines()[0]
    assert first.startswith(f"# raft-grader claims v{graders.version('claims')} sha256:")
    assert (tiny_study / "problem" / "graders" / "__init__.py").is_file()
    assert graders.status(tiny_study) == []
    with pytest.raises(SystemExit, match="already"):
        graders.add(tiny_study, "claims")
    path.write_text(path.read_text() + "\n# local edit\n")
    assert graders.status(tiny_study) == ["problem/graders/claims.py: edited after copying; copy it again with --force"]


def test_status_reports_behind(tiny_study, monkeypatch):
    graders.add(tiny_study, "table")
    monkeypatch.setattr(graders, "version", lambda name: 99)
    (msg,) = graders.status(tiny_study)
    assert "behind the library (v1 → v99)" in msg


def test_unknown_grader(tiny_study):
    with pytest.raises(SystemExit, match="no grader named 'nope'"):
        graders.add(tiny_study, "nope")


def test_cli_grader_add(tiny_git_study, monkeypatch, capsys):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["grader", "add", "table", "--study", "tiny"]) == 0
    assert "problem/graders/table.py" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_graders.py -q`
Expected: FAIL with `ImportError: cannot import name 'graders'`.

- [ ] **Step 3: Write the library**

`raft/graders/checks.py`:

```python
"""Checks every measure.py starts with: the method returned what setup.py promised."""
import numpy as np

VERSION = 1


def require_keys(fields, keys) -> dict:
    if not isinstance(fields, dict) or not set(keys) <= set(fields):
        raise ValueError(f"solve() must return a dict with keys {sorted(keys)}")
    return fields


def array(fields, key, shape, allow_neg_inf: bool = False) -> np.ndarray:
    a = np.asarray(fields[key], dtype=float)
    if a.shape != tuple(shape):
        raise ValueError(f"{key} has shape {a.shape}, expected {tuple(shape)}")
    bad = np.isnan(a) | np.isposinf(a)
    if not allow_neg_inf:
        bad = bad | np.isneginf(a)
    if bad.any():
        raise ValueError(f"non-finite values in {key}")
    return a
```

`raft/graders/table.py`:

```python
"""Grade numbers against a paper's table: the largest and the RMS difference at the table's own points."""
import numpy as np

VERSION = 1


def match(values, reference, tolerance: float, name: str = "value") -> dict:
    v, r = np.asarray(values, dtype=float), np.asarray(reference, dtype=float)
    if v.shape != r.shape or v.size == 0:
        raise ValueError(f"{name}: {v.shape} values against a table of shape {r.shape}")
    d = np.abs(v - r)
    d = np.where(np.isfinite(d), d, np.inf)
    mx = float(min(d.max(), 1e300))
    rms = float(min(np.sqrt(np.mean(np.minimum(d, 1e150) ** 2)), 1e300))
    return {"errors": {f"{name}_max": mx, f"{name}_rms": rms}, "pass": bool(mx <= tolerance)}
```

`raft/graders/claims.py`:

```python
"""Grade the claims papers make about estimators: exact, unbiased, error falls with budget, lower bound, budget."""
import math

import numpy as np

VERSION = 1
BIG = 1e300


def _f(x) -> float:
    x = float(x)
    return BIG if math.isnan(x) or x > BIG else x


def exact(estimate, truth, tolerance: float, name: str = "abs_error") -> dict:
    e = np.abs(np.asarray(estimate, dtype=float) - np.asarray(truth, dtype=float))
    e = np.where(np.isfinite(e), e, np.inf)
    m = _f(e.max())
    return {"errors": {f"max_{name}": m}, "pass": bool(m <= tolerance)}


def unbiased(estimates, truth, z_limit: float, min_rel_sd: float | None = None) -> dict:
    """estimates has seeds on the last axis; truth broadcasts to the other axes. z-test of the mean of Ẑ/Z per cell
    and pooled over cells. min_rel_sd: also require the spread of Ẑ/Z to exceed it (a constant answer is not an
    estimate)."""
    ratio = np.asarray(estimates, dtype=float) / np.asarray(truth, dtype=float)[..., None]
    n = ratio.shape[-1]
    if n < 2:
        raise ValueError("unbiased needs at least 2 seeds")
    mean, sd = ratio.mean(axis=-1), ratio.std(axis=-1, ddof=1)
    se = sd / math.sqrt(n)
    close = np.abs(mean - 1) <= 1e-9
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(close, 0.0, np.where(se > 0, np.abs(mean - 1) / se, np.inf))
    z = np.nan_to_num(z, nan=np.inf)
    live = ~close & (se > 0) & np.isfinite(se)
    pooled = (float(np.sum((mean - 1)[live] / se[live] ** 2) / math.sqrt(np.sum(1 / se[live] ** 2)))
              if live.any() else 0.0)
    errors = {"max_z": _f(z.max()), "pooled_z": _f(abs(pooled))}
    ok = errors["max_z"] <= z_limit and errors["pooled_z"] <= z_limit
    if min_rel_sd is not None:
        errors["min_rel_sd"] = _f(np.nan_to_num(sd, nan=0.0).min())
        ok = ok and errors["min_rel_sd"] > min_rel_sd
    return {"errors": errors, "pass": bool(ok)}


def error_falls(estimates, truth) -> dict:
    """estimates (..., budgets, seeds): the relative RMSE at the largest budget is below the smallest's in every cell."""
    ratio = np.asarray(estimates, dtype=float) / np.asarray(truth, dtype=float)[..., None, None]
    rmse = np.sqrt(np.mean((ratio - 1) ** 2, axis=-1)).reshape(-1, ratio.shape[-2])
    first, last = rmse[:, 0], rmse[:, -1]
    falls = (last < first) | ((last <= 1e-12) & (first <= 1e-12))
    worst = max((l / f if f > 0 else 0.0) for f, l in zip(first, last))
    return {"errors": {"worst_rmse_ratio": _f(worst)}, "pass": bool(np.all(falls) and np.all(np.isfinite(rmse)))}


def lower_bound(estimate, truth, tolerance: float) -> dict:
    share = np.asarray(estimate, dtype=float) / np.asarray(truth, dtype=float)
    over = _f(np.nan_to_num(share - 1, nan=np.inf).max())
    return {"errors": {"max_overshoot": over}, "pass": bool(over <= tolerance)}


def within_budget(used, limit) -> dict:
    over = _f((np.asarray(used, dtype=float) - np.asarray(limit, dtype=float)).max())
    return {"errors": {"max_over_budget": over}, "pass": bool(over <= 0)}
```

`raft/graders/__init__.py`:

```python
"""The grader library. Studies copy a grader into problem/graders/ (`raft grader add`); copies never change silently.

A copy starts with `# raft-grader <name> v<version> sha256:<hash of the library file>`, followed by the library
file verbatim. `status` reports copies that were edited or are behind the library.
"""
import hashlib
import re
from importlib.resources import files
from pathlib import Path

NAMES = ("checks", "table", "claims")
HEADER = re.compile(r"^# raft-grader (\w+) v(\d+) sha256:([0-9a-f]{64})$")


def library_text(name: str) -> str:
    if name not in NAMES:
        raise SystemExit(f"raft: no grader named {name!r} (have: {', '.join(NAMES)})")
    return files("raft.graders").joinpath(f"{name}.py").read_text()


def version(name: str) -> int:
    return int(re.search(r"^VERSION = (\d+)$", library_text(name), re.M).group(1))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def add(study_dir: Path, name: str, force: bool = False) -> Path:
    text = library_text(name)
    d = Path(study_dir) / "problem" / "graders"
    target = d / f"{name}.py"
    if target.exists() and not force:
        raise SystemExit(f"raft: {target} already exists; pass --force to replace it with the library's version")
    d.mkdir(parents=True, exist_ok=True)
    init = d / "__init__.py"
    if not init.exists():
        init.write_text('"""Graders copied from raft/graders (`raft grader add`). Do not edit; copy again instead."""\n')
    target.write_text(f"# raft-grader {name} v{version(name)} sha256:{_sha(text)}\n{text}")
    return target


def status(study_dir: Path) -> list[str]:
    problems = []
    d = Path(study_dir) / "problem" / "graders"
    for f in sorted(d.glob("*.py")) if d.is_dir() else []:
        if f.name == "__init__.py":
            continue
        rel = f"problem/graders/{f.name}"
        head, _, body = f.read_text().partition("\n")
        m = HEADER.match(head)
        if not m:
            problems.append(f"{rel}: no raft-grader header; copy it with `raft grader add`")
            continue
        name, ver, sha = m.group(1), int(m.group(2)), m.group(3)
        if name not in NAMES or f.stem != name:
            problems.append(f"{rel}: unknown grader {name!r}")
        elif _sha(body) != sha:
            problems.append(f"{rel}: edited after copying; copy it again with --force")
        elif ver < version(name):
            problems.append(f"{rel}: behind the library (v{ver} → v{version(name)}); copy it again with --force")
    return problems
```

Note: `files("raft.graders")` needs `raft/graders/` to be a package, which `__init__.py` makes it.

- [ ] **Step 4: Wire the CLI**

In `raft/cli.py`: add `"--force"` to `KNOWN`. After the `bench` parser lines, add:

```python
    gr = sub.add_parser("grader", help="copy a grader from the library into a study's problem/graders/")
    gr.add_argument("action", choices=("add",))
    gr.add_argument("name")
    gr.add_argument("--study")
    gr.add_argument("--force", action="store_true")
```

and, after the `bench` handler block (before `params = _params(rest)`):

```python
    if args.cmd == "grader":
        from . import graders
        study = paths.resolve_study(root, args.study)
        path = graders.add(root / "studies" / study, args.name, force=args.force)
        print(f"✓ copied {args.name} to {path.relative_to(root)}; use it in measure.py with `from graders import {args.name}`")
        return 0
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_graders.py -q && uv run pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 6: Commit**

```bash
git add raft/graders raft/cli.py tests/test_graders.py
git commit -m "Grader library (checks, table, claims) and raft grader add"
```

---

### Task 3: Intake from arXiv: `raft new --arxiv`

**Files:**
- Create: `raft/arxiv.py`
- Modify: `raft/cli.py` (`new` takes `--arxiv`, `--id`, `--brief`)
- Test: `tests/test_arxiv.py`

**Interfaces:**
- Consumes: `scaffold.new_study(root, study_id, title, doi) -> Path`.
- Produces: `arxiv.Fetcher(opener=None, clock=time.monotonic, sleep=time.sleep)` with `.get(url, limit) -> bytes` (opener signature `opener(url: str, limit: int) -> bytes`); `arxiv.parse_record(xml: bytes) -> dict` (`id, title, authors, abstract, license, version, year`); `arxiv.slug(authors, year, title) -> str`; `arxiv.intake(root, arxiv_id, *, study_id=None, brief=None, fetcher=None) -> Path` (the study folder).

- [ ] **Step 1: Write the failing tests**

`tests/test_arxiv.py`:

```python
import pytest
import yaml

from raft import arxiv, cli

RECORD = b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
<GetRecord><record><metadata>
<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
<id>2608.27428</id>
<version version="v1"><date>Mon, 31 Aug 2026 17:59:01 GMT</date><size>900kb</size></version>
<version version="v2"><date>Tue, 8 Sep 2026 10:00:00 GMT</date><size>910kb</size></version>
<title>Stochastic Estimation of
  Transduced Language Models</title>
<authors>V\xc3\xa9steinn Sn\xc3\xa6bjarnarson, Samuel Kiegeland, Manuel de Prada Corral, Ryan Cotterell and Tim Vieira</authors>
<license>http://creativecommons.org/licenses/by-sa/4.0/</license>
<abstract>  We estimate prefix probabilities.
</abstract>
</arXivRaw></metadata></record></GetRecord></OAI-PMH>"""

MISSING = b"""<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
<error code="idDoesNotExist">No matching identifier</error></OAI-PMH>"""

PDF = b"%PDF-1.5 tiny"


class FakeNet:
    def __init__(self, replies):
        self.replies, self.urls, self.t, self.sleeps = list(replies), [], 0.0, []

    def opener(self, url, limit):
        self.urls.append(url)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r[: limit + 1]

    def fetcher(self):
        return arxiv.Fetcher(opener=self.opener, clock=lambda: self.t, sleep=self.sleeps.append)


def test_parse_record():
    r = arxiv.parse_record(RECORD)
    assert r["title"] == "Stochastic Estimation of Transduced Language Models"
    assert r["authors"] == ["Vésteinn Snæbjarnarson", "Samuel Kiegeland", "Manuel de Prada Corral",
                            "Ryan Cotterell", "Tim Vieira"]
    assert r["year"] == 2026 and r["version"] == "v2" and r["abstract"] == "We estimate prefix probabilities."
    assert r["license"] == "http://creativecommons.org/licenses/by-sa/4.0/"


def test_slug():
    assert arxiv.slug(["Vésteinn Snæbjarnarson"], 2026, "Stochastic Estimation of X") == "snaebjarnarson-2026-stochastic"
    assert arxiv.slug(["Ann Lee"], 2020, "On the Size of It") == "lee-2020-size"


def test_intake_writes_a_draft_study(tiny_study):
    root = tiny_study.parents[1]
    net = FakeNet([RECORD, PDF])
    d = arxiv.intake(root, "2608.27428", brief="https://paperaft.vercel.app/papers/2608.27428/", fetcher=net.fetcher())
    assert d.name == "snaebjarnarson-2026-stochastic"
    paper = yaml.safe_load((d / "paper.yaml").read_text())
    assert paper["draft"] is True and paper["arxiv"] == "2608.27428"
    assert paper["doi"] == "10.48550/arXiv.2608.27428" and paper["pdf"] == f"papers/{d.name}.pdf"
    assert paper["pdf_url"] == "https://arxiv.org/pdf/2608.27428v2"
    assert paper["citation"] == ("Snæbjarnarson, Kiegeland, de Prada Corral et al. (2026). Stochastic Estimation of "
                                 "Transduced Language Models. arXiv:2608.27428.")
    assert paper["authors"][0] == "Vésteinn Snæbjarnarson" and paper["brief_url"].endswith("2608.27428/")
    assert (root / "papers" / f"{d.name}.pdf").read_bytes() == PDF
    assert net.urls[0].startswith("https://export.arxiv.org/oai2?") and "metadataPrefix=arXivRaw" in net.urls[0]
    assert net.sleeps == [3.0]


def test_intake_refuses_existing_id_before_downloading(tiny_study):
    net = FakeNet([RECORD, PDF])
    with pytest.raises(SystemExit, match="already exists"):
        arxiv.intake(tiny_study.parents[1], "2608.27428", study_id="tiny", fetcher=net.fetcher())
    assert len(net.urls) == 1


@pytest.mark.parametrize("replies, msg", [
    ([MISSING], "no record for that id"),
    ([b"<html>Service unavailable</html>"], "unexpected reply from arXiv"),
    ([OSError("network down")], "could not reach arXiv"),
    ([RECORD, b"<html>not a pdf</html>"], "not a PDF"),
    ([RECORD, b"%PDF" + b"x" * (arxiv.MAX_PDF + 10)], "larger than 50 MB"),
])
def test_intake_errors_leave_nothing_behind(tiny_study, replies, msg):
    root = tiny_study.parents[1]
    before = sorted(p.name for p in (root / "studies").iterdir())
    with pytest.raises(SystemExit, match=msg):
        arxiv.intake(root, "2608.27428", fetcher=FakeNet(replies).fetcher())
    assert sorted(p.name for p in (root / "studies").iterdir()) == before
    assert not (root / "papers").exists()


def test_bad_id():
    with pytest.raises(SystemExit, match="new-style arXiv id"):
        arxiv.intake(None, "2608.27428v1")


def test_cli_new_needs_title_without_arxiv(tiny_git_study, monkeypatch):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    with pytest.raises(SystemExit):
        cli.main(["new", "smith-2020"])


def test_cli_new_arxiv(tiny_git_study, monkeypatch, capsys):
    root = tiny_git_study.parents[1]
    monkeypatch.chdir(root)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    net = FakeNet([RECORD, PDF])
    monkeypatch.setattr(arxiv, "Fetcher", lambda: net.fetcher())
    assert cli.main(["new", "--arxiv", "2608.27428", "--id", "tl-2026"]) == 0
    assert (root / "studies" / "tl-2026" / "paper.yaml").is_file()
    assert "raft prepare --study tl-2026" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_arxiv.py -q`
Expected: FAIL with `ImportError: cannot import name 'arxiv'`.

- [ ] **Step 3: Write `raft/arxiv.py`**

```python
"""Fetch a paper's record and PDF from arXiv's official endpoints only (OAI-PMH and arxiv.org/pdf)."""
import json
import re
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import yaml

from . import scaffold

OAI = "https://export.arxiv.org/oai2?verb=GetRecord&identifier=oai:arXiv.org:{id}&metadataPrefix=arXivRaw"
PDF_URL = "https://arxiv.org/pdf/{id}{version}"
NS = {"oai": "http://www.openarchives.org/OAI/2.0/", "raw": "http://arxiv.org/OAI/arXivRaw/"}
USER_AGENT = "PaperRaft/0.1 (+https://github.com/lusknchars/paper-raft)"
MAX_PDF = 50 * 1024 * 1024
SPACING = 3.0
ID_RE = re.compile(r"\d{4}\.\d{4,5}")
_LETTERS = str.maketrans({"æ": "ae", "Æ": "ae", "ø": "o", "Ø": "o", "ß": "ss", "đ": "d", "ł": "l", "Ł": "l",
                          "þ": "th", "Þ": "th", "œ": "oe", "Œ": "oe"})


class Fetcher:
    """One request at a time, at least SPACING seconds apart, as arXiv asks."""

    def __init__(self, opener=None, clock=time.monotonic, sleep=time.sleep):
        self.opener, self.clock, self.sleep, self.last = opener or self._urlopen, clock, sleep, None

    @staticmethod
    def _urlopen(url: str, limit: int) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read(limit + 1)

    def get(self, url: str, limit: int = 5_000_000) -> bytes:
        if self.last is not None:
            wait = SPACING - (self.clock() - self.last)
            if wait > 0:
                self.sleep(wait)
        try:
            return self.opener(url, limit)
        except OSError as e:
            raise SystemExit(f"raft: could not reach arXiv ({e})") from None
        finally:
            self.last = self.clock()


def _split_authors(text: str) -> list[str]:
    return [a.strip() for a in re.split(r",\s*(?:and\s+)?|\s+and\s+", text) if a.strip()]


def parse_record(xml: bytes) -> dict:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise SystemExit("raft: unexpected reply from arXiv (not an OAI-PMH record)") from None
    err = root.find("oai:error", NS)
    if err is not None:
        raise SystemExit(f"raft: arXiv has no record for that id ({err.get('code')}: {(err.text or '').strip()})")
    raw = root.find(".//raw:arXivRaw", NS)
    if raw is None:
        raise SystemExit("raft: unexpected reply from arXiv (no arXivRaw record)")

    def text(tag):
        return " ".join((raw.findtext(f"raw:{tag}", "", NS) or "").split())

    versions = raw.findall("raw:version", NS)
    if not versions:
        raise SystemExit("raft: unexpected reply from arXiv (no versions)")
    first = parsedate_to_datetime(versions[0].findtext("raw:date", "", NS))
    return {"id": text("id"), "title": text("title"), "authors": _split_authors(text("authors")),
            "abstract": text("abstract"), "license": text("license") or None,
            "version": versions[-1].get("version"), "year": first.year}


def _ascii(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.translate(_LETTERS)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", plain)


def _surname(author: str) -> str:
    parts = author.split()
    return parts[-1] if parts else author


def slug(authors: list[str], year: int, title: str) -> str:
    word = next((_ascii(w) for w in title.split() if len(_ascii(w)) > 3), "paper")
    return f"{_ascii(_surname(authors[0])) if authors else 'anon'}-{year}-{word}"


def _citation(rec: dict, arxiv_id: str) -> str:
    names = [_surname(a) if " de " not in f" {a} " else a.split(" ", 1)[1] for a in rec["authors"]]
    who = ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")
    return f"{who} ({rec['year']}). {rec['title']}. arXiv:{arxiv_id}."


def intake(root: Path, arxiv_id: str, *, study_id: str | None = None, brief: str | None = None,
           fetcher: Fetcher | None = None) -> Path:
    if not ID_RE.fullmatch(arxiv_id or ""):
        raise SystemExit("raft: --arxiv takes a new-style arXiv id such as 2608.27428 (no version suffix)")
    root = Path(root)
    f = fetcher or Fetcher()
    rec = parse_record(f.get(OAI.format(id=arxiv_id)))
    sid = study_id or slug(rec["authors"], rec["year"], rec["title"])
    if (root / "studies" / sid).exists():
        raise SystemExit(f"raft: study {sid!r} already exists; pass --id to pick another name")
    pdf_url = PDF_URL.format(id=arxiv_id, version=rec["version"])
    pdf = f.get(pdf_url, limit=MAX_PDF)
    if len(pdf) > MAX_PDF:
        raise SystemExit("raft: the PDF is larger than 50 MB; download it yourself into papers/")
    if not pdf.startswith(b"%PDF-"):
        raise SystemExit(f"raft: {pdf_url} did not return a PDF")
    doi = f"10.48550/arXiv.{arxiv_id}"
    d = scaffold.new_study(root, sid, rec["title"], doi)
    citation = _citation(rec, arxiv_id)
    paper = yaml.safe_load((d / "paper.yaml").read_text())
    paper.update({"authors": rec["authors"], "citation": citation, "arxiv": arxiv_id, "pdf_url": pdf_url,
                  "license": rec["license"], "abstract": rec["abstract"]})
    if brief:
        paper["brief_url"] = brief
    (d / "paper.yaml").write_text(yaml.safe_dump(paper, sort_keys=False, allow_unicode=True))
    ref = json.loads((d / "problem" / "reference.json").read_text())
    ref["citation"] = citation
    (d / "problem" / "reference.json").write_text(json.dumps(ref, indent=2, ensure_ascii=False) + "\n")
    (root / "papers").mkdir(exist_ok=True)
    (root / "papers" / f"{sid}.pdf").write_bytes(pdf)
    return d
```

Note on `_citation`: "Manuel de Prada Corral" keeps "de Prada Corral" (everything after the first name) when the name has a lowercase particle `de`; other names use the last word.

- [ ] **Step 4: Wire the CLI**

In `raft/cli.py`, add `"--arxiv", "--id", "--brief"` to `KNOWN`. Replace the three `new` parser lines:

```python
    n = sub.add_parser("new", help="start a new study folder (a draft until problem/ is filled in)")
    n.add_argument("study_id", nargs="?")
    n.add_argument("--title")
    n.add_argument("--doi")
    n.add_argument("--arxiv", help="fetch the record and PDF from arXiv, e.g. 2608.27428")
    n.add_argument("--id", dest="new_id", help="with --arxiv: the study id (default: surname-year-word)")
    n.add_argument("--brief", help="with --arxiv: the paper's Paperraft brief URL")
```

Replace the `if args.cmd == "new":` block with:

```python
    if args.cmd == "new":
        if args.arxiv:
            from . import arxiv
            d = arxiv.intake(root, args.arxiv, study_id=args.new_id or args.study_id, brief=args.brief,
                             fetcher=arxiv.Fetcher())
            print(f"✓ created {d.relative_to(root)} from arXiv:{args.arxiv} (PDF in papers/, not committed). "
                  f"Next: `uv run raft prepare --study {d.name} --agent <claude-code|codex>`")
            return 0
        if not (args.study_id and args.title and args.doi):
            p.error("new needs a study id, --title and --doi (or --arxiv <id>)")
        d = scaffold.new_study(root, args.study_id, args.title, args.doi)
        print(f"✓ created {d.relative_to(root)} as a draft. Next: fill in problem/setup.py, problem/measure.py and "
              f"problem/reference.json, put the PDF at papers/{args.study_id}.pdf, delete `draft: true` from "
              f"paper.yaml, then run `uv run raft extract --study {args.study_id}`.")
        return 0
```

(`test_cli_new_arxiv` patches `arxiv.Fetcher` to a no-argument factory, which is why the CLI calls `arxiv.Fetcher()` with no arguments.)

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_arxiv.py tests/test_multi_study.py -q && uv run pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 6: Commit**

```bash
git add raft/arxiv.py raft/cli.py tests/test_arxiv.py
git commit -m "raft new --arxiv: record and PDF from arXiv's official endpoints"
```

---

### Task 4: Checker validation: `raft validate`

**Files:**
- Create: `raft/checker.py` (validation part)
- Create: `raft/contracts/checker-review.schema.json`
- Modify: `raft/schema.py` (`NAMES` += `"checker-review"`), `tests/test_schema.py` (sample)
- Modify: `raft/cli.py` (`validate`)
- Test: `tests/test_checker_validate.py`

**Interfaces:**
- Consumes: `graders.status`, `runner.load_measure`, `runner._setup_module`, `runner.expand`, `runner.execute`, `runner.run_id`, `flow.case_label`, `bench._IGNORE`.
- Produces: `checker.MUTATIONS`; `checker.mutate(fields, kind)`; `checker.run_attacks(root, study, run_timeout) -> list[dict]` (`name, blocked, passed: [case labels], guard: [str]`); `checker.validate(root, study, run_timeout=1800.0, log=print) -> list[str]` (holes; empty = holds). CLI `raft validate [--study s]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_checker_validate.py`:

```python
import json

import numpy as np
import pytest

from raft import checker, cli, schema

ANSWER = '''
import numpy as np

REFERENCE_ANSWER_PASSES = True
SKIP_MUTATIONS = {}


def reference_answer(setup):
    return {"y": np.linspace(0, 1, setup.n) ** 2}
'''

WEAK_MEASURE = '''
import numpy as np


def measure(setup, fields, reference):
    y = np.asarray(fields["y"], dtype=float)
    err = float(np.nanmax(np.abs(y))) if y.size else 0.0
    return {"samples": {}, "errors": {"y_max": err}, "tolerance": 10.0, "pass": True}
'''

ATTACK_ZEROS = '''
import numpy as np


def solve(setup):
    return {"y": np.zeros(setup.n)}
'''


def with_answer(sd, text=ANSWER):
    (sd / "checker").mkdir(exist_ok=True)
    (sd / "checker" / "answer.py").write_text(text)
    return sd


def test_good_checker_holds(tiny_study):
    with_answer(tiny_study)
    assert checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None) == []


def test_missing_answer(tiny_study):
    (holes,) = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert "checker/answer.py is missing" in holes


def test_weak_measure_is_caught_by_named_mutations(tiny_study):
    with_answer(tiny_study)
    (tiny_study / "problem" / "measure.py").write_text(WEAK_MEASURE)
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    for kind in ("nan", "inf", "wrong_shape", "zeros", "scaled", "shuffled"):
        assert any(f"mutation {kind!r} passes" in h for h in holes), kind


def test_reference_answer_must_pass_or_fail_as_declared(tiny_study):
    with_answer(tiny_study, ANSWER.replace("REFERENCE_ANSWER_PASSES = True", "REFERENCE_ANSWER_PASSES = False"))
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("the reference answer passes (expected it to fail)" in h for h in holes)


def test_measure_that_crashes_is_reported_not_raised(tiny_study):
    with_answer(tiny_study, ANSWER.replace("return {\"y\"", "raise RuntimeError('boom')\n    return {\"y\""))
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("reference_answer failed: RuntimeError: boom" in h for h in holes)


def test_skips_need_reasons_and_known_names(tiny_study):
    with_answer(tiny_study, ANSWER.replace("SKIP_MUTATIONS = {}", "SKIP_MUTATIONS = {'scaled': '', 'melt': 'x'}"))
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("SKIP_MUTATIONS['scaled'] needs a reason" in h for h in holes)
    assert any("unknown mutation 'melt'" in h for h in holes)


def test_attacks_run_through_the_runner(tiny_study):
    with_answer(tiny_study)
    (tiny_study / "checker" / "attacks").mkdir()
    (tiny_study / "checker" / "attacks" / "zeros.py").write_text(ATTACK_ZEROS)
    root = tiny_study.parents[1]
    (a,) = checker.run_attacks(root, "tiny", 60)
    assert a["name"] == "zeros" and a["blocked"] is True and a["passed"] == []
    (tiny_study / "problem" / "measure.py").write_text(WEAK_MEASURE)
    (a,) = checker.run_attacks(root, "tiny", 60)
    assert a["blocked"] is False and a["passed"] == ["4", "8"]
    assert any("attack zeros passes: 4, 8" in h for h in checker.validate(root, "tiny", 60, log=lambda s: None))


def test_bad_attack_name(tiny_study):
    with_answer(tiny_study)
    (tiny_study / "checker" / "attacks").mkdir()
    (tiny_study / "checker" / "attacks" / "Bad_Name.py").write_text(ATTACK_ZEROS)
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("Bad_Name.py: attack file names" in h for h in holes)


def test_review_must_match_schema_and_files(tiny_study):
    with_answer(tiny_study)
    (tiny_study / "checker" / "review.json").write_text(json.dumps({"study": "tiny", "builder_agent": "b",
        "attacker_agent": "a", "rounds": [{"round": 1, "attacks": [{"name": "ghost", "idea": "i", "blocked": True}]}]}))
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("review.json names attack 'ghost' but checker/attacks/ghost.py does not exist" in h for h in holes)


def test_stale_grader_copy_is_a_hole(tiny_study):
    from raft import graders
    with_answer(tiny_study)
    p = graders.add(tiny_study, "table")
    p.write_text(p.read_text() + "# edit\n")
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("edited after copying" in h for h in holes)


def test_mutate():
    base = {"y": np.array([1.0, 2.0, 3.0]), "label": "x", "k": 2.0}
    assert np.isnan(checker.mutate(base, "nan")["y"][0]) and base["y"][0] == 1.0
    assert checker.mutate(base, "wrong_shape")["y"].shape == (2,)
    assert checker.mutate(base, "wrong_shape")["k"].shape == (2,)
    assert checker.mutate(base, "zeros")["label"] == "x"
    assert list(checker.mutate(base, "scaled")["y"]) == [1.5, 3.0, 4.5]
    assert sorted(checker.mutate(base, "shuffled")["y"]) == [1.0, 2.0, 3.0]


def test_cli_validate(tiny_git_study, monkeypatch, capsys):
    with_answer(tiny_git_study)
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["validate"]) == 0
    assert "✓ tiny: the checker holds" in capsys.readouterr().out
```

Add to `VALID` in `tests/test_schema.py` (before the closing `}` of the dict):

```python
    "checker-review": {
        "study": "tiny", "builder_agent": "codex:checker-builder", "attacker_agent": "claude-code:checker-attacker",
        "rounds": [{"round": 1, "attacks": [{"name": "zeros", "idea": "return zeros", "blocked": True}]}],
    },
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_checker_validate.py -q`
Expected: FAIL with `ImportError: cannot import name 'checker'`.

- [ ] **Step 3: Write the schema**

`raft/contracts/checker-review.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Paper Raft checker review (the attacker's record)",
  "type": "object",
  "additionalProperties": false,
  "required": ["study", "builder_agent", "attacker_agent", "rounds"],
  "properties": {
    "study": {"type": "string", "minLength": 1},
    "builder_agent": {"type": "string", "minLength": 1},
    "attacker_agent": {"type": "string", "minLength": 1},
    "rounds": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false, "required": ["round", "attacks"],
        "properties": {
          "round": {"type": "integer", "minimum": 1},
          "attacks": {
            "type": "array",
            "items": {
              "type": "object", "additionalProperties": false, "required": ["name", "idea", "blocked"],
              "properties": {"name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
                             "idea": {"type": "string", "minLength": 1}, "blocked": {"type": "boolean"}}
            }
          }
        }
      }
    }
  }
}
```

Change `NAMES` in `raft/schema.py` to:

```python
NAMES = ("extraction", "method", "manifest", "results", "review", "reference", "flow", "bench-entry", "checker-review")
```

- [ ] **Step 4: Write `raft/checker.py` (validation)**

```python
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
```

- [ ] **Step 5: Wire the CLI**

In `raft/cli.py`, after the `grader` parser lines add:

```python
    va = sub.add_parser("validate", help="check a study's checker: reference answer, mutations, attacks, grader copies")
    va.add_argument("--study")
    va.add_argument("--run-timeout", type=_duration, default=1800.0)
```

and after the `grader` handler block:

```python
    if args.cmd == "validate":
        from . import checker
        study = paths.resolve_study(root, args.study)
        return _report(checker.validate(root, study, args.run_timeout), f"{study}: the checker holds")
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_checker_validate.py tests/test_schema.py -q && uv run pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 7: Commit**

```bash
git add raft/checker.py raft/contracts/checker-review.schema.json raft/schema.py raft/cli.py tests/test_checker_validate.py tests/test_schema.py
git commit -m "raft validate: positive control, mutations, saved attacks and grader copies"
```

---

### Task 5: Builder and attacker roles; guard and implementer rule

**Files:**
- Create: `roles/checker-builder.md`, `roles/checker-attacker.md`
- Modify: `roles/implementer.md` (rule about `checker/`), `raft/guard.py` (`checker/` forbidden), `raft/cli.py` (`build-checker`, `attack`)
- Modify: `tests/conftest.py` (fixture roles)
- Test: `tests/test_checker_roles.py`

**Interfaces:**
- Produces: CLI `raft build-checker [--study s]` and `raft attack [--study s] [--round N]` print the rendered role (attack replaces `{{round}}`).

- [ ] **Step 1: Fixture roles**

In `tests/conftest.py` `make_tiny_study`, change the role loop tuple to include the two new roles:

```python
    for role in ("extractor", "implementer", "reviewer", "checker-builder", "checker-attacker"):
```

- [ ] **Step 2: Write the failing tests**

`tests/test_checker_roles.py`:

```python
from pathlib import Path

from raft import cli, guard

ROOT = Path(__file__).resolve().parents[1]


def test_builder_role_names_every_deliverable():
    text = (ROOT / "roles" / "checker-builder.md").read_text()
    for needle in ("problem/setup.py", "problem/measure.py", "problem/reference.json", "raft grader add",
                   "checker/NOTE.md", "checker/answer.py", "REFERENCE_ANSWER_PASSES", "checker/attacks/",
                   "raft validate", "Never lower a tolerance"):
        assert needle in text, needle


def test_attacker_role_names_its_limits():
    text = (ROOT / "roles" / "checker-attacker.md").read_text()
    for needle in ("{{round}}", "checker/attacks/", "checker/review.json", "raft validate", "Never edit",
                   "raft approve"):
        assert needle in text, needle


def test_implementer_role_forbids_the_checker_folder():
    assert "checker/" in (ROOT / "roles" / "implementer.md").read_text()


def test_guard_forbids_mentioning_the_checker(tmp_path):
    (tmp_path / "solver.py").write_text('PATH = "../checker/answer.py"\n')
    (problem,) = guard.scan_method(tmp_path)
    assert "checker/" in problem


def test_cli_prints_briefs(tiny_git_study, monkeypatch, capsys):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["build-checker"]) == 0
    assert capsys.readouterr().out.startswith("# checker-builder for tiny")
    assert cli.main(["attack", "--round", "2"]) == 0
    assert capsys.readouterr().out.startswith("# checker-attacker for tiny")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_checker_roles.py -q`
Expected: FAIL (missing role files; `invalid choice: 'build-checker'`).

- [ ] **Step 4: Write the roles**

`roles/checker-builder.md`:

```markdown
# Role: checker builder for {{study}}

You turn the paper into a checker: the code that decides whether someone's implementation reproduces the paper's claims. Implementers and their agents will never see your work in `checker/`, and a different agent will try to cheat what you build. Write it so that only real work passes.

**Read:** the PDF at `{{pdf}}`, `{{study_dir}}/extraction.json` and `{{study_dir}}/paper.yaml`. Pick the experiment to reproduce: one whose claims the paper states clearly and that runs on a laptop in minutes. Say in `NOTE.md` what you cut to get there.

**Write:**
1. `{{study_dir}}/problem/setup.py`: a module docstring that defines exactly what `solve(setup)` receives and must return (keys, shapes, units, rules such as "draw randomness only from setup.rng"), `make_setup(params)`, `expand(params)` listing the cases, `HEADLINE` (the case shown first) and, if needed, `REPRO_RTOL`.
2. `{{study_dir}}/problem/measure.py`: `measure(setup, fields, reference)` (add a `method` parameter if methods are graded against different claims) returning `samples`, `errors`, `tolerance`, `pass`. Build it from library graders: run `uv run raft grader add checks --study {{study}}` (and `table` or `claims`), then `from graders import checks, claims`. Start with `checks` on every key and shape.
3. `{{study_dir}}/problem/reference.json`: the paper's numbers with `citation`, `doi`, `tolerance`, `cases`, and a `page` for every number. Set `verified_against_pdf` only after checking every number against the PDF.
4. `{{study_dir}}/checker/NOTE.md`: plain words. What is graded, what is not and why, which numbers come from where, every assumption.
5. `{{study_dir}}/checker/answer.py`: `reference_answer(setup)` (take `method` too if measure does), the best answer you can build from the paper; `REFERENCE_ANSWER_PASSES = True` (or `False`, or a `{method: bool}` map, when the claim is about estimation so a perfect closed-form answer must fail); `SKIP_MUTATIONS = {}` (only with a reason per entry); `METHODS = [...]` if measure grades by method name.
6. `{{study_dir}}/checker/attacks/<name>.py`: at least two cheating methods of your own, each a normal `solve(setup)` (hard-coded numbers, the right shape filled with junk). File names are lowercase with hyphens.

**Rules:** Never lower a tolerance to make something pass; say in `NOTE.md` that the paper's number cannot be met instead. Use numpy and scipy only. Do not write anything in `methods/`, `runs/` or `reviews/`.

**Done when** `uv run raft validate --study {{study}}` prints that the checker holds. Never run `raft approve`: only the owner approves.
```

`roles/checker-attacker.md`:

```markdown
# Role: checker attacker for {{study}}, round {{round}}

Someone built a checker for this paper. Your job is to break it: pass it without doing the paper's work. You did not build it and you never fix it.

**Read:** `{{study_dir}}/problem/` (setup.py, measure.py, reference.json, graders/), `{{study_dir}}/checker/NOTE.md`, `{{study_dir}}/checker/answer.py` and the attacks already in `{{study_dir}}/checker/attacks/`.

**Try, each as a new file `{{study_dir}}/checker/attacks/<name>.py` exposing `solve(setup)`:** hard-coded or memorised numbers; answers that only satisfy the shape and finiteness checks; exploiting a tolerance that is looser than the claim needs; skipping the claim's real condition (an "estimator" that returns the exact answer, a budget that is ignored); cases the grader never looks at; anything else you can think of. Your file must not mention `reference.json`, `measure`, `problem/`, `runs/`, `reviews/` or `checker/` (the guard rejects that, which is not an interesting attack).

After each try, run `uv run raft validate --study {{study}}` to see whether it got through.

**Record** every try in `{{study_dir}}/checker/review.json`: keep earlier rounds; add `{"round": {{round}}, "attacks": [{"name": "<file stem>", "idea": "<one sentence>", "blocked": true|false}]}`; set `attacker_agent` to an identifier of yourself and keep `builder_agent` as it is (if the file does not exist yet, set `study`, `builder_agent` from `checker/NOTE.md` or "unknown").

**Rules:** Never edit `problem/`, `checker/answer.py` or `checker/NOTE.md`. Never delete an attack. Never run `raft approve`. Report in your final message which attacks got through and why.
```

In `roles/implementer.md`, change rule 1 to:

```markdown
1. Never read, import or mention the shared measurement module, the reference data, `runs/`, `reviews/` or the study's `checker/` folder.
```

In `raft/guard.py`, change `FORBIDDEN_TEXT` to:

```python
FORBIDDEN_TEXT = ("reference.json", "measure", "problem/", "problem\\", "runs/", "reviews/", "checker/", "checker\\")
```

- [ ] **Step 5: Wire the CLI**

In `raft/cli.py`, add `"--round"` to `KNOWN`. After the `validate` parser lines:

```python
    sub.add_parser("build-checker", parents=[common], help="print the checker builder's brief")
    at = sub.add_parser("attack", parents=[common], help="print the checker attacker's brief")
    at.add_argument("--round", type=int, default=1)
```

In `_study_cmd`, before `if args.cmd == "repro":`, add:

```python
    if args.cmd == "build-checker":
        print(briefs.render(root, "checker-builder", study))
        return 0
    if args.cmd == "attack":
        print(briefs.render(root, "checker-attacker", study).replace("{{round}}", str(args.round)))
        return 0
```

and in `main`, extend the `--all-studies` single-study refusal so these two are refused with `--all-studies` too: change the `single = (...)` expression's first clause to `args.cmd in ("implement", "build-checker", "attack")`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_checker_roles.py tests/test_guard.py -q && uv run pytest -q`
Expected: PASS; full suite green (the existing lab methods never mention `checker/`).

- [ ] **Step 7: Commit**

```bash
git add roles raft/guard.py raft/cli.py tests/conftest.py tests/test_checker_roles.py
git commit -m "Checker builder and attacker roles; methods may not touch checker/"
```

---

### Task 6: Owner approval and the gate

**Files:**
- Modify: `raft/checker.py` (approval, state, gate)
- Create: `raft/contracts/checker-approval.schema.json`
- Modify: `raft/schema.py` (`NAMES` += `"checker-approval"`), `tests/test_schema.py` (sample)
- Modify: `raft/cli.py` (`approve`; gate on `run` and `implement`), `raft/bench.py` (gate in `run_bench`)
- Modify: `tests/conftest.py` (fixture study is approved)
- Test: `tests/test_checker_approval.py`

**Interfaces:**
- Produces: `checker.APPROVAL = "checker-approval.json"`; `checker.fingerprints(study_dir) -> {"problem", "checker"}`; `checker.record_approval(root, study, *, approved_by: dict, builder=None, attacker=None, rounds=None, attacks=None) -> Path`; `checker.approval_state(root, study) -> {"state": "approved" | "approved-before-attacks" | "stale" | "missing", "rounds": int | None, "approved_at": str | None}`; `checker.gate(root, study) -> None` (raises `SystemExit`); `checker.approve(root, study, *, without_attacks=False, stdin=None (sys.stdin at call time), read=input, out=print, run_timeout=1800.0) -> Path`.

- [ ] **Step 1: Approve the fixture study**

In `tests/conftest.py`, in `make_tiny_study`, right before `if git_repo:` add:

```python
    from raft import checker
    checker.record_approval(root, "tiny", approved_by={"name": "test", "email": "t@example.com"})
```

- [ ] **Step 2: Write the failing tests**

`tests/test_checker_approval.py`:

```python
import json

import pytest
from conftest import commit_all

from raft import checker, cli, schema
from test_checker_validate import ATTACK_ZEROS, with_answer


class Tty:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


def ready(sd):
    """A tiny study with a checker that holds, one attack round, everything committed."""
    with_answer(sd)
    (sd / "checker" / "attacks").mkdir()
    (sd / "checker" / "attacks" / "zeros.py").write_text(ATTACK_ZEROS)
    (sd / "checker" / "NOTE.md").write_text("Grades y = x^2 at n = 4 and 8.")
    (sd / "checker" / "review.json").write_text(json.dumps({
        "study": "tiny", "builder_agent": "codex:checker-builder", "attacker_agent": "claude-code:checker-attacker",
        "rounds": [{"round": 1, "attacks": [{"name": "zeros", "idea": "return zeros", "blocked": True}]}]}))
    commit_all(sd.parents[1], "checker")
    return sd.parents[1]


def test_fixture_study_is_approved(tiny_git_study):
    assert checker.approval_state(tiny_git_study.parents[1], "tiny")["state"] == "approved-before-attacks"


def test_approve_needs_a_terminal(tiny_git_study):
    root = ready(tiny_git_study)
    with pytest.raises(SystemExit, match="interactive terminal"):
        checker.approve(root, "tiny", stdin=Tty(False), read=lambda p: "tiny", out=lambda s: None)


def test_approve_needs_the_study_id_typed(tiny_git_study):
    root = ready(tiny_git_study)
    with pytest.raises(SystemExit, match="not approved"):
        checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "yes", out=lambda s: None)


def test_approve_writes_the_record(tiny_git_study):
    root = ready(tiny_git_study)
    shown = []
    path = checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "tiny", out=shown.append, run_timeout=60)
    rec = schema.load("checker-approval", path)
    assert rec["rounds"] == 1 and rec["attacks"] == {"tried": 1, "blocked": 1}
    assert rec["attacker_agent"] == "claude-code:checker-attacker" and rec["approved_by"]["name"] == "t"
    screen = "\n".join(shown)
    assert "Grades y = x^2" in screen and "round 1: 1 tried, 1 blocked" in screen
    assert checker.approval_state(root, "tiny") == {"state": "approved", "rounds": 1, "approved_at": rec["approved_at"]}


def test_approve_refuses_uncommitted_changes(tiny_git_study):
    root = ready(tiny_git_study)
    (tiny_git_study / "checker" / "NOTE.md").write_text("changed")
    with pytest.raises(SystemExit, match="commit them first"):
        checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "tiny", out=lambda s: None)


def test_approve_refuses_a_checker_with_holes(tiny_git_study):
    root = ready(tiny_git_study)
    (tiny_git_study / "checker" / "answer.py").write_text(
        (tiny_git_study / "checker" / "answer.py").read_text().replace("= True", "= False"))
    commit_all(root, "break")
    with pytest.raises(SystemExit, match="does not hold"):
        checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "tiny", out=lambda s: None, run_timeout=60)


def test_approve_without_attack_rounds_is_refused(tiny_git_study):
    root = tiny_git_study.parents[1]
    with_answer(tiny_git_study)
    commit_all(root, "answer")
    with pytest.raises(SystemExit, match="no attack rounds"):
        checker.approve(root, "tiny", stdin=Tty(True), read=lambda p: "tiny", out=lambda s: None, run_timeout=60)


def test_without_attacks_needs_committed_runs(tiny_git_study):
    root = tiny_git_study.parents[1]
    with pytest.raises(SystemExit, match="only for a study with committed runs"):
        checker.approve(root, "tiny", without_attacks=True, stdin=Tty(True), read=lambda p: "tiny",
                        out=lambda s: None)


def test_gate_blocks_after_a_change(tiny_git_study, monkeypatch):
    root = tiny_git_study.parents[1]
    monkeypatch.chdir(root)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["run", "exact", "--n", "4"]) == 0
    p = tiny_git_study / "problem" / "setup.py"
    p.write_text(p.read_text() + "\n# v2\n")
    commit_all(root, "v2")
    assert checker.approval_state(root, "tiny")["state"] == "stale"
    for argv in (["run", "exact", "--n", "4"], ["implement", "exact"]):
        with pytest.raises(SystemExit, match="changed since the checker was approved"):
            cli.main(argv)


def test_gate_blocks_without_approval(tiny_git_study, monkeypatch):
    root = tiny_git_study.parents[1]
    (tiny_git_study / checker.APPROVAL).unlink()
    commit_all(root, "no approval")
    monkeypatch.chdir(root)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    with pytest.raises(SystemExit, match="has no approved checker"):
        cli.main(["run", "exact", "--n", "4"])
    from raft import bench
    with pytest.raises(SystemExit, match="has no approved checker"):
        bench.run_bench(root, "tiny", "command", cmd="x {brief}", log=lambda s: None)


def test_cli_approve_refuses_without_tty(tiny_git_study, monkeypatch):
    monkeypatch.chdir(ready(tiny_git_study))
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    with pytest.raises(SystemExit, match="interactive terminal"):
        cli.main(["approve"])
```

Add to `VALID` in `tests/test_schema.py`:

```python
    "checker-approval": {
        "schema": 1, "study": "tiny", "problem_hash": HASH, "checker_hash": HASH,
        "approved_by": {"name": "Owner", "email": "o@example.com"}, "approved_at": "2026-10-15T00:00:00+00:00",
        "builder_agent": None, "attacker_agent": None, "rounds": None, "attacks": None,
    },
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_checker_approval.py -q`
Expected: FAIL (conftest error: `checker` has no attribute `record_approval`).

- [ ] **Step 4: Schema**

`raft/contracts/checker-approval.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Paper Raft checker approval (the owner's sign-off)",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "study", "problem_hash", "checker_hash", "approved_by", "approved_at", "builder_agent",
               "attacker_agent", "rounds", "attacks"],
  "properties": {
    "schema": {"const": 1},
    "study": {"type": "string", "minLength": 1},
    "problem_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "checker_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "approved_by": {"type": "object", "additionalProperties": false, "required": ["name", "email"],
                    "properties": {"name": {"type": "string"}, "email": {"type": "string"}}},
    "approved_at": {"type": "string"},
    "builder_agent": {"type": ["string", "null"]},
    "attacker_agent": {"type": ["string", "null"]},
    "rounds": {"type": ["integer", "null"], "minimum": 1},
    "attacks": {"type": ["object", "null"], "additionalProperties": false, "required": ["tried", "blocked"],
                "properties": {"tried": {"type": "integer", "minimum": 0}, "blocked": {"type": "integer", "minimum": 0}}}
  }
}
```

`raft/schema.py` `NAMES`:

```python
NAMES = ("extraction", "method", "manifest", "results", "review", "reference", "flow", "bench-entry", "checker-review",
         "checker-approval")
```

- [ ] **Step 5: Add approval and the gate to `raft/checker.py`**

Add `import sys` and `from datetime import datetime, timezone` to the imports, extend the package import to `from . import bench, flow, graders, guard, provenance, runner, schema`, then append:

```python
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
```

Note: `record_approval` writes the file outside `problem/` and `checker/`, so it never changes either fingerprint. In the fixture it is written before the first commit; untracked files hash the same through the fallback as tracked ones do later.

- [ ] **Step 6: Wire the CLI and bench**

In `raft/cli.py`, add `"--without-attacks"` to `KNOWN`; after the `attack` parser lines:

```python
    ap = sub.add_parser("approve", help="the owner's sign-off on a study's checker (interactive terminal only)")
    ap.add_argument("--study")
    ap.add_argument("--without-attacks", action="store_true",
                    help="only for a study with runs made before the checker gate")
    ap.add_argument("--run-timeout", type=_duration, default=1800.0)
```

after the `validate` handler block:

```python
    if args.cmd == "approve":
        from . import checker
        study = paths.resolve_study(root, args.study)
        path = checker.approve(root, study, without_attacks=args.without_attacks, run_timeout=args.run_timeout)
        print(f"✓ approved: {path.relative_to(root)}. Commit it; runs and bench now work on {study}.")
        return 0
```

In `_study_cmd`, change the implement branch and add the gate before runs:

```python
    if args.cmd == "implement":
        from . import checker
        checker.gate(root, study)
        print(briefs.render(root, "implementer", study, args.method))
        return 0
```

and right after `if args.all == bool(args.method): p.error("give one method name or --all")` add:

```python
    from . import checker
    checker.gate(root, study)
```

In `raft/bench.py` `run_bench`, right after `require_clean(root, study)` add:

```python
    from . import checker
    checker.gate(root, study)
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_checker_approval.py tests/test_schema.py -q && uv run pytest -q`
Expected: PASS; full suite green. If an existing test builds a study without `make_tiny_study` and then runs it, approve that study in the test with `checker.record_approval` and note it in the report.

- [ ] **Step 8: Commit**

```bash
git add raft/checker.py raft/contracts/checker-approval.schema.json raft/schema.py raft/cli.py raft/bench.py tests/conftest.py tests/test_checker_approval.py tests/test_schema.py
git commit -m "raft approve (terminal only) and the checker gate on run, implement and bench"
```

---

### Task 7: `raft prepare`: extractor, builder and attacker, headless

**Files:**
- Create: `raft/prepare.py`
- Modify: `raft/cli.py` (`prepare`)
- Test: `tests/test_prepare.py`

**Interfaces:**
- Consumes: `arxiv.intake`, `agents.check`, `agents.run`, `bench.trim_copy`, `briefs.render`, `validate.extraction`, `checker.validate`, `schema.load("checker-review", …)`.
- Produces: `prepare.prepare(root, *, agent, arxiv=None, study=None, study_id=None, brief_url=None, model=None, cmd=None, attacker=None, attacker_model=None, attacker_cmd=None, timeout=2700.0, run_timeout=1800.0, rounds=3, log=print, fetcher=None) -> str` (the study id). CLI `raft prepare`.

- [ ] **Step 1: Write the failing tests**

`tests/test_prepare.py`:

```python
import json
import shlex
import sys

import pytest

from raft import prepare
from test_checker_validate import ANSWER, ATTACK_ZEROS

FAKE = r'''
import json, os, sys
from pathlib import Path
brief = Path(sys.argv[1]).read_text()
sd = Path.cwd() / "studies" / "tiny"
mode = os.environ.get("FAKE_MODE", "good")
if mode == "silent":
    sys.exit(0)
if brief.startswith("# extractor"):
    (sd / "extraction.json").write_text(json.dumps({"study": "tiny", "items": [{"id": "tiny-method", "kind": "method",
        "text": "square x", "page": 1, "quote": "y = x^2", "missing": False}]}))
elif brief.startswith("# checker-builder"):
    (sd / "checker").mkdir(exist_ok=True)
    (sd / "checker" / "answer.py").write_text(os.environ["FAKE_ANSWER"])
    (sd / "checker" / "NOTE.md").write_text("note")
elif brief.startswith("# checker-attacker"):
    rnd = int(brief.split("round ")[1].split()[0]) if "round " in brief else 1
    a = sd / "checker" / "attacks"
    a.mkdir(parents=True, exist_ok=True)
    name = "honest" if mode == "holes" else f"zeros-{rnd}"
    (a / f"{name}.py").write_text(os.environ["FAKE_HONEST"] if mode == "holes" else os.environ["FAKE_ZEROS"])
    p = sd / "checker" / "review.json"
    rev = json.loads(p.read_text()) if p.exists() else {"study": "tiny", "builder_agent": "fake", "attacker_agent": "fake", "rounds": []}
    rev["rounds"].append({"round": rnd, "attacks": [{"name": name, "idea": "try", "blocked": mode != "holes"}]})
    p.write_text(json.dumps(rev))
'''

HONEST = "import numpy as np\n\n\ndef solve(setup):\n    xs = np.array([i / (setup.n - 1) for i in range(setup.n)])\n    return {'y': xs * xs}\n"


@pytest.fixture
def env(tiny_git_study, tmp_path, monkeypatch):
    root = tiny_git_study.parents[1]
    fake = tmp_path / "fake.py"
    fake.write_text(FAKE)
    monkeypatch.setenv("FAKE_ANSWER", ANSWER)
    monkeypatch.setenv("FAKE_ZEROS", ATTACK_ZEROS)
    monkeypatch.setenv("FAKE_HONEST", HONEST)
    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(fake))} {{brief}}"
    return root, cmd


def run(root, cmd, **kw):
    return prepare.prepare(root, study="tiny", agent="command", cmd=cmd, run_timeout=60, timeout=60,
                           log=lambda s: None, **kw)


def test_prepare_reaches_the_approval_step(env):
    root, cmd = env
    approval = (root / "studies" / "tiny" / "checker-approval.json").read_text()
    assert run(root, cmd) == "tiny"
    sd = root / "studies" / "tiny"
    review = json.loads((sd / "checker" / "review.json").read_text())
    assert len(review["rounds"]) == 1 and review["rounds"][0]["attacks"][0]["blocked"] is True
    names = sorted(p.name for p in (sd / "checker" / "transcripts").iterdir())
    assert any(n.startswith("build-") for n in names) and any(n.startswith("attack-") for n in names)
    assert (sd / "checker-approval.json").read_text() == approval  # prepare never approves


def test_prepare_fixes_a_broken_extraction(env):
    root, cmd = env
    (root / "studies" / "tiny" / "extraction.json").write_text("{not json")
    run(root, cmd)
    assert json.loads((root / "studies" / "tiny" / "extraction.json").read_text())["study"] == "tiny"


def test_prepare_resumes_without_redoing_finished_steps(env):
    root, cmd = env
    run(root, cmd)
    t = root / "studies" / "tiny" / "checker" / "transcripts"
    before = sorted(p.name for p in t.iterdir())
    run(root, cmd)
    assert sorted(p.name for p in t.iterdir()) == before


def test_prepare_stops_after_three_rounds_with_holes(env, monkeypatch):
    root, cmd = env
    monkeypatch.setenv("FAKE_MODE", "holes")
    with pytest.raises(SystemExit, match="holes remain after 3 attack rounds"):
        run(root, cmd)
    t = root / "studies" / "tiny" / "checker" / "transcripts"
    assert len([p for p in t.iterdir() if p.name.startswith("attack-") and p.suffix == ".jsonl"]) == 3


def test_prepare_stops_clearly_when_the_agent_does_nothing(env, monkeypatch):
    root, cmd = env
    monkeypatch.setenv("FAKE_MODE", "silent")
    with pytest.raises(SystemExit, match="the checker does not hold after 2 builder tries") as e:
        run(root, cmd)
    assert "raft prepare --study tiny" in str(e.value)
    assert any((root / "studies" / "tiny" / "checker" / "transcripts").iterdir())


def test_prepare_needs_one_source(env):
    root, cmd = env
    with pytest.raises(SystemExit, match="--arxiv or --study"):
        prepare.prepare(root, agent="command", cmd=cmd, log=lambda s: None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_prepare.py -q`
Expected: FAIL with `ImportError: cannot import name 'prepare'`.

- [ ] **Step 3: Write `raft/prepare.py`**

```python
"""raft prepare: from an arXiv id (or a draft study) to a checker ready for the owner's approval, with agents.

Steps, each skipped when its gate already passes, so a rerun resumes: intake → extract (gate: extract --validate)
→ build the checker (gate: raft validate) → attack rounds (gate: the last recorded round was fully blocked and the
checker still holds). It never approves.
"""
import tempfile
from pathlib import Path

from . import agents, bench, briefs, checker, schema, validate


def _transcript(sd: Path, step: str) -> Path:
    d = sd / "checker" / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob(f"{step}-*.jsonl"))) + 1
    return d / f"{step}-{n}.jsonl"


def _agent(root: Path, sd: Path, step: str, text: str, agent: str, model, cmd, timeout: float, log) -> None:
    with tempfile.TemporaryDirectory(prefix="raft-prepare-") as tmp:
        brief = Path(tmp) / "brief.md"
        brief.write_text(text)
        t = Path(tmp) / "t.jsonl"
        log(f"• {step}: {agent} …")
        r = agents.run(agent, brief, root, step, model=model, cmd=cmd, timeout=timeout, transcript=t)
        dest = _transcript(sd, step)
        bench.trim_copy(t, dest)
        if t.with_suffix(".stderr.txt").is_file() and t.with_suffix(".stderr.txt").stat().st_size:
            bench.trim_copy(t.with_suffix(".stderr.txt"), dest.with_suffix(".stderr.txt"))
        log(f"  {step}: " + ("timed out" if r["timed_out"] else f"agent exited {r['exit']}") + f" after {r['wall_s']:.0f}s")


def _with_problems(text: str, title: str, problems: list[str]) -> str:
    return text + f"\n\n**{title}:**\n" + "\n".join(f"- {p}" for p in problems) if problems else text


def _review_holds(sd: Path) -> bool:
    path = sd / "checker" / "review.json"
    if not path.is_file():
        return False
    try:
        rounds = schema.load("checker-review", path)["rounds"]
    except schema.ContractError:
        return False
    return bool(rounds) and all(a["blocked"] for a in rounds[-1]["attacks"])


def _rounds_done(sd: Path) -> int:
    path = sd / "checker" / "review.json"
    try:
        return len(schema.load("checker-review", path)["rounds"]) if path.is_file() else 0
    except schema.ContractError:
        return 0


def prepare(root: Path, *, agent: str, arxiv: str | None = None, study: str | None = None,
            study_id: str | None = None, brief_url: str | None = None, model=None, cmd=None, attacker=None,
            attacker_model=None, attacker_cmd=None, timeout: float = 2700.0, run_timeout: float = 1800.0,
            rounds: int = 3, log=print, fetcher=None) -> str:
    root = Path(root)
    if bool(arxiv) == bool(study):
        raise SystemExit("raft: prepare needs --arxiv or --study (one of them)")
    agents.check(agent, model=model, cmd=cmd)
    attacker = attacker or agent
    if attacker == agent and attacker_cmd is None:
        attacker_cmd, attacker_model = cmd, attacker_model or model
    agents.check(attacker, model=attacker_model, cmd=attacker_cmd)
    if arxiv:
        from . import arxiv as intake
        study = intake.intake(root, arxiv, study_id=study_id, brief=brief_url,
                              fetcher=fetcher or intake.Fetcher()).name
        log(f"✓ intake: studies/{study}")
    sd = root / "studies" / study
    if not (sd / "paper.yaml").is_file():
        raise SystemExit(f"raft: no study {study!r}")
    next_step = f"Fix it by hand or rerun `uv run raft prepare --study {study} --agent {agent}`."

    problems = validate.extraction(sd)
    for attempt in range(2):
        if not problems:
            break
        text = _with_problems(briefs.render(root, "extractor", study), "Problems from the last attempt",
                              problems if attempt else [])
        _agent(root, sd, "extract", text, agent, model, cmd, timeout, log)
        problems = validate.extraction(sd)
    if problems:
        raise SystemExit(f"raft: extraction still fails after 2 tries:\n  " + "\n  ".join(problems) + f"\n{next_step}")
    log("✓ extraction")

    holes = checker.validate(root, study, run_timeout, log=lambda s: None)
    built = not holes
    for attempt in range(2):
        if not holes:
            break
        text = _with_problems(briefs.render(root, "checker-builder", study), "Holes from the last attempt",
                              holes if attempt else [])
        _agent(root, sd, "build", text, agent, model, cmd, timeout, log)
        holes = checker.validate(root, study, run_timeout, log=lambda s: None)
    if holes:
        raise SystemExit("raft: the checker does not hold after 2 builder tries:\n  " + "\n  ".join(holes)
                         + f"\n{next_step}")
    log("✓ checker validates")

    if built and _review_holds(sd):
        log("✓ attacks: the last recorded round was fully blocked")
    else:
        for i in range(rounds):
            rnd = _rounds_done(sd) + 1
            text = briefs.render(root, "checker-attacker", study).replace("{{round}}", str(rnd))
            _agent(root, sd, "attack", text, attacker, attacker_model, attacker_cmd, timeout, log)
            holes = checker.validate(root, study, run_timeout, log=lambda s: None)
            if not holes:
                log(f"✓ round {rnd}: every attack was blocked")
                break
            if i == rounds - 1:
                raise SystemExit(f"raft: holes remain after {rounds} attack rounds:\n  " + "\n  ".join(holes)
                                 + f"\nRead studies/{study}/checker/review.json and decide: fix problem/ yourself, "
                                 f"or rerun `uv run raft prepare --study {study}`.")
            text = _with_problems(briefs.render(root, "checker-builder", study),
                                  "Attacks or checks that got through; fix problem/ so they fail", holes)
            _agent(root, sd, "build", text, agent, model, cmd, timeout, log)
    log(f"Ready for your approval. Read studies/{study}/checker/, commit it, then run in your terminal:\n"
        f"  uv run raft approve --study {study}")
    return study
```

Note on the "holes" test: the fake builder never fixes anything, so every round's honest attack passes; after round 3 `prepare` stops. Builder fixes run between rounds (two of them), so the transcript count for `attack-` is exactly 3.

- [ ] **Step 4: Wire the CLI**

In `raft/cli.py`, add `"--attacker", "--attacker-model", "--attacker-cmd", "--rounds"` to `KNOWN`. After the `approve` parser lines:

```python
    pr = sub.add_parser("prepare", help="from an arXiv id or a draft study to a checker ready for your approval, with agents")
    pr.add_argument("--arxiv")
    pr.add_argument("--study")
    pr.add_argument("--id", dest="new_id")
    pr.add_argument("--brief")
    pr.add_argument("--agent", choices=("claude-code", "codex", "command"), required=True)
    pr.add_argument("--model")
    pr.add_argument("--cmd", dest="agent_cmd")
    pr.add_argument("--attacker", choices=("claude-code", "codex", "command"))
    pr.add_argument("--attacker-model")
    pr.add_argument("--attacker-cmd")
    pr.add_argument("--timeout", type=_duration, default=2700.0, help="per agent step (default 45m)")
    pr.add_argument("--run-timeout", type=_duration, default=1800.0)
    pr.add_argument("--rounds", type=int, default=3)
```

and after the `approve` handler:

```python
    if args.cmd == "prepare":
        from . import prepare
        prepare.prepare(root, agent=args.agent, arxiv=args.arxiv, study=args.study, study_id=args.new_id,
                        brief_url=args.brief, model=args.model, cmd=args.agent_cmd, attacker=args.attacker,
                        attacker_model=args.attacker_model, attacker_cmd=args.attacker_cmd, timeout=args.timeout,
                        run_timeout=args.run_timeout, rounds=args.rounds)
        return 0
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_prepare.py -q && uv run pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 6: Commit**

```bash
git add raft/prepare.py raft/cli.py tests/test_prepare.py
git commit -m "raft prepare: extractor, checker builder and attacker run headless up to the owner's approval"
```

---

### Task 8: Checker state on the site; docs

**Files:**
- Modify: `raft/compare.py` (`checker` state per study), `raft/site_template/app.js` (show it)
- Modify: `README.md`, `CONTRIBUTING.md`, `adapters/claude-code/.claude/skills/reproduce-paper/SKILL.md`
- Test: `tests/test_compare.py` (add a test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_compare.py`:

```python
def test_site_data_has_the_checker_state(tiny_git_study):
    from raft import compare
    (study,) = compare.build(tiny_git_study.parents[1], None)["studies"]
    assert study["checker"]["state"] == "approved-before-attacks"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_compare.py -q -k checker_state`
Expected: FAIL with `KeyError: 'checker'`.

- [ ] **Step 3: Implement**

In `raft/compare.py`, extend the package import with `checker`, and in `build` add to the dict appended to `data["studies"]` (after `"counts": …`):

```python
            "checker": checker.approval_state(root, sd.name),
```

In `raft/site_template/app.js`, add after the `badge` const:

```js
const CHECKER = {
  "approved": (c) => `checker approved after ${c.rounds} attack round${c.rounds === 1 ? "" : "s"}`,
  "approved-before-attacks": () => "checker approved before attack rounds existed",
  "stale": () => "checker changed since approval",
  "missing": () => "checker not approved",
};
const checkerLine = (s) => s.checker ? el("p", { class: "muted" }, CHECKER[s.checker.state](s.checker)) : null;
```

In `overview()`, inside the study card, after the `el("p", { class: "muted" }, s.reference.citation)` element add `checkerLine(s),`. In `studyNav(study)`, after the citation paragraph element add `checkerLine(study),`.

- [ ] **Step 4: Docs**

README: add after the Bench section:

```markdown
## Add a paper with one command

    uv run raft prepare --arxiv 2608.27428 --agent codex --attacker claude-code

Paper Raft fetches the record and PDF from arXiv (official endpoints only; the PDF stays in `papers/`, never
committed), has an agent extract the paper and build its checker (the grader, in `problem/`, plus a plain
`checker/NOTE.md` on what is and is not tested), and has a second agent attack that checker for up to three rounds.
Paper Raft itself checks every checker: the paper's own answer must pass (or fail, when the claim is about
estimation), broken copies of it (NaN, wrong shape, zeros, scaled, shuffled) must fail, and every saved attack must
fail. It stops at your approval:

    uv run raft approve --study <study>

which only works in your terminal, where you read the note and the attack rounds and type the study id. After
that, `raft bench` and `raft run` work on the new paper, and they refuse to run if the checker changes until it is
attacked and approved again. Step by step instead: `raft new --arxiv`, `raft extract`, `raft build-checker`,
`raft validate`, `raft attack`, `raft approve`. Graders come from a small library: `raft grader add <checks|table|claims>`.
```

CONTRIBUTING: replace the first sentence of "Add a study (a new paper)" with:

```markdown
For an arXiv paper, run `uv run raft prepare --arxiv <id> --agent <claude-code|codex>` (see the README); it ends at `raft approve`, which only the maintainer runs. By hand: start with `uv run raft new <id> --title "…" --doi "…"` (or `raft new --arxiv <id>`).
```

Append to `adapters/claude-code/.claude/skills/reproduce-paper/SKILL.md`:

```markdown
For a paper that has no study yet, `uv run raft prepare --arxiv <id> --agent claude-code` builds and attacks its checker. Never run `raft approve`; the owner does.
```

- [ ] **Step 5: Run everything**

Run: `uv run pytest -q && uv run raft compare && node scripts/check_bench.mjs site && node scripts/check_flow.mjs site`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add raft/compare.py raft/site_template/app.js README.md CONTRIBUTING.md adapters/claude-code/.claude/skills/reproduce-paper/SKILL.md tests/test_compare.py
git commit -m "Checker state on the site; docs for raft prepare and approve"
```

---

## After the plan (owner)

1. `uv run raft approve --study transduced-lm-2026 --without-attacks` in your terminal, then commit the record. Until then `raft bench` and `raft run` refuse that study.
2. One real `raft prepare --arxiv <id> --agent codex --attacker claude-code` on a laptop-sized paper from the Paperraft collection, then read `checker/` and approve or reject.

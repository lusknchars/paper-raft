# Paper Raft v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an open-source harness where agents reproduce a paper (Ghia, Ghia & Shin 1982, Re = 100 lid-driven cavity) through file contracts, guarded parallel implementations, independent reviews and a static results site.

**Architecture:** A small Python package `raft` (CLI + JSON Schemas + runner + status + site builder) knows nothing about fluids. Each paper is a *study* folder holding a shared, read-only `problem/` (setup, measurement, reference data), one folder per method, run outputs and reviews. Agent roles are plain markdown prompts rendered by the CLI; Claude Code is the first adapter.

**Tech Stack:** Python ≥ 3.11, uv (lockfile), numpy, scipy, jsonschema, pyyaml, pytest; static HTML/JS with Chart.js 4.4.1 from cdnjs; GitHub Actions + Pages.

**Spec:** `docs/specs/2026-10-12-paper-raft-design.md`

## Global Constraints

- Python ≥ 3.11; dependencies limited to numpy, scipy, jsonschema, pyyaml (runtime) and pytest (dev); `uv.lock` committed; everything runs via `uv run`.
- Licence Apache-2.0. Paper PDFs are never committed; `papers/` is gitignored.
- Implementers write only inside `studies/<study>/methods/<name>/`; they never read, import or mention `problem/measure.py`, `problem/reference.json`, `runs/` or `reviews/`.
- Every result carries a status, `verified | unverified | failed`, derived by one function (`raft.status.derive_status`) used by both the CLI and the site.
- A run is verified only when `pass` is true, the run is not dirty, a review exists with verdict `verified`, and `reviewed_sha` equals the run's `method_sha` (last commit touching the method folder as of the run).
- Failed runs are written and shown, never dropped.
- v1 success: at least one method reproduces Ghia Re = 100 on a 129×129 grid with max absolute error ≤ 1e-2 on both centrelines and is reviewer-verified; all three methods have runs and reviews; a fresh clone reproduces with `uv sync && uv run raft run --all --re 100 && uv run raft compare`.
- Reproducibility: rerunning a manifest reproduces results within its recorded `repro_rtol` (1e-8 relative by default).
- No API key is needed to rerun and check results.
- Nothing is pushed to GitHub or published until the owner says so (Task 14).

## Contract additions beyond the spec text

These follow from the spec's own rules and are recorded here so reviewers aren't surprised:
- manifest gains `method_sha`, `dirty` and `repro_rtol` (needed for the verified rule and for the rerun tolerance)
- results gain optional `reference_samples` and `fields_coarse` (so the site can plot the paper's points and the streamfunction view without knowing about fluids)
- review gains an optional `summary`
- "Fields" is a plain dict `{"u", "v"}` rather than a class, so methods never import shared code

## Review Focus

1. **Running `raft` in the wrong place or with a wrong name** (outside a checkout, unknown study, unknown method, bad `--re`): a reasonable person expects a one-line `raft: …` message and exit code ≠ 0, never a traceback. Pinned in Task 6 (`test_cli_errors`).
2. **A method that crashes, hangs, returns NaN or the wrong shape**: expected to produce a written `failed` result with a readable reason while `raft run --all` carries on with the next method. Pinned in Task 5 (`test_failures_are_written`, `test_timeout`).
3. **Editing a solver after it was reviewed**: the "verified" badge must drop to "unverified" until it is re-reviewed. Pinned in Task 2 (`test_status_review_for_other_commit`) and Task 10 (`test_compare_status_follows_review_commit`).
4. **Running with uncommitted solver changes**: the manifest records `dirty: true` and the run can never show as verified. Pinned in Task 2 (`test_status_dirty_never_verified`) and Task 4 (`test_dirty_detection`).
5. **Opening the site straight from disk (`file://`), or before any run exists**: it must still render (data comes from `data.js`, not `fetch`), and show "No runs for this combination." / "No data.js found…" rather than a blank page. Pinned in Task 10 (`test_write_site_files`, plus the manual check in Step 10.7).

---

## File map

```
paper-raft/
  pyproject.toml  uv.lock  .gitignore  LICENSE  README.md  CONTRIBUTING.md
  CITATION.cff  CODE_OF_CONDUCT.md  .github/workflows/ci.yml  .github/ISSUE_TEMPLATE/*.md
  raft/
    __init__.py
    paths.py            repo root + study resolution
    schema.py           load/validate contract files
    contracts/          __init__.py + six *.schema.json
    provenance.py       git sha, method sha, dirty flag, inputs hash, package versions
    status.py           derive_status (single source of truth)
    guard.py            static yardstick-isolation scan of a method folder
    runner.py           load modules, execute in a child process, write runs, repro
    briefs.py           render roles/*.md for a study/method
    validate.py         extraction + method.json + review cross-checks
    compare.py          build site data + write static site
    cli.py              argparse entry point `raft`
    site_template/      __init__.py, index.html, app.js, style.css
  roles/                extractor.md implementer.md reviewer.md
  adapters/claude-code/.claude/agents/*.md, skills/reproduce-paper/SKILL.md
  .claude -> adapters/claude-code/.claude   (symlink)
  studies/ghia-1982/
    paper.yaml  extraction.json
    problem/setup.py  problem/measure.py  problem/reference.json
    methods/{streamfunction-vorticity,projection,lattice-boltzmann}/solver.py + method.json
    runs/<run-id>/manifest.json + results.json
    reviews/<method>.json
  tests/
    conftest.py  test_schema.py  test_status.py  test_provenance.py  test_ghia_problem.py
    test_guard.py  test_runner.py  test_cli.py  test_validate.py  test_compare.py
    test_adapter.py  test_golden.py
```

---

### Task 1: Scaffold, contracts and schema validation

**Files:**
- Create: `pyproject.toml`, `.gitignore` (replace), `raft/__init__.py`, `raft/paths.py`, `raft/schema.py`, `raft/contracts/__init__.py`, `raft/contracts/{extraction,method,manifest,results,review,reference}.schema.json`
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces: `raft.schema.errors(name: str, obj) -> list[str]`, `raft.schema.load(name: str, path: Path) -> dict` (raises `raft.schema.ContractError`), `raft.schema.check(name, obj) -> None` (raises `ContractError`), `raft.schema.NAMES`. `raft.paths.repo_root() -> Path`, `raft.paths.resolve_study(root: Path, name: str | None) -> str`.

- [ ] **Step 1.1: Project files**

`pyproject.toml`:
```toml
[project]
name = "paper-raft"
version = "0.1.0"
description = "Agents reproduce research papers in a controlled environment."
readme = "README.md"
license = "Apache-2.0"
requires-python = ">=3.11"
dependencies = ["numpy>=1.26", "scipy>=1.11", "jsonschema>=4.21", "pyyaml>=6.0"]

[project.scripts]
raft = "raft.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["raft"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`.gitignore`:
```
papers/
site/
.venv/
__pycache__/
*.pyc
.pytest_cache/
.DS_Store
```

`raft/__init__.py`:
```python
"""Paper Raft: agents reproduce research papers in a controlled environment."""
__version__ = "0.1.0"
```

`raft/contracts/__init__.py`: empty file (makes the folder a resource package).

Run: `cd ~/paper-raft && uv sync` (creates `.venv` and `uv.lock`). Expected: completes without errors.

- [ ] **Step 1.2: Write the failing schema tests**

`tests/test_schema.py`:
```python
import json

import pytest

from raft import schema

SHA = "a" * 40
HASH = "b" * 64

VALID = {
    "extraction": {
        "study": "ghia-1982",
        "extractor_agent": "claude-code:raft-extractor",
        "items": [
            {"id": "vorticity-transport", "kind": "equation", "text": "w_t + u w_x + v w_y = (1/Re) lap w",
             "page": 389, "quote": "vorticity transport equation", "missing": False},
            {"id": "convergence-tolerance", "kind": "parameter", "text": "stopping tolerance",
             "page": 392, "quote": "", "missing": True, "assumption": "stop when max residual < 1e-7"},
        ],
    },
    "method": {"name": "projection", "implements": ["vorticity-transport"], "author_agent": "claude-code:raft-implementer#projection"},
    "manifest": {
        "run_id": "projection-grid129-re100", "study": "ghia-1982", "method": "projection",
        "params": {"re": 100, "grid": 129}, "inputs_hash": HASH, "git_sha": SHA, "method_sha": SHA,
        "dirty": False, "python": "3.12.3", "packages": {"numpy": "2.1.0"}, "seed": 0,
        "started_at": "2026-10-12T18:00:00+00:00", "duration_s": 12.5, "repro_rtol": 1e-8,
    },
    "results": {
        "run_id": "projection-grid129-re100", "status": "ok",
        "samples": {"u_vertical": [[0.0, 0.0], [1.0, 1.0]]},
        "reference_samples": {"u_vertical": [[0.0, 0.0], [1.0, 1.0]]},
        "errors": {"u_max": 0.001}, "tolerance": 0.01, "pass": True,
        "fields_coarse": {"psi": [[0.0, 0.0], [0.0, -0.1]]},
    },
    "review": {
        "method": "projection", "reviewed_sha": SHA, "reviewer_agent": "claude-code:raft-reviewer#projection",
        "verdict": "verified", "summary": "matches", "discrepancies": [],
    },
    "reference": {"citation": "Ghia et al. 1982", "doi": "10.1016/0021-9991(82)90058-4", "tolerance": 0.01,
                  "cases": {"100": {"u_vertical": [[0, 0], [1, 1]], "v_horizontal": [[0, 0], [1, 0]]}}},
}


@pytest.mark.parametrize("name", schema.NAMES)
def test_valid_samples_pass(name):
    assert schema.errors(name, VALID[name]) == []


def test_extraction_item_needs_page():
    bad = json.loads(json.dumps(VALID["extraction"]))
    del bad["items"][0]["page"]
    assert any("page" in e for e in schema.errors("extraction", bad))


def test_missing_item_needs_assumption():
    bad = json.loads(json.dumps(VALID["extraction"]))
    del bad["items"][1]["assumption"]
    assert any("assumption" in e for e in schema.errors("extraction", bad))


def test_failed_results_need_reason_and_null_samples():
    bad = {"run_id": "x", "status": "failed", "samples": None, "errors": None, "tolerance": None, "pass": False}
    assert any("reason" in e for e in schema.errors("results", bad))
    good = {**bad, "reason": "timeout after 5s"}
    assert schema.errors("results", good) == []
    worse = {**good, "pass": True}
    assert schema.errors("results", worse) != []


def test_verified_review_allows_only_minor_discrepancies():
    bad = json.loads(json.dumps(VALID["review"]))
    bad["discrepancies"] = [{"file": "solver.py", "line": 3, "extraction_id": "x", "page": 1,
                             "description": "sign flipped", "severity": "major"}]
    assert schema.errors("review", bad) != []
    bad["verdict"] = "discrepancies"
    assert schema.errors("review", bad) == []


def test_discrepancies_verdict_needs_at_least_one():
    bad = {**VALID["review"], "verdict": "discrepancies"}
    assert schema.errors("review", bad) != []


def test_load_reports_path_and_errors(tmp_path):
    p = tmp_path / "method.json"
    p.write_text(json.dumps({"name": "x"}))
    with pytest.raises(schema.ContractError) as exc:
        schema.load("method", p)
    assert str(p) in str(exc.value) and "implements" in str(exc.value)


def test_load_reports_bad_json(tmp_path):
    p = tmp_path / "method.json"
    p.write_text("{not json")
    with pytest.raises(schema.ContractError, match="not valid JSON"):
        schema.load("method", p)
```

- [ ] **Step 1.3: Run tests to verify they fail**

Run: `uv run pytest tests/test_schema.py -q`
Expected: FAIL / error with `ImportError: cannot import name 'schema'`.

- [ ] **Step 1.4: Write the schemas**

`raft/contracts/extraction.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Extraction: implementable facts from a paper, each with a page",
  "type": "object",
  "additionalProperties": false,
  "required": ["study", "items"],
  "properties": {
    "study": {"type": "string", "minLength": 1},
    "extractor_agent": {"type": "string"},
    "items": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "kind", "text", "page", "quote", "missing"],
        "properties": {
          "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
          "kind": {"enum": ["method", "equation", "parameter", "boundary_condition", "result"]},
          "text": {"type": "string", "minLength": 1},
          "page": {"type": "integer", "minimum": 1},
          "quote": {"type": "string"},
          "missing": {"type": "boolean"},
          "assumption": {"type": "string", "minLength": 1}
        },
        "if": {"properties": {"missing": {"const": true}}},
        "then": {"required": ["assumption"]}
      }
    }
  }
}
```

`raft/contracts/method.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Method: which extraction items an implementation covers",
  "type": "object",
  "additionalProperties": false,
  "required": ["name", "implements", "author_agent"],
  "properties": {
    "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
    "implements": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    "author_agent": {"type": "string", "minLength": 1},
    "notes": {"type": "string"}
  }
}
```

`raft/contracts/manifest.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Run manifest: everything needed to rerun",
  "type": "object",
  "additionalProperties": false,
  "required": ["run_id", "study", "method", "params", "inputs_hash", "git_sha", "method_sha", "dirty",
               "python", "packages", "seed", "started_at", "duration_s", "repro_rtol"],
  "properties": {
    "run_id": {"type": "string", "minLength": 1},
    "study": {"type": "string"},
    "method": {"type": "string"},
    "params": {"type": "object", "additionalProperties": {"type": ["number", "string"]}},
    "inputs_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "git_sha": {"type": "string"},
    "method_sha": {"type": ["string", "null"]},
    "dirty": {"type": "boolean"},
    "python": {"type": "string"},
    "packages": {"type": "object", "additionalProperties": {"type": "string"}},
    "seed": {"type": "integer"},
    "started_at": {"type": "string"},
    "duration_s": {"type": "number", "minimum": 0},
    "repro_rtol": {"type": "number", "exclusiveMinimum": 0}
  }
}
```

`raft/contracts/results.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Run results: samples, errors vs reference, status",
  "type": "object",
  "additionalProperties": false,
  "required": ["run_id", "status", "samples", "errors", "tolerance", "pass"],
  "$defs": {
    "series": {
      "type": "object",
      "additionalProperties": {
        "type": "array",
        "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
      }
    },
    "grid2d": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}
  },
  "properties": {
    "run_id": {"type": "string"},
    "status": {"enum": ["ok", "failed"]},
    "reason": {"type": "string", "minLength": 1},
    "samples": {"oneOf": [{"$ref": "#/$defs/series"}, {"type": "null"}]},
    "reference_samples": {"$ref": "#/$defs/series"},
    "errors": {"oneOf": [{"type": "object", "additionalProperties": {"type": "number"}}, {"type": "null"}]},
    "tolerance": {"type": ["number", "null"]},
    "pass": {"type": "boolean"},
    "fields_coarse": {"type": "object", "additionalProperties": {"$ref": "#/$defs/grid2d"}}
  },
  "if": {"properties": {"status": {"const": "failed"}}},
  "then": {
    "required": ["reason"],
    "properties": {"samples": {"type": "null"}, "errors": {"type": "null"}, "pass": {"const": false}}
  },
  "else": {
    "properties": {"samples": {"type": "object"}, "errors": {"type": "object"}, "tolerance": {"type": "number"}}
  }
}
```

`raft/contracts/review.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Review: one implementation checked against the paper",
  "type": "object",
  "additionalProperties": false,
  "required": ["method", "reviewed_sha", "reviewer_agent", "verdict", "discrepancies"],
  "properties": {
    "method": {"type": "string"},
    "reviewed_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
    "reviewer_agent": {"type": "string", "minLength": 1},
    "verdict": {"enum": ["verified", "discrepancies", "unverified"]},
    "summary": {"type": "string"},
    "discrepancies": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["file", "line", "extraction_id", "page", "description", "severity"],
        "properties": {
          "file": {"type": "string"},
          "line": {"type": "integer", "minimum": 1},
          "extraction_id": {"type": "string"},
          "page": {"type": "integer", "minimum": 1},
          "description": {"type": "string", "minLength": 1},
          "severity": {"enum": ["minor", "major", "blocking"]}
        }
      }
    }
  },
  "allOf": [
    {"if": {"properties": {"verdict": {"const": "discrepancies"}}},
     "then": {"properties": {"discrepancies": {"minItems": 1}}}},
    {"if": {"properties": {"verdict": {"const": "verified"}}},
     "then": {"properties": {"discrepancies": {"items": {"properties": {"severity": {"const": "minor"}}}}}}}
  ]
}
```

`raft/contracts/reference.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Reference data published in the paper",
  "type": "object",
  "required": ["citation", "doi", "tolerance", "cases"],
  "properties": {
    "citation": {"type": "string", "minLength": 1},
    "doi": {"type": "string", "minLength": 1},
    "tolerance": {"type": "number", "exclusiveMinimum": 0},
    "cases": {"type": "object", "additionalProperties": {"type": "object"}}
  }
}
```

- [ ] **Step 1.5: Write `raft/schema.py` and `raft/paths.py`**

`raft/schema.py`:
```python
"""Load and validate the JSON contract files every stage hands to the next."""
import json
from functools import cache
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator

NAMES = ("extraction", "method", "manifest", "results", "review", "reference")


class ContractError(Exception):
    """A contract file is missing, not JSON, or does not match its schema."""


@cache
def _validator(name: str) -> Draft202012Validator:
    if name not in NAMES:
        raise KeyError(f"unknown contract {name!r}; expected one of {NAMES}")
    text = files("raft.contracts").joinpath(f"{name}.schema.json").read_text()
    return Draft202012Validator(json.loads(text))


def errors(name: str, obj) -> list[str]:
    found = sorted(_validator(name).iter_errors(obj), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in found]


def check(name: str, obj) -> None:
    errs = errors(name, obj)
    if errs:
        raise ContractError(f"{name} does not match its schema:\n  " + "\n  ".join(errs))


def load(name: str, path: Path) -> dict:
    path = Path(path)
    try:
        obj = json.loads(path.read_text())
    except FileNotFoundError:
        raise ContractError(f"{path}: file not found") from None
    except json.JSONDecodeError as e:
        raise ContractError(f"{path}: not valid JSON ({e})") from None
    errs = errors(name, obj)
    if errs:
        raise ContractError(f"{path}:\n  " + "\n  ".join(errs))
    return obj
```

`raft/paths.py`:
```python
"""Find the Paper Raft checkout and its studies."""
import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("RAFT_ROOT")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / "studies").is_dir() and (d / "pyproject.toml").is_file():
            return d
    raise SystemExit("raft: run this inside a Paper Raft checkout (no studies/ folder found), or set RAFT_ROOT")


def studies(root: Path) -> list[str]:
    base = root / "studies"
    return sorted(d.name for d in base.iterdir() if (d / "paper.yaml").is_file()) if base.is_dir() else []


def resolve_study(root: Path, name: str | None) -> str:
    have = studies(root)
    if name:
        if name not in have:
            raise SystemExit(f"raft: unknown study {name!r} (have: {', '.join(have) or 'none'})")
        return name
    if len(have) == 1:
        return have[0]
    raise SystemExit(f"raft: pass --study (have: {', '.join(have) or 'none'})")
```

- [ ] **Step 1.6: Run tests to verify they pass**

Run: `uv run pytest tests/test_schema.py -q`
Expected: all PASS.

- [ ] **Step 1.7: Commit**

```bash
git add pyproject.toml uv.lock .gitignore raft tests/test_schema.py
git commit -m "Scaffold raft package with contract schemas and validation"
```

---

### Task 2: Status derivation

**Files:**
- Create: `raft/status.py`
- Test: `tests/test_status.py`

**Interfaces:**
- Consumes: dicts shaped by `results`, `manifest`, `review` schemas (Task 1).
- Produces: `raft.status.derive_status(results: dict, manifest: dict, review: dict | None) -> str` returning `"verified" | "unverified" | "failed"`.

- [ ] **Step 2.1: Write the failing tests**

`tests/test_status.py`:
```python
from raft.status import derive_status

SHA = "c" * 40
OK = {"status": "ok", "pass": True}
MAN = {"dirty": False, "method_sha": SHA}
REV = {"verdict": "verified", "reviewed_sha": SHA}


def test_status_verified():
    assert derive_status(OK, MAN, REV) == "verified"


def test_status_failed_wins():
    assert derive_status({"status": "failed", "pass": False}, MAN, REV) == "failed"


def test_status_no_review():
    assert derive_status(OK, MAN, None) == "unverified"


def test_status_over_tolerance_is_unverified():
    assert derive_status({"status": "ok", "pass": False}, MAN, REV) == "unverified"


def test_status_review_for_other_commit():
    assert derive_status(OK, {**MAN, "method_sha": "d" * 40}, REV) == "unverified"


def test_status_dirty_never_verified():
    assert derive_status(OK, {**MAN, "dirty": True}, REV) == "unverified"


def test_status_uncommitted_method_never_verified():
    assert derive_status(OK, {**MAN, "method_sha": None}, REV) == "unverified"


def test_status_review_with_discrepancies():
    assert derive_status(OK, MAN, {**REV, "verdict": "discrepancies"}) == "unverified"
```

- [ ] **Step 2.2: Run to verify failure**

Run: `uv run pytest tests/test_status.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'raft.status'`.

- [ ] **Step 2.3: Implement**

`raft/status.py`:
```python
"""The one place that decides whether a run is verified, unverified or failed."""


def derive_status(results: dict, manifest: dict, review: dict | None) -> str:
    if results["status"] == "failed":
        return "failed"
    verified = (
        results["pass"]
        and not manifest["dirty"]
        and manifest["method_sha"] is not None
        and review is not None
        and review["verdict"] == "verified"
        and review["reviewed_sha"] == manifest["method_sha"]
    )
    return "verified" if verified else "unverified"
```

- [ ] **Step 2.4: Run to verify pass**

Run: `uv run pytest tests/test_status.py -q`
Expected: 8 passed.

- [ ] **Step 2.5: Commit**

```bash
git add raft/status.py tests/test_status.py
git commit -m "Derive run status from results, manifest and review"
```

---

### Task 3: Ghia study problem (setup, reference data, measurement)

**Files:**
- Create: `studies/ghia-1982/paper.yaml`, `studies/ghia-1982/problem/setup.py`, `studies/ghia-1982/problem/reference.json`, `studies/ghia-1982/problem/measure.py`
- Test: `tests/test_ghia_problem.py`

**Interfaces:**
- Produces (the generic study contract every study's `problem/` must follow, used by Task 5):
  - `setup.py`: `make_setup(params: dict) -> setup object` (raises `ValueError` on bad params), `expand(params: dict) -> list[dict]` (fill missing params from `RUN_MATRIX`), `HEADLINE: dict`, optional `REPRO_RTOL: float`.
  - `measure.py`: `measure(setup, fields, reference: dict) -> dict` with keys `samples`, `reference_samples`, `errors`, `tolerance`, `pass`, optional `fields_coarse`; raises `ValueError` for bad fields.
  - Ghia specifics: `CavitySetup(re, grid, lid_velocity=1.0, length=1.0)` with `.h`, `.nu`, `.nodes()`; methods return `{"u": ndarray, "v": ndarray}` of shape `(grid, grid)` indexed `[j, i]`.

- [ ] **Step 3.1: Write `paper.yaml` and `reference.json`**

`studies/ghia-1982/paper.yaml`:
```yaml
title: "High-Re solutions for incompressible flow using the Navier–Stokes equations and a multigrid method"
authors: ["U. Ghia", "K. N. Ghia", "C. T. Shin"]
citation: "Ghia, U., Ghia, K. N., & Shin, C. T. (1982). Journal of Computational Physics, 48(3), 387–411."
doi: "10.1016/0021-9991(82)90058-4"
pdf: "papers/ghia-1982.pdf"
experiment: "Lid-driven square cavity, centreline velocity profiles (Tables I and II), Re = 100 on a 129×129 grid"
```

`studies/ghia-1982/problem/reference.json`. These are the published Table I/II values for Re = 100 and 1000 as commonly reproduced. **Task 7 verifies every number against the PDF and fills the page fields.** Until then they are unverified.
```json
{
  "citation": "Ghia, U., Ghia, K. N., & Shin, C. T. (1982). J. Comput. Phys. 48, 387–411. Tables I and II.",
  "doi": "10.1016/0021-9991(82)90058-4",
  "tolerance": 0.01,
  "verified_against_pdf": false,
  "cases": {
    "100": {
      "table_u": "I", "table_v": "II", "page_u": null, "page_v": null,
      "u_vertical": [[0.0000, 0.00000], [0.0547, -0.03717], [0.0625, -0.04192], [0.0703, -0.04775],
                     [0.1016, -0.06434], [0.1719, -0.10150], [0.2813, -0.15662], [0.4531, -0.21090],
                     [0.5000, -0.20581], [0.6172, -0.13641], [0.7344, 0.00332], [0.8516, 0.23151],
                     [0.9531, 0.68717], [0.9609, 0.73722], [0.9688, 0.78871], [0.9766, 0.84123],
                     [1.0000, 1.00000]],
      "v_horizontal": [[0.0000, 0.00000], [0.0625, 0.09233], [0.0703, 0.10091], [0.0781, 0.10890],
                       [0.0938, 0.12317], [0.1563, 0.16077], [0.2266, 0.17507], [0.2344, 0.17527],
                       [0.5000, 0.05454], [0.8047, -0.24533], [0.8594, -0.22445], [0.9063, -0.16914],
                       [0.9453, -0.10313], [0.9531, -0.08864], [0.9609, -0.07391], [0.9688, -0.05906],
                       [1.0000, 0.00000]]
    },
    "1000": {
      "table_u": "I", "table_v": "II", "page_u": null, "page_v": null,
      "u_vertical": [[0.0000, 0.00000], [0.0547, -0.18109], [0.0625, -0.20196], [0.0703, -0.22220],
                     [0.1016, -0.29730], [0.1719, -0.38289], [0.2813, -0.27805], [0.4531, -0.10648],
                     [0.5000, -0.06080], [0.6172, 0.05702], [0.7344, 0.18719], [0.8516, 0.33304],
                     [0.9531, 0.46604], [0.9609, 0.51117], [0.9688, 0.57492], [0.9766, 0.65928],
                     [1.0000, 1.00000]],
      "v_horizontal": [[0.0000, 0.00000], [0.0625, 0.27485], [0.0703, 0.29012], [0.0781, 0.30353],
                       [0.0938, 0.32627], [0.1563, 0.37095], [0.2266, 0.33075], [0.2344, 0.32235],
                       [0.5000, 0.02526], [0.8047, -0.31966], [0.8594, -0.42665], [0.9063, -0.51550],
                       [0.9453, -0.39188], [0.9531, -0.33714], [0.9609, -0.27669], [0.9688, -0.21388],
                       [1.0000, 0.00000]]
    }
  }
}
```

- [ ] **Step 3.2: Write the failing tests**

`tests/test_ghia_problem.py`:
```python
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from raft import schema

PROBLEM = Path(__file__).resolve().parents[1] / "studies" / "ghia-1982" / "problem"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"ghia_{name}", PROBLEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


setup_mod = _load("setup")
measure_mod = _load("measure")
REF = {"citation": "t", "doi": "t", "tolerance": 0.01,
       "cases": {"100": {"u_vertical": [[0, 0], [0.25, 0.25], [1, 1]],
                         "v_horizontal": [[0, 0], [0.5, 0.5], [1, 1]]}}}


def linear_fields(s, dv=0.0):
    y, x = np.meshgrid(s.nodes(), s.nodes(), indexing="ij")
    return {"u": y.copy(), "v": x + dv}


def test_reference_file_matches_schema_and_shape():
    ref = schema.load("reference", PROBLEM / "reference.json")
    for case in ref["cases"].values():
        for key, end in (("u_vertical", 1.0), ("v_horizontal", 0.0)):
            pts = np.array(case[key])
            assert pts.shape == (17, 2)
            assert np.all(np.diff(pts[:, 0]) > 0)
            assert pts[0, 1] == 0.0 and pts[-1, 1] == end


def test_make_setup_and_expand():
    s = setup_mod.make_setup({"re": 100, "grid": 33})
    assert s.h == pytest.approx(1 / 32) and s.nu == pytest.approx(0.01)
    assert setup_mod.expand({"re": 100}) == [{"re": 100, "grid": 33}, {"re": 100, "grid": 65}, {"re": 100, "grid": 129}]
    assert setup_mod.expand({"re": 1000, "grid": 65}) == [{"re": 1000, "grid": 65}]


@pytest.mark.parametrize("params", [{"re": 100, "grid": 64}, {"re": -1, "grid": 33}, {"re": 100, "grid": 33, "mach": 1}])
def test_make_setup_rejects_bad_params(params):
    with pytest.raises(ValueError):
        setup_mod.make_setup(params)


def test_measure_exact_fields_have_zero_error():
    s = setup_mod.make_setup({"re": 100, "grid": 33})
    m = measure_mod.measure(s, linear_fields(s), REF)
    assert m["errors"] == pytest.approx({"u_max": 0, "u_rms": 0, "v_max": 0, "v_rms": 0}, abs=1e-12)
    assert m["pass"] is True and m["tolerance"] == 0.01
    assert len(m["samples"]["u_vertical"]) == 33
    assert m["reference_samples"]["v_horizontal"] == [[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]]
    json.dumps(m)  # plain Python types only


def test_measure_reports_offset():
    s = setup_mod.make_setup({"re": 100, "grid": 33})
    m = measure_mod.measure(s, linear_fields(s, dv=0.1), REF)
    assert m["errors"]["v_max"] == pytest.approx(0.1) and m["errors"]["v_rms"] == pytest.approx(0.1)
    assert m["pass"] is False


def test_streamfunction_of_uniform_u_is_y():
    s = setup_mod.make_setup({"re": 100, "grid": 9})
    psi = measure_mod.streamfunction(np.ones((9, 9)), s.h)
    assert psi[:, 4] == pytest.approx(s.nodes())


@pytest.mark.parametrize("fields, msg", [
    ({"u": np.zeros((33, 33))}, "keys"),
    ({"u": np.zeros((32, 33)), "v": np.zeros((33, 33))}, "shape"),
    ({"u": np.full((33, 33), np.nan), "v": np.zeros((33, 33))}, "non-finite"),
])
def test_measure_rejects_bad_fields(fields, msg):
    s = setup_mod.make_setup({"re": 100, "grid": 33})
    with pytest.raises(ValueError, match=msg):
        measure_mod.measure(s, fields, REF)


def test_measure_rejects_unknown_reynolds():
    s = setup_mod.make_setup({"re": 400, "grid": 33})
    with pytest.raises(ValueError, match="no reference data for Re = 400"):
        measure_mod.measure(s, linear_fields(s), REF)
```

- [ ] **Step 3.3: Run to verify failure**

Run: `uv run pytest tests/test_ghia_problem.py -q`
Expected: error, `setup.py` not found.

- [ ] **Step 3.4: Implement `setup.py` and `measure.py`**

`studies/ghia-1982/problem/setup.py`:
```python
"""Shared problem setup for Ghia, Ghia & Shin (1982): the lid-driven square cavity.

Read-only for implementers. Every method exposes ``solve(setup: CavitySetup) -> dict``
returning ``{"u": ndarray, "v": ndarray}``, each of shape ``(grid, grid)``, indexed
``[j, i]`` = value at ``(x_i, y_j)`` on the uniform node grid ``x_i = i * h``,
``y_j = j * h``, ``h = length / (grid - 1)``, walls included.

The lid is the top wall (y = length) moving in +x at ``lid_velocity``; the other three
walls are no-slip. Velocities are in units of the lid speed (lid_velocity = 1), so the
top row of u is 1 and every other wall value is 0. Kinematic viscosity is
``nu = lid_velocity * length / re``.
"""
import itertools
from dataclasses import dataclass

import numpy as np

REYNOLDS = (100, 1000)
GRIDS = (33, 65, 129)
RUN_MATRIX = {"re": [100], "grid": list(GRIDS)}
HEADLINE = {"re": 100, "grid": 129}
REPRO_RTOL = 1e-8
_KEYS = ("re", "grid")


@dataclass(frozen=True)
class CavitySetup:
    re: float
    grid: int
    lid_velocity: float = 1.0
    length: float = 1.0

    @property
    def h(self) -> float:
        return self.length / (self.grid - 1)

    @property
    def nu(self) -> float:
        return self.lid_velocity * self.length / self.re

    def nodes(self) -> np.ndarray:
        return np.linspace(0.0, self.length, self.grid)


def make_setup(params: dict) -> CavitySetup:
    unknown = set(params) - {*_KEYS, "seed"}
    if unknown:
        raise ValueError(f"unknown parameters {sorted(unknown)} for ghia-1982 (use --re and --grid)")
    re, grid = float(params["re"]), int(params["grid"])
    if re <= 0:
        raise ValueError(f"re must be positive, got {re:g}")
    if grid < 9 or grid % 2 == 0:
        raise ValueError(f"grid must be odd and at least 9 so the centrelines are grid lines, got {grid}")
    return CavitySetup(re=re, grid=grid)


def expand(params: dict) -> list[dict]:
    extra = {k: v for k, v in params.items() if k not in _KEYS}
    choices = [[params[k]] if k in params else RUN_MATRIX[k] for k in _KEYS]
    combos = [{**dict(zip(_KEYS, c)), **extra} for c in itertools.product(*choices)]
    for c in combos:
        make_setup(c)
    return combos
```

`studies/ghia-1982/problem/measure.py`:
```python
"""Shared measurement for ghia-1982. Read-only; methods never import or read it."""
import numpy as np
from scipy.interpolate import RegularGridInterpolator

COARSE = 33


def check_fields(setup, fields) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(fields, dict) or not {"u", "v"} <= set(fields):
        raise ValueError("solve() must return a dict with keys 'u' and 'v'")
    out = []
    for key in ("u", "v"):
        a = np.asarray(fields[key], dtype=float)
        if a.shape != (setup.grid, setup.grid):
            raise ValueError(f"{key} has shape {a.shape}, expected ({setup.grid}, {setup.grid})")
        if not np.all(np.isfinite(a)):
            raise ValueError(f"non-finite values in {key}")
        out.append(a)
    return out[0], out[1]


def streamfunction(u: np.ndarray, h: float) -> np.ndarray:
    """psi(x, y) = integral of u dy from the bottom wall (trapezoid rule); psi = 0 there."""
    psi = np.zeros_like(u)
    psi[1:] = np.cumsum(0.5 * (u[1:] + u[:-1]) * h, axis=0)
    return psi


def _pairs(xs, ys) -> list[list[float]]:
    return [[float(a), float(b)] for a, b in zip(xs, ys)]


def measure(setup, fields, reference: dict) -> dict:
    u, v = check_fields(setup, fields)
    key = f"{setup.re:g}"
    case = reference["cases"].get(key)
    if case is None:
        raise ValueError(f"no reference data for Re = {key} (have {sorted(reference['cases'])})")
    nodes = setup.nodes()
    mid_index, mid = (setup.grid - 1) // 2, 0.5 * setup.length
    ref_u = np.asarray(case["u_vertical"], dtype=float)
    ref_v = np.asarray(case["v_horizontal"], dtype=float)
    u_at = RegularGridInterpolator((nodes, nodes), u)(np.column_stack([ref_u[:, 0], np.full(len(ref_u), mid)]))
    v_at = RegularGridInterpolator((nodes, nodes), v)(np.column_stack([np.full(len(ref_v), mid), ref_v[:, 0]]))
    du, dv = u_at - ref_u[:, 1], v_at - ref_v[:, 1]
    errors = {
        "u_max": float(np.max(np.abs(du))), "u_rms": float(np.sqrt(np.mean(du**2))),
        "v_max": float(np.max(np.abs(dv))), "v_rms": float(np.sqrt(np.mean(dv**2))),
    }
    tolerance = float(reference["tolerance"])
    coarse = np.linspace(0.0, setup.length, COARSE)
    yy, xx = np.meshgrid(coarse, coarse, indexing="ij")
    psi = RegularGridInterpolator((nodes, nodes), streamfunction(u, setup.h))(
        np.column_stack([yy.ravel(), xx.ravel()])).reshape(COARSE, COARSE)
    return {
        "samples": {"u_vertical": _pairs(nodes, u[:, mid_index]), "v_horizontal": _pairs(nodes, v[mid_index, :])},
        "reference_samples": {"u_vertical": _pairs(ref_u[:, 0], ref_u[:, 1]),
                              "v_horizontal": _pairs(ref_v[:, 0], ref_v[:, 1])},
        "errors": errors,
        "tolerance": tolerance,
        "pass": bool(max(errors["u_max"], errors["v_max"]) <= tolerance),
        "fields_coarse": {"psi": np.round(psi, 6).tolist()},
    }
```

- [ ] **Step 3.5: Run to verify pass**

Run: `uv run pytest tests/test_ghia_problem.py -q`
Expected: all PASS.

- [ ] **Step 3.6: Commit**

```bash
git add studies/ghia-1982 tests/test_ghia_problem.py
git commit -m "Ghia 1982 study: shared cavity setup, reference tables (unverified), measurement"
```

---

### Task 4: Provenance and the yardstick guard

**Files:**
- Create: `raft/provenance.py`, `raft/guard.py`
- Test: `tests/test_provenance.py`, `tests/test_guard.py`

**Interfaces:**
- Produces:
  - `provenance.git_sha(root: Path) -> str` (`"unknown"` outside git)
  - `provenance.method_sha(root: Path, method_dir: Path) -> str | None`
  - `provenance.is_dirty(root: Path, paths: list[Path]) -> bool` (True when git is unavailable)
  - `provenance.inputs_hash(params: dict, problem_dir: Path) -> str` (64-hex)
  - `provenance.package_versions(names=("numpy", "scipy")) -> dict[str, str]`
  - `guard.scan_method(method_dir: Path) -> list[str]` (empty = clean)

- [ ] **Step 4.1: Write the failing tests**

`tests/test_provenance.py`:
```python
import subprocess

from raft import provenance


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def make_repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    m = tmp_path / "methods" / "a"
    m.mkdir(parents=True)
    (m / "solver.py").write_text("def solve(s):\n    return {}\n")
    (tmp_path / "other.txt").write_text("x")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    return m


def test_inputs_hash_tracks_params_and_files(tmp_path):
    p = tmp_path / "problem"
    p.mkdir()
    (p / "setup.py").write_text("A = 1\n")
    h1 = provenance.inputs_hash({"re": 100}, p)
    assert len(h1) == 64
    assert provenance.inputs_hash({"re": 100}, p) == h1
    assert provenance.inputs_hash({"re": 1000}, p) != h1
    (p / "__pycache__").mkdir()
    (p / "__pycache__" / "setup.cpython-312.pyc").write_bytes(b"junk")
    assert provenance.inputs_hash({"re": 100}, p) == h1
    (p / "setup.py").write_text("A = 2\n")
    assert provenance.inputs_hash({"re": 100}, p) != h1


def test_git_shas(tmp_path):
    m = make_repo(tmp_path)
    head = provenance.git_sha(tmp_path)
    assert len(head) == 40
    assert provenance.method_sha(tmp_path, m) == head
    (tmp_path / "other.txt").write_text("y")
    git(tmp_path, "commit", "-qam", "unrelated")
    assert provenance.git_sha(tmp_path) != head
    assert provenance.method_sha(tmp_path, m) == head


def test_dirty_detection(tmp_path):
    m = make_repo(tmp_path)
    assert provenance.is_dirty(tmp_path, [m]) is False
    (m / "solver.py").write_text("changed")
    assert provenance.is_dirty(tmp_path, [m]) is True


def test_outside_git(tmp_path):
    assert provenance.git_sha(tmp_path) == "unknown"
    assert provenance.method_sha(tmp_path, tmp_path) is None
    assert provenance.is_dirty(tmp_path, [tmp_path]) is True


def test_package_versions():
    v = provenance.package_versions()
    assert set(v) == {"numpy", "scipy"} and all(v.values())
```

`tests/test_guard.py`:
```python
from pathlib import Path

import pytest

from raft import guard

ROOT = Path(__file__).resolve().parents[1]
REAL_METHODS = sorted(p for p in ROOT.glob("studies/*/methods/*") if p.is_dir())


def write(tmp_path, code):
    (tmp_path / "solver.py").write_text(code)
    return tmp_path


def test_clean_method(tmp_path):
    assert guard.scan_method(write(tmp_path, '"""Uses the reference velocity of the lid."""\nimport numpy as np\n')) == []


@pytest.mark.parametrize("code, hit", [
    ('import json\nref = json.load(open("../../problem/reference.json"))\n', "reference.json"),
    ("from measure import measure\n", "measure"),
    ("import importlib\nm = importlib.import_module('measure')\n", "measure"),
    ('p = "problem/setup.py"\n', "problem/"),
    ('runs = "../runs/projection-grid33-re100"\n', "runs/"),
])
def test_forbidden(tmp_path, code, hit):
    found = guard.scan_method(write(tmp_path, code))
    assert found and hit in found[0]


def test_syntax_error_is_reported(tmp_path):
    assert "syntax error" in guard.scan_method(write(tmp_path, "def (:\n"))[0]


@pytest.mark.parametrize("method_dir", REAL_METHODS, ids=[p.name for p in REAL_METHODS])
def test_real_methods_are_clean(method_dir):
    assert guard.scan_method(method_dir) == []
```

- [ ] **Step 4.2: Run to verify failure**

Run: `uv run pytest tests/test_provenance.py tests/test_guard.py -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 4.3: Implement**

`raft/provenance.py`:
```python
"""Where a run came from: commits, dirty state, input hash, package versions."""
import hashlib
import json
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def git_sha(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD") or "unknown"


def _rel(root: Path, path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def method_sha(root: Path, method_dir: Path) -> str | None:
    return _git(root, "log", "-1", "--format=%H", "--", _rel(root, method_dir)) or None


def is_dirty(root: Path, paths: list[Path]) -> bool:
    out = _git(root, "status", "--porcelain", "--", *(_rel(root, p) for p in paths))
    return out is None or out != ""


def inputs_hash(params: dict, problem_dir: Path) -> str:
    h = hashlib.sha256(json.dumps(params, sort_keys=True).encode())
    for f in sorted(Path(problem_dir).rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
            h.update(str(f.relative_to(problem_dir)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def package_versions(names=("numpy", "scipy")) -> dict[str, str]:
    out = {}
    for n in names:
        try:
            out[n] = version(n)
        except PackageNotFoundError:
            out[n] = "not installed"
    return out
```

`raft/guard.py`:
```python
"""Static check that a method cannot see or touch the yardstick it is measured with.

Forbidden in a method folder's Python files (docstrings excepted): string literals that
mention the reference data, the measurement module, the shared problem folder, runs or
reviews; and importing anything named measure or reference. The runner adds a runtime
check (problem/ must be byte-identical after the run).
"""
import ast
from pathlib import Path

FORBIDDEN_TEXT = ("reference.json", "measure", "problem/", "problem\\", "runs/", "reviews/")
FORBIDDEN_MODULES = ("measure", "reference")


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def scan_method(method_dir: Path) -> list[str]:
    problems = []
    for f in sorted(Path(method_dir).rglob("*.py")):
        rel = f.relative_to(method_dir)
        try:
            tree = ast.parse(f.read_text(), filename=str(f))
        except SyntaxError as e:
            problems.append(f"{rel}:{e.lineno}: syntax error ({e.msg})")
            continue
        docs = _docstring_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                hit = next((t for t in FORBIDDEN_TEXT if t in node.value), None)
                if hit:
                    problems.append(f"{rel}:{node.lineno}: string mentions {hit!r}")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names]
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for name in names:
                    if any(part in FORBIDDEN_MODULES for part in name.split(".")):
                        problems.append(f"{rel}:{node.lineno}: imports {name!r}")
    return problems
```

- [ ] **Step 4.4: Run to verify pass**

Run: `uv run pytest tests/test_provenance.py tests/test_guard.py -q`
Expected: all PASS (`test_real_methods_are_clean` has no cases yet and reports as skipped/empty).

- [ ] **Step 4.5: Commit**

```bash
git add raft/provenance.py raft/guard.py tests/test_provenance.py tests/test_guard.py
git commit -m "Provenance helpers and static yardstick guard"
```

---

### Task 5: Runner (execute, write, repro)

**Files:**
- Create: `raft/runner.py`, `tests/conftest.py`
- Test: `tests/test_runner.py`, `tests/test_golden.py`

**Interfaces:**
- Consumes: `schema.check`, `provenance.*`, `guard.scan_method`, study contract from Task 3.
- Produces:
  - `runner.load_module(path: Path, name: str) -> module`
  - `runner.methods(study_dir: Path) -> list[str]`
  - `runner.expand(study_dir: Path, params: dict) -> list[dict]`
  - `runner.run_id(method: str, params: dict) -> str` (e.g. `projection-grid129-re100`)
  - `runner.execute(study_dir: Path, method: str, params: dict, timeout: float) -> tuple[dict, dict]` (manifest, results; writes nothing)
  - `runner.run_one(study_dir: Path, method: str, params: dict, timeout: float) -> tuple[dict, dict]` (execute + write to `runs/<run_id>/`)
  - `runner.summary(manifest: dict, results: dict) -> str`
  - `runner.repro(study_dir: Path, filters: dict, timeout: float) -> list[str]` (problems; empty = all reproduced)
  - Test fixture `tiny_study(tmp_path, git=False) -> Path` in `tests/conftest.py` (returns the study dir), plus `add_method(study_dir, name, code)` and `commit_all(root)`.

- [ ] **Step 5.1: Write the test fixture**

`tests/conftest.py`:
```python
"""A tiny, fast study used to test the generic machinery without any fluids."""
import json
import subprocess
from pathlib import Path

import pytest

SETUP = '''
from dataclasses import dataclass

HEADLINE = {"n": 8}


@dataclass(frozen=True)
class Setup:
    n: int


def make_setup(params):
    if int(params["n"]) < 2:
        raise ValueError("n must be at least 2")
    return Setup(n=int(params["n"]))


def expand(params):
    ns = [params["n"]] if "n" in params else [4, 8]
    out = [{"n": n} for n in ns]
    for c in out:
        make_setup(c)
    return out
'''

MEASURE = '''
import numpy as np


def measure(setup, fields, reference):
    y = np.asarray(fields["y"], dtype=float)
    if y.shape != (setup.n,):
        raise ValueError(f"y has shape {y.shape}, expected ({setup.n},)")
    if not np.all(np.isfinite(y)):
        raise ValueError("non-finite values in y")
    x = np.linspace(0, 1, setup.n)
    ref = x**2
    err = float(np.max(np.abs(y - ref)))
    pairs = lambda a, b: [[float(p), float(q)] for p, q in zip(a, b)]
    return {"samples": {"y": pairs(x, y)}, "reference_samples": {"y": pairs(x, ref)},
            "errors": {"y_max": err}, "tolerance": reference["tolerance"],
            "pass": bool(err <= reference["tolerance"])}
'''

EXACT = '''
import numpy as np


def solve(setup):
    x = np.linspace(0, 1, setup.n)
    return {"y": x**2}
'''


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def commit_all(root: Path, msg="commit"):
    git(root, "add", "-A")
    git(root, "commit", "-qm", msg)


def add_method(study_dir: Path, name: str, code: str, implements=("tiny-method",)):
    d = study_dir / "methods" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "solver.py").write_text(code)
    (d / "method.json").write_text(json.dumps(
        {"name": name, "implements": list(implements), "author_agent": f"test:implementer#{name}"}))
    return d


def make_tiny_study(root: Path, git_repo: bool = False) -> Path:
    (root / "pyproject.toml").write_text("[project]\nname = 'tiny'\n")
    (root / ".gitignore").write_text("__pycache__/\n")
    (root / "roles").mkdir()
    for role in ("extractor", "implementer", "reviewer"):
        (root / "roles" / f"{role}.md").write_text(f"# {role} for {{{{study}}}} {{{{method}}}} at {{{{study_dir}}}} pdf {{{{pdf}}}}\n")
    sd = root / "studies" / "tiny"
    (sd / "problem").mkdir(parents=True)
    (sd / "paper.yaml").write_text("title: Tiny\ncitation: Tiny test study\ndoi: 10.0000/tiny\npdf: papers/tiny.pdf\n")
    (sd / "problem" / "setup.py").write_text(SETUP)
    (sd / "problem" / "measure.py").write_text(MEASURE)
    (sd / "problem" / "reference.json").write_text(json.dumps(
        {"citation": "Tiny test study", "doi": "10.0000/tiny", "tolerance": 1e-9, "cases": {}}))
    (sd / "extraction.json").write_text(json.dumps({"study": "tiny", "items": [
        {"id": "tiny-method", "kind": "method", "text": "square x", "page": 1, "quote": "y = x^2", "missing": False}]}))
    add_method(sd, "exact", EXACT)
    if git_repo:
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "t@example.com")
        git(root, "config", "user.name", "t")
        commit_all(root, "tiny study")
    return sd


@pytest.fixture
def tiny_study(tmp_path):
    return make_tiny_study(tmp_path)


@pytest.fixture
def tiny_git_study(tmp_path):
    return make_tiny_study(tmp_path, git_repo=True)
```

- [ ] **Step 5.2: Write the failing runner tests**

`tests/test_runner.py`:
```python
import json

import pytest

from conftest import add_method, commit_all
from raft import runner, schema


def test_run_id():
    assert runner.run_id("projection", {"re": 100, "grid": 129}) == "projection-grid129-re100"


def test_methods_and_expand(tiny_study):
    add_method(tiny_study, "zzz", "def solve(s):\n    return {}\n")
    assert runner.methods(tiny_study) == ["exact", "zzz"]
    assert runner.expand(tiny_study, {}) == [{"n": 4}, {"n": 8}]


def test_run_one_writes_valid_files(tiny_git_study):
    manifest, results = runner.run_one(tiny_git_study, "exact", {"n": 8}, timeout=60)
    out = tiny_git_study / "runs" / "exact-n8"
    assert schema.load("manifest", out / "manifest.json") == manifest
    assert schema.load("results", out / "results.json") == results
    assert results["status"] == "ok" and results["pass"] is True
    assert manifest["dirty"] is False and manifest["method_sha"] == manifest["git_sha"]
    assert manifest["repro_rtol"] == 1e-8 and manifest["seed"] == 0


@pytest.mark.parametrize("name, code, reason", [
    ("broken", "def solve(s):\n    raise RuntimeError('boom')\n", "RuntimeError: boom"),
    ("nan", "import numpy as np\ndef solve(s):\n    return {'y': np.full(s.n, np.nan)}\n", "measure: non-finite values in y"),
    ("shape", "import numpy as np\ndef solve(s):\n    return {'y': np.zeros(s.n + 1)}\n", "measure: y has shape"),
    ("peeker", "import json\nREF = 'reference.json'\ndef solve(s):\n    return {}\n", "guard: solver.py:2: string mentions 'reference.json'"),
    ("tamper", "from pathlib import Path\ndef solve(s):\n    (Path(__file__).parents[2] / ('prob' + 'lem') / 'x.txt').write_text('x')\n"
               "    import numpy as np\n    return {'y': np.linspace(0, 1, s.n) ** 2}\n", "problem/ was modified during the run"),
])
def test_failures_are_written(tiny_study, name, code, reason):
    add_method(tiny_study, name, code)
    manifest, results = runner.run_one(tiny_study, name, {"n": 4}, timeout=60)
    assert results["status"] == "failed" and results["reason"].startswith(reason)
    saved = json.loads((tiny_study / "runs" / f"{name}-n4" / "results.json").read_text())
    assert saved["status"] == "failed"


def test_timeout(tiny_study):
    add_method(tiny_study, "slow", "import time\ndef solve(s):\n    time.sleep(30)\n")
    _, results = runner.run_one(tiny_study, "slow", {"n": 4}, timeout=1)
    assert results["reason"] == "timeout after 1s"


def test_unknown_method_is_a_clean_error(tiny_study):
    with pytest.raises(SystemExit, match="no method 'nope'"):
        runner.run_one(tiny_study, "nope", {"n": 4}, timeout=5)


def test_outside_git_is_dirty(tiny_study):
    manifest, _ = runner.run_one(tiny_study, "exact", {"n": 4}, timeout=60)
    assert manifest["git_sha"] == "unknown" and manifest["method_sha"] is None and manifest["dirty"] is True


def test_repro_passes_then_detects_changed_solver(tiny_git_study):
    runner.run_one(tiny_git_study, "exact", {"n": 4}, timeout=60)
    assert runner.repro(tiny_git_study, {}, timeout=60) == []
    solver = tiny_git_study / "methods" / "exact" / "solver.py"
    solver.write_text(solver.read_text().replace("x**2", "x**2 + 1e-3"))
    commit_all(tiny_git_study.parents[1], "change solver")
    problems = runner.repro(tiny_git_study, {}, timeout=60)
    assert any("solver changed since this run" in p for p in problems)
    assert any("results differ" in p for p in problems)


def test_repro_filters(tiny_git_study):
    runner.run_one(tiny_git_study, "exact", {"n": 4}, timeout=60)
    assert runner.repro(tiny_git_study, {"n": 99}, timeout=60) == ["no runs match the filter {'n': 99}"]
```

- [ ] **Step 5.3: Run to verify failure**

Run: `uv run pytest tests/test_runner.py -q`
Expected: FAIL with `ImportError: cannot import name 'runner'`.

- [ ] **Step 5.4: Implement `raft/runner.py`**

```python
"""Run a method on a study's shared problem in a child process and record everything."""
import importlib.util
import json
import multiprocessing as mp
import platform
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


def _setup_module(study_dir: Path, tag: str):
    return load_module(Path(study_dir) / "problem" / "setup.py", f"raft_setup_{tag}")


def methods(study_dir: Path) -> list[str]:
    base = Path(study_dir) / "methods"
    return sorted(d.name for d in base.iterdir() if (d / "solver.py").is_file()) if base.is_dir() else []


def expand(study_dir: Path, params: dict) -> list[dict]:
    return _setup_module(study_dir, "expand").expand(params)


def run_id(method: str, params: dict) -> str:
    return method + "-" + "-".join(f"{k}{params[k]}" for k in sorted(params))


def _child(study_dir: str, method: str, params: dict):
    sd = Path(study_dir)
    setup = _setup_module(sd, "child").make_setup(params)
    solver = load_module(sd / "methods" / method / "solver.py", f"raft_method_{method.replace('-', '_')}")
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


def execute(study_dir: Path, method: str, params: dict, timeout: float) -> tuple[dict, dict]:
    sd = Path(study_dir).resolve()
    root = sd.parents[1]
    method_dir, problem = sd / "methods" / method, sd / "problem"
    if not (method_dir / "solver.py").is_file():
        raise SystemExit(f"raft: no method {method!r} in {sd / 'methods'} (have: {', '.join(methods(sd)) or 'none'})")
    rid = run_id(method, params)
    before = provenance.inputs_hash(params, problem)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.monotonic()
    fields, reason = None, None
    violations = guard.scan_method(method_dir)
    if violations:
        reason = "guard: " + "; ".join(violations)
    else:
        with mp.get_context("spawn").Pool(1) as pool:
            job = pool.apply_async(_child, (str(sd), method, params))
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
        measure_mod = load_module(problem / "measure.py", "raft_measure")
        reference = json.loads((problem / "reference.json").read_text())
        try:
            measured = measure_mod.measure(setup_mod.make_setup(params), fields, reference)
            results = {"run_id": rid, "status": "ok", **measured}
        except ValueError as e:
            results["reason"] = f"measure: {e}"
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
    return manifest, results


def run_one(study_dir: Path, method: str, params: dict, timeout: float) -> tuple[dict, dict]:
    manifest, results = execute(study_dir, method, params, timeout)
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
```

Note for `_same`: the "results differ" message must contain "results differ" (asserted in the test).

- [ ] **Step 5.5: Write the golden test (runs every real Ghia method on a coarse grid)**

`tests/test_golden.py`:
```python
from pathlib import Path

import pytest

from raft import runner

STUDY = Path(__file__).resolve().parents[1] / "studies" / "ghia-1982"
METHODS = runner.methods(STUDY)


@pytest.mark.parametrize("method", METHODS)
def test_golden_coarse_grid(method):
    _, results = runner.execute(STUDY, method, {"re": 100, "grid": 33}, timeout=600)
    assert results["status"] == "ok", results.get("reason")
    assert max(results["errors"]["u_max"], results["errors"]["v_max"]) <= 0.05
```

- [ ] **Step 5.6: Run to verify pass**

Run: `uv run pytest tests/test_runner.py tests/test_golden.py -q`
Expected: runner tests PASS; golden has no cases yet.

- [ ] **Step 5.7: Commit**

```bash
git add raft/runner.py tests/conftest.py tests/test_runner.py tests/test_golden.py
git commit -m "Runner: guarded child-process execution, manifests, results, repro"
```

---

### Task 6: Roles, briefs, validation and the `raft` CLI

**Files:**
- Create: `roles/extractor.md`, `roles/implementer.md`, `roles/reviewer.md`, `raft/briefs.py`, `raft/validate.py`, `raft/cli.py`
- Test: `tests/test_validate.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `paths`, `schema`, `runner` (Tasks 1, 5); `compare.build/write_site/repo_url` (Task 10). Until Task 10 exists, the `compare` branch imports lazily (see code).
- Produces: `briefs.render(root: Path, role: str, study: str, method: str = "") -> str`; `validate.extraction(study_dir: Path) -> list[str]`; `validate.methods_and_reviews(study_dir: Path) -> list[str]`; `cli.main(argv: list[str] | None = None) -> int`.

- [ ] **Step 6.1: Write the role prompts**

`roles/extractor.md`:
```markdown
# Role: extractor for {{study}}

You turn a paper into `{{study_dir}}/extraction.json`, the list every implementer and reviewer works from. You do not write solver code.

**Input:** the PDF at `{{pdf}}`. It is gitignored. If it is missing, stop and say so. Also read `{{study_dir}}/paper.yaml` and `{{study_dir}}/problem/setup.py` to see which experiment is being reproduced.

**Write one item per implementable fact:**
- `method`: a numerical method or algorithm the paper uses
- `equation`: governing equations, discretisations, boundary formulas
- `parameter`: Reynolds numbers, grid sizes, tolerances, relaxation factors
- `boundary_condition`
- `result`: a table or figure we compare against

Each item has `id` (kebab-case, stable), `kind`, `text` (your plain statement), `page` (the journal's printed page number), `quote` (a short verbatim excerpt, 30 words at most) and `missing: false`.

**Gaps:** when an implementer would need a detail the paper does not give (convergence tolerance, initial condition, corner treatment, time step, multigrid cycle settings), add an item with `missing: true`, the page where the detail belongs, `quote: ""`, and an `assumption` giving the default you recommend and why. Never fill a gap silently inside `text`.

**Reference check:** compare `{{study_dir}}/problem/reference.json` with the paper's tables number by number. Fill in the `page_u` / `page_v` fields and set `verified_against_pdf: true` only if every number matches. List every mismatch in your final message, and do not change any reference value without listing it.

Set `extractor_agent` to an identifier of yourself (`tool:role`, e.g. `claude-code:raft-extractor`).

**Done when** `uv run raft extract --validate --study {{study}}` passes.
```

`roles/implementer.md`:
```markdown
# Role: implementer of {{method}} for {{study}}

You write one independent implementation. Other agents implement different methods in parallel. You will not see their code and must not look for it.

**Read:** `{{study_dir}}/extraction.json`, and `{{study_dir}}/problem/setup.py` (its docstring defines the interface you must satisfy), plus the method notes in the task that dispatched you.

**Write only inside `{{study_dir}}/methods/{{method}}/`:**
- `solver.py`, exposing `solve(setup) -> {"u": ndarray, "v": ndarray}` exactly as setup.py describes
- `method.json`: `{"name": "{{method}}", "implements": [extraction ids you implemented], "author_agent": "<tool:role#{{method}}>", "notes": "<every choice the paper does not dictate, citing extraction ids>"}`

**Rules** (a guard test enforces 1–3):
1. Never read, import or mention the shared measurement module, the reference data, `runs/` or `reviews/`.
2. Never write outside your folder.
3. Use numpy and scipy only.
4. Be deterministic: no randomness. Stop on a convergence criterion plus an iteration cap, and raise `RuntimeError("did not converge …")` at the cap.
5. Record every assumption in `notes`, especially for extraction items marked `missing`.
6. Do not tune against the reference. Check your work with physics instead: wall values, a divergence-free field, grid convergence across 33, 65 and 129.

**Finish:**
1. Run `uv run pytest tests/test_guard.py -q`.
2. Commit your folder.
3. Run `uv run raft run {{method}} --study {{study}} --re 100` and commit `{{study_dir}}/runs/{{method}}-*`.
4. Report the errors per grid in your final message. If a run is over tolerance or failed, say so plainly; a failed reproduction is still a result.
```

`roles/reviewer.md`:
```markdown
# Role: reviewer of {{method}} for {{study}}

You check one implementation against the paper. You did not write it, and you do not fix it.

**Read:** `{{study_dir}}/methods/{{method}}/solver.py`, its `method.json`, `{{study_dir}}/extraction.json`, `{{study_dir}}/problem/setup.py`, and the PDF at `{{pdf}}` wherever an extraction item is unclear.

**For each extraction id in `implements`:** find the code that implements it and check it against the paper: equations, signs, boundary formulas, parameters. Also check that:
- the interface in setup.py is honoured ([j, i] indexing, walls included, lid-speed units)
- there are no unexplained tuning constants
- every assumption for a `missing` item is stated in `notes`

**Write `{{study_dir}}/reviews/{{method}}.json`:**
`{"method": "{{method}}", "reviewed_sha": "<output of: git log -1 --format=%H -- {{study_dir}}/methods/{{method}}>", "reviewer_agent": "<tool:role#{{method}}>", "verdict": "verified" | "discrepancies" | "unverified", "summary": "…", "discrepancies": [{"file": "solver.py", "line": N, "extraction_id": "…", "page": N, "description": "…", "severity": "minor" | "major" | "blocking"}]}`

**Verdicts:**
- `verified`: every implemented item matches; only minor discrepancies remain.
- `discrepancies`: at least one major or blocking discrepancy.
- `unverified`: you could not check it; say why in `summary`.

Check the method folder has no uncommitted changes before you take the sha. Commit the review file.

**Done when** `uv run raft review --validate --study {{study}}` passes.
```

- [ ] **Step 6.2: Write the failing tests**

`tests/test_validate.py`:
```python
import json

from raft import validate


def test_tiny_extraction_valid(tiny_study):
    assert validate.extraction(tiny_study) == []


def test_duplicate_ids(tiny_study):
    p = tiny_study / "extraction.json"
    data = json.loads(p.read_text())
    data["items"].append(dict(data["items"][0]))
    p.write_text(json.dumps(data))
    assert validate.extraction(tiny_study) == ["extraction.json: duplicate id 'tiny-method'"]


def test_missing_extraction(tiny_study):
    (tiny_study / "extraction.json").unlink()
    assert "file not found" in validate.extraction(tiny_study)[0]


def test_method_cites_unknown_id(tiny_study):
    p = tiny_study / "methods" / "exact" / "method.json"
    m = json.loads(p.read_text())
    m["implements"] = ["nope"]
    p.write_text(json.dumps(m))
    assert validate.methods_and_reviews(tiny_study) == ["methods/exact/method.json: implements unknown extraction id 'nope'"]


def test_review_by_implementer_rejected(tiny_study):
    (tiny_study / "reviews").mkdir()
    (tiny_study / "reviews" / "exact.json").write_text(json.dumps({
        "method": "exact", "reviewed_sha": "a" * 40, "reviewer_agent": "test:implementer#exact",
        "verdict": "verified", "discrepancies": []}))
    assert validate.methods_and_reviews(tiny_study) == ["reviews/exact.json: reviewer is the method's implementer"]


def test_review_for_unknown_method(tiny_study):
    (tiny_study / "reviews").mkdir()
    (tiny_study / "reviews" / "ghost.json").write_text(json.dumps({
        "method": "ghost", "reviewed_sha": "a" * 40, "reviewer_agent": "r",
        "verdict": "unverified", "discrepancies": []}))
    assert validate.methods_and_reviews(tiny_study) == ["reviews/ghost.json: no method named 'ghost'"]
```

`tests/test_cli.py`:
```python
import pytest

from raft import cli


@pytest.fixture
def in_tiny(tiny_git_study, monkeypatch):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    return tiny_git_study


def test_brief_renders(in_tiny, capsys):
    assert cli.main(["implement", "exact"]) == 0
    assert capsys.readouterr().out.strip() == "# implementer for tiny exact at studies/tiny pdf papers/tiny.pdf"


def test_validate_commands(in_tiny, capsys):
    assert cli.main(["extract", "--validate"]) == 0
    assert cli.main(["review", "--validate"]) == 0
    assert "✓" in capsys.readouterr().out


def test_run_and_repro(in_tiny, capsys):
    assert cli.main(["run", "--all", "--n", "4"]) == 0
    assert "✓ exact n=4: pass" in capsys.readouterr().out
    assert (in_tiny / "runs" / "exact-n4" / "results.json").is_file()
    assert cli.main(["repro"]) == 0


@pytest.mark.parametrize("argv, msg", [
    (["run", "nope", "--n", "4"], "no method 'nope'"),
    (["run", "exact", "--n", "1"], "n must be at least 2"),
    (["run", "--study", "ghost", "exact"], "unknown study 'ghost'"),
    (["run", "exact", "--n"], "--n needs a value"),
])
def test_cli_errors(in_tiny, argv, msg):
    with pytest.raises(SystemExit, match=msg):
        cli.main(argv)


def test_outside_checkout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    with pytest.raises(SystemExit, match="inside a Paper Raft checkout"):
        cli.main(["review", "--validate"])


def test_run_needs_method_or_all(in_tiny):
    with pytest.raises(SystemExit):
        cli.main(["run"])
```

- [ ] **Step 6.3: Run to verify failure**

Run: `uv run pytest tests/test_validate.py tests/test_cli.py -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 6.4: Implement**

`raft/briefs.py`:
```python
"""Render a role prompt for a study (and method) so any agent tool can follow it."""
from pathlib import Path

import yaml


def render(root: Path, role: str, study: str, method: str = "") -> str:
    path = root / "roles" / f"{role}.md"
    if not path.is_file():
        raise SystemExit(f"raft: no role prompt at {path}")
    paper = yaml.safe_load((root / "studies" / study / "paper.yaml").read_text()) or {}
    values = {"study": study, "method": method, "study_dir": f"studies/{study}", "pdf": paper.get("pdf", "")}
    text = path.read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text
```

`raft/validate.py`:
```python
"""Cross-file checks the JSON Schemas cannot express."""
from pathlib import Path

from . import schema


def _ids(study_dir: Path) -> set[str]:
    try:
        return {i["id"] for i in schema.load("extraction", study_dir / "extraction.json")["items"]}
    except schema.ContractError:
        return set()


def extraction(study_dir: Path) -> list[str]:
    try:
        data = schema.load("extraction", study_dir / "extraction.json")
    except schema.ContractError as e:
        return [str(e)]
    seen, problems = set(), []
    for item in data["items"]:
        if item["id"] in seen:
            problems.append(f"extraction.json: duplicate id {item['id']!r}")
        seen.add(item["id"])
    return problems


def methods_and_reviews(study_dir: Path) -> list[str]:
    ids, problems, authors = _ids(study_dir), [], {}
    for d in sorted(p for p in (study_dir / "methods").glob("*") if p.is_dir()):
        rel = f"methods/{d.name}/method.json"
        try:
            m = schema.load("method", d / "method.json")
        except schema.ContractError as e:
            problems.append(str(e))
            continue
        if m["name"] != d.name:
            problems.append(f"{rel}: name {m['name']!r} does not match folder {d.name!r}")
        problems += [f"{rel}: implements unknown extraction id {i!r}" for i in m["implements"] if i not in ids]
        authors[d.name] = m["author_agent"]
    for f in sorted((study_dir / "reviews").glob("*.json")):
        rel = f"reviews/{f.name}"
        try:
            r = schema.load("review", f)
        except schema.ContractError as e:
            problems.append(str(e))
            continue
        if r["method"] not in authors:
            problems.append(f"{rel}: no method named {r['method']!r}")
            continue
        if r["reviewer_agent"] == authors[r["method"]]:
            problems.append(f"{rel}: reviewer is the method's implementer")
        problems += [f"{rel}: discrepancy cites unknown extraction id {d['extraction_id']!r}"
                     for d in r["discrepancies"] if d["extraction_id"] not in ids]
    return problems
```

`raft/cli.py`:
```python
"""raft: extract | implement | run | review | repro | compare."""
import argparse
import sys
from pathlib import Path

from . import briefs, paths, runner, validate


def _value(text: str):
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def _params(rest: list[str]) -> dict:
    params, i = {}, 0
    while i < len(rest):
        tok = rest[i]
        if not tok.startswith("--") or tok == "--":
            raise SystemExit(f"raft: unexpected argument {tok!r}")
        key = tok[2:]
        if "=" in key:
            key, val = key.split("=", 1)
            i += 1
        elif i + 1 < len(rest) and not rest[i + 1].startswith("--"):
            val = rest[i + 1]
            i += 2
        else:
            raise SystemExit(f"raft: --{key} needs a value")
        params[key.replace("-", "_")] = _value(val)
    return params


# Options raft itself understands; every other --key [value] is a study parameter.
KNOWN = {"--all", "--timeout", "--study", "--validate", "--out", "--help", "-h"}


def _split(argv: list[str]) -> tuple[list[str], list[str]]:
    """Pull study parameters out before argparse, so `run --all --re 100` never reads 100 as a method."""
    keep, extra, i = [], [], 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--") and tok != "--" and tok.split("=", 1)[0] not in KNOWN:
            extra.append(tok)
            if "=" not in tok and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                extra.append(argv[i + 1])
                i += 1
        else:
            keep.append(tok)
        i += 1
    return keep, extra


def _report(problems: list[str], ok: str) -> int:
    if problems:
        print("\n".join(f"✗ {p}" for p in problems))
        return 1
    print(f"✓ {ok}")
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--study", help="study folder under studies/ (default: the only one)")
    p = argparse.ArgumentParser(prog="raft", description="Reproduce research papers with agents, in a controlled environment.")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", parents=[common], help="print the extractor brief, or --validate extraction.json")
    e.add_argument("--validate", action="store_true")
    im = sub.add_parser("implement", parents=[common], help="print the implementer brief for one method")
    im.add_argument("method")
    r = sub.add_parser("run", parents=[common], help="run methods; extra --key value pairs are study parameters")
    r.add_argument("method", nargs="?")
    r.add_argument("--all", action="store_true")
    r.add_argument("--timeout", type=float, default=1800.0)
    rv = sub.add_parser("review", parents=[common], help="print the reviewer brief, or --validate methods and reviews")
    rv.add_argument("method", nargs="?")
    rv.add_argument("--validate", action="store_true")
    rp = sub.add_parser("repro", parents=[common], help="rerun committed runs; extra --key value pairs filter them")
    rp.add_argument("--timeout", type=float, default=1800.0)
    c = sub.add_parser("compare", help="score every run and build the static site")
    c.add_argument("--out", default="site")
    keep, rest = _split(sys.argv[1:] if argv is None else argv)
    args = p.parse_args(keep)
    if rest and args.cmd not in ("run", "repro"):
        p.error(f"unrecognized arguments: {' '.join(rest)}")
    root = paths.repo_root()

    if args.cmd == "compare":
        from . import compare
        out = Path(args.out) if Path(args.out).is_absolute() else root / args.out
        compare.write_site(compare.build(root, compare.repo_url(root)), out)
        print(f"✓ site written to {out}. Open {out / 'index.html'}")
        return 0

    study = paths.resolve_study(root, args.study)
    sd = root / "studies" / study
    if args.cmd == "extract":
        if args.validate:
            return _report(validate.extraction(sd), f"{study}/extraction.json is valid")
        print(briefs.render(root, "extractor", study))
        return 0
    if args.cmd == "implement":
        print(briefs.render(root, "implementer", study, args.method))
        return 0
    if args.cmd == "review":
        if args.validate:
            return _report(validate.methods_and_reviews(sd), f"{study}: method.json files and reviews are valid")
        if not args.method:
            p.error("review needs a method name, or --validate")
        print(briefs.render(root, "reviewer", study, args.method))
        return 0

    params = _params(rest)
    if args.cmd == "repro":
        return _report(runner.repro(sd, params, args.timeout), "every matching run reproduced")
    if args.all == bool(args.method):
        p.error("give one method name or --all")
    names = runner.methods(sd) if args.all else [args.method]
    if not names:
        raise SystemExit(f"raft: no methods in {sd / 'methods'} yet")
    try:
        combos = runner.expand(sd, params)
    except ValueError as e:
        raise SystemExit(f"raft: {e}") from None
    for name in names:
        for combo in combos:
            print(runner.summary(*runner.run_one(sd, name, combo, args.timeout)), flush=True)
    return 0
```

Note: `p.error` raises `SystemExit(2)`, which satisfies `test_run_needs_method_or_all`. For `["run", "exact", "--n", "1"]`, `expand` raises `ValueError("n must be at least 2")`, which becomes `SystemExit("raft: n must be at least 2")`.

- [ ] **Step 6.5: Run to verify pass**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6.6: Smoke-check the real CLI**

Run: `uv run raft implement projection`
Expected: the implementer brief with `studies/ghia-1982` substituted.
Run: `uv run raft run projection --re 100`
Expected: `raft: no method 'projection' in …/methods (have: none)`, exit 1.

- [ ] **Step 6.7: Commit**

```bash
git add roles raft/briefs.py raft/validate.py raft/cli.py tests/test_validate.py tests/test_cli.py
git commit -m "Role prompts, briefs, cross-file validation and the raft CLI"
```

---

### Task 7: Extraction of Ghia 1982 (extractor agent)

**Files:**
- Create: `studies/ghia-1982/extraction.json`
- Modify: `studies/ghia-1982/problem/reference.json` (page fields, `verified_against_pdf`, and any corrected values)

**Interfaces:**
- Consumes: `raft extract` brief and validator (Task 6).
- Produces: extraction ids that Tasks 8a–8c cite in `method.json`. The extractor chooses the ids. At minimum, the file must contain items for: the vorticity transport equation, the streamfunction Poisson equation, the velocity–streamfunction relations, the wall-vorticity boundary formula, the lid/no-slip conditions, Re = 100 and 1000, the 129×129 grid, Tables I and II, and `missing` items for convergence tolerance, initial condition, time-stepping/relaxation, and the multigrid configuration.

- [ ] **Step 7.1: Check the PDF is present**

Run: `test -f papers/ghia-1982.pdf && echo present || echo MISSING`
If MISSING: stop and ask the owner to place the paper at `papers/ghia-1982.pdf` (it's paywalled at Elsevier; the file stays local and gitignored). Do not continue without it.

- [ ] **Step 7.2: Dispatch the extractor agent**

Get the brief with `uv run raft extract`, and dispatch one agent (Claude Code: the `raft-extractor` agent from Task 11, or a general-purpose agent given the brief verbatim) with the brief as its prompt.

- [ ] **Step 7.3: Validate**

Run: `uv run raft extract --validate`
Expected: `✓ ghia-1982/extraction.json is valid`.

- [ ] **Step 7.4: Spot-check (controller, not the extractor)**

Open the PDF and pick three items at random, plus every `missing` item. Confirm each page number and quote. Confirm `reference.json` now has `verified_against_pdf: true` and integer `page_u`/`page_v` for both cases, and read every value change the extractor reported. If values changed, rerun `uv run pytest tests/test_ghia_problem.py -q` (expect PASS).

- [ ] **Step 7.5: Commit**

```bash
git add studies/ghia-1982/extraction.json studies/ghia-1982/problem/reference.json
git commit -m "Ghia 1982 extraction with page references; reference tables checked against the PDF"
```

---

### Tasks 8a, 8b, 8c: Three independent implementations (implementer agents, in parallel)

The solver code is **deliberately not written in this plan**. Paper Raft exists so that independent agents implement from the paper and the extraction. Pre-writing the code here would break that independence. Each task gives the agent the brief, a method sheet (below) and fixed acceptance checks. Dispatch the three tasks at the same time, each in its own git worktree (`isolation: "worktree"`), then merge them one at a time (they touch disjoint folders).

**Shared for all three:**

**Files:** Create `studies/ghia-1982/methods/<name>/solver.py`, `studies/ghia-1982/methods/<name>/method.json`, `studies/ghia-1982/runs/<name>-grid{33,65,129}-re100/`.

**Interfaces:**
- Consumes: `CavitySetup` (`re`, `grid`, `lid_velocity`, `length`, `h`, `nu`, `nodes()`), extraction ids (Task 7).
- Produces: `solve(setup) -> {"u": ndarray (grid, grid), "v": ndarray (grid, grid)}`, indexed `[j, i]`, walls included, top row of u = 1, all other wall values 0.

**Steps for each:**
- [ ] **Step 8.1:** Get the brief: `uv run raft implement <name>`. Dispatch an implementer agent with that brief plus the method sheet below.
- [ ] **Step 8.2 (agent):** Write `solver.py` and `method.json`, then run `uv run pytest tests/test_guard.py -q`. Expected: PASS.
- [ ] **Step 8.3 (agent):** Run `uv run pytest "tests/test_golden.py::test_golden_coarse_grid[<name>]" -q`. Expected: PASS, i.e. 33×33 max error ≤ 0.05. If it fails, debug with physics checks, not by fitting the reference.
- [ ] **Step 8.4 (agent):** Commit the method folder: `git add studies/ghia-1982/methods/<name> && git commit -m "<name> solver for Ghia 1982"`.
- [ ] **Step 8.5 (agent):** Run `uv run raft run <name> --re 100`. Expected: three lines, one per grid. Then commit: `git add studies/ghia-1982/runs/<name>-* && git commit -m "<name>: Re=100 runs on 33, 65, 129"`.
- [ ] **Step 8.6 (controller):** Check that the manifests have `"dirty": false` and a non-null `method_sha`. Merge the worktree branch.

#### Task 8a: `streamfunction-vorticity` (the paper's formulation)

**Method sheet:**
- **Unknowns:** ψ and ω on all `grid × grid` nodes, where u = ∂ψ/∂y and v = −∂ψ/∂x, with ∇²ψ = −ω and ∂ω/∂t + u ∂ω/∂x + v ∂ω/∂y = ν ∇²ω.
- **Walls:** ψ = 0 on all walls. Thom's formula for wall vorticity: ω_wall = −2 ψ_adjacent / h², and on the lid ω = −2 ψ_{below} / h² − 2 U / h. Use the formula the extraction gives if it differs, and cite its id.
- **Discretisation:** second-order central differences. Ghia used an implicit multigrid solver. A pseudo-time march to steady state is an acceptable substitute, but it must be recorded in `notes` against the extraction's multigrid `missing` item.
- **Poisson solve:** build the 5-point Laplacian for interior nodes with `scipy.sparse` and factorise it once with `scipy.sparse.linalg.splu`.
- **Time step:** explicit Euler with dt = 0.5 · min(h² / (4ν), h / U). If coarse grids wiggle (cell Reynolds number U·h/ν > 2), switch convection to second-order upwind and record that.
- **Convergence:** max|ω^{n+1} − ω^n| / (dt · max(1, max|ω|)) < 1e-7. Cap at 2·10⁶ steps.
- **Output:** u and v from central differences of ψ in the interior. Set the walls exactly: u = 1 on the top row (corners included), 0 elsewhere.

#### Task 8b: `projection` (fractional step, primitive variables)

**Method sheet:**
- **Grid:** staggered MAC grid with N = grid − 1 cells per side. u sits on vertical faces, v on horizontal faces, p at cell centres.
- **Walls:** no-slip through ghost values. The tangential ghost is set so the wall average equals the wall velocity; the lid ghost is u_ghost = 2U − u_inside.
- **Step:** advection–diffusion with explicit Euler (or AB2; record which), then solve the pressure Poisson equation with Neumann walls. Pin one cell (p = 0 in cell [0, 0]) to remove the null space, and prefactorise the matrix with `splu`. Then project the velocity.
- **Time step:** dt = 0.5 · min(h² / (4ν), h / U).
- **Convergence:** max change in u and v per unit time below 1e-7. Cap at 2·10⁶ steps.
- **Output:** interpolate u and v to the nodes `[j, i]` by averaging adjacent faces, then set the walls exactly (top row u = 1, others 0).
- **Extraction mapping:** this method does not use Ghia's formulation, so `implements` lists the governing equations, boundary conditions and parameters it shares with the paper. The formulation difference goes in `notes`.

#### Task 8c: `lattice-boltzmann` (D2Q9 BGK)

**Method sheet:**
- **Lattice:** D2Q9 with standard weights, N = grid − 1 fluid cells per side, and cell centres at ((i + ½)/N, (j + ½)/N).
- **Units:** lattice lid speed U_lb = 0.1, so ν_lb = U_lb · N / Re and τ = 3 ν_lb + ½.
- **Walls:** halfway bounce-back on all walls, with the moving-wall momentum correction on the lid (Ladd).
- **Initial state:** ρ = 1, u = 0, equilibrium populations.
- **Convergence:** check every 1000 steps; stop when max|Δu| / U_lb < 1e-7 over 1000 steps. Cap at 2·10⁶ steps.
- **Output:** velocities divided by U_lb. Interpolate from cell centres to the node grid with bilinear interpolation (`scipy.interpolate.RegularGridInterpolator`, nearest-cell extrapolation at the outer half-cell), then set the walls exactly.
- **Notes:** record the compressibility error (Ma ≈ 0.17) as an assumption.

---

### Task 9: Reviews (reviewer agents, cross-assigned)

**Files:**
- Create: `studies/ghia-1982/reviews/{streamfunction-vorticity,projection,lattice-boltzmann}.json`
- Possibly modify: method folders (fix pass), runs (rerun after fixes)

**Interfaces:**
- Consumes: methods + runs from Tasks 8a–8c; review brief and validator (Task 6).
- Produces: reviews whose `reviewed_sha` matches each run's `method_sha`.

- [ ] **Step 9.1:** For each method, get `uv run raft review <name>` and dispatch a **fresh** reviewer agent, never the agent that implemented it. Set the `reviewer_agent` ids so they differ from the `author_agent` in `method.json`. The three reviews can run in parallel; each writes only its own review file.
- [ ] **Step 9.2:** Run `uv run raft review --validate`. Expected: `✓ ghia-1982: method.json files and reviews are valid`.
- [ ] **Step 9.3: Fix loop.** For any `major` or `blocking` discrepancy, dispatch a fresh implementer agent with the brief plus the review file. It fixes the solver, commits, and reruns `uv run raft run <name> --re 100`, then commits the runs. Then dispatch a fresh reviewer (Step 9.1) on the new commit. Stop after two rounds per method. Whatever remains stays recorded as `discrepancies`; failures are results.
- [ ] **Step 9.4:** Check the v1 success bar: at least one method has `pass: true` on `grid129-re100` with a matching `verified` review. Check it with:
  `uv run python -c "from raft import compare, paths; d = compare.build(paths.repo_root(), None); print({m['name']: m['headline_status'] for m in d['studies'][0]['methods']})"` (once Task 10 exists; until then, read the files by hand).
  If no method is verified after the fix rounds, stop and report to the owner with the errors and the review summaries. Do not lower the tolerance.
- [ ] **Step 9.5:** Commit:
```bash
git add studies/ghia-1982/reviews studies/ghia-1982/methods studies/ghia-1982/runs
git commit -m "Independent reviews of the three Ghia implementations"
```

---

### Task 10: Compare and the static site

**Files:**
- Create: `raft/compare.py`, `raft/site_template/__init__.py` (empty), `raft/site_template/index.html`, `raft/site_template/app.js`, `raft/site_template/style.css`
- Test: `tests/test_compare.py`

**Interfaces:**
- Consumes: `schema.load`, `status.derive_status`, `runner.methods`, `runner.load_module`.
- Produces: `compare.build(root: Path, repo_url: str | None) -> dict`, `compare.write_site(data: dict, out_dir: Path) -> None`, `compare.repo_url(root: Path) -> str | None`. Each method in the data has `name`, `method`, `review`, `runs[]` (`run_id`, `params`, `manifest`, `results`, `status`, `code_url`) and `headline_status`. Each study has `id`, `paper`, `extraction`, `reference`, `headline`, `methods`, `counts`.

- [ ] **Step 10.1: Write the failing tests**

`tests/test_compare.py`:
```python
import json

from conftest import commit_all
from raft import compare, runner


def _review(sd, sha, verdict="verified"):
    (sd / "reviews").mkdir(exist_ok=True)
    (sd / "reviews" / "exact.json").write_text(json.dumps({
        "method": "exact", "reviewed_sha": sha, "reviewer_agent": "test:reviewer#exact",
        "verdict": verdict, "discrepancies": []}))


def test_build_structure_and_verified(tiny_git_study):
    root = tiny_git_study.parents[1]
    manifest, _ = runner.run_one(tiny_git_study, "exact", {"n": 8}, timeout=60)
    _review(tiny_git_study, manifest["method_sha"])
    data = compare.build(root, "https://github.com/acme/raft")
    s = data["studies"][0]
    assert s["id"] == "tiny" and s["headline"] == {"n": 8}
    m = s["methods"][0]
    assert m["name"] == "exact" and m["headline_status"] == "verified"
    assert s["counts"] == {"verified": 1}
    run = m["runs"][0]
    assert run["code_url"] == f"https://github.com/acme/raft/blob/{manifest['git_sha']}/studies/tiny/methods/exact/solver.py"


def test_compare_status_follows_review_commit(tiny_git_study):
    root = tiny_git_study.parents[1]
    manifest, _ = runner.run_one(tiny_git_study, "exact", {"n": 8}, timeout=60)
    _review(tiny_git_study, manifest["method_sha"])
    solver = tiny_git_study / "methods" / "exact" / "solver.py"
    solver.write_text(solver.read_text() + "\n# tweak\n")
    commit_all(root, "edit solver after review")
    runner.run_one(tiny_git_study, "exact", {"n": 8}, timeout=60)
    m = compare.build(root, None)["studies"][0]["methods"][0]
    assert m["headline_status"] == "unverified"
    assert m["runs"][0]["code_url"] is None


def test_no_runs(tiny_study):
    s = compare.build(tiny_study.parents[1], None)["studies"][0]
    assert s["methods"][0]["runs"] == [] and s["methods"][0]["headline_status"] == "no run"


def test_write_site_files(tiny_study, tmp_path):
    out = tmp_path / "site"
    compare.write_site(compare.build(tiny_study.parents[1], None), out)
    assert {p.name for p in out.iterdir()} >= {"index.html", "app.js", "style.css", "data.json", "data.js"}
    assert (out / "data.js").read_text().startswith("window.RAFT_DATA = ")
    html = (out / "index.html").read_text()
    assert 'src="data.js"' in html and "fetch(" not in (out / "app.js").read_text()


def test_repo_url_normalises(monkeypatch, tmp_path):
    monkeypatch.setenv("RAFT_REPO_URL", "git@github.com:lusknchars/paper-raft.git")
    assert compare.repo_url(tmp_path) == "https://github.com/lusknchars/paper-raft"
```

- [ ] **Step 10.2: Run to verify failure**

Run: `uv run pytest tests/test_compare.py -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 10.3: Implement `raft/compare.py`**

```python
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

from . import runner, schema
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
    for sd in sorted(p for p in (root / "studies").iterdir() if (p / "paper.yaml").is_file()):
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
        })
    return data


def write_site(data: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    template = files("raft.site_template")
    for name in SITE_FILES:
        with template.joinpath(name).open("rb") as src, open(out_dir / name, "wb") as dst:
            shutil.copyfileobj(src, dst)
    (out_dir / "data.json").write_text(json.dumps(data, indent=1) + "\n")
    (out_dir / "data.js").write_text("window.RAFT_DATA = " + json.dumps(data) + ";\n")
```

Note: `test_compare_status_follows_review_commit` expects `code_url is None`. That's because `repo` is `None` in that call, not because of the edit. The status assertion is the point of that test.

- [ ] **Step 10.4: Write the site template**

`raft/site_template/index.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Paper Raft</title>
  <link rel="stylesheet" href="style.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
  <script src="data.js"></script>
</head>
<body>
  <header>
    <a class="brand" href="#">PAPER RAFT</a>
    <p class="sub">Agents reproduce research papers. Every number links to its code, its run and its page in the paper.</p>
  </header>
  <main id="app"></main>
  <aside id="drawer" hidden>
    <button id="drawer-close" aria-label="Close provenance">×</button>
    <div id="drawer-body"></div>
  </aside>
  <script src="app.js"></script>
</body>
</html>
```

`raft/site_template/style.css`:
```css
:root {
  --bg: #0b0c0e; --panel: #131519; --line: #24272d; --text: #e6e6e6; --muted: #8b9099;
  --accent: #7aa2ff; --ok: #7ee0a1; --warn: #ffb86b; --bad: #ff7a90;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.5 ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
header, main { max-width: 1100px; margin: 0 auto; padding: 16px; }
header { border-bottom: 1px solid var(--line); }
.brand { color: var(--text); text-decoration: none; font-weight: 700; letter-spacing: 0.12em; }
.sub, .muted { color: var(--muted); }
a { color: var(--accent); }
h2 { font-size: 18px; margin: 16px 0 4px; } h3 { font-size: 15px; margin: 24px 0 8px; }
.card { display: block; background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  padding: 16px; margin: 12px 0; color: var(--text); text-decoration: none; }
.card:hover, .card:focus-visible { border-color: var(--accent); }
.count { margin-right: 16px; }
.badge { display: inline-block; padding: 0 6px; border-radius: 4px; border: 1px solid currentColor; font-size: 12px; }
.badge.verified { color: var(--ok); } .badge.unverified { color: var(--warn); }
.badge.failed { color: var(--bad); } .badge.no-run, .badge.missing { color: var(--muted); }
.controls { display: flex; flex-wrap: wrap; gap: 16px; margin: 16px 0; }
select, button { font: inherit; color: var(--text); background: var(--panel); border: 1px solid var(--line);
  border-radius: 4px; padding: 4px 8px; min-height: 32px; }
button { cursor: pointer; } button:hover { border-color: var(--accent); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
figure { margin: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px; }
figcaption { color: var(--muted); margin-bottom: 8px; }
.table-wrap { overflow-x: auto; margin-top: 16px; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.wrap { white-space: normal; }
.maps { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
canvas.heat { width: 100%; aspect-ratio: 1; image-rendering: pixelated; display: block; }
#drawer { position: fixed; inset: 0 0 0 auto; width: min(560px, 100vw); background: var(--panel);
  border-left: 1px solid var(--line); padding: 16px; overflow-y: auto; }
#drawer-close { float: right; }
pre { white-space: pre-wrap; word-break: break-all; background: var(--bg); padding: 8px; border-radius: 4px; }
.warn { color: var(--warn); }
```

`raft/site_template/app.js`:
```js
const D = window.RAFT_DATA;
const app = document.getElementById("app");
const drawer = document.getElementById("drawer");
const COLORS = ["#7aa2ff", "#ffb86b", "#7ee0a1", "#ff7a90", "#c792ea", "#5fd7d7"];
const AXIS = { ticks: { color: "#8b9099" }, grid: { color: "#24272d" } };
let charts = [];

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) n.append(kid.nodeType ? kid : String(kid));
  return n;
}
const fmt = (x) => (x == null ? "—" : x !== 0 && Math.abs(x) < 1e-3 ? x.toExponential(2) : x.toFixed(4));
const badge = (s) => el("span", { class: "badge " + s.replace(" ", "-") }, s);
const same = (a, b) => String(a) === String(b);

function clear() { charts.forEach((c) => c.destroy()); charts = []; }

function route() {
  clear();
  app.replaceChildren();
  if (!D) { app.append(el("p", {}, "No data.js found. Run `uv run raft compare` first.")); return; }
  const [view, id, sub] = location.hash.slice(1).split("/");
  const study = D.studies.find((s) => s.id === id);
  if (view === "study" && study) (sub === "extraction" ? extractionView : compareView)(study);
  else overview();
}

function overview() {
  if (!D.studies.length) { app.append(el("p", {}, "No studies yet.")); return; }
  for (const s of D.studies) {
    app.append(el("a", { class: "card", href: `#study/${s.id}` },
      el("h2", {}, s.paper.title || s.id),
      el("p", { class: "muted" }, s.reference.citation),
      el("p", {}, ["verified", "unverified", "failed", "no run"].map((k) =>
        el("span", { class: "count" }, badge(k), " ", s.counts[k] || 0)))));
  }
}

function paramValues(study) {
  const values = {};
  for (const m of study.methods) for (const r of m.runs) for (const [k, v] of Object.entries(r.params)) {
    (values[k] ||= new Set()).add(v);
  }
  return Object.fromEntries(Object.entries(values).map(([k, s]) => [k, [...s].sort((a, b) => a - b)]));
}

function studyNav(study) {
  return [
    el("nav", {}, el("a", { href: "#" }, "← all studies"), " · ",
      el("a", { href: `#study/${study.id}` }, "results"), " · ",
      el("a", { href: `#study/${study.id}/extraction` }, "extraction")),
    el("h2", {}, study.paper.title || study.id),
    el("p", { class: "muted" }, study.reference.citation, " · ",
      el("a", { href: `https://doi.org/${study.reference.doi}`, target: "_blank", rel: "noopener" }, "DOI")),
  ];
}

function compareView(study) {
  const values = paramValues(study);
  const sel = {};
  for (const [k, vs] of Object.entries(values)) sel[k] = k in study.headline ? study.headline[k] : vs[0];
  const controls = el("div", { class: "controls" });
  const body = el("div");
  app.append(...studyNav(study), controls, body);
  for (const [k, vs] of Object.entries(values)) {
    const s = el("select", { "aria-label": k, onchange: (e) => { sel[k] = e.target.value; render(); } },
      vs.map((v) => { const o = el("option", { value: v }, v); o.selected = same(v, sel[k]); return o; }));
    controls.append(el("label", {}, k, " ", s));
  }

  function render() {
    clear();
    body.replaceChildren();
    const rows = study.methods.map((m) => ({ m, run: m.runs.find((r) => Object.keys(sel).every((k) => same(r.params[k], sel[k]))) }));
    if (!rows.some((r) => r.run)) { body.append(el("p", {}, "No runs for this combination.")); return; }
    const ok = rows.filter((r) => r.run && r.run.results.status === "ok");

    const grid = el("div", { class: "charts" });
    body.append(grid);
    for (const key of ok.length ? Object.keys(ok[0].run.results.samples) : []) {
      const canvas = el("canvas", { role: "img", "aria-label": `${key} by method against the paper` });
      grid.append(el("figure", {}, el("figcaption", {}, key), canvas));
      const datasets = ok.map((r, i) => ({
        label: r.m.name, data: r.run.results.samples[key].map(([x, y]) => ({ x, y })),
        borderColor: COLORS[i % COLORS.length], backgroundColor: COLORS[i % COLORS.length],
        showLine: true, pointRadius: 0, borderWidth: 1.5,
      }));
      const ref = ok[0].run.results.reference_samples?.[key];
      if (ref) datasets.push({ label: "paper", data: ref.map(([x, y]) => ({ x, y })), borderColor: "#e6e6e6",
        backgroundColor: "#e6e6e6", showLine: false, pointRadius: 4, pointStyle: "crossRot" });
      charts.push(new Chart(canvas, { type: "scatter", data: { datasets },
        options: { animation: false, scales: { x: AXIS, y: AXIS }, plugins: { legend: { labels: { color: "#e6e6e6" } } } } }));
    }

    const errKeys = ok.length ? Object.keys(ok[0].run.results.errors) : [];
    const tbody = el("tbody", {}, rows.map(({ m, run }) => {
      if (!run) return el("tr", {}, el("td", {}, m.name), el("td", { colspan: errKeys.length + 3, class: "muted" }, "no run"));
      const r = run.results;
      return el("tr", {}, el("td", {}, m.name),
        errKeys.map((k) => el("td", { class: "num" }, fmt(r.errors?.[k]))),
        el("td", {}, r.status === "ok" ? (r.pass ? "yes" : "no") : "—"),
        el("td", { class: "wrap" }, badge(run.status), r.reason ? " " + r.reason : ""),
        el("td", {}, el("button", { onclick: () => openDrawer(study, m, run) }, "provenance")));
    }));
    const tol = ok[0]?.run.results.tolerance;
    body.append(el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "method"), errKeys.map((k) => el("th", {}, k)),
        el("th", {}, tol != null ? `≤ ${tol}` : "pass"), el("th", {}, "status"), el("th", {}, ""))), tbody)));

    const withFields = ok.filter((r) => r.run.results.fields_coarse);
    for (const field of withFields.length ? Object.keys(withFields[0].run.results.fields_coarse) : []) {
      const base = el("select", { "aria-label": `${field} baseline` }, el("option", { value: "" }, "none"),
        withFields.map((r) => el("option", { value: r.m.name }, r.m.name)));
      const maps = el("div", { class: "maps" });
      const draw = () => {
        maps.replaceChildren();
        const b = withFields.find((r) => r.m.name === base.value);
        for (const r of withFields) {
          const f = r.run.results.fields_coarse[field];
          const diff = b && b !== r;
          const g = diff ? f.map((row, j) => row.map((v, i) => v - b.run.results.fields_coarse[field][j][i])) : f;
          maps.append(el("figure", {}, heatmap(g, `${r.m.name} ${field}`), el("figcaption", {}, diff ? `${r.m.name} − ${b.m.name}` : `${r.m.name} ${field}`)));
        }
      };
      base.addEventListener("change", draw);
      body.append(el("h3", {}, field), el("label", {}, "difference from ", base), maps);
      draw();
    }
  }
  render();
}

function heatmap(f, label) {
  const n = f.length, m = f[0].length;
  const c = el("canvas", { width: m, height: n, class: "heat", role: "img", "aria-label": label });
  const ctx = c.getContext("2d");
  const img = ctx.createImageData(m, n);
  const max = Math.max(1e-12, ...f.flat().map(Math.abs));
  for (let j = 0; j < n; j++) for (let i = 0; i < m; i++) {
    const t = f[j][i] / max, k = ((n - 1 - j) * m + i) * 4;
    const [r, g, b] = t >= 0 ? [255, 170, 80] : [90, 140, 255];
    const a = Math.abs(t);
    img.data[k] = 20 + (r - 20) * a; img.data[k + 1] = 20 + (g - 20) * a; img.data[k + 2] = 24 + (b - 24) * a; img.data[k + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

function openDrawer(study, m, run) {
  const body = document.getElementById("drawer-body");
  const items = new Map((study.extraction?.items || []).map((i) => [i.id, i]));
  const rv = m.review, man = run.manifest;
  body.replaceChildren(
    el("h3", {}, `${m.name} · ${run.run_id}`), badge(run.status),
    run.code_url ? el("p", {}, el("a", { href: run.code_url, target: "_blank", rel: "noopener" }, "solver code at this commit ↗"))
      : el("p", { class: "muted" }, "No code link (no remote, or the run was dirty)."),
    el("h4", {}, "Paper pages behind it"),
    el("ul", {}, (m.method?.implements || []).map((id) => {
      const it = items.get(id);
      return el("li", {}, it ? `p. ${it.page}: ${it.text}` : `${id} (not in extraction)`, " ",
        it?.missing ? el("span", { class: "badge missing" }, "missing in paper") : null);
    })),
    el("h4", {}, "Review"),
    rv ? el("div", {},
      el("p", {}, `${rv.verdict} by ${rv.reviewer_agent} at ${rv.reviewed_sha.slice(0, 10)}`),
      rv.summary ? el("p", {}, rv.summary) : null,
      rv.reviewed_sha !== man.method_sha ? el("p", { class: "warn" }, "This review is for a different solver commit than this run.") : null,
      el("ul", {}, rv.discrepancies.map((d) => el("li", {}, `[${d.severity}] ${d.file}:${d.line} vs p. ${d.page} (${d.extraction_id}): ${d.description}`))))
      : el("p", { class: "muted" }, "Not reviewed yet."),
    el("h4", {}, "Manifest"), el("pre", {}, JSON.stringify(man, null, 2)));
  drawer.hidden = false;
  document.getElementById("drawer-close").focus();
}

function extractionView(study) {
  app.append(...studyNav(study));
  const items = study.extraction?.items;
  if (!items) { app.append(el("p", {}, "No extraction yet.")); return; }
  app.append(el("div", { class: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ["id", "kind", "page", "statement", "quote / assumption"].map((h) => el("th", {}, h)))),
    el("tbody", {}, items.map((i) => el("tr", {}, el("td", {}, i.id), el("td", {}, i.kind), el("td", { class: "num" }, i.page),
      el("td", { class: "wrap" }, i.text),
      el("td", { class: "wrap" }, i.missing ? [el("span", { class: "badge missing" }, "missing in paper"), " ", i.assumption] : `“${i.quote}”`)))))));
}

document.getElementById("drawer-close").addEventListener("click", () => { drawer.hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") drawer.hidden = true; });
window.addEventListener("hashchange", route);
route();
```

- [ ] **Step 10.5: Run to verify pass**

Run: `uv run pytest tests/test_compare.py -q`
Expected: all PASS.

- [ ] **Step 10.6: Build the real site**

Run: `uv run raft compare`
Expected: `✓ site written to …/site. Open …/site/index.html`.

- [ ] **Step 10.7: Manual check in a browser**

Open `site/index.html` straight from disk (`file://`) and check:
- the overview card shows the counts
- the comparison view draws two centreline charts, with Ghia's points as crosses
- the grid selector switches runs
- the error table shows the `≤ 0.01` header and status badges
- the streamfunction maps render, and choosing a baseline shows differences
- the provenance drawer shows pages, the review and the manifest, and closes on Escape
- the extraction view lists the items, with "missing in paper" badges
- at 390 px width there is no horizontal page scroll (the table scrolls inside its wrapper)

Take a screenshot and save it to `docs/screenshots/site-comparison.png`.

- [ ] **Step 10.8: Commit**

```bash
git add raft/compare.py raft/site_template tests/test_compare.py docs/screenshots/site-comparison.png
git commit -m "raft compare: site data with derived status and a static results explorer"
```

---

### Task 11: Claude Code adapter

**Files:**
- Create: `adapters/claude-code/.claude/agents/raft-extractor.md`, `.../raft-implementer.md`, `.../raft-reviewer.md`, `adapters/claude-code/.claude/skills/reproduce-paper/SKILL.md`, symlink `.claude -> adapters/claude-code/.claude`
- Test: `tests/test_adapter.py`

**Interfaces:**
- Consumes: CLI commands from Task 6 (`raft extract`, `raft implement <m>`, `raft review <m>`, `--validate`, `raft run`, `raft compare`).
- Produces: agents named `raft-extractor`, `raft-implementer`, `raft-reviewer` and a skill named `reproduce-paper`.

- [ ] **Step 11.1: Write the failing test**

`tests/test_adapter.py`:
```python
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "adapters" / "claude-code" / ".claude" / "agents"
EXPECT = {"raft-extractor": "raft extract", "raft-implementer": "raft implement", "raft-reviewer": "raft review"}


def frontmatter(path):
    text = path.read_text()
    assert text.startswith("---\n"), path
    head = text.split("---\n")[1]
    return dict(line.split(": ", 1) for line in head.strip().splitlines()), text


@pytest.mark.parametrize("name, command", EXPECT.items())
def test_agent_files(name, command):
    meta, text = frontmatter(AGENTS / f"{name}.md")
    assert meta["name"] == name and meta["description"]
    assert command in text


def test_skill_mentions_every_stage():
    meta, text = frontmatter(ROOT / "adapters" / "claude-code" / ".claude" / "skills" / "reproduce-paper" / "SKILL.md")
    assert meta["name"] == "reproduce-paper"
    for cmd in ("raft extract", "raft implement", "raft run", "raft review", "raft compare"):
        assert cmd in text


def test_repo_symlink():
    link = ROOT / ".claude"
    assert link.is_symlink() and link.resolve() == (ROOT / "adapters" / "claude-code" / ".claude").resolve()
```

- [ ] **Step 11.2: Run to verify failure**

Run: `uv run pytest tests/test_adapter.py -q`
Expected: FAIL, files not found.

- [ ] **Step 11.3: Write the adapter files**

`adapters/claude-code/.claude/agents/raft-extractor.md`:
```markdown
---
name: raft-extractor
description: Turns a Paper Raft study's PDF into extraction.json with page references and flagged gaps. Use once per study before any implementation.
tools: Read, Write, Edit, Bash, Grep, Glob
---
Run `uv run raft extract --study <study>` and follow the brief it prints exactly. When you finish, `uv run raft extract --validate --study <study>` must pass. Report every reference-data mismatch you found.
```

`adapters/claude-code/.claude/agents/raft-implementer.md`:
```markdown
---
name: raft-implementer
description: Implements one method of a Paper Raft study inside methods/<name>/ only, from extraction.json and the shared setup. Dispatch one per method, in parallel worktrees.
tools: Read, Write, Edit, Bash, Grep, Glob
---
Run `uv run raft implement <method> --study <study>` and follow the brief it prints exactly. Never open the shared measurement module, the reference data, runs/ or reviews/. Report the per-grid errors honestly, failures included.
```

`adapters/claude-code/.claude/agents/raft-reviewer.md`:
```markdown
---
name: raft-reviewer
description: Reviews one Paper Raft implementation against the paper and writes reviews/<method>.json. Never dispatch the agent that implemented the method.
tools: Read, Write, Bash, Grep, Glob
---
Run `uv run raft review <method> --study <study>` and follow the brief it prints exactly. You do not edit solver code. When you finish, `uv run raft review --validate --study <study>` must pass.
```

`adapters/claude-code/.claude/skills/reproduce-paper/SKILL.md`:
```markdown
---
name: reproduce-paper
description: Run the Paper Raft loop for one study (extract, implement in parallel, run, review, compare). Use when asked to reproduce a paper or add a method to a study.
---
# Reproduce a paper with Paper Raft

1. **Extract** (once per study): the PDF must be at the path in `studies/<study>/paper.yaml`. Dispatch `raft-extractor`. Gate: `uv run raft extract --validate --study <study>`.
2. **Implement:** for each method, dispatch `raft-implementer` with `isolation: "worktree"`, all in one message so they run in parallel. Include the method notes from the user or the plan. Each agent reads its brief from `uv run raft implement <method>`. Merge the branches one at a time; they touch disjoint folders.
3. **Run:** each implementer commits its runs, made with `uv run raft run <method> --study <study> --re 100`. For a full refresh, run `uv run raft run --all --study <study>`.
4. **Review:** for each method, dispatch a fresh `raft-reviewer`, never the implementer. Gate: `uv run raft review --validate --study <study>`. For major or blocking discrepancies, send a fresh implementer the review file, rerun, then re-review. Stop after two rounds and keep what remains recorded.
5. **Compare:** run `uv run raft compare` and open `site/index.html`.

Never lower a study's tolerance to make a method pass. A failed reproduction is a result: commit it.
```

Run: `cd ~/paper-raft && ln -s adapters/claude-code/.claude .claude`

- [ ] **Step 11.4: Run to verify pass**

Run: `uv run pytest tests/test_adapter.py -q`
Expected: 5 passed.

- [ ] **Step 11.5: Commit**

```bash
git add adapters .claude tests/test_adapter.py
git commit -m "Claude Code adapter: extractor, implementer, reviewer agents and reproduce-paper skill"
```

Note on ordering: Task 11 has no dependency on Tasks 7–9 and should run **before** Task 7, so that the extractor, implementers and reviewers can be dispatched as these named agents. Execution order: 1 → 2 → 3 → 4 → 5 → 6 → 11 → 7 → 8a/8b/8c → 9 → 10 → 12 → 12b → 13 → 14.

---

### Task 12: CI and Pages workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `uv run pytest`, `raft extract --validate`, `raft review --validate`, `raft repro --re 100`, `raft compare`.

- [ ] **Step 12.1: Write the workflow**

`.github/workflows/ci.yml`:
```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # method_sha needs full history
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --locked
      - run: uv run pytest -q
      - run: uv run raft extract --validate
      - run: uv run raft review --validate
      - run: uv run raft repro --re 100
      - run: uv run raft compare
        env:
          RAFT_REPO_URL: https://github.com/${{ github.repository }}
      - uses: actions/upload-pages-artifact@v3
        if: github.ref == 'refs/heads/main'
        with:
          path: site
  deploy:
    if: github.ref == 'refs/heads/main'
    needs: check
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - id: deploy
        uses: actions/deploy-pages@v4
```

- [ ] **Step 12.2: Run the same gate locally**

Run: `uv sync --locked && uv run pytest -q && uv run raft extract --validate && uv run raft review --validate && uv run raft repro --re 100 && uv run raft compare`
Expected: every step exits 0. Each run printed by `repro` shows `✓`.

- [ ] **Step 12.3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "CI: tests, contract validation, reproduction of committed runs, Pages deploy"
```

Cross-platform note: committed runs are produced on macOS, and CI reruns them on Linux. If `repro` fails **only** on CI with "results differ beyond rtol 1e-8", look at the size of the difference. If it is floating-point drift (≤ 1e-6 relative), set `REPRO_RTOL = 1e-6` in `studies/ghia-1982/problem/setup.py`, regenerate the runs (`uv run raft run --all --re 100`), add a line to spec §5 step 3 saying why, and tell the owner. Never raise it to hide a real change.

---

### Task 12b: Every study, one command (`raft new`, `--all-studies`)

Added 2026-10-12 at the owner's request ("rerun with infrastructure that can create and test in all the papers that we collected"). It supersedes spec §9's exclusion of a study template generator.

**Files:**
- Create: `raft/scaffold.py`
- Modify: `raft/paths.py` (draft-aware `studies`), `raft/cli.py` (full replacement below), `raft/compare.py` (iterate `paths.studies`), `.github/workflows/ci.yml` (all studies)
- Test: `tests/test_multi_study.py`

**Interfaces:**
- Consumes: everything from Tasks 1–12.
- Produces:
  - `paths.studies(root: Path, include_drafts: bool = False) -> list[str]`; a study is a draft when its `paper.yaml` has `draft: true`
  - `paths.resolve_study(...)` accepts drafts when named explicitly
  - `scaffold.new_study(root: Path, study_id: str, title: str, doi: str) -> Path`
  - CLI `raft new <id> --title T --doi D`, plus `--all-studies` on `extract --validate`, `review --validate`, `run --all` and `repro`

- [ ] **Step 12b.1: Write the failing tests**

`tests/test_multi_study.py`:
```python
import shutil

import pytest
import yaml

from conftest import make_tiny_study
from raft import cli, compare, paths


@pytest.fixture
def two_studies(tmp_path, monkeypatch):
    sd = make_tiny_study(tmp_path)
    shutil.copytree(sd, sd.parent / "tiny2")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    return tmp_path


def test_new_study_scaffold(two_studies):
    assert cli.main(["new", "smith-2020", "--title", "A paper", "--doi", "10.1/x"]) == 0
    d = two_studies / "studies" / "smith-2020"
    assert {p.name for p in (d / "problem").iterdir()} == {"setup.py", "measure.py", "reference.json"}
    paper = yaml.safe_load((d / "paper.yaml").read_text())
    assert paper["draft"] is True and paper["pdf"] == "papers/smith-2020.pdf" and paper["doi"] == "10.1/x"
    assert "smith-2020" not in paths.studies(two_studies)
    assert paths.resolve_study(two_studies, "smith-2020") == "smith-2020"


@pytest.mark.parametrize("sid, msg", [("tiny", "already exists"), ("Bad_Id", "lowercase")])
def test_new_study_rejects(two_studies, sid, msg):
    with pytest.raises(SystemExit, match=msg):
        cli.main(["new", sid, "--title", "t", "--doi", "d"])


def test_all_studies_validate_and_run(two_studies, capsys):
    assert cli.main(["extract", "--validate", "--all-studies"]) == 0
    assert cli.main(["run", "--all", "--all-studies", "--n", "4"]) == 0
    out = capsys.readouterr().out
    assert "── tiny\n" in out and "── tiny2\n" in out
    assert (two_studies / "studies" / "tiny2" / "runs" / "exact-n4").is_dir()


def test_all_studies_reports_bad_params_per_study(two_studies, capsys):
    assert cli.main(["run", "--all", "--all-studies", "--n", "1"]) == 1
    out = capsys.readouterr().out
    assert "✗ tiny: n must be at least 2" in out and "✗ tiny2: n must be at least 2" in out


def test_all_studies_skips_drafts(two_studies, capsys):
    cli.main(["new", "draft-one", "--title", "t", "--doi", "d"])
    capsys.readouterr()
    assert cli.main(["review", "--validate", "--all-studies"]) == 0
    assert "draft-one" not in capsys.readouterr().out
    assert [s["id"] for s in compare.build(two_studies, None)["studies"]] == ["tiny", "tiny2"]


@pytest.mark.parametrize("argv", [["implement", "exact", "--all-studies"], ["run", "exact", "--all-studies"],
                                  ["review", "--validate", "--all-studies", "--study", "tiny"]])
def test_all_studies_rejects_single_study_commands(two_studies, argv):
    with pytest.raises(SystemExit):
        cli.main(argv)


def test_two_studies_need_a_choice(two_studies):
    with pytest.raises(SystemExit, match="pass --study"):
        cli.main(["review", "--validate"])
```

- [ ] **Step 12b.2: Run to verify failure**

Run: `uv run pytest tests/test_multi_study.py -q`
Expected: FAIL (`raft new` is unknown, and there's no `--all-studies`).

- [ ] **Step 12b.3: Implement**

`raft/paths.py`: replace `studies` and `resolve_study` with:
```python
def _is_draft(paper: Path) -> bool:
    return bool((yaml.safe_load(paper.read_text()) or {}).get("draft"))


def studies(root: Path, include_drafts: bool = False) -> list[str]:
    base = root / "studies"
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir()
                  if (d / "paper.yaml").is_file() and (include_drafts or not _is_draft(d / "paper.yaml")))


def resolve_study(root: Path, name: str | None) -> str:
    if name:
        have = studies(root, include_drafts=True)
        if name not in have:
            raise SystemExit(f"raft: unknown study {name!r} (have: {', '.join(have) or 'none'})")
        return name
    have = studies(root)
    if len(have) == 1:
        return have[0]
    raise SystemExit(f"raft: pass --study or --all-studies (have: {', '.join(have) or 'none'})")
```
and add `import yaml` at the top.

`raft/scaffold.py`:
```python
"""Start a new study folder. It stays a draft (skipped by --all-studies and the site) until filled in."""
import json
import re
from pathlib import Path

import yaml

SETUP = '''"""Shared problem setup for {study_id}. Read-only for implementers.

Describe here, precisely, what solve(setup) receives and what it must return.
"""
RUN_MATRIX = {{}}
HEADLINE = {{}}


def make_setup(params: dict):
    raise NotImplementedError("define the experiment's parameters in studies/{study_id}/problem/setup.py")


def expand(params: dict) -> list[dict]:
    raise NotImplementedError("list the runs to make in studies/{study_id}/problem/setup.py")
'''

MEASURE = '''"""Shared measurement for {study_id}. Read-only; methods never import or read it."""


def measure(setup, fields, reference: dict) -> dict:
    raise NotImplementedError("compare fields with reference.json in studies/{study_id}/problem/measure.py")
'''


def new_study(root: Path, study_id: str, title: str, doi: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", study_id):
        raise SystemExit(f"raft: study id must be lowercase letters, digits and hyphens, got {study_id!r}")
    d = root / "studies" / study_id
    if d.exists():
        raise SystemExit(f"raft: study {study_id!r} already exists at {d}")
    (d / "problem").mkdir(parents=True)
    paper = {"title": title, "authors": [], "citation": "", "doi": doi,
             "pdf": f"papers/{study_id}.pdf", "experiment": "", "draft": True}
    (d / "paper.yaml").write_text(yaml.safe_dump(paper, sort_keys=False, allow_unicode=True))
    (d / "problem" / "setup.py").write_text(SETUP.format(study_id=study_id))
    (d / "problem" / "measure.py").write_text(MEASURE.format(study_id=study_id))
    (d / "problem" / "reference.json").write_text(json.dumps(
        {"citation": title, "doi": doi, "tolerance": 0.01, "cases": {}}, indent=2) + "\n")
    return d
```

`raft/compare.py`: in `build`, replace the loop header
`for sd in sorted(p for p in (root / "studies").iterdir() if (p / "paper.yaml").is_file()):`
with `for sd in (root / "studies" / s for s in paths.studies(root)):`, and change the import line to `from . import paths, runner, schema`.

`raft/cli.py`: full replacement. `_value`, `_split`, `_params` and `_report` keep their Task 6 bodies; only `KNOWN` changes.
```python
"""raft: new | extract | implement | run | review | repro | compare."""
import argparse
import sys
from pathlib import Path

from . import briefs, paths, runner, scaffold, validate

# Options raft itself understands; every other --key [value] is a study parameter.
KNOWN = {"--all", "--all-studies", "--timeout", "--study", "--validate", "--out", "--title", "--doi", "--help", "-h"}

# _value, _split, _params, _report: unchanged from Task 6.


def _study_cmd(p, args, root: Path, study: str, params: dict) -> int:
    sd = root / "studies" / study
    if args.cmd == "extract":
        if args.validate:
            return _report(validate.extraction(sd), f"{study}/extraction.json is valid")
        print(briefs.render(root, "extractor", study))
        return 0
    if args.cmd == "implement":
        print(briefs.render(root, "implementer", study, args.method))
        return 0
    if args.cmd == "review":
        if args.validate:
            return _report(validate.methods_and_reviews(sd), f"{study}: method.json files and reviews are valid")
        if not args.method:
            p.error("review needs a method name, or --validate")
        print(briefs.render(root, "reviewer", study, args.method))
        return 0
    if args.cmd == "repro":
        return _report(runner.repro(sd, params, args.timeout), f"{study}: every matching run reproduced")
    if args.all == bool(args.method):
        p.error("give one method name or --all")
    names = runner.methods(sd) if args.all else [args.method]
    if not names:
        if args.all_studies:
            print(f"• {study}: no methods yet")
            return 0
        raise SystemExit(f"raft: no methods in {sd / 'methods'} yet")
    try:
        combos = runner.expand(sd, params)
    except ValueError as e:
        if args.all_studies:
            print(f"✗ {study}: {e}")
            return 1
        raise SystemExit(f"raft: {e}") from None
    for name in names:
        for combo in combos:
            print(runner.summary(*runner.run_one(sd, name, combo, args.timeout)), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--study", help="study folder under studies/ (default: the only one)")
    common.add_argument("--all-studies", action="store_true", help="repeat for every study that is not a draft")
    p = argparse.ArgumentParser(prog="raft", description="Reproduce research papers with agents, in a controlled environment.")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="start a new study folder (a draft until problem/ is filled in)")
    n.add_argument("study_id")
    n.add_argument("--title", required=True)
    n.add_argument("--doi", required=True)
    e = sub.add_parser("extract", parents=[common], help="print the extractor brief, or --validate extraction.json")
    e.add_argument("--validate", action="store_true")
    im = sub.add_parser("implement", parents=[common], help="print the implementer brief for one method")
    im.add_argument("method")
    r = sub.add_parser("run", parents=[common], help="run methods; extra --key value pairs are study parameters")
    r.add_argument("method", nargs="?")
    r.add_argument("--all", action="store_true")
    r.add_argument("--timeout", type=float, default=1800.0)
    rv = sub.add_parser("review", parents=[common], help="print the reviewer brief, or --validate methods and reviews")
    rv.add_argument("method", nargs="?")
    rv.add_argument("--validate", action="store_true")
    rp = sub.add_parser("repro", parents=[common], help="rerun committed runs; extra --key value pairs filter them")
    rp.add_argument("--timeout", type=float, default=1800.0)
    c = sub.add_parser("compare", help="score every run and build the static site")
    c.add_argument("--out", default="site")
    keep, rest = _split(sys.argv[1:] if argv is None else argv)
    args = p.parse_args(keep)
    if rest and args.cmd not in ("run", "repro"):
        p.error(f"unrecognized arguments: {' '.join(rest)}")
    root = paths.repo_root()

    if args.cmd == "new":
        d = scaffold.new_study(root, args.study_id, args.title, args.doi)
        print(f"✓ created {d.relative_to(root)} as a draft. Next: fill in problem/setup.py, problem/measure.py and "
              f"problem/reference.json, put the PDF at papers/{args.study_id}.pdf, delete `draft: true` from "
              f"paper.yaml, then run `uv run raft extract --study {args.study_id}`.")
        return 0
    if args.cmd == "compare":
        from . import compare
        out = Path(args.out) if Path(args.out).is_absolute() else root / args.out
        compare.write_site(compare.build(root, compare.repo_url(root)), out)
        print(f"✓ site written to {out}. Open {out / 'index.html'}")
        return 0

    params = _params(rest)
    if args.all_studies:
        single = (args.cmd == "implement" or (args.cmd in ("extract", "review") and not args.validate)
                  or (args.cmd == "run" and not args.all) or args.study)
        if single:
            p.error("--all-studies works with: extract --validate, review --validate, run --all, repro (and not with --study)")
        targets = paths.studies(root)
        if not targets:
            raise SystemExit("raft: no studies yet (drafts are skipped)")
    else:
        targets = [paths.resolve_study(root, args.study)]
    code = 0
    for study in targets:
        if args.all_studies:
            print(f"── {study}")
        code = max(code, _study_cmd(p, args, root, study, params))
    return code
```

Notes: the `_study_cmd` messages for `repro` now include the study name; `test_cli.py` only checks exit codes there. Update `tests/test_cli.py::test_validate_commands` if it asserted any changed text (it checks only for "✓").

`.github/workflows/ci.yml`: replace the three study steps with
```yaml
      - run: uv run raft extract --validate --all-studies
      - run: uv run raft review --validate --all-studies
      - run: uv run raft repro --all-studies
```

- [ ] **Step 12b.4: Run to verify pass**

Run: `uv run pytest -q`
Expected: all PASS, with the earlier suites unchanged.

- [ ] **Step 12b.5: Real-repo smoke check**

Run: `uv run raft repro --all-studies`
Expected: `── ghia-1982` followed by one ✓ per committed run, and `✓ ghia-1982: every matching run reproduced`.

- [ ] **Step 12b.6: Commit**

```bash
git add raft/scaffold.py raft/paths.py raft/cli.py raft/compare.py .github/workflows/ci.yml tests/test_multi_study.py
git commit -m "raft new and --all-studies: scaffold studies, rerun and validate every paper at once"
```

---

### Task 13: Open-source documents

**Files:**
- Create: `LICENSE`, `README.md`, `CONTRIBUTING.md`, `CITATION.cff`, `CODE_OF_CONDUCT.md`, `.github/ISSUE_TEMPLATE/new-study.md`, `.github/ISSUE_TEMPLATE/reproduction-failed.md`

- [ ] **Step 13.1: Licence**

Run: `curl -fsSL https://www.apache.org/licenses/LICENSE-2.0.txt -o LICENSE && head -3 LICENSE`
Expected: the header shows "Apache License / Version 2.0, January 2004".

- [ ] **Step 13.2: README**

`README.md`:
````markdown
# Paper Raft

Agents reproduce research papers in a controlled environment, and every result shows how far to trust it.

A paper goes in. Out come independent implementations of its methods, measured with the same tools against the paper's own numbers, checked by a separate reviewer, and browsable in a static site where every number links to its code, its run and its page in the paper.

![Comparison view](docs/screenshots/site-comparison.png)

## Quickstart

```bash
uv sync
uv run raft run --all --re 100   # every method, every grid, Re = 100
uv run raft compare              # builds site/; open site/index.html
```

No API key is needed to rerun and check results.

## How it works

| Stage | Who | Writes | Gate |
|---|---|---|---|
| Extract | extractor agent | `extraction.json`: methods, equations, settings, each with a page; gaps flagged `missing` | `raft extract --validate` |
| Implement | one agent per method, in parallel | `methods/<name>/`, and nothing else | guard test: no peeking at the reference |
| Run | `raft run` | `runs/<id>/manifest.json` + `results.json` | `raft repro` reruns from a clean checkout |
| Review | a different agent per method | `reviews/<name>.json` | `raft review --validate` |
| Compare | `raft compare` | `site/` | |

Working with many papers: `uv run raft new <id> --title … --doi …` starts a study, and `uv run raft repro --all-studies` reruns every committed result in every study. CI does the same on every push.

A result shows as **verified** only when it is within tolerance, a reviewer verified the exact solver commit that produced it, and the run was made from committed code. Everything else shows as **unverified** or **failed**, and failures are published too.

## First study: Ghia, Ghia & Shin (1982)

Lid-driven cavity flow at Re = 100, scored against the paper's centreline velocity tables (max error ≤ 0.01), using three independent methods: stream-function/vorticity, projection, and lattice Boltzmann. The reference values are reproduced with attribution: Ghia, U., Ghia, K. N., & Shin, C. T. (1982), *J. Comput. Phys.* 48, 387–411, doi:10.1016/0021-9991(82)90058-4. The paper itself is not in this repository.

## Using it with your agent tool

The roles in `roles/` are plain markdown, and `raft extract | implement <m> | review <m>` prints them filled in for a study, so any tool can follow them. Claude Code users get ready-made agents and a `reproduce-paper` skill in `.claude/` (source: `adapters/claude-code/`).

## Add a study or a method

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Apache-2.0. See [LICENSE](LICENSE). To cite Paper Raft, use [CITATION.cff](CITATION.cff).
````

- [ ] **Step 13.3: CONTRIBUTING, CITATION, code of conduct, issue templates**

`CONTRIBUTING.md`:
````markdown
# Contributing to Paper Raft

## Add a method to an existing study
1. Read the brief with `uv run raft implement <your-method>`.
2. Write `studies/<study>/methods/<your-method>/solver.py` and `method.json`, touching nothing outside that folder.
3. Run `uv run pytest -q`. The guard test must pass.
4. Commit the folder, then run `uv run raft run <your-method> --re 100` and commit `runs/<your-method>-*`.
5. Open a PR. A maintainer or a different agent reviews it with `uv run raft review <your-method>`; you can't review your own method.

## Add a study (a new paper)
Start with `uv run raft new <id> --title "…" --doi "…"`. That creates a draft folder, which `--all-studies` and the site skip until you remove `draft: true` from `paper.yaml`. Fill in:
- `paper.yaml`: `title`, `authors`, `citation`, `doi`, `pdf` (a local path under `papers/`; never commit the PDF), `experiment`
- `problem/setup.py`: `make_setup(params)`, `expand(params)`, `HEADLINE`, optional `REPRO_RTOL`, and a docstring that defines the `solve(setup)` interface
- `problem/measure.py`: `measure(setup, fields, reference)` returning `samples`, `reference_samples`, `errors`, `tolerance`, `pass`, and optionally `fields_coarse`
- `problem/reference.json`: the paper's numbers, with table and page references and a citation

Then run the extractor (`uv run raft extract --study <id>`) and continue as above. Copy `studies/ghia-1982/` as a worked example.

## Ground rules
- Never lower a tolerance to make something pass.
- Failed reproductions are welcome: commit them, with the reason.
- Never commit paper PDFs.
````

`CITATION.cff`:
```yaml
cff-version: 1.2.0
message: "If you use Paper Raft, please cite it as below."
title: "Paper Raft"
type: software
license: Apache-2.0
authors:
  - family-names: Oliveira
    given-names: Lucas
repository-code: "https://github.com/lusknchars/paper-raft"
references:
  - type: article
    title: "High-Re solutions for incompressible flow using the Navier–Stokes equations and a multigrid method"
    authors:
      - family-names: Ghia
        given-names: U.
      - family-names: Ghia
        given-names: K. N.
      - family-names: Shin
        given-names: C. T.
    journal: "Journal of Computational Physics"
    volume: 48
    issue: 3
    start: 387
    end: 411
    year: 1982
    doi: "10.1016/0021-9991(82)90058-4"
```

`CODE_OF_CONDUCT.md`:
```markdown
# Code of Conduct

This project follows the [Contributor Covenant, version 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). Report unacceptable behaviour by opening a private security advisory on the repository, or by contacting the maintainer listed in CITATION.cff.
```

`.github/ISSUE_TEMPLATE/new-study.md`:
```markdown
---
name: New study
about: Propose a paper to reproduce
---
**Paper** (title, authors, year, DOI):

**Experiment to reproduce** (which table or figure, which parameters):

**Published reference numbers available?** (yes/no, and where in the paper):

**Methods worth comparing:**
```

`.github/ISSUE_TEMPLATE/reproduction-failed.md`:
```markdown
---
name: Reproduction failed
about: A committed run does not reproduce on your machine
---
**Command** (e.g. `uv run raft repro --re 100`):

**Output** (paste the ✗ lines):

**Platform** (OS, CPU, `uv run python -V`):
```

- [ ] **Step 13.4: Commit**

```bash
git add LICENSE README.md CONTRIBUTING.md CITATION.cff CODE_OF_CONDUCT.md .github/ISSUE_TEMPLATE
git commit -m "Open-source documents: licence, README, contributing, citation, conduct, issue templates"
```

---

### Task 14: Clean-clone verification and publish (owner-gated)

- [ ] **Step 14.1: Clean clone reproduces**

Run:
```bash
S=$(mktemp -d) && git clone -q ~/paper-raft "$S/paper-raft" && cd "$S/paper-raft" \
  && uv sync --locked && uv run pytest -q && uv run raft repro --re 100 && uv run raft compare
```
Expected: every step exits 0, and `site/index.html` exists in the clone.

- [ ] **Step 14.2: Spec success checklist (§6)**

Confirm and write down the evidence for each:
- a verified method at re100/grid129 with max error ≤ 1e-2
- all three methods have runs and reviews
- the clean-clone reproduction passed (Step 14.1)
- the local CI gate passed (Step 12.2)

- [ ] **Step 14.3: Ask the owner before publishing**

Stop and ask: "Create public repo `lusknchars/paper-raft`, push `main`, and enable GitHub Pages?" Only after an explicit yes, run:
```bash
cd ~/paper-raft
gh repo create lusknchars/paper-raft --public --source . --remote origin --description "Agents reproduce research papers in a controlled environment" --push
gh api -X POST repos/lusknchars/paper-raft/pages -f build_type=workflow
gh run watch --exit-status "$(gh run list --limit 1 --json databaseId -q '.[0].databaseId')"
```
Expected: the CI run succeeds and the Pages URL is printed in the deploy job. Open it and repeat the Step 10.7 checks on the live site.

---

### Optional Task 15 (stretch): Re = 1000

Only after Task 14. For each method, run `uv run raft run <name> --re 1000 --grid 129` (expect longer runtimes; raise `--timeout` if needed), commit the runs, re-review only if solver code changed, and rerun `raft compare`. Report the results whatever they are; there is no tolerance change.

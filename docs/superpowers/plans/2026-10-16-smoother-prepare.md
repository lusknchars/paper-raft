# Smoother Prepare Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `raft prepare` finds tool problems before spending a step, names them in plain words when they happen,
stops without wasted retries, keeps the builder's home path out of transcripts, and always ends with the one next
command (also available as `raft status`).

**Architecture:** `raft/agents.py` gains `diagnose()` (reads a step's transcript and stderr into a `Problem`).
`raft/doctor.py` checks the tools (installed, logged in, a trivial try, cached). `raft/studystate.py` knows a
study's stage and the next command. `raft/bench.py` gains redaction in the one function that saves transcripts.
`prepare` and `bench` call all of these. The attacker brief is reworded as testing a grader with decoys.

**Tech Stack:** Python 3, argparse, pytest; fake `codex`/`claude` executables for tests.

**Spec:** `docs/superpowers/specs/2026-10-16-smoother-prepare-design.md`

## Global Constraints

- Never add Co-Authored-By Claude or "Generated with Claude Code" lines to commits.
- Never edit `studies/*/problem/` of a study with runs; never lower a tolerance.
- Recognisers for named tool failures come only from recorded samples in `tests/fixtures/tool-failures/`.
- `--agent command` is never diagnosed or checked by `doctor` (its output format is unknown).
- Don't rename the `raft attack` command, the `checker/attacks/` folder, or the `review.json` fields.
- The try brief is exactly: ``Run `echo raft-ok` in the shell, then reply with exactly: raft-ok``. It runs with a
  120-second limit, and a pass is cached for 12 hours in `.raft/doctor.json`, keyed by tool, version, model and oss.
- `Problem.detail` is at most 300 characters.
- Display names: `codex` → "Codex", `claude-code` → "Claude Code". The other tool: codex ↔ claude-code.
- Run the suite with `uv run pytest -q`.

## Review Focus

1. A Codex `error` event that the tool recovers from (for example a reconnect notice, followed by `turn.completed`)
   must not stop a run (test in Task 2).
2. A step where the tool reports an error but still left valid files (for example Claude Code hitting its turn limit
   after writing a good extraction) must continue, not stop (test in Task 3).
3. `HOME` unset, empty or `/` must never make redaction replace every slash, and a longer name that starts with the
   home path (`/Users/someone2`) must stay as it is (tests in Task 1).
4. A corrupted `.raft/doctor.json` must be treated as empty, not crash the run (test in Task 5).
5. A tool that hangs during the try is stopped at the limit and reported, with the run stopped before any step
   (test in Task 5).

---

### Task 1: Transcripts without the home path

**Files:**
- Modify: `raft/bench.py` (add `redact`, `redact_file`, `transcripts_with_home`; `trim_copy` redacts)
- Modify: `raft/prepare.py` (redact the study's existing transcripts at start)
- Test: `tests/test_redact.py`

**Interfaces:**
- Produces: `bench.redact(data: bytes) -> bytes`, `bench.redact_file(path: Path) -> bool` (True when it changed the
  file), `bench.transcripts_with_home(paths) -> list[Path]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_redact.py`:

```python
"""Saved transcripts never carry the builder's home path."""
import json

from raft import bench
from test_prepare import env, run  # noqa: F401  (env is a fixture)


def test_redact_replaces_the_home_path(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/someone")
    data = json.dumps({"cmd": "cat /Users/someone/paper-raft/x.py", "cwd": "/Users/someone"}).encode() + b"\n"
    assert bench.redact(data) == json.dumps({"cmd": "cat ~/paper-raft/x.py", "cwd": "~"}).encode() + b"\n"


def test_redact_needs_a_real_home(monkeypatch):
    for home in ("/", ""):
        monkeypatch.setenv("HOME", home)
        assert bench.redact(b"/usr/bin/x /Users/a .") == b"/usr/bin/x /Users/a ."


def test_redact_leaves_a_longer_name_alone(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/someone")
    assert bench.redact(b'"/Users/someone2/x" "/Users/someone"') == b'"/Users/someone2/x" "~"'


def test_trim_copy_redacts_before_trimming(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", "/Users/someone")
    src = tmp_path / "t.jsonl"
    src.write_bytes(b'{"p": "/Users/someone/a"}\n' * 40)
    bench.trim_copy(src, tmp_path / "out.jsonl", limit=200)
    out = (tmp_path / "out.jsonl").read_bytes()
    assert b"/Users/someone" not in out and b'"~/a"' in out and b"raft_trimmed_bytes" in out


def test_redact_file_and_finding_unredacted_files(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", "/Users/someone")
    p = tmp_path / "x.jsonl"
    p.write_bytes(b'{"p": "/Users/someone/x"}\n')
    assert bench.transcripts_with_home([p, tmp_path / "gone.jsonl"]) == [p]
    assert bench.redact_file(p) is True and bench.redact_file(p) is False
    assert bench.transcripts_with_home([p]) == []


def test_prepare_redacts_the_studys_old_transcripts(env, monkeypatch):  # noqa: F811
    root, cmd = env
    monkeypatch.setenv("HOME", "/Users/someone")
    t = root / "studies" / "tiny" / "checker" / "transcripts"
    t.mkdir(parents=True)
    (t / "old-1.jsonl").write_bytes(b'{"p": "/Users/someone/x"}\n')
    run(root, cmd)
    assert (t / "old-1.jsonl").read_bytes() == b'{"p": "~/x"}\n'
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q tests/test_redact.py`
Expected: FAIL with `AttributeError: module 'raft.bench' has no attribute 'redact'`.

- [ ] **Step 3: Implement**

In `raft/bench.py`, replace `trim_copy` with:

```python
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
```

In `raft/prepare.py` `prepare`, right after `sd = root / "studies" / study` and its `paper.yaml` check, add:

```python
    for t in sorted((sd / "checker" / "transcripts").glob("*")):
        if t.is_file():
            bench.redact_file(t)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q tests/test_redact.py tests/test_bench_workspace.py tests/test_prepare.py`
Expected: PASS.

- [ ] **Step 5: Run the whole suite, then commit**

Run: `uv run pytest -q` → all pass, 1 skipped.

```bash
git add raft/bench.py raft/prepare.py tests/test_redact.py
git commit -m "Transcripts replace the home path with ~; prepare cleans a study's old transcripts"
```

---

### Task 2: `agents.diagnose`: name the tool problem in a step

**Files:**
- Modify: `raft/agents.py` (add `NAMES`, `OTHER`, `Problem`, `diagnose`)
- Create: `tests/fixtures/tool-failures/codex-refused.jsonl` (copy of the real
  `studies/wu-2026-multimodal/checker/transcripts/attack-1.jsonl`)
- Create: `tests/fixtures/tool-failures/codex-code-mode.stderr.txt` (copy of the real
  `studies/wu-2026-multimodal/checker/transcripts/extract-1.stderr.txt`)
- Test: `tests/test_diagnose.py`

**Interfaces:**
- Produces:
  - `agents.NAMES = {"codex": "Codex", "claude-code": "Claude Code", "command": "your command"}`
  - `agents.OTHER = {"codex": "claude-code", "claude-code": "codex"}`
  - `@dataclass(frozen=True) class Problem: kind: str; tool: str; detail: str; advice: str` with
    `headline(step: str) -> str` and `as_dict(role: str, step: str) -> dict` (keys `kind, tool, role, detail, headline`)
  - `agents.diagnose(agent: str, text: str, stderr: str, exit_code: int | None) -> Problem | None`

- [ ] **Step 1: Copy the recorded samples**

```bash
mkdir -p tests/fixtures/tool-failures
cp studies/wu-2026-multimodal/checker/transcripts/attack-1.jsonl tests/fixtures/tool-failures/codex-refused.jsonl
cp studies/wu-2026-multimodal/checker/transcripts/extract-1.stderr.txt tests/fixtures/tool-failures/codex-code-mode.stderr.txt
grep -c "$HOME" tests/fixtures/tool-failures/* || true
```

Expected: the grep prints `0` for both files (neither sample holds the home path).

- [ ] **Step 2: Write the failing tests**

`tests/test_diagnose.py`:

```python
"""Name what went wrong with the tool in a step, from its own output. Recognisers come from recorded samples."""
import json
from pathlib import Path

import pytest

from raft import agents

FIX = Path(__file__).parent / "fixtures" / "tool-failures"


def ev(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_codex_refusal_from_the_real_sample():
    p = agents.diagnose("codex", (FIX / "codex-refused.jsonl").read_text(), "", 1)
    assert p.kind == "refused" and p.tool == "codex"
    assert "flagged for possible cybersecurity risk" in p.detail and len(p.detail) <= 300
    assert p.headline("attack") == "Codex refused the attack brief (its content filter flagged it)"
    assert "Claude Code" in p.advice


def test_codex_code_mode_host_from_the_real_sample():
    p = agents.diagnose("codex", ev({"type": "turn.started"}, {"type": "turn.completed", "usage": {}}),
                        (FIX / "codex-code-mode.stderr.txt").read_text(), 0)
    assert p.kind == "tool-broken" and "code-mode host" in p.detail
    assert p.headline("extract") == "Codex's shell tool is failing"
    assert "uv run raft doctor --agent codex --try" in p.advice


def test_a_recovered_codex_error_is_fine():
    text = ev({"type": "error", "message": "Reconnecting... 1/5"}, {"type": "turn.completed", "usage": {}})
    assert agents.diagnose("codex", text, "", 0) is None


def test_another_codex_failure_keeps_its_own_words():
    p = agents.diagnose("codex", ev({"type": "turn.failed", "error": {"message": "model gpt-x not found"}}), "", 1)
    assert p.kind == "tool-error" and p.detail == "model gpt-x not found"
    assert p.headline("build") == "Codex stopped with an error"


def test_claude_error_result():
    text = ev({"type": "result", "subtype": "error_during_execution", "is_error": True,
               "result": "API Error: 529 overloaded"})
    p = agents.diagnose("claude-code", text, "", 1)
    assert p.kind == "tool-error" and "529 overloaded" in p.detail


def test_claude_success_is_fine():
    text = ev({"type": "result", "subtype": "success", "is_error": False, "result": "done"})
    assert agents.diagnose("claude-code", text, "", 0) is None


@pytest.mark.parametrize("agent", ["codex", "claude-code"])
def test_no_output(agent):
    p = agents.diagnose(agent, "", "", 0)
    assert p.kind == "no-output" and p.headline("extract").endswith("printed nothing")


def test_a_timeout_is_not_no_output():
    assert agents.diagnose("codex", "", "", None) is None  # prepare reports timeouts itself


def test_command_agents_are_never_diagnosed():
    assert agents.diagnose("command", "", "timed out negotiating with the code-mode host", 0) is None


def test_details_are_cut():
    p = agents.diagnose("codex", ev({"type": "turn.failed", "error": {"message": "x " * 400}}), "", 1)
    assert len(p.detail) <= 300


def test_as_dict():
    p = agents.diagnose("codex", (FIX / "codex-refused.jsonl").read_text(), "", 1)
    d = p.as_dict("attacker", "attack")
    assert d["kind"] == "refused" and d["role"] == "attacker" and d["headline"].startswith("Codex refused")
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest -q tests/test_diagnose.py`
Expected: FAIL with `AttributeError: module 'raft.agents' has no attribute 'diagnose'`.

- [ ] **Step 4: Implement**

In `raft/agents.py`, add `from dataclasses import dataclass` to the imports, and after `ISOLATION`:

```python
NAMES = {"codex": "Codex", "claude-code": "Claude Code", "command": "your command"}
OTHER = {"codex": "claude-code", "claude-code": "codex"}
CODE_MODE = "timed out negotiating with the code-mode host"  # tests/fixtures/tool-failures/codex-code-mode.stderr.txt
REFUSED = "flagged for possible"  # tests/fixtures/tool-failures/codex-refused.jsonl


@dataclass(frozen=True)
class Problem:
    """What went wrong with the tool itself in a step, in plain words, with what to do."""
    kind: str  # refused | tool-broken | tool-error | no-output
    tool: str
    detail: str
    advice: str

    def headline(self, step: str) -> str:
        t = NAMES.get(self.tool, self.tool)
        return {"refused": f"{t} refused the {step} brief (its content filter flagged it)",
                "tool-broken": f"{t}'s shell tool is failing",
                "tool-error": f"{t} stopped with an error",
                "no-output": f"{t} printed nothing"}[self.kind]

    def as_dict(self, role: str, step: str) -> dict:
        return {"kind": self.kind, "tool": self.tool, "role": role, "detail": self.detail,
                "headline": self.headline(step)}


def _cut(text) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= 300 else s[:299] + "…"


def diagnose(agent: str, text: str, stderr: str, exit_code) -> "Problem | None":
    """Read a step's transcript and stderr. None when the tool itself looks fine (the step's files are judged
    elsewhere). Unknown tools (`command`) are never diagnosed."""
    if agent not in EXE:
        return None
    t = NAMES[agent]
    check = f"Check {t} with `uv run raft doctor --agent {agent} --try`, then run the command below."
    for line in stderr.splitlines():
        if CODE_MODE in line:
            return Problem("tool-broken", agent, _cut(line),
                           f"Update or restart {t}, then check it with `uv run raft doctor --agent {agent} --try`.")
    events = list(_events(text))
    if agent == "codex":
        bad = [i for i, e in enumerate(events) if e.get("type") in ("error", "turn.failed")]
        if bad and not any(e.get("type") == "turn.completed" for e in events[bad[-1] + 1:]):
            e = events[bad[-1]]
            msg = str((e.get("message") if e["type"] == "error" else (e.get("error") or {}).get("message")) or e["type"])
            if REFUSED in msg:
                return Problem("refused", agent, _cut(msg), f"Run this step with {NAMES[OTHER[agent]]} instead.")
            return Problem("tool-error", agent, _cut(msg), check)
    else:
        results = [e for e in events if e.get("type") == "result"]
        if results and results[-1].get("is_error"):
            r = results[-1]
            return Problem("tool-error", agent, _cut(r.get("result") or r.get("subtype") or "error"), check)
    if exit_code is not None and not text.strip():
        last = stderr.strip().splitlines()[-1] if stderr.strip() else "no output at all"
        return Problem("no-output", agent, _cut(last), check)
    return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q tests/test_diagnose.py tests/test_agents.py`
Expected: PASS.

- [ ] **Step 6: Run the whole suite, then commit**

Run: `uv run pytest -q` → all pass.

```bash
git add raft/agents.py tests/test_diagnose.py tests/fixtures/tool-failures
git commit -m "agents.diagnose: name a refused brief, a broken shell tool, a tool error or no output, from recorded samples"
```

---

### Task 3: prepare and bench stop on a named tool problem, with the command to continue

**Files:**
- Create: `raft/studystate.py` (only `prepare_cmd` in this task)
- Modify: `raft/contracts/live.schema.json` (optional `problem`)
- Modify: `raft/live.py` (`Session.set_problem`)
- Modify: `raft/prepare.py` (`_agent` diagnoses; `_step` returns the problem; `_stop_for`; callers; stop messages
  use `prepare_cmd`)
- Modify: `raft/bench.py` (`_bench_body` stops on a problem when the method wrote no solver)
- Test: `tests/test_prepare_problems.py`

**Interfaces:**
- Consumes: `agents.diagnose`, `agents.Problem`, `agents.NAMES`, `agents.OTHER` (Task 2); `live.read_tail`.
- Produces:
  - `studystate.prepare_cmd(study: str, agent: str | None = None, attacker: str | None = None) -> str`
  - `live.Session.set_problem(problem: dict) -> None`; live sessions may carry
    `"problem": {"kind","tool","role","detail","headline"}`
  - `prepare._stop_for(problem, step, study, role, agent, attacker, ls)` raises `SystemExit`

Ruling carried from the spec: a step whose tool reports a problem but whose files pass their checks continues; the
problem only stops the run when the step's own check also fails. That is what "a step that ran fine but left the
wrong files keeps today's behaviour" needs, and it keeps good work that ended with a tool error.

- [ ] **Step 1: Write the failing tests**

`tests/test_prepare_problems.py`:

```python
"""A named tool problem stops prepare (or bench) at once, with the command to continue; good files still count."""
import sys

import pytest

from raft import agents, bench, live, prepare, studystate
from test_bench_cli import tiny  # noqa: F401  (bench fixture)
from test_prepare import env, run  # noqa: F401  (env is a fixture)

REFUSED = agents.Problem("refused", "codex", "This content was flagged for possible cybersecurity risk.",
                         "Run this step with Claude Code instead.")
BROKEN = agents.Problem("tool-broken", "codex", "ERROR codex_core::tools::router: error=timed out negotiating with "
                        "the code-mode host", "Update or restart Codex, then check it with "
                        "`uv run raft doctor --agent codex --try`.")


def always(problem, monkeypatch):
    monkeypatch.setattr(agents, "diagnose", lambda agent, text, stderr, code: problem)


def transcripts(root, step):
    return [p for p in (root / "studies" / "tiny" / "checker" / "transcripts").glob(f"{step}-*.jsonl")]


def test_prepare_cmd():
    assert studystate.prepare_cmd("s") == "uv run raft prepare --study s --agent <claude-code|codex>"
    assert studystate.prepare_cmd("s", "codex", "codex") == "uv run raft prepare --study s --agent codex"
    assert studystate.prepare_cmd("s", "codex", "claude-code") == \
        "uv run raft prepare --study s --agent codex --attacker claude-code"
    assert studystate.prepare_cmd("s", "command", "command") == 'uv run raft prepare --study s --agent command --cmd "…"'


def test_a_tool_problem_with_good_files_does_not_stop(env, monkeypatch):  # noqa: F811
    root, cmd = env
    always(REFUSED, monkeypatch)
    assert run(root, cmd) == "tiny"


def test_a_refused_attack_stops_after_one_try_and_switches_the_attacker(env, monkeypatch):  # noqa: F811
    root, cmd = env
    always(REFUSED, monkeypatch)
    monkeypatch.setenv("FAKE_MODE", "silent-attacker")
    with pytest.raises(SystemExit) as e:
        run(root, cmd)
    msg = str(e.value)
    assert msg.startswith("raft: Codex refused the attack brief (its content filter flagged it)")
    assert "Run this step with Claude Code instead." in msg
    assert msg.rstrip().endswith('Next: uv run raft prepare --study tiny --agent command --cmd "…" --attacker claude-code')
    assert len(transcripts(root, "attack")) == 1
    s = live.sessions(root)[0]
    assert s["state"] == "stopped" and s["problem"]["kind"] == "refused" and s["problem"]["role"] == "attacker"


def test_a_broken_builder_stops_without_a_second_try(env, monkeypatch):  # noqa: F811
    root, cmd = env
    always(BROKEN, monkeypatch)
    monkeypatch.setenv("FAKE_MODE", "silent")
    with pytest.raises(SystemExit) as e:
        run(root, cmd)
    msg = str(e.value)
    assert "Codex's shell tool is failing" in msg and "uv run raft doctor --agent codex --try" in msg
    assert 'Next: uv run raft prepare --study tiny --agent command --cmd "…"' in msg
    assert len(transcripts(root, "build")) == 1


def test_without_a_problem_the_old_retry_stays(env, monkeypatch):  # noqa: F811
    root, cmd = env
    monkeypatch.setenv("FAKE_MODE", "silent")
    with pytest.raises(SystemExit, match="the checker does not hold after 2 builder tries"):
        run(root, cmd)
    assert len(transcripts(root, "build")) == 2


def test_bench_stops_when_the_tool_fails_and_wrote_nothing(tiny, monkeypatch):  # noqa: F811
    root, _ = tiny
    always(REFUSED, monkeypatch)
    nothing = f'{sys.executable} -c "import sys" {{brief}}'
    with pytest.raises(SystemExit) as e:
        bench.run_bench(root, "tiny", "command", cmd=nothing, timeout=60, run_timeout=60, out_dir=root / "out",
                        log=lambda s: None)
    assert "Codex refused the implement exact brief" in str(e.value)
    assert "Next: uv run raft bench --study tiny --agent claude-code" in str(e.value)
    assert live.sessions(root)[0]["problem"]["role"] == "agent"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q tests/test_prepare_problems.py`
Expected: FAIL at import: `ImportError: cannot import name 'studystate' from 'raft'`.

- [ ] **Step 3: `studystate.prepare_cmd`, the live `problem`**

Create `raft/studystate.py`:

```python
"""raft status: where a study stands, one line per gate, and the one command to run next."""


def prepare_cmd(study: str, agent: str | None = None, attacker: str | None = None) -> str:
    if not agent:
        return f"uv run raft prepare --study {study} --agent <claude-code|codex>"
    cmd = f"uv run raft prepare --study {study} --agent {agent}" + (' --cmd "…"' if agent == "command" else "")
    if attacker and attacker != agent:
        cmd += f" --attacker {attacker}" + (' --attacker-cmd "…"' if attacker == "command" else "")
    return cmd
```

In `raft/contracts/live.schema.json`, add to the top-level `properties` (after `"next"`):

```json
    "problem": {
      "type": ["object", "null"], "additionalProperties": false,
      "required": ["kind", "tool", "role", "detail", "headline"],
      "properties": {"kind": {"enum": ["refused", "tool-broken", "tool-error", "no-output"]},
                     "tool": {"type": "string"}, "role": {"type": "string"},
                     "detail": {"type": "string"}, "headline": {"type": "string"}}
    }
```

(keep the comma after `"next": {...}`). In `raft/live.py`, add to `Session` after `set_results`:

```python
    def set_problem(self, problem: dict) -> None:
        with self._lock:
            self.data["problem"] = problem
            self._write(force=True)
```

- [ ] **Step 4: prepare diagnoses each step and stops on a problem with bad files**

In `raft/prepare.py`:

1. Add `studystate` to the `from . import ...` line.
2. In `_agent`, inside the `with tempfile...` block, after the stderr `trim_copy` and before the `log(...)` line:

```python
        r["problem"] = agents.diagnose(agent, live.read_tail(t), live.read_tail(t.with_suffix(".stderr.txt"), 65536),
                                       r["exit"])
        if r["problem"]:
            log(f"  {step}: {r['problem'].headline(step)}")
```

3. In `_step`, change the return to:

```python
    return {"run": r, "before": before, "after": after, "problem": r["problem"]}
```

4. Add after `_step`:

```python
def _stop_for(problem: "agents.Problem", step: str, study: str, role: str, agent: str, attacker: str,
              ls: "live.Session"):
    """The tool itself failed and the step's files don't pass: a second try with the same tool fails the same way."""
    a, b = agent, attacker
    if problem.kind == "refused" and problem.tool in agents.OTHER:
        if role == "attacker":
            b = agents.OTHER[problem.tool]
        else:
            a = agents.OTHER[problem.tool]
    ls.set_problem(problem.as_dict(role, step))
    raise SystemExit(f"raft: {problem.headline(step)}\n  {agents.NAMES.get(problem.tool, problem.tool)}: "
                     f"{problem.detail}\n{problem.advice}\nNext: {studystate.prepare_cmd(study, a, b)}")
```

5. In `_prepare_steps`:
   - Replace the first line with
     `next_step = f"Fix it by hand or run `{studystate.prepare_cmd(study, agent, attacker)}`."`
     (keep the inner backticks: the f-string is `f"Fix it by hand or run \`{...}\`."`).
   - Extract loop: change `_step(root, sd, "extract", ...)` to `done = _step(root, sd, "extract", ...)`, and after
     `problems = validate.extraction(sd)` add:

```python
        if problems and done["problem"]:
            ls.end(sid, "failed", detail=done["problem"].headline("extract"))
            _stop_for(done["problem"], "extract", study, "builder", agent, attacker, ls)
```

   - Build loop: change `_step(root, sd, "build", ...)` to `done = _step(...)`, and after
     `holes = checker.validate(...)` and `ls.set_results(holes=len(holes))` add:

```python
        if holes and done["problem"]:
            ls.end(sid, "failed", detail=done["problem"].headline("build"))
            _stop_for(done["problem"], "build", study, "builder", agent, attacker, ls)
```

   - Attack loop: inside `if done["run"]["timed_out"] or not new_files ...:`, before `why = ...`, add:

```python
            if done["problem"]:
                ls.end(sid, "failed", detail=done["problem"].headline("attack"))
                _stop_for(done["problem"], "attack", study, "attacker", agent, attacker, ls)
```

     and in that block's `raise SystemExit(...)`, replace ``rerun `uv run raft prepare --study {study}`.`` with
     ``run `{studystate.prepare_cmd(study, agent, attacker)}`.``
   - The "holes remain after N rounds" message: replace ``or rerun `uv run raft prepare --study {study}`.`` with
     ``or run `{studystate.prepare_cmd(study, agent, attacker)}`.``
   - Fix step: change `_step(root, sd, "build", text, ..., fid, ...)` to `done = _step(...)` and after its
     `holes = checker.validate(...)` / `ls.set_results(holes=len(holes))` add:

```python
        if holes and done["problem"]:
            ls.end(fid, "failed", detail=done["problem"].headline("build"))
            _stop_for(done["problem"], "build", study, "builder", agent, attacker, ls)
```

   Read the code around each edit: keep `ls.end` calls that already exist for the normal path in place.

- [ ] **Step 5: bench stops on a problem when the method wrote no solver**

In `raft/bench.py` `_bench_body`, after the `with live.watching(...)` block that runs the agent and before
`ls.end(sid, ...)`:

```python
            problem = agents.diagnose(agent, live.read_tail(logs / f"{m}.jsonl"),
                                      live.read_tail(logs / f"{m}.stderr.txt", 65536), t["exit"])
            if problem and not (ws / "studies" / study / "methods" / m / "solver.py").is_file():
                step = f"implement {m}"
                ls.end(sid, "failed", detail=problem.headline(step))
                ls.set_problem(problem.as_dict("agent", step))
                nxt = agents.OTHER.get(problem.tool, agent) if problem.kind == "refused" else agent
                raise SystemExit(f"raft: {problem.headline(step)}\n  {agents.NAMES.get(problem.tool, problem.tool)}: "
                                 f"{problem.detail}\n{problem.advice}\n"
                                 f"Next: uv run raft bench --study {study} --agent {nxt} (add your --setup, --model "
                                 "and --label again)")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest -q tests/test_prepare_problems.py tests/test_prepare.py tests/test_prepare_live.py tests/test_checker_hardening.py tests/test_bench_live.py tests/test_live.py tests/test_schema.py`
Expected: PASS. (Existing tests that match `raft prepare --study tiny` still match: `prepare_cmd` keeps that text.)

- [ ] **Step 7: Run the whole suite, then commit**

Run: `uv run pytest -q` → all pass.

```bash
git add raft/studystate.py raft/contracts/live.schema.json raft/live.py raft/prepare.py raft/bench.py tests/test_prepare_problems.py
git commit -m "prepare and bench stop on a named tool problem, without a wasted retry, and print the command to continue"
```

---

### Task 4: An attacker brief tools don't refuse

**Files:**
- Modify: `roles/checker-attacker.md` (rewritten)
- Modify: `roles/checker-builder.md` (two sentences)
- Test: `tests/test_checker_roles.py` (one new test)

**Interfaces:** none (role text only; the file names, `{{round}}` and the needles in
`test_attacker_role_names_its_limits` stay).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_checker_roles.py`:

```python
import re

FLAGGED = re.compile(r"\b(attack|break|exploit|cheat|hack)\w*", re.I)


def _prose(text: str) -> str:
    return re.sub(r"`[^`]*`", "", text)  # file names and commands in backticks stay as they are


@pytest.mark.parametrize("role", ["checker-attacker", "checker-builder"])
def test_the_grader_briefs_avoid_words_that_trip_content_filters(role):
    found = FLAGGED.findall(_prose((ROOT / "roles" / f"{role}.md").read_text()))
    assert not found, found
```

and add `import pytest` at the top of the file.

Run: `uv run pytest -q tests/test_checker_roles.py`
Expected: FAIL: both briefs contain flagged words (`attacker`, `break`, `cheat`, …).

- [ ] **Step 2: Rewrite `roles/checker-attacker.md`**

```markdown
# Role: grader tester for {{study}}, round {{round}}

Someone built a grader for this paper's experiment. Your job is to test it: write decoy solutions that do not do the paper's work but might still pass, so we learn whether the grader can tell the difference. You did not build the grader and you never fix it.

**Read:** `{{study_dir}}/problem/` (setup.py, measure.py, reference.json, graders/), `{{study_dir}}/checker/NOTE.md`, `{{study_dir}}/checker/answer.py` and the decoys already in `{{study_dir}}/checker/attacks/`.

**Write decoys, each as a new file `{{study_dir}}/checker/attacks/<name>.py` exposing `solve(setup)`:** hard-coded or memorised numbers; answers that only have the right keys, shapes and finite values; answers that stay just inside a tolerance looser than the claim needs; skipping the claim's real condition (an "estimator" that returns the exact answer, a budget that is ignored); cases the grader never looks at; any other shortcut you can think of. A decoy must not mention `reference.json`, `measure`, `problem/`, `runs/`, `reviews/` or `checker/` (the guard rejects that, so it teaches us nothing).

After each decoy, run `uv run raft validate --study {{study}}` to see whether the grader caught it.

**Record** every decoy in `{{study_dir}}/checker/review.json`: keep earlier rounds; add `{"round": {{round}}, "attacks": [{"name": "<file stem>", "idea": "<one sentence>", "blocked": true|false}]}` (`blocked` is true when the grader failed the decoy); set `attacker_agent` to an identifier of yourself and keep `builder_agent` as it is (if the file does not exist yet, set `study`, and `builder_agent` from `checker/NOTE.md` or "unknown").

**Rules:** Never edit `problem/`, `checker/answer.py` or `checker/NOTE.md`. Never delete a decoy. Never run `raft approve`. Say in your final message which decoys passed the grader and why.
```

- [ ] **Step 3: Two sentences in `roles/checker-builder.md`**

- In the first paragraph, replace `and a different agent will try to cheat what you build. Write it so that only real work passes.`
  with `and a different agent will test it with decoy solutions. Write it so that only real work passes.`
- Replace item 6 with:
  ``6. `{{study_dir}}/checker/attacks/<name>.py`: at least two decoy solutions of your own, each a normal `solve(setup)` that should fail (hard-coded numbers, the right shape filled with junk). File names are lowercase with hyphens.``

Then reread the whole file for any other flagged word outside backticks (the test lists them) and reword it the same
way.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q tests/test_checker_roles.py tests/test_prepare.py`
Expected: PASS (the needles in the existing role tests are all still present).

- [ ] **Step 5: Run the whole suite, then commit**

Run: `uv run pytest -q` → all pass.

```bash
git add roles/checker-attacker.md roles/checker-builder.md tests/test_checker_roles.py
git commit -m "Grader briefs describe testing with decoy solutions, not attacks, so content filters don't refuse them"
```

---

### Task 5: `raft doctor` and the preflight in prepare and bench

**Files:**
- Create: `raft/doctor.py`
- Create: `tests/fake_tools.py` (fake `codex` and `claude` executables)
- Modify: `raft/prepare.py` (`try_tools` parameter; preflight before intake)
- Modify: `raft/bench.py` (`try_tools` parameter; preflight after `agents.check`)
- Modify: `raft/cli.py` (`doctor` command; `--no-try` on `prepare` and `bench`; `KNOWN` gains `--try`, `--no-try`, `--quick`)
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `agents.EXE`, `agents.NAMES`, `agents.OTHER`, `agents.run`, `agents.tool_version`, `agents.diagnose`
  (Task 2); `live.activity_lines`; `bench.transcripts_with_home` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class Check: tool: str; ok: bool; line: str`
  - `doctor.check_tools(root, tools: list[tuple[str, str | None, bool]], *, try_: bool = True, try_timeout: float = 120.0, now=None) -> list[Check]`
    (one Check per distinct `(tool, model, oss)`; `command` skipped)
  - `doctor.preflight(root, tools, *, try_: bool, log, now=None) -> None` (raises `SystemExit` before any step)
  - `doctor.home_paths(root, study) -> list[Path]`
  - `prepare.prepare(..., try_tools: bool = True)`, `bench.run_bench(..., try_tools: bool = True)`

- [ ] **Step 1: The fake tools**

`tests/fake_tools.py`:

```python
"""Fake `codex` and `claude` executables, steered by environment variables:
FAKE_LOGIN=0 (not logged in), FAKE_TRY=ok|silent|codemode|hang, FAKE_VERSION, FAKE_CALLS=<file> (one line per run)."""
import os
import sys
from pathlib import Path

COMMON = r'''#!PYTHON
import json, os, sys, time
a = sys.argv[1:]
def calls(what):
    if os.environ.get("FAKE_CALLS"):
        with open(os.environ["FAKE_CALLS"], "a") as f:
            f.write(what + "\n")
def out(events):
    print("\n".join(json.dumps(e) for e in events))
'''

CODEX = COMMON + r'''
if a[:1] == ["--version"]:
    print(os.environ.get("FAKE_VERSION", "codex-cli 9.9.9")); sys.exit(0)
if a[:2] == ["login", "status"]:
    ok = os.environ.get("FAKE_LOGIN", "1") == "1"
    print("Logged in using ChatGPT" if ok else "Not logged in"); sys.exit(0 if ok else 1)
if a[:1] == ["exec"]:
    calls("codex exec"); sys.stdin.read()
    mode = os.environ.get("FAKE_TRY", "ok")
    if mode == "silent":
        sys.exit(0)
    if mode == "hang":
        time.sleep(60)
    if mode == "codemode":
        print("ERROR codex_core::tools::router: error=timed out negotiating with the code-mode host", file=sys.stderr)
    ev = [{"type": "thread.started"}, {"type": "turn.started"}]
    if mode == "ok":
        c = {"id": "c1", "type": "command_execution", "command": "echo raft-ok"}
        ev += [{"type": "item.started", "item": c}, {"type": "item.completed", "item": c},
               {"type": "item.completed", "item": {"id": "m1", "type": "agent_message", "text": "raft-ok"}}]
    out(ev + [{"type": "turn.completed", "usage": {}}]); sys.exit(0)
sys.exit(2)
'''

CLAUDE = COMMON + r'''
if a[:1] == ["--version"]:
    print(os.environ.get("FAKE_VERSION", "9.9.9 (Claude Code)")); sys.exit(0)
if a[:2] == ["auth", "status"]:
    sys.exit(0 if os.environ.get("FAKE_LOGIN", "1") == "1" else 1)
if "-p" in a:
    calls("claude -p"); sys.stdin.read()
    mode = os.environ.get("FAKE_TRY", "ok")
    if mode == "silent":
        sys.exit(0)
    if mode == "hang":
        time.sleep(60)
    ev = []
    if mode == "ok":
        ev = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
                                                             "input": {"command": "echo raft-ok"}}]}},
              {"type": "assistant", "message": {"content": [{"type": "text", "text": "raft-ok"}]}}]
    out(ev + [{"type": "result", "subtype": "success", "is_error": False, "result": "raft-ok"}]); sys.exit(0)
sys.exit(2)
'''


def install(tmp_path: Path, monkeypatch, only: bool = False) -> Path:
    """Put fake codex and claude first on PATH (or alone on it, with only=True). Returns the bin folder."""
    b = tmp_path / "fakebin"
    b.mkdir(exist_ok=True)
    for name, body in (("codex", CODEX), ("claude", CLAUDE)):
        p = b / name
        p.write_text(body.replace("#!PYTHON", "#!" + sys.executable))
        p.chmod(0o755)
    monkeypatch.setenv("PATH", str(b) if only else f"{b}{os.pathsep}{os.environ.get('PATH', '')}")
    return b
```

- [ ] **Step 2: Write the failing tests**

`tests/test_doctor.py`:

```python
"""raft doctor: is each tool installed, logged in, and able to do a trivial task, before a long run starts."""
from datetime import datetime, timedelta, timezone

import pytest

from fake_tools import install
from raft import cli, doctor, prepare
from test_prepare import env, run  # noqa: F401  (env is a fixture)

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
CODEX = [("codex", None, False)]


def one(root, tools=CODEX, **kw):
    (c,) = doctor.check_tools(root, tools, **kw)
    return c


def test_a_working_tool_passes(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    checks = doctor.check_tools(tmp_path, [("codex", None, False), ("claude-code", None, False)], try_=True, now=T0)
    assert [c.ok for c in checks] == [True, True]
    assert "codex-cli 9.9.9" in checks[0].line and "9.9.9 (Claude Code)" in checks[1].line


def test_a_missing_tool(tmp_path, monkeypatch):
    b = install(tmp_path, monkeypatch, only=True)
    (b / "codex").unlink()
    c = one(tmp_path)
    assert not c.ok and "Codex: `codex` is not installed or not on PATH" in c.line


def test_not_logged_in(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_LOGIN", "0")
    c = one(tmp_path)
    assert not c.ok and "run `codex login`" in c.line
    assert "run `claude auth login`" in one(tmp_path, [("claude-code", None, False)]).line


def test_a_local_model_needs_no_login(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_LOGIN", "0")
    assert one(tmp_path, [("codex", "gpt-oss:20b", True)], now=T0).ok


@pytest.mark.parametrize("mode, expect", [("codemode", "Codex's shell tool is failing"),
                                          ("silent", "Codex printed nothing"),
                                          ("nochat", "did not run `echo raft-ok` and reply raft-ok")])
def test_try_failures(tmp_path, monkeypatch, mode, expect):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_TRY", mode)
    c = one(tmp_path, now=T0)
    assert not c.ok and expect in c.line


def test_a_hanging_tool_is_stopped_at_the_limit(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_TRY", "hang")
    c = one(tmp_path, try_timeout=2, now=T0)
    assert not c.ok and "did not finish the test task within 2s" in c.line


def test_without_try_only_install_and_login_are_checked(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_TRY", "silent")
    monkeypatch.setenv("FAKE_CALLS", str(tmp_path / "calls"))
    assert one(tmp_path, try_=False).ok and not (tmp_path / "calls").exists()


def test_a_pass_is_cached_for_twelve_hours_per_version(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    calls = tmp_path / "calls"
    monkeypatch.setenv("FAKE_CALLS", str(calls))
    count = lambda: calls.read_text().count("codex exec") if calls.exists() else 0  # noqa: E731
    one(tmp_path, now=T0)
    one(tmp_path, now=T0 + timedelta(hours=11))
    assert count() == 1
    one(tmp_path, now=T0 + timedelta(hours=13))
    assert count() == 2
    monkeypatch.setenv("FAKE_VERSION", "codex-cli 10.0.0")
    one(tmp_path, now=T0 + timedelta(hours=13, minutes=1))
    assert count() == 3


def test_a_corrupt_cache_is_ignored(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    (tmp_path / ".raft").mkdir()
    (tmp_path / ".raft" / "doctor.json").write_text("{not json")
    assert one(tmp_path, now=T0).ok


def test_command_agents_are_skipped(tmp_path):
    assert doctor.check_tools(tmp_path, [("command", None, False)]) == []


def test_preflight_stops_and_names_the_other_tool(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_TRY", "codemode")  # breaks codex's try; claude's fake has no code-mode line
    lines = []
    with pytest.raises(SystemExit) as e:
        doctor.preflight(tmp_path, CODEX, try_=True, log=lines.append, now=T0)
    msg = str(e.value)
    assert msg.startswith("raft: a tool check failed before any step ran")
    assert "Codex's shell tool is failing" in msg and "Or switch to Claude Code (installed and logged in)." in msg
    assert lines and lines[0].startswith("✗ ")


def test_prepare_runs_the_preflight(env, monkeypatch):  # noqa: F811
    root, cmd = env
    seen = []
    monkeypatch.setattr(doctor, "preflight", lambda root, tools, **kw: seen.append((tools, kw["try_"])))
    run(root, cmd)
    run(root, cmd, try_tools=False)
    assert seen[0][1] is True and seen[1][1] is False
    assert ("command", None, False) in seen[0][0]


def test_cli_doctor(tmp_path, tiny_git_study, monkeypatch, capsys):
    install(tmp_path, monkeypatch)
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["doctor", "--agent", "codex", "--try"]) == 0
    assert "✓ Codex: codex-cli 9.9.9" in capsys.readouterr().out
    assert cli.main(["doctor"]) == 0  # both tools, install and login only
    monkeypatch.setenv("FAKE_LOGIN", "0")
    assert cli.main(["doctor", "--agent", "codex"]) == 1


def test_cli_doctor_finds_home_paths_in_a_studys_transcripts(tiny_git_study, monkeypatch, capsys):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    monkeypatch.setenv("HOME", "/Users/someone")
    t = tiny_git_study / "checker" / "transcripts"
    t.mkdir(parents=True)
    (t / "build-1.jsonl").write_text('{"p": "/Users/someone/x"}\n')
    assert cli.main(["doctor", "--study", "tiny"]) == 1
    assert "studies/tiny/checker/transcripts/build-1.jsonl" in capsys.readouterr().out
```

Note on `nochat`: the fake codex treats any unknown `FAKE_TRY` like `ok` without the command and message events
(it prints only `thread.started`, `turn.started`, `turn.completed`), which is a tool that answered but didn't do the
task.

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest -q tests/test_doctor.py`
Expected: FAIL at import: `ImportError: cannot import name 'doctor' from 'raft'`.

- [ ] **Step 4: Write `raft/doctor.py`**

```python
"""raft doctor: check the agent tools before a long run. Installed, logged in, and (with the try) able to run one
shell command and answer, which catches a broken tool before it costs a 45-minute step."""
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import agents, bench, live

CACHE = Path(".raft") / "doctor.json"
CACHE_FOR = timedelta(hours=12)
TRY_BRIEF = "Run `echo raft-ok` in the shell, then reply with exactly: raft-ok\n"
LOGIN = {"codex": ["codex", "login", "status"], "claude-code": ["claude", "auth", "status"]}
LOGIN_HINT = {"codex": "codex login", "claude-code": "claude auth login"}


@dataclass(frozen=True)
class Check:
    tool: str
    ok: bool
    line: str


def _load(root: Path) -> dict:
    try:
        data = json.loads((Path(root) / CACHE).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(root: Path, data: dict) -> None:
    try:
        (Path(root) / CACHE).parent.mkdir(parents=True, exist_ok=True)
        (Path(root) / CACHE).write_text(json.dumps(data, indent=1) + "\n")
    except OSError:
        pass  # the cache is a convenience; a read-only disk only means the try runs again


def _logged_in(agent: str) -> bool:
    try:
        return subprocess.run(LOGIN[agent], capture_output=True, text=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def try_tool(agent: str, model=None, oss: bool = False, timeout: float = 120.0) -> str | None:
    """Run the trivial task. None when it passed, else why not."""
    with tempfile.TemporaryDirectory(prefix="raft-doctor-") as tmp:
        brief, t = Path(tmp) / "brief.md", Path(tmp) / "t.jsonl"
        brief.write_text(TRY_BRIEF)
        ws = Path(tmp) / "ws"
        ws.mkdir()
        r = agents.run(agent, brief, ws, "doctor", model=model, oss=oss, timeout=timeout, transcript=t)
        text = t.read_text(errors="replace")
        err = t.with_suffix(".stderr.txt").read_text(errors="replace") if t.with_suffix(".stderr.txt").is_file() else ""
    if r["timed_out"]:
        return f"did not finish the test task within {timeout:.0f}s"
    problem = agents.diagnose(agent, text, err, r["exit"])
    if problem:
        return f"{problem.headline('test')}: {problem.detail}"
    lines = live.activity_lines(agent, text)
    ran = any("echo raft-ok" in x for x in lines)
    said = any("raft-ok" in x and "echo" not in x for x in lines)
    return None if r["exit"] == 0 and ran and said else "did not run `echo raft-ok` and reply raft-ok"


def _check(root: Path, agent: str, model, oss: bool, try_: bool, timeout: float, now) -> Check:
    name, exe = agents.NAMES[agent], agents.EXE[agent]
    if shutil.which(exe) is None:
        return Check(agent, False, f"{name}: `{exe}` is not installed or not on PATH")
    ver = agents.tool_version(agent) or "unknown version"
    if not oss and not _logged_in(agent):
        return Check(agent, False, f"{name}: {ver}, not logged in; run `{LOGIN_HINT[agent]}` in your terminal")
    who = "local model" if oss else "logged in"
    if not try_:
        return Check(agent, True, f"{name}: {ver}, {who}")
    key = f"{agent}|{ver}|{model or ''}|{'oss' if oss else ''}"
    cache = _load(root)
    when = cache.get(key)
    try:
        fresh = when and now - datetime.fromisoformat(when) < CACHE_FOR
    except (TypeError, ValueError):
        fresh = False
    if fresh:
        return Check(agent, True, f"{name}: {ver}, {who}, did the test task at {when[:16].replace('T', ' ')}")
    why = try_tool(agent, model, oss, timeout)
    if why:
        return Check(agent, False, f"{name}: {ver}, {who}, but {why}")
    cache[key] = now.isoformat(timespec="seconds")
    _save(root, cache)
    return Check(agent, True, f"{name}: {ver}, {who}, did the test task")


def check_tools(root, tools, *, try_: bool = True, try_timeout: float = 120.0, now=None) -> list[Check]:
    now = now or datetime.now(timezone.utc)
    seen, out = set(), []
    for agent, model, oss in tools:
        if agent not in agents.EXE or (agent, model, oss) in seen:
            continue
        seen.add((agent, model, oss))
        out.append(_check(Path(root), agent, model, bool(oss), try_, try_timeout, now))
    return out


def preflight(root, tools, *, try_: bool, log, now=None) -> None:
    """Before any agent step: stop with the reason (and a tool that would work) if a tool can't do the job."""
    checks = check_tools(root, tools, try_=try_, now=now)
    for c in checks:
        log(("✓ " if c.ok else "✗ ") + c.line)
    bad = [c for c in checks if not c.ok]
    if not bad:
        return
    used = {t for t, _, _ in tools}
    alts = []
    for c in bad:
        other = agents.OTHER.get(c.tool)
        if other and other not in used and all(x.ok for x in check_tools(root, [(other, None, False)], try_=False)):
            alts.append(f"Or switch to {agents.NAMES[other]} (installed and logged in).")
    raise SystemExit("raft: a tool check failed before any step ran:\n  " + "\n  ".join(c.line for c in bad)
                     + "".join("\n" + a for a in dict.fromkeys(alts))
                     + "\nSkip the test task with --no-try only if you know the tool works.")


def home_paths(root, study: str) -> list[Path]:
    root = Path(root)
    files = list((root / "studies" / study / "checker" / "transcripts").glob("*"))
    files += list((root / "bench" / "results" / study).glob("*/transcript/*"))
    return bench.transcripts_with_home(sorted(files))
```

- [ ] **Step 5: Call the preflight from prepare and bench**

In `raft/prepare.py`: add `doctor` to the imports; add `try_tools: bool = True` as the last keyword parameter of
`prepare`; after the second `agents.check(...)` (before `if arxiv:`) add:

```python
    doctor.preflight(root, [(agent, model, False), (attacker, attacker_model, False)], try_=try_tools, log=log)
```

In `raft/bench.py`: add `try_tools: bool = True` as the last keyword parameter of `run_bench`, and after
`agents.check(agent, model=model, oss=oss, cmd=cmd)` add:

```python
    from . import doctor
    doctor.preflight(root, [(agent, model, oss)], try_=try_tools, log=log)
```

(`doctor` imports `bench`, so bench imports it inside the function.)

- [ ] **Step 6: The CLI**

In `raft/cli.py`:

1. `KNOWN` gains `"--try", "--no-try", "--quick"`.
2. Add to the `bench` parser: `b.add_argument("--no-try", action="store_true", help="skip the tool's daily test task")`,
   and to the `prepare` parser: `pr.add_argument("--no-try", action="store_true", help="skip the tools' daily test task")`.
3. Pass `try_tools=not args.no_try` in the `bench.run_bench(...)` and `prepare.prepare(...)` calls.
4. Add the parser (after the `gaps` parser):

```python
    dr = sub.add_parser("doctor", help="check the agent tools (installed, logged in, --try a trivial task) or a study's transcripts")
    dr.add_argument("--agent", choices=("claude-code", "codex"))
    dr.add_argument("--attacker", choices=("claude-code", "codex"))
    dr.add_argument("--model")
    dr.add_argument("--oss", action="store_true")
    dr.add_argument("--try", dest="try_", action="store_true", help="also run a trivial task (uses a few cents of your quota)")
    dr.add_argument("--study", help="report transcripts in this study that still hold your home path")
```

5. Add the dispatch (before the `gaps` dispatch):

```python
    if args.cmd == "doctor":
        from . import doctor
        if args.study:
            study = paths.resolve_study(root, args.study)
            found = doctor.home_paths(root, study)
            for f in found:
                print(f"✗ {f.relative_to(root)} holds your home path; `uv run raft prepare --study {study} …` cleans it")
            return _report([] if not found else [f"{len(found)} transcript(s) to clean"], f"{study}: no home paths in transcripts")
        tools = [(t, args.model, args.oss) for t in dict.fromkeys(x for x in (args.agent, args.attacker) if x)] \
            or [("claude-code", None, False), ("codex", None, False)]
        if args.try_:
            print("• the test task uses a few cents of your quota")
        checks = doctor.check_tools(root, tools, try_=args.try_)
        for c in checks:
            print(("✓ " if c.ok else "✗ ") + c.line)
        return 0 if all(c.ok for c in checks) else 1
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest -q tests/test_doctor.py tests/test_prepare.py tests/test_bench_cli.py tests/test_bench_live.py tests/test_cli.py`
Expected: PASS.

- [ ] **Step 8: Run the whole suite, then commit**

Run: `uv run pytest -q` → all pass.

```bash
git add raft/doctor.py raft/prepare.py raft/bench.py raft/cli.py tests/fake_tools.py tests/test_doctor.py
git commit -m "raft doctor: tools installed, logged in and able to do a trivial task; prepare and bench check before the first step"
```

---

### Task 6: `raft status` and the docs

**Files:**
- Modify: `raft/studystate.py` (add `Stage`, `tools`, `stages`, `next_step`, `report`, `summary`)
- Modify: `raft/cli.py` (`status` command)
- Modify: `README.md` (prepare section: doctor, named problems, status)
- Modify: `AGENTS.md` (two table rows)
- Test: `tests/test_studystate.py`

**Interfaces:**
- Consumes: `studystate.prepare_cmd` (Task 3); live `problem` (Task 3); `agents.OTHER`; `checker.approval_state`,
  `checker.validate`, `checker.APPROVAL`; `gaps.load/counts/count_line`; `validate.extraction`; `runner.methods`.
- Produces:
  - `@dataclass(frozen=True) class Stage: name: str; ok: bool | None; text: str`
  - `studystate.tools(root, study) -> tuple[str | None, str | None]`
  - `studystate.stages(root, study, quick: bool = False) -> list[Stage]`
  - `studystate.next_step(root, study, st: list[Stage], tools: tuple) -> str`
  - `studystate.report(root, study, quick: bool = False) -> str`
  - `studystate.summary(root) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_studystate.py`:

```python
"""raft status: where a study stands, gate by gate, and the one command to run next."""
import json

import pytest

from conftest import commit_all
from raft import checker, cli, live, scaffold, studystate

REVIEW = {"study": "tiny", "builder_agent": "a", "attacker_agent": "b",
          "rounds": [{"round": 1, "attacks": [{"name": "zeros-1", "idea": "zeros", "blocked": True}]}]}


def pdf(root, study="tiny"):
    p = root / "papers" / f"{study}.pdf"
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(b"%PDF-1.4\n")


def by(st):
    return {s.name: s for s in st}


def test_a_fresh_draft_needs_extracting(tiny_study):
    root = tiny_study.parents[1]
    scaffold.new_study(root, "fresh", "Fresh", "10.1/x")
    pdf(root, "fresh")
    st = studystate.stages(root, "fresh", quick=True)
    assert by(st)["paper"].ok and by(st)["extraction"].ok is False and by(st)["extraction"].text == "not extracted"
    assert by(st)["approval"].text == "—"
    assert studystate.next_step(root, "fresh", st, (None, None)) == \
        "uv run raft prepare --study fresh --agent <claude-code|codex>"


def test_no_pdf(tiny_study):
    root = tiny_study.parents[1]
    st = studystate.stages(root, "tiny", quick=True)
    assert by(st)["paper"].ok is False
    assert studystate.next_step(root, "tiny", st, (None, None)) == "Put the paper's PDF at papers/tiny.pdf"


def test_tested_but_not_approved(tiny_study):
    root = tiny_study.parents[1]
    pdf(root)
    (tiny_study / "checker").mkdir(exist_ok=True)
    (tiny_study / "checker" / "review.json").write_text(json.dumps(REVIEW))
    (tiny_study / checker.APPROVAL).unlink()
    st = studystate.stages(root, "tiny", quick=True)
    assert by(st)["checker"].ok is None and by(st)["tested"].ok
    assert by(st)["approval"].ok is False and by(st)["approval"].text == "not approved"
    assert studystate.next_step(root, "tiny", st, (None, None)).startswith("uv run raft approve --study tiny")


def test_approved_and_committed_with_methods_but_no_runs(tiny_git_study):
    root = tiny_git_study.parents[1]
    pdf(root)
    (tiny_git_study / "checker").mkdir(exist_ok=True)
    (tiny_git_study / "checker" / "review.json").write_text(json.dumps(REVIEW))
    checker.record_approval(root, "tiny", approved_by={"name": "t", "email": "t@example.com"})
    commit_all(root, "approve")
    st = studystate.stages(root, "tiny", quick=True)
    assert by(st)["approval"].ok and by(st)["gaps"].text == "none"
    assert by(st)["runs"].ok is False and by(st)["runs"].text == "1 method(s), 0 run(s)"
    assert studystate.next_step(root, "tiny", st, (None, None)) == "uv run raft run --all --study tiny"


def test_the_last_stop_switches_the_refused_tool(tiny_study):
    root = tiny_study.parents[1]
    pdf(root)
    s = live.Session(root, "prepare", "tiny", agents={"builder": {"tool": "codex", "model": None},
                                                      "attacker": {"tool": "codex", "model": None}}, total=4)
    s.set_problem({"kind": "refused", "tool": "codex", "role": "attacker", "detail": "flagged",
                   "headline": "Codex refused the attack brief (its content filter flagged it)"})
    s.stop("raft: Codex refused the attack brief")
    assert studystate.tools(root, "tiny") == ("codex", "claude-code")
    text = studystate.report(root, "tiny", quick=True)
    assert "last stop: Codex refused the attack brief (its content filter flagged it)" in text
    assert text.rstrip().endswith("Next: uv run raft prepare --study tiny --agent codex --attacker claude-code")


def test_quick_never_runs_the_grader(tiny_study, monkeypatch):
    root = tiny_study.parents[1]
    pdf(root)
    monkeypatch.setattr(checker, "validate", lambda *a, **k: pytest.fail("ran the grader"))
    studystate.stages(root, "tiny", quick=True)
    monkeypatch.setattr(checker, "validate", lambda *a, **k: [])
    assert by(studystate.stages(root, "tiny"))["checker"].text.startswith("validates")


def test_cli_status(tiny_git_study, monkeypatch, capsys):
    pdf(tiny_git_study.parents[1])
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["status", "--study", "tiny", "--quick"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("tiny") and "✓ paper" in out and "Next: " in out
    assert cli.main(["status"]) == 0
    assert capsys.readouterr().out.startswith("tiny: ")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q tests/test_studystate.py`
Expected: FAIL with `AttributeError: module 'raft.studystate' has no attribute 'stages'`.

- [ ] **Step 3: Implement the rest of `raft/studystate.py`**

Replace the module docstring line and add, keeping `prepare_cmd` as it is:

```python
"""raft status: where a study stands, one line per gate, and the one command to run next."""
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import agents, checker, gaps, live, paths, provenance, runner, schema, validate

CORE = ("paper", "extraction", "checker", "tested", "approval")


@dataclass(frozen=True)
class Stage:
    name: str
    ok: bool | None  # None: not checked (or not reached)
    text: str


def _last(root: Path, study: str):
    found = [s for s in live.sessions(root, study) if s["kind"] == "prepare"]
    return found[0] if found else None


def tools(root, study: str) -> tuple:
    """The tools of the last prepare run, with a refused one swapped for the other tool."""
    s = _last(Path(root), study)
    if not s:
        return None, None
    a = (s["agents"].get("builder") or {}).get("tool")
    b = (s["agents"].get("attacker") or {}).get("tool")
    p = s.get("problem")
    if p and p["kind"] == "refused" and p["tool"] in agents.OTHER:
        if p["role"] == "attacker":
            b = agents.OTHER[p["tool"]]
        else:
            a = agents.OTHER[p["tool"]]
    return a, b


def _committed(root: Path, path: Path) -> bool:
    rel = provenance._rel(root, path)
    return (provenance._git(root, "ls-files", "--error-unmatch", rel) is not None
            and not provenance.is_dirty(root, [path]))


def _rounds(sd: Path) -> list:
    try:
        return schema.load("checker-review", sd / "checker" / "review.json")["rounds"]
    except schema.ContractError:
        return []


def stages(root, study: str, quick: bool = False) -> list[Stage]:
    root = Path(root)
    sd = root / "studies" / study
    paper = yaml.safe_load((sd / "paper.yaml").read_text()) or {}
    out, blocked = [], False

    def add(name, ok, text):
        nonlocal blocked
        if blocked:
            out.append(Stage(name, None, "—"))
            return
        out.append(Stage(name, ok, text))
        blocked = ok is False

    pdf = paper.get("pdf") or f"papers/{study}.pdf"
    has_pdf = (root / pdf).is_file()
    src = f"arXiv:{paper['arxiv']}" if paper.get("arxiv") else (paper.get("doi") or "no source")
    add("paper", has_pdf, f"{src}, " + ("PDF in papers/" if has_pdf else f"no PDF at {pdf}"))
    items = []
    if not (sd / "extraction.json").is_file():
        add("extraction", False, "not extracted")
    else:
        problems = validate.extraction(sd)
        if problems:
            add("extraction", False, f"{len(problems)} problem(s) in extraction.json")
        else:
            items = schema.load("extraction", sd / "extraction.json")["items"]
            add("extraction", True, f"{len(items)} items, {sum(i['missing'] for i in items)} missing")
    decoys = len(list((sd / "checker" / "attacks").glob("*.py")))
    if quick:
        add("checker", None, "not checked (--quick)")
    elif not blocked:
        try:
            holes = checker.validate(root, study, 1800.0, log=lambda s: None)
        except Exception as e:  # noqa: BLE001 (a broken checker is a finding, not a crash)
            holes = [f"{type(e).__name__}: {e}"]
        add("checker", not holes, f"validates ({decoys} decoys in checker/attacks/)" if not holes
            else f"{len(holes)} hole(s)")
    else:
        add("checker", None, "—")
    rounds = _rounds(sd)
    if not rounds:
        add("tested", False, "0 rounds")
    else:
        through = sum(not a["blocked"] for a in rounds[-1]["attacks"])
        add("tested", through == 0, f"{len(rounds)} round(s), last fully blocked" if not through
            else f"{len(rounds)} round(s), {through} decoy(s) passed the grader in the last")
    try:
        state = checker.approval_state(root, study)["state"]
    except schema.ContractError:
        state = "invalid"
    if state in ("approved", "approved-before-attacks"):
        done = _committed(root, sd / checker.APPROVAL)
        add("approval", done, "approved" if done else "approved, not committed yet")
    else:
        add("approval", False, {"missing": "not approved", "stale": "checker changed since approval",
                                "invalid": "checker-approval.json is invalid"}[state])
    missing = sum(i["missing"] for i in items)
    try:
        data = gaps.load(sd)
    except SystemExit:
        data, missing = None, -1
    if data:
        add("gaps", True, gaps.count_line(gaps.counts(data)))
    elif missing:
        add("gaps", False, "gaps.json is invalid" if missing < 0 else f"{missing} missing details not listed yet")
    else:
        add("gaps", True, "none")
    runs = list((sd / "runs").glob("*/manifest.json"))
    add("runs", bool(runs), f"{len(runner.methods(sd))} method(s), {len(runs)} run(s)")
    return out


def next_step(root, study: str, st: list[Stage], tools: tuple) -> str:
    root = Path(root)
    sd = root / "studies" / study
    paper = yaml.safe_load((sd / "paper.yaml").read_text()) or {}
    first = next((s for s in st if s.ok is False), None)
    name = first.name if first else None
    if name == "paper":
        return f"Put the paper's PDF at {paper.get('pdf') or f'papers/{study}.pdf'}"
    if name in ("extraction", "checker", "tested"):
        return prepare_cmd(study, *tools)
    if name == "approval":
        if first.text == "approved, not committed yet":
            return f'git add studies/{study}/{checker.APPROVAL} && git commit -m "Approve {study} checker"'
        return f"uv run raft approve --study {study}   (in your own terminal, then commit {checker.APPROVAL})"
    if name == "gaps":
        return f"uv run raft gaps --study {study}"
    if name == "runs":
        if not runner.methods(sd):
            return f"uv run raft implement <method> --study {study}   (one per method; see CONTRIBUTING.md)"
        return f"uv run raft run --all --study {study}"
    if paper.get("draft"):
        return f"Remove `draft: true` from studies/{study}/paper.yaml to publish it"
    if (sd / "gaps.json").is_file() and gaps.counts(gaps.load(sd))["open"]:
        return f"uv run raft gaps --study {study} --letter"
    return "uv run raft compare"


def report(root, study: str, quick: bool = False) -> str:
    root = Path(root)
    paper = yaml.safe_load((root / "studies" / study / "paper.yaml").read_text()) or {}
    st = stages(root, study, quick)
    first = next((s for s in st if s.ok is False), None)
    lines = [study + ("  (draft)" if paper.get("draft") else "")]
    for s in st:
        mark = "✓" if s.ok else ("✗" if s is first else "·")
        lines.append(f"{mark} {s.name:<11} {s.text}")
    last = _last(root, study)
    if last and last["state"] in ("stopped", "lost"):
        why = (last.get("problem") or {}).get("headline") or (
            "the run was interrupted (its process is gone)" if last["state"] == "lost"
            else (last["message"] or "stopped").splitlines()[0].removeprefix("raft: "))
        lines.append(f"  last stop: {why} ({last['updated_at'][:16].replace('T', ' ')})")
    lines.append(f"Next: {next_step(root, study, st, tools(root, study))}")
    return "\n".join(lines)


def summary(root) -> str:
    root = Path(root)
    rows = []
    for s in paths.studies(root, include_drafts=True):
        st = stages(root, s, quick=True)
        first = next((x for x in st if x.ok is False), None)
        rows.append(f"{s}: {first.name + ' — ' + first.text if first else 'ready'} → "
                    f"{next_step(root, s, st, tools(root, s))}")
    return "\n".join(rows) or "• no studies yet"
```

- [ ] **Step 4: The CLI and the docs**

In `raft/cli.py`, add the parser (after `doctor`):

```python
    stt = sub.add_parser("status", help="where a study stands, gate by gate, and the command to run next")
    stt.add_argument("--study")
    stt.add_argument("--quick", action="store_true", help="don't run the grader to check the checker")
```

and the dispatch (before the `doctor` dispatch):

```python
    if args.cmd == "status":
        from . import studystate
        if args.study:
            print(studystate.report(root, paths.resolve_study(root, args.study), args.quick))
        else:
            print(studystate.summary(root))
        return 0
```

In `README.md`, at the end of the "Add a paper with one command" section, add:

```markdown
Before the first step, `prepare` checks your tools: installed, logged in, and able to run one shell command
(`uv run raft doctor --agent codex --try` does the same by hand; the result is remembered for 12 hours, and
`--no-try` skips it). If a tool fails during a step (a refused brief, a broken shell tool, an error), `prepare` says
so in plain words, stops without a wasted retry, and prints the command to continue, often with the other tool.
`uv run raft status --study <study>` shows where a study stands and what to run next. Saved transcripts never hold
your home path.
```

In `AGENTS.md`, add two rows to the "Find your task" table, after the "build the site" row:

```markdown
| see where a study stands and what to run next | `uv run raft status --study <study>` |
| check that the agent tools are installed and logged in | `uv run raft doctor` |
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q tests/test_studystate.py tests/test_agent_docs.py tests/test_cli.py`
Expected: PASS.

- [ ] **Step 6: Run everything CI runs, then commit**

```bash
uv run pytest -q
uv run raft extract --validate --all-studies
uv run raft review --validate --all-studies
uv run raft gaps --validate --all-studies
uv run raft status --quick
```

Expected: all pass; `raft status` prints one line for `transduced-lm-2026` and one for `wu-2026-multimodal`.

```bash
git add raft/studystate.py raft/cli.py README.md AGENTS.md tests/test_studystate.py
git commit -m "raft status: where a study stands, gate by gate, and the one command to run next"
```

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

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

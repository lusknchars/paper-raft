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

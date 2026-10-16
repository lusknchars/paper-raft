"""Final-review fixes: a timed-out step is a timeout, not a tool error; redaction catches the home path before
punctuation and in its escaped form; the paid test task is announced; no flagged words in the fix brief."""
import json

from raft import agents, bench, doctor
from fake_tools import install
from test_prepare import env, run  # noqa: F401  (env is a fixture)


def test_a_timeout_after_a_recoverable_error_is_left_to_the_timeout_message():
    text = json.dumps({"type": "error", "message": "Reconnecting... 1/5"}) + "\n"
    assert agents.diagnose("codex", text, "", None) is None


def test_a_broken_shell_tool_is_still_named_when_the_step_times_out():
    p = agents.diagnose("codex", "", "ERROR codex_core::tools::router: error=timed out negotiating with the "
                        "code-mode host\n", None)
    assert p is not None and p.kind == "tool-broken"


def test_redaction_before_punctuation_and_in_escaped_form(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/someone")
    assert bench.redact(b"in /Users/someone. and /Users/someone: (/Users/someone), x") == b"in ~. and ~: (~), x"
    assert bench.redact(b'{"p": "\\/Users\\/someone\\/x"}') == b'{"p": "~\\/x"}'
    assert bench.redact(b"/Users/someone2 /Users/someone_b /Users/someone-c") == \
        b"/Users/someone2 /Users/someone_b /Users/someone-c"


def test_the_paid_test_task_is_announced(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    lines = []
    doctor.preflight(tmp_path, [("codex", None, False)], try_=True, log=lines.append)
    assert any("a few cents of your quota" in x for x in lines)
    lines.clear()
    doctor.preflight(tmp_path, [("codex", None, False)], try_=True, log=lines.append)  # cached now: nothing spent
    assert not any("quota" in x for x in lines)


def test_the_fix_brief_has_no_flagged_words(env, monkeypatch):  # noqa: F811
    root, cmd = env
    briefs = []
    real = agents.run
    monkeypatch.setattr(agents, "run", lambda agent, brief, *a, **k: briefs.append(brief.read_text()) or real(agent, brief, *a, **k))
    monkeypatch.setenv("FAKE_MODE", "holes")
    try:
        run(root, cmd)
    except SystemExit:
        pass
    fix = [b for b in briefs if "fix problem/" in b]
    assert fix and not any("Attacks" in b.split("**")[-2] for b in fix if b.count("**") >= 2)

"""AGENTS.md and CLAUDE.md are what agent tools read first: keep every command and path they name real."""
import re
from pathlib import Path

import pytest

from raft import cli

ROOT = Path(__file__).resolve().parents[1]


def subcommands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["-h"])
    return set(re.search(r"\{([a-z,-]+)\}", capsys.readouterr().out).group(1).split(","))


def test_every_raft_command_in_the_agent_docs_exists(capsys):
    known = subcommands(capsys)
    text = (ROOT / "AGENTS.md").read_text() + (ROOT / "CLAUDE.md").read_text()
    named = set(re.findall(r"raft ([a-z][a-z-]*)", text))
    assert named and named <= known, f"unknown raft commands in the agent docs: {sorted(named - known)}"


def test_claude_md_loads_agents_md():
    assert (ROOT / "CLAUDE.md").read_text().startswith("@AGENTS.md\n")


def test_the_claude_code_agents_and_skill_the_docs_name_exist():
    text = (ROOT / "CLAUDE.md").read_text()
    claude = ROOT / "adapters" / "claude-code" / ".claude"
    for name in re.findall(r"`(raft-[a-z]+)`", text):
        assert (claude / "agents" / f"{name}.md").is_file(), name
    assert (claude / "skills" / "reproduce-paper" / "SKILL.md").is_file()


def test_every_folder_in_the_layout_exists_or_is_written_by_raft():
    text = (ROOT / "AGENTS.md").read_text().split("## Layout", 1)[1]
    for path in re.findall(r"^- `([a-z/-]+/)`", text, re.M):
        assert (ROOT / path).is_dir() or path == "bench/results/", path

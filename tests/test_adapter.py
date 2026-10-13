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

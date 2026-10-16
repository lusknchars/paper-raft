"""prepare ends with the gaps line; the checker builder is told how to mark blocking gaps."""
from pathlib import Path

from raft import gaps, prepare
from test_gaps import ITEMS, with_missing
from test_prepare import env  # noqa: F401  (env is a fixture)

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_line_counts_gaps_and_blocking_ones(tiny_study):
    root = tiny_study.parents[1]
    assert gaps.prepare_line(root, "tiny") == "• no gaps: the extraction flags nothing missing"
    with_missing(tiny_study, *ITEMS)
    gaps.refresh(root, "tiny")
    gaps.set_blocks(root, "tiny", "corpus", "Table 2")
    assert gaps.prepare_line(root, "tiny") == "• 3 gaps (1 blocking a stricter check): uv run raft gaps --study tiny"


def test_prepare_ends_with_the_gaps_line(env):  # noqa: F811
    root, cmd = env
    lines = []
    prepare.prepare(root, study="tiny", agent="command", cmd=cmd, run_timeout=60, timeout=60, log=lines.append)
    assert lines[-1] == "• no gaps: the extraction flags nothing missing"
    assert (root / "studies" / "tiny" / "gaps.json").is_file()


def test_the_checker_builder_is_told_to_mark_blocking_gaps():
    text = (ROOT / "roles" / "checker-builder.md").read_text()
    assert 'uv run raft gaps --study {{study}} --blocks <item id> "<the check>"' in text


def test_agents_md_forbids_recording_answers():
    text = (ROOT / "AGENTS.md").read_text()
    assert "--blocks" in text and "Never record, edit or invent an author's answer" in text

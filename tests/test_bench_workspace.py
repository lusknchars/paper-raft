import subprocess
from pathlib import Path

import pytest

from raft import bench

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_is_blind(tiny_git_study, tmp_path):
    root = tiny_git_study.parents[1]
    (root / "papers").mkdir()
    (root / "papers" / "tiny.pdf").write_bytes(b"%PDF-1.4 tiny")
    ws = bench.make_workspace(root, "tiny", tmp_path / "ws", None)
    sd = ws / "studies" / "tiny"
    assert (sd / "paper.yaml").is_file() and (sd / "extraction.json").is_file()
    assert (sd / "problem" / "setup.py").is_file()
    assert not (sd / "problem" / "measure.py").exists() and not (sd / "problem" / "reference.json").exists()
    assert (sd / "methods").is_dir() and not any((sd / "methods").iterdir())
    assert (ws / "papers" / "tiny.pdf").read_bytes() == b"%PDF-1.4 tiny"
    assert not (ws / "roles").exists() and not (ws / "pyproject.toml").exists()
    log = subprocess.run(["git", "log", "--format=%s"], cwd=ws, capture_output=True, text=True, check=True).stdout
    assert log.strip() == "workspace"


def test_setup_overlay_lands_and_skips_git(tiny_git_study, tmp_path):
    root = tiny_git_study.parents[1]
    setup = tmp_path / "my-setup"
    (setup / ".codex").mkdir(parents=True)
    (setup / "AGENTS.md").write_text("Think step by step.")
    (setup / ".codex" / "config.toml").write_text("model = 'x'")
    (setup / ".git").mkdir()
    (setup / ".git" / "HEAD").write_text("ref: refs/heads/main")
    ws = bench.make_workspace(root, "tiny", tmp_path / "ws", setup)
    assert (ws / "AGENTS.md").read_text() == "Think step by step."
    assert (ws / ".codex" / "config.toml").is_file()
    info = bench.setup_info(setup)
    assert info["files"] == [".codex/config.toml", "AGENTS.md"] and len(info["hash"]) == 64
    assert bench.setup_info(None) is None


def test_setup_with_studies_is_refused(tiny_git_study, tmp_path):
    setup = tmp_path / "bad"
    (setup / "studies").mkdir(parents=True)
    with pytest.raises(SystemExit, match="must not contain studies/"):
        bench.make_workspace(tiny_git_study.parents[1], "tiny", tmp_path / "ws", setup)


def test_setup_must_be_a_folder(tiny_git_study, tmp_path):
    with pytest.raises(SystemExit, match="is not a folder"):
        bench.make_workspace(tiny_git_study.parents[1], "tiny", tmp_path / "ws", tmp_path / "nope")


def test_brief_names_method_and_python(tiny_git_study):
    text = bench.render_brief(tiny_git_study.parents[1], "tiny", "exact", "/tmp/x/bin/python")
    assert text.strip() == "# bench tiny exact at studies/tiny python /tmp/x/bin/python"


def test_real_role_mentions_the_essentials():
    text = (ROOT / "roles" / "bench-implementer.md").read_text()
    for needle in ("{{method}}", "{{study_dir}}/methods/{{method}}/", "{{python}}", "solve(setup)", "numpy and scipy"):
        assert needle in text


def test_require_clean(tiny_git_study):
    root = tiny_git_study.parents[1]
    bench.require_clean(root, "tiny")
    (tiny_git_study / "problem" / "setup.py").write_text("# changed\n")
    with pytest.raises(SystemExit, match="uncommitted changes"):
        bench.require_clean(root, "tiny")

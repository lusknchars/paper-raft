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

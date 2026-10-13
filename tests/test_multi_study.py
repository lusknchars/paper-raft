import shutil

import pytest
import yaml

from conftest import make_tiny_study
from raft import cli, compare, paths


@pytest.fixture
def two_studies(tmp_path, monkeypatch):
    sd = make_tiny_study(tmp_path)
    shutil.copytree(sd, sd.parent / "tiny2")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    return tmp_path


def test_new_study_scaffold(two_studies):
    assert cli.main(["new", "smith-2020", "--title", "A paper", "--doi", "10.1/x"]) == 0
    d = two_studies / "studies" / "smith-2020"
    assert {p.name for p in (d / "problem").iterdir()} == {"setup.py", "measure.py", "reference.json"}
    paper = yaml.safe_load((d / "paper.yaml").read_text())
    assert paper["draft"] is True and paper["pdf"] == "papers/smith-2020.pdf" and paper["doi"] == "10.1/x"
    assert "smith-2020" not in paths.studies(two_studies)
    assert paths.resolve_study(two_studies, "smith-2020") == "smith-2020"


@pytest.mark.parametrize("sid, msg", [("tiny", "already exists"), ("Bad_Id", "lowercase")])
def test_new_study_rejects(two_studies, sid, msg):
    with pytest.raises(SystemExit, match=msg):
        cli.main(["new", sid, "--title", "t", "--doi", "d"])


def test_all_studies_validate_and_run(two_studies, capsys):
    assert cli.main(["extract", "--validate", "--all-studies"]) == 0
    assert cli.main(["run", "--all", "--all-studies", "--n", "4"]) == 0
    out = capsys.readouterr().out
    assert "── tiny\n" in out and "── tiny2\n" in out
    assert (two_studies / "studies" / "tiny2" / "runs" / "exact-n4").is_dir()


def test_all_studies_reports_bad_params_per_study(two_studies, capsys):
    assert cli.main(["run", "--all", "--all-studies", "--n", "1"]) == 1
    out = capsys.readouterr().out
    assert "✗ tiny: n must be at least 2" in out and "✗ tiny2: n must be at least 2" in out


def test_all_studies_skips_drafts(two_studies, capsys):
    cli.main(["new", "draft-one", "--title", "t", "--doi", "d"])
    capsys.readouterr()
    assert cli.main(["review", "--validate", "--all-studies"]) == 0
    assert "draft-one" not in capsys.readouterr().out
    assert [s["id"] for s in compare.build(two_studies, None)["studies"]] == ["tiny", "tiny2"]


@pytest.mark.parametrize("argv", [["implement", "exact", "--all-studies"], ["run", "exact", "--all-studies"],
                                  ["review", "--validate", "--all-studies", "--study", "tiny"]])
def test_all_studies_rejects_single_study_commands(two_studies, argv):
    with pytest.raises(SystemExit):
        cli.main(argv)


def test_two_studies_need_a_choice(two_studies):
    with pytest.raises(SystemExit, match="pass --study"):
        cli.main(["review", "--validate"])


def test_all_studies_with_only_drafts_is_a_clean_no_op(tmp_path, monkeypatch, capsys):
    sd = make_tiny_study(tmp_path)
    (sd / "paper.yaml").write_text((sd / "paper.yaml").read_text() + "draft: true\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["repro", "--all-studies"]) == 0
    assert "no studies to check yet" in capsys.readouterr().out

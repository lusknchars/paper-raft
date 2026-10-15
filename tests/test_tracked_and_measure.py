import shutil

from conftest import commit_all, make_tiny_study

from raft import provenance, runner

MEASURE_WITH_GRADER = '''
from graders import scale


def measure(setup, fields, reference):
    return {"samples": {}, "errors": {"k": scale.K}, "tolerance": 1.0, "pass": True}
'''


def test_tracked_hash_ignores_untracked_and_excluded(tiny_git_study):
    root = tiny_git_study.parents[1]
    (root / ".gitignore").write_text("__pycache__/\n.DS_Store\n")
    commit_all(root, "ignore")
    problem = tiny_git_study / "problem"
    before = provenance.tracked_hash(problem)
    (problem / ".DS_Store").write_bytes(b"x")
    assert provenance.tracked_hash(problem) == before
    (problem / "setup.py").write_text((problem / "setup.py").read_text() + "\n# edit\n")
    assert provenance.tracked_hash(problem) != before


def test_tracked_hash_excludes_a_top_level_folder(tiny_git_study):
    root = tiny_git_study.parents[1]
    checker = tiny_git_study / "checker"
    (checker / "transcripts").mkdir(parents=True)
    (checker / "NOTE.md").write_text("note")
    (checker / "transcripts" / "a.jsonl").write_text("1")
    commit_all(root, "checker")
    before = provenance.tracked_hash(checker, exclude=("transcripts",))
    (checker / "transcripts" / "a.jsonl").write_text("2")
    commit_all(root, "transcript")
    assert provenance.tracked_hash(checker, exclude=("transcripts",)) == before


def test_tracked_hash_without_git_uses_every_file(tiny_study):
    problem = tiny_study / "problem"
    before = provenance.tracked_hash(problem)
    (problem / "extra.py").write_text("x = 1\n")
    assert provenance.tracked_hash(problem) != before
    assert provenance.tracked_hash(tiny_study / "missing") == provenance.tracked_hash(tiny_study / "missing2")


def test_each_study_loads_its_own_graders(tmp_path):
    sd = make_tiny_study(tmp_path)
    other = sd.parent / "tiny2"
    shutil.copytree(sd, other)
    for d, k in ((sd, 1), (other, 2)):
        (d / "problem" / "graders").mkdir()
        (d / "problem" / "graders" / "__init__.py").write_text("")
        (d / "problem" / "graders" / "scale.py").write_text(f"K = {k}\n")
        (d / "problem" / "measure.py").write_text(MEASURE_WITH_GRADER)
    a = runner.load_measure(sd / "problem").measure(None, None, None)["errors"]["k"]
    b = runner.load_measure(other / "problem").measure(None, None, None)["errors"]["k"]
    assert (a, b) == (1, 2)


def test_runs_use_graders(tmp_path):
    sd = make_tiny_study(tmp_path)
    (sd / "problem" / "graders").mkdir()
    (sd / "problem" / "graders" / "__init__.py").write_text("")
    (sd / "problem" / "graders" / "scale.py").write_text("K = 7\n")
    (sd / "problem" / "measure.py").write_text(MEASURE_WITH_GRADER)
    _, results = runner.execute(sd, "exact", {"n": 4}, 60)
    assert results["status"] == "ok" and results["errors"] == {"k": 7}

import subprocess

from raft import provenance


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def make_repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    m = tmp_path / "methods" / "a"
    m.mkdir(parents=True)
    (m / "solver.py").write_text("def solve(s):\n    return {}\n")
    (tmp_path / "other.txt").write_text("x")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    return m


def test_inputs_hash_tracks_params_and_files(tmp_path):
    p = tmp_path / "problem"
    p.mkdir()
    (p / "setup.py").write_text("A = 1\n")
    h1 = provenance.inputs_hash({"re": 100}, p)
    assert len(h1) == 64
    assert provenance.inputs_hash({"re": 100}, p) == h1
    assert provenance.inputs_hash({"re": 1000}, p) != h1
    (p / "__pycache__").mkdir()
    (p / "__pycache__" / "setup.cpython-312.pyc").write_bytes(b"junk")
    assert provenance.inputs_hash({"re": 100}, p) == h1
    (p / "setup.py").write_text("A = 2\n")
    assert provenance.inputs_hash({"re": 100}, p) != h1


def test_git_shas(tmp_path):
    m = make_repo(tmp_path)
    head = provenance.git_sha(tmp_path)
    assert len(head) == 40
    assert provenance.method_sha(tmp_path, m) == head
    (tmp_path / "other.txt").write_text("y")
    git(tmp_path, "commit", "-qam", "unrelated")
    assert provenance.git_sha(tmp_path) != head
    assert provenance.method_sha(tmp_path, m) == head


def test_dirty_detection(tmp_path):
    m = make_repo(tmp_path)
    assert provenance.is_dirty(tmp_path, [m]) is False
    (m / "solver.py").write_text("changed")
    assert provenance.is_dirty(tmp_path, [m]) is True


def test_outside_git(tmp_path):
    assert provenance.git_sha(tmp_path) == "unknown"
    assert provenance.method_sha(tmp_path, tmp_path) is None
    assert provenance.is_dirty(tmp_path, [tmp_path]) is True


def test_package_versions():
    v = provenance.package_versions()
    assert set(v) == {"numpy", "scipy"} and all(v.values())

import json

from conftest import commit_all
from raft import compare, runner


def _review(sd, sha, verdict="verified"):
    (sd / "reviews").mkdir(exist_ok=True)
    (sd / "reviews" / "exact.json").write_text(json.dumps({
        "method": "exact", "reviewed_sha": sha, "reviewer_agent": "test:reviewer#exact",
        "verdict": verdict, "discrepancies": []}))


def test_build_structure_and_verified(tiny_git_study):
    root = tiny_git_study.parents[1]
    manifest, _ = runner.run_one(tiny_git_study, "exact", {"n": 8}, timeout=60)
    _review(tiny_git_study, manifest["method_sha"])
    data = compare.build(root, "https://github.com/acme/raft")
    s = data["studies"][0]
    assert s["id"] == "tiny" and s["headline"] == {"n": 8}
    m = s["methods"][0]
    assert m["name"] == "exact" and m["headline_status"] == "verified"
    assert s["counts"] == {"verified": 1}
    run = m["runs"][0]
    assert run["code_url"] == f"https://github.com/acme/raft/blob/{manifest['git_sha']}/studies/tiny/methods/exact/solver.py"


def test_compare_status_follows_review_commit(tiny_git_study):
    root = tiny_git_study.parents[1]
    manifest, _ = runner.run_one(tiny_git_study, "exact", {"n": 8}, timeout=60)
    _review(tiny_git_study, manifest["method_sha"])
    solver = tiny_git_study / "methods" / "exact" / "solver.py"
    solver.write_text(solver.read_text() + "\n# tweak\n")
    commit_all(root, "edit solver after review")
    runner.run_one(tiny_git_study, "exact", {"n": 8}, timeout=60)
    m = compare.build(root, None)["studies"][0]["methods"][0]
    assert m["headline_status"] == "unverified"
    assert m["runs"][0]["code_url"] is None


def test_no_runs(tiny_study):
    s = compare.build(tiny_study.parents[1], None)["studies"][0]
    assert s["methods"][0]["runs"] == [] and s["methods"][0]["headline_status"] == "no run"


def test_write_site_files(tiny_study, tmp_path):
    out = tmp_path / "site"
    compare.write_site(compare.build(tiny_study.parents[1], None), out)
    assert {p.name for p in out.iterdir()} >= {"index.html", "app.js", "style.css", "data.json", "data.js"}
    assert (out / "data.js").read_text().startswith("window.RAFT_DATA = ")
    html = (out / "index.html").read_text()
    assert 'src="data.js"' in html and "fetch(" not in (out / "app.js").read_text()


def test_repo_url_normalises(monkeypatch, tmp_path):
    monkeypatch.setenv("RAFT_REPO_URL", "git@github.com:lusknchars/paper-raft.git")
    assert compare.repo_url(tmp_path) == "https://github.com/lusknchars/paper-raft"


def test_compare_includes_flows_and_writes_them(tiny_git_study, tmp_path):
    root = tiny_git_study.parents[1]
    runner.run_one(tiny_git_study, "exact", {"n": 8}, timeout=60)
    data = compare.build(root, None)
    assert data["flows"]["tiny"]["study"] == "tiny"
    out = tmp_path / "site"
    compare.write_site(data, out)
    assert json.loads((out / "flows" / "tiny.json").read_text())["study"] == "tiny"
    assert "window.RAFT_DATA" in (out / "data.js").read_text()
    assert (out / "flow" / "flow.js").is_file() and not (out / "flow" / "watch.html").exists()


def test_site_data_has_an_empty_bench(tiny_git_study):
    from raft import compare
    data = compare.build(tiny_git_study.parents[1], None)
    assert data["bench"] == {}


def test_site_data_lists_bench_entries(tiny_git_study, tmp_path):
    import shlex
    import sys

    from raft import bench, compare
    root = tiny_git_study.parents[1]
    agent = tmp_path / "agent.py"
    agent.write_text(
        "import sys\nfrom pathlib import Path\n"
        "d = Path(sys.argv[2]) / 'studies' / 'tiny' / 'methods' / sys.argv[3]\n"
        "d.mkdir(parents=True)\n"
        "(d / 'solver.py').write_text('import numpy as np\\n\\n\\ndef solve(setup):\\n'\n"
        "    '    xs = np.array([i / (setup.n - 1) for i in range(setup.n)])\\n    return {\"y\": xs * xs}\\n')\n")
    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(agent))} {{brief}} {{workspace}} {{method}}"
    bench.run_bench(root, "tiny", "command", cmd=cmd, label="site test", log=lambda s: None)
    data = compare.build(root, "https://github.com/o/r")
    (row,) = data["bench"]["tiny"]["full"]
    assert row["label"] == "site test" and row["passed"] == 2 and row["expected"] == 2
    assert row["url"].startswith("https://github.com/o/r/tree/")


def test_site_data_has_the_checker_state(tiny_git_study):
    from raft import compare
    (study,) = compare.build(tiny_git_study.parents[1], None)["studies"]
    assert study["checker"]["state"] == "approved-before-attacks"


def test_site_never_carries_the_live_page(tiny_study, tmp_path):
    out = tmp_path / "site"
    compare.write_site(compare.build(tiny_study.parents[1], None), out)
    assert (out / "flow" / "flow.js").is_file() and not list(out.rglob("live.*"))

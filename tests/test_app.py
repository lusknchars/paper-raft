"""The data and routes behind `raft app`: everything from the lab's own files, ids checked, the grader never run."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from raft import app, checker, cli, paperraft, scaffold, watch


@pytest.fixture
def lab(tiny_git_study):
    root = tiny_git_study.parents[1]
    scaffold.new_study(root, "fresh", "Fresh Draft", "10.1/fresh")
    return root


def test_app_data_lists_drafts_and_never_runs_the_grader(lab, monkeypatch):
    monkeypatch.setattr(checker, "validate", lambda *a, **k: pytest.fail("ran the grader"))
    d = app.app_data(lab)
    by = {s["id"]: s for s in d["studies"]}
    assert set(by) == {"tiny", "fresh"} and by["fresh"]["draft"] is True and by["tiny"]["draft"] is False
    assert [g["name"] for g in by["tiny"]["stages"]][:2] == ["paper", "extraction"]
    assert by["tiny"]["next"] and by["tiny"]["methods"] == 1
    assert set(d["counts"]) == {"studies", "running", "verified_runs", "bench_entries", "open_gaps"}
    assert d["counts"]["studies"] == 2 and d["sessions"] == [] and d["warning"] is None


def test_a_broken_study_does_not_break_the_app(lab):
    (lab / "studies" / "tiny" / "problem" / "reference.json").write_text("{broken")
    d = app.app_data(lab)
    assert {s["id"] for s in d["studies"]} == {"tiny", "fresh"} and d["warning"]


def test_study_detail_for_a_study_and_a_draft(lab):
    t = app.study_detail(lab, "tiny")
    assert [r["name"] for r in t["results"]] == ["exact"] and t["results"][0]["status"] == "no run"
    assert t["checker"]["note"] is None and t["checker"]["rounds"] == [] and t["gaps_file"] is None
    assert t["flow"]["study"] == "tiny"
    f = app.study_detail(lab, "fresh")
    assert f["results"] == [] and f["letter"] is None and f["bench"] == {"full": [], "partial": []}


@pytest.fixture
def server(lab):
    srv = watch.make_server(lab, None, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def get(srv, path, host=None):
    h, p = srv.server_address
    req = urllib.request.Request(f"http://{h}:{p}{path}", headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, None, b""


def test_routes(server, monkeypatch):
    s, ctype, body = get(server, "/app.html")
    assert s == 200 and ctype.startswith("text/html") and b"/app/app.js" in body
    s, _, body = get(server, "/app.json")
    assert s == 200 and {x["id"] for x in json.loads(body)["studies"]} == {"tiny", "fresh"}
    s, _, body = get(server, "/app/study/fresh.json")
    assert s == 200 and json.loads(body)["id"] == "fresh"
    monkeypatch.setattr(paperraft, "answer", lambda pid, **kw: {"found": False, "brief": None, "offline": True,
                                                                 "stale": False, "id": pid})
    s, _, body = get(server, "/paperraft/2608.27428.json")
    assert s == 200 and json.loads(body)["id"] == "2608.27428"


@pytest.mark.parametrize("path", ["/app/study/nope.json", "/app/study/../tiny.json", "/app/study/%2e%2e/tiny.json",
                                  "/app/study/tiny.json/", "/paperraft/junk.json", "/paperraft/../2608.27428.json",
                                  "/paperraft/2608.27428v2.json"])
def test_bad_ids_are_404(server, path):
    assert get(server, path)[0] == 404


def test_the_host_check_still_holds(server):
    assert get(server, "/app.json", host="evil.example")[0] == 403


def test_cli_app_opens_the_right_page(tiny_git_study, monkeypatch):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    seen = []
    monkeypatch.setattr(watch, "serve", lambda root, study, port, open_browser, path="/": seen.append(path))
    assert cli.main(["app", "--no-open"]) == 0
    assert cli.main(["app", "--study", "tiny"]) == 0
    assert cli.main(["app", "--paper", "https://paperaft.vercel.app/papers/2608.27428/"]) == 0
    assert seen == ["/app.html", "/app.html#/study/tiny", "/app.html#/paper/2608.27428"]
    with pytest.raises(SystemExit):
        cli.main(["app", "--paper", "junk"])
    with pytest.raises(SystemExit):
        cli.main(["app", "--study", "nope"])

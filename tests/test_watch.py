import json
import threading
import urllib.error
import urllib.request

import pytest

from conftest import commit_all
from raft import flow, runner, watch


@pytest.fixture
def server(tiny_git_study):
    srv = watch.make_server(tiny_git_study.parents[1], "tiny", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, tiny_git_study
    srv.shutdown()
    srv.server_close()


def _get(srv, path):
    host, port = srv.server_address
    with urllib.request.urlopen(f"http://{host}:{port}{path}") as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def test_watch_binds_localhost_and_serves_flow_and_progress(server):
    srv, sd = server
    assert srv.server_address[0] == "127.0.0.1"
    status, ctype, body = _get(srv, "/flow.json")
    assert status == 200 and ctype.startswith("application/json") and json.loads(body)["study"] == "tiny"
    assert json.loads(_get(srv, "/progress.json")[2]) == {}
    runner.run_one(sd, "exact", {"n": 8}, timeout=60)
    assert json.loads(_get(srv, "/progress.json")[2])["exact-n8"]["state"] == "finished"
    status, ctype, body = _get(srv, "/")
    assert b"mountFlow" in body and ctype.startswith("text/html")
    assert _get(srv, "/flow/flow.js")[1].startswith("text/javascript")


@pytest.mark.parametrize("path", ["/../../pyproject.toml", "/flow/../../cli.py", "/nope.txt",
                                  "/../contracts/flow.schema.json", "/flow/../../contracts/flow.schema.json",
                                  "/%2e%2e/contracts/flow.schema.json"])
def test_watch_serves_nothing_outside_the_template(server, path):
    srv, _ = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(srv, path)
    assert e.value.code == 404


def test_read_progress_skips_broken_files(tiny_study):
    d = tiny_study / "runs" / ".progress"
    d.mkdir(parents=True)
    (d / "a.json").write_text('{"state": "running"}')
    (d / "b.json").write_text("{not json")
    assert watch.read_progress(tiny_study) == {"a": {"state": "running"}}


def test_export_refuses_uncommitted_changes_and_writes_assets(tiny_git_study, tmp_path):
    root = tiny_git_study.parents[1]
    (tiny_git_study / "paper.yaml").write_text((tiny_git_study / "paper.yaml").read_text() + "# edit\n")
    with pytest.raises(SystemExit):
        flow.export(root, "tiny", tmp_path / "x.flow.json", None, None)
    commit_all(root, "edit")
    flow.export(root, "tiny", tmp_path / "x.flow.json", tmp_path / "assets", None)
    assert json.loads((tmp_path / "x.flow.json").read_text())["study"] == "tiny"
    assert (tmp_path / "assets" / "paper-raft-flow" / "flow.js").is_file()
    assert (tmp_path / "assets" / flow.THREE / "build" / "three.module.js").is_file()


def test_watch_rejects_foreign_host_header(server):
    import http.client
    srv, _ = server
    host, port = srv.server_address
    for h, code in (("evil.example", 403), (f"localhost:{port}", 200), (f"127.0.0.1:{port}", 200)):
        conn = http.client.HTTPConnection(host, port)
        conn.putrequest("GET", "/progress.json", skip_host=True)
        conn.putheader("Host", h)
        conn.endheaders()
        assert conn.getresponse().status == code
        conn.close()


def test_watch_reports_flow_errors_and_keeps_serving(server):
    srv, sd = server
    setup = sd / "problem" / "setup.py"
    setup.write_text(setup.read_text() + "\ndef expand(params):\n    raise RuntimeError('broken')\n")
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(srv, "/flow.json")
    assert e.value.code == 500 and e.value.headers.get("Content-Type").startswith("application/json")
    assert "RuntimeError" in json.loads(e.value.read())["error"]
    assert _get(srv, "/progress.json")[0] == 200


def test_watch_nul_byte_path_is_404(server):
    import socket
    srv, _ = server
    port = srv.server_address[1]
    with socket.create_connection(srv.server_address) as sock:
        sock.settimeout(5)
        sock.sendall(b"GET /a\x00b HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n\r\n" % port)
        data = b""
        while chunk := sock.recv(4096):
            data += chunk
    assert b" 404 " in data.split(b"\r\n", 1)[0]


from raft import live


def test_watch_without_a_study_serves_the_live_page_and_sessions(tiny_git_study):
    root = tiny_git_study.parents[1]
    srv = watch.make_server(root, None, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert json.loads(_get(srv, "/live.json")[2]) == []
        s = live.Session(root, "prepare", "tiny", agents={}, total=1)
        got = json.loads(_get(srv, "/live.json")[2])
        assert got[0]["id"] == s.path.stem and got[0]["state"] == "running"
        assert b"mountLive" in _get(srv, "/")[2]
        assert _get(srv, "/flow/live.js")[1].startswith("text/javascript")
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(srv, "/flow.json")
        assert e.value.code == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_watch_with_a_study_filters_sessions(server):
    srv, sd = server
    live.Session(sd.parents[1], "prepare", "other", agents={}, total=1)
    assert json.loads(_get(srv, "/live.json")[2]) == []


def test_background_server_survives_a_taken_port(tiny_git_study, capsys):
    root = tiny_git_study.parents[1]
    first = watch.background(root, port=0, open_browser=False)
    try:
        assert watch.background(root, port=first.server_address[1], open_browser=False) is None
        assert "in use" in capsys.readouterr().out
    finally:
        first.shutdown()
        first.server_close()

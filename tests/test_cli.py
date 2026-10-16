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


def test_prepare_watch_flag_starts_the_server(in_tiny, monkeypatch, capsys):
    from raft import prepare, watch
    started = []
    monkeypatch.setattr(watch, "background", lambda root, **kw: started.append(kw) or None)
    monkeypatch.setattr(prepare, "prepare", lambda root, **kw: "tiny")
    assert cli.main(["prepare", "--study", "tiny", "--agent", "codex", "--watch"]) == 0
    assert started == [{}]
    assert cli.main(["prepare", "--study", "tiny", "--agent", "codex"]) == 0
    assert started == [{}] and "watch live: uv run raft watch" in capsys.readouterr().out


def test_watch_server_outlives_the_command_then_shuts_down(in_tiny, monkeypatch):
    from raft import prepare, watch
    monkeypatch.setattr(cli, "LIVE_GRACE_S", 0.3)
    log = []

    class Srv:
        def shutdown(self):
            log.append("shutdown")

        def server_close(self):
            log.append("close")
    srv = Srv()
    monkeypatch.setattr(watch, "background", lambda root, **kw: srv)
    real_sleep = cli.time.sleep
    monkeypatch.setattr(cli.time, "sleep", lambda t: log.append(("grace", t)) or real_sleep(0))
    monkeypatch.setattr(prepare, "prepare", lambda root, **kw: log.append("body"))
    assert cli.main(["prepare", "--study", "tiny", "--agent", "codex", "--watch"]) == 0
    assert log == ["body", ("grace", 0.3), "shutdown", "close"]


def test_watch_server_outlives_a_failing_command(in_tiny, monkeypatch):
    from raft import prepare, watch
    monkeypatch.setattr(cli, "LIVE_GRACE_S", 0)
    log = []

    class Srv:
        def shutdown(self):
            log.append("shutdown")

        def server_close(self):
            log.append("close")
    monkeypatch.setattr(watch, "background", lambda root, **kw: Srv())

    def boom(root, **kw):
        raise RuntimeError("agent died")
    monkeypatch.setattr(prepare, "prepare", boom)
    with pytest.raises(RuntimeError):
        cli.main(["prepare", "--study", "tiny", "--agent", "codex", "--watch"])
    assert log == ["shutdown", "close"]


def test_real_watch_server_still_answers_after_the_body_ends(in_tiny, monkeypatch):
    import urllib.request
    from raft import prepare, watch
    monkeypatch.setattr(cli, "LIVE_GRACE_S", 0)
    made, real = [], watch.background

    def start(root, **kw):
        srv = real(root, port=0, open_browser=False)
        made.append(srv)
        return srv
    monkeypatch.setattr(watch, "background", start)
    seen = []

    def during_grace(t):
        port = made[0].server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/live.json", timeout=5) as r:
            seen.append(r.status)
    monkeypatch.setattr(cli.time, "sleep", during_grace)
    monkeypatch.setattr(prepare, "prepare", lambda root, **kw: "tiny")
    assert cli.main(["prepare", "--study", "tiny", "--agent", "codex", "--watch"]) == 0
    assert seen == [200]
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{made[0].server_address[1]}/live.json", timeout=2)

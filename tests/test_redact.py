"""Saved transcripts never carry the builder's home path."""
import json

from raft import bench
from test_prepare import env, run  # noqa: F401  (env is a fixture)


def test_redact_replaces_the_home_path(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/someone")
    data = json.dumps({"cmd": "cat /Users/someone/paper-raft/x.py", "cwd": "/Users/someone"}).encode() + b"\n"
    assert bench.redact(data) == json.dumps({"cmd": "cat ~/paper-raft/x.py", "cwd": "~"}).encode() + b"\n"


def test_redact_needs_a_real_home(monkeypatch):
    for home in ("/", ""):
        monkeypatch.setenv("HOME", home)
        assert bench.redact(b"/usr/bin/x /Users/a .") == b"/usr/bin/x /Users/a ."


def test_redact_leaves_a_longer_name_alone(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/someone")
    assert bench.redact(b'"/Users/someone2/x" "/Users/someone"') == b'"/Users/someone2/x" "~"'


def test_trim_copy_redacts_before_trimming(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", "/Users/someone")
    src = tmp_path / "t.jsonl"
    src.write_bytes(b'{"p": "/Users/someone/a"}\n' * 40)
    bench.trim_copy(src, tmp_path / "out.jsonl", limit=200)
    out = (tmp_path / "out.jsonl").read_bytes()
    assert b"/Users/someone" not in out and b'"~/a"' in out and b"raft_trimmed_bytes" in out


def test_redact_file_and_finding_unredacted_files(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", "/Users/someone")
    p = tmp_path / "x.jsonl"
    p.write_bytes(b'{"p": "/Users/someone/x"}\n')
    assert bench.transcripts_with_home([p, tmp_path / "gone.jsonl"]) == [p]
    assert bench.redact_file(p) is True and bench.redact_file(p) is False
    assert bench.transcripts_with_home([p]) == []


def test_prepare_redacts_the_studys_old_transcripts(env, monkeypatch):  # noqa: F811
    root, cmd = env
    monkeypatch.setenv("HOME", "/Users/someone")
    t = root / "studies" / "tiny" / "checker" / "transcripts"
    t.mkdir(parents=True)
    (t / "old-1.jsonl").write_bytes(b'{"p": "/Users/someone/x"}\n')
    run(root, cmd)
    assert (t / "old-1.jsonl").read_bytes() == b'{"p": "~/x"}\n'

import json
import os
import subprocess
import sys

from raft import live, schema

AGENTS = {"builder": {"tool": "codex", "model": None}}


def make(tmp_path, **kw):
    seen = []
    s = live.Session(tmp_path, "prepare", "tiny", agents=AGENTS, total=kw.pop("total", 4), interval=0,
                     on_write=seen.append, **kw)
    return s, seen


def test_session_file_is_valid_and_walks_through_steps(tmp_path):
    s, seen = make(tmp_path, title="T", arxiv="2608.04234")
    assert s.path.parent == tmp_path / ".raft" / "live" and s.path.name.startswith("prepare-tiny-")
    s.skip("intake", "Intake", "studies/tiny")
    s.begin("extract-1", "Extract", agent="builder", timeout_s=60)
    s.set_activity("extract-1", ["reading the PDF"], "boom")
    s.end("extract-1", detail="valid")
    s.finish("uv run raft approve --study tiny")
    for d in seen:
        schema.check("live", d)
    d = json.loads(s.path.read_text())
    assert d["state"] == "finished" and d["next"] == "uv run raft approve --study tiny"
    assert d["units"] == {"done": 2, "total": 4}
    ex = d["steps"][1]
    assert ex["state"] == "done" and ex["activity"][-1]["text"] == "reading the PDF" and ex["stderr_tail"] == "boom"
    assert isinstance(ex["wall_s"], (int, float))


def test_units_retry_partial_and_drop(tmp_path):
    s, _ = make(tmp_path, total=3)
    s.begin("a", "A")
    s.set_partial(0.5)
    assert s.data["units"]["done"] == 0.5
    s.end("a", state="failed")
    s.add_total(1)
    assert s.data["units"] == {"done": 1, "total": 4}
    s.add_total(-10)
    assert s.data["units"]["total"] == 1  # never below done


def test_stop_marks_running_steps_failed(tmp_path):
    s, _ = make(tmp_path)
    s.begin("build-1", "Build checker")
    s.stop("raft: the build agent changed checker-approval.json")
    d = json.loads(s.path.read_text())
    assert d["state"] == "stopped" and d["steps"][0]["state"] == "failed" and d["message"].startswith("raft: the build")


def test_throttled_writes_still_write_state_changes(tmp_path):
    s = live.Session(tmp_path, "prepare", "tiny", agents=AGENTS, total=2, interval=60)
    s.begin("a", "A")
    s.set_activity("a", ["one"], None)   # throttled: not on disk yet
    assert json.loads(s.path.read_text())["steps"][0]["activity"] == []
    s.end("a")                           # a state change always writes
    assert json.loads(s.path.read_text())["steps"][0]["activity"][0]["text"] == "one"


def test_sessions_lists_newest_first_skips_junk_and_marks_lost(tmp_path):
    a, _ = make(tmp_path)
    b, _ = make(tmp_path)
    b.finish("next")
    d = tmp_path / ".raft" / "live"
    (d / "broken.json").write_text("{half")
    (d / "old.json").write_text(json.dumps({"kind": "prepare"}))
    dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    lost = json.loads(a.path.read_text()) | {"pid": int(dead.stdout)}
    (d / "prepare-tiny-00000000T000000000000Z.json").write_text(json.dumps(lost))
    got = live.sessions(tmp_path)
    assert [g["id"] for g in got][:2] == [b.path.stem, a.path.stem]
    assert {g["state"] for g in got} == {"finished", "running", "lost"}
    assert all(g["study"] == "tiny" for g in got) and live.sessions(tmp_path, study="other") == []


def test_no_live_dir_means_no_sessions(tmp_path):
    assert live.sessions(tmp_path) == []
    assert os.getpid() == live.Session(tmp_path, "bench", "tiny", agents=AGENTS, total=1).data["pid"]

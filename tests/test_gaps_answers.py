"""Recording what the authors said: only the owner, only with a source, and never a private answer's text."""
import pytest

from raft import cli, gaps
from test_gaps import ITEMS, with_missing


@pytest.fixture
def root(tiny_study):
    with_missing(tiny_study, *ITEMS)
    gaps.refresh(tiny_study.parents[1], "tiny")
    return tiny_study.parents[1]


def entry(root, gid):
    return next(g for g in gaps.load(root / "studies" / "tiny")["gaps"] if g["id"] == gid)


def test_a_published_answer_is_stored_with_its_credit(root):
    gaps.answer(root, "tiny", "corpus", by="Vésteinn Snæbjarnarson", source="email, 2026-10-20",
                publish=True, text="  We used the “GRCh38” corpus.\n", today="2026-10-21")
    g = entry(root, "corpus")
    assert g["status"] == "answered"
    assert g["answer"] == {"text": "We used the “GRCh38” corpus.", "by": "Vésteinn Snæbjarnarson",
                           "source": "email, 2026-10-20", "recorded_on": "2026-10-21"}
    assert "Snæbjarnarson" in (root / "studies" / "tiny" / "gaps.json").read_text()  # stored unescaped
    assert gaps.validate(root / "studies" / "tiny") == []


def test_a_private_answer_stores_no_text(root):
    gaps.answer(root, "tiny", "ties", by="A. Author", source="email", publish=False, note="our assumption matched",
                today="2026-10-21")
    g = entry(root, "ties")
    assert g["status"] == "answered_private"
    assert g["answer"] == {"by": "A. Author", "source": "email", "recorded_on": "2026-10-21",
                           "note": "our assumption matched"}


def test_decline(root):
    gaps.decline(root, "tiny", "corpus", by="A. Author", source="email", today="2026-10-21")
    g = entry(root, "corpus")
    assert g["status"] == "declined" and "text" not in g["answer"]


@pytest.mark.parametrize("kw, msg", [
    ({"publish": True, "text": None}, "--publish needs --from"),
    ({"publish": True, "text": "  \n "}, "--publish needs --from"),
    ({"publish": False, "text": "secret"}, "--private stores no answer text"),
    ({"publish": True, "text": "x", "note": "n"}, "--note goes with --private"),
])
def test_bad_combinations_are_refused(root, kw, msg):
    with pytest.raises(SystemExit, match=msg):
        gaps.answer(root, "tiny", "corpus", by="a", source="b", **kw)
    assert entry(root, "corpus")["status"] == "open"


def test_unknown_and_already_answered_gaps_are_refused(root):
    with pytest.raises(SystemExit, match="no gap 'nope'"):
        gaps.answer(root, "tiny", "nope", by="a", source="b", publish=True, text="x")
    gaps.decline(root, "tiny", "corpus", by="a", source="b")
    with pytest.raises(SystemExit, match="already declined"):
        gaps.answer(root, "tiny", "corpus", by="a", source="b", publish=True, text="x")


@pytest.mark.parametrize("call", [
    lambda r: gaps.answer(r, "tiny", "corpus", by="a", source="b", publish=True, text="x"),
    lambda r: gaps.decline(r, "tiny", "corpus", by="a", source="b"),
    lambda r: gaps.mark_asked(r, "tiny"),
])
def test_answers_refuse_inside_an_agent_session(root, monkeypatch, call):
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(SystemExit, match="inside an agent session"):
        call(root)
    assert entry(root, "corpus")["status"] == "open"


def test_cli_answer_and_decline(tiny_git_study, monkeypatch, capsys, tmp_path):
    with_missing(tiny_git_study, *ITEMS)
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["gaps", "--study", "tiny"]) == 0
    reply = tmp_path / "reply.txt"
    reply.write_text("We used GRCh38.\n")
    assert cli.main(["gaps", "--study", "tiny", "--answer", "corpus", "--from", str(reply), "--by", "A. Author",
                     "--source", "email, 2026-10-20", "--publish"]) == 0
    assert "✓ corpus: answered" in capsys.readouterr().out
    assert cli.main(["gaps", "--study", "tiny", "--decline", "ties", "--by", "A. Author", "--source", "email"]) == 0
    with pytest.raises(SystemExit):
        cli.main(["gaps", "--study", "tiny", "--answer", "edge", "--by", "a", "--source", "b"])  # neither flag
    with pytest.raises(SystemExit):
        cli.main(["gaps", "--study", "tiny", "--answer", "edge", "--private"])  # no --by / --source

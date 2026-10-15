import pytest
import yaml

from raft import arxiv, cli

RECORD = b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
<GetRecord><record><metadata>
<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
<id>2608.27428</id>
<version version="v1"><date>Mon, 31 Aug 2026 17:59:01 GMT</date><size>900kb</size></version>
<version version="v2"><date>Tue, 8 Sep 2026 10:00:00 GMT</date><size>910kb</size></version>
<title>Stochastic Estimation of
  Transduced Language Models</title>
<authors>V\xc3\xa9steinn Sn\xc3\xa6bjarnarson, Samuel Kiegeland, Manuel de Prada Corral, Ryan Cotterell and Tim Vieira</authors>
<license>http://creativecommons.org/licenses/by-sa/4.0/</license>
<abstract>  We estimate prefix probabilities.
</abstract>
</arXivRaw></metadata></record></GetRecord></OAI-PMH>"""

MISSING = b"""<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
<error code="idDoesNotExist">No matching identifier</error></OAI-PMH>"""

PDF = b"%PDF-1.5 tiny"


class FakeNet:
    def __init__(self, replies):
        self.replies, self.urls, self.t, self.sleeps = list(replies), [], 0.0, []

    def opener(self, url, limit):
        self.urls.append(url)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r[: limit + 1]

    def fetcher(self):
        return arxiv.Fetcher(opener=self.opener, clock=lambda: self.t, sleep=self.sleeps.append)


def test_parse_record():
    r = arxiv.parse_record(RECORD)
    assert r["title"] == "Stochastic Estimation of Transduced Language Models"
    assert r["authors"] == ["Vésteinn Snæbjarnarson", "Samuel Kiegeland", "Manuel de Prada Corral",
                            "Ryan Cotterell", "Tim Vieira"]
    assert r["year"] == 2026 and r["version"] == "v2" and r["abstract"] == "We estimate prefix probabilities."
    assert r["license"] == "http://creativecommons.org/licenses/by-sa/4.0/"


def test_slug():
    assert arxiv.slug(["Vésteinn Snæbjarnarson"], 2026, "Stochastic Estimation of X") == "snaebjarnarson-2026-stochastic"
    assert arxiv.slug(["Ann Lee"], 2020, "On the Size of It") == "lee-2020-size"


def test_intake_writes_a_draft_study(tiny_study):
    root = tiny_study.parents[1]
    net = FakeNet([RECORD, PDF])
    d = arxiv.intake(root, "2608.27428", brief="https://paperaft.vercel.app/papers/2608.27428/", fetcher=net.fetcher())
    assert d.name == "snaebjarnarson-2026-stochastic"
    paper = yaml.safe_load((d / "paper.yaml").read_text())
    assert paper["draft"] is True and paper["arxiv"] == "2608.27428"
    assert paper["doi"] == "10.48550/arXiv.2608.27428" and paper["pdf"] == f"papers/{d.name}.pdf"
    assert paper["pdf_url"] == "https://arxiv.org/pdf/2608.27428v2"
    assert paper["citation"] == ("Snæbjarnarson, Kiegeland, de Prada Corral et al. (2026). Stochastic Estimation of "
                                 "Transduced Language Models. arXiv:2608.27428.")
    assert paper["authors"][0] == "Vésteinn Snæbjarnarson" and paper["brief_url"].endswith("2608.27428/")
    assert (root / "papers" / f"{d.name}.pdf").read_bytes() == PDF
    assert net.urls[0].startswith("https://export.arxiv.org/oai2?") and "metadataPrefix=arXivRaw" in net.urls[0]
    assert net.sleeps == [3.0]


def test_intake_refuses_existing_id_before_downloading(tiny_study):
    net = FakeNet([RECORD, PDF])
    with pytest.raises(SystemExit, match="already exists"):
        arxiv.intake(tiny_study.parents[1], "2608.27428", study_id="tiny", fetcher=net.fetcher())
    assert len(net.urls) == 1


@pytest.mark.parametrize("replies, msg", [
    ([MISSING], "no record for that id"),
    ([b"<html>Service unavailable</html>"], "unexpected reply from arXiv"),
    ([OSError("network down")], "could not reach arXiv"),
    ([RECORD, b"<html>not a pdf</html>"], "not a PDF"),
    ([RECORD, b"%PDF" + b"x" * (arxiv.MAX_PDF + 10)], "larger than 50 MB"),
])
def test_intake_errors_leave_nothing_behind(tiny_study, replies, msg):
    root = tiny_study.parents[1]
    before = sorted(p.name for p in (root / "studies").iterdir())
    with pytest.raises(SystemExit, match=msg):
        arxiv.intake(root, "2608.27428", fetcher=FakeNet(replies).fetcher())
    assert sorted(p.name for p in (root / "studies").iterdir()) == before
    assert not (root / "papers").exists()


def test_bad_id():
    with pytest.raises(SystemExit, match="new-style arXiv id"):
        arxiv.intake(None, "2608.27428v1")


def test_cli_new_needs_title_without_arxiv(tiny_git_study, monkeypatch):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    with pytest.raises(SystemExit):
        cli.main(["new", "smith-2020"])


def test_cli_new_arxiv(tiny_git_study, monkeypatch, capsys):
    root = tiny_git_study.parents[1]
    monkeypatch.chdir(root)
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    net = FakeNet([RECORD, PDF])
    made = net.fetcher()  # built before the patch below replaces arxiv.Fetcher
    monkeypatch.setattr(arxiv, "Fetcher", lambda: made)
    assert cli.main(["new", "--arxiv", "2608.27428", "--id", "tl-2026"]) == 0
    assert (root / "studies" / "tl-2026" / "paper.yaml").is_file()
    assert "raft prepare --study tl-2026" in capsys.readouterr().out

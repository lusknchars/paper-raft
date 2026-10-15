"""Fetch a paper's record and PDF from arXiv's official endpoints only (OAI-PMH and arxiv.org/pdf)."""
import json
import re
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import yaml

from . import scaffold

OAI = "https://export.arxiv.org/oai2?verb=GetRecord&identifier=oai:arXiv.org:{id}&metadataPrefix=arXivRaw"
PDF_URL = "https://arxiv.org/pdf/{id}{version}"
NS = {"oai": "http://www.openarchives.org/OAI/2.0/", "raw": "http://arxiv.org/OAI/arXivRaw/"}
USER_AGENT = "PaperRaft/0.1 (+https://github.com/lusknchars/paper-raft)"
MAX_PDF = 50 * 1024 * 1024
SPACING = 3.0
ID_RE = re.compile(r"\d{4}\.\d{4,5}")
_LETTERS = str.maketrans({"æ": "ae", "Æ": "ae", "ø": "o", "Ø": "o", "ß": "ss", "đ": "d", "ł": "l", "Ł": "l",
                          "þ": "th", "Þ": "th", "œ": "oe", "Œ": "oe"})


class Fetcher:
    """One request at a time, at least SPACING seconds apart, as arXiv asks."""

    def __init__(self, opener=None, clock=time.monotonic, sleep=time.sleep):
        self.opener, self.clock, self.sleep, self.last = opener or self._urlopen, clock, sleep, None

    @staticmethod
    def _urlopen(url: str, limit: int) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read(limit + 1)

    def get(self, url: str, limit: int = 5_000_000) -> bytes:
        if self.last is not None:
            wait = SPACING - (self.clock() - self.last)
            if wait > 0:
                self.sleep(wait)
        try:
            return self.opener(url, limit)
        except OSError as e:
            raise SystemExit(f"raft: could not reach arXiv ({e})") from None
        finally:
            self.last = self.clock()


_TEX_LETTERS = {"ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "aa": "å", "AA": "Å", "ss": "ß", "o": "ø", "O": "Ø",
                "l": "ł", "L": "Ł", "i": "ı"}
_TEX_ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304",
                ".": "\u0307", "c": "\u0327", "v": "\u030c", "u": "\u0306", "H": "\u030b", "r": "\u030a",
                "k": "\u0328", "d": "\u0323", "b": "\u0331"}
_LETTER = r"(ae|AE|oe|OE|aa|AA|ss|o|O|l|L|i)(?![A-Za-z])"


def _detex(text: str) -> str:
    """arXiv metadata writes accents in TeX (Sn{\\ae}bjarnarson, J\\"org); turn them into Unicode."""
    def accent(m):
        base = m.group(2)
        base = "i" if base == "\\i" else base.lstrip("\\")
        return base + _TEX_ACCENTS[m.group(1)]
    text = re.sub(r"\\(['`^\"~=.cvuHrkdb])\s*\{\s*(\\i(?![A-Za-z])|[A-Za-z])\s*\}", accent, text)
    text = re.sub(r"\\(['`^\"~=.])\s*(\\i(?![A-Za-z])|[A-Za-z])", accent, text)
    text = re.sub(r"\\([cvuHrkdb])\s+([A-Za-z])", accent, text)
    text = re.sub(r"\{\\" + _LETTER + r"\s*\}", lambda m: _TEX_LETTERS[m.group(1)], text)
    text = re.sub(r"\\" + _LETTER + r"\s?", lambda m: _TEX_LETTERS[m.group(1)], text)
    prev = None
    while prev != text:
        prev, text = text, re.sub(r"\{([^{}\\$]*)\}", r"\1", text)
    return unicodedata.normalize("NFC", text)


def _split_authors(text: str) -> list[str]:
    return [a.strip() for a in re.split(r",\s*(?:and\s+)?|\s+and\s+", text) if a.strip()]


def parse_record(xml: bytes) -> dict:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise SystemExit("raft: unexpected reply from arXiv (not an OAI-PMH record)") from None
    err = root.find("oai:error", NS)
    if err is not None:
        raise SystemExit(f"raft: arXiv has no record for that id ({err.get('code')}: {(err.text or '').strip()})")
    raw = root.find(".//raw:arXivRaw", NS)
    if raw is None:
        raise SystemExit("raft: unexpected reply from arXiv (no arXivRaw record)")

    def text(tag):
        return _detex(" ".join((raw.findtext(f"raw:{tag}", "", NS) or "").split()))

    versions = raw.findall("raw:version", NS)
    if not versions:
        raise SystemExit("raft: unexpected reply from arXiv (no versions)")
    first = parsedate_to_datetime(versions[0].findtext("raw:date", "", NS))
    return {"id": text("id"), "title": text("title"), "authors": _split_authors(text("authors")),
            "abstract": text("abstract"), "license": text("license") or None,
            "version": versions[-1].get("version"), "year": first.year}


def _ascii(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.translate(_LETTERS)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", plain)


def _surname(author: str) -> str:
    parts = author.split()
    return parts[-1] if parts else author


def slug(authors: list[str], year: int, title: str) -> str:
    word = next((_ascii(w) for w in title.split() if len(_ascii(w)) > 3), "paper")
    return f"{_ascii(_surname(authors[0])) if authors else 'anon'}-{year}-{word}"


def _citation(rec: dict, arxiv_id: str) -> str:
    names = [_surname(a) if " de " not in f" {a} " else a.split(" ", 1)[1] for a in rec["authors"]]
    who = ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")
    return f"{who} ({rec['year']}). {rec['title']}. arXiv:{arxiv_id}."


def intake(root: Path, arxiv_id: str, *, study_id: str | None = None, brief: str | None = None,
           fetcher: Fetcher | None = None) -> Path:
    if not ID_RE.fullmatch(arxiv_id or ""):
        raise SystemExit("raft: --arxiv takes a new-style arXiv id such as 2608.27428 (no version suffix)")
    root = Path(root)
    f = fetcher or Fetcher()
    rec = parse_record(f.get(OAI.format(id=arxiv_id)))
    sid = study_id or slug(rec["authors"], rec["year"], rec["title"])
    if (root / "studies" / sid).exists():
        raise SystemExit(f"raft: study {sid!r} already exists; pass --id to pick another name")
    pdf_url = PDF_URL.format(id=arxiv_id, version=rec["version"])
    pdf = f.get(pdf_url, limit=MAX_PDF)
    if len(pdf) > MAX_PDF:
        raise SystemExit("raft: the PDF is larger than 50 MB; download it yourself into papers/")
    if not pdf.startswith(b"%PDF-"):
        raise SystemExit(f"raft: {pdf_url} is not a PDF")
    doi = f"10.48550/arXiv.{arxiv_id}"
    d = scaffold.new_study(root, sid, rec["title"], doi)
    citation = _citation(rec, arxiv_id)
    paper = yaml.safe_load((d / "paper.yaml").read_text())
    paper.update({"authors": rec["authors"], "citation": citation, "arxiv": arxiv_id, "pdf_url": pdf_url,
                  "license": rec["license"], "abstract": rec["abstract"]})
    if brief:
        paper["brief_url"] = brief
    (d / "paper.yaml").write_text(yaml.safe_dump(paper, sort_keys=False, allow_unicode=True))
    ref = json.loads((d / "problem" / "reference.json").read_text())
    ref["citation"] = citation
    (d / "problem" / "reference.json").write_text(json.dumps(ref, indent=2, ensure_ascii=False) + "\n")
    (root / "papers").mkdir(exist_ok=True)
    (root / "papers" / f"{sid}.pdf").write_bytes(pdf)
    return d

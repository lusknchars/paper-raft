"""raft gaps: page-referenced questions to a paper's authors for the details it leaves out, and their answers.

Built from extraction.json's missing items, deterministically. Paper Raft never sends anything and never looks up
contact details: the owner sends the letter and records each answer in their own terminal."""
import json
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

from . import paths, schema

FILE = "gaps.json"
STATUSES = ("open", "asked", "answered", "answered_private", "declined", "resolved")
UNANSWERED = ("open", "asked")
REPLIED = ("answered", "answered_private", "declined")
LETTER_SMALL_CAP = 8
ASK = {"parameter": "What did you use?", "result": "What did you use?", "method": "How is this done?",
       "equation": "How is this done?", "boundary_condition": "What happens here?"}


def _today() -> str:
    return date.today().isoformat()


def _study_dir(root: Path, study: str) -> Path:
    return Path(root) / "studies" / study


def _sentence(text: str) -> str:
    return text.strip().rstrip(".") + "."


def question(item: dict) -> str:
    return f"{_sentence(item['text'])} {ASK[item['kind']]} We assumed: {_sentence(item['assumption'])[:-1]}. Is that right?"


def load(sd: Path) -> dict | None:
    path = Path(sd) / FILE
    if not path.is_file():
        return None
    try:
        return schema.load("gaps", path)
    except schema.ContractError as e:
        raise SystemExit(f"raft: {e}\nFix studies/{Path(sd).name}/{FILE} by hand (or delete it to start over).") from None


def save(sd: Path, data: dict) -> None:
    schema.check("gaps", data)
    (Path(sd) / FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _extraction(sd: Path, study: str) -> dict:
    if not (sd / "extraction.json").is_file():
        raise SystemExit(f"raft: studies/{study} has no extraction.json yet; run `uv run raft extract --study {study}` "
                         "first")
    try:
        return schema.load("extraction", sd / "extraction.json")
    except schema.ContractError as e:
        raise SystemExit(f"raft: {e}") from None


def refresh(root: Path, study: str, today: str | None = None) -> dict:
    """Create or update gaps.json. Asked questions stay as sent; replies are never touched; open or asked gaps whose
    item is no longer missing become resolved."""
    sd = _study_dir(root, study)
    today = today or _today()
    ext = _extraction(sd, study)
    old = {g["id"]: g for g in (load(sd) or {"gaps": []})["gaps"]}
    out = []
    for item in ext["items"]:
        if not item["missing"]:
            continue
        g = old.pop(item["id"], None)
        if g is None or g["status"] in ("open", "resolved"):
            g = {**(g or {}), "id": item["id"], "page": item["page"], "kind": item["kind"], "question": question(item),
                 "assumption": item["assumption"], "status": "open"}
            g.pop("resolved_on", None)
        out.append(g)
    for g in old.values():
        if g["status"] in UNANSWERED:
            g["status"], g["resolved_on"] = "resolved", today
        out.append(g)
    data = {"study": study, "gaps": out}
    save(sd, data)
    return data


def validate(sd: Path) -> list[str]:
    sd = Path(sd)
    if not (sd / FILE).is_file():
        return []
    try:
        data = schema.load("gaps", sd / FILE)
    except schema.ContractError as e:
        return [str(e)]
    problems = []
    if data["study"] != sd.name:
        problems.append(f"{FILE}: study is {data['study']!r}, expected {sd.name!r}")
    try:
        items = {i["id"]: i for i in schema.load("extraction", sd / "extraction.json")["items"]}
    except schema.ContractError as e:
        return problems + [f"{FILE} needs a valid extraction.json: {e}"]
    seen = set()
    for g in data["gaps"]:
        if g["id"] in seen:
            problems.append(f"{FILE}: duplicate gap {g['id']!r}")
        seen.add(g["id"])
        item = items.get(g["id"])
        if g["status"] in UNANSWERED and not (item and item["missing"]):
            problems.append(f"{FILE}: {g['id']!r} is {g['status']} but is not a missing item in extraction.json "
                            f"(run `uv run raft gaps --study {sd.name}` to refresh)")
    return problems


def _entry(data: dict, gid: str, study: str) -> dict:
    for g in data["gaps"]:
        if g["id"] == gid:
            return g
    raise SystemExit(f"raft: no gap {gid!r} in studies/{study}/{FILE} "
                     f"(have: {', '.join(g['id'] for g in data['gaps']) or 'none'})")


def set_blocks(root: Path, study: str, gid: str, text: str) -> dict:
    """Name the check a missing detail keeps out of the grader. Agents may do this (the checker builder does)."""
    sd = _study_dir(root, study)
    data = load(sd) or refresh(root, study)
    _entry(data, gid, study)["blocks"] = text.strip()
    save(sd, data)
    return data


def _owner_only(what: str) -> None:
    from .checker import AGENT_ENV
    if any(os.environ.get(k) for k in AGENT_ENV):
        raise SystemExit(f"raft: gaps {what} refuses to run inside an agent session (Claude Code or Codex): only the "
                         "owner records what was sent to the authors and what they said, in their own terminal")


def _need(sd: Path, study: str) -> dict:
    data = load(sd)
    if data is None:
        raise SystemExit(f"raft: studies/{study} has no {FILE} yet; run `uv run raft gaps --study {study}` first")
    return data


def site_url(repo: str | None) -> str | None:
    env = os.environ.get("RAFT_SITE_URL")
    if env:
        return env.rstrip("/") + "/"
    m = re.fullmatch(r"https://github\.com/([^/]+)/([^/]+)", repo or "")
    return f"https://{m.group(1).lower()}.github.io/{m.group(2)}/" if m else None


def selection(data: dict) -> tuple[list[dict], list[dict], int]:
    """What the letter asks: every unanswered gap that blocks a check, then the first few others."""
    waiting = [g for g in data["gaps"] if g["status"] in UNANSWERED]
    blocking = [g for g in waiting if g.get("blocks")]
    small = [g for g in waiting if not g.get("blocks")]
    return blocking, small[:LETTER_SMALL_CAP], max(0, len(small) - LETTER_SMALL_CAP)


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def letter(root: Path, study: str, repo: str | None = None) -> str:
    """Plain text for the owner to paste into an email. Changes nothing."""
    sd = _study_dir(root, study)
    data = _need(sd, study)
    blocking, small, more = selection(data)
    if not blocking and not small:
        raise SystemExit(f"raft: no unanswered gaps in studies/{study}/{FILE}")
    paper = yaml.safe_load((sd / "paper.yaml").read_text()) or {}
    names = [n for n in paper.get("authors") or [] if n]
    site = site_url(repo)
    out = [f"Dear {_names(names)}," if names else "Dear authors,", "",
           f"We reproduced parts of “{paper.get('title') or study}” with Paper Raft, an open harness where agents "
           "implement a paper's methods and the harness grades their code against the paper's own claims. Some "
           "details we needed are not in the paper; for each one we made an assumption, listed below with its page."]
    if site:
        out.append(f"The study: {site}#study/{study} · how it was built: {site}#flow/{study}")
    n = 0

    def section(title: str, gs: list[dict]) -> None:
        nonlocal n
        if not gs:
            return
        out.extend(["", title, ""])
        for g in gs:
            n += 1
            out.append(f"{n}. p. {g['page']}: {g['question']}")
            if g.get("blocks"):
                out.append(f"   An answer would let us check: {g['blocks']}")
    section("What blocks a stricter check", blocking)
    section("Smaller details, if you have time", small)
    if more:
        where = f"{site}#study/{study}/gaps" if site else f"studies/{study}/{FILE} in the Paper Raft repository"
        out.append(f"…and {more} more: {where}")
    out += ["", "With your permission we'll publish your answers in the study, credited to you. If you'd rather not, "
                "we'll use them only to check our own assumptions.", "", "Thank you,", ""]
    return "\n".join(out)


def mark_asked(root: Path, study: str, today: str | None = None) -> list[str]:
    """Record that the letter's questions were sent: the same selection `letter` prints."""
    _owner_only("--mark-asked")
    sd = _study_dir(root, study)
    data = _need(sd, study)
    blocking, small, _ = selection(data)
    if not blocking and not small:
        raise SystemExit(f"raft: no unanswered gaps in studies/{study}/{FILE}")
    today = today or _today()
    for g in blocking + small:
        g["status"], g["asked_on"] = "asked", today
    save(sd, data)
    return [g["id"] for g in blocking + small]

def _reply(root: Path, study: str, gid: str, what: str):
    _owner_only(what)
    sd = _study_dir(root, study)
    data = _need(sd, study)
    g = _entry(data, gid, study)
    if g["status"] not in UNANSWERED:
        raise SystemExit(f"raft: {gid!r} is already {g['status']}; correct studies/{study}/{FILE} by hand if needed")
    return sd, data, g


def answer(root: Path, study: str, gid: str, *, by: str, source: str, publish: bool, text: str | None = None,
           note: str | None = None, today: str | None = None) -> dict:
    """Record an author's answer. Published answers keep their text; private ones never do."""
    text = text.strip() if text else None
    if publish and not text:
        raise SystemExit("raft: --publish needs --from <file> holding the author's answer")
    if not publish and text:
        raise SystemExit("raft: --private stores no answer text; drop --from (use --note for your own words)")
    if publish and note:
        raise SystemExit("raft: --note goes with --private; a published answer speaks for itself")
    sd, data, g = _reply(root, study, gid, "--answer")
    g["status"] = "answered" if publish else "answered_private"
    g["answer"] = {**({"text": text} if publish else {}), "by": by.strip(), "source": source.strip(),
                   "recorded_on": today or _today(), **({"note": note.strip()} if note else {})}
    save(sd, data)
    return g


def decline(root: Path, study: str, gid: str, *, by: str, source: str, today: str | None = None) -> dict:
    sd, data, g = _reply(root, study, gid, "--decline")
    g["status"] = "declined"
    g["answer"] = {"by": by.strip(), "source": source.strip(), "recorded_on": today or _today()}
    save(sd, data)
    return g

def published(sd: Path) -> list[dict]:
    data = load(sd)
    return [g for g in data["gaps"] if g["status"] == "answered"] if data else []


def answers_section(root: Path, source: str) -> str:
    gs = published(_study_dir(root, source))
    if not gs:
        return ""
    lines = ["", f"**Author answers.** This study is a stricter version of `studies/{source}`. Its authors answered "
                 f"these gaps (`studies/{source}/{FILE}`). Write each as not missing, with the paper's page, `quote: \"\"` "
                 "and the `answer` reference shown, and use the answer instead of the old assumption:", ""]
    for g in gs:
        a = g["answer"]
        lines.append(f"- `{g['id']}` (p. {g['page']}), answered by {a['by']} ({a['source']}): {a['text']} "
                     f"→ `\"answer\": \"{source}/{FILE}#{g['id']}\"`")
    return "\n".join(lines) + "\n"


def counts(data: dict) -> dict:
    c = Counter(g["status"] for g in data["gaps"])
    return {"gaps": len(data["gaps"]) - c["resolved"], **{s: c[s] for s in STATUSES},
            "blocking": sum(1 for g in data["gaps"] if g["status"] in UNANSWERED and g.get("blocks"))}


def count_line(c: dict) -> str:
    line = f"{c['gaps']} gaps · {c['open']} open · {c['asked']} asked · {c['answered'] + c['answered_private']} answered"
    if c["declined"]:
        line += f" · {c['declined']} declined"
    return line + f" · {c['blocking']} blocking a stricter check"


def listing(data: dict, study: str) -> str:
    rows = [f"{g['status']:<17} p. {g['page']:<4} {g['id']}" + (f"  · blocks: {g['blocks']}" if g.get("blocks") else "")
            for g in data["gaps"]]
    return "\n".join(rows + ["", count_line(counts(data)),
                             f"Next: uv run raft gaps --study {study} --letter"])


def summary_text(root: Path) -> str:
    lines = []
    for s in paths.studies(root, include_drafts=True):
        sd = _study_dir(root, s)
        if not (sd / FILE).is_file():
            continue
        try:
            lines.append(f"{s}: {count_line(counts(load(sd)))}")
        except SystemExit:
            lines.append(f"{s}: ✗ {FILE} is invalid (run `uv run raft gaps --validate --study {s}`)")
    return "\n".join(lines) or "• no study has a gaps.json yet. Start one: uv run raft gaps --study <study>"

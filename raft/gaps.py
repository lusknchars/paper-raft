"""raft gaps: page-referenced questions to a paper's authors for the details it leaves out, and their answers.

Built from extraction.json's missing items, deterministically. Paper Raft never sends anything and never looks up
contact details: the owner sends the letter and records each answer in their own terminal."""
import json
from collections import Counter
from datetime import date
from pathlib import Path

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

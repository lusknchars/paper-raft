"""Cross-file checks the JSON Schemas cannot express."""
from pathlib import Path

from . import schema


def _ids(study_dir: Path) -> set[str]:
    try:
        return {i["id"] for i in schema.load("extraction", study_dir / "extraction.json")["items"]}
    except schema.ContractError:
        return set()


def _answer_problems(study_dir: Path, item: dict) -> list[str]:
    """An item that cites an author's answer must be filled (not missing), and the answer must be published."""
    ref, iid = item["answer"], item["id"]
    if item["missing"]:
        return [f"extraction.json: {iid!r} is missing but cites an answer ({ref})"]
    src, gid = ref.split("/gaps.json#")
    path = study_dir.parent / src / "gaps.json"
    if not path.is_file():
        return [f"extraction.json: {iid!r} cites {ref}, but there is no studies/{src}/gaps.json"]
    try:
        entries = {g["id"]: g for g in schema.load("gaps", path)["gaps"]}
    except schema.ContractError as e:
        return [f"extraction.json: {iid!r} cites {ref}: {e}"]
    if gid not in entries:
        return [f"extraction.json: {iid!r} cites {ref}, but there is no gap {gid!r} there"]
    if entries[gid]["status"] != "answered":
        return [f"extraction.json: {iid!r} cites {ref}, which is not a published answer "
                f"(status {entries[gid]['status']})"]
    return []


def extraction(study_dir: Path) -> list[str]:
    try:
        data = schema.load("extraction", study_dir / "extraction.json")
    except schema.ContractError as e:
        return [str(e)]
    seen, problems = set(), []
    for item in data["items"]:
        if item["id"] in seen:
            problems.append(f"extraction.json: duplicate id {item['id']!r}")
        seen.add(item["id"])
        if "answer" in item:
            problems += _answer_problems(study_dir, item)
    return problems


def methods_and_reviews(study_dir: Path) -> list[str]:
    ids, problems, authors = _ids(study_dir), [], {}
    for d in sorted(p for p in (study_dir / "methods").glob("*") if p.is_dir()):
        rel = f"methods/{d.name}/method.json"
        try:
            m = schema.load("method", d / "method.json")
        except schema.ContractError as e:
            problems.append(str(e))
            continue
        if m["name"] != d.name:
            problems.append(f"{rel}: name {m['name']!r} does not match folder {d.name!r}")
        problems += [f"{rel}: implements unknown extraction id {i!r}" for i in m["implements"] if i not in ids]
        authors[d.name] = m["author_agent"]
    for f in sorted((study_dir / "reviews").glob("*.json")):
        rel = f"reviews/{f.name}"
        try:
            r = schema.load("review", f)
        except schema.ContractError as e:
            problems.append(str(e))
            continue
        if r["method"] not in authors:
            problems.append(f"{rel}: no method named {r['method']!r}")
            continue
        if r["reviewer_agent"] == authors[r["method"]]:
            problems.append(f"{rel}: reviewer is the method's implementer")
        problems += [f"{rel}: discrepancy cites unknown extraction id {d['extraction_id']!r}"
                     for d in r["discrepancies"] if d["extraction_id"] not in ids]
    return problems

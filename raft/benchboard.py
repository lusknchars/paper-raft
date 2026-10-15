"""Score, rank and print bench entries: pure functions over entry dicts (raft/contracts/bench-entry.schema.json)."""
import math
from pathlib import Path

from . import runner, schema

AGG = {"max": max, "min": min, "mean": lambda v: sum(v) / len(v)}
FOOTNOTE = ("*Reported by the agent's tool, not verified. Scores are graded by the study's own measure, "
            "in a copy the agent never saw, and are not reviewed.")


def aggregate_metrics(specs: list[dict], methods: list[dict]) -> list[dict]:
    """The study's paper.yaml metrics over every run that has the error key (same rule as the flow view)."""
    out = []
    for s in specs:
        vals = []
        for m in methods:
            for r in m["runs"]:
                errs = r.get("errors") or {}
                if s["from"] in errs and all(r["params"].get(k) == v for k, v in s.get("where", {}).items()):
                    v = float(errs[s["from"]])
                    vals.append(v if math.isfinite(v) else 1e300)
        out.append({"key": s["key"], "label": s["label"], "note": s["note"], "format": s["format"],
                    "value": AGG[s["agg"]](vals) if vals else None})
    return out


def score_counts(methods: list[dict]) -> dict:
    return {"passed": sum(bool(r["pass"]) for m in methods for r in m["runs"]),
            "expected": sum(len(m["runs"]) for m in methods)}


def totals(entry: dict) -> dict:
    ms = entry["methods"]

    def total(key):
        vals = [m["usage"][key] for m in ms]
        return None if any(v is None for v in vals) else sum(vals)

    return {"wall_s": round(sum(m["wall_s"] for m in ms), 1), "input_tokens": total("input_tokens"),
            "output_tokens": total("output_tokens"), "cost_usd": total("cost_usd")}


def fraction(entry: dict) -> float:
    s = entry["score"]
    return s["passed"] / s["expected"] if s["expected"] else 0.0


def is_full(entry: dict, lab: list[str]) -> bool:
    return bool(lab) and set(lab) <= {m["name"] for m in entry["methods"]}


def _key(entry: dict):
    t = totals(entry)
    return (-fraction(entry), math.inf if t["cost_usd"] is None else t["cost_usd"], t["wall_s"], entry["id"])


def ranked(entries: list[dict], lab: list[str]) -> dict:
    return {"full": sorted((e for e in entries if is_full(e, lab)), key=_key),
            "partial": sorted((e for e in entries if not is_full(e, lab)), key=_key)}


def load_all(root: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in sorted((Path(root) / "bench" / "results").glob("*/*/entry.json")):
        e = schema.load("bench-entry", p)
        if e["study"] != p.parent.parent.name or e["id"] != p.parent.name:
            raise schema.ContractError(f"{p}: study and id do not match the folder")
        out.setdefault(e["study"], []).append(e)
    return out


def _lab(root: Path, study: str) -> list[str]:
    return runner.methods(Path(root) / "studies" / study)


def entrant_name(entry: dict) -> str:
    a = entry["entrant"]
    return a["agent"] + (f" · {a['model']}" if a["model"] else "") + (" (local)" if a["oss"] else "")


def row(entry: dict, repo: str | None, commit: str | None) -> dict:
    ok = repo and commit and commit != "unknown"
    url = f"{repo}/tree/{commit}/bench/results/{entry['study']}/{entry['id']}" if ok else None
    return {"id": entry["id"], "entrant": entrant_name(entry), "label": entry["entrant"]["label"],
            "passed": entry["score"]["passed"], "expected": entry["score"]["expected"],
            "score": round(fraction(entry), 4), "methods": len(entry["methods"]), **totals(entry),
            "metrics": entry["metrics"], "url": url, "created_at": entry["created_at"]}


def board(root: Path, repo: str | None, commit: str | None) -> dict:
    out = {}
    for study, entries in sorted(load_all(root).items()):
        r = ranked(entries, _lab(root, study))
        out[study] = {k: [row(e, repo, commit) for e in v] for k, v in r.items()}
    return out


def _cell(text) -> str:
    return str(text).replace("|", "\\|")


def table(root: Path, study: str | None = None) -> str:
    lines = []
    for sid, entries in sorted(load_all(root).items()):
        if study and sid != study:
            continue
        r = ranked(entries, _lab(root, sid))
        lines += [f"### {sid}", "", "| # | Agent | Setup | Score | Time | Tokens* | Cost* |",
                  "|---|---|---|---|---|---|---|"]
        for kind in ("full", "partial"):
            for i, e in enumerate(r[kind], 1):
                t = totals(e)
                tokens = ("—" if t["input_tokens"] is None or t["output_tokens"] is None
                          else f"{(t['input_tokens'] + t['output_tokens']) / 1000:.0f}k")
                cost = "—" if t["cost_usd"] is None else f"${t['cost_usd']:.2f}"
                rank = str(i) if kind == "full" else "partial"
                lines.append(f"| {rank} | {_cell(entrant_name(e))} | {_cell(e['entrant']['label'] or '—')} | "
                             f"{e['score']['passed']}/{e['score']['expected']} | {t['wall_s'] / 60:.0f} min | "
                             f"{tokens} | {cost} |")
        lines += ["", FOOTNOTE, ""]
    return "\n".join(lines).rstrip() if lines else "No bench entries yet."

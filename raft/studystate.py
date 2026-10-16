"""raft status: where a study stands, one line per gate, and the one command to run next."""
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import agents, checker, gaps, live, paths, provenance, runner, schema, validate

CORE = ("paper", "extraction", "checker", "tested", "approval")



def prepare_cmd(study: str, agent: str | None = None, attacker: str | None = None) -> str:
    if not agent:
        return f"uv run raft prepare --study {study} --agent <claude-code|codex>"
    cmd = f"uv run raft prepare --study {study} --agent {agent}" + (' --cmd "…"' if agent == "command" else "")
    if attacker and attacker != agent:
        cmd += f" --attacker {attacker}" + (' --attacker-cmd "…"' if attacker == "command" else "")
    return cmd


@dataclass(frozen=True)
class Stage:
    name: str
    ok: bool | None  # None: not checked (or not reached)
    text: str


def _last(root: Path, study: str):
    found = [s for s in live.sessions(root, study) if s["kind"] == "prepare"]
    return found[0] if found else None


def last_stop(root, study: str) -> dict | None:
    """How the newest prepare run for the study ended, when it did not finish."""
    last = _last(Path(root), study)
    if not last or last["state"] not in ("stopped", "lost"):
        return None
    why = (last.get("problem") or {}).get("headline") or (
        "the run was interrupted (its process is gone)" if last["state"] == "lost"
        else (last["message"] or "stopped").splitlines()[0].removeprefix("raft: "))
    return {"headline": why, "at": last["updated_at"]}


def arxiv_of(paper: dict) -> str | None:
    """The study's arXiv id: `arxiv:` in paper.yaml, else the id inside an arXiv DOI (10.48550/arXiv.<id>)."""
    if paper.get("arxiv"):
        return str(paper["arxiv"])
    doi = str(paper.get("doi") or "")
    return doi.split("arXiv.", 1)[1] if "arXiv." in doi else None


def find_arxiv(root, arxiv_id: str) -> str | None:
    for s in paths.studies(Path(root), include_drafts=True):
        if arxiv_of(yaml.safe_load((Path(root) / "studies" / s / "paper.yaml").read_text()) or {}) == arxiv_id:
            return s
    return None


def tools(root, study: str) -> tuple:
    """The tools of the last prepare run, with a refused one swapped for the other tool."""
    s = _last(Path(root), study)
    if not s:
        return None, None
    a = (s["agents"].get("builder") or {}).get("tool")
    b = (s["agents"].get("attacker") or {}).get("tool")
    p = s.get("problem")
    if p and p["kind"] == "refused" and p["tool"] in agents.OTHER:
        if p["role"] == "attacker":
            b = agents.OTHER[p["tool"]]
        else:
            a = agents.OTHER[p["tool"]]
    return a, b


def _committed(root: Path, path: Path) -> bool:
    rel = provenance._rel(root, path)
    return (provenance._git(root, "ls-files", "--error-unmatch", rel) is not None
            and not provenance.is_dirty(root, [path]))


def _rounds(sd: Path) -> list:
    try:
        return schema.load("checker-review", sd / "checker" / "review.json")["rounds"]
    except schema.ContractError:
        return []


def stages(root, study: str, quick: bool = False) -> list[Stage]:
    root = Path(root)
    sd = root / "studies" / study
    paper = yaml.safe_load((sd / "paper.yaml").read_text()) or {}
    out, blocked = [], False

    def add(name, ok, text):
        nonlocal blocked
        if blocked:
            out.append(Stage(name, None, "—"))
            return
        out.append(Stage(name, ok, text))
        blocked = ok is False

    pdf = paper.get("pdf") or f"papers/{study}.pdf"
    has_pdf = (root / pdf).is_file()
    src = f"arXiv:{paper['arxiv']}" if paper.get("arxiv") else (paper.get("doi") or "no source")
    extracted = (sd / "extraction.json").is_file()  # once extracted, the PDF is needed only to extract again
    add("paper", has_pdf or extracted, f"{src}, " + ("PDF in papers/" if has_pdf else
                                                     f"no PDF at {pdf} (needed only to extract again)" if extracted
                                                     else f"no PDF at {pdf}"))
    items = []
    if not (sd / "extraction.json").is_file():
        add("extraction", False, "not extracted")
    else:
        problems = validate.extraction(sd)
        if problems:
            add("extraction", False, f"{len(problems)} problem(s) in extraction.json")
        else:
            items = schema.load("extraction", sd / "extraction.json")["items"]
            add("extraction", True, f"{len(items)} items, {sum(i['missing'] for i in items)} missing")
    decoys = len(list((sd / "checker" / "attacks").glob("*.py")))
    if quick:
        add("checker", None, "not checked (--quick)")
    elif not blocked:
        try:
            holes = checker.validate(root, study, 1800.0, log=lambda s: None)
        except Exception as e:  # noqa: BLE001 (a broken checker is a finding, not a crash)
            holes = [f"{type(e).__name__}: {e}"]
        add("checker", not holes, f"validates ({decoys} decoys in checker/attacks/)" if not holes
            else f"{len(holes)} hole(s)")
    else:
        add("checker", None, "—")
    try:
        state = checker.approval_state(root, study)["state"]
    except schema.ContractError:
        state = "invalid"
    rounds = _rounds(sd)
    if state == "approved-before-attacks":
        add("tested", True, "approved before decoy testing existed")
    elif not rounds:
        add("tested", False, "0 rounds")
    else:
        through = sum(not a["blocked"] for a in rounds[-1]["attacks"])
        add("tested", through == 0, f"{len(rounds)} round(s), last fully blocked" if not through
            else f"{len(rounds)} round(s), {through} decoy(s) passed the grader in the last")
    if state in ("approved", "approved-before-attacks"):
        done = _committed(root, sd / checker.APPROVAL)
        add("approval", done, "approved" if done else "approved, not committed yet")
    else:
        add("approval", False, {"missing": "not approved", "stale": "checker changed since approval",
                                "invalid": "checker-approval.json is invalid"}[state])
    missing = sum(i["missing"] for i in items)
    try:
        data = gaps.load(sd)
    except SystemExit:
        data, missing = None, -1
    if data:
        add("gaps", True, gaps.count_line(gaps.counts(data)))
    elif missing:
        add("gaps", False, "gaps.json is invalid" if missing < 0 else f"{missing} missing details not listed yet")
    else:
        add("gaps", True, "none")
    runs = list((sd / "runs").glob("*/manifest.json"))
    add("runs", bool(runs), f"{len(runner.methods(sd))} method(s), {len(runs)} run(s)")
    return out


def next_step(root, study: str, st: list[Stage], tools: tuple) -> str:
    root = Path(root)
    sd = root / "studies" / study
    paper = yaml.safe_load((sd / "paper.yaml").read_text()) or {}
    first = next((s for s in st if s.ok is False), None)
    name = first.name if first else None
    if name == "paper":
        return f"Put the paper's PDF at {paper.get('pdf') or f'papers/{study}.pdf'}"
    if name in ("extraction", "checker", "tested"):
        return prepare_cmd(study, *tools)
    if name == "approval":
        if first.text == "approved, not committed yet":
            return f'git add studies/{study}/{checker.APPROVAL} && git commit -m "Approve {study} checker"'
        return f"uv run raft approve --study {study}   (in your own terminal, then commit {checker.APPROVAL})"
    if name == "gaps":
        return f"uv run raft gaps --study {study}"
    if name == "runs":
        if not runner.methods(sd):
            return f"uv run raft implement <method> --study {study}   (one per method; see CONTRIBUTING.md)"
        return f"uv run raft run --all --study {study}"
    if paper.get("draft"):
        return f"Remove `draft: true` from studies/{study}/paper.yaml to publish it"
    if (sd / "gaps.json").is_file() and gaps.counts(gaps.load(sd))["open"]:
        return f"uv run raft gaps --study {study} --letter"
    return "uv run raft compare"


def report(root, study: str, quick: bool = False) -> str:
    root = Path(root)
    paper = yaml.safe_load((root / "studies" / study / "paper.yaml").read_text()) or {}
    st = stages(root, study, quick)
    first = next((s for s in st if s.ok is False), None)
    lines = [study + ("  (draft)" if paper.get("draft") else "")]
    for s in st:
        mark = "✓" if s.ok else ("✗" if s is first else "·")
        lines.append(f"{mark} {s.name:<11} {s.text}")
    stop = last_stop(root, study)
    if stop:
        lines.append(f"  last stop: {stop['headline']} ({stop['at'][:16].replace('T', ' ')})")
    lines.append(f"Next: {next_step(root, study, st, tools(root, study))}")
    return "\n".join(lines)


def summary(root) -> str:
    root = Path(root)
    rows = []
    for s in paths.studies(root, include_drafts=True):
        st = stages(root, s, quick=True)
        first = next((x for x in st if x.ok is False), None)
        rows.append(f"{s}: {first.name + ' — ' + first.text if first else 'ready'} → "
                    f"{next_step(root, s, st, tools(root, s))}")
    return "\n".join(rows) or "• no studies yet"

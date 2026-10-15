"""raft prepare: from an arXiv id (or a draft study) to a checker ready for the owner's approval, with agents.

Steps, each skipped when its gate already passes, so a rerun resumes: intake → extract (gate: extract --validate)
→ build the checker (gate: raft validate) → attack rounds (gate: the last recorded round was fully blocked and the
checker still holds). It never approves.
"""
import tempfile
from pathlib import Path

from . import agents, bench, briefs, checker, schema, validate


def _transcript(sd: Path, step: str) -> Path:
    d = sd / "checker" / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob(f"{step}-*.jsonl"))) + 1
    return d / f"{step}-{n}.jsonl"


def _agent(root: Path, sd: Path, step: str, text: str, agent: str, model, cmd, timeout: float, log) -> None:
    with tempfile.TemporaryDirectory(prefix="raft-prepare-") as tmp:
        brief = Path(tmp) / "brief.md"
        brief.write_text(text)
        t = Path(tmp) / "t.jsonl"
        log(f"• {step}: {agent} …")
        r = agents.run(agent, brief, root, step, model=model, cmd=cmd, timeout=timeout, transcript=t)
        dest = _transcript(sd, step)
        bench.trim_copy(t, dest)
        if t.with_suffix(".stderr.txt").is_file() and t.with_suffix(".stderr.txt").stat().st_size:
            bench.trim_copy(t.with_suffix(".stderr.txt"), dest.with_suffix(".stderr.txt"))
        log(f"  {step}: " + ("timed out" if r["timed_out"] else f"agent exited {r['exit']}") + f" after {r['wall_s']:.0f}s")


def _with_problems(text: str, title: str, problems: list[str]) -> str:
    return text + f"\n\n**{title}:**\n" + "\n".join(f"- {p}" for p in problems) if problems else text


def _review_holds(sd: Path) -> bool:
    path = sd / "checker" / "review.json"
    if not path.is_file():
        return False
    try:
        rounds = schema.load("checker-review", path)["rounds"]
    except schema.ContractError:
        return False
    return bool(rounds) and all(a["blocked"] for a in rounds[-1]["attacks"])


def _rounds_done(sd: Path) -> int:
    path = sd / "checker" / "review.json"
    try:
        return len(schema.load("checker-review", path)["rounds"]) if path.is_file() else 0
    except schema.ContractError:
        return 0


def prepare(root: Path, *, agent: str, arxiv: str | None = None, study: str | None = None,
            study_id: str | None = None, brief_url: str | None = None, model=None, cmd=None, attacker=None,
            attacker_model=None, attacker_cmd=None, timeout: float = 2700.0, run_timeout: float = 1800.0,
            rounds: int = 3, log=print, fetcher=None) -> str:
    root = Path(root)
    if bool(arxiv) == bool(study):
        raise SystemExit("raft: prepare needs --arxiv or --study (one of them)")
    agents.check(agent, model=model, cmd=cmd)
    attacker = attacker or agent
    if attacker == agent and attacker_cmd is None:
        attacker_cmd, attacker_model = cmd, attacker_model or model
    agents.check(attacker, model=attacker_model, cmd=attacker_cmd)
    if arxiv:
        from . import arxiv as intake
        study = intake.intake(root, arxiv, study_id=study_id, brief=brief_url,
                              fetcher=fetcher or intake.Fetcher()).name
        log(f"✓ intake: studies/{study}")
    sd = root / "studies" / study
    if not (sd / "paper.yaml").is_file():
        raise SystemExit(f"raft: no study {study!r}")
    next_step = f"Fix it by hand or rerun `uv run raft prepare --study {study} --agent {agent}`."

    problems = validate.extraction(sd)
    for attempt in range(2):
        if not problems:
            break
        text = _with_problems(briefs.render(root, "extractor", study), "Problems from the last attempt",
                              problems if attempt else [])
        _agent(root, sd, "extract", text, agent, model, cmd, timeout, log)
        problems = validate.extraction(sd)
    if problems:
        raise SystemExit(f"raft: extraction still fails after 2 tries:\n  " + "\n  ".join(problems) + f"\n{next_step}")
    log("✓ extraction")

    holes = checker.validate(root, study, run_timeout, log=lambda s: None)
    built = not holes
    for attempt in range(2):
        if not holes:
            break
        text = _with_problems(briefs.render(root, "checker-builder", study), "Holes from the last attempt",
                              holes if attempt else [])
        _agent(root, sd, "build", text, agent, model, cmd, timeout, log)
        holes = checker.validate(root, study, run_timeout, log=lambda s: None)
    if holes:
        raise SystemExit("raft: the checker does not hold after 2 builder tries:\n  " + "\n  ".join(holes)
                         + f"\n{next_step}")
    log("✓ checker validates")

    if built and _review_holds(sd):
        log("✓ attacks: the last recorded round was fully blocked")
    else:
        for i in range(rounds):
            rnd = _rounds_done(sd) + 1
            text = briefs.render(root, "checker-attacker", study).replace("{{round}}", str(rnd))
            _agent(root, sd, "attack", text, attacker, attacker_model, attacker_cmd, timeout, log)
            holes = checker.validate(root, study, run_timeout, log=lambda s: None)
            if not holes:
                log(f"✓ round {rnd}: every attack was blocked")
                break
            if i == rounds - 1:
                raise SystemExit(f"raft: holes remain after {rounds} attack rounds:\n  " + "\n  ".join(holes)
                                 + f"\nRead studies/{study}/checker/review.json and decide: fix problem/ yourself, "
                                 f"or rerun `uv run raft prepare --study {study}`.")
            text = _with_problems(briefs.render(root, "checker-builder", study),
                                  "Attacks or checks that got through; fix problem/ so they fail", holes)
            _agent(root, sd, "build", text, agent, model, cmd, timeout, log)
    log(f"Ready for your approval. Read studies/{study}/checker/, commit it, then run in your terminal:\n"
        f"  uv run raft approve --study {study}")
    return study

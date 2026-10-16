"""raft prepare: from an arXiv id (or a draft study) to a checker ready for the owner's approval, with agents.

Steps, each skipped when its gate already passes, so a rerun resumes: intake → extract (gate: extract --validate)
→ build the checker (gate: raft validate) → attack rounds (gate: the last recorded round was fully blocked and the
checker still holds). It never approves.
"""
import hashlib
import json
import tempfile
from pathlib import Path

import yaml

from . import agents, bench, briefs, checker, live, schema, validate


def _transcript(sd: Path, step: str) -> Path:
    d = sd / "checker" / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob(f"{step}-*.jsonl"))) + 1
    return d / f"{step}-{n}.jsonl"


def _evidence(sd: Path) -> dict:
    """What the agents may only add to: attack files (by hash) and recorded rounds; and the approval, never touched."""
    a = sd / "checker" / "attacks"
    review = sd / "checker" / "review.json"
    try:
        rounds = json.loads(review.read_text()).get("rounds", []) if review.is_file() else []
    except (json.JSONDecodeError, AttributeError):
        rounds = []
    approval = sd / checker.APPROVAL
    return {"attacks": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(a.glob("*.py"))}
            if a.is_dir() else {},
            "rounds": rounds, "approval": approval.read_bytes() if approval.is_file() else None}


def _kept(before: dict, after: dict) -> bool:
    return (all(after["attacks"].get(k) == v for k, v in before["attacks"].items())
            and after["rounds"][:len(before["rounds"])] == before["rounds"])


def _agent(root: Path, sd: Path, step: str, text: str, agent: str, model, cmd, timeout: float, log,
           ls: "live.Session", step_id: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="raft-prepare-") as tmp:
        brief = Path(tmp) / "brief.md"
        brief.write_text(text)
        t = Path(tmp) / "t.jsonl"
        log(f"• {step}: {agent} …")
        with live.watching(ls, step_id, agent, t):
            r = agents.run(agent, brief, root, step, model=model, cmd=cmd, timeout=timeout, transcript=t)
        dest = _transcript(sd, step)
        bench.trim_copy(t, dest)
        if t.with_suffix(".stderr.txt").is_file() and t.with_suffix(".stderr.txt").stat().st_size:
            bench.trim_copy(t.with_suffix(".stderr.txt"), dest.with_suffix(".stderr.txt"))
        log(f"  {step}: " + ("timed out" if r["timed_out"] else f"agent exited {r['exit']}") + f" after {r['wall_s']:.0f}s")
    return r


def _step(root: Path, sd: Path, step: str, text: str, agent: str, model, cmd, timeout: float, log,
          ls: "live.Session", step_id: str, label: str, role: str) -> dict:
    """Run one agent step; stop if it touched the approval or removed or changed earlier attack evidence."""
    ls.begin(step_id, label, agent=role, timeout_s=timeout)
    before = _evidence(sd)
    r = _agent(root, sd, step, text, agent, model, cmd, timeout, log, ls, step_id)
    after = _evidence(sd)
    if after["approval"] != before["approval"]:
        raise SystemExit(f"raft: the {step} agent changed {checker.APPROVAL}; only the owner approves. Restore it "
                         f"with `git checkout -- studies/{sd.name}/{checker.APPROVAL}` and check what else it did.")
    if not _kept(before, after):
        raise SystemExit(f"raft: the {step} agent removed or changed attack evidence (checker/attacks/ or earlier "
                         f"rounds in checker/review.json). Restore them from git and rerun "
                         f"`uv run raft prepare --study {sd.name}`.")
    return {"run": r, "before": before, "after": after}


def _round_results(sd: Path) -> list[dict]:
    try:
        rounds = schema.load("checker-review", sd / "checker" / "review.json")["rounds"]
    except schema.ContractError:
        return []
    return [{"round": r["round"], "tried": len(r["attacks"]), "blocked": sum(bool(a["blocked"]) for a in r["attacks"]),
             "attacks": [{"name": a["name"], "blocked": bool(a["blocked"])} for a in r["attacks"]]} for r in rounds]


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
            rounds: int = 3, log=print, fetcher=None, on_live=None) -> str:
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
    paper = yaml.safe_load((sd / "paper.yaml").read_text()) or {}
    ls = live.Session(root, "prepare", study, title=paper.get("title"), arxiv=str(paper["arxiv"]) if paper.get("arxiv") else None,
                      agents={"builder": {"tool": agent, "model": model}, "attacker": {"tool": attacker, "model": attacker_model}},
                      total=3 + rounds, on_write=on_live)
    ls.skip("intake", "Intake", f"studies/{study} from arXiv:{arxiv}" if arxiv else f"studies/{study}")
    try:
        _prepare_steps(root, sd, study, ls, agent=agent, model=model, cmd=cmd, attacker=attacker,
                       attacker_model=attacker_model, attacker_cmd=attacker_cmd, timeout=timeout,
                       run_timeout=run_timeout, rounds=rounds, log=log)
    except SystemExit as e:
        ls.stop(str(e.code if e.code is not None else "stopped"))
        raise
    except KeyboardInterrupt:
        ls.stop("interrupted (Ctrl-C)")
        raise
    except Exception as e:  # noqa: BLE001 (record any crash, then let it surface)
        ls.stop(f"{type(e).__name__}: {e}")
        raise
    ls.finish(f"uv run raft approve --study {study}")
    log(f"Ready for your approval. Read studies/{study}/checker/, commit it, then run in your terminal:\n"
        f"  uv run raft approve --study {study}")
    return study


def _prepare_steps(root: Path, sd: Path, study: str, ls: "live.Session", *, agent, model, cmd, attacker,
                   attacker_model, attacker_cmd, timeout, run_timeout, rounds, log) -> None:
    next_step = f"Fix it by hand or rerun `uv run raft prepare --study {study} --agent {agent}`."

    problems = validate.extraction(sd)
    if not problems:
        ls.skip("extract", "Extract", "extraction.json already valid")
    for attempt in range(2):
        if not problems:
            break
        if attempt:
            ls.add_total(1)
        sid = f"extract-{attempt + 1}"
        text = _with_problems(briefs.render(root, "extractor", study), "Problems from the last attempt",
                              problems if attempt else [])
        _step(root, sd, "extract", text, agent, model, cmd, timeout, log, ls, sid,
              "Extract" + (", try 2" if attempt else ""), "builder")
        problems = validate.extraction(sd)
        ls.end(sid, "failed" if problems else "done",
               detail=f"{len(problems)} problem(s) in extraction.json" if problems else "extraction.json valid")
    if problems:
        raise SystemExit(f"raft: extraction still fails after 2 tries:\n  " + "\n  ".join(problems) + f"\n{next_step}")
    log("✓ extraction")

    holes = checker.validate(root, study, run_timeout, log=lambda s: None)
    built = not holes
    ls.set_results(holes=len(holes), rounds=_round_results(sd))
    if built:
        ls.skip("build", "Build checker", "the checker already validates")
    for attempt in range(2):
        if not holes:
            break
        if attempt:
            ls.add_total(1)
        sid = f"build-{attempt + 1}"
        text = _with_problems(briefs.render(root, "checker-builder", study), "Holes from the last attempt",
                              holes if attempt else [])
        _step(root, sd, "build", text, agent, model, cmd, timeout, log, ls, sid,
              "Build checker" + (", try 2" if attempt else ""), "builder")
        holes = checker.validate(root, study, run_timeout, log=lambda s: None)
        ls.set_results(holes=len(holes))
        ls.end(sid, "failed" if holes else "done", detail=f"{len(holes)} hole(s)" if holes else "checker validates")
    if holes:
        raise SystemExit("raft: the checker does not hold after 2 builder tries:\n  " + "\n  ".join(holes)
                         + f"\n{next_step}")
    log("✓ checker validates")

    if built and _review_holds(sd):
        ls.skip("attack", "Attacks", "the last recorded round was fully blocked")
        ls.add_total(-(rounds - 1))
        log("✓ attacks: the last recorded round was fully blocked")
        return
    for i in range(rounds):
        rnd = _rounds_done(sd) + 1
        sid = f"attack-{rnd}"
        text = briefs.render(root, "checker-attacker", study).replace("{{round}}", str(rnd))
        done = _step(root, sd, "attack", text, attacker, attacker_model, attacker_cmd, timeout, log, ls, sid,
                     f"Attack round {rnd}", "attacker")
        new_files = set(done["after"]["attacks"]) - set(done["before"]["attacks"])
        new_rounds = done["after"]["rounds"][len(done["before"]["rounds"]):]
        if done["run"]["timed_out"] or not new_files or not new_rounds or not new_rounds[-1].get("attacks"):
            why = "timed out" if done["run"]["timed_out"] else "the attack step recorded no new round and attack"
            raise SystemExit(f"raft: round {rnd}: {why} (checker/attacks/ and checker/review.json are unchanged). "
                             f"Read checker/transcripts/, then rerun `uv run raft prepare --study {study}`.")
        holes = checker.validate(root, study, run_timeout, log=lambda s: None)
        ls.set_results(holes=len(holes), rounds=_round_results(sd))
        ls.end(sid, detail="every attack was blocked" if not holes else f"{len(holes)} hole(s) got through")
        if not holes:
            ls.add_total(-(rounds - i - 1))
            log(f"✓ round {rnd}: every attack was blocked")
            return
        if i == rounds - 1:
            raise SystemExit(f"raft: holes remain after {rounds} attack rounds:\n  " + "\n  ".join(holes)
                             + f"\nRead studies/{study}/checker/review.json and decide: fix problem/ yourself, "
                             f"or rerun `uv run raft prepare --study {study}`.")
        ls.add_total(1)
        fid = f"fix-{rnd}"
        text = _with_problems(briefs.render(root, "checker-builder", study),
                              "Attacks or checks that got through; fix problem/ so they fail", holes)
        _step(root, sd, "build", text, agent, model, cmd, timeout, log, ls, fid, f"Fix checker after round {rnd}",
              "builder")
        holes = checker.validate(root, study, run_timeout, log=lambda s: None)
        ls.set_results(holes=len(holes))
        ls.end(fid, detail=f"{len(holes)} hole(s)" if holes else "checker validates")

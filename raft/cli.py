"""raft: new | extract | implement | run | review | repro | compare | watch | flow-export | bench."""
import argparse
import json
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import briefs, paths, runner, scaffold, validate

def _value(text: str):
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def _params(rest: list[str]) -> dict:
    params, i = {}, 0
    while i < len(rest):
        tok = rest[i]
        if not tok.startswith("--") or tok == "--":
            raise SystemExit(f"raft: unexpected argument {tok!r}")
        key = tok[2:]
        if "=" in key:
            key, val = key.split("=", 1)
            i += 1
        elif i + 1 < len(rest) and not rest[i + 1].startswith("--"):
            val = rest[i + 1]
            i += 2
        else:
            raise SystemExit(f"raft: --{key} needs a value")
        params[key.replace("-", "_")] = _value(val)
    return params


# Options raft itself understands; every other --key [value] is a study parameter.
KNOWN = {"--all", "--all-studies", "--timeout", "--study", "--validate", "--out", "--title", "--doi", "--help", "-h",
         "--assets", "--port", "--no-open", "--agent", "--model", "--oss", "--setup", "--methods", "--label", "--cmd",
         "--run-timeout", "--verify", "--table", "--force", "--arxiv", "--id", "--brief", "--round", "--without-attacks", "--attacker", "--attacker-model", "--attacker-cmd",
         "--rounds", "--watch", "--letter", "--mark-asked", "--answer", "--decline", "--blocks", "--from", "--by",
         "--source", "--publish", "--private", "--note", "--reword", "--try", "--no-try", "--quick"}


def _split(argv: list[str]) -> tuple[list[str], list[str]]:
    """Pull study parameters out before argparse, so `run --all --re 100` never reads 100 as a method."""
    keep, extra, i = [], [], 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--") and tok != "--" and tok.split("=", 1)[0] not in KNOWN:
            extra.append(tok)
            if "=" not in tok and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                extra.append(argv[i + 1])
                i += 1
        else:
            keep.append(tok)
        i += 1
    return keep, extra


def _report(problems: list[str], ok: str) -> int:
    if problems:
        print("\n".join(f"✗ {p}" for p in problems))
        return 1
    print(f"✓ {ok}")
    return 0


LIVE_GRACE_S = 2.5  # how long --watch keeps serving after the command ends, so the page sees the final state


@contextmanager
def _live_view(root: Path, on: bool):
    from . import watch
    if not on:
        print("• watch live: uv run raft watch", flush=True)
        yield
        return
    srv = watch.background(root)
    try:
        yield
    finally:
        if srv is not None:
            time.sleep(LIVE_GRACE_S)
            srv.shutdown()
            srv.server_close()


def _duration(text: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", text.strip())
    if not m:
        raise argparse.ArgumentTypeError(f"not a duration: {text!r} (use 90s, 30m or 2h)")
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]


def _study_cmd(p, args, root: Path, study: str, params: dict) -> int:
    sd = root / "studies" / study
    if args.cmd == "extract":
        if args.validate:
            return _report(validate.extraction(sd), f"{study}/extraction.json is valid")
        print(briefs.render(root, "extractor", study))
        return 0
    if args.cmd == "implement":
        from . import checker
        checker.gate(root, study)
        print(briefs.render(root, "implementer", study, args.method))
        return 0
    if args.cmd == "review":
        if args.validate:
            return _report(validate.methods_and_reviews(sd), f"{study}: method.json files and reviews are valid")
        if not args.method:
            p.error("review needs a method name, or --validate")
        print(briefs.render(root, "reviewer", study, args.method))
        return 0
    if args.cmd == "build-checker":
        print(briefs.render(root, "checker-builder", study))
        return 0
    if args.cmd == "attack":
        print(briefs.render(root, "checker-attacker", study).replace("{{round}}", str(args.round)))
        return 0
    if args.cmd == "repro":
        return _report(runner.repro(sd, params, args.timeout), f"{study}: every matching run reproduced")
    if args.all == bool(args.method):
        p.error("give one method name or --all")
    from . import checker
    checker.gate(root, study)
    names = runner.methods(sd) if args.all else [args.method]
    if not names:
        if args.all_studies:
            print(f"• {study}: no methods yet")
            return 0
        raise SystemExit(f"raft: no methods in {sd / 'methods'} yet")
    try:
        combos = runner.expand(sd, params)
    except ValueError as e:
        if args.all_studies:
            print(f"✗ {study}: {e}")
            return 1
        raise SystemExit(f"raft: {e}") from None
    for name in names:
        for combo in combos:
            print(runner.summary(*runner.run_one(sd, name, combo, args.timeout)), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--study", help="study folder under studies/ (default: the only one)")
    common.add_argument("--all-studies", action="store_true", help="repeat for every study that is not a draft")
    p = argparse.ArgumentParser(prog="raft", description="Reproduce research papers with agents, in a controlled environment.")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="start a new study folder (a draft until problem/ is filled in)")
    n.add_argument("study_id", nargs="?")
    n.add_argument("--title")
    n.add_argument("--doi")
    n.add_argument("--arxiv", help="fetch the record and PDF from arXiv, e.g. 2608.27428")
    n.add_argument("--id", dest="new_id", help="with --arxiv: the study id (default: surname-year-word)")
    n.add_argument("--brief", help="with --arxiv: the paper's Paperraft brief URL")
    n.add_argument("--from", dest="from_study", help="start a stricter version of this study, using its published author answers")
    e = sub.add_parser("extract", parents=[common], help="print the extractor brief, or --validate extraction.json")
    e.add_argument("--validate", action="store_true")
    im = sub.add_parser("implement", parents=[common], help="print the implementer brief for one method")
    im.add_argument("method")
    r = sub.add_parser("run", parents=[common], help="run methods; extra --key value pairs are study parameters")
    r.add_argument("method", nargs="?")
    r.add_argument("--all", action="store_true")
    r.add_argument("--timeout", type=float, default=1800.0)
    rv = sub.add_parser("review", parents=[common], help="print the reviewer brief, or --validate methods and reviews")
    rv.add_argument("method", nargs="?")
    rv.add_argument("--validate", action="store_true")
    rp = sub.add_parser("repro", parents=[common], help="rerun committed runs; extra --key value pairs filter them")
    rp.add_argument("--timeout", type=float, default=1800.0)
    c = sub.add_parser("compare", help="score every run and build the static site")
    c.add_argument("--out", default="site")
    w = sub.add_parser("watch", help="show live prepare and bench sessions on localhost; with --study, the flow view of its runs")
    w.add_argument("--study")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--no-open", action="store_true")
    fe = sub.add_parser("flow-export", help="write a committed study's flow.json (and the view's files) for Paperraft")
    fe.add_argument("--study")
    fe.add_argument("--out", required=True)
    fe.add_argument("--assets")
    b = sub.add_parser("bench", help="give a study to your agent in a blind workspace, grade its code, write a scoreboard entry")
    b.add_argument("--watch", action="store_true", help="open the live view in your browser while it runs")
    b.add_argument("--study")
    b.add_argument("--agent", choices=("claude-code", "codex", "command"))
    b.add_argument("--model")
    b.add_argument("--oss", action="store_true", help="codex only: use a local model through codex --oss")
    b.add_argument("--setup", help="your setup folder (AGENTS.md, CLAUDE.md, .claude/skills, …), copied onto the workspace")
    b.add_argument("--methods", help="comma-separated; default: every method of the study")
    b.add_argument("--label", help="a short name for your setup on the scoreboard")
    b.add_argument("--cmd", dest="agent_cmd", help="with --agent command: your tool's command line, with {brief} (and {workspace}, {method})")
    b.add_argument("--timeout", type=_duration, default=1800.0, help="per method, for the agent (default 30m)")
    b.add_argument("--run-timeout", type=_duration, default=1800.0, help="per graded run (default 30m)")
    b.add_argument("--verify", nargs="*", metavar="ENTRY", help="rerun entries (default: every entry) and check their numbers")
    b.add_argument("--table", action="store_true", help="print the scoreboard as markdown")
    b.add_argument("--no-try", action="store_true", help="skip the tool's daily test task")
    gr = sub.add_parser("grader", help="copy a grader from the library into a study's problem/graders/")
    gr.add_argument("action", choices=("add",))
    gr.add_argument("name")
    gr.add_argument("--study")
    gr.add_argument("--force", action="store_true")
    va = sub.add_parser("validate", help="check a study's checker: reference answer, mutations, attacks, grader copies")
    va.add_argument("--study")
    va.add_argument("--run-timeout", type=_duration, default=1800.0)
    sub.add_parser("build-checker", parents=[common], help="print the checker builder's brief")
    at = sub.add_parser("attack", parents=[common], help="print the checker attacker's brief")
    at.add_argument("--round", type=int, default=1)
    ap = sub.add_parser("approve", help="the owner's sign-off on a study's checker (interactive terminal only)")
    ap.add_argument("--study")
    ap.add_argument("--without-attacks", action="store_true",
                    help="only for a study with runs made before the checker gate")
    ap.add_argument("--run-timeout", type=_duration, default=1800.0)
    pr = sub.add_parser("prepare", help="from an arXiv id or a draft study to a checker ready for your approval, with agents")
    pr.add_argument("--arxiv")
    pr.add_argument("--watch", action="store_true", help="open the live view in your browser while it runs")
    pr.add_argument("--study")
    pr.add_argument("--id", dest="new_id")
    pr.add_argument("--brief")
    pr.add_argument("--agent", choices=("claude-code", "codex", "command"), required=True)
    pr.add_argument("--model")
    pr.add_argument("--cmd", dest="agent_cmd")
    pr.add_argument("--attacker", choices=("claude-code", "codex", "command"))
    pr.add_argument("--attacker-model")
    pr.add_argument("--attacker-cmd")
    pr.add_argument("--timeout", type=_duration, default=2700.0, help="per agent step (default 45m)")
    pr.add_argument("--run-timeout", type=_duration, default=1800.0)
    pr.add_argument("--rounds", type=int, default=3)
    pr.add_argument("--no-try", action="store_true", help="skip the tools' daily test task")
    dr = sub.add_parser("doctor", help="check the agent tools (installed, logged in, --try a trivial task) or a study's transcripts")
    dr.add_argument("--agent", choices=("claude-code", "codex"))
    dr.add_argument("--attacker", choices=("claude-code", "codex"))
    dr.add_argument("--model")
    dr.add_argument("--oss", action="store_true")
    dr.add_argument("--try", dest="try_", action="store_true", help="also run a trivial task (uses a few cents of your quota)")
    dr.add_argument("--study", help="report transcripts in this study that still hold your home path")
    stt = sub.add_parser("status", help="where a study stands, gate by gate, and the command to run next")
    stt.add_argument("--study")
    stt.add_argument("--quick", action="store_true", help="don't run the grader to check the checker")
    g = sub.add_parser("gaps", help="questions to the authors for what the paper leaves out, and their answers")
    g.add_argument("--study")
    g.add_argument("--all-studies", action="store_true")
    ga = g.add_mutually_exclusive_group()  # one action per call: a reply is never recorded alongside another
    ga.add_argument("--validate", action="store_true")
    ga.add_argument("--reword", nargs=2, metavar=("ID", "QUESTION"), help="put an open question in plain words before it is sent")
    ga.add_argument("--blocks", nargs=2, metavar=("ID", "CHECK"), help="name the check a missing detail keeps out of the grader")
    ga.add_argument("--letter", action="store_true", help="print a letter to the authors (changes nothing)")
    ga.add_argument("--mark-asked", action="store_true", help="record that the letter's questions were sent today (owner only)")
    ga.add_argument("--answer", metavar="ID", help="record an author's answer (owner only; with --publish or --private)")
    ga.add_argument("--decline", metavar="ID", help="record that the author can't share it (owner only)")
    g.add_argument("--from", dest="answer_file", help="with --answer --publish: a file holding the author's answer")
    g.add_argument("--by", help="who answered")
    g.add_argument("--source", help="where the answer came from, e.g. \"email, 2026-10-20\"")
    g.add_argument("--publish", action="store_true", help="the author agreed to publication")
    g.add_argument("--private", action="store_true", help="the author did not agree; only who, where and when are kept")
    g.add_argument("--note", help="with --private: your own words on what the answer told you (published)")
    keep, rest = _split(sys.argv[1:] if argv is None else argv)
    args = p.parse_args(keep)
    if rest and args.cmd not in ("run", "repro"):
        p.error(f"unrecognized arguments: {' '.join(rest)}")
    root = paths.repo_root()

    if args.cmd == "new":
        if args.from_study:
            new_id = args.new_id or args.study_id
            if not new_id:
                p.error("new --from needs --id <new study id>")
            from . import gaps
            d = scaffold.new_version(root, args.from_study, new_id)
            k = len(gaps.published(root / "studies" / args.from_study))
            print(f"✓ created {d.relative_to(root)} as a draft version of {args.from_study}, with fresh problem/ "
                  f"stubs. Its extractor gets {k} published answer{'' if k == 1 else 's'} from "
                  f"studies/{args.from_study}/gaps.json. Next: `uv run raft prepare --study {new_id} --agent "
                  "<claude-code|codex>`")
            return 0
        if args.arxiv:
            from . import arxiv
            d = arxiv.intake(root, args.arxiv, study_id=args.new_id or args.study_id, brief=args.brief,
                             fetcher=arxiv.Fetcher())
            print(f"✓ created {d.relative_to(root)} from arXiv:{args.arxiv} (PDF in papers/, not committed). "
                  f"Next: `uv run raft prepare --study {d.name} --agent <claude-code|codex>`")
            return 0
        if not (args.study_id and args.title and args.doi):
            p.error("new needs a study id, --title and --doi (or --arxiv <id>)")
        d = scaffold.new_study(root, args.study_id, args.title, args.doi)
        print(f"✓ created {d.relative_to(root)} as a draft. Next: fill in problem/setup.py, problem/measure.py and "
              f"problem/reference.json, put the PDF at papers/{args.study_id}.pdf, delete `draft: true` from "
              f"paper.yaml, then run `uv run raft extract --study {args.study_id}`.")
        return 0
    if args.cmd == "compare":
        from . import compare
        out = Path(args.out) if Path(args.out).is_absolute() else root / args.out
        compare.write_site(compare.build(root, compare.repo_url(root)), out)
        print(f"✓ site written to {out}. Open {out / 'index.html'}")
        return 0
    if args.cmd == "watch":
        from . import watch
        study = paths.resolve_study(root, args.study) if args.study else None
        watch.serve(root, study, args.port, not args.no_open)
        return 0
    if args.cmd == "flow-export":
        from . import compare, flow
        study = paths.resolve_study(root, args.study)
        out = Path(args.out).resolve()
        flow.export(root, study, out, Path(args.assets).resolve() if args.assets else None, compare.repo_url(root))
        print(f"✓ {study}: flow written to {out}" + (f", view files to {args.assets}" if args.assets else ""))
        return 0

    if args.cmd == "bench":
        from . import bench, benchboard
        if args.table:
            print(benchboard.table(root, args.study))
            return 0
        if args.verify is not None:
            dirs = [Path(d).resolve() for d in args.verify] or bench.entry_dirs(root)
            if not dirs:
                print("• no bench entries to verify")
                return 0
            problems = []
            for d in dirs:
                found = bench.verify(root, d, args.run_timeout)
                print(f"{'✗' if found else '✓'} {d.name}", flush=True)
                problems += found
            return _report(problems, f"{len(dirs)} bench {'entry' if len(dirs) == 1 else 'entries'} reproduced")
        if not args.agent:
            p.error("bench needs --agent (or --table, or --verify)")
        study = paths.resolve_study(root, args.study)
        methods = [m.strip() for m in args.methods.split(",") if m.strip()] if args.methods else None
        with _live_view(root, args.watch):
            dest = bench.run_bench(root, study, args.agent, model=args.model, oss=args.oss, setup=args.setup,
                                   methods=methods, label=args.label, cmd=args.agent_cmd, timeout=args.timeout,
                                   run_timeout=args.run_timeout, try_tools=not args.no_try)
        entry = json.loads((dest / "entry.json").read_text())
        print(f"✓ score {entry['score']['passed']}/{entry['score']['expected']} → {dest.relative_to(root)}\n"
              "  Read the transcript before sharing it, then commit the folder and open a pull request to join the scoreboard.")
        return 0

    if args.cmd == "grader":
        from . import graders
        study = paths.resolve_study(root, args.study)
        path = graders.add(root / "studies" / study, args.name, force=args.force)
        print(f"✓ copied {args.name} to {path.relative_to(root)}; use it in measure.py with `from graders import {args.name}`")
        return 0

    if args.cmd == "validate":
        from . import checker
        study = paths.resolve_study(root, args.study)
        return _report(checker.validate(root, study, args.run_timeout), f"{study}: the checker holds")

    if args.cmd == "approve":
        from . import checker
        study = paths.resolve_study(root, args.study)
        path = checker.approve(root, study, without_attacks=args.without_attacks, run_timeout=args.run_timeout)
        print(f"✓ approved: {path.relative_to(root)}. Commit it; runs and bench now work on {study}.")
        return 0

    if args.cmd == "status":
        from . import studystate
        if args.study:
            print(studystate.report(root, paths.resolve_study(root, args.study), args.quick))
        else:
            print(studystate.summary(root))
        return 0

    if args.cmd == "doctor":
        from . import doctor
        if args.study:
            study = paths.resolve_study(root, args.study)
            found = doctor.home_paths(root, study)
            for f in found:
                print(f"✗ {f.relative_to(root)} holds your home path; `uv run raft prepare --study {study} …` cleans it")
            return _report([] if not found else [f"{len(found)} transcript(s) to clean"], f"{study}: no home paths in transcripts")
        tools = [(t, args.model, args.oss) for t in dict.fromkeys(x for x in (args.agent, args.attacker) if x)] \
            or [("claude-code", None, False), ("codex", None, False)]
        if args.try_:
            print("• the test task uses a few cents of your quota")
        checks = doctor.check_tools(root, tools, try_=args.try_)
        for c in checks:
            print(("✓ " if c.ok else "✗ ") + c.line)
        return 0 if all(c.ok for c in checks) else 1

    if args.cmd == "gaps":
        from . import gaps
        if args.validate:
            targets = paths.studies(root) if args.all_studies else [paths.resolve_study(root, args.study)]
            problems = [x for s in targets for x in gaps.validate(root / "studies" / s)]
            return _report(problems, f"gaps.json valid in {len(targets)} stud{'y' if len(targets) == 1 else 'ies'}")
        if args.all_studies:
            p.error("gaps --all-studies works only with --validate")
        if not args.study and not (args.blocks or args.reword or args.letter or args.mark_asked or args.answer or args.decline):
            print(gaps.summary_text(root))
            return 0
        study = paths.resolve_study(root, args.study)
        if args.reword:
            gaps.reword(root, study, *args.reword)
            print(f"✓ {args.reword[0]}: reworded")
            return 0
        if args.letter:
            from . import compare
            print(gaps.letter(root, study, compare.repo_url(root)))
            return 0
        if args.mark_asked:
            ids = gaps.mark_asked(root, study)
            print(f"✓ marked {len(ids)} questions asked today: {', '.join(ids)}")
            return 0
        if args.blocks:
            gid, text = args.blocks
            gaps.set_blocks(root, study, gid, text)
            print(f"✓ {study}/{gid}: blocks: {text}")
            return 0
        if args.answer or args.decline:
            if not (args.by and args.source):
                p.error("--answer and --decline need --by and --source")
            if args.decline:
                gaps.decline(root, study, args.decline, by=args.by, source=args.source)
                print(f"✓ {args.decline}: declined")
                return 0
            if args.publish == args.private:
                p.error("--answer needs exactly one of --publish or --private")
            text = Path(args.answer_file).read_text() if args.answer_file else None
            g_ = gaps.answer(root, study, args.answer, by=args.by, source=args.source, publish=args.publish,
                             text=text, note=args.note)
            print(f"✓ {args.answer}: {g_['status'].replace('_', ' ')}. Commit studies/{study}/gaps.json.")
            return 0
        print(gaps.listing(gaps.refresh(root, study), study))
        return 0

    if args.cmd == "prepare":
        from . import prepare
        with _live_view(root, args.watch):
            prepare.prepare(root, agent=args.agent, arxiv=args.arxiv, study=args.study, study_id=args.new_id,
                            brief_url=args.brief, model=args.model, cmd=args.agent_cmd, attacker=args.attacker,
                            attacker_model=args.attacker_model, attacker_cmd=args.attacker_cmd, timeout=args.timeout,
                            run_timeout=args.run_timeout, rounds=args.rounds, try_tools=not args.no_try)
        return 0

    params = _params(rest)
    if args.all_studies:
        single = (args.cmd in ("implement", "build-checker", "attack") or (args.cmd in ("extract", "review") and not args.validate)
                  or (args.cmd == "run" and not args.all) or args.study)
        if single:
            p.error("--all-studies works with: extract --validate, review --validate, run --all, repro (and not with --study)")
        targets = paths.studies(root)
        if not targets:
            print("• no studies to check yet (drafts are skipped)")
            return 0
    else:
        targets = [paths.resolve_study(root, args.study)]
    code = 0
    for study in targets:
        if args.all_studies:
            print(f"── {study}")
        code = max(code, _study_cmd(p, args, root, study, params))
    return code

"""raft: new | extract | implement | run | review | repro | compare | watch | flow-export."""
import argparse
import sys
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
         "--assets", "--port", "--no-open"}


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


def _study_cmd(p, args, root: Path, study: str, params: dict) -> int:
    sd = root / "studies" / study
    if args.cmd == "extract":
        if args.validate:
            return _report(validate.extraction(sd), f"{study}/extraction.json is valid")
        print(briefs.render(root, "extractor", study))
        return 0
    if args.cmd == "implement":
        print(briefs.render(root, "implementer", study, args.method))
        return 0
    if args.cmd == "review":
        if args.validate:
            return _report(validate.methods_and_reviews(sd), f"{study}: method.json files and reviews are valid")
        if not args.method:
            p.error("review needs a method name, or --validate")
        print(briefs.render(root, "reviewer", study, args.method))
        return 0
    if args.cmd == "repro":
        return _report(runner.repro(sd, params, args.timeout), f"{study}: every matching run reproduced")
    if args.all == bool(args.method):
        p.error("give one method name or --all")
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
    n.add_argument("study_id")
    n.add_argument("--title", required=True)
    n.add_argument("--doi", required=True)
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
    w = sub.add_parser("watch", help="show the flow view on localhost, live while runs are going")
    w.add_argument("--study")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--no-open", action="store_true")
    fe = sub.add_parser("flow-export", help="write a committed study's flow.json (and the view's files) for Paperraft")
    fe.add_argument("--study")
    fe.add_argument("--out", required=True)
    fe.add_argument("--assets")
    keep, rest = _split(sys.argv[1:] if argv is None else argv)
    args = p.parse_args(keep)
    if rest and args.cmd not in ("run", "repro"):
        p.error(f"unrecognized arguments: {' '.join(rest)}")
    root = paths.repo_root()

    if args.cmd == "new":
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
        watch.serve(root, paths.resolve_study(root, args.study), args.port, not args.no_open)
        return 0
    if args.cmd == "flow-export":
        from . import compare, flow
        study = paths.resolve_study(root, args.study)
        out = Path(args.out).resolve()
        flow.export(root, study, out, Path(args.assets).resolve() if args.assets else None, compare.repo_url(root))
        print(f"✓ {study}: flow written to {out}" + (f", view files to {args.assets}" if args.assets else ""))
        return 0

    params = _params(rest)
    if args.all_studies:
        single = (args.cmd == "implement" or (args.cmd in ("extract", "review") and not args.validate)
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

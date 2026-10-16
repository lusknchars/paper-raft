# Smoother prepare: fewer dead runs for people adding papers

**Date:** 2026-10-16 · **Status:** draft, awaiting owner review · **Repo:** paper-raft

## Purpose

`raft prepare` is how a builder turns a paper into a study, and it's the first thing a newcomer tries. Every one of the
first three real runs ended badly for a reason the builder couldn't see coming:

1. **wu-2026, run 1:** Codex's shell tool failed with `timed out negotiating with the code-mode host`. Two extract
   tries burned before `prepare` stopped, with a message about `extraction.json`, not about Codex.
2. **The command typo:** `--attacker codex-watch`. argparse caught it, and that's fine as it is.
3. **wu-2026, run 2:** extract and build worked. Then Codex refused the attacker brief with "This content was
   flagged for possible cybersecurity risk", because the brief says *attack*, *break* and *exploit*. `prepare` said
   only "the attack step recorded no new round", and its advice (rerun the same command) would fail the same way.

The study's transcripts also hold the builder's home path (`/Users/<name>/…`) 78 times, so the study can't be pushed
as it is. And after a stop, the builder has to work out from scratch where the study stands and what to run next.

This spec makes `prepare` find tool problems before spending a step, name them in plain words when they happen, stop
without wasted retries, and always end with the one next command.

## 1. Check the tools before the first step

New command: `uv run raft doctor --agent codex [--attacker claude-code] [--try]`. `prepare` and `bench` run the same
checks automatically before their first agent step.

For each tool the run will use:

- **Installed:** the tool is on PATH, and its version is shown (`agents.tool_version`).
- **Logged in:** `codex login status` and `claude auth status` must exit 0. Skipped for `codex --oss` and
  `--agent command`.
- **Answers a trivial task (`--try`):** the same headless command `prepare` uses, run in an empty temporary folder,
  with a 2-minute limit and this brief: "Run `echo raft-ok` in the shell, then reply with exactly: raft-ok". It
  passes when the tool exits 0, the transcript shows the command ran, and the final message contains `raft-ok`.
  This catches what the first two checks miss, such as today's code-mode host failure. It costs a few cents of the
  builder's quota, which `doctor` prints.

`prepare` and `bench` run the try check too, because one broken tool costs up to 90 minutes of retries. They cache a
pass in `.raft/doctor.json` for 12 hours, keyed by tool and version, so it runs about once a day. `--no-try` skips it.

When a check fails, the run stops before any step, with the reason and what to do: install, log in (`codex login`),
or the tool's own error line. It also names another tool the builder can switch to, if that tool passed.

## 2. Name tool problems when they happen

After every agent step, `prepare` and `bench` read the step's transcript and stderr with a new
`agents.diagnose(agent, transcript_text, stderr_text) -> Problem | None`. `Problem` has `kind`, `tool`, `detail` (the
tool's own line, cut to 300 characters) and `advice`.

| kind | how it's recognised | advice |
|---|---|---|
| `refused` | Codex `error`/`turn.failed` text containing "flagged for possible", or Claude Code result text that refuses | "<tool> refused this brief. Run this step with the other tool: `…--attacker claude-code`" |
| `tool-broken` | stderr containing "timed out negotiating with the code-mode host" | "<tool>'s shell tool is failing (update or restart it). Check with `uv run raft doctor --agent <tool> --try`" |
| `tool-error` | any other Codex `turn.failed`/`error` event, or a Claude Code `result` with `is_error: true` | the tool's own message, verbatim |
| `no-output` | the tool exited at once with an empty transcript | "<tool> printed nothing. Check with `uv run raft doctor --agent <tool> --try`" |

The two recognisers seeded here come from real failures. New ones are added only with a recorded sample in
`tests/fixtures/tool-failures/`, never guessed.

When a step ends with a `Problem`:

- **Stop now.** No second try, since the same tool fails the same way. This saves up to 45 minutes per problem.
- **Say what happened.** The stop message leads with the problem, for example "Codex refused the attacker brief
  (content flagged as a possible cybersecurity risk)". It then gives the advice and the exact command to continue,
  which resumes and skips the finished steps.
- **Show it on the live page.** The page shows the problem in the step's detail, and the amber box keeps the tool's
  own line.

A step that ran fine but left the wrong files (bad extraction, holes) keeps today's behaviour: one more try, with the
problems in the brief.

## 3. An attacker brief tools don't refuse

`roles/checker-attacker.md` is rewritten as **testing the grader with decoy solutions**:

> Someone built a grader for this paper. Your job is to test it: write decoy solutions that do not do the paper's
> work but might still pass, so we find out whether the grader can tell. …

What changes:

- The job is described as testing a grader, and each try is a decoy solution that should fail. The words *attack*,
  *break*, *exploit*, *cheat* and *hack* no longer appear in the brief, which a test enforces.
- The decoy ideas list stays the same in substance: hard-coded numbers, shape-only answers, loose tolerances, ignored
  budgets, unchecked cases.

What stays the same, so no existing study changes:

- the files (`checker/attacks/<name>.py`) and `review.json` fields (`attacks`, `blocked`);
- the CLI (`raft attack`);
- the role file name.

The checker builder's brief uses the same wording for its own decoys.

The owner reruns the wu-2026 study with `--attacker codex` to confirm Codex accepts the new brief. If Codex still
refuses, §2 names the refusal and points to `--attacker claude-code`.

## 4. Transcripts without the builder's home path

Saved transcripts (`checker/transcripts/` in prepare, `transcript/` in bench entries) replace every occurrence of the
user's home directory (`str(Path.home())`) with `~`. This happens in `bench.trim_copy`, the one function both
commands use to save them. The redaction is applied to the bytes before trimming. The transcript stays valid JSONL,
because only the path text changes.

At start, `prepare` also redacts the existing transcripts of the study it works on. That fixes wu-2026 on its next
run. `raft doctor --study S` reports any transcript in S that still contains the home path.

## 5. Where is my study, and what's next

New command: `uv run raft status --study S` prints the study's stage, one line per gate, and one next command:

```
wu-2026-multimodal  (draft)
✓ paper       arXiv:2608.04234, PDF in papers/
✓ extraction  58 items, 16 missing
✓ checker     validates (4 builder decoys)
✗ tested      0 rounds; last stop: Codex refused the attacker brief (2026-10-16 12:38)
· approval    —
· gaps        —
· runs        —
Next: uv run raft prepare --study wu-2026-multimodal --agent claude-code --attacker claude-code
```

The stages, in order:
1. **paper:** `paper.yaml`, and the PDF on disk.
2. **extraction:** `validate.extraction`.
3. **checker:** `checker.validate`. This is skipped with "not checked" when `--quick` is given, because it runs the
   grader.
4. **tested:** the review rounds, and whether the last one was fully blocked.
5. **approval:** `checker.approval_state`, and whether it is committed.
6. **gaps:** `gaps.counts`.
7. **runs:** the method and run counts.

The "last stop" line comes from the newest live session for the study (`.raft/live/`), with any `Problem` recorded
there. The next command is the first unmet stage's command, using the tools that last worked.

The same next command ends:
- every `prepare` stop message (in place of today's "rerun prepare");
- the live page's stopped state;
- `prepare`'s success message.

`raft status` with no `--study` lists every study in one line each.

## Testing

- **doctor:** use fake `codex` and `claude` executables on a temporary PATH. Cover each outcome: missing, not logged
  in, a try that passes, a try that fails with the code-mode line, and a try that prints nothing. Check the cache is
  hit inside 12 hours and missed after a version change. Check that `--no-try` skips the try.
- **diagnose:** recorded samples, starting with the real wu-2026 `attack-1.jsonl` (redacted) and the run-1 stderr.
  Each sample maps to its kind; clean transcripts map to `None`.
- **prepare:** with the fake command agent emitting a refusal event, `prepare` stops after one try, and its message
  names the refusal and the switch command. The live session records the problem. A wrong-files failure still
  retries once.
- **attacker brief:** the brief has none of the five words, and the existing prepare tests still pass with it.
- **redaction:** a transcript containing the home path is saved with `~`, stays valid JSONL, and is trimmed after
  redacting. `prepare` redacts an existing study's transcripts at start.
- **status:** a draft study at each stage gives the right ✓/✗ lines and next command, `--quick` skips the grader,
  and the last-stop line comes from a fixture live session.
- **Real run (owner):** `uv run raft prepare --study wu-2026-multimodal --agent claude-code --attacker codex --watch`.

## Out of scope

- Switching tools automatically. `prepare` names the switch, and the builder decides, since it's their quota.
- Cost estimates before a run.
- New agent tools such as Gemini or OpenCode.
- Changing the CLI word `attack` or the `attacks/` folder.
- Redacting anything other than the home path (for example usernames inside tool output).

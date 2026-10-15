import json

import numpy as np
import pytest

from raft import checker, cli, schema

ANSWER = '''
import numpy as np

REFERENCE_ANSWER_PASSES = True
SKIP_MUTATIONS = {}


def reference_answer(setup):
    return {"y": np.linspace(0, 1, setup.n) ** 2}
'''

WEAK_MEASURE = '''
import numpy as np


def measure(setup, fields, reference):
    y = np.asarray(fields["y"], dtype=float)
    err = float(np.nanmax(np.abs(y))) if y.size else 0.0
    return {"samples": {}, "errors": {"y_max": err}, "tolerance": 10.0, "pass": True}
'''

ATTACK_ZEROS = '''
import numpy as np


def solve(setup):
    return {"y": np.zeros(setup.n)}
'''


def with_answer(sd, text=ANSWER):
    (sd / "checker").mkdir(exist_ok=True)
    (sd / "checker" / "answer.py").write_text(text)
    return sd


def test_good_checker_holds(tiny_study):
    with_answer(tiny_study)
    assert checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None) == []


def test_missing_answer(tiny_study):
    (holes,) = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert "checker/answer.py is missing" in holes


def test_weak_measure_is_caught_by_named_mutations(tiny_study):
    with_answer(tiny_study)
    (tiny_study / "problem" / "measure.py").write_text(WEAK_MEASURE)
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    for kind in ("nan", "inf", "wrong_shape", "zeros", "scaled", "shuffled"):
        assert any(f"mutation {kind!r} passes" in h for h in holes), kind


def test_reference_answer_must_pass_or_fail_as_declared(tiny_study):
    with_answer(tiny_study, ANSWER.replace("REFERENCE_ANSWER_PASSES = True", "REFERENCE_ANSWER_PASSES = False"))
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("the reference answer passes (expected it to fail)" in h for h in holes)


def test_measure_that_crashes_is_reported_not_raised(tiny_study):
    with_answer(tiny_study, ANSWER.replace("return {\"y\"", "raise RuntimeError('boom')\n    return {\"y\""))
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("reference_answer failed: RuntimeError: boom" in h for h in holes)


def test_skips_need_reasons_and_known_names(tiny_study):
    with_answer(tiny_study, ANSWER.replace("SKIP_MUTATIONS = {}", "SKIP_MUTATIONS = {'scaled': '', 'melt': 'x'}"))
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("SKIP_MUTATIONS['scaled'] needs a reason" in h for h in holes)
    assert any("unknown mutation 'melt'" in h for h in holes)


def test_attacks_run_through_the_runner(tiny_study):
    with_answer(tiny_study)
    (tiny_study / "checker" / "attacks").mkdir()
    (tiny_study / "checker" / "attacks" / "zeros.py").write_text(ATTACK_ZEROS)
    root = tiny_study.parents[1]
    (a,) = checker.run_attacks(root, "tiny", 60)
    assert a["name"] == "zeros" and a["blocked"] is True and a["passed"] == []
    (tiny_study / "problem" / "measure.py").write_text(WEAK_MEASURE)
    (a,) = checker.run_attacks(root, "tiny", 60)
    assert a["blocked"] is False and a["passed"] == ["4", "8"]
    assert any("attack zeros passes: 4, 8" in h for h in checker.validate(root, "tiny", 60, log=lambda s: None))


def test_bad_attack_name(tiny_study):
    with_answer(tiny_study)
    (tiny_study / "checker" / "attacks").mkdir()
    (tiny_study / "checker" / "attacks" / "Bad_Name.py").write_text(ATTACK_ZEROS)
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("Bad_Name.py: attack file names" in h for h in holes)


def test_review_must_match_schema_and_files(tiny_study):
    with_answer(tiny_study)
    (tiny_study / "checker" / "review.json").write_text(json.dumps({"study": "tiny", "builder_agent": "b",
        "attacker_agent": "a", "rounds": [{"round": 1, "attacks": [{"name": "ghost", "idea": "i", "blocked": True}]}]}))
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("review.json names attack 'ghost' but checker/attacks/ghost.py does not exist" in h for h in holes)


def test_stale_grader_copy_is_a_hole(tiny_study):
    from raft import graders
    with_answer(tiny_study)
    p = graders.add(tiny_study, "table")
    p.write_text(p.read_text() + "# edit\n")
    holes = checker.validate(tiny_study.parents[1], "tiny", 60, log=lambda s: None)
    assert any("edited after copying" in h for h in holes)


def test_mutate():
    base = {"y": np.array([1.0, 2.0, 3.0]), "label": "x", "k": 2.0}
    assert np.isnan(checker.mutate(base, "nan")["y"][0]) and base["y"][0] == 1.0
    assert checker.mutate(base, "wrong_shape")["y"].shape == (2,)
    assert checker.mutate(base, "wrong_shape")["k"].shape == (2,)
    assert checker.mutate(base, "zeros")["label"] == "x"
    assert list(checker.mutate(base, "scaled")["y"]) == [1.5, 3.0, 4.5]
    assert sorted(checker.mutate(base, "shuffled")["y"]) == [1.0, 2.0, 3.0]


def test_cli_validate(tiny_git_study, monkeypatch, capsys):
    with_answer(tiny_git_study)
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["validate"]) == 0
    assert "✓ tiny: the checker holds" in capsys.readouterr().out

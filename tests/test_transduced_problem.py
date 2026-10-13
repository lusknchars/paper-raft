"""The transduced-lm-2026 yardstick: genetic code, predicates, exact answers and grading."""
import itertools
import math
from pathlib import Path

import numpy as np
import pytest

from raft import runner

STUDY = Path(__file__).resolve().parents[1] / "studies" / "transduced-lm-2026"
setup_mod = runner.load_module(STUDY / "problem" / "setup.py", "tlm_setup")
measure_mod = runner.load_module(STUDY / "problem" / "measure.py", "tlm_measure")
REFERENCE = __import__("json").loads((STUDY / "problem" / "reference.json").read_text())


def test_genetic_code():
    code = setup_mod.GENETIC_CODE
    assert len(code) == 64 and sorted(c for c, a in code.items() if a == "*") == ["TAA", "TAG", "TGA"]
    count = lambda aa: sum(a == aa for a in code.values())
    assert (count("I"), count("M"), count("W"), count("L"), count("S"), count("R")) == (3, 1, 1, 6, 6, 6)
    assert code["ATG"] == "M" and code["GCT"] == "A" and code["TGG"] == "W"


def test_predicates():
    f = setup_mod.CodonTransducer()
    assert f.output("ATGGC") == "M" and f.output("") == ""
    assert f.is_live("", "MV") and f.is_live("AT", "MV") and f.is_live("ATGG", "MV")
    assert not f.is_live("ATA", "MV") and not f.is_live("ATGC", "MV")  # ATA = I; GCN = A, not V
    assert not f.is_member("ATGGT", "MV") and f.is_member("ATGGTA", "MV") and f.is_member("ATGGTAC", "MV")
    assert f.is_cylinder("ATGGTA", "MV") and not f.is_cylinder("ATGGT", "MV")
    assert f.is_live("ATGGTAAAA", "MV")  # already covers y: every extension does


def test_sources_are_distributions():
    for src in (setup_mod.UNIFORM, setup_mod.BIGRAM):
        for prefix in ("", "A", "C", "G", "T", "ACGT"):
            p = src.next_probs(prefix)
            assert p.shape == (5,) and np.all(p >= 0) and math.isclose(p.sum(), 1.0)
        assert src.next_probs_batch(["", "A"]).shape == (2, 5)
    assert setup_mod.UNIFORM.next_probs("A")[setup_mod.EOS] == 0.0
    assert setup_mod.BIGRAM.next_probs("A")[setup_mod.EOS] == pytest.approx(0.02)
    assert setup_mod.BIGRAM.next_probs("")[setup_mod.EOS] == 0.0


def _brute_log_z(src, f, y):
    """Sum the source prefix mass of every length-3|y| DNA string that covers y, via next_probs only."""
    total = 0.0
    for x in map("".join, itertools.product("ACGT", repeat=3 * len(y))):
        if f.is_member(x, y):
            total += math.prod(src.next_probs(x[:i])["ACGT".index(x[i])] for i in range(len(x)))
    return math.log(total)


@pytest.mark.parametrize("y", ["MVH", "MAL", "MKT", "LSR", "W"])
def test_exact_matches_brute_force(y):
    src, f = setup_mod.BIGRAM, setup_mod.CodonTransducer()
    assert measure_mod.exact_log_z(src, y, f.table) == pytest.approx(_brute_log_z(src, f, y), rel=1e-12)


def test_worst_case_closed_form():
    code = setup_mod.GENETIC_CODE
    got = measure_mod.exact_log_z(setup_mod.UNIFORM, "I" * 100, code)
    assert got == pytest.approx(100 * math.log(3) - 300 * math.log(4), rel=1e-12)
    d = [sum(a == s for a in code.values()) for s in setup_mod.WORST_MIX]
    got = measure_mod.exact_log_z(setup_mod.UNIFORM, setup_mod.WORST_MIX, code)
    assert got == pytest.approx(sum(map(math.log, d)) - 300 * math.log(4), rel=1e-12)
    assert measure_mod.exact_log_z(setup_mod.UNIFORM, "*", code) == pytest.approx(math.log(3 / 64))
    with pytest.raises(ValueError, match="longer than the source allows"):
        measure_mod.exact_log_z(setup_mod.UNIFORM, "I" * 101, code)
    with pytest.raises(ValueError, match="not in the genetic code"):
        measure_mod.exact_log_z(setup_mod.BIGRAM, "MB", code)


def test_worst_source_stops_at_300_like_appendix_e():
    assert setup_mod.UNIFORM.next_probs("A" * 299)[setup_mod.EOS] == 0.0
    assert list(setup_mod.UNIFORM.next_probs("A" * 300)) == [0, 0, 0, 0, 1]
    first_two = {}
    for codon, aa in setup_mod.GENETIC_CODE.items():
        first_two.setdefault(aa, set()).add(codon[:2])
    assert all(len(first_two[a]) == 1 for a in setup_mod.WORST_MIX) and len(setup_mod.WORST_MIX) == 100


def test_setup_and_expand():
    assert setup_mod.expand({}) == [{"case": "worst"}, {"case": "bigram"}]
    s = setup_mod.make_setup({"case": "bigram"})
    assert len(s.targets) == 3 and all(len(y) == 10 for y in s.targets) and s.beam_prune == "tau"
    assert s.m_values == (16, 64, 256) and len(s.seeds) == 128 and s.kappa == math.exp(-30) and s.epsilon == 0.0
    w = setup_mod.make_setup({"case": "worst"})
    assert w.beam_prune == "top_m" and w.kappa == 0.0 and len(w.targets) == 2
    a, b = s.rng(0, 1, 2).random(3), s.rng(0, 1, 2).random(3)
    assert np.array_equal(a, b) and not np.array_equal(a, s.rng(0, 1, 3).random(3))
    with pytest.raises(ValueError, match="case must be one of"):
        setup_mod.make_setup({"case": "text"})
    with pytest.raises(ValueError, match="unknown parameters"):
        setup_mod.make_setup({"case": "worst", "m": 4})


def _exact(s):
    return np.array([measure_mod.exact_log_z(s.source, y, s.transducer.table) for y in s.targets])


def _shape(s):
    return len(s.targets), len(s.m_values), len(s.seeds)


def _grade(case, method, log_z, particles=None):
    s = setup_mod.make_setup({"case": case})
    if particles is None:
        particles = np.broadcast_to(np.array(s.m_values, dtype=float)[None, :, None], _shape(s))
    return measure_mod.measure(s, {"log_z": log_z, "max_particles": particles}, REFERENCE, method)


def test_claim_names():
    claims = REFERENCE["cases"]["bigram"]["claims"]
    assert measure_mod.claim_for(claims, "smc-rb") == "smc-rb"
    assert measure_mod.claim_for(claims, "smc-rb-2") == "smc-rb"
    assert measure_mod.claim_for(claims, "beam-swor-adaptive-v2") == "beam-swor-adaptive"
    assert measure_mod.claim_for(claims, "beam-sworx") is None and measure_mod.claim_for(claims, "smc") is None


def test_exact_claim():
    s = setup_mod.make_setup({"case": "worst"})
    perfect = np.broadcast_to(_exact(s)[:, None, None], _shape(s))
    r = _grade("worst", "smc-rb", perfect)
    assert r["pass"] and r["errors"]["max_abs_log_error"] == 0.0 and r["tolerance"] == 1e-9
    assert not _grade("worst", "beam-swor", perfect + 1e-6)["pass"]
    assert not _grade("worst", "smc-simple", np.full(_shape(s), -np.inf))["pass"]
    assert not _grade("worst", "smc-rb", perfect, particles=np.full(_shape(s), 300.0))["pass"]


def test_top_m_share_claim():
    s = setup_mod.make_setup({"case": "worst"})
    beam = np.log(np.array(s.m_values, dtype=float))[None, :, None] - 300 * math.log(4) + np.zeros(_shape(s))
    assert _grade("worst", "beam-summing", beam)["pass"]
    perfect = np.broadcast_to(_exact(s)[:, None, None], _shape(s))
    assert not _grade("worst", "beam-summing", perfect)["pass"]  # it cannot be exact with M ≪ ∏ d


def _noisy(s, bias=1.0, seed=0, sigma=None):
    """Ẑ = Z · bias · mean-1 noise whose spread falls as M grows (Gamma, or log-normal with sigma/√(M/16))."""
    rng = np.random.default_rng(seed)
    if sigma is None:
        k = np.array(s.m_values, dtype=float)[None, :, None] / 4
        ratio = rng.gamma(k, 1 / k, size=_shape(s))
    else:
        sg = sigma / np.sqrt(np.array(s.m_values, dtype=float)[None, :, None] / 16)
        ratio = np.exp(rng.normal(-sg ** 2 / 2, sg, size=_shape(s)))
    return _exact(s)[:, None, None] + np.log(ratio * bias)


def test_unbiased_claim():
    s = setup_mod.make_setup({"case": "bigram"})
    good = _grade("bigram", "smc-rb", _noisy(s))
    assert good["pass"] and good["errors"]["max_z"] <= 4 and good["errors"]["worst_rmse_ratio"] < 1
    assert set(good["samples"]) == {f"{p}_t{i}" for p in ("rel_rmse", "sd_log_z") for i in (1, 2, 3)}
    assert _grade("bigram", "beam-swor", _noisy(s, sigma=0.3))["pass"]
    assert not _grade("bigram", "beam-swor", _noisy(s, bias=0.8))["pass"]
    assert not _grade("bigram", "smc-rb", _noisy(s, bias=0.97, sigma=0.3))["pass"]  # caught by the pooled test
    flat = _exact(s)[:, None, None] + np.log(np.random.default_rng(1).gamma(4.0, 0.25, size=_shape(s)))
    assert not _grade("bigram", "smc-simple", flat)["pass"]  # error does not fall with M
    exact = np.broadcast_to(_exact(s)[:, None, None], _shape(s))
    r = _grade("bigram", "smc-rb", exact + 1e-13)
    assert not r["pass"] and r["errors"]["min_sd_log_z"] <= 1e-3  # computing the answer is not estimating it


def test_unbiased_exact_up_to_rounding_passes_in_the_worst_case():
    s = setup_mod.make_setup({"case": "worst"})
    log_z = np.broadcast_to(_exact(s)[:, None, None] + 8e-13, _shape(s)).copy()
    log_z[:, :, ::2] = np.nextafter(log_z[:, :, ::2], 0)
    assert _grade("worst", "beam-swor-adaptive", log_z)["pass"]


def test_lower_bound_claim():
    s = setup_mod.make_setup({"case": "bigram"})
    ref = np.array([math.log(measure_mod.beam_summing_tau(s.source, s.transducer, y, s.tau)) for y in s.targets])
    share = np.exp(ref - _exact(s))
    assert np.all((share > 0.9) & (share < 1.0))
    fig1 = ref[:, None, None] + np.zeros(_shape(s))
    r = _grade("bigram", "beam-summing", fig1, particles=np.zeros(_shape(s)))
    assert r["pass"] and r["errors"]["max_rel_diff_from_fig1"] == 0.0
    assert not _grade("bigram", "beam-summing", fig1 + math.log(0.5))["pass"]       # a lower bound, but not Fig. 1
    assert not _grade("bigram", "beam-summing", np.full(_shape(s), -np.inf))["pass"]
    over = np.broadcast_to(_exact(s)[:, None, None] + 0.01, _shape(s))
    assert not _grade("bigram", "beam-summing", over)["pass"]


def test_prune_tau_keeps_the_heaviest_mass():
    pool = [("a", 0.5), ("b", 0.3), ("c", 0.15), ("d", 0.05)]
    assert [x for x, _ in measure_mod._prune_tau(pool, 0.1)] == ["a", "b", "c"]
    assert [x for x, _ in measure_mod._prune_tau(pool, 0.0)] == ["a", "b", "c", "d"]
    assert measure_mod._prune_tau([], 0.1) == []


def test_bad_output_and_unknown_method():
    s = setup_mod.make_setup({"case": "bigram"})
    with pytest.raises(ValueError, match="keys 'log_z' and 'max_particles'"):
        measure_mod.measure(s, {"log_z": 1}, REFERENCE, "smc-rb")
    with pytest.raises(ValueError, match="log_z has shape"):
        _grade("bigram", "smc-rb", np.zeros((3, 3, 8)))
    with pytest.raises(ValueError, match="NaN"):
        _grade("bigram", "smc-rb", np.full(_shape(s), np.nan))
    with pytest.raises(ValueError, match="no claim for method 'other'"):
        _grade("bigram", "other", np.zeros(_shape(s)))


def test_end_to_end_through_the_runner(tmp_path):
    """A hyphenated method folder is graded through the real runner (the bug the first review caught)."""
    import shutil
    sd = tmp_path / "studies" / "transduced-lm-2026"
    shutil.copytree(STUDY / "problem", sd / "problem")
    shutil.copy(STUDY / "paper.yaml", sd / "paper.yaml")
    (tmp_path / ".gitignore").write_text("__pycache__/\n")
    d = sd / "methods" / "smc-rb"
    d.mkdir(parents=True)
    (d / "solver.py").write_text(
        "import numpy as np\n"
        "def solve(setup):\n"
        "    shape = (len(setup.targets), len(setup.m_values), len(setup.seeds))\n"
        "    return {'log_z': np.zeros(shape), 'max_particles': np.ones(shape)}\n")
    _, results = runner.run_one(sd, "smc-rb", {"case": "worst"}, timeout=120)
    assert results["status"] == "ok" and results["pass"] is False and results["errors"]["max_abs_log_error"] > 1
    (sd / "methods" / "other").mkdir()
    (sd / "methods" / "other" / "solver.py").write_text((d / "solver.py").read_text())
    _, results = runner.run_one(sd, "other", {"case": "worst"}, timeout=120)
    assert results["status"] == "failed" and results["reason"].startswith("measure: the paper makes no claim")

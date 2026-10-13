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
    assert setup_mod.BIGRAM.next_probs("A")[setup_mod.EOS] == pytest.approx(0.002)
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
    got = measure_mod.exact_log_z(setup_mod.UNIFORM, "I" * 100, setup_mod.GENETIC_CODE)
    assert got == pytest.approx(100 * math.log(3) - 300 * math.log(4), rel=1e-12)
    assert measure_mod.exact_log_z(setup_mod.UNIFORM, "*", setup_mod.GENETIC_CODE) == pytest.approx(math.log(3 / 64))


def test_setup_and_expand():
    assert setup_mod.expand({}) == [{"case": "worst"}, {"case": "bigram"}]
    s = setup_mod.make_setup({"case": "bigram"})
    assert len(s.targets) == 3 and all(len(y) == 10 for y in s.targets) and s.beam_prune == "tau"
    assert s.m_values == (16, 64, 256) and len(s.seeds) == 64
    assert setup_mod.make_setup({"case": "worst"}).beam_prune == "top_m"
    a, b = s.rng(0, 1, 2).random(3), s.rng(0, 1, 2).random(3)
    assert np.array_equal(a, b) and not np.array_equal(a, s.rng(0, 1, 3).random(3))
    with pytest.raises(ValueError, match="case must be one of"):
        setup_mod.make_setup({"case": "text"})
    with pytest.raises(ValueError, match="unknown parameters"):
        setup_mod.make_setup({"case": "worst", "m": 4})


def _exact(s):
    return np.array([measure_mod.exact_log_z(s.source, y, s.transducer.table) for y in s.targets])


def _grade(case, method, log_z):
    s = setup_mod.make_setup({"case": case})
    return measure_mod.measure(s, {"log_z": log_z}, REFERENCE, method)


def _shape(s):
    return len(s.targets), len(s.m_values), len(s.seeds)


def test_exact_claim():
    s = setup_mod.make_setup({"case": "worst"})
    perfect = np.broadcast_to(_exact(s)[:, None, None], _shape(s))
    r = _grade("worst", "smc_rb", perfect)
    assert r["pass"] and r["errors"]["max_abs_log_error"] == 0.0 and r["tolerance"] == 1e-9
    assert not _grade("worst", "beam_swor", perfect + 1e-6)["pass"]
    assert not _grade("worst", "smc_simple", np.full(_shape(s), -np.inf))["pass"]


def test_top_m_share_claim():
    s = setup_mod.make_setup({"case": "worst"})
    beam = np.log(np.array(s.m_values, dtype=float))[None, :, None] - 300 * math.log(4) + np.zeros(_shape(s))
    assert _grade("worst", "beam_summing", beam)["pass"]
    perfect = np.broadcast_to(_exact(s)[:, None, None], _shape(s))
    assert not _grade("worst", "beam_summing", perfect)["pass"]  # it cannot be exact with M ≪ 3^100


def _noisy(s, bias=1.0, seed=0):
    """Ẑ = Z · bias · Gamma noise with mean 1 whose spread falls as M grows."""
    rng = np.random.default_rng(seed)
    k = np.array(s.m_values, dtype=float)[None, :, None] / 4
    ratio = rng.gamma(k, 1 / k, size=_shape(s)) * bias
    return _exact(s)[:, None, None] + np.log(ratio)


def test_unbiased_claim():
    s = setup_mod.make_setup({"case": "bigram"})
    good = _grade("bigram", "smc_rb", _noisy(s))
    assert good["pass"] and good["errors"]["max_z"] <= 4 and good["errors"]["worst_rmse_ratio"] < 1
    assert set(good["samples"]) == {f"{p}_{y}" for p in ("rel_rmse", "sd_log_z_8_seeds") for y in s.targets}
    assert not _grade("bigram", "beam_swor", _noisy(s, bias=0.8))["pass"]
    flat = _exact(s)[:, None, None] + np.log(np.random.default_rng(1).gamma(4.0, 0.25, size=_shape(s)))
    assert not _grade("bigram", "smc_simple", flat)["pass"]  # error does not fall with M


def test_lower_bound_claim():
    s = setup_mod.make_setup({"case": "bigram"})
    under = _exact(s)[:, None, None] + math.log(0.99) + np.zeros(_shape(s))
    r = _grade("bigram", "beam_summing", under)
    assert r["pass"] and r["errors"]["min_share"] == pytest.approx(0.99)
    assert not _grade("bigram", "beam_summing", under + 0.02)["pass"]


def test_bad_output_and_unknown_method():
    s = setup_mod.make_setup({"case": "bigram"})
    with pytest.raises(ValueError, match="must return a dict with key 'log_z'"):
        measure_mod.measure(s, {"z": 1}, REFERENCE, "smc_rb")
    with pytest.raises(ValueError, match="log_z has shape"):
        _grade("bigram", "smc_rb", np.zeros((3, 3, 8)))
    with pytest.raises(ValueError, match="NaN"):
        _grade("bigram", "smc_rb", np.full(_shape(s), np.nan))
    with pytest.raises(ValueError, match="no claim for method 'other'"):
        _grade("bigram", "other", np.zeros(_shape(s)))

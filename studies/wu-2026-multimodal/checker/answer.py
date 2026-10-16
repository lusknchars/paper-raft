"""Reference answer for wu-2026-multimodal: Algorithm 1 (weighted, on the fixed supports) with multi-start.

Population: 16 random starts (they all reach the same value). One-sample: warm start from the population optimum A*
plus 1 random start. Two-sample: A* under the 8 symmetries of the latent grid plus 1 random start. Starts run to a
loose tolerance and the lowest is refined until its plans move by less than 1e-10 (measure.best_of). Random starts
use seeds that differ from the grader's.
"""
import math
import sys
from pathlib import Path

import numpy as np

from raft import runner

_PROBLEM = Path(__file__).resolve().parents[1] / "problem"
M = runner.load_measure(_PROBLEM)

REFERENCE_ANSWER_PASSES = True
SKIP_MUTATIONS = {}


def _best(W, L, a, b, zn, Z, eps, starts):
    J, plans, _ = M.best_of(W, L, a, b, zn, Z, eps, starts)
    return J, plans


def reference_answer(setup):
    W, Z, eps = setup.gram(), setup.z, setup.eps
    zn = (Z ** 2).sum(axis=1)
    L = M._factor(W)
    rand = lambda *k: 0.1 * np.random.default_rng([555, *k]).standard_normal((L.shape[1], 2))  # noqa: E731

    a_pop = np.concatenate(setup.mu)
    pop_val, pop_plans = _best(W, L, a_pop, setup.nu, zn, Z, eps, [rand(0, s) for s in range(16)])
    Pi = np.vstack(pop_plans)
    A_star = L.T @ Pi @ Z

    nn, R = len(setup.n_values), setup.reps
    out = {k: np.zeros((nn, R)) for k in ("one_sample_values", "two_sample_values")}
    out.update({k: np.zeros((nn, R, 2, 20, 49)) for k in ("one_sample_plans", "two_sample_plans")})
    for j in range(nn):
        for r in range(R):
            for regime in ("one_sample", "two_sample"):
                a, b = M.problem(setup, regime, j, r)
                if regime == "one_sample":
                    starts = [A_star] + [rand(1, j, r)]
                else:
                    starts = [A_star @ Q for Q in M._SYM] + [rand(2, j, r)]
                val, plans = _best(W, L, a, b, zn, Z, eps, starts)
                out[f"{regime}_values"][j, r] = val
                out[f"{regime}_plans"][j, r] = np.array(plans)
    return {"population_value": pop_val, "population_plans": np.array(pop_plans), **out}


if __name__ == "__main__":  # quick look: uv run python studies/wu-2026-multimodal/checker/answer.py
    import json
    import time
    setup_mod = runner.load_module(_PROBLEM / "setup.py", "wu_setup")
    s = setup_mod.make_setup({"experiment": "rate"})
    t0 = time.time()
    ans = reference_answer(s)
    print(f"answer in {time.time() - t0:.0f}s, S = {ans['population_value']:.12f}")
    t0 = time.time()
    res = M.measure(s, ans, json.loads((_PROBLEM / "reference.json").read_text()))
    print(f"measure in {time.time() - t0:.0f}s", json.dumps({k: res[k] for k in ("errors", "pass", "samples")}, indent=1))
    sys.exit(0)

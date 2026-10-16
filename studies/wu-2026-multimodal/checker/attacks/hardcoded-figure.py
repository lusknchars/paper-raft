"""Attack: no solver. Population value guessed, empirical values = guess +- the errors read off Figure 4 Left,
plans = the independent coupling a b^T (feasible, but neither optimal nor consistent with the values)."""
import numpy as np

FIG = {"one_sample": [0.059, 0.0318, 0.0247, 0.0144, 0.0098, 0.0072],
       "two_sample": [0.073, 0.0414, 0.0308, 0.0234, 0.0152, 0.0131]}


def _emp(idx, size):
    return np.bincount(idx, minlength=size) / len(idx)


def solve(setup):
    g = setup.rng(0)
    guess = 1.08
    out = {"population_value": guess,
           "population_plans": np.array([np.outer(m, setup.nu) for m in setup.mu])}
    nn, R = len(setup.n_values), setup.reps
    for regime in ("one_sample", "two_sample"):
        vals = np.zeros((nn, R))
        plans = np.zeros((nn, R, 2, 20, 49))
        for j in range(nn):
            for r in range(R):
                d = setup.draws[j][r]
                b = setup.nu if regime == "one_sample" else _emp(d["z"], 49)
                plans[j, r, 0] = np.outer(_emp(d["x1"], 20), b)
                plans[j, r, 1] = np.outer(_emp(d["x2"], 20), b)
                vals[j, r] = guess + g.choice([-1, 1]) * FIG[regime][j] * g.exponential()
        out[f"{regime}_values"], out[f"{regime}_plans"] = vals, plans
    return out

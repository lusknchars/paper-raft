"""Attack: feasible plans (the independent coupling a b^T) and values that are exactly the objective of those plans.
Consistent and feasible, but not a fixed point of Algorithm 1 and far above the minimum."""
import numpy as np


def _emp(idx, size):
    return np.bincount(idx, minlength=size) / len(idx)


def _obj(W, plans, zn, Z):
    Pi = np.vstack(plans)
    m, q, PZ = Pi.sum(1), Pi @ zn, Pi @ Z
    return float(2 * q @ W @ m - 2 * np.sum(PZ * (W @ PZ)))  # KL of the product coupling is 0


def solve(setup):
    W, Z = setup.gram(), setup.z
    zn = (Z ** 2).sum(1)
    pop = [np.outer(m, setup.nu) for m in setup.mu]
    out = {"population_value": _obj(W, pop, zn, Z), "population_plans": np.array(pop)}
    nn, R = len(setup.n_values), setup.reps
    for regime in ("one_sample", "two_sample"):
        vals, plans = np.zeros((nn, R)), np.zeros((nn, R, 2, 20, 49))
        for j in range(nn):
            for r in range(R):
                d = setup.draws[j][r]
                b = setup.nu if regime == "one_sample" else _emp(d["z"], 49)
                p = [np.outer(_emp(d["x1"], 20), b), np.outer(_emp(d["x2"], 20), b)]
                vals[j, r], plans[j, r] = _obj(W, p, zn, Z), np.array(p)
        out[f"{regime}_values"], out[f"{regime}_plans"] = vals, plans
    return out

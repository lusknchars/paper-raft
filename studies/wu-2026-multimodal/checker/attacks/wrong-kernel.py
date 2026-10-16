"""Attack: a real multi-start Algorithm 1 on the wrong kernel: the cross-modality blocks are dropped (gamma_cross = 0),
so the two modalities are aligned independently. Feasible, consistent and stationary for the wrong objective."""
import numpy as np


def _emp(idx, size):
    return np.bincount(idx, minlength=size) / len(idx)


def _sinkhorn(C, a, b, eps, v):
    P = np.zeros_like(C)
    ra, cb = a > 0, b > 0
    Cs = C[np.ix_(ra, cb)]
    K = np.exp(-(Cs - Cs.min(1, keepdims=True)) / eps)
    aa, bb = a[ra], b[cb]
    v = np.ones(len(bb)) if v is None else v
    for it in range(100000):
        u = aa / (K @ v)
        v = bb / (K.T @ u)
        if it % 5 == 0 and np.abs(u * (K @ v) - aa).sum() < 1e-13:
            break
    P[np.ix_(ra, cb)] = u[:, None] * K * v[None]
    return P, v


def _alg1(W, a, b, Z, eps, A0):
    zn = (Z ** 2).sum(1)
    Om = W @ a
    WPZ = A0
    vs, Jp = [None, None], np.inf
    for t in range(5000):
        C = 2 * np.outer(Om, zn) - 4 * WPZ @ Z.T
        plans = []
        for i in range(2):
            P, vs[i] = _sinkhorn(C[20 * i:20 * i + 20], a[20 * i:20 * i + 20], b, eps, vs[i])
            plans.append(P)
        Pi = np.vstack(plans)
        WPZ = W @ Pi @ Z
        PZ = Pi @ Z
        kl = sum(float(np.sum(P[P > 0] * np.log(P[P > 0] / np.outer(a[20 * i:20 * i + 20], b)[P > 0])))
                 for i, P in enumerate(plans))
        J = 2 * (Pi @ zn) @ W @ Pi.sum(1) - 2 * np.sum(PZ * (W @ PZ)) + eps * kl
        if t > 0 and abs(J - Jp) / (1 + abs(Jp)) < 1e-12:
            break
        Jp = J
    return float(J), np.array(plans)


def _multi(W, a, b, Z, eps, g):
    return min((_alg1(W, a, b, Z, eps, 0.1 * g.standard_normal((40, 2))) for _ in range(3)), key=lambda x: x[0])


def solve(setup):
    W, Z, eps = setup.gram(), setup.z, setup.eps
    W[:20, 20:] = 0.0
    W[20:, :20] = 0.0
    g = setup.rng(1)
    out = {}
    out["population_value"], out["population_plans"] = _multi(W, np.concatenate(setup.mu), setup.nu, Z, eps, g)
    nn, R = len(setup.n_values), setup.reps
    for regime in ("one_sample", "two_sample"):
        vals, plans = np.zeros((nn, R)), np.zeros((nn, R, 2, 20, 49))
        for j in range(nn):
            for r in range(R):
                d = setup.draws[j][r]
                a = np.concatenate([_emp(d["x1"], 20), _emp(d["x2"], 20)])
                b = setup.nu if regime == "one_sample" else _emp(d["z"], 49)
                vals[j, r], plans[j, r] = _multi(W, a, b, Z, eps, g)
        out[f"{regime}_values"], out[f"{regime}_plans"] = vals, plans
    return out

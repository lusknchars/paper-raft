"""Attack: a real Algorithm 1, but started once from A = 0 (the closed-form update at the independent coupling, which
is zero because the latent grid is centred). On the symmetric problems it never leaves that saddle point."""
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


def _alg1(W, a, b, Z, eps):
    zn = (Z ** 2).sum(1)
    Om = W @ a
    A = np.zeros((40, 2))  # stands for L^T Pi Z; with L = full factor, L A = W Pi Z
    WPZ = np.zeros((40, 2))
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


def solve(setup):
    W, Z, eps = setup.gram(), setup.z, setup.eps
    out = {}
    out["population_value"], out["population_plans"] = _alg1(W, np.concatenate(setup.mu), setup.nu, Z, eps)
    nn, R = len(setup.n_values), setup.reps
    for regime in ("one_sample", "two_sample"):
        vals, plans = np.zeros((nn, R)), np.zeros((nn, R, 2, 20, 49))
        for j in range(nn):
            for r in range(R):
                d = setup.draws[j][r]
                a = np.concatenate([_emp(d["x1"], 20), _emp(d["x2"], 20)])
                b = setup.nu if regime == "one_sample" else _emp(d["z"], 49)
                vals[j, r], plans[j, r] = _alg1(W, a, b, Z, eps)
        out[f"{regime}_values"], out[f"{regime}_plans"] = vals, plans
    return out

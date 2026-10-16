"""Grader for wu-2026-multimodal: the parametric-rate experiment of Section 5.2 (Figure 4 Left). Methods never see it.

Every returned value must be the JK-EGW objective of a feasible plan that is a fixed point of Algorithm 1 (checked
for all 1 + 2 * 6 * reps problems). On a fixed subset of problems the grader runs its own multi-start Algorithm 1
and the method may be at most 1e-6 above the lowest value found (the population value always). The paper's claims
are then checked on the mean absolute error curves: log-log slope within 0.25 of -1/2, and every point within a
factor 2 of the values read off Figure 4 Left.
"""
import math
import numpy as np

from graders import checks, claims

BIG = 1e300
SPOT_SEED = 90417
SPOT_PER_N = 3
N_RESTART_RANDOM = 8


def _f(x) -> float:
    x = float(x)
    return BIG if not math.isfinite(x) or x > BIG else x


# ---------------------------------------------------------------- objective, Sinkhorn and Algorithm 1 (weighted)

def objective(W, plans, a, b, zn, Z, eps) -> float:
    """JK-EGW objective (Eq. 1) of stacked plans Pi (40 x 49) with target marginals a (40,), b (49,)."""
    Pi = np.vstack(plans)
    m, q, PZ = Pi.sum(axis=1), Pi @ zn, Pi @ Z
    quad = 2.0 * q @ W @ m - 2.0 * np.sum(PZ * (W @ PZ))
    ent = 0.0
    for i, P in enumerate(plans):
        ai = a[20 * i:20 * (i + 1)]
        pos = P > 0
        ref = np.outer(ai, b)[pos]
        if np.any(ref <= 0):
            return math.inf
        ent += float(np.sum(P[pos] * np.log(P[pos] / ref)))
    return float(quad + eps * ent)


def sinkhorn(C, a, b, eps, tol=1e-14, max_iter=200000, v=None):
    """Entropic plan for cost C, marginals a, b, to tol in L1 row-marginal error; zero-weight atoms get zeros.
    Returns (plan, v); pass v back in to warm-start the next solve on a nearby cost."""
    P = np.zeros_like(C)
    ra, cb = a > 0, b > 0
    Cs = C[np.ix_(ra, cb)]
    Cs = Cs - Cs.min(axis=1, keepdims=True)
    K = np.exp(-Cs / eps)
    aa, bb = a[ra], b[cb]
    v = np.ones(len(bb)) if v is None else v
    for it in range(max_iter):
        u = aa / (K @ v)
        v = bb / (K.T @ u)
        if it % 5 == 0 and np.abs(u * (K @ v) - aa).sum() < tol:
            break
    P[np.ix_(ra, cb)] = u[:, None] * K * v[None, :]
    return P, v


def step(W, plans, a, b, zn, Z, eps):
    """One Algorithm 1 iteration from the plans: A = L^T Pi Z, then exact Sinkhorn on C(A) = 2 W a |z|^2 - 4 W Pi Z Z^T."""
    C = 2.0 * np.outer(W @ a, zn) - 4.0 * W @ np.vstack(plans) @ Z @ Z.T
    return [sinkhorn(C[20 * i:20 * (i + 1)], a[20 * i:20 * (i + 1)], b, eps)[0] for i in range(2)]


def _factor(W):
    lam, U = np.linalg.eigh(W)
    lam = np.clip(lam, 0.0, None)
    return U * np.sqrt(lam)


def algorithm1(W, L, a, b, zn, Z, eps, A0, tau=1e-12, inner_tol=1e-13, t_max=20000, plan_tol=None):
    """Algorithm 1 (p. 17) with weighted marginals; returns (J, plans, A). With plan_tol, also keep going until the
    plans move by less than plan_tol (L1) in one iteration."""
    Om = L @ (L.T @ a)
    A, J_prev, plans, vs = A0, math.inf, None, [None, None]
    for t in range(t_max):
        C = 2.0 * np.outer(Om, zn) - 4.0 * L @ A @ Z.T
        prev, plans = plans, []
        for i in range(2):
            P, vs[i] = sinkhorn(C[20 * i:20 * (i + 1)], a[20 * i:20 * (i + 1)], b, eps, tol=inner_tol, v=vs[i])
            plans.append(P)
        A = L.T @ np.vstack(plans) @ Z
        J = objective(W, plans, a, b, zn, Z, eps)
        done = t > 0 and abs(J_prev - J) / (1 + abs(J_prev)) < tau
        if done and plan_tol is not None:
            done = max(float(np.abs(p - q).sum()) for p, q in zip(plans, prev)) < plan_tol
        if done:
            break
        J_prev = J
    return J, plans, A


_SYM = [np.array(q, dtype=float) for q in ([[1, 0], [0, 1]], [[-1, 0], [0, 1]], [[1, 0], [0, -1]], [[-1, 0], [0, -1]],
                                          [[0, 1], [1, 0]], [[0, -1], [1, 0]], [[0, 1], [-1, 0]], [[0, -1], [-1, 0]])]


def best_of(W, L, a, b, zn, Z, eps, starts):
    """Run every start loosely (tau 1e-8), then refine the lowest one until its plans move by less than 1e-10."""
    best = (math.inf, None, None)
    for A0 in starts:
        out = algorithm1(W, L, a, b, zn, Z, eps, A0, tau=1e-8, inner_tol=1e-10)
        if out[0] < best[0]:
            best = out
    return algorithm1(W, L, a, b, zn, Z, eps, best[2], tau=1e-13, inner_tol=1e-14, plan_tol=1e-10)


def multistart(W, a, b, zn, Z, eps, warm=None, n_random=N_RESTART_RANDOM, seed=0):
    """Lowest Algorithm 1 value over warm starts (warm @ Q for the 8 grid symmetries Q) and random starts."""
    L = _factor(W)
    starts = [warm @ Q for Q in _SYM] if warm is not None else []
    g = np.random.default_rng([SPOT_SEED, seed])
    starts += [0.1 * g.standard_normal((L.shape[1], 2)) for _ in range(n_random)]
    return best_of(W, L, a, b, zn, Z, eps, starts)


_POP_CACHE = {}


def population(setup):
    """(S_eps, plans, A*) for the population problem, from 16 random starts (they all reach one value)."""
    W, Z = setup.gram(), setup.z
    a, b, zn = np.concatenate(setup.mu), setup.nu, (Z ** 2).sum(axis=1)
    key = (a.tobytes(), b.tobytes(), W.tobytes(), float(setup.eps))
    if key not in _POP_CACHE:
        _POP_CACHE[key] = multistart(W, a, b, zn, Z, setup.eps, warm=None, n_random=16, seed=1)
    return _POP_CACHE[key]


def empirical(idx, size):
    return np.bincount(np.asarray(idx), minlength=size) / len(idx)


def problem(setup, regime, j, r):
    d = setup.draws[j][r]
    a = np.concatenate([empirical(d["x1"], 20), empirical(d["x2"], 20)])
    b = setup.nu if regime == "one_sample" else empirical(d["z"], 49)
    return a, b


# ---------------------------------------------------------------- grading

def _verify(W, plans, value, a, b, zn, Z, eps):
    """(marginal L1 error, |value - objective(plans)|, fixed-point L1 distance) for one problem."""
    if np.any(plans < -1e-15):
        return math.inf, math.inf, math.inf
    plans = [np.clip(plans[0], 0, None), np.clip(plans[1], 0, None)]
    marg = max(float(np.abs(P.sum(axis=1) - a[20 * i:20 * (i + 1)]).sum() + np.abs(P.sum(axis=0) - b).sum())
               for i, P in enumerate(plans))
    if marg > 1e-7:
        return marg, math.inf, math.inf
    J = objective(W, plans, a, b, zn, Z, eps)
    gap = abs(J - float(value)) if math.isfinite(J) else math.inf
    nxt = step(W, plans, a, b, zn, Z, eps)
    fix = max(float(np.abs(n - P).sum()) for n, P in zip(nxt, plans))
    return marg, gap, fix


def spot_cells(reps, n_n):
    g = np.random.default_rng(SPOT_SEED)
    return {regime: [(j, int(r)) for j in range(n_n) for r in g.choice(reps, size=min(SPOT_PER_N, reps), replace=False)]
            for regime in ("one_sample", "two_sample")}


def _slope(ns, errs):
    if np.any(errs <= 0) or not np.all(np.isfinite(errs)):
        return math.nan
    return float(np.polyfit(np.log(ns), np.log(errs), 1)[0])


def measure(setup, fields, reference: dict) -> dict:
    case = reference["cases"]["rate"]
    tol = reference["tolerance"]
    nn, R = len(setup.n_values), setup.reps
    keys = ("population_value", "population_plans", "one_sample_values", "one_sample_plans",
            "two_sample_values", "two_sample_plans")
    checks.require_keys(fields, keys)
    pop_val = checks.array(fields, "population_value", ())
    pop_plans = checks.array(fields, "population_plans", (2, 20, 49))
    vals = {k: checks.array(fields, f"{k}_values", (nn, R)) for k in ("one_sample", "two_sample")}
    plans = {k: checks.array(fields, f"{k}_plans", (nn, R, 2, 20, 49)) for k in ("one_sample", "two_sample")}

    W, Z, eps = setup.gram(), setup.z, setup.eps
    zn = (Z ** 2).sum(axis=1)
    ns = np.array(setup.n_values, dtype=float)
    errors, ok = {}, True

    # 1. Population: feasible, consistent, stationary, and equal to the grader's minimum.
    S, _, A_star = population(setup)
    a_pop = np.concatenate(setup.mu)
    m, g_, fx = _verify(W, pop_plans, pop_val, a_pop, setup.nu, zn, Z, eps)
    pop = claims.exact(pop_val, S, case["value_tolerance"], name="population_error")
    errors.update(pop["errors"])
    worst = {"max_marginal_error": m, "max_value_vs_plans": g_, "max_fixed_point_distance": fx}
    ok = ok and pop["pass"]

    # 2. Every empirical problem: feasible, value = objective of plans, fixed point of Algorithm 1.
    limits = {"max_marginal_error": case["marginal_tolerance"], "max_value_vs_plans": case["value_vs_plans_tolerance"],
              "max_fixed_point_distance": case["fixed_point_tolerance"]}
    ok = ok and all(worst[k] <= limits[k] for k in limits)
    cells = [(regime, j, r) for regime in ("one_sample", "two_sample") for j in range(nn) for r in range(R)]
    for regime, j, r in cells:
        if not ok:  # already failing: stop paying for the remaining checks
            break
        a, b = problem(setup, regime, j, r)
        got = _verify(W, plans[regime][j, r], vals[regime][j, r], a, b, zn, Z, eps)
        worst = {k: max(worst[k], v) for k, v in zip(limits, got)}
        ok = all(worst[k] <= limits[k] for k in limits)
    errors.update({k: _f(v) for k, v in worst.items()})

    # 3. Spot checks: no more than value_tolerance above the grader's multi-start minimum.
    excess = math.inf
    if ok:
        excess = -math.inf
        for regime, cells in spot_cells(R, nn).items():
            for j, r in cells:
                a, b = problem(setup, regime, j, r)
                best = multistart(W, a, b, zn, Z, eps, warm=A_star, seed=1000 * j + r)[0]
                excess = max(excess, float(vals[regime][j, r]) - best)
        ok = excess <= case["value_tolerance"]
    errors["max_spot_excess_over_grader_minimum"] = _f(max(excess, 0.0))

    # 4. The paper's claims on the mean absolute error curves.
    samples, ref_samples = {}, {}
    for regime in ("one_sample", "two_sample"):
        mae = np.abs(vals[regime] - S).mean(axis=1)
        paper = np.array(case["figure_4_left"][regime]["mean_abs_error"], dtype=float)
        slope = _slope(ns, mae)
        errors[f"{regime}_slope"] = _f(slope) if math.isfinite(slope) else BIG
        errors[f"{regime}_slope_minus_half"] = _f(abs(slope + 0.5)) if math.isfinite(slope) else BIG
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.abs(np.log(mae / paper))
        errors[f"{regime}_max_log_ratio_to_figure"] = _f(np.nan_to_num(ratio, nan=np.inf).max())
        ok = ok and math.isfinite(slope) and abs(slope + 0.5) <= case["slope_tolerance"] \
            and errors[f"{regime}_max_log_ratio_to_figure"] <= math.log(case["figure_factor"])
        samples[regime] = [[float(n), _f(e)] for n, e in zip(ns, mae)]
        ref_samples[regime] = [[float(n), float(e)] for n, e in zip(ns, paper)]
    errors = {k: _f(v) for k, v in errors.items()}
    return {"samples": samples, "reference_samples": ref_samples, "errors": errors, "tolerance": tol,
            "pass": bool(ok)}

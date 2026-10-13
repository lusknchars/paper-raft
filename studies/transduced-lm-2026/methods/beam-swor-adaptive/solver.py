"""beam_swor_adaptive (Snæbjarnarson et al. 2026, Fig. 1 + Fig. 2 lines 63-85, §3.4, App. B.2).

beam_summing over target prefixes (Fig. 1) whose prune is the adaptive-budget SWOR prune swor_adaptive:
the particle count m = min(M, floor(mu + 1/2)) with mu = sum_i min(1, c W_i), c = M / (rho (A_eps + W))
(Eqs. 15-17), Russian roulette when m = 0, then pps + systematic sampling with Horvitz-Thompson
reweighting. Twist psi = is_live, so twisted weights equal raw weights on every created child.
No tail-roulette decorator: the paper applies it only to the fixed-M methods (App. B.6, "Settings").

Access rules: the source is used only through next_probs; the transducer only through is_live,
is_member and is_cylinder; all randomness comes from setup.rng(i, j, k).
"""
import math

import numpy as np


class _Oracle:
    """Memoised black-box calls (results are deterministic, so caching changes no number)."""

    def __init__(self, source, transducer):
        self.source, self.fst = source, transducer
        self._probs, self._live, self._member, self._cyl = {}, {}, {}, {}

    def probs(self, x):
        p = self._probs.get(x)
        if p is None:
            p = np.asarray(self.source.next_probs(x), dtype=float)
            self._probs[x] = p
        return p

    def live(self, x, y):
        key = (x, y)
        v = self._live.get(key)
        if v is None:
            v = bool(self.fst.is_live(x, y))
            self._live[key] = v
        return v

    def member(self, x, y):
        key = (x, y)
        v = self._member.get(key)
        if v is None:
            v = bool(self.fst.is_member(x, y))
            self._member[key] = v
        return v

    def cylinder(self, x, y):
        key = (x, y)
        v = self._cyl.get(key)
        if v is None:
            v = bool(self.fst.is_cylinder(x, y))
            self._cyl[key] = v
        return v


def pps(W, m):
    """Fig. 2 lines 48-57: inclusion probabilities proportional to size with certainty set.

    W: positive twisted weights (length N > m), m >= 1. Returns pi (each in (0, 1]) and the pinned mask.
    """
    n = len(W)
    pi = np.zeros(n)
    pinned = np.zeros(n, dtype=bool)
    while True:
        free = np.flatnonzero(~pinned)
        rem = m - int(pinned.sum())
        pf = rem * W[free] / W[free].sum()
        new = pf >= 1.0
        # Rounding guard: never pin so many that no slot is left for the remaining positive weights.
        if new.any() and int(new.sum()) < rem:
            pinned[free[new]] = True
            pi[free[new]] = 1.0
            continue
        if new.any():  # rem particles carry (numerically) all the remaining mass: pin them, rest get pi = 0+
            order = free[np.argsort(-W[free], kind="stable")][:rem]
            pinned[order] = True
            pi[order] = 1.0
            free = np.flatnonzero(~pinned)
            # Only reachable through rounding; the leftover mass is O(machine eps) of the pool.
            pi[free] = 0.0
            return pi, pinned
        pi[free] = pf
        return pi, pinned


def systematic(pi, pinned, m, rng):
    """Fig. 2 lines 58-62 (Madow 1949), returning the selected indices.

    Pinned particles (pi = 1) are always selected; systematic sampling then runs over the others with
    the remaining m - |pinned| slots. Removing a unit-length interval from the systematic line shifts every
    later point by an integer, so this is the same draw as Fig. 2's over all N with a uniform permutation.
    The cumulative sum is rescaled so it ends exactly at the slot count (floating-point guard).
    """
    sel = list(np.flatnonzero(pinned))
    free = np.flatnonzero(~pinned & (pi > 0))
    k = m - len(sel)
    if k > 0 and len(free):
        perm = free[rng.permutation(len(free))]
        c = np.cumsum(pi[perm])
        c *= k / c[-1]
        u = rng.random()
        pts = u + np.arange(k)
        idx = np.searchsorted(c, pts, side="right")
        idx = np.minimum(idx, len(perm) - 1)
        sel.extend(perm[idx].tolist())
    return np.asarray(sel, dtype=int)


def swor_adaptive(xs, ws, A_eff, M, rho, rng):
    """Fig. 2 lines 63-79. Twisted weights = raw weights: every child passed in is live (psi = 1)."""
    Wt = ws  # psi = is_live = 1 on every created child
    W = float(Wt.sum())
    if W <= 0.0:
        return [], np.zeros(0)
    pos = np.flatnonzero(Wt > 0)
    c = M / (rho * (A_eff + W))
    mu = float(np.minimum(1.0, c * Wt).sum())
    m = min(M, int(math.floor(mu + 0.5)))
    if m == 0:
        if not (rng.random() < mu):
            return [], np.zeros(0)
        m = 1
        ws = ws / mu  # pps below still uses the unscaled twisted weights Wt
    if len(pos) <= m:
        return [xs[i] for i in pos], ws[pos].copy()
    pi_pos, pin_pos = pps(Wt[pos], m)
    s = systematic(pi_pos, pin_pos, m, rng)
    idx = pos[s]
    return [xs[i] for i in idx], ws[idx] / pi_pos[s]


def beam_swor_adaptive(oracle, y, M, rho, eps, rng):
    """Returns (Z_hat for the whole y, largest pool size returned by any prune)."""
    Q = [("", 1.0)]  # base case N = 0: Q' = {(eps, 1)}
    R = []
    z_prev = 1.0  # Z_hat_0 = 1 (Eq. 17)
    A = 1.0
    max_kept = 0
    for t in range(1, len(y) + 1):
        yt = y[:t]
        pool_x = [x for x, _ in Q]
        pool_w = np.array([w for _, w in Q], dtype=float)
        Q, R_new, A = [], [], 0.0
        for x, w in R:  # remainder re-check (Fig. 1 lines 9-12)
            if oracle.member(x, yt):
                R_new.append((x, w))
                A += w
        R = R_new
        while pool_x:
            cx, cw = [], []
            for x, w in zip(pool_x, pool_w):
                if oracle.cylinder(x, yt):
                    Q.append((x, w))
                    A += w
                    continue
                p = oracle.probs(x)
                if oracle.member(x, yt) and p[4] > 0.0:
                    R.append((x, w * p[4]))
                    A += w * p[4]
                for s, sym in enumerate("ACGT"):
                    if p[s] > 0.0 and w > 0.0:
                        xc = x + sym
                        if oracle.live(xc, yt):
                            cx.append(xc)
                            cw.append(w * p[s])
            if not cx:
                break
            A_eff = max(A, eps * z_prev)  # Eq. 17; only for the count/threshold
            pool_x, pool_w = swor_adaptive(cx, np.asarray(cw), A_eff, M, rho, rng)
            max_kept = max(max_kept, len(pool_x))
        z_prev = A
    return A, max_kept


def solve(setup):
    T, J, K = len(setup.targets), len(setup.m_values), len(setup.seeds)
    log_z = np.empty((T, J, K))
    max_particles = np.zeros((T, J, K), dtype=int)
    oracle = _Oracle(setup.source, setup.transducer)
    eps = float(getattr(setup, "epsilon", 0.0))
    for i, y in enumerate(setup.targets):
        for j, M in enumerate(setup.m_values):
            for k in range(K):
                rng = setup.rng(i, j, k)
                z, kept = beam_swor_adaptive(oracle, y, int(M), float(setup.rho), eps, rng)
                log_z[i, j, k] = math.log(z) if z > 0.0 else -math.inf
                max_particles[i, j, k] = kept
    return {"log_z": log_z, "max_particles": max_particles}

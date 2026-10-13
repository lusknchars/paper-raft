"""smc_simple (Snaebjarnarson et al. 2026, Fig. 10 / App. B.3): a textbook particle filter over the whole target.

M particles start at the empty source prefix with weight 1/M. At every iteration each particle draws one next
symbol (a base or EOS) from the live-restricted proposal of Eq. (33) with t = |y|:

    q(x'|x)   = p(x'|x) is_live(x x', y) / nu(x)
    q(EOS|x)  = is_member(x, y) p(EOS|x) / nu(x)
    nu(x)     = is_member(x, y) p(EOS|x) + sum_{x''} p(x''|x) is_live(x x'', y)

and multiplies its weight by p(x'|x) / q(x'|x) (Eq. 27), which equals nu(x) for every draw allowed by q. A particle
that draws EOS is completed: its weight times the potential phi(x) = is_member(x, y) is added to R (Fig. 10
lines 94-95). The other particles form P', which goes through the ESS-gated multinomial resample (Fig. 10 lines
100-105) wrapped by the tail-roulette decorator (Fig. 13, App. B.6) with threshold kappa * w0, where w0 is the
particle's weight at the start of the run (1/M). Z_hat = sum of weights in R. No cylinder shortcut: a particle
finishes only by sampling EOS.

Weights are carried in log space so the worst case (Z = 3^100 4^-300) and long walks cannot underflow.
"""
import math

import numpy as np

EOS = 4
N_SYM = 5
MAX_ITERS = 200_000  # iteration cap on the while-loop of Fig. 10; the sources stop with probability one


def _logsumexp(a: np.ndarray) -> float:
    if a.size == 0:
        return -math.inf
    m = float(np.max(a))
    if m == -math.inf:
        return -math.inf
    return m + math.log(float(np.sum(np.exp(a - m))))


class _Predicates:
    """Per-run cache of transducer predicate results (pure functions of the prefix and the fixed target)."""

    def __init__(self, transducer, y):
        self.t = transducer
        self.y = y
        self.live = {}
        self.member = {}

    def is_live(self, x: str) -> bool:
        r = self.live.get(x)
        if r is None:
            r = bool(self.t.is_live(x, self.y))
            self.live[x] = r
        return r

    def is_member(self, x: str) -> bool:
        r = self.member.get(x)
        if r is None:
            r = bool(self.t.is_member(x, self.y))
            self.member[x] = r
        return r


def _proposal(source, preds, prefixes, symbols):
    """Unnormalised proposal masses p(x'|x) * gate(x, x') for every particle, shape (n, 5).

    gate is is_live(x x', y) for a base and is_member(x, y) for EOS (Eq. 33). Predicates are only evaluated where
    the source mass is positive, since a zero source mass makes the product zero anyway.
    """
    probs = np.asarray(source.next_probs_batch(prefixes), dtype=float).reshape(-1, N_SYM)
    mass = np.zeros_like(probs)
    for i, x in enumerate(prefixes):
        row = probs[i]
        for s in range(4):
            if row[s] > 0.0 and preds.is_live(x + symbols[s]):
                mass[i, s] = row[s]
        if row[EOS] > 0.0 and preds.is_member(x):
            mass[i, EOS] = row[EOS]
    return mass


def _resample(rng, logw, eta):
    """ESS-gated multinomial resample (Fig. 10 lines 100-105). Returns (indices, new log weights)."""
    n = logw.size
    if n == 0:
        return np.arange(0), logw
    m = float(np.max(logw))
    w = np.exp(logw - m)
    s1 = float(np.sum(w))
    s2 = float(np.sum(w * w))
    if s1 * s1 >= eta * n * s2:  # ESS >= eta |P|: return P unchanged
        return np.arange(n), logw
    idx = rng.choice(n, size=n, replace=True, p=w / s1)
    mean_log = m + math.log(s1) - math.log(n)  # every weight reset to the pool mean
    return idx, np.full(n, mean_log)


def _tail_roulette(rng, logw, logw0, log_kappa):
    """Fig. 13: particles with w < kappa w0 survive with probability 1/2 at doubled weight. Returns keep mask, logw."""
    n = logw.size
    keep = np.isfinite(logw)  # w = 0 particles are skipped (dropped)
    if log_kappa == -math.inf or n == 0:  # kappa = 0: the decorator never fires
        return keep, logw
    light = keep & (logw < log_kappa + logw0)
    k = int(np.count_nonzero(light))
    if k == 0:
        return keep, logw
    coins = rng.random(k) < 0.5
    logw = logw.copy()
    li = np.flatnonzero(light)
    keep[li[~coins]] = False
    logw[li[coins]] += math.log(2.0)
    return keep, logw


def smc_simple(source, transducer, y, m, rng, eta, kappa):
    """One run of Fig. 10 for target y with M = m particles. Returns (log Z_hat, max particles after a prune)."""
    symbols = source.alphabet
    preds = _Predicates(transducer, y)
    log_kappa = math.log(kappa) if kappa > 0 else -math.inf

    prefixes = [""] * m
    logw = np.full(m, -math.log(m))
    logw0 = logw.copy()  # w0: weight at the start of the run (App. B.6, no target-prefix calls in Fig. 10)
    completed = []  # log weights of R (phi already applied)
    max_particles = 0

    it = 0
    while prefixes:
        it += 1
        if it > MAX_ITERS:
            raise RuntimeError(f"did not converge: smc_simple pool still holds {len(prefixes)} particles "
                               f"after {MAX_ITERS} iterations")
        mass = _proposal(source, preds, prefixes, symbols)
        nu = mass.sum(axis=1)
        alive = nu > 0.0  # nu = 0: the proposal is undefined and the particle carries no target mass; drop it
        q = np.zeros_like(mass)
        q[alive] = mass[alive] / nu[alive, None]
        cdf = np.cumsum(q, axis=1)
        u = rng.random(len(prefixes))
        draw = np.minimum((u[:, None] >= cdf).sum(axis=1), N_SYM - 1)
        # guard against a draw landing on a zero-probability symbol through rounding at the top of the cdf
        for i in np.flatnonzero(alive & (q[np.arange(len(prefixes)), draw] == 0.0)):
            draw[i] = int(np.flatnonzero(q[i] > 0.0)[-1])

        new_prefixes, new_logw, new_logw0 = [], [], []
        for i, x in enumerate(prefixes):
            if not alive[i]:
                continue
            lw = logw[i] + math.log(nu[i])  # Eq. 27: p(x'|x) / q(x'|x) = nu(x) for any draw with q > 0
            s = int(draw[i])
            if s == EOS:
                if preds.is_member(x):  # potential phi(x) = is_member(x, y)
                    completed.append(lw)
            else:
                new_prefixes.append(x + symbols[s])
                new_logw.append(lw)
                new_logw0.append(logw0[i])

        lw_arr = np.asarray(new_logw, dtype=float)
        lw0_arr = np.asarray(new_logw0, dtype=float)
        idx, lw_arr = _resample(rng, lw_arr, eta)
        lw0_arr = lw0_arr[idx]  # resampled copies inherit w0
        keep, lw_arr = _tail_roulette(rng, lw_arr, lw0_arr, log_kappa)
        prefixes = [new_prefixes[j] for j, k in zip(idx, keep) if k]
        logw = lw_arr[keep]
        logw0 = lw0_arr[keep]
        max_particles = max(max_particles, len(prefixes))

    return _logsumexp(np.asarray(completed, dtype=float)), max_particles


def solve(setup):
    shape = (len(setup.targets), len(setup.m_values), len(setup.seeds))
    log_z = np.empty(shape)
    max_particles = np.zeros(shape, dtype=int)
    for i, y in enumerate(setup.targets):
        for j, m in enumerate(setup.m_values):
            for k in range(len(setup.seeds)):
                lz, mp = smc_simple(setup.source, setup.transducer, y, int(m), setup.rng(i, j, k),
                                    setup.eta, setup.kappa)
                log_z[i, j, k] = lz
                max_particles[i, j, k] = mp
    return {"log_z": log_z, "max_particles": max_particles}

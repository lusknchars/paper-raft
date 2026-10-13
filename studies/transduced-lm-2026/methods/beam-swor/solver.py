"""beam_swor (arXiv 2608.27428, Fig. 1 + Fig. 2, App. B.6): beam summing over the quotient-remainder
decomposition whose prune draws M distinct survivors without replacement (pps + systematic sampling) with
Horvitz-Thompson reweighting, composed with the tail-roulette decorator.

Particles are triples (x, w, w0): source prefix, weight, and the weight at the start of the current
target-prefix call (the tail-roulette reference). The twist is psi = is_live relative to the target prefix
of the current call, so every pooled child has psi = 1 and twisted weights equal raw weights.

The source is used only through next_probs_batch and the transducer only through is_live, is_member and
is_cylinder. Predicate results and source conditionals are cached by exact (prefix, target) strings.
"""
import math

import numpy as np

SYMBOLS = "ACGT"
EOS = 4
PIN_TOL = 1e-12      # pps: pin a child whose inclusion probability is within this of 1
CACHE_LIMIT = 2_000_000


class _Oracle:
    """Memoised access to the source conditionals and transducer predicates (exact-key caches only)."""

    def __init__(self, source, transducer):
        self.source, self.fst = source, transducer
        self.probs, self.live, self.member, self.cyl = {}, {}, {}, {}

    def _trim(self):
        for c in (self.probs, self.live, self.member, self.cyl):
            if len(c) > CACHE_LIMIT:
                c.clear()

    def next_probs(self, prefixes):
        self._trim()
        missing = [p for p in prefixes if p not in self.probs]
        if missing:
            rows = np.asarray(self.source.next_probs_batch(missing), dtype=float).reshape(-1, 5)
            for p, r in zip(missing, rows):
                self.probs[p] = r
        return np.array([self.probs[p] for p in prefixes]).reshape(-1, 5)

    def is_live(self, x, y):
        k = (x, y)
        v = self.live.get(k)
        if v is None:
            v = self.live[k] = bool(self.fst.is_live(x, y))
        return v

    def is_member(self, x, y):
        k = (x, y)
        v = self.member.get(k)
        if v is None:
            v = self.member[k] = bool(self.fst.is_member(x, y))
        return v

    def is_cylinder(self, x, y):
        k = (x, y)
        v = self.cyl.get(k)
        if v is None:
            v = self.cyl[k] = bool(self.fst.is_cylinder(x, y))
        return v


def pps(W, m):
    """Fig. 2 lines 48-57: inclusion probabilities pi_i = min(1, c W_i) summing to m (W >= 0, m >= 1).

    Returns (pi, certain) where certain marks the pinned children (pi = 1 exactly)."""
    W = np.asarray(W, dtype=float)
    pi = np.zeros_like(W)
    certain = np.zeros(W.shape, dtype=bool)
    while True:
        free = ~certain
        rest = m - int(certain.sum())
        tot = W[free].sum()
        if rest <= 0 or tot <= 0:
            break
        pi[free] = rest * W[free] / tot
        new = free & (pi >= 1.0 - PIN_TOL)
        if not new.any():
            break
        certain |= new
        pi[new] = 1.0
    return pi, certain


def systematic(pi, certain, m, rng):
    """Fig. 2 lines 58-62: Madow's systematic sampling of exactly m indices with inclusion probabilities pi.

    Certain children (pi = 1) are always selected; in exact arithmetic an interval of length one always holds
    exactly one point u + k, so drawing the rest by systematic sampling over the non-certain children (same
    random order, same u) is the same design. Cumulative sums are anchored to their exact total so rounding
    can never change the sample size."""
    n = len(pi)
    perm = rng.permutation(n)
    u = rng.random()
    sel = [int(i) for i in perm if certain[i]]
    order = np.array([i for i in perm if not certain[i]], dtype=int)
    m_rest = m - len(sel)
    if m_rest > 0 and order.size:
        C = np.concatenate(([0.0], np.cumsum(pi[order])))
        C = np.minimum(C, float(m_rest))
        C[-1] = float(m_rest)
        counts = np.ceil(C[1:] - u) - np.ceil(C[:-1] - u)
        if counts.max() > 1 or int(counts.sum()) != m_rest:
            raise RuntimeError("systematic sampling produced an invalid sample")
        sel.extend(int(i) for i in order[counts > 0])
    return sel


def swor(pool, M, rng):
    """Fig. 2 lines 40-47 under psi = is_live (every pooled child is live, so W = w)."""
    W = np.array([w for _, w, _ in pool], dtype=float)
    pos = np.flatnonzero(W > 0)
    if pos.size <= M:
        return [pool[i] for i in pos]
    pi, certain = pps(W, M)
    S = systematic(pi, certain, M, rng)
    return [(pool[i][0], pool[i][1] / pi[i], pool[i][2]) for i in S]


def tail_roulette(pool, kappa, rng):
    """Fig. 13: drop a light particle (w < kappa w0) with probability 1/2, else double its weight."""
    out = []
    for x, w, w0 in pool:
        if w == 0:
            continue
        if w >= kappa * w0:
            out.append((x, w, w0))
            continue
        if rng.random() < 0.5:
            out.append((x, 2.0 * w, w0))
    return out


def beam_swor(y, M, kappa, oracle, rng):
    """Fig. 1 with prune = with_tail_roulette(swor_{M,psi}, kappa); iterative over target prefixes.

    Returns (Z_hat list over positions, largest pool size after any prune)."""
    Q = [("", 1.0)]          # N = 0 base case: the single particle (eps, 1)
    R = []
    z_hat = []
    max_kept = 0
    for t in range(1, len(y) + 1):
        yt = y[:t]
        pool = [(x, w, w) for x, w in Q]      # w0 = w at the start of the call
        Q, R_new, A = [], [], 0.0
        for x, w in R:                        # remainder re-check (lines 9-12)
            if oracle.is_member(x, yt):
                R_new.append((x, w))
                A += w
        R = R_new
        while pool:
            parents = []
            for x, w, w0 in pool:
                if oracle.is_cylinder(x, yt):
                    Q.append((x, w))
                    A += w
                    continue
                parents.append((x, w, w0))
            if not parents:
                break
            probs = oracle.next_probs([x for x, _, _ in parents])
            children = []
            for (x, w, w0), p in zip(parents, probs):
                if oracle.is_member(x, yt):   # remainder: stop branch added directly, particle still extended
                    rw = w * p[EOS]
                    if rw > 0:
                        R.append((x, rw))
                        A += rw
                for s, sym in enumerate(SYMBOLS):
                    xs = x + sym
                    if oracle.is_live(xs, yt):
                        children.append((xs, w * p[s], w0))
            pool = swor(children, M, rng)
            if kappa > 0:
                pool = tail_roulette(pool, kappa, rng)
            max_kept = max(max_kept, len(pool))
        z_hat.append(A)
    return z_hat, max_kept


def solve(setup):
    nt, nm, ns = len(setup.targets), len(setup.m_values), len(setup.seeds)
    log_z = np.full((nt, nm, ns), -np.inf)
    max_particles = np.zeros((nt, nm, ns), dtype=int)
    oracle = _Oracle(setup.source, setup.transducer)
    kappa = float(setup.kappa)
    for i, y in enumerate(setup.targets):
        for j, M in enumerate(setup.m_values):
            for k in range(ns):
                rng = setup.rng(i, j, k)
                z_hat, kept = beam_swor(y, int(M), kappa, oracle, rng)
                z = z_hat[-1]
                log_z[i, j, k] = math.log(z) if z > 0 else -np.inf
                max_particles[i, j, k] = kept
    return {"log_z": log_z, "max_particles": max_particles}

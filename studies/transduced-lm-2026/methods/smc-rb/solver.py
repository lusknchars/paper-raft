"""smc_rb (Snæbjarnarson et al. 2026, App. B.4, Fig. 12) with the live twist, ESS-gated multinomial
resampling (Fig. 12 lines 136-143) and the tail-roulette decorator (Fig. 13).

The recursion over target prefixes (Fig. 12 lines 106-135) is unrolled into a loop over t = 1..|y|: call t
starts from the quotient Q and remainder R returned by call t-1 (call 0 returns M copies of (eps, 1/M)).
Weights are kept in log space so the worst case's ~e^-420 weights never underflow.
"""
import math

import numpy as np

N_SYM = 4      # source symbols A, C, G, T; next_probs index 4 is EOS
EOS = 4


def _logsumexp(a):
    a = np.asarray(a, dtype=float)
    if a.size == 0:
        return -math.inf
    m = float(np.max(a))
    if m == -math.inf:
        return -math.inf
    return m + math.log(float(np.sum(np.exp(a - m))))


class _Oracle:
    """Memoised access to the black-box source and the transducer predicates (results are deterministic)."""

    def __init__(self, setup):
        self.source = setup.source
        self.fst = setup.transducer
        self.alphabet = self.source.alphabet
        self._probs = {}
        self._live = {}
        self._member = {}
        self._cyl = {}

    _LIMIT = 1_000_000

    def _trim(self):
        if len(self._live) > self._LIMIT:
            self._probs.clear(); self._live.clear(); self._member.clear(); self._cyl.clear()

    def next_probs(self, x):
        p = self._probs.get(x)
        if p is None:
            p = np.asarray(self.source.next_probs(x), dtype=float)
            self._probs[x] = p
        return p

    def is_live(self, x, y):
        k = (x, y)
        v = self._live.get(k)
        if v is None:
            v = bool(self.fst.is_live(x, y))
            self._live[k] = v
        return v

    def is_member(self, x, y):
        k = (x, y)
        v = self._member.get(k)
        if v is None:
            v = bool(self.fst.is_member(x, y))
            self._member[k] = v
        return v

    def is_cylinder(self, x, y):
        k = (x, y)
        v = self._cyl.get(k)
        if v is None:
            v = bool(self.fst.is_cylinder(x, y))
            self._cyl[k] = v
        return v

    def live_children(self, x, y):
        """psi(x x') for x' in the source alphabet (live twist), as a float 0/1 vector."""
        self._trim()
        return np.array([1.0 if self.is_live(x + a, y) else 0.0 for a in self.alphabet])


def _resample(xs, lw, lw0, eta, rng):
    """resample_{psi,eta} of Fig. 12 lines 136-143 under the live twist (psi = 1 on every pool member).

    Returns the pool unchanged when V^2 >= eta N sum W^2, else N iid multinomial draws, each carrying
    V w^(j) / (N W^(j)) = V / N. Copies inherit their ancestor's w0 (App. B.6).
    """
    n = len(xs)
    if n == 0:
        return xs, lw, lw0
    log_v = _logsumexp(lw)
    if log_v == -math.inf:
        return [], np.empty(0), np.empty(0)
    log_sq = _logsumexp(2.0 * lw)
    if 2.0 * log_v >= math.log(eta) + math.log(n) + log_sq:
        return xs, lw, lw0
    probs = np.exp(lw - log_v)
    cdf = np.cumsum(probs)
    cdf /= cdf[-1]
    u = rng.random(n)
    idx = np.minimum(np.searchsorted(cdf, u, side="right"), n - 1)
    new_lw = np.full(n, log_v - math.log(n))
    return [xs[j] for j in idx], new_lw, lw0[idx].copy()


def _tail_roulette(xs, lw, lw0, log_kappa, rng):
    """Fig. 13: drop zero weights; a particle with w < kappa w0 survives with prob. 1/2 at weight 2w."""
    keep_x, keep_w, keep_w0 = [], [], []
    for x, w, w0 in zip(xs, lw, lw0):
        if w == -math.inf:
            continue
        if log_kappa == -math.inf or w >= log_kappa + w0:
            keep_x.append(x); keep_w.append(w); keep_w0.append(w0)
            continue
        if rng.random() < 0.5:
            keep_x.append(x); keep_w.append(w + math.log(2.0)); keep_w0.append(w0)
    return keep_x, np.array(keep_w, dtype=float), np.array(keep_w0, dtype=float)


def smc_rb(oracle, y, m, eta, kappa, rng):
    """One run of smc_rb for target y with M = m particles. Returns (log Z_hat_{|y|}, max particles kept)."""
    log_kappa = math.log(kappa) if kappa > 0 else -math.inf
    # Call for N = 0 (Fig. 12 line 109): M copies of (eps, 1/M), no remainder.
    q_x = [""] * m
    q_lw = np.full(m, -math.log(m))
    r_x, r_lw = [], []
    z_hat = []
    max_kept = 0
    for t in range(1, len(y) + 1):
        yt = y[:t]
        # Lines 112-117: pool <- Queue(Q'); remainder re-check.
        pool_x, pool_lw = list(q_x), np.array(q_lw, dtype=float)
        pool_lw0 = pool_lw.copy()               # App. B.6: w0 = w at the start of each target-prefix call
        new_qx, new_qlw, new_rx, new_rlw = [], [], [], []
        a_terms = []                            # log of every term added to the running total A
        for x, w in zip(r_x, r_lw):
            if oracle.is_member(x, yt):
                new_rx.append(x); new_rlw.append(w); a_terms.append(w)
        # Lines 118-133.
        while pool_x:
            ch_x, ch_lw, ch_lw0 = [], [], []
            for x, w, w0 in zip(pool_x, pool_lw, pool_lw0):
                if oracle.is_cylinder(x, yt):
                    new_qx.append(x); new_qlw.append(w); a_terms.append(w)
                    continue
                p = oracle.next_probs(x)
                if oracle.is_member(x, yt):
                    # Stop branch added directly (Rao-Blackwellised); zero when p(EOS|x) = 0.
                    if p[EOS] > 0:
                        rw = w + math.log(p[EOS])
                        new_rx.append(x); new_rlw.append(rw); a_terms.append(rw)
                psi = oracle.live_children(x, yt)
                mass = p[:N_SYM] * psi
                lam = float(mass.sum())
                if lam <= 0.0:
                    continue
                cdf = np.cumsum(mass / lam)
                j = int(np.searchsorted(cdf, rng.random() * cdf[-1], side="right"))
                j = min(j, N_SYM - 1)
                while mass[j] <= 0.0:          # guard against landing on a zero-mass symbol by rounding
                    j -= 1
                # w <- w * lambda / psi(x x'), psi = 1 for the sampled live child (Eq. 38).
                ch_x.append(x + oracle.alphabet[j]); ch_lw.append(w + math.log(lam)); ch_lw0.append(w0)
            ch_lw = np.array(ch_lw, dtype=float)
            ch_lw0 = np.array(ch_lw0, dtype=float)
            # Line 133: P <- prune(P', A), prune = with_tail_roulette(resample_{psi,eta}, kappa).
            pool_x, pool_lw, pool_lw0 = _resample(ch_x, ch_lw, ch_lw0, eta, rng)
            pool_x, pool_lw, pool_lw0 = _tail_roulette(pool_x, pool_lw, pool_lw0, log_kappa, rng)
            max_kept = max(max_kept, len(pool_x))
        z_hat.append(_logsumexp(a_terms))        # line 134
        q_x, q_lw, r_x, r_lw = new_qx, np.array(new_qlw, dtype=float), new_rx, new_rlw
    return z_hat[-1], max_kept


def solve(setup):
    oracle = _Oracle(setup)
    shape = (len(setup.targets), len(setup.m_values), len(setup.seeds))
    log_z = np.full(shape, -np.inf)
    max_particles = np.zeros(shape, dtype=int)
    for i, y in enumerate(setup.targets):
        for j, m in enumerate(setup.m_values):
            for k in range(len(setup.seeds)):
                rng = setup.rng(i, j, k)
                log_z[i, j, k], max_particles[i, j, k] = smc_rb(oracle, y, int(m), setup.eta, setup.kappa, rng)
    return {"log_z": log_z, "max_particles": max_particles}

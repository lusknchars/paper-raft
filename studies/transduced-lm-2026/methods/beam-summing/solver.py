"""beam_summing (Fig. 1, §3.1 of arXiv:2608.27428) with the deterministic prunes prune_M and prune_tau.

The recursion over target prefixes (Fig. 1 lines 1-27) is unrolled into a loop over t = 1..|y|: the call for
y_{<=t} starts its pool from the quotient entries of the call for y_{<t}, re-checks that call's remainder
entries, then repeatedly extends every non-cylinder particle by every live source symbol and prunes the child
pool, adding cylinder weights and member stop weights to the running total A. When the pool empties, A is
Z_hat_t (Eq. 6). The estimate for the whole target is Z_hat_{|y|}.

The method is deterministic: no random numbers are drawn, so every seed slot holds the same value.
The source is touched only through ``next_probs_batch``; the transducer only through its predicates.
"""
import math

import numpy as np

N_SYMBOLS = 4  # source alphabet A, C, G, T; next_probs index 4 is EOS
EOS = 4


def _stable_desc_order(weights):
    """Indices sorting weights descending; ties keep insertion order (pool order, then A, C, G, T)."""
    return np.argsort(-np.asarray(weights, dtype=float), kind="stable")


def prune_m(children, m):
    """Fig. 1 lines 28-31: keep the min(M, N) heaviest particles unchanged."""
    if not children:
        return []
    order = _stable_desc_order([w for _, w in children])
    return [children[i] for i in order[:m]]


def prune_tau(children, tau):
    """Fig. 1 lines 32-39: keep the heaviest particles holding at least 1 - tau of the pool's mass."""
    if not children:
        return []
    w = np.array([w for _, w in children], dtype=float)
    order = np.argsort(-w, kind="stable")
    cum = np.cumsum(w[order])
    # k = smallest i (1-based) with W_i >= (1 - tau) W_N; exact float comparison. i = N always qualifies.
    k = int(np.argmax(cum >= (1.0 - tau) * cum[-1])) + 1
    return [children[i] for i in order[:k]]


class _Oracle:
    """Caches next_probs per source prefix and the predicates per (prefix, target prefix)."""

    def __init__(self, source, transducer):
        self.source = source
        self.f = transducer
        self._probs = {}
        self._live = {}
        self._member = {}
        self._cyl = {}

    def probs(self, prefixes):
        missing = [x for x in dict.fromkeys(prefixes) if x not in self._probs]
        if missing:
            rows = np.asarray(self.source.next_probs_batch(missing), dtype=float).reshape(-1, N_SYMBOLS + 1)
            for x, row in zip(missing, rows):
                self._probs[x] = row
        return [self._probs[x] for x in prefixes]

    def is_live(self, x, y):
        key = (x, y)
        v = self._live.get(key)
        if v is None:
            v = self._live[key] = bool(self.f.is_live(x, y))
        return v

    def is_member(self, x, y):
        key = (x, y)
        v = self._member.get(key)
        if v is None:
            v = self._member[key] = bool(self.f.is_member(x, y))
        return v

    def is_cylinder(self, x, y):
        key = (x, y)
        v = self._cyl.get(key)
        if v is None:
            v = self._cyl[key] = bool(self.f.is_cylinder(x, y))
        return v


def beam_summing(y, oracle, prune, alphabet):
    """Return (Z_hat list over target positions, largest pool size kept after any prune)."""
    quotient = [("", 1.0)]  # base case N = 0: Q' = {(eps, 1)}, R' = {}
    remainder = []
    z_hat = []
    max_kept = 0
    for t in range(1, len(y) + 1):
        yt = y[:t]
        pool = list(quotient)
        q_new, r_new = [], []
        a = 0.0
        # Remainder re-check (Fig. 1 lines 9-12): weights already carry their stop factor.
        for x, w in remainder:
            if oracle.is_member(x, yt):
                r_new.append((x, w))
                a += w
        while pool:
            children = []
            rows = oracle.probs([x for x, _ in pool if not oracle.is_cylinder(x, yt)])
            r_i = 0
            for x, w in pool:
                if oracle.is_cylinder(x, yt):
                    q_new.append((x, w))
                    a += w
                    continue
                p = rows[r_i]
                r_i += 1
                if oracle.is_member(x, yt):
                    # Zero-mass convention: the summand is zero when p(EOS|x) = 0.
                    ws = w * p[EOS]
                    r_new.append((x, ws))
                    a += ws
                for s in range(N_SYMBOLS):
                    xx = x + alphabet[s]
                    if oracle.is_live(xx, yt):  # psi = is_live gates the extension (line 23)
                        children.append((xx, w * p[s]))
            pool = prune(children, a)
            max_kept = max(max_kept, len(pool))
        z_hat.append(a)
        quotient, remainder = q_new, r_new
    return z_hat, max_kept


def solve(setup):
    n_t, n_m, n_s = len(setup.targets), len(setup.m_values), len(setup.seeds)
    log_z = np.empty((n_t, n_m, n_s))
    max_particles = np.zeros((n_t, n_m, n_s), dtype=np.int64)
    alphabet = getattr(setup.source, "alphabet", "ACGT")
    oracle = _Oracle(setup.source, setup.transducer)
    for i, y in enumerate(setup.targets):
        tau_result = None
        for j, m in enumerate(setup.m_values):
            if setup.beam_prune == "top_m":
                z_hat, kept = beam_summing(y, oracle, lambda c, a, m=int(m): prune_m(c, m), alphabet)
            elif setup.beam_prune == "tau":
                if tau_result is None:  # M is unused by prune_tau: one run serves every M
                    tau_result = beam_summing(y, oracle, lambda c, a: prune_tau(c, setup.tau), alphabet)
                z_hat, kept = tau_result
            else:
                raise ValueError(f"unknown beam_prune {setup.beam_prune!r}")
            z = z_hat[-1]
            log_z[i, j, :] = math.log(z) if z > 0 else -math.inf
            max_particles[i, j, :] = kept
    return {"log_z": log_z, "max_particles": max_particles}

"""Shared measurement for transduced-lm-2026. Read-only; methods never import or read it.

Each method is graded against the claim the paper makes for it in the run's case (``reference.json``,
``cases.<case>.claims``, keyed by method name; ``smc-rb-2`` is graded as ``smc-rb``):

- ``exact``: every estimate equals the true value (Appendix E): max |log Ẑ − log Z| ≤ the case tolerance.
- ``top_m_share``: beam search with prune_M keeps exactly min(M, ∏ d_t) of the ∏ d_t equally likely covering
  strings (Appendix E, Eq. 49): max |log Ẑ − log(min(M, ∏ d_t) · 4^-3T)| ≤ the case tolerance.
- ``unbiased`` (§3.3, §4.3, Fig. 9a): for every target and M, the seed average of Ẑ/Z is within 1e-9 of 1 or
  within ``z_max`` standard errors of it; a pooled test over all cells is within ``z_max`` too; the relative RMSE
  at the largest M is below that at the smallest M for every target; and where the case requires it, the seeds
  really differ: the between-seed std of Ẑ/Z exceeds ``min_spread`` in every cell (an estimator, not an exact
  computation). Estimates of zero are legitimate (a run the tail roulette ended) and count in every test.
- ``lower_bound``: beam summing with prune_τ (Fig. 1) only discards mass, so Ẑ ≤ Z; and it is the specific
  deterministic algorithm of Fig. 1, so Ẑ matches this module's own run of it within ``beam_rtol``.

Every claim except ``lower_bound`` also needs ``max_particles ≤ M``.
"""
import math
import warnings

import numpy as np


def exact_log_z(source, target: str, table: dict) -> float:
    """log p_Y→(target): forward path sum over codons, the state being the last base (Appendix D)."""
    max_len = getattr(source, "_max_len", None)
    if max_len is not None and 3 * len(target) > max_len:
        raise ValueError(f"target of length {len(target)} is longer than the source allows")
    start, trans = source._start, source._trans
    codons = {}
    for codon, amino in table.items():
        codons.setdefault(amino, []).append(codon)
    idx = {b: i for i, b in enumerate("ACGT")}
    alpha, log_scale = None, 0.0
    for t, amino in enumerate(target):
        if amino not in codons:
            raise ValueError(f"target symbol {amino!r} is not in the genetic code")
        nxt = np.zeros(4)
        for codon in codons[amino]:
            a, b, c = (idx[ch] for ch in codon)
            tail = trans[a, b] * trans[b, c]
            nxt[c] += (start[a] if t == 0 else alpha @ trans[:, a]) * tail
        total = nxt.sum()
        if total == 0.0:
            return -math.inf
        alpha, log_scale = nxt / total, log_scale + math.log(total)
    return log_scale


def beam_summing_tau(source, transducer, target: str, tau: float) -> float:
    """The prior work's beam summing with prune_τ (Fig. 1), deterministic; returns Ẑ for the whole target.

    With this transducer every member is a cylinder, so the remainder stays empty.
    """
    quotient, z = [("", 1.0)], 0.0
    for t in range(1, len(target) + 1):
        y = target[:t]
        queue, found, total = quotient, [], 0.0
        while queue:
            children = []
            for x, w in queue:
                if transducer.is_cylinder(x, y):
                    found.append((x, w))
                    total += w
                    continue
                p = source.next_probs(x)
                for s, sym in enumerate("ACGT"):
                    if p[s] > 0 and transducer.is_live(x + sym, y):
                        children.append((x + sym, w * p[s]))
            queue = _prune_tau(children, tau)
        quotient, z = found, total
    return z


def _prune_tau(pool, tau):
    if not pool:
        return []
    pool = sorted(pool, key=lambda pw: -pw[1])
    cum = np.cumsum([w for _, w in pool])
    k = int(np.searchsorted(cum, (1 - tau) * cum[-1], side="left")) + 1
    return pool[:min(k, len(pool))]


def check_output(setup, fields) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(fields, dict) or not {"log_z", "max_particles"} <= set(fields):
        raise ValueError("solve() must return a dict with keys 'log_z' and 'max_particles'")
    shape = (len(setup.targets), len(setup.m_values), len(setup.seeds))
    out = []
    for key in ("log_z", "max_particles"):
        a = np.asarray(fields[key], dtype=float)
        if a.shape != shape:
            raise ValueError(f"{key} has shape {a.shape}, expected {shape}")
        if np.isnan(a).any() or np.isposinf(a).any():
            raise ValueError(f"{key} contains NaN or +inf")
        out.append(a)
    return out[0], out[1]


def claim_for(claims: dict, method: str):
    """The claim for ``method``: an exact key, else the longest key that ``method`` extends with a '-suffix'."""
    if method in claims:
        return method
    keys = [k for k in claims if method.startswith(k + "-")]
    return max(keys, key=len) if keys else None


def _pairs(xs, ys) -> list[list[float]]:
    return [[float(a), float(b)] for a, b in zip(xs, ys)]


def _finite(x: float) -> float:
    """JSON has no infinity or NaN; map both to a large number so errors stay valid and still fail."""
    return 1e300 if math.isnan(x) else float(min(x, 1e300))


def measure(setup, fields, reference: dict, method: str) -> dict:
    log_z, particles = check_output(setup, fields)
    case = reference["cases"].get(setup.case)
    if case is None:
        raise ValueError(f"no reference data for case {setup.case!r} (have {sorted(reference['cases'])})")
    key = claim_for(case["claims"], method)
    if key is None:
        raise ValueError(f"the paper makes no claim for method {method!r} in case {setup.case!r} "
                         f"(graded names: {sorted(case['claims'])}, optionally with a '-suffix')")
    claim = case["claims"][key]
    tolerance = float(case["tolerance"][claim])
    table = setup.transducer.table
    exact = np.array([exact_log_z(setup.source, y, table) for y in setup.targets])
    m = np.asarray(setup.m_values, dtype=float)
    samples, errors, passed = {}, {}, True

    if claim != "lower_bound":
        over = particles - m[None, :, None]
        errors["max_particles_over_m"] = float(over.max())
        passed = passed and errors["max_particles_over_m"] <= 0

    if claim in ("exact", "top_m_share"):
        expected = np.broadcast_to(exact[:, None, None], log_z.shape).copy()
        if claim == "top_m_share":
            for i, y in enumerate(setup.targets):
                log_paths = sum(math.log(sum(a == s for a in table.values())) for s in y)  # log ∏ d_t
                expected[i] = (np.minimum(np.log(m), log_paths) - log_paths + exact[i])[:, None]
        err = np.abs(log_z - expected)
        err = np.where(np.isfinite(err), err, np.inf)
        errors["max_abs_log_error"] = _finite(err.max())
        for i in range(len(setup.targets)):
            samples[f"abs_log_error_t{i + 1}"] = _pairs(m, err[i].max(axis=1))
        passed = passed and errors["max_abs_log_error"] <= tolerance

    elif claim == "unbiased":
        ratio = np.exp(log_z - exact[:, None, None])           # Ẑ/Z per target, M, seed
        n = ratio.shape[2]
        mean, sd = ratio.mean(axis=2), ratio.std(axis=2, ddof=1)
        se = sd / math.sqrt(n)
        close = np.abs(mean - 1) <= 1e-9
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(close, 0.0, np.where(se > 0, np.abs(mean - 1) / se, np.inf))
        z = np.nan_to_num(z, nan=np.inf)
        live = ~close & (se > 0) & np.isfinite(se)
        pooled = (float(np.sum((mean - 1)[live] / se[live] ** 2) / math.sqrt(np.sum(1 / se[live] ** 2)))
                  if live.any() else 0.0)
        rmse = np.sqrt(np.mean((ratio - 1) ** 2, axis=2))      # relative RMSE, Fig. 9a
        shrinks = [(r[-1] < r[0]) or (r[-1] <= 1e-12 and r[0] <= 1e-12) for r in rmse]
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            # Display only: spread of log Ẑ over the seeds whose estimate is nonzero.
            sd_log = np.nanstd(np.where(np.isfinite(log_z), log_z, np.nan), axis=2, ddof=1)
        errors["max_z"] = _finite(z.max())
        errors["pooled_z"] = _finite(abs(pooled))
        errors["worst_rmse_ratio"] = _finite(max(r[-1] / r[0] if r[0] > 0 else 0.0 for r in rmse))
        passed = passed and errors["max_z"] <= tolerance and errors["pooled_z"] <= tolerance and all(shrinks)
        if case.get("require_spread"):
            # Spread of Ẑ/Z itself, so seeds whose estimate is 0 (a legitimate outcome, §4.1) still count.
            errors["min_rel_sd"] = _finite(float(np.nan_to_num(sd, nan=0.0).min()))
            passed = passed and errors["min_rel_sd"] > float(case["min_spread"])
        for i in range(len(setup.targets)):
            samples[f"rel_rmse_t{i + 1}"] = _pairs(m, rmse[i])
            samples[f"sd_log_z_t{i + 1}"] = _pairs(m, np.nan_to_num(sd_log[i], nan=1e300))

    elif claim == "lower_bound":
        ref = np.array([math.log(beam_summing_tau(setup.source, setup.transducer, y, setup.tau))
                        for y in setup.targets])
        share = np.exp(log_z - exact[:, None, None])
        errors["max_overshoot"] = _finite(float((share - 1).max()))
        errors["max_rel_diff_from_fig1"] = _finite(float(np.abs(np.exp(log_z - ref[:, None, None]) - 1).max()))
        for i in range(len(setup.targets)):
            samples[f"share_t{i + 1}"] = _pairs(m, share[i, :, 0])
        passed = (errors["max_overshoot"] <= tolerance
                  and errors["max_rel_diff_from_fig1"] <= float(case["beam_rtol"]))

    else:
        raise ValueError(f"unknown claim {claim!r} in reference.json")

    return {"samples": samples, "errors": errors, "tolerance": tolerance, "pass": bool(passed)}

"""Shared measurement for transduced-lm-2026. Read-only; methods never import or read it.

Each method is graded against the claim the paper makes for it in the run's case (``reference.json``,
``cases.<case>.claims``):

- ``exact``: every estimate equals the true value (Appendix E): max |log Ẑ − log Z| ≤ the case tolerance.
- ``top_m_share``: beam search with prune_M captures exactly min(M, d^T) of the d^T equally likely covering
  strings (Appendix E, Eq. 49): max |log Ẑ − log(min(M, d^T) · 4^-3T)| ≤ the case tolerance.
- ``unbiased``: for every target and M, the seed average of Ẑ/Z is within ``z_max`` standard errors of 1, and
  the relative RMSE at the largest M is below that at the smallest M for every target (§3.3, §4.3, Fig. 9a).
- ``lower_bound``: beam summing with prune_τ only discards mass, so Ẑ ≤ Z (§3.1): max(Ẑ/Z − 1) ≤ the case
  tolerance.
"""
import math

import numpy as np


def exact_log_z(source, target: str, table: dict) -> float:
    """log p_Y→(target): forward path sum over codons, the state being the last base (Appendix D)."""
    start, trans = source._start, source._trans
    codons = {}
    for codon, amino in table.items():
        codons.setdefault(amino, []).append(codon)
    idx = {b: i for i, b in enumerate("ACGT")}
    alpha, log_scale = None, 0.0
    for t, amino in enumerate(target):
        nxt = np.zeros(4)
        for codon in codons.get(amino, []):
            a, b, c = (idx[ch] for ch in codon)
            tail = trans[a, b] * trans[b, c]
            nxt[c] += (start[a] if t == 0 else alpha @ trans[:, a]) * tail
        total = nxt.sum()
        if total == 0.0:
            return -math.inf
        alpha, log_scale = nxt / total, log_scale + math.log(total)
    return log_scale


def check_log_z(setup, fields) -> np.ndarray:
    if not isinstance(fields, dict) or "log_z" not in fields:
        raise ValueError("solve() must return a dict with key 'log_z'")
    a = np.asarray(fields["log_z"], dtype=float)
    shape = (len(setup.targets), len(setup.m_values), len(setup.seeds))
    if a.shape != shape:
        raise ValueError(f"log_z has shape {a.shape}, expected {shape}")
    if np.isnan(a).any() or np.isposinf(a).any():
        raise ValueError("log_z contains NaN or +inf")
    return a


def _pairs(xs, ys) -> list[list[float]]:
    return [[float(a), float(b)] for a, b in zip(xs, ys)]


def _finite(x: float) -> float:
    """JSON has no infinity or NaN; map both to a large number so errors stay valid and still fail."""
    return 1e300 if math.isnan(x) else float(min(x, 1e300))


def measure(setup, fields, reference: dict, method: str) -> dict:
    log_z = check_log_z(setup, fields)
    case = reference["cases"].get(setup.case)
    if case is None:
        raise ValueError(f"no reference data for case {setup.case!r} (have {sorted(reference['cases'])})")
    claim = case["claims"].get(method)
    if claim is None:
        raise ValueError(f"the paper makes no claim for method {method!r} in case {setup.case!r} "
                         f"(have {sorted(case['claims'])})")
    tolerance = float(case["tolerance"][claim])
    exact = np.array([exact_log_z(setup.source, y, setup.transducer.table) for y in setup.targets])
    m = np.asarray(setup.m_values, dtype=float)
    samples, errors = {}, {}

    if claim in ("exact", "top_m_share"):
        expected = np.broadcast_to(exact[:, None, None], log_z.shape).copy()
        if claim == "top_m_share":
            for i, y in enumerate(setup.targets):
                d = case["aliases_per_symbol"]
                kept = np.minimum(m, float(d) ** len(y))
                expected[i] = (np.log(kept) - len(y) * math.log(float(d)) + exact[i])[:, None]
        err = np.abs(log_z - expected)
        err = np.where(np.isfinite(err), err, np.inf)
        errors["max_abs_log_error"] = _finite(err.max())
        samples["abs_log_error"] = _pairs(m, err.max(axis=(0, 2)))
        passed = errors["max_abs_log_error"] <= tolerance

    elif claim == "unbiased":
        ratio = np.exp(log_z - exact[:, None, None])           # Ẑ/Z per target, M, seed
        n = ratio.shape[2]
        mean, sd = ratio.mean(axis=2), ratio.std(axis=2, ddof=1)
        se = sd / math.sqrt(n)
        z = np.where(se > 0, np.abs(mean - 1) / np.where(se > 0, se, 1),
                     np.where(np.abs(mean - 1) <= 1e-9, 0.0, np.inf))
        z = np.nan_to_num(z, nan=np.inf)
        rmse = np.sqrt(np.mean((ratio - 1) ** 2, axis=2))      # relative RMSE, Fig. 9a
        shrinks = [(r[-1] < r[0]) or (r[-1] <= 1e-12 and r[0] <= 1e-12) for r in rmse]
        errors["max_z"] = _finite(z.max())
        errors["worst_rmse_ratio"] = _finite(max(r[-1] / r[0] if r[0] > 0 else 0.0 for r in rmse))
        with np.errstate(invalid="ignore"):
            sd_log = np.std(np.where(np.isfinite(log_z), log_z, np.nan)[:, :, :8], axis=2, ddof=1)
        for i, y in enumerate(setup.targets):
            samples[f"rel_rmse_{y}"] = _pairs(m, rmse[i])
            samples[f"sd_log_z_8_seeds_{y}"] = _pairs(m, np.nan_to_num(sd_log[i], nan=1e300))
        passed = errors["max_z"] <= tolerance and all(shrinks)

    elif claim == "lower_bound":
        over = np.exp(log_z - exact[:, None, None]) - 1
        errors["max_overshoot"] = _finite(over.max())
        errors["min_share"] = float(np.exp(log_z - exact[:, None, None]).min())
        for i, y in enumerate(setup.targets):
            samples[f"share_{y}"] = _pairs(m, np.exp(log_z[i, :, 0] - exact[i]))
        passed = errors["max_overshoot"] <= tolerance

    else:
        raise ValueError(f"unknown claim {claim!r} in reference.json")

    return {"samples": samples, "errors": errors, "tolerance": tolerance, "pass": bool(passed)}

# raft-grader claims v1 sha256:4159a6aa933860c47b7a035bad07046a8c9b159c7c831f24746d29461d6d4e7e
"""Grade the claims papers make about estimators: exact, unbiased, error falls with budget, lower bound, budget."""
import math

import numpy as np

VERSION = 1
BIG = 1e300


def _f(x) -> float:
    x = float(x)
    return BIG if math.isnan(x) or x > BIG else x


def exact(estimate, truth, tolerance: float, name: str = "abs_error") -> dict:
    e = np.abs(np.asarray(estimate, dtype=float) - np.asarray(truth, dtype=float))
    e = np.where(np.isfinite(e), e, np.inf)
    m = _f(e.max())
    return {"errors": {f"max_{name}": m}, "pass": bool(m <= tolerance)}


def unbiased(estimates, truth, z_limit: float, min_rel_sd: float | None = None) -> dict:
    """estimates has seeds on the last axis; truth broadcasts to the other axes. z-test of the mean of Ẑ/Z per cell
    and pooled over cells. min_rel_sd: also require the spread of Ẑ/Z to exceed it (a constant answer is not an
    estimate)."""
    ratio = np.asarray(estimates, dtype=float) / np.asarray(truth, dtype=float)[..., None]
    n = ratio.shape[-1]
    if n < 2:
        raise ValueError("unbiased needs at least 2 seeds")
    mean, sd = ratio.mean(axis=-1), ratio.std(axis=-1, ddof=1)
    se = sd / math.sqrt(n)
    close = np.abs(mean - 1) <= 1e-9
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(close, 0.0, np.where(se > 0, np.abs(mean - 1) / se, np.inf))
    z = np.nan_to_num(z, nan=np.inf)
    live = ~close & (se > 0) & np.isfinite(se)
    pooled = (float(np.sum((mean - 1)[live] / se[live] ** 2) / math.sqrt(np.sum(1 / se[live] ** 2)))
              if live.any() else 0.0)
    errors = {"max_z": _f(z.max()), "pooled_z": _f(abs(pooled))}
    ok = errors["max_z"] <= z_limit and errors["pooled_z"] <= z_limit
    if min_rel_sd is not None:
        errors["min_rel_sd"] = _f(np.nan_to_num(sd, nan=0.0).min())
        ok = ok and errors["min_rel_sd"] > min_rel_sd
    return {"errors": errors, "pass": bool(ok)}


def error_falls(estimates, truth) -> dict:
    """estimates (..., budgets, seeds): the relative RMSE at the largest budget is below the smallest's in every cell."""
    ratio = np.asarray(estimates, dtype=float) / np.asarray(truth, dtype=float)[..., None, None]
    rmse = np.sqrt(np.mean((ratio - 1) ** 2, axis=-1)).reshape(-1, ratio.shape[-2])
    first, last = rmse[:, 0], rmse[:, -1]
    falls = (last < first) | ((last <= 1e-12) & (first <= 1e-12))
    worst = max((l / f if f > 0 else 0.0) for f, l in zip(first, last))
    return {"errors": {"worst_rmse_ratio": _f(worst)}, "pass": bool(np.all(falls) and np.all(np.isfinite(rmse)))}


def lower_bound(estimate, truth, tolerance: float) -> dict:
    share = np.asarray(estimate, dtype=float) / np.asarray(truth, dtype=float)
    over = _f(np.nan_to_num(share - 1, nan=np.inf).max())
    return {"errors": {"max_overshoot": over}, "pass": bool(over <= tolerance)}


def within_budget(used, limit) -> dict:
    over = _f((np.asarray(used, dtype=float) - np.asarray(limit, dtype=float)).max())
    return {"errors": {"max_over_budget": over}, "pass": bool(over <= 0)}

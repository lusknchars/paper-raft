# raft-grader checks v1 sha256:78ab90782a1789a3b369ca96d7cb1ad6e18da77c5e289c66c36ce83d69fcd290
"""Checks every measure.py starts with: the method returned what setup.py promised."""
import numpy as np

VERSION = 1


def require_keys(fields, keys) -> dict:
    if not isinstance(fields, dict) or not set(keys) <= set(fields):
        raise ValueError(f"solve() must return a dict with keys {sorted(keys)}")
    return fields


def array(fields, key, shape, allow_neg_inf: bool = False) -> np.ndarray:
    a = np.asarray(fields[key], dtype=float)
    if a.shape != tuple(shape):
        raise ValueError(f"{key} has shape {a.shape}, expected {tuple(shape)}")
    bad = np.isnan(a) | np.isposinf(a)
    if not allow_neg_inf:
        bad = bad | np.isneginf(a)
    if bad.any():
        raise ValueError(f"non-finite values in {key}")
    return a

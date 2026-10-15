"""Grade numbers against a paper's table: the largest and the RMS difference at the table's own points."""
import numpy as np

VERSION = 1


def match(values, reference, tolerance: float, name: str = "value") -> dict:
    v, r = np.asarray(values, dtype=float), np.asarray(reference, dtype=float)
    if v.shape != r.shape or v.size == 0:
        raise ValueError(f"{name}: {v.shape} values against a table of shape {r.shape}")
    d = np.abs(v - r)
    d = np.where(np.isfinite(d), d, np.inf)
    mx = float(min(d.max(), 1e300))
    rms = float(min(np.sqrt(np.mean(np.minimum(d, 1e150) ** 2)), 1e300))
    return {"errors": {f"{name}_max": mx, f"{name}_rms": rms}, "pass": bool(mx <= tolerance)}

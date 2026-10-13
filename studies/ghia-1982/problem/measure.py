"""Shared measurement for ghia-1982. Read-only; methods never import or read it."""
import numpy as np
from scipy.interpolate import RegularGridInterpolator

COARSE = 33


def check_fields(setup, fields) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(fields, dict) or not {"u", "v"} <= set(fields):
        raise ValueError("solve() must return a dict with keys 'u' and 'v'")
    out = []
    for key in ("u", "v"):
        a = np.asarray(fields[key], dtype=float)
        if a.shape != (setup.grid, setup.grid):
            raise ValueError(f"{key} has shape {a.shape}, expected ({setup.grid}, {setup.grid})")
        if not np.all(np.isfinite(a)):
            raise ValueError(f"non-finite values in {key}")
        out.append(a)
    return out[0], out[1]


def streamfunction(u: np.ndarray, h: float) -> np.ndarray:
    """psi(x, y) = integral of u dy from the bottom wall (trapezoid rule); psi = 0 there."""
    psi = np.zeros_like(u)
    psi[1:] = np.cumsum(0.5 * (u[1:] + u[:-1]) * h, axis=0)
    return psi


def _pairs(xs, ys) -> list[list[float]]:
    return [[float(a), float(b)] for a, b in zip(xs, ys)]


def measure(setup, fields, reference: dict) -> dict:
    u, v = check_fields(setup, fields)
    key = f"{setup.re:g}"
    case = reference["cases"].get(key)
    if case is None:
        raise ValueError(f"no reference data for Re = {key} (have {sorted(reference['cases'])})")
    nodes = setup.nodes()
    mid_index, mid = (setup.grid - 1) // 2, 0.5 * setup.length
    ref_u = np.asarray(case["u_vertical"], dtype=float)
    ref_v = np.asarray(case["v_horizontal"], dtype=float)
    u_at = RegularGridInterpolator((nodes, nodes), u)(np.column_stack([ref_u[:, 0], np.full(len(ref_u), mid)]))
    v_at = RegularGridInterpolator((nodes, nodes), v)(np.column_stack([np.full(len(ref_v), mid), ref_v[:, 0]]))
    du, dv = u_at - ref_u[:, 1], v_at - ref_v[:, 1]
    errors = {
        "u_max": float(np.max(np.abs(du))), "u_rms": float(np.sqrt(np.mean(du**2))),
        "v_max": float(np.max(np.abs(dv))), "v_rms": float(np.sqrt(np.mean(dv**2))),
    }
    tolerance = float(reference["tolerance"])
    coarse = np.linspace(0.0, setup.length, COARSE)
    yy, xx = np.meshgrid(coarse, coarse, indexing="ij")
    psi = RegularGridInterpolator((nodes, nodes), streamfunction(u, setup.h))(
        np.column_stack([yy.ravel(), xx.ravel()])).reshape(COARSE, COARSE)
    return {
        "samples": {"u_vertical": _pairs(nodes, u[:, mid_index]), "v_horizontal": _pairs(nodes, v[mid_index, :])},
        "reference_samples": {"u_vertical": _pairs(ref_u[:, 0], ref_u[:, 1]),
                              "v_horizontal": _pairs(ref_v[:, 0], ref_v[:, 1])},
        "errors": errors,
        "tolerance": tolerance,
        "pass": bool(max(errors["u_max"], errors["v_max"]) <= tolerance),
        "fields_coarse": {"psi": np.round(psi, 6).tolist()},
    }

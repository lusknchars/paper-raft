"""Shared problem setup for Ghia, Ghia & Shin (1982): the lid-driven square cavity.

Read-only for implementers. Every method exposes ``solve(setup: CavitySetup) -> dict``
returning ``{"u": ndarray, "v": ndarray}``, each of shape ``(grid, grid)``, indexed
``[j, i]`` = value at ``(x_i, y_j)`` on the uniform node grid ``x_i = i * h``,
``y_j = j * h``, ``h = length / (grid - 1)``, walls included.

The lid is the top wall (y = length) moving in +x at ``lid_velocity``; the other three
walls are no-slip. Velocities are in units of the lid speed (lid_velocity = 1), so the
top row of u is 1 and every other wall value is 0. Kinematic viscosity is
``nu = lid_velocity * length / re``.
"""
import itertools
from dataclasses import dataclass

import numpy as np

REYNOLDS = (100, 1000)
GRIDS = (33, 65, 129)
RUN_MATRIX = {"re": [100], "grid": list(GRIDS)}
HEADLINE = {"re": 100, "grid": 129}
REPRO_RTOL = 1e-8
_KEYS = ("re", "grid")


@dataclass(frozen=True)
class CavitySetup:
    re: float
    grid: int
    lid_velocity: float = 1.0
    length: float = 1.0

    @property
    def h(self) -> float:
        return self.length / (self.grid - 1)

    @property
    def nu(self) -> float:
        return self.lid_velocity * self.length / self.re

    def nodes(self) -> np.ndarray:
        return np.linspace(0.0, self.length, self.grid)


def make_setup(params: dict) -> CavitySetup:
    unknown = set(params) - {*_KEYS, "seed"}
    if unknown:
        raise ValueError(f"unknown parameters {sorted(unknown)} for ghia-1982 (use --re and --grid)")
    re, grid = float(params["re"]), int(params["grid"])
    if re <= 0:
        raise ValueError(f"re must be positive, got {re:g}")
    if grid < 9 or grid % 2 == 0:
        raise ValueError(f"grid must be odd and at least 9 so the centrelines are grid lines, got {grid}")
    return CavitySetup(re=re, grid=grid)


def expand(params: dict) -> list[dict]:
    extra = {k: v for k, v in params.items() if k not in _KEYS}
    choices = [[params[k]] if k in params else RUN_MATRIX[k] for k in _KEYS]
    combos = [{**dict(zip(_KEYS, c)), **extra} for c in itertools.product(*choices)]
    for c in combos:
        make_setup(c)
    return combos

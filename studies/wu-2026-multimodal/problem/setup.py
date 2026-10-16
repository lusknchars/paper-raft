"""Shared problem setup for Wu, Zhu, Shi (2026), arXiv:2608.04234: joint kernel entropic Gromov--Wasserstein (JK-EGW).

Read-only for implementers. The experiment is the parametric-rate study of Section 5.2 (Figure 4 Left, p. 21-22):
the plug-in JK-EGW objective computed on n samples converges to the population objective at rate n^(-1/2).

The objective (Eq. 1, p. 7)
---------------------------
M = 2 modalities. Modality i has a probability measure a^i on the 20 points ``setup.x`` (a uniform grid in [0, 1]).
The latent reference b is a probability measure on the 49 points ``setup.z`` (a 7 x 7 grid in [-1, 1]^2). A plan
pi^i for modality i is a nonnegative 20 x 49 matrix with row sums a^i and column sums b; ``pi^i[k, l]`` is the mass
sent from x_k to z_l. The objective is

    S_eps({a^i}, b) = min over plans of
        sum_{i,j=1..2} sum_{k,k',l,l'} K_ij(x_k, x_k') pi^i[k,l] pi^j[k',l'] ||z_l - z_l'||^2
        + eps * sum_i KL(pi^i || a^i b^T),

with KL(p || q) = sum over entries with p > 0 of p log(p / q), eps = ``setup.eps`` = 0.2, and the kernel
K_ij(x, x') = gamma_ij exp(-|x - x'|^2 / (2 l^2)), l = ``setup.length_scale`` = 0.1, gamma_ij = 1 for i = j and
0.6 for i != j (``setup.gamma_within``, ``setup.gamma_cross``). ``setup.kernel(i, j)`` returns the 20 x 20 block
K_ij on the grid; ``setup.gram()`` returns the full 40 x 40 matrix [[K_11, K_12], [K_21, K_22]] (rows modality 1
first). The full kernel is used: no rank truncation.

An empirical measure built from n draws (1/n) sum_k delta_{x_{d_k}} is the measure on the same grid whose weight on
x_k is (number of draws equal to k) / n; atoms that were never drawn have weight 0. Plans are always reported on
the fixed 20 x 49 grid in this aggregated form (a zero-weight atom has a zero row or column).

The objective is not convex. Algorithm 1 (p. 17) is a local method: it can stop at a saddle (the symmetric start
A = 0 is one) or at a local minimum, and the two-sample problems below have several local minima. S_eps is the
minimum, so report the lowest value you can find (use several starting points per problem). Spot checks compare
your value with the lowest value the grader finds itself; you pass if yours is no more than 1e-6 above it.

The three regimes
-----------------
- population: a^i = ``setup.mu[i]`` (the mixture weights of Figure 3), b = ``setup.nu`` (uniform, 1/49 each).
- one-sample, cell (j, r): a^i = empirical measure of ``setup.draws[j][r]["x1"]`` (i = 0) and ``["x2"]`` (i = 1);
  b = ``setup.nu``.
- two-sample, cell (j, r): the same a^i; b = empirical measure of ``setup.draws[j][r]["z"]`` (indices into
  ``setup.z``).
Here j indexes ``setup.n_values`` = (50, 100, 200, 400, 800, 1600) and r indexes the ``setup.reps`` = 100 Monte
Carlo repetitions. ``setup.draws[j][r]`` holds integer index arrays of length n_values[j]; they are fixed so that
every method solves the same problems.

What solve(setup) returns
-------------------------
A dict with exactly these keys (numpy arrays or nested lists of floats):

- ``population_value``: float, S_eps({mu^i}, nu).
- ``population_plans``: shape (2, 20, 49), the plans achieving it.
- ``one_sample_values``: shape (6, reps), S_eps({mu_hat^i_n}, nu) for each cell (j, r).
- ``one_sample_plans``: shape (6, reps, 2, 20, 49).
- ``two_sample_values``: shape (6, reps), S_eps({mu_hat^i_n}, nu_hat_n).
- ``two_sample_plans``: shape (6, reps, 2, 20, 49).

Every reported value must be the objective of its reported plans (to 1e-7). The plans must satisfy their marginals
(L1 error at most 1e-7 per plan) and be a fixed point of Algorithm 1: with A = L^T Pi Z and the cost
C = 2 Omega ||z||^2^T - 4 L A Z^T (equivalently 2 (W a) ||z||^2^T - 4 W Pi Z Z^T with W the Gram matrix and a the
stacked row weights), one more exact Sinkhorn step on C with marginals (a^i, b) must reproduce each plan to an L1
distance of at most 1e-4.

Rules for methods:
- Compute every value; do not copy numbers from the paper. Use numpy and scipy only.
- Draw all randomness (for example random starting points) from ``setup.rng(*keys)``, so runs are reproducible.
- Do not change ``setup.draws``, ``setup.mu`` or any other field of the setup.
"""
from dataclasses import dataclass, field

import numpy as np

RUN_MATRIX = {"experiment": ["rate"]}
HEADLINE = {"experiment": "rate"}
REPRO_RTOL = 1e-6
_KEYS = ("experiment",)

# Mixture weights of mu^1 and mu^2 on linspace(0, 1, 20), read off Figure 3 (p. 21) at 400 dpi and normalised.
_MU1 = (0.0187, 0.0200, 0.0268, 0.0471, 0.0815, 0.1083, 0.1016, 0.0683, 0.0381, 0.0251,
        0.0262, 0.0384, 0.0590, 0.0781, 0.0817, 0.0668, 0.0451, 0.0290, 0.0215, 0.0191)
_MU2 = (0.0182, 0.0182, 0.0184, 0.0189, 0.0217, 0.0305, 0.0499, 0.0758, 0.0913, 0.0832,
        0.0587, 0.0358, 0.0238, 0.0231, 0.0379, 0.0772, 0.1159, 0.1069, 0.0626, 0.0303)
N_VALUES = (50, 100, 200, 400, 800, 1600)
REPS = 100
_DRAW_SEED = 2608_04234


@dataclass(frozen=True)
class RateSetup:
    x: np.ndarray                 # (20,) feature grid, shared by both modalities
    mu: np.ndarray                # (2, 20) population weights
    z: np.ndarray                 # (49, 2) latent grid, row 7 * p + q is (g[p], g[q]) with g = linspace(-1, 1, 7)
    nu: np.ndarray                # (49,) uniform latent weights
    eps: float
    length_scale: float
    gamma_within: float
    gamma_cross: float
    n_values: tuple
    reps: int
    draws: list = field(repr=False)   # draws[j][r] = {"x1": (n,), "x2": (n,), "z": (n,)} integer arrays

    def kernel(self, i: int, j: int) -> np.ndarray:
        d = self.x[:, None] - self.x[None, :]
        gamma = self.gamma_within if i == j else self.gamma_cross
        return gamma * np.exp(-d ** 2 / (2 * self.length_scale ** 2))

    def gram(self) -> np.ndarray:
        return np.block([[self.kernel(0, 0), self.kernel(0, 1)], [self.kernel(1, 0), self.kernel(1, 1)]])

    def rng(self, *keys) -> np.random.Generator:
        return np.random.default_rng([7, *[int(k) for k in keys]])


def _draws(mu: np.ndarray, n_values, reps: int) -> list:
    out = []
    for j, n in enumerate(n_values):
        row = []
        for r in range(reps):
            g = np.random.default_rng([_DRAW_SEED, j, r])
            row.append({"x1": g.choice(20, size=n, p=mu[0]), "x2": g.choice(20, size=n, p=mu[1]),
                        "z": g.integers(0, 49, size=n)})
        out.append(row)
    return out


def make_setup(params: dict) -> RateSetup:
    if params.get("experiment", "rate") != "rate":
        raise ValueError(f"unknown experiment {params.get('experiment')!r}")
    mu = np.array([_MU1, _MU2], dtype=float)
    mu /= mu.sum(axis=1, keepdims=True)
    g = np.linspace(-1.0, 1.0, 7)
    z = np.array([(u, v) for u in g for v in g], dtype=float)
    return RateSetup(x=np.linspace(0.0, 1.0, 20), mu=mu, z=z, nu=np.full(49, 1 / 49), eps=0.2, length_scale=0.1,
                     gamma_within=1.0, gamma_cross=0.6, n_values=N_VALUES, reps=REPS,
                     draws=_draws(mu, N_VALUES, REPS))


def expand(params: dict) -> list[dict]:
    extra = {k: v for k, v in params.items() if k not in _KEYS}
    combos = [{"experiment": e, **extra} for e in ([params["experiment"]] if "experiment" in params
                                                    else RUN_MATRIX["experiment"])]
    for c in combos:
        make_setup(c)
    return combos

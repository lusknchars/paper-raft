"""Shared problem setup for Snæbjarnarson et al. (2026), arXiv:2608.27428: transduced language models.

Read-only for implementers. A transduced language model passes strings drawn from a *source* language
model over DNA through a transducer ``f`` (here the standard genetic code) to get a model over amino-acid
strings. Every method estimates the prefix probability

    Z = p_Y→(y) = Pr_{X ~ p_X}[ y ⪯ f(X) ]

of each target amino-acid string ``y`` and exposes ``solve(setup: TransductionSetup) -> dict`` returning
``{"log_z": array, "max_particles": array}``, both of shape
``(len(setup.targets), len(setup.m_values), len(setup.seeds))``. Entry ``[i, j, k]`` of ``log_z`` is the natural
log of the estimate for target ``i`` with maximum particle count ``m_values[j]`` and random seed ``seeds[k]``
(``-inf`` for an estimate of zero, never NaN). Entry ``[i, j, k]`` of ``max_particles`` is the largest number of
particles the method kept after any prune or resampling step in that run (it must not exceed ``m_values[j]``;
beam summing with prune_τ has no M and reports its largest pool). A deterministic method fills every seed slot
with the same value.

Graded method names (the folder under ``methods/``): ``beam-summing``, ``smc-simple``, ``smc-rb``,
``beam-swor``, ``beam-swor-adaptive``. A second implementation of the same algorithm adds a suffix
(``smc-rb-2``) and is graded against the same claim.

Rules for methods:
- Use the source only through ``setup.source.next_probs(prefix)`` (or ``next_probs_batch``): the source is
  treated as a black-box autoregressive model, as in the paper. Do not read its private tables.
- Use the transducer only through its predicates ``is_live``, ``is_member``, ``is_cylinder`` (and
  ``output``), as in the paper (§2.2).
- Draw all randomness from ``setup.rng(i, j, k)``, so runs are reproducible.
- Estimate; do not solve. No closed forms, no exact path sums, no enumeration of the whole precover, and no use
  of the source's private tables, even where the problem is small enough to allow it.

The source alphabet is ``"ACGT"``; ``next_probs`` returns probabilities over ``A, C, G, T, EOS`` (index 4 is
end of sequence), i.e. p_X→(x' | x) for the four symbols and p_X→(eos | x).

Cases:
- ``worst``: Appendix E. A uniform source (each base 1/4) that stops after exactly 300 bases, and two targets of
  length 100: isoleucine × 100 (the paper's example) and a fixed mix of amino acids whose codons share their first
  two bases. Beam summing runs with prune_M (keep the M heaviest). No tail roulette here (``kappa = 0``): the
  decomposition is finite, so every method halts without it.
- ``bigram``: §4.3–4.4. A fixed DNA bigram source (a stand-in: the paper's DNA corpus is not named) that stops
  with probability 0.02 after each base, and three amino-acid targets of length 10. Beam summing runs with prune_τ,
  τ = 1e-3, as in the paper. The tail-roulette threshold is ``kappa`` times the particle's weight at the start of
  the current target-prefix call (App. B.6); for a method without target-prefix calls (Fig. 10), the start of
  the run.

The transducer reads codons left to right in frame 0; stop codons emit ``*`` and translation continues; a
trailing partial codon emits nothing. The paper does not say how f_dna2aa treats stop codons; no target
contains ``*``, so the answer does not depend on it. Because output only grows, ``is_cylinder`` equals
``is_member`` here and the remainder is always empty.
"""
import itertools
import math
from dataclasses import dataclass, field

import numpy as np

SYMBOLS = "ACGT"
EOS = 4
RUN_MATRIX = {"case": ["worst", "bigram"]}
HEADLINE = {"case": "bigram"}
REPRO_RTOL = 1e-8
_KEYS = ("case",)

# Standard genetic code, codons in TCAG order; '*' marks the three stop codons.
_BASES = "TCAG"
_AMINO = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
GENETIC_CODE = {a + b + c: _AMINO[16 * i + 4 * j + k]
                for i, a in enumerate(_BASES) for j, b in enumerate(_BASES) for k, c in enumerate(_BASES)}


class BigramSource:
    """A DNA language model whose next-symbol distribution depends only on the last base."""

    alphabet = SYMBOLS

    def __init__(self, start, trans, max_len=None):
        self._start = np.asarray(start, dtype=float)
        self._trans = np.asarray(trans, dtype=float)
        self._max_len = max_len

    def next_probs(self, prefix: str) -> np.ndarray:
        """Probabilities of A, C, G, T and EOS after ``prefix``."""
        if self._max_len is not None and len(prefix) >= self._max_len:
            return np.array([0.0, 0.0, 0.0, 0.0, 1.0])
        row = self._start if not prefix else self._trans[SYMBOLS.index(prefix[-1])]
        return row.copy()

    def next_probs_batch(self, prefixes) -> np.ndarray:
        """``next_probs`` for many prefixes at once, shape ``(len(prefixes), 5)``."""
        return np.array([self.next_probs(p) for p in prefixes]).reshape(-1, 5)


def _row(a, c, g, t, eos):
    return [(1 - eos) * a, (1 - eos) * c, (1 - eos) * g, (1 - eos) * t, eos]


# Appendix E: p_X(x) = (1/4)^300 for each of the 4^300 strings of length 300.
UNIFORM = BigramSource(start=_row(.25, .25, .25, .25, 0.0), trans=[_row(.25, .25, .25, .25, 0.0)] * 4, max_len=300)
# High-entropy and human-like (A/T rich, CpG depleted); stops with probability 0.02 after each base.
_STOP = 0.02
BIGRAM = BigramSource(
    start=_row(.30, .20, .20, .30, 0.0),
    trans=[_row(.33, .17, .24, .26, _STOP),   # after A
           _row(.35, .26, .05, .34, _STOP),   # after C
           _row(.29, .21, .25, .25, _STOP),   # after G
           _row(.22, .20, .25, .33, _STOP)],  # after T
)


@dataclass(frozen=True)
class CodonTransducer:
    """f: DNA → amino acids, reading codons left to right; a trailing partial codon emits nothing."""

    table: dict = field(default_factory=lambda: dict(GENETIC_CODE))

    def output(self, x: str) -> str:
        return "".join(self.table[x[i:i + 3]] for i in range(0, len(x) - len(x) % 3, 3))

    def is_member(self, x: str, y: str) -> bool:
        """x ∈ P(y): the output emitted so far covers y."""
        return self.output(x).startswith(y)

    def is_cylinder(self, x: str, y: str) -> bool:
        """Every extension of x covers y. Output only grows as x grows, so this equals is_member."""
        return self.is_member(x, y)

    def is_live(self, x: str, y: str) -> bool:
        """Some extension of x covers y."""
        out = self.output(x)
        if len(out) >= len(y):
            return out.startswith(y)
        if not y.startswith(out):
            return False
        partial, want = x[3 * len(out):], y[len(out)]
        return any(c.startswith(partial) and a == want for c, a in self.table.items())


@dataclass(frozen=True)
class TransductionSetup:
    case: str
    source: BigramSource
    transducer: CodonTransducer
    targets: tuple
    m_values: tuple
    seeds: tuple
    beam_prune: str          # "top_m" (keep the M heaviest) or "tau" (keep ≥ 1 − τ of the mass)
    tau: float = 1e-3        # prune_τ threshold (§4.3)
    rho: float = 0.1         # beam_swor_adaptive budget parameter ρ (§3.4, §4.4)
    kappa: float = math.exp(-30)  # tail-roulette threshold κ for DNA (App. B.6); 0 turns the roulette off
    eta: float = 0.5         # ESS resampling threshold η for smc_rb (App. C default)
    epsilon: float = 0.0     # ε in the adaptive running total A_ε (App. C: "The experiments use ε = 0")

    def rng(self, target_index: int, m_index: int, seed_index: int) -> np.random.Generator:
        return np.random.default_rng([self.seeds[seed_index], target_index, m_index])


# Amino acids whose codons all share their first two bases, so the live proposal is uniform over d codons
# and Appendix E's argument holds symbol by symbol. Drawn once with random.Random(2608) and fixed here.
WORST_MIX = ("KHTTCNVPDWMYMAKFAMCIHEKYDDMIWPGFYYETIGHFYVQCDHTPDYDMWIFIDPTTFNVCMTGFVDFTCQKMPCEKEHVCKFYAPAHFM"
             "GVIPGQW")

CASES = {
    "worst": dict(source=UNIFORM, targets=("I" * 100, WORST_MIX), m_values=(16, 64, 256),
                  seeds=tuple(range(8)), beam_prune="top_m", kappa=0.0),
    "bigram": dict(source=BIGRAM, targets=("MVHLTPEEKS", "MALWMRLLPL", "MKTAYIAKQR"),
                   m_values=(16, 64, 256), seeds=tuple(range(128)), beam_prune="tau"),
}


def make_setup(params: dict) -> TransductionSetup:
    unknown = set(params) - {*_KEYS, "seed"}
    if unknown:
        raise ValueError(f"unknown parameters {sorted(unknown)} for transduced-lm-2026 (use --case)")
    case = params.get("case")
    if case not in CASES:
        raise ValueError(f"case must be one of {sorted(CASES)}, got {case!r}")
    return TransductionSetup(case=case, transducer=CodonTransducer(), **CASES[case])


def expand(params: dict) -> list[dict]:
    extra = {k: v for k, v in params.items() if k not in _KEYS}
    choices = [[params[k]] if k in params else RUN_MATRIX[k] for k in _KEYS]
    combos = [{**dict(zip(_KEYS, c)), **extra} for c in itertools.product(*choices)]
    for c in combos:
        make_setup(c)
    return combos

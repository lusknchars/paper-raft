# Checker for wu-2026-multimodal

## What is reproduced

The parametric-rate experiment of Section 5.2 (pages 21-22, Figure 4 Left). It checks Theorem 5 (page 12): the
plug-in JK-EGW objective converges to the population objective at rate n^(-1/2), with both one-sample (ν known)
and two-sample (ν estimated) errors.

Setup, as the paper states it (page 21):
- M = 2 modalities on the same 20-point grid in [0, 1].
- ν uniform on a 7 × 7 grid in [-1, 1]².
- RBF kernel with ℓ = 0.1, γ = 1 within a modality and 0.6 across.
- n ∈ {50, 100, 200, 400, 800, 1600}, with 100 Monte Carlo repetitions.

Everything is finite, so it runs on a laptop. There is one case, `experiment=rate`.

## What is cut, and why

- **Numerals (5.1, Figure 2):** a qualitative picture with no numbers.
- **MS-COCO (5.3, Tables 1-3):** needs COCO images, MPNet and DINOv3 encoders, and MLP training. The paper does not
  give the kernel, ε, rank or categories (see the `coco-*-missing` extraction items). It does not run in minutes on
  a laptop.
- **Kernel truncation (Figure 4 Right):**
  - The figure shows ranks up to R = 56, but the 40-atom Gram matrix described in the text has rank at most 40, so
    the paper's setup for this panel is not the one stated.
  - With the stated setup (40 × 40 Gram, cross factor 0.6, ℓ = 0.15, ε = 0.2), my own runs fall far slower than
    the figure. For example, the RBF gap at R = 16 is 1.7e-4, against about 1e-13 in the figure.
  - Grading it would mean grading my guesses, so it is cut.

## What solve() returns and what is graded

`problem/setup.py` defines the output: the value and plans for the population problem, then values (6 × 100) and
plans (6 × 100 × 2 × 20 × 49) for each regime. Plans are on the fixed grids. An empirical measure is the grid
measure with weights count/n, which gives the same objective as the paper's n × n formulation.

`measure.py` checks, in order:

1. **Keys and shapes**, all values finite (`graders.checks`).
2. **Population value:** within 1e-6 of the grader's own Algorithm 1 minimum (`graders.claims.exact`). Sixteen
   random starts all reach S = 1.0833966598 to about 1e-12.
3. **Every one of the 1 + 1200 problems:**
   - Plans are nonnegative, with marginals correct to 1e-7 (L1).
   - The reported value equals the JK-EGW objective of the reported plans to 1e-7.
   - The plans are a fixed point of Algorithm 1: one more exact Sinkhorn step from A = LᵀΠZ moves them by at most
     1e-4 (L1).

   Together these mean every number is the objective of a stationary point of the right problem.
4. **Spot checks:** a fixed hidden set of 18 one-sample and 18 two-sample cells (3 repetitions per n). The grader
   runs its own multi-start Algorithm 1: the population optimum A* under the 8 symmetries of the grid, plus 8
   random starts, with the winner refined to a 1e-10 fixed point. The method's value may be at most 1e-6 above the
   grader's.
   - This is needed because the two-sample problems have several local minima, up to 0.05 apart at n = 50.
   - S_ε is defined as a minimum, and a local minimum is a wrong value of the right size.
   - In tests, A* under the 8 symmetries found the best of 48 starts in 36 of 36 problems.
5. **The paper's claims, on the mean absolute error curves** mean_r |S(cell) − S_pop|, using the grader's S_pop:
   - The least-squares log-log slope over the 6 values of n is within 0.25 of −1/2, for both regimes. My reading
     of the figure gives slopes of about −0.60 (one-sample) and −0.50 (two-sample). The theorem is an O(n^(-1/2))
     bound, so a band rather than an exact slope.
   - Every point is within a factor 2 of the value read off Figure 4 Left. The factor allows for reading error
     (about ±5%), Monte Carlo noise from 100 repetitions (about ±10%), and the Figure 3 weights being read rather
     than given.

`measure.py` stops the expensive checks as soon as one cheap check fails, so a failing answer is graded quickly.

## Where the numbers come from

- **Page 21:** the setup numbers (grid sizes, ℓ, γ, n values, 100 repetitions) and the claim "both curves show
  trends consistent with O(n^(-1/2))".
- **Page 22:**
  - ε = 0.2, stated for the truncation paragraph only.
  - The Figure 4 Left values, read at 500 dpi with the log axis calibrated on the 10⁻² label and the minor
    gridlines:
    - one-sample: 0.059, 0.0318, 0.0247, 0.0144, 0.0098, 0.0072
    - two-sample: 0.073, 0.0414, 0.0308, 0.0234, 0.0152, 0.0131
- **Page 21 (Figure 3):** the mixture weights of μ¹ and μ², read off at 400 dpi and renormalised. The raw reads sum
  to 1.0004 and 0.9983.

Every number in `reference.json` was checked against the rendered PDF pages.

## Assumptions

- **ε = 0.2 for the rate experiment.** The paper gives it only for the truncation experiment (extraction
  `synthetic-rate-epsilon-missing`). The errors this gives land close to the figure's (see the answer run), which
  supports the assumption.
- **Figure 3 weights.** They are read off the figure, not given (extraction `synthetic-mixture-weights-missing`).
  The extraction's fallback mixture is not used.
- **Draws.** They are fixed in `setup.py` from `default_rng([260804234, j, r])`, so every method solves the same
  problems. The paper's seeds are unknown.
- **Weighted, rectangular Algorithm 1.** The paper writes Algorithm 1 for uniform n × n plans. The population and
  one-sample runs need weights, as the extraction's `population-weights-generalisation-missing` item describes:
  Ω = W a, C = 2Ω|z|²ᵀ − 4LAZᵀ, Sinkhorn with marginals (aⁱ, b).
- **The start of Algorithm 1.** The paper does not give one. The extraction suggests the update at the independent
  coupling, which is A = 0 here because the latent grid is centred. **A = 0 is a saddle point:** Algorithm 1 stays
  at 1.4226 instead of 1.0834. `setup.py` warns about this and asks for several starts. The `saddle-start` attack
  shows the grader rejects it.

## Attacks (checker/attacks/)

- `hardcoded-figure`: a guessed population value plus figure-sized noise, with product-coupling plans. Blocked:
  the population value and the value-vs-plans check fail.
- `independent-coupling`: feasible product plans whose values are exactly their objective. Blocked: not a fixed
  point, and the population value is wrong.
- `saddle-start`: an honest Algorithm 1 started at A = 0. Blocked: the population value is 1.42, not 1.08.
- `wrong-kernel`: an honest multi-start Algorithm 1 that drops the cross-modality kernel blocks. Blocked: wrong
  population value, and not stationary for the true objective.

## Not graded

- The error-bar sizes in Figure 4.
- Runtime.
- How plans split mass between duplicate samples of the same atom: only the aggregated plan is graded, and the
  objective depends only on it at the optimum.

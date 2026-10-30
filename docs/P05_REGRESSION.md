# P05 — Negotiation, substitution and buy-timing failure paths (KAN-11)

Stage 1 requirements 1.2.4–1.2.6. Owner: Yat Man Peter Ho (Negotiation & Substitution).
Depends on P02 (KAN-8), P03 (KAN-9) and P04 (KAN-10).

## Scope and method

The release under test is `peter` with `origin/main` (KAN-5, KAN-6, KAN-23 and KAN-30 release work, up to
`7ee6e99`) merged in. Every scenario runs through the HTTP API against a freshly seeded database, using the
offline mock LLM, so results repeat exactly. The two exceptions are FP-13, which calls `negotiation.analyse`
on the P01 fixture catalogue, and FP-14 to FP-16, which call `buy_timing.advise` with a fixed clock.

- Matrix: `backend/tests/test_failure_paths.py` (18 scenarios, FP-01 to FP-18). Each one states its expected
  outcome and records what it observed.
- Expected vs observed results: `docs/evidence/p05-failure-paths.md`, written by
  `P05_REPORT=../docs/evidence/p05-failure-paths.md python -m pytest tests/test_failure_paths.py` (from `backend/`).
- The detailed per-feature tests are still in `test_substitution.py` (P02), `test_negotiation.py` (P03) and
  `test_buy_timing.py` (P04).

| Ticket scenario | Matrix rows |
|---|---|
| Over budget | FP-01, FP-02 |
| Out of stock | FP-03, FP-04, FP-05 |
| Unsafe swap | FP-06, FP-07 |
| Declined trade-off | FP-08 (swap), FP-09, FP-10, FP-11 (negotiation) |
| Timeout | FP-12 (build), FP-13 (trade-off search) |
| Insufficient history | FP-14, with FP-15 to FP-18 covering the rest of 1.2.6 |

## Defects found during integration

Merging `origin/main` into `peter` conflicted in 8 files. Each defect below was found while resolving those
conflicts or when re-running the tests afterwards. File each one as a Jira defect linked to KAN-11 and to
the owner's ticket.

| ID | Defect | Owner | Resolution | Retest |
|---|---|---|---|---|
| P05-D1 | `OptimisationResult` diverged. P01 added `timed_out`, while KAN-23/KAN-5 added `failure_reason` (`timeout` \| `solver_error`) with new messages. A build timeout returned `timed_out` on one side and `retryable` on the other. | Sanskar (S03) with Peter | `failure_reason` is canonical, `timed_out` is a read-only property derived from it, and the build returns `retryable` with a `reason`. The P01 contract test, the P03 test and `OPTIMISER_CONTRACT.md` were updated to match. | FP-12; `test_optimiser_contract.py::test_timeout_is_not_infeasibility` |
| P05-D2 | With `main`'s new `solver_error`, `negotiation.analyse` treated a solver error during the trade-off search as proof of infeasibility. It would then have told the shopper that their dietary rules leave no protein or vegetable options. | Peter | Any `failure_reason` now marks the search as incomplete: no options and no `blocked_roles`, and the message asks the shopper to retry. | FP-13; `test_negotiation.py::test_a_timeout_while_negotiating_is_not_reported_as_blocked` |
| P05-D3 | Accepting a swap that became unsafe: `main` (KAN-23) raised a 400 error, and the rollback left the swap pending, so it could be accepted again later and the refusal wasn't audited. P02 discarded it instead. | Peter with Sanskar (KAN-23) | Kept the P02 behaviour (withdraw, keep the original, audit `discard_substitution`), now using KAN-23's `compliance.recheck()`. | FP-07; `test_substitution.py::test_a_swap_that_became_unsafe_is_not_applied` |
| P05-D4 | The build path's call to `negotiation.analyse` conflicted, and `main`'s side dropped the edit pins and the reserved budget, so trade-offs for a chat edit ignored pinned items and money already spent on extras. | Peter | Kept the P03 call with pins and reserve, plus `main`'s cancellation `checkpoint()`. | `test_negotiation.py::test_pins_and_reserved_budget_are_kept_while_searching` |
| P05-D5 | Frontend build results diverged: P03's `timed_out` status versus `main`'s `retryable` and `cancelled`, and P03's negotiate-cancel versus `main`'s build-cancel endpoints. | Peter with Sanskar | `main`'s `retryable`/`cancelled` handling, with P03's "Keep my request as it is" (`/negotiate/cancel`) kept alongside build cancellation. | Frontend type-check and tests; FP-09 |

No defects were found in the integrated behaviour itself: once the conflicts were resolved, all 18 scenarios
gave the expected result on the first run (see the evidence file).

## Retest

| Run | Result |
|---|---|
| Failure-path matrix on the integrated release | 18/18 expected = observed |
| Full backend suite on the integrated release | see commit message / CI |
| Frontend type-check and tests | see commit message / CI |

## Still open for Done

- File P05-D1 to P05-D5 in Jira and confirm the resolutions with the owners named above (Sanskar for D1,
  D3 and D5).
- Peer review of the `peter` → `main` PR, then link this page and the evidence file on KAN-11.
- Demonstrate FP-03 (out of stock), FP-09 (cancel negotiation) and FP-17 (demo-history label) in the app.

# Synthetic cross-scenario validation

This report records validation of `flux:synthetic-scenario-input:v1` (input hash
`f5b2c271416b`) using `uv run --extra dev python -m model.validate_robustness`.
The full, machine-readable result is
[`data/demo/synthetic-cross-scenario-validation-v1.json`](../../data/demo/synthetic-cross-scenario-validation-v1.json).
The committed artifact is fully deterministic: `model/test_validate_robustness.py::test_committed_report_matches_code`
regenerates it from the code and compares byte-for-byte, so a hand edit to the
JSON or a code change without regeneration fails the suite.
Its top-level `units` block declares MW, MWh, hours, and fraction units for all
reported metric rows, including zero-shed rows.

## Results

| Scenario | Unserved MW | Horizon unserved MWh | Fraction of demand unserved |
| --- | ---: | ---: | ---: |
| Baseline | 188 | 752 | 13.77% |
| Candidate A | 51 | 204 | 3.74% |
| Candidate B | 82 | 328 | 6.01% |

The horizon is the fixture's `durationHours` (four hours), so MWh is
`unserved MW × 4`; it is not an hourly reconstruction. Candidate A reduces
fixture unserved demand by 137 MW relative to baseline, versus 106 MW for B.

## Sensitivity grid: what it drives and what it can show

The deterministic 3 × 3 grid scales `assumptions.demandMw` by 0.95/1.00/1.05
and scales `assumptions.baselineAvailableGenerationMw` **and every candidate's
`modeledContributionMw`** by 0.90/1.00/1.10 (the "availability" axis applies
the same factor to baseline generation and to both candidates). The fixture's
displayed `demandMultiplier` and `generationAvailabilityFraction` are **not**
consumed by `model/generate_demo.py` and therefore are not what this grid
perturbs; changing them changes no metric. The report lists this under
`sensitivity.axes` (`drivenFields` / `notConsumed`).

The grid produced no A/B rank reversal: A is better in seven cells and both
candidates tie at zero unserved MW in two low-shortage cells. **This is a
structural guarantee of the fixture model, not empirical evidence of
robustness.** With `shed = max(0, demandMw − (baselineAvailableGenerationMw +
modeledContributionMw))` and both contributions scaled by the same availability
factor, the candidate with the larger `modeledContributionMw` is never worse in
any cell for any positive scale; the only other outcome the grid can produce is
a tie. The report states this in `sensitivity.structuralNote` and
`transferBoundary.ranking`. The reversal detector itself is proven live by
`test_detector_reports_reversal_when_a_cell_reorders_candidates`, which injects a
per-cell reordering and asserts three reversals are reported.

An unseen, harsher fixture perturbation (1.08 demand, 0.94 availability) also
ranks A above B: 239.04 MW (956.16 MWh, 16.21%) unserved for A and 268.18 MW
(1072.72 MWh, 18.19%) for B. The same structural guarantee applies to it.

## Input validation

The validator refuses fixtures it cannot report on honestly instead of
substituting defaults: `demandMw <= 0`, `durationHours <= 0`, negative
generation or contribution, non-numeric MW values, missing fields, or candidate
ids other than exactly `a` and `b` raise `ValidationInputInvalid(field, reason)`
and the CLI exits 2 with `validation input invalid: <field>: <reason>`.

## Runtime and scope boundary

Wall-clock timings and machine identity are **not** part of the committed
report. `uv run --extra dev python -m model.validate_robustness --timings`
writes them to `data/demo/synthetic-cross-scenario-timings.local.json`, which is
git-ignored, so the committed artifact does not drift between machines or runs.

One recorded, labelled measurement for reference (author's Windows 11 /
Python 3.12.10 machine, one warm-up and 31 samples per shape): median
`result_payload()` execution was 0.2048 ms at 5 buses/6 lines, 0.5841 ms at
25/30, 1.0776 ms at 50/60, and 2.0763 ms at 100/120. These are
fixture-materialization timings only, not power-flow, OPF, cascade, or
real-network solver timings, and they are specific to that machine.

Temporal transfer is not evaluated: this is a static four-hour balance, not a
time-indexed holdout. Geographic transfer is not evaluated: the fixture is not
Minnesota, New York, Texas, ERCOT, MISO, or an actual interconnection model.
Minnesota and New York validation remain future/feasible-only until a verified
case and execution exist.

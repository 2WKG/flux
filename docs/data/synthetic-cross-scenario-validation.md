# Synthetic cross-scenario validation

This report records validation of `flux:synthetic-scenario-input:v1` (input hash
`f5b2c271416b`) using `py -3.12 -m model.validate_robustness`. The full,
machine-readable result is
[`data/demo/synthetic-cross-scenario-validation-v1.json`](../../data/demo/synthetic-cross-scenario-validation-v1.json).

## Results

| Scenario | Unserved MW | Horizon unserved MWh | Fraction of demand unserved |
| --- | ---: | ---: | ---: |
| Baseline | 188 | 752 | 13.77% |
| Candidate A | 51 | 204 | 3.74% |
| Candidate B | 82 | 328 | 6.01% |

The horizon is a fixed four hours, so MWh is `unserved MW × 4`; it is not an
hourly reconstruction. Candidate A reduces fixture unserved demand by 137 MW
relative to baseline, versus 106 MW for B.

The deterministic 3 × 3 grid changes demand by 0.95/1.00/1.05 and generation
availability by 0.90/1.00/1.10. It found no A/B rank reversal: A is better in
seven grid cells and both candidates tie at zero unserved MW in two low-shortage
cells. An unseen, harsher fixture perturbation (1.08 demand, 0.94 availability)
also ranks A above B: 239.04 MW (956.16 MWh, 16.21%) unserved for A and 268.18
MW (1072.72 MWh, 18.19%) for B.

## Runtime and scope boundary

The recorded same-process Windows 11 / Python 3.12.10 run used one warm-up and
31 samples per shape. Median `result_payload()` execution was 0.2048 ms at 5
buses/6 lines, 0.5841 ms at 25/30, 1.0776 ms at 50/60, and 2.0763 ms at
100/120. These are fixture-materialization timings only, not power-flow, OPF,
cascade, or real-network solver timings.

Temporal transfer is not evaluated: this is a static four-hour balance, not a
time-indexed holdout. Geographic transfer is not evaluated: the fixture is not
Minnesota, New York, Texas, ERCOT, MISO, or an actual interconnection model.
Minnesota and New York validation remain future/feasible-only until a verified
case and execution exist.

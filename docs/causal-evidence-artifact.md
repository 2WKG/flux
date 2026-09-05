# Causal evidence artifact

`causal-evidence-artifact.schema.json` is the versioned contract for every causal response. Its default is fail closed: an effect may be exposed only by the `estimable_study` + `available` branch, which requires a labeled question, source versions and coverage, sample, covariates, assumptions, diagnostics, citations, estimate evidence, interval, and caveats.

`interface_fixture` is deliberately not an estimate. It is a minimal identity/classification/availability record: it must carry `FIXTURE_NOT_ESTIMABLE`, omits study evidence fields, cannot contain `estimate` or claim availability, and may demonstrate response rendering only. No unlabeled treatment, outcome, covariate, or source can satisfy the schema: each has its own definition and provenance fields.

## Sufficiency decision table

| Condition | Artifact status | Required unavailable code or required estimate evidence | Copilot behavior |
| --- | --- | --- | --- |
| UI/demo fixture, synthetic or otherwise not intended for inference | `interface_fixture` / `unavailable` | `FIXTURE_NOT_ESTIMABLE` | Render as a fixture; never state an effect. |
| Identification strategy or identifying assumptions absent | `estimable_study` / `unavailable` | `MISSING_IDENTIFICATION` | Return unavailable. |
| Treatment definition or its provenance absent | `estimable_study` / `unavailable` | `MISSING_TREATMENT_DEFINITION` | Return unavailable. |
| Outcome definition or its provenance absent | `estimable_study` / `unavailable` | `MISSING_OUTCOME_DEFINITION` | Return unavailable. |
| Required population, time, treatment, outcome, or control coverage absent | `estimable_study` / `unavailable` | `MISSING_DATA_COVERAGE` | Return unavailable. |
| Required diagnostic was not run or failed | `estimable_study` / `unavailable` | `MISSING_DIAGNOSTICS` | Return unavailable. |
| All prerequisites are present | `estimable_study` / `available` | `estimate` with estimand, method, effect, interval, confidence level, evidence citations, and caveats | Expose the qualified observational estimate and its caveats. |

An artifact may carry multiple unavailable codes. `available` is invalid when any unavailable code is present; `unavailable` is invalid without at least one code. Validation is necessary, not proof that the underlying causal assumptions are true.

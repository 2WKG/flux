# Causal evidence artifact

`causal-evidence-artifact.schema.json` is the versioned contract for the persisted backing evidence artifact; it is not the `causal_query` wire response. Its default is fail closed: an effect may be exposed only by the `estimable_study` + `available` branch, which requires a labeled question, source versions and coverage, sample, covariates, assumptions, diagnostics, citations, estimate evidence, interval, and caveats.

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
| A `citations[*]` or `estimate.evidence[*]` entry names a `source_id` that is not declared in `sources` | `estimable_study` / `unavailable` | `UNRESOLVED_CITATION` | Return unavailable; never fabricate a citation from `sources`. |
| All prerequisites are present | `estimable_study` / `available` | `estimate` with estimand, method, effect, interval, confidence level, evidence citations, and caveats | Expose the qualified observational estimate and its caveats. |

An artifact may carry multiple unavailable codes. `available` is invalid when any unavailable code is present; `unavailable` is invalid without at least one code. Validation is necessary, not proof that the underlying causal assumptions are true.

The schema's list and string bounds (`maxItems: 50` on `sources`, `diagnostics`, `citations`, `estimate.evidence`, `assumptions`, `estimate.caveats`; `maxLength` on every text field — 256 on identifiers, names, `estimate.estimand` and `estimate.method`, 512 on `sources[*].name`, 1024 on definitions, descriptions, coverage, periods, `assumptions[*]` and `estimate.caveats[*]`, 2048 on locators and diagnostic evidence) mirror the pydantic bounds of the `causal_query` wire models in `copilot/tools/schemas.py`, so an artifact that satisfies the schema also fits the response. `CausalData.assumptions` is unbounded on the frozen wire model, so the reader enforces the `assumptions`/`caveats` bounds (50 items, 1024 characters each) and the `estimand` bound itself at the read boundary, and it refuses any artifact file larger than 2 MiB before reading it (`artifact_unavailable`). If the schema and the wire model ever drift, the reader still fails closed: any exception raised while mapping an artifact into the response becomes the `insufficient_evidence` unavailable envelope, never a raised error.

Any string anywhere in the artifact containing `[UNVERIFIED` — including `assumptions`, `estimate.caveats`, `estimate.estimand`, `diagnostics[*].evidence`, `sources[*].name`/`coverage`, and every `question` definition or `target_population` text — is an unresolved claim (`CLAUDE.md`). The reader returns `insufficient_evidence` for such an artifact rather than presenting the tagged text as identifying evidence.

## Artifact-to-response mapping

`causal_query` reads this artifact and emits its separate wire contract. The mapping is intentionally narrow:

| Artifact evidence | `causal_query` response |
| --- | --- |
| `estimate.effect` and `estimate.method` | `answer_numbers` (`{"effect": ...}`) / `method` |
| `estimate.interval` | `interval` (`[lower, upper]`) |
| `assumptions` followed by `estimate.caveats` | `assumptions` (one list, artifact order preserved) |
| `estimate.estimand`, `effect`, `interval`, `confidence_level`, `evidence` | `evidence_rows` — exactly one row `{estimand, effect, interval: [lower, upper], confidence_level, evidence: [{source_id, locator}]}`, so every number in `answer_numbers` appears in an evidence row |
| `citations` | `citations` (copied, never derived from `sources`) |
| `question`, `sources`, `sample`, `diagnostics` | the same-named typed fields |
| registration `path` | `provenance[0].source_ref` as a repo-relative path or bare file name — never an absolute host path |

The artifact remains the durable, validated source; the response is a transient presentation shape.

# Interactive synthetic-simulation HTTP surface

`copilot.app:app` mounts the interactive surface at the public root using one
process-local service and a freshly built synthetic network per request.

All five success bodies have the same truth envelope:
`model_fidelity: "dc_screening"`,
`network_provenance: "synthetic_activsg2000"`, `limitations`, and `data`.
Each request uses a copied scenario network and every cascade call supplies
`write=False`; no route writes to DuckDB.

| Method and path | Typed inputs | Measured `data` |
| --- | --- | --- |
| `POST /scenario/edit` | `{base_scenario_id, ops:[{op:"outage", element_id}], hour?, seed?}` | `{edit_hash, feasibility:[…]}` in `data`; the immutable edit is process-memory only |
| `POST /cascade` | `{element_ids, scenario_id, hour, edit_hash?, seed?}` | one solver-produced `CascadeResult` in `data` |
| `GET /balance` | `scope=base\|edit`, `scenario_id`, `hour`, `edit_hash?` | measured `GridBalance` in `data` |
| `GET /redundancy` | `bus_id`, `scenario_id`, `hour` | measured `RedundancyScore` in `data` |
| `POST /siting/search` | `{kind:"synthetic_generation", unit_mw, scenario_id, n, hour?, seed?}` | up to five core-ranked candidate counterfactuals in `data` |

`/siting/search` deliberately has no feasibility or composite score. It ranks
the canonical model buses then performs an actual bounded counterfactual for
each returned candidate. `GET /cascade` remains
the separate persisted-artifact read route and is never replaced by this POST.

Malformed inputs produce the standard `422 invalid_input` envelope.  Missing
core inputs or a failed DC solve produce `503 unavailable`; no route returns a
plausible substitute result.

# Interactive synthetic-simulation HTTP surface

`copilot.interactive_routes.create_interactive_router(duckdb_path=..., case_path=...)`
creates an opt-in router under `/interactive`.  The default `copilot.app:app`
does not mount it.  The demo composition may mount it after the reviewed
synthetic core is available.

All five success bodies have the same truth envelope:
`model_fidelity: "dc_screening"`,
`network_provenance: "synthetic_activsg2000"`, `limitations`, and `data`.
Each request uses a copied scenario network and every cascade call supplies
`write=False`; no route writes to DuckDB.

| Method and path | Typed inputs | Measured `data` |
| --- | --- | --- |
| `POST /interactive/scenario/edit` | `{base_scenario_id, ops:[{op:"outage", element_id}], hour?, seed?}` | `{edit_hash, feasibility:[…]}` in `data`; the immutable edit is process-memory only |
| `POST /interactive/cascade` | `{element_ids, scenario_id, hour, edit_hash?, seed?}` | one solver-produced `CascadeResult` in `data` |
| `GET /interactive/balance` | `scope=base\|edit`, `scenario_id=interactive`, `hour=0`, `edit_hash?` | measured `GridBalance` in `data` |
| `GET /interactive/redundancy` | `bus_id`, `scenario_id=interactive`, `hour=0` | measured `RedundancyScore` in `data` |
| `POST /interactive/siting/search` | `{kind:"synthetic_generation", unit_mw, scenario_id, n, hour?, seed?}` | up to eight core-ranked candidate counterfactuals in `data` |

`/siting/search` deliberately has no feasibility or composite score. It ranks
the canonical model buses then performs an actual bounded counterfactual for
each returned candidate. `GET /cascade` remains
the separate persisted-artifact read route and is never replaced by this POST.

`balance` and `redundancy` measure the base synthetic network (or its saved
edit) only; they reject any scenario or hour they cannot apply with the standard
`422 invalid_input` envelope. Missing
core inputs or a failed DC solve produce `503 unavailable`; no route returns a
plausible substitute result.

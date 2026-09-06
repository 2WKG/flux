# Interactive synthetic-simulation HTTP surface

`copilot.app:app` mounts the interactive surface at the public root using one
process-local service and a freshly built synthetic network per request.

All five success bodies have the same truth envelope:
`model_fidelity: "dc_screening"`,
`network_provenance: "synthetic (ACTIVSg2000)"` (`pipelines.labels.SYNTHETIC_TOPOLOGY_LABEL`
verbatim) and `limitations`, alongside the payload's own keys. Success bodies are
unwrapped: there is no `data` member on the HTTP surface.
Each request builds a fresh static synthetic baseline and every cascade call
stays in memory; no route writes to DuckDB. The installed core does not yet
apply a persisted scenario, hourly conditions, or a stochastic seed. The only
accepted context is `scenario_id=interactive`, `hour=0`, and `seed=0` (where a
seed is accepted). Other values fail with `422 invalid_input`; the service
never relabels the static baseline as a requested scenario.

| Method and path | Typed inputs | Measured `data` |
| --- | --- | --- |
| `POST /interactive/scenario/edit` | `{base_scenario_id, ops:[{op:"outage", element_id}], hour?, seed?}` | `{edit_hash, feasibility:[…]}` in `data`; the immutable edit is process-memory only |
| `POST /interactive/cascade` | `{element_ids, scenario_id, hour, edit_hash?, seed?}` | one solver-produced `CascadeResult` plus a deterministic `cascade_id` for the exact in-memory request and core grid-input fingerprint in `data` |
| `GET /interactive/balance` | `scope=base\|edit`, `scenario_id`, `hour`, `seed`, `edit_hash?` | measured `GridBalance` in `data` |
| `GET /interactive/redundancy` | `bus_id`, `scenario_id`, `hour`, `seed` | measured `RedundancyScore` in `data` |

`siting.search` has no route on this surface: `twin.build.build_network` attaches no
candidate source, so a `/siting/search` route would be structurally `503` in every
deployment. It is deliberately not registered rather than registered-and-broken.

An edit hash remains the canonical operations-only hash, while its
process-local snapshot is additionally bound to the validated scenario, hour,
and seed.

Malformed inputs produce the standard `422 invalid_input` envelope.  Missing
core inputs or a failed DC solve produce `503 unavailable`; no route returns a
plausible substitute result.

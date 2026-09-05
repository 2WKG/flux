# Versioned API envelopes and unavailable/error semantics

Contract for every read route on the Copilot HTTP surface (spec 05 owns the
route names; spec 00 §4.2 pins the list). Implemented in
[`copilot/api/envelope.py`](../../copilot/api/envelope.py) and
[`copilot/api/errors.py`](../../copilot/api/errors.py); contract tests live in
`copilot/api/test_envelope.py`.

Current envelope version: **`v1`** (`copilot.api.API_VERSION`). Bump it on any
breaking change to the shapes below.

## Success

```json
{
  "status": "ok",
  "data": { "...": "route-specific payload" },
  "meta": {
    "api_version": "v1",
    "request_id": "3f2c…",
    "generated_at": "2026-09-05T18:04:11Z",
    "artifacts": [
      {
        "artifact_id": "cascade_runs",
        "artifact_version": "uri_2021-s0-ab12cd34",
        "source_kind": "simulated"
      }
    ],
    "partial": false
  }
}
```

- `meta.artifacts` is the provenance of what produced `data`. `source_kind` is
  one of `fixture | observed | simulated | heuristic | retrieval`, so a fixture
  answer is never presented as an observed one.
- `partial: true` marks a documented short result (for example
  `GET /elements/critical` returning fewer than `n` elements because only that
  many cascades are persisted). It never means fabricated filler.

Build one with `copilot.api.success(payload, request_id=…, artifacts=…)`.

## Failure

The same shape for all four failure classes:

```json
{
  "status": "unavailable",
  "data": null,
  "error": {
    "code": "unavailable",
    "message": "Cascade artifacts for scenario 'uri_2021' have not been built.",
    "retryable": true,
    "retry_after_s": 30,
    "details": { "scenario_id": "uri_2021" }
  },
  "meta": { "api_version": "v1", "request_id": "3f2c…", "generated_at": "…", "artifacts": [], "partial": false }
}
```

| Class | Exception | `status` | HTTP | `code` | `retryable` | Meaning |
|---|---|---|---|---|---|---|
| Unavailable | `UnavailableError` | `unavailable` | 503 (+ `Retry-After: 30`) | `unavailable` | yes, `retry_after_s: 30` | Required artifact absent, unbuilt, stale, or not yet computed |
| Invalid input | `InvalidInputError` | `error` | 422 | `invalid_input` | no | Parameters malformed or outside the supported contract |
| Not found | `NotFoundError` | `error` | 404 | `not_found` | no | Named scenario, layer, site, or line does not exist |
| Server failure | `InternalError` | `error` | 500 | `internal_error` | no | Unexpected server-side failure; message is fixed |

Rules:

- **Unavailable is never an empty success.** A missing artifact returns the
  failure envelope above, not `status: "ok"` with `[]`, `null`, or zeros. A
  route that cannot answer raises; it does not invent a default.
- **Not found vs unavailable.** The target does not exist → `not_found`. The
  target exists but its artifact has not been produced → `unavailable`. The
  documented `national_hex` "not built" case is `unavailable`, not a 404.
- Every response carries `meta.request_id`, echoed in the `X-Request-ID`
  response header. A client-supplied `X-Request-ID` is reused when present.

## Safety

- Envelope models are `extra="forbid"` and `frozen`, so no field can be
  smuggled into a response by an upstream dict.
- `error.message` is author-written and safe to display. Exception text is
  never copied into it: `internal_error_from()` logs the real exception
  server-side and returns the fixed `internal_error` message plus the request
  id, so raw DuckDB errors, file paths, and connection strings stay out of
  responses.
- `error.details` is a small `str -> str` map for stable hints such as
  `{"field": "query.hour"}`. `safe_details()` drops keys naming a secret,
  credential, path, URL, SQL, or traceback, truncates values to 200 characters,
  and caps the map at 10 entries.

## Using it in a route

```python
from copilot.api import SuccessEnvelope, UnavailableError, install_error_handlers, success

app = install_error_handlers(FastAPI())

@app.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, request: Request) -> SuccessEnvelope[Scenario]:
    row = repo.scenario(scenario_id)
    if row is None:
        raise NotFoundError(f"Unknown scenario {scenario_id!r}.")
    if not row.has_cascade:
        raise UnavailableError(
            "Cascade artifacts for this scenario have not been built.",
            details={"scenario_id": scenario_id},
        )
    return success(row.payload, request_id=request_id_of(request), artifacts=(row.artifact,))
```

`install_error_handlers(app)` also maps FastAPI's own
`RequestValidationError` to `invalid_input` and any unhandled exception to
`internal_error`, so a route cannot fall back to a framework-shaped error body.

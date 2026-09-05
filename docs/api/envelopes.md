# API failure envelopes

**Scope:** This document defines the **failure contract only** for every read route on the Copilot HTTP surface (spec 05 owns the route names; spec 00 §4.2 pins the list). Success payloads are unwrapped exactly as spec 00 §4.2 and spec 05 specify them: bare arrays for `/scenarios`, equality-tested tool-dict pass-throughs for `/cascade` and `/site-score`, GeoJSON/Arrow IPC bytes for `/layers/{name}` — there is deliberately no success envelope. Implemented in [`copilot/api/envelope.py`](../../copilot/api/envelope.py) and [`copilot/api/errors.py`](../../copilot/api/errors.py). **Version: `v1`** (`copilot.api.API_VERSION`); bump on any breaking change.

## Failure envelope

```json
{
  "status": "error",
  "data": null,
  "error": {
    "code": "not_found",
    "message": "Scenario 'unknown_id' does not exist.",
    "retryable": false,
    "retry_after_s": null,
    "details": {}
  },
  "meta": {
    "api_version": "v1",
    "request_id": "3f2c…",
    "generated_at": "2026-09-05T18:04:11Z"
  }
}
```

## Error classes

| Exception | `status` | HTTP | `code` | Retryable | `Retry-After` |
|---|---|---|---|---|---|
| `UnavailableError` | `unavailable` | 503 | `unavailable` | yes | 30 s |
| `InvalidInputError` | `error` | 422 | `invalid_input` | no | — |
| `NotFoundError` | `error` | 404 | `not_found` | no | — |
| `InternalError` | `error` | 500 | `internal_error` | no | — |

## Rules

- **Unavailable is never an empty success.** A missing or unbuilt artifact raises rather than returning `[]`, `null`, or zeros.
- **Not found vs unavailable:** target does not exist → `not_found`; target exists but its artifact is not built → `unavailable`. **Correction:** `GET /layers/national_hex` when not built returns a `not_found` 404 failure envelope (spec 06 §"Data loading"/`national_hex`: the client hides the toggle with a "not built" tooltip off the 404), not 503.
- `partial` stays inside the route payload where spec 00 §4.2 puts it (`GET /elements/critical` returns `{"partial": true}` in its body); the envelope does not carry it.
- Every response carries `X-Request-ID` (stamped by middleware in `install_error_handlers`); a client-supplied header value is reused.

## Safety

- Models are `extra="forbid"` and frozen; no field can be smuggled in.
- `internal_error_from()` logs the real exception server-side and returns a fixed message, so raw DuckDB errors, paths, and credentials never reach a response.
- `error.details` is a small author-written `str → str` map (max 10 keys) for stable hints like `{"field": "query.hour"}` — never populated from exception text.

## Usage

```python
from copilot.api import NotFoundError, UnavailableError, install_error_handlers
from fastapi import FastAPI

app = install_error_handlers(FastAPI())

@app.get("/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str):
    row = db.scenario(scenario_id)
    if row is None:
        raise NotFoundError(f"Unknown scenario {scenario_id!r}.")
    if not row.cascade_built:
        raise UnavailableError(
            "Cascade not yet built for this scenario.",
            details={"scenario_id": scenario_id}
        )
    return row.to_dict()  # unwrapped payload
```

**Caveat:** The catch-all `Exception` handler in `install_error_handlers` is served by Starlette's outermost `ServerErrorMiddleware`, which runs outside CORS middleware — a cross-origin browser client sees a network error rather than the 500 envelope.

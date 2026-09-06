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
- Every response carries `X-Flux-Api-Version: v1`. This is response metadata, not a success envelope; success payload bodies remain exactly the route payloads specified by specs 00 and 05.
- `X-Flux-Artifact` appears only on a successful `GET /cascade` response. Its value is the same resolved immutable `artifact_id` in that response body. It is omitted from every other success response and every failure: a logical artifact named in failure details is not a selected immutable artifact.
- CORS exposes `X-Request-ID`, `X-Flux-Api-Version`, and `X-Flux-Artifact` to browser API clients.

## Safety

- Models are `extra="forbid"` and frozen; no field can be smuggled in.
- `internal_error_from()` logs the real exception server-side and returns a fixed message, so raw DuckDB errors, paths, and credentials never reach a response.
- `error.details` is a small author-written `str → str` map (max 10 keys) for stable hints like `{"field": "query.hour"}` — never populated from exception text.

## Ask attempt transport

`POST /ask` is the one streaming exception to the JSON failure-envelope surface.
Its deployment factory accepts an explicit local `ask_backend`; the default is no
backend and streams the v1 `lifecycle` followed by an explicit `unavailable`
terminal. The route does not construct a provider or make a network call. A
configured backend may inject a provider after it has supplied local tool
evidence; an absent, failed, or cancelled provider becomes the documented SSE
terminal rather than a fabricated answer.

The injected backend turn and provider text iterator are cooperative async
boundaries. They begin only after the lifecycle event is sent, so the transport
can emit keepalives and propagate a client disconnect to them. A backend or
provider failure at that live phase is one safe SSE terminal; it cannot change
an already-started stream into an HTTP error envelope.

The client supplies a 16–128 character URL-safe `attempt_id`; accepted streams
echo it in `X-Flux-Attempt-Id`. Replay storage is not implemented, so a valid
`Last-Event-ID` resume is rejected as unavailable before a stream begins and a
malformed value is a 422 input failure. The transport sends `: keepalive`
comments every 15 seconds while idle. Comments have no SSE id and never advance
the v1 application sequence.

The local backend proof uses fixture-labelled persisted score retrieval, bounded
read-only SQL, and deterministic local retrieval. It does not claim a live
provider, a numerical topology solve, or real topology availability.

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

**Caveat:** The request middleware converts an unhandled route exception to the
fixed 500 envelope before it escapes the configured CORS middleware. Errors
after an SSE response has started cannot be replaced with an HTTP envelope; the
stream emits its one safe terminal when it can still be delivered.

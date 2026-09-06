# SSE event schema and delivery semantics

## Status and bounded scope

This is the v1 transport contract for a future `POST /ask` copilot stream.
It defines event envelopes and delivery rules only. It adds no endpoint, server,
client, event store, replay system, or authorization mechanism; it must not be
read as evidence that any streaming behavior exists at runtime.

The contract covers one answer attempt at a time. It does not define prompts,
tool internals, database schemas, or UI behavior.

## Wire format and ordering

The response media type is `text/event-stream; charset=utf-8`. Each event is
normal SSE with a blank line after it:

```text
id: 7
event: text
data: {"v":1,"seq":7,"delta":"A county-level outage model "}

```

- `data` is exactly one UTF-8 JSON object; a producer must not split an object
  over several `data:` lines.
- `v` is the major schema version. This document defines `v: 1`.
- `seq` and SSE `id` are the same positive decimal integer, scoped to one
  attempt. The first application event is `1`; later events increment by one.
- Clients reconstruct the stream by `seq`, not arrival time. A missing,
  repeated, non-contiguous, malformed, or `id`/`seq`-mismatched event is a
  protocol error, never a reason to invent content.
- Unknown fields and unknown event names are ignorable for forward
  compatibility. A response never mixes major versions.

Tools may run concurrently, but their observable events are serialized into
this one sequence. A `tool_call` precedes its matching `tool_result`;
unrelated calls and results may interleave.

## Event types

### `lifecycle`

The first application event for an accepted attempt. Required: `v`, `seq`, and
`status: "started"`. It lets a client distinguish an accepted stream from a
connection that failed before the application protocol began.

```json
{"v":1,"seq":1,"status":"started"}
```

### `text`

An incremental display fragment. Required: `v`, `seq`, and non-empty `delta`.

```json
{"v":1,"seq":7,"delta":"A county-level outage model "}
```

Clients append `delta` exactly once in sequence order. The event does not make
an unverified number safe to display; normal copilot verification still owns
that decision.

### `tool_call`

An observable start of a model-requested tool invocation, not proof of success.
Required: `v`, `seq`, unique opaque `call_id`, `tool`, and validated `input`.

```json
{"v":1,"seq":8,"call_id":"call_01J8...","tool":"score_site","input":{"site_id":"site_tx_0007","unit_mw":300,"scenario_id":"uri_2021"}}
```

Inputs must be redacted or summarized before emission when they contain a
credential, protected data, or unsafe volume.

### `tool_result`

The one outcome for a previous `tool_call`. Required: `v`, `seq`, `call_id`,
`tool`, boolean `ok`, and `elapsed_ms`. It contains exactly one of `result`
when `ok` is true or `error` when false.

```json
{"v":1,"seq":9,"call_id":"call_01J8...","tool":"score_site","ok":true,"result":{"site_id":"site_tx_0007","grid_value_score":82.1},"elapsed_ms":124}
```

```json
{"v":1,"seq":9,"call_id":"call_01J8...","tool":"score_site","ok":false,"error":{"code":"timeout","message":"The site scoring tool did not finish in time."},"elapsed_ms":20000}
```

Failure is explicit. A producer never substitutes a plausible value, fallback
score, or fabricated result. `result` is a bounded safe-to-display
serialization, not an unlimited backend response.

### `citation`

A retrieved source that may support an external claim. Required: `v`, `seq`,
unique `citation_id`, `doc`, `title`, `page`, and `chunk_id`; `locator`,
`excerpt`, and `url` may be null.

```json
{"v":1,"seq":10,"citation_id":"cite_01J8...","doc":"10-cfr-part-100.pdf","title":"10 CFR Part 100","page":12,"chunk_id":"10cfr100-p12-c2","locator":"§ 100.10","excerpt":"…","url":null}
```

Retrieval alone does not validate a model statement.

### `done`

The successful terminal event. Required: `v`, `seq`, `status: "completed"`,
and `verified`. When `verified` is false, `unverified_numbers` is required;
`usage` is optional and omitted when unavailable rather than synthesized.

```json
{"v":1,"seq":11,"status":"completed","verified":true,"unverified_numbers":[],"usage":{"input_tokens":1320,"output_tokens":241}}
```

### `error`

The unsuccessful terminal event. Required: `v`, `seq`, `status: "failed"`,
and `error`, which has a stable `code`, safe user-facing `message`, and boolean
`retryable`.

```json
{"v":1,"seq":11,"status":"failed","error":{"code":"deadline","message":"The answer could not finish within the request deadline.","retryable":true}}
```

The closed v1 code set is: `invalid_request`, `unavailable`, `deadline`,
`upstream_error`, `tool_error`, `refusal`, `cancelled`, and `protocol_error`.
Unavailable dependencies and failures are reported as such: never silently
replace an answer, tool value, citation, or success state.

## Completion, heartbeats, and reconnect

Every attempt emits exactly one terminal event: one `done` or one `error`,
never both. No application event may follow it. Servers should stop work
promptly on disconnect.

**Normative — a terminal-less stream is `request_failed`.** If the stream closes
(EOF, abort, or connection loss) with neither a terminal `done` nor a terminal
`error`, the server has broken this contract, and the client marks the attempt
**failed**, not completed and not merely incomplete. The client emits the frozen
UI token `request_failed` — never `unavailable`, which is reserved for a cause
the server itself declared — carrying the named code
`stream_ended_without_terminal` so the surface shows which failure it is rather
than a bare sentence. The client never fabricates the terminal event it did not
receive: any text already delivered is retained as incomplete. Decided as OQ-1
in [`../specs/spec-code-reconciliation.md`](../specs/spec-code-reconciliation.md)
on 2026-09-06. Implemented by `web/src/ask/run-state/reducer.ts`
(`stream_closed`) and `web/src/failure-states/adapters.ts` (`fromStreamClose`).

While active and otherwise silent for 15 seconds, a server should send a
comment heartbeat:

```text
: keepalive

```

Heartbeats carry no id, do not advance `seq`, are not replayed, and are ignored
by clients.

Because `/ask` uses `POST`, a client cannot rely on `EventSource` automatic
reconnect. For every initial request, the client creates an opaque
`attempt_id` (16--128 URL-safe ASCII characters) and sends it as the required
top-level `attempt_id` field in the JSON request body. Before starting the
stream, the server echoes that exact value in the `X-Flux-Attempt-Id` response
header. The header is the acknowledgement that binds this response to that
attempt; application event ids remain sequence numbers, not attempt ids.

To resume, the client sends the same body `attempt_id` and a
`Last-Event-ID` header equal to the last fully processed event id. A server
must reject malformed identifiers, a missing/invalid `Last-Event-ID` on a
known attempt, or an id that belongs to a different/expired attempt as
`invalid_request` (or an HTTP 4xx before streaming). If replay is supported,
the server sends events with strictly greater `seq`, in order, then continues
live delivery. It never duplicates an event. A fresh `attempt_id` starts at
sequence 1 and must not be used to resume another attempt.

Replay is optional infrastructure, not an implied implementation promise.
Until it exists, a resume request is rejected with `unavailable` (or an HTTP
error before streaming). The client must not silently retry a potentially
non-idempotent request. A malformed, out-of-range, or attempt-mismatched
`Last-Event-ID` is `invalid_request`.

## Safe payload limits

The producer enforces these limits before serialization:

| Item | v1 limit | Behavior at the limit |
| --- | ---: | --- |
| JSON `data` payload | 8 KiB UTF-8 | Split text; summarize/truncate structured payloads with `truncated: true`. |
| `text.delta` | 4 KiB UTF-8 | Split at a Unicode code-point boundary into later `text` events. |
| `tool_call.input` | 4 KiB UTF-8 | Redact/summarize and set `input_truncated: true`; never expose secrets. |
| `tool_result.result` | 8 KiB before envelope | Apply row/chunk caps, then set `truncated: true` with omission metadata. |
| `citation.excerpt` | 1,200 characters | Truncate and set `excerpt_truncated: true`; keep source identity. |
| Application events | 1,000 per attempt | End with one terminal `error`; do not silently drop later events. |

The serialized envelope must still fit the 8 KiB limit. If a safe valid form
cannot fit, send one terminal `error`, never malformed data.

## Versioning

`v` is major-only. v1 consumers ignore additive fields and unknown event types.
Removing or changing a required field, its meaning/type, sequencing, or
terminal behavior requires a new major version. A future request must negotiate
its schema version explicitly. Until negotiation exists, v1 is the only
documented contract; a server unable to honor it reports `unavailable`.

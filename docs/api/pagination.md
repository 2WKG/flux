# API pagination and deterministic ordering

**Scope:** shared implementation contract for future paginated Copilot read
routes. It complements the existing [failure-envelope contract](envelopes.md).
It does not alter an existing route payload or introduce a success envelope.

`copilot.api.pagination` exports the following route-owned building blocks:

| Export | Contract |
| --- | --- |
| `PageRequest(limit=50, offset=0)` | `limit` is an integer from 1 through 100; `offset` is an integer from 0 through 10,000. Routes bind `PageRequest.sql_parameters` to `LIMIT ? OFFSET ?`; they do not interpolate client values. |
| `SortTerm(field, direction)` | A persisted-column identifier and `ASC` or `DESC`. Identifiers are quoted only after the helper accepts its simple identifier syntax. |
| `DeterministicOrder(primary, tie_breaker)` | A primary order followed by a distinct, persisted unique-key field. Its `clause(page)` produces the complete `ORDER BY … LIMIT ? OFFSET ?` suffix and bound values. |

Each route declares its own primary fields and documented unique tie-breaker. For
example, a score ranking can use `score_value DESC, artifact_id ASC`; a route
must not rely on physical database order when scores tie. `DeterministicOrder`
records the tie-breaker but cannot prove a field is unique, so the consuming
route's tests must use tied rows and assert the documented order.

The helper is for browser/API reads, not the frozen model-facing tool inputs:
`top_lines(region, tech, n)` remains unpaginated and has no model-facing sort
parameter under specs 00 and 05.

## Data status and empty pages

Success bodies remain unwrapped, as required by the existing read-route
contract. A valid page may be empty only after the route has established that
the selected artifact is available. A missing database/table, an unavailable
Minnesota artifact, invalid persisted data, or an unsupported result continues
to use the existing `UnavailableError`/failure envelope. Pagination must never
replace such a state with `[]`, zero values, a guessed total, or a fabricated
next cursor.

This contract deliberately reports no `total`, `total_pages`, or `next` value:
none is truthful without an additional bounded count/query contract. Routes may
add one later only when they can derive and document it from the same qualified
artifact selection.

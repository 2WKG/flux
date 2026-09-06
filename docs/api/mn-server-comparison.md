# Minnesota server comparison

`POST /mn/comparisons` accepts versioned baseline and candidate context IDs.
It reads two persisted, validated Minnesota aggregate model artifacts with the
same metric and unit, then returns the server-computed signed candidate-minus-
baseline delta.  Every metric includes persisted provenance and every scene
highlight ID comes from persisted artifact identity.  Missing artifacts,
metrics, provenance, or highlight IDs return the standard unavailable error;
the route never implies topology, flow, or temporal outage data.

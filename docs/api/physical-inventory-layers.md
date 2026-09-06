# Physical inventory map transport

`GET /api/v1/grid/layers/{layer}` reads a published, versioned physical
inventory release. `state` (`tx` or `mn`) and a semantic `version` are
required. `bbox=west,south,east,north` is optional EPSG:4326 viewport filtering;
`limit` is 1–100; an opaque `cursor` is valid only for the same release SHA,
state, version, layer, and viewport.

Current layer names are the physical asset classes published by each release:
Texas has `line`, `generation`, and `storage`; Minnesota additionally has
`substation`; `all` is the explicit union. Items sort by stable `asset_id`.
The response's `page.total` is the count after the requested class and viewport
filter, and `coverage` is copied from the release without recalculation.

Each item preserves `native_geometry`, `native_crs`, `geometry_status`, accuracy
basis, precision, source record identity, source version, and retrieval time.
`display_geometry` is an EPSG:4326 renderer-only transform, with its method in
`transform_provenance`. Renderers must draw only `display_geometry` and retain
the native/provenance fields for inspection. An unavailable geometry has null
native and display geometries and `availability: "unavailable"`; it is never
placed in a viewport result. Coverage retains its unavailable and unknown counts
so its absence is visible instead of being interpreted as a zero.

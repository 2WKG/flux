# Minnesota demo handoff — local proof and delivery boundary

**Applies to:** the Minnesota demonstration planning contract in
[`docs/specs/10-minnesota-demo.md`](../specs/10-minnesota-demo.md).

**This handoff:** documents what can be proved from a local checkout. It does
not publish a URL, configure a tunnel, add an API proxy, or change the demo
launcher. The launcher was delivered separately in merged PR #282.

## Minnesota evidence boundary

Minnesota is not the checked-in static fixture. The current browser build
bundles `data/demo/bundle.json`; it is a synthetic five-bus demonstration and
must not be labelled Minnesota, MISO, ERCOT, or an operational grid model.

The Minnesota planning contract permits two distinct data modes:

| Mode | What a result may say | What it must not imply |
| --- | --- | --- |
| Source-backed topology | A validated, versioned source provides the required bus, branch, impedance/reactance, base-MVA, allocation, rating, terms, and source-to-solver mapping evidence. | A source inventory alone proves flows, contingencies, outages, or interconnection feasibility. |
| Aggregate stress | A named regional metric with its formula, units, allocation assumptions, artifact IDs, and source/synthetic label. | Bus flows, line loading or ratings, DC power flow, N-1 results, trips, cascades, or a Minnesota grid twin. |

Until the source-decision record accepts every topology input, describe the
Minnesota path as **aggregate stress**, or return an explicit unavailable
result. Do not repurpose the synthetic fixture or the legacy ACTIVSg2000 path
as a Minnesota substitute.

## Static browser versus optional API

The local static origin and the optional FastAPI process are separate services.
The browser build makes no runtime data request and `web/server.mjs` has no API
route: an unknown path, including `/api/demo`, returns the SPA HTML shell. A
`200` from that path is therefore not API evidence.

`scripts/dev/launch_demo.sh --offline` starts only the loopback static origin.
`--live --duckdb /absolute/path/to/grid.duckdb` additionally starts a local,
read-only FastAPI process over an already-built DuckDB artifact. It does not
wire the browser to that API, provide Minnesota topology, configure a model
provider, or expose either process externally. The stable operating detail is
in [`local-startup.md`](local-startup.md).

## Local proof commands

From the repository root, use one of these local-only commands:

```bash
# Static synthetic browser proof only.
scripts/dev/launch_demo.sh --offline

# Optional local API proof; the caller supplies an existing readable artifact.
scripts/dev/launch_demo.sh --live --duckdb /absolute/path/to/grid.duckdb
```

The launcher prints its run directory and records its processes there. Stop
only that invocation with its printed run directory, for example:

```bash
scripts/dev/launch_demo.sh --run-dir /tmp/flux-demo-launch-$USER --stop
```

While the offline origin is running, prove the static boundary rather than
treating a fallback shell as an API response:

```bash
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:4317/
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:4317/api/demo
curl -s http://127.0.0.1:4317/ | shasum -a 256
curl -s http://127.0.0.1:4317/api/demo | shasum -a 256
```

The expected evidence is HTML for both paths and identical digests. Use the
actual port reported by the launcher when an override is supplied. For live
mode's API health and artifact checks, follow the commands in
[`local-startup.md`](local-startup.md); their success is local API availability,
not browser integration or public serving.

## External delivery remains pending (2WKG-84)

No durable external Minnesota deployment is established by this handoff.
2WKG-84 owns the external tunnel/origin mapping and its verification. A local
listener, a successful local curl, or a Cloudflare edge response cannot prove
that the Minnesota browser flow and its API boundary are externally reachable.

Do not claim public deployment until the 2WKG-84 owner has supplied and
verified the durable origin-to-tunnel mapping for the intended artifact, and an
independent external check confirms the expected static asset and any separately
approved API route. The existing static-origin inventory is background only:
[`static-origin-and-tunnel.md`](static-origin-and-tunnel.md). It does not turn
the current synthetic static fixture into a Minnesota deployment.

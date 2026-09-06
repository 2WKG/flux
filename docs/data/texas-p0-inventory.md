# Texas P0 public-input inventory

[`data/sources/texas-p0-inventory.json`](../../data/sources/texas-p0-inventory.json)
is the reviewable, machine-readable record for the Texas P0 sources that the
legacy adapter declares: synthetic topology/geometry, county geometry and
hazards, public outage/weather/storm context, EIA/ERCO aggregates, and public
siting/critical-load geometry.

It is intentionally evidence-first. The repository does not track raw source
files, DuckDB databases, or Parquet outputs. Therefore a source with no
checked-in immutable receipt is `unavailable`, not silently treated as
ingested. `validated` means the checked-in evidence includes a reproducible
receipt; it does not mean a fresh clone contains the raw artifact or database.
`excluded` is a deliberate P0 scope decision, and is never shorthand for a
restricted or non-public source.

Generate a report without fetching or modifying source data:

```powershell
py -3.12 scripts/validate_texas_p0_inventory.py --report "$env:TEMP\flux-texas-p0-inventory-report.json"
```

Pass `--raw-root <path>` to additionally report whether declared raw artifacts
are locally present and to re-check any declared SHA-256 values. Keep generated
reports outside the repository unless deliberately publishing a dated evidence
snapshot; their local-artifact presence is expected to vary by machine.

The inventory's synthetic-topology caveat is binding: ACTIVSg2000 is a
synthetic Texas-shaped network, not the real ERCOT network. A public geometry
or nearest synthetic-bus association never establishes real electrical
connectivity or a service connection.

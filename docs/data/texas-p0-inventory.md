# Texas P0 public-input inventory

[`data/sources/texas-p0-inventory.json`](../../data/sources/texas-p0-inventory.json)
is the reviewable, machine-readable record for the Texas P0 sources that the
legacy adapter declares: synthetic topology/geometry, county geometry and
hazards, public outage/weather/storm context, EIA/ERCO aggregates, and public
siting/critical-load geometry.

It is intentionally evidence-first. The repository does not track raw source
files, DuckDB databases, or Parquet outputs. Therefore a source with no
checked-in immutable receipt is `unavailable`, not silently treated as
ingested. `excluded` is a deliberate P0 scope decision, and is never shorthand
for a restricted or non-public source.

The validator (`scripts/validate_texas_p0_inventory.py`) enforces the status
vocabulary rather than trusting the hand-written JSON:

- `ingested` and `validated` both require a `checked_in_receipt` path to a
  tracked receipt and a non-null `ingestion_timestamp`; the receipt must exist,
  parse, carry the same `retrieved_at`, and match every `sha256:` immutable id
  the record declares.
- `validated` additionally requires at least one artifact with an immutable
  identifier. `ingested` is the weaker claim: a tracked receipt records the
  retrieval, but no artifact carries an immutable identifier yet. Neither
  status means a fresh clone contains the raw artifact or database.
- `unavailable` and `excluded` must have `checked_in_receipt` absent or null
  and a null `ingestion_timestamp`.

Generate a report without fetching or modifying source data:

```sh
uv run --extra dev python scripts/validate_texas_p0_inventory.py
```

The report is printed to stdout; pass `--report <path>` to write it to a file
instead. Generated reports carry a `generated_at` timestamp, so keep them
outside the repository unless deliberately publishing a dated evidence
snapshot. On Windows PowerShell, for example:

```powershell
py -3.12 scripts/validate_texas_p0_inventory.py --report "$env:TEMP\flux-texas-p0-inventory-report.json"
```

Pass `--raw-root <path>` to additionally report whether declared raw artifacts
are locally present and to re-check any declared SHA-256 values; local-artifact
presence is expected to vary by machine. When `validation.passed` is false,
`summary` counts and per-record `artifacts`/`checked_in_receipt` details are
not evidence: records that failed schema validation are reported with
`schema_valid: false` and no artifact or receipt checks.

The inventory's synthetic-topology caveat is binding: ACTIVSg2000 is a
synthetic Texas-shaped network, not the real ERCOT network. A public geometry
or nearest synthetic-bus association never establishes real electrical
connectivity or a service connection.

For the placement and truth-label policy of the reusable 3D archetypes, see
[`texas-asset-taxonomy.md`](texas-asset-taxonomy.md). It cross-references this
inventory without treating generic meshes as source evidence or changing the
shared 3D asset contract.

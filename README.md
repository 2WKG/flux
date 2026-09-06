# Flux — grid resilience demo

Flux is a local, evidence-labeled Texas and Minnesota energy demo. The Texas
model mode uses a synthetic ACTIVSg2000 DC screening network; physical inventory
and Minnesota aggregate coverage are separate views and do not imply a complete
Minnesota electrical topology.

## Run the full local demo

From the repository root on the prepared demo machine:

```bash
scripts/dev/launch_demo.sh --live \
  --duckdb /Users/joshua/buckeye-swarm/flux/data/duck/grid.duckdb \
  --case /Users/joshua/buckeye-swarm/flux/data/raw/activsg2000_current/case_ACTIVSg2000.m
```

Open <http://127.0.0.1:4317>. Use **Asset inventory** for source-backed Texas
and Minnesota assets, and **Texas grid model** for the explicitly synthetic
DC cascade. Weather history comes from persisted HRRR artifacts. JEPA timelines
are experimental historical observed-count forecasts and show their lineage or
an explicit unavailable state. Ask responses expose their local tool trace and
limitations.

Stop this invocation with:

```bash
scripts/dev/launch_demo.sh --run-dir /tmp/flux-demo-launch-$USER --stop
```

For a labeled user LaunchAgent that survives terminal exit, add `--persist` to
the live command; remove it with `scripts/dev/launch_demo.sh --remove-persist`.
The complete startup, recovery, and evidence references are in
[`docs/runbooks/local-startup.md`](docs/runbooks/local-startup.md),
[`docs/data/runtime-store.md`](docs/data/runtime-store.md), and
[`docs/specs/11-interactive-simulation.md`](docs/specs/11-interactive-simulation.md).

## Repository context

The project is expanding from the current synthetic preview toward source-backed network, scenario, and candidate-site datasets. The wider research plan and data catalog live in `docs/specs/` and `datasets/README.md`. Bulk downloads, parquet outputs, and DuckDB files remain outside Git.

## Verify

```powershell
python -m unittest discover -s model -p "test_*.py"
npm --prefix web run build
```

The synthetic fixture's cross-scenario validation report is documented in
[`docs/data/synthetic-cross-scenario-validation.md`](docs/data/synthetic-cross-scenario-validation.md).

The current fixture is not a Texas-grid model, outage forecast, interconnection study, or licensing assessment.

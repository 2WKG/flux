# Texas P0 bounded public-source receipts

This receipt set records three public source families actually retrieved and
validated on 2026-09-06. It is legacy Texas data-intake evidence only; it does
not change the Minnesota demo authority, create a real ERCOT topology, or make
an untracked database artifact available in a fresh clone.

| Source | Evidence | Validation |
| --- | --- | --- |
| Census TIGER/Line 2024 counties | [`texas-tiger-2024.json`](../../data/sources/texas-tiger-2024.json) | `load_counties` loaded 254 Texas counties and transformed geometry to EPSG:4326. |
| FEMA NRI v1.20 counties | [`texas-nri-v1.20.json`](../../data/sources/texas-nri-v1.20.json) | `load_nri` loaded 254 Texas county rows, with no missing population or NRI score. |
| PUDL EIA-860 v2026.2.0 | [`texas-pudl-eia860-v2026.2.0.json`](../../data/sources/texas-pudl-eia860-v2026.2.0.json) | `load_eia860_plants` loaded 1,584 Texas plants and 628,701 generator-history rows. |

The source URLs, versions, licenses, raw paths, byte counts, SHA-256 values,
coverage, units, and uncertainty boundaries remain in the inventory and linked
receipts. Raw archives/Parquet and temporary DuckDB validation outputs are
gitignored.

## Reproduce the bounded intake

```sh
mkdir -p data/raw/tiger/2024 data/raw/nri/v1.20 data/raw/pudl/v2026.2.0
curl --fail --location --output data/raw/tiger/2024/tl_2024_us_county.zip \
  https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip
curl --fail --location --output data/raw/nri/v1.20/NRI_Table_Counties.zip \
  https://www.fema.gov/about/reports-and-data/openfema/nri/v120/NRI_Table_Counties.zip
curl --fail --location --output data/raw/pudl/v2026.2.0/out_eia__yearly_plants.parquet \
  https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/v2026.2.0/out_eia__yearly_plants.parquet
curl --fail --location --output data/raw/pudl/v2026.2.0/out_eia__yearly_generators.parquet \
  https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/v2026.2.0/out_eia__yearly_generators.parquet
uv run --extra dev python scripts/validate_texas_p0_inventory.py --raw-root data/raw
```

The full legacy Texas builder still requires EIA-930, Storm Events, NWS
crosswalk, EAGLE-I, and NTAD inputs. EAGLE-I annual payloads are 1.1–1.4 GB;
they remain explicitly unavailable pending a bounded, source-preserving intake.
No successful source receipt authorizes a synthetic-to-real connectivity claim.

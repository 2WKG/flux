# P0 Uri/Beryl calibration status

Generated from `data/calibration/p0-uri-beryl-calibration-ledger-v1.json` (SHA-256 `56d385ae89548dadc20e4f5b51101eba2169f0871b580ae507b33009f4575e50`). This is a reproducible fail-closed report, not a reconstruction or calibration claim.

## Result classes

| Observed | Proxy | Modeled | Unavailable |
| ---: | ---: | ---: | ---: |
| 0 | 0 | 0 | 2 |

## Scenario results

| Scenario | Calibration | Result class | Like-for-like comparison |
| --- | --- | --- | --- |
| uri_2021 | unavailable | unavailable | not_performed |
| beryl_2024 | unavailable | unavailable | not_performed |

No P0 Uri or Beryl calibration is available. The report fails closed because required public observations are not checked in.

## Citable topology context, not calibration evidence

`data/sources/activsg2000.json` (SHA-256 `da8335a0b2c73792574207a8999293c932a1885f7dd71c7c394c71b2d75920ed`) records: A.B. Birchfield et al., Grid Structural Characteristics as Validation Criteria for Synthetic Networks, IEEE Transactions on Power Systems, 2017, doi:10.1109/TPWRS.2016.2616385. ACTIVSg2000 is a synthetic Texas test case. It is not ERCOT topology and supplies no SCADA, nodal telemetry, ratings, restricted data, or real-world asset mapping.

## Per-result limits

### Winter Storm Uri (`uri_2021`)

- Like-for-like comparison: not_performed — No checked-in like-for-like observed and modeled quantity exists.
- Synthetic-topology mapping: No synthetic-to-real asset, line, bus, generator, or service mapping is asserted.
- Non-nodal/aggregate limit: No county, balancing-authority, or nodal comparison is reported.
- Restricted-data limit: No ERCOT topology, SCADA, nodal telemetry, ratings, or restricted data is used or claimed.
- Uncertainty: high: no calibration can be estimated without checked-in observations

### Hurricane Beryl (`beryl_2024`)

- Like-for-like comparison: not_performed — No checked-in like-for-like observed and modeled quantity exists.
- Synthetic-topology mapping: No synthetic-to-real asset, line, bus, generator, or service mapping is asserted.
- Non-nodal/aggregate limit: No county, balancing-authority, or nodal comparison is reported.
- Restricted-data limit: No ERCOT topology, SCADA, nodal telemetry, ratings, or restricted data is used or claimed.
- Uncertainty: high: no calibration can be estimated without checked-in observations

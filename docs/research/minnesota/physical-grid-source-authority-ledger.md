# Minnesota physical-grid source authority ledger

This document explains the machine-readable ledger at
`data/sources/minnesota-source-authority-ledger-v1.json`. It is an acquisition
record, not a claim that Minnesota has a complete public physical-grid map.

## Verified sources and limits

The official MnGeo/PUC Electric Utility Service Area FeatureServer is the
strongest current statewide geographic source found. It returned 192 polygon
features on 2026-09-06, uses EPSG:26915, and exposes identifiers including
`mn_utility_id`, `eusa_v5_id`, and (where populated) `eia_utility_id`.
The PUC calls this the state's official electric service-area map. It maps
retail service areas, not transmission, distribution, substations, terminals,
or electrical connectivity. Its metadata does not provide a positional-error
value, so the ledger records its review/update basis rather than inventing a
precision number.

MnGeo's utilities page says the Department of Commerce stopped supporting the
old statewide transmission-line/substation dataset on 2022-07-20 because of
accuracy problems and insufficient current information. It is therefore a
closed acquisition route for a current statewide physical inventory.

Mille Lacs County publishes native geometries through a public ArcGIS
MapServer. The queried service returned 31 transmission-line features (28 at
69 kV and 3 at 230 kV; 178.68783197 reported GIS miles) and 11 substation
features. These counts are denominators for those queried source layers only.
They are neither countywide completeness assertions nor statewide denominators.
The layers publish no captured numeric accuracy statement.

The PUC's permitting/eDockets path can yield project-specific applicant
exhibits, but the index is not an as-built statewide inventory. Its interactive
project map explicitly uses approximate locators and excludes some pending or
permitted projects. Each future filing must retain docket/document identity,
filing date, source checksum, page or GIS layer, and supersession status.

MISO's MTEP access page says maps need a website login and reliability-model
FTP access needs appropriate CEII NDA/UNDA documents. No account request,
credential, NDA, or owner request was made. The restricted status records that
fact without converting it into network coverage.

## Distribution and interfaces

The EUSA source has no feeder, device, terminal, or connectivity fields. No
statewide public distribution source was acquired. The distribution class is
therefore unavailable with a null denominator, not zero assets and not a
complete class. The same applies to real electrical connectivity.

The ledger identifies Manitoba, North Dakota, South Dakota, Iowa, and Wisconsin
as interface directions requiring asset-specific evidence. It does not assert a
count or endpoint for any interface. MISO's restricted planning/model route is
not a substitute for such evidence.

## Sources

- [MnGeo utilities data and maps](https://www.mngeo.state.mn.us/chouse/utilities.html)
- [PUC maps and EUSA description](https://mn.gov/puc/activities/maps/)
- [EUSA FeatureServer](https://arcgis.metc.state.mn.us/server/rest/services/GDRS/MNGEO_util_service_areas/FeatureServer/0)
- [Mille Lacs County utilities MapServer](https://gis.co.mille-lacs.mn.us/arcgis/rest/services/Utilities/MapServer)
- [PUC power-plant sites and transmission-line routes](https://mn.gov/elicense/a-z/?id=1083-231022)
- [MISO MTEP access page](https://www.misoenergy.org/planning/transmission-planning/mtep/)
- [Minnesota Statutes §216B.2425](https://www.revisor.mn.gov/statutes/cite/216B.2425)

Section 216B.2425 requires the Department of Commerce to maintain and annually
update a transmission-line inventory, and requires relevant owners to submit
biennial transmission reports. That legal obligation establishes an authority
and acquisition lead. It does not establish that a public, current,
machine-readable statewide geometry or connectivity artifact has been acquired.

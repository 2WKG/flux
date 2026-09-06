# Snow and blizzard candidate coverage

This bundle records five independent Upper Midwest candidate episodes: April
2018, February 2019, December 2021, and two distinct December 2022 systems.
NCEI Storm Events supplies candidate-discovery context with native event IDs
and explicit local-standard-time to UTC conversions. Four records retain
forecast-zone weather evidence; the 2022-12-14 St. Louis record is weather
`uncovered` because MNZ019 is a sub-county zone and cannot establish coverage
for county FIPS 27137.

Three records are `candidate_only` (2018-04-14, 2022-12-14, and 2022-12-21),
and two are explicit EAGLE-I acquisition `shortfall`s (2019-02-24 and
2021-12-10). No record has acquired and response-body-verified EAGLE-I annual
stream provenance. Each therefore has `outage.coverage="uncovered"`, an
`unavailable` label, no outage rate, and no five-percent positive/negative
assertion. An `UncoveredLabel` is not claimed because the necessary verified
annual stream is absent; it cannot be inferred from historical metadata.

The candidate frame is the listed event systems, selected from NWS Twin Cities
event summaries and NCEI Storm Events records. It is not a prevalence or
statistical-sufficiency sample.

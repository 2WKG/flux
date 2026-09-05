# Minnesota solver-network feasibility

**Decision (2026-09-05): use the aggregate fallback now. Do not build a Minnesota
AC/DC power-flow network from public sources.** A solver network is feasible only
after an authorized MISO model transfer and a source-by-source import validation.
It is not an implementation blocker for aggregate planning views, but it is a hard
blocker for flow, contingency, thermal-loading, deliverability, or cascade claims.

## Solver gate

A usable case must deliver one versioned snapshot with (1) bus and branch identities
and their mapping to the source assets, (2) topology, voltage bases and the system
base MVA, (3) branch `r` and `x` with their units/base, (4) normal/emergency thermal
limits with their units, (5) generator and load allocations to buses, and (6) terms
that permit this project to store and use the case. None of the public candidates
below meets all six conditions.

| Candidate | Identities / mapping | `r` / `x`, base MVA, loads and generation | Thermal ratings | Version, provenance, and terms | Decision |
| --- | --- | --- | --- | --- | --- |
| **MISO MTEP reliability model** | MISO describes its Model Manager as the system for network-topology data and says reliability models are posted on its FTP/ShareFile services. The actual Minnesota case and its schema were not available to this worktree. | Do not infer any field from a public description. The required electrical and allocation fields must be checked in the delivered case. | Same: not publicly inspected. | MISO says FTP reliability-model access requires a website login and appropriate CEII NDA/UNDA; its access matrix also identifies MTEP power-flow models as restricted. [MTEP access](https://extranet.misoenergy.org/planning/transmission-planning/mtep), [access matrix](https://help.misoenergy.org/knowledgebase/article/KA-01511/en-us), [Model Manager](https://www.misoenergy.org/markets-and-operations/MSE/miso-model-manager/). | **Potential licensed path; not available now.** Obtain legal approval and a versioned delivery before attempting import. |
| **FERC Form 715** | Form 715 includes power-flow base cases and maps/diagrams, but FERC classifies Parts 2–6 as CEII. | Not publicly available for use as a case. | Not publicly available for use as a case. | [FERC Form 715](https://ferc.gov/industries-data/electric/general-information/electric-industry-forms/filing-form-no-715-annual). | **Not a public fallback.** Treat it as a CEII request path, not a scrape target. |
| **HIFLD transmission lines + DOE/NREL preliminary DLR** | HIFLD provides line features/identifiers for geographic reference; the EIA explicitly says it and HIFLD do **not** publish substation locations. Therefore the routes cannot establish a bus/branch network. [EIA FAQ](https://www.eia.gov/tools/faqs/faq.php?id=567&t=1). | Neither source supplies an inspectable AC topology, impedance/reactance, system base MVA, or bus-level load/generation allocation. | DOE/NREL publishes **modelled** static ratings in amperes and hourly rating ratios for 2007–2013; it warns that the results are not a substitute for direct sensor data and that HIFLD routes may be inaccurate. | HIFLD is public, government-works licensed, and last updated 2022-10-24. The DOE/NREL DLR dataset is public under CC BY 4.0 and explicitly identifies the 2007–2013 time range. [HIFLD metadata](https://catalog.data.gov/dataset/electric-power-transmission-lines), [DOE/NREL DLR metadata](https://catalog.data.gov/dataset/hourly-dynamic-line-ratings-for-existing-transmission-across-the-contiguous-united-states-). | **Map/context only.** Never infer connectivity or call its modelled amperes an operator limit. |
| **Minnesota service-area GIS + EIA-860/EIA-930** | Minnesota publishes reviewed utility service-area boundaries; EIA-860 publishes plant locations and generator identities/capability. These support geographic association to a utility area, not a bus. [MnGeo service-area item](https://gis.data.mn.gov/datasets/f1b545bcc02f42fcb9b9eada85c32494_0/explore), [EIA-860](https://www.eia.gov/electricity/data/eia860/). | No `r`, `x`, base MVA, bus mapping, or nodal allocation. EIA-930 is balancing-authority-level hourly demand/net-generation/interchange, not a bus model. | No branch thermal limits. | EIA-860 is a versioned annual survey; EIA-930 is an hourly balancing-authority feed. Record the actual release/report period and source URLs at ingest. [EIA-930 API catalogue](https://www.eia.gov/opendata/browser/electricity/rto). | **Approved aggregate fallback inputs.** |

The public DOE/NREL rating data is useful for a clearly labelled historical
*modelled rating* overlay only: its static-rating denominator is in amperes, its
timestamps are UTC, and its assumed conductor is chosen by voltage class. It must
not be converted into a claimed operator `rate_a`, MVA limit, or contingency limit.

## Aggregate fallback contract

The fallback has no electrical network. Its smallest reporting unit is the source
balancing authority `b`; a Minnesota utility service-area `z` is an optional
geographic allocation, never a bus.

For every hour `t`, retain these source values without reinterpretation:

\[
D_b(t) = \text{EIA-930 actual demand (MW)},\qquad
G_b(t) = \text{EIA-930 net generation (MW)}.
\]

For plant `g`, retain EIA-860 summer capability \(C_g\) in MW and associate the
plant point with `z` only by spatial containment in the Minnesota service-area
layer. Capacity is not dispatch. If, and only if, a reviewed mapping declares a
set of service areas \(Z_b\) to fully partition a reporting area `b`, define the
transparent capacity-proxy weight

\[
w_{z,b}=\frac{\sum_{g\in z} C_g}{\sum_{q\in Z_b}\sum_{g\in q} C_g},\qquad
\widehat D_z(t)=w_{z,b}D_b(t),\qquad
\widehat G_z(t)=w_{z,b}G_b(t).
\]

All \(\widehat{}\) values are **estimated MW allocations**, not measured utility
load or plant dispatch. Do not allocate a BA value when the BA/service-area mapping
is incomplete, overlapping, or unreconciled; show the BA total instead. The derived
residual \(\widehat D_z-\widehat G_z\) is an allocation balance only. It is not
interchange, a flow, congestion, or a reliability metric. Do not express any
fallback quantity in per-unit, MVA, Mvar, or line-loading percent.

At ingest, attach `source_url`, `retrieved_at_utc`, source release/report period,
file checksum, geographic filter, and the exact allocation/membership version to
every aggregate output. Preserve unknown BA membership as `NULL`, rather than
filling it by proximity.

## Claim limits and exit criteria

This fallback may say where public plants, service territories, and transmission
routes are shown, and may report BA totals or explicitly estimated geographic
allocations. It may **not** claim a Minnesota line flow, N-1 result, overload,
transfer capability, congestion, marginal loss, outage propagation, or generator
deliverability.

Exit the fallback only when an authorized MISO delivery has passed an import review
that records: model vintage and checksum; legal use/storage terms; the system and
voltage bases; counts and identifiers for buses, branches, generators, and loads;
units and completeness for `r`, `x`, and each rating class; and a reconciliation of
every generator/load allocation to a bus. Until then, absence of a field is a
reported unavailable check, not a value to synthesize.

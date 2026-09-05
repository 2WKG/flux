# Spec verification — combined summary

All ten specs in `docs/specs/` were fact-checked on 2026-09-05 by independent agents (never the
spec's author) against primary sources or live library introspection in the repo `uv` env. The
per-claim evidence lives in four ledgers under `docs/specs/verification/`; this page is the
cross-spec view: one row per spec, the corrections that change what gets built, and every
`[UNVERIFIED]` tag still open in the spec text. `verification/README.md` is the per-ledger index.

Verdicts: VERIFIED (claim stood, source recorded) · CORRECTED (spec text changed in place, old →
new recorded in the ledger) · UNVERIFIABLE (left tagged `[UNVERIFIED …]` in the spec with what
would verify it). Nothing was softened or deleted because it could not be checked.

## Counts per spec

| Spec | Verified | Corrected | Unverifiable | Ledger |
|---|---|---|---|---|
| 00 overview | 17 | 3 (+2 cross-spec mismatches flagged, not edited) | 0 new (3 pre-existing tags untouched) | `verification/00-07-08-09.md` §1 |
| 01 data ingest | 41 | 25 | 7 | `verification/01-02.md` |
| 02 outage model | 15 | 6 | 2 | `verification/01-02.md` |
| 03 cascade sim | 17 | 12 | 3 | `verification/03-04.md` |
| 04 siting engine | 15 | 19 | 7 | `verification/03-04.md` |
| 05 copilot | 30 | 9 | 0 | `verification/05-06.md` |
| 06 frontend | 24 | 9 | 2 | `verification/05-06.md` |
| 07 causal layer | 9 | 7 | 2 kept | `verification/00-07-08-09.md` §2 |
| 08 line-upgrade screen | 16 | 10 | 4 | `verification/00-07-08-09.md` §3 |
| 09 Speed-to-Power backup | 12 | 6 | 8 (3 new, 5 kept) | `verification/00-07-08-09.md` §4 |
| **Total** | **196** | **106** | **35** | |

Counts are the ledgers' own (one row per claim; a row can carry several tags). The pitch deck
(`docs/pitch/hackathon-pitches-and-designs.md`) is read-only; its 20 wrong/stale/unverifiable
claims are listed in `00-07-08-09.md` §5.

## Load-bearing corrections (these change what gets built)

1. **ACTIVSg2000 coordinates come from `ACTIVSg2000.aux`, not the June-2016 xlsx** (01, 03). The
   xlsx is the previous case version: 2,007 buses, disjoint numbering, only 98 ids shared with the
   pip `case_ACTIVSg2000.m`, 49,776 MW vs 67,109 MW load. The current-version zip's AUX maps all
   2,000 bus ids with 0 kV mismatches via `Bus.SubNum → Substation.Latitude/Longitude`
   (`coord_source='tamu_aux'`). `from_mpc` renumbers buses to row position — join by name/order.
2. **pandapower `rundcpp` is the solver; lightsim2grid is incompatible** (03, 04).
   `init_from_pandapower` raises `Unsupported element found (Impedance)`; warm `rundcpp` is
   ~9–14 ms, so a 168-h Uri replay is 6–12 s at `hour_stride=1`. lightsim demoted to stretch.
3. **847 branches import as `net.impedance`, not `net.trafo`** (03). `res_impedance` has no
   `loading_percent`; the cascade loop must compute transformer loading as
   `max(|p_from|,|p_to|)/sn_mva` or the cascade is silently lines-only.
4. **The case has no 345 kV** (03, 04). Bus kV classes are 115 / 161 / 230 / 500; every
   "345 kV" test bus became 500 kV; the `base_kv >= 138` filter leaves 725 buses.
5. **10 CFR 53.530 is FINAL, the July 2026 rule is proposed** (00, 04). Part 53 final rule
   91 FR 15696 (eff. 29 Apr 2026) carries the societal-risk language; "Modernizing Reactor
   Licensing, Safety Oversight, and Siting Practices" (91 FR 44560, 16 Jul 2026) revises Part 100
   and is not final. "Tier 1/Tier 2" is pitch vocabulary, not rule text.
6. **OR-SAGE thresholds re-sourced from ORNL/TM-2012/403 and ORNL/TM-2011/157** (04). S3 PGA
   0.3 g (1 GW) / 0.5 g (300 MW); S5 low flow ≥ 200,000 gpm / ≥ 65,000 gpm (was 50,000);
   S2 is 1⅓ × LPZ not EAB; S9 airports 5 mi, refineries 1 mi; S10 moderate-or-high landslide;
   report titles were swapped. STAND was not used in DOE's 2024 study.
7. **Several "Texas" plants are not on the ERCOT twin** (04). Pirkey/Welsh (SWEPCO) and
   Harrington/Tolk (SPS) are SPP; Fort Bliss is WECC, Red River AD is SPP → `interconnection`
   field, `bus_id NULL`; candidate set is ~12, not 15–25; "Fort Cavazos" → "Fort Hood".
8. **LightGBM 4.7 kwargs** (02). `scale_pos_weight='auto'` raises `LightGBMError`;
   `early_stopping_rounds` without `eval_set` raises `ValueError` → numeric weight,
   `.fit(eval_set=…, callbacks=[lightgbm.early_stopping(100)])`, `subsample_freq=1` (else
   `subsample` is inert); `predict(pred_contrib=True)` returns a trailing bias column to drop.
9. **`coverage_history.csv` covers 2018–2022 only** (01, 02). Filter on `max_pct_covered`
   (TX 2019 `min` = 0.59 would wrongly drop the year); the rule cannot fire for 2023–2025 and
   must say so in `metrics.json.notes`. `total_customers` exists only in the 2024 EAGLE-I file.
10. **NWS renamed "Excessive Heat Warning" → "Extreme Heat Warning"** (02); Storm Events uses
    `Hurricane (Typhoon)`, `Winter Weather`, `Heat` as exact `EVENT_TYPE` strings.
11. **HRRR accumulations live in `f01`, not `f00`** (01, 02): a `f00`-only loader yields all-zero
    `ice_mm`/`precip_mm`. Only the 00/06/12/18Z cycles run to f48 (others stop at f18).
12. **ERCO demand at Uri 07Z was 65,255 MW, not < 50 GW** (01 AC 6 rewritten to 18Z); the
    EIA-930 `Imputed` column is NaN for all ERCO Uri hours.
13. **API shapes that were wrong**: pgmpy 1.1.2 `DiscreteBayesianNetwork` (07);
    `from gridstatus.ercot_api.ercot_api import ErcotAPI` + `get_shadow_prices_sced` (08);
    Anthropic SDK stream yields `TextEvent`, not `text_delta` (05); deck.gl `_onMetrics`,
    `PathStyleExtension` in `@deck.gl/extensions`, `beforeId` `water_name` (06); DuckDB
    `read_only=True` still executes `COPY … TO` so the `sql` denylist is load-bearing (05).
14. **Regulatory numbers that were ours, not the source's** (08, 09, 04): FERC DLR ANOPR RM24-6
    proposes no $500k/yr or 3 m/s threshold; Drake 795 ACSR anchor is 907 A at 25 °C (not 900 A
    at 40 °C); LBNL Queued Up 2026 says 13 % (not ~20 %) reached COD; ADVANCE Act has no 55 %
    fee cut in statute (NRC rule ≈ 53 %); DOE-site EO is 14299, not 14301/14302.

## Open `[UNVERIFIED]` items (as tagged in the spec text today)

**00 overview** — which DoD installation actually loses supply in the cascade demo (pick from the
real run); AUC ≥ 0.75 on the Uri hold-out achievable; a published Texas Uri EAGLE-I subset exists
(moot: figshare is open).

**01 data ingest** — DuckDB size after the Texas filter (~35 MB); 2021-era NWS zone edition vs
`bp16ap26.dbx`; ISD "~200 TX stations" count; `whp2023.gdb` layer names; inner format of
`US_2023_HazardMaps.zip`; HIFLD archive size (76.8 MB) and whether the ArcGIS Hub page is a stub;
HIFLD substations location on DataLumos; split-county majority-supplier BA rule and uncaptured
SPP/MISO co-ops; `core_eia861__assn_balancing_authority` columns; ACTIVSg82k gating; NRI
shapefile companion URL; DataLumos project ids behind Cloudflare.

**02 outage model** — `y_out` positive rate 0.5–5 % (needs the built label table); per-county
≥ 5 % rate at the Uri peak (only the statewide 4,257,873 at 02-16 19Z is verified).

**03 cascade sim** — 2.5 persons per customer (Census gives 2.70 per household); fragility priors
g0/a/i0/b and gen derates 0.35/0.5/0.05; `rundcpp(recycle=…)` speed gain.

**04 siting engine** — Pantex within any DOE authorization pathway; unit-level retirement
statuses vs EIA-860M; STAND criteria; S2 4-mile population-center proxy; S5 2 km² reservoir
size; S9 ordnance/LNG 5-mile distance; S12 25 % wetlands footprint; Janus/Pele program details;
1,200 MW slot; synthetic case's ERCOT-only footprint.

**05 copilot** — none tagged (model ids and Opus 5 400-rules are documented-not-live; the spec
says so and requires a `/health` `models.retrieve` guard).

**06 frontend** — Protomaps hosted API terms; deck.gl `useControl` + `MapboxOverlay` React wiring
example.

**07 causal layer** — tree-canopy proxy (none in P0); `RESL_SCORE` column present in NRI;
`ExpectationMaximization` runtime on 60k rows (twice); spec 03 `FragilityParams` per-element
override (plan on emulation).

**08 line-upgrade screen** — kV-class conductor defaults (477 Hawk / 795 Drake / 2×954 Rail);
per-mile reconductoring cost placeholders and the "$1–8 M/mile" range; $20/MWh twin-proxy
shadow price; whether SPARK selections have been announced.

**09 Speed-to-Power backup** — ERCOT Large Load report is per-project (NPRR 1267 says
"aggregated"); public Batch Zero project list; PJM load-forecast file; SPP HILLGA; Cleanview
free-tier export; EEI download; PUDL Form 714 S3 key; ERCOT status vocabulary; EPRI DCFlex
response-time tiers; LMP node mapping; SPARK notice PDF posted; ≥ 100 terminal ERCOT rows;
EIA-861 territory polygons; PPL exact congestion figures on the slide; SPARK award timing;
REWIRE Act bill status; ERCOT LL report PDF-vs-XLSX months.

## Top cross-spec risks

1. Nothing in 02 has run against a built label table, and nothing in 05 has hit the Anthropic
   API live; both acceptance suites rest on documented-not-exercised facts.
2. The transformer-overload path (847 `net.impedance` rows) and the `f01` HRRR rule are silent
   zeros if skipped — neither raises; both need the break-it probes the specs now list.
3. Fragility/derate priors (03), per-mile costs (08) and the ERCOT Large Load report granularity
   (09) are the unsourced numbers the demo's rankings depend on.

## How to re-verify

Open the ledger named in the table above; every row gives the claim's location in the spec, the
verdict, the primary source or the exact introspection call, and the old → new text for
corrections. Each ledger ends with a "skeptic's first read" naming the two or three commands to
rerun (e.g. `uv run python -c "import lightgbm; lightgbm.LGBMClassifier(scale_pos_weight='auto').fit([[0],[1]],[0,1])"`
must raise; `from pgmpy.models import BayesianNetwork; BayesianNetwork([('a','b')])` must raise;
`lightsim2grid.gridmodel.init_from_pandapower(net)` must raise on this case). Re-running a check
means editing the spec in place and appending a row to its ledger, not editing this summary.

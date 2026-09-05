# Graph Report - docs  (2026-09-05)

## Corpus Check
- Corpus is ~39,932 words - fits in a single context window. You may not need a graph.

## Summary
- 326 nodes · 598 edges · 17 communities (15 shown, 2 thin omitted)
- Extraction: 71% EXTRACTED · 28% INFERRED · 0% AMBIGUOUS · INFERRED: 170 edges (avg confidence: 0.93)
- Token cost: 478,829 input · 0 output

## Community Hubs (Navigation)
- Pitch Ideas & Shared Stack
- Siting & Line-Upgrade Scoring
- Copilot Tool Contract
- Scenarios & Outage Model
- Cascade, Siting & Causal Spine
- Causal Layer (pgmpy/DoWhy)
- Weather & Data Ingest Specs
- Frontend Map Layers & EAGLE-I
- Fragility & Effect Estimation
- Cascade Runtime & Load Scaling
- ACTIVSg2000 Twin Build
- Copilot Ask Loop & Verification
- Data-Center Grid Impact Score
- Ingest Build & Download Script
- Outage Model Evaluation
- Outage Labels
- Holdout Split

## God Nodes (most connected - your core abstractions)
1. `Idea 1: National Grid Digital Twin + Outage Prediction + Nuclear Siting` - 27 edges
2. `09 Backup: Data-Center Load Verification Spec` - 22 edges
3. `L4 Cascade Simulation (physics)` - 16 edges
4. `Data Ingest pipelines/ (spec 01)` - 16 edges
5. `run_cascade tool` - 14 edges
6. `L3 Outage Model (LightGBM on EAGLE-I)` - 14 edges
7. `L6 Copilot (FastAPI + Claude tool loop)` - 13 edges
8. `L5 Siting Engine` - 12 edges
9. `flux Hackathon Build Specs README` - 12 edges
10. `twin.cascade.run_cascade` - 12 edges

## Surprising Connections (you probably didn't know these)
- `Idea 1: National Grid Digital Twin + Outage Prediction + Nuclear Siting` --references--> `OR-SAGE / STAND siting criteria`  [INFERRED]
  pitch/hackathon-pitches-and-designs.md → specs/00-overview.md
- `Spec 08: Line-Upgrade Screen` --references--> `IEEE 738 ampacity equation`  [INFERRED]
  specs/README.md → pitch/hackathon-pitches-and-designs.md
- `Idea 3: Transmission Line Upgrade Prioritization` --references--> `top_lines tool`  [INFERRED]
  pitch/hackathon-pitches-and-designs.md → specs/00-overview.md
- `Idea 1: National Grid Digital Twin + Outage Prediction + Nuclear Siting` --references--> `EAGLE-I (ORNL outage dataset)`  [INFERRED]
  pitch/hackathon-pitches-and-designs.md → specs/00-overview.md
- `Idea 1: National Grid Digital Twin + Outage Prediction + Nuclear Siting` --references--> `EIA-860 (via PUDL)`  [INFERRED]
  pitch/hackathon-pitches-and-designs.md → specs/00-overview.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Copilot six-tool contract (Idea 1)** — docs_specs_00_overview_copilot, docs_specs_00_overview_predict_outage, docs_specs_00_overview_run_cascade, docs_specs_00_overview_score_site, docs_specs_00_overview_top_lines, docs_specs_00_overview_sql, docs_specs_00_overview_cite, docs_specs_00_overview_model_never_computes [EXTRACTED 1.00]
- **Critical path 01→03→04→06 (siting screen)** — docs_specs_00_overview_data_ingest, docs_specs_00_overview_cascade_simulation, docs_specs_00_overview_siting_engine, docs_specs_00_overview_frontend, docs_specs_00_overview_counterfactual_replay [EXTRACTED 1.00]
- **Idea 2 data-center pipeline (ingest → resolve → reality → score → cost → tools)** — docs_specs_09_backup_idea2_datacenter_load_registry_ingest, docs_specs_09_backup_idea2_datacenter_load_entity_resolution, docs_specs_09_backup_idea2_datacenter_load_reality_model, docs_specs_09_backup_idea2_datacenter_load_grid_impact_score, docs_specs_09_backup_idea2_datacenter_load_cost_model, docs_specs_09_backup_idea2_datacenter_load_phantom_ratio, docs_specs_09_backup_idea2_datacenter_load_duplicates, docs_specs_09_backup_idea2_datacenter_load_score_dc_site, docs_specs_09_backup_idea2_datacenter_load_cost_exposure [EXTRACTED 1.00]
- **Shared DuckDB contract tables produced by ingest** — docs_specs_01_data_ingest_grid_duckdb, docs_specs_01_data_ingest_buses, docs_specs_01_data_ingest_lines, docs_specs_01_data_ingest_gens, docs_specs_01_data_ingest_loads, docs_specs_01_data_ingest_counties, docs_specs_01_data_ingest_critical_loads, docs_specs_01_data_ingest_eaglei_outages, docs_specs_01_data_ingest_weather_hourly, docs_specs_01_data_ingest_storm_events, docs_specs_01_data_ingest_hazard_static, docs_specs_01_data_ingest_ba_load_hourly, docs_specs_01_data_ingest_site_candidates, docs_specs_01_data_ingest_scenarios [EXTRACTED 1.00]
- **Cascade loop: scale -> sample weather -> DC PF -> trip -> attribute -> write** — docs_specs_03_cascade_sim_scale_loads, docs_specs_03_cascade_sim_weather_sample, docs_specs_03_cascade_sim_run_cascade, docs_specs_03_cascade_sim_run_scenario, docs_specs_03_cascade_sim_write_cascade_runs, docs_specs_03_cascade_sim_cascade_runs [EXTRACTED 1.00]
- **Counterfactual do-operator: seeded twin + site + run_scenario(net=) -> counterfactual_runs** — docs_specs_07_causal_layer_c3_counterfactual_replay, docs_specs_07_causal_layer_replay_with_site, docs_specs_03_cascade_sim_run_scenario, docs_specs_03_cascade_sim_determinism, docs_specs_01_data_ingest_site_candidates, docs_specs_07_causal_layer_counterfactual_runs [EXTRACTED 1.00]
- **Shared engine-tool contract (copilot fronts siting and line-upgrade tools)** — docs_specs_05_copilot_tool_use_loop, docs_specs_05_copilot_tool_schemas, docs_specs_04_siting_engine_score_site, docs_specs_08_line_upgrade_screen_top_lines, docs_specs_05_copilot_run_cascade, docs_specs_05_copilot_predict_outage [EXTRACTED 1.00]
- **Demo step 5: 'Why this site over the one near Houston?' flow** — docs_specs_06_frontend_ask_panel, docs_specs_06_frontend_map_linkage, docs_specs_05_copilot_post_ask, docs_specs_05_copilot_verify_py, docs_specs_04_siting_engine_score_site, docs_specs_05_copilot_cite, docs_specs_06_frontend_site_card [EXTRACTED 1.00]
- **Line-upgrade ranking pipeline (congestion + DLR + reconductor to MW per $M with FERC/SPARK flags)** — docs_specs_08_line_upgrade_screen_congestion_attribution, docs_specs_08_line_upgrade_screen_dlr, docs_specs_08_line_upgrade_screen_reconductoring, docs_specs_08_line_upgrade_screen_mw_per_musd, docs_specs_08_line_upgrade_screen_ferc_dlr_anopr, docs_specs_08_line_upgrade_screen_doe_spark, docs_specs_08_line_upgrade_screen_line_upgrade_scores [EXTRACTED 1.00]

## Communities (17 total, 2 thin omitted)

### Community 0 - "Pitch Ideas & Shared Stack"
Cohesion: 0.08
Nodes (43): Hackathon Pitches and Design Outlines, Dynamic Line Rating (DLR), Final Recommendation (Idea 1 headline, 3 embedded, 2 backup), gridstatus (ISO LMP data), Idea 2: Data Center Load Verification + Grid Impact Scoring, Idea 3: Transmission Line Upgrade Prioritization, IEEE 738 ampacity equation, PUDL (EIA/FERC ingest) (+35 more)

### Community 1 - "Siting & Line-Upgrade Scoring"
Cohesion: 0.07
Nodes (38): add_unit (pro-rata displacement), ADVANCE Act of 2024, Blackstart Reach (graph proxy), Siting break-it probes, Combined score (geometric mean), siting/grid_value.py, NRC proposed rule July 2026 (10 CFR 53.530), OR-SAGE (ORNL/TM-2012/403) (+30 more)

### Community 2 - "Copilot Tool Contract"
Cohesion: 0.10
Nodes (36): CEII (Critical Energy Infrastructure Information), Grid2Op operator agent (stretch), Idea 1: National Grid Digital Twin + Outage Prediction + Nuclear Siting, Palantir Chain Reaction (competitor), 10 CFR Part 100, cite tool (regulatory PDF retrieval), claude-sonnet-5 (Anthropic SDK), L6 Copilot (FastAPI + Claude tool loop) (+28 more)

### Community 3 - "Scenarios & Outage Model"
Cohesion: 0.11
Nodes (31): beryl_2024 scenario, forecast_72h scenario, helene_2024 scenario, L3 Outage Model (LightGBM on EAGLE-I), outage_predictions table, scenarios table, storm_events table, uri_2021 scenario (Winter Storm Uri) (+23 more)

### Community 4 - "Cascade, Siting & Causal Spine"
Cohesion: 0.10
Nodes (30): Grid Impact Score (0-100), Grid-Strength Value Score, cascade_runs table, L4 Cascade Simulation (physics), Counterfactual Replay (site online), critical_loads table, Critical Path 01→03→04→06, Definition of Demo-Ready (+22 more)

### Community 5 - "Causal Layer (pgmpy/DoWhy)"
Cohesion: 0.11
Nodes (23): Causal-AI Layer (simulator as SCM), Entity Resolution / Duplicate Detection, Phantom Ratio (announced vs queued vs forecast vs operating), Causal Layer (pgmpy DAG + DoWhy), DoWhy, pgmpy, causal.bn.fit_bn, pgmpy (+15 more)

### Community 6 - "Weather & Data Ingest Specs"
Cohesion: 0.10
Nodes (23): HRRR weather reanalysis, NOAA Storm Events, weather_hourly table, Spec 01 — Data Ingest, counties table, pipelines.db.ensure_schema, FEMA National Risk Index (S9), data/duck/grid.duckdb (+15 more)

### Community 7 - "Frontend Map Layers & EAGLE-I"
Cohesion: 0.12
Nodes (21): deck.gl, EAGLE-I (ORNL outage dataset), eaglei_outages table, Frontend (Vite + React + deck.gl + MapLibre), MapLibre, EAGLE-I county outages (S5), eaglei_outages table, pipelines.eaglei.load_eaglei (+13 more)

### Community 8 - "Fragility & Effect Estimation"
Cohesion: 0.12
Nodes (19): LightGBM, EIA-861 reliability SAIDI/SAIFI (S16), HeuristicOutageModel (fallback logistic), LightGBM, OutageModel dataclass, models.outage.train.train, Two heads: p_out classifier + tweedie frac regressor, Uri was generation shortfall, not only wires (+11 more)

### Community 9 - "Cascade Runtime & Load Scaling"
Cohesion: 0.13
Nodes (17): ba_load_hourly table, critical_loads table, NTAD Military Bases (S14), EIA-930 hourly BA demand (S4), Load scaling handoff to twin, Break-it mutation probes (trip_pct, zero failure probs), CascadeBudgetExceeded, CascadeResult dataclass (+9 more)

### Community 10 - "ACTIVSg2000 Twin Build"
Cohesion: 0.17
Nodes (16): ACTIVSg2000 synthetic Texas grid, pandapower (DC power flow), Texas First Scope, ACTIVSg2000 (S1), pipelines.ba_map.assign_ba, BA-county mapping (S17), buses table, EIA-860 via PUDL (S3) (+8 more)

### Community 11 - "Copilot Ask Loop & Verification"
Cohesion: 0.27
Nodes (10): claude-opus-5 via Anthropic SDK, eval/questions.yaml + run_eval.py, Never-compute principle, POST /ask (SSE), Prompt caching strategy, SSE event contract, System prompt (frozen, cache-controlled), Tool-use loop (agent/loop.py) (+2 more)

### Community 12 - "Data-Center Grid Impact Score"
Cohesion: 0.32
Nodes (8): dc_headroom table, dc_site_scores table, Duke Nicholas Institute curtailment-headroom tables, Grid Impact Score (models/dc/impact.py), gridstatus (LMP congestion component), score_dc_site tool, ScoreParams TypedDict, suggest_fixes ('what would make this a 90')

### Community 13 - "Ingest Build & Download Script"
Cohesion: 0.50
Nodes (4): scripts/data/download.sh, pipelines.build.export_parquet, Idempotent per-source ingest, pipelines.build

### Community 14 - "Outage Model Evaluation"
Cohesion: 0.67
Nodes (3): models.outage.evaluate.evaluate, Lead with hit_rate_top20 and peak_statewide_err, outage_eval table

## Ambiguous Edges - Review These
- `causal.counterfactual.replay_with_hardening` → `FragilityParams (twin/params.yaml)`  [AMBIGUOUS]
  specs/07-causal-layer.md · relation: references

## Knowledge Gaps
- **57 isolated node(s):** `loads table`, `critical_loads table`, `storm_events table`, `Reconductoring (advanced conductors)`, `Grid2Op operator agent (stretch)` (+52 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 73 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `causal.counterfactual.replay_with_hardening` and `FragilityParams (twin/params.yaml)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `Idea 1: National Grid Digital Twin + Outage Prediction + Nuclear Siting` connect `Copilot Tool Contract` to `Pitch Ideas & Shared Stack`, `Cascade, Siting & Causal Spine`, `Causal Layer (pgmpy/DoWhy)`, `Weather & Data Ingest Specs`, `Frontend Map Layers & EAGLE-I`, `Fragility & Effect Estimation`, `ACTIVSg2000 Twin Build`?**
  _High betweenness centrality (0.174) - this node is a cross-community bridge._
- **Why does `score_site tool` connect `Copilot Tool Contract` to `Pitch Ideas & Shared Stack`, `Siting & Line-Upgrade Scoring`, `Cascade, Siting & Causal Spine`, `Cascade Runtime & Load Scaling`, `Data-Center Grid Impact Score`?**
  _High betweenness centrality (0.133) - this node is a cross-community bridge._
- **Why does `09 Backup: Data-Center Load Verification Spec` connect `Pitch Ideas & Shared Stack` to `Copilot Tool Contract`, `Cascade, Siting & Causal Spine`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Are the 19 inferred relationships involving `Idea 1: National Grid Digital Twin + Outage Prediction + Nuclear Siting` (e.g. with `10 CFR Part 100` and `ACTIVSg2000 synthetic Texas grid`) actually correct?**
  _`Idea 1: National Grid Digital Twin + Outage Prediction + Nuclear Siting` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `run_cascade tool` (e.g. with `Idea 1: National Grid Digital Twin + Outage Prediction + Nuclear Siting` and `twin.tools.run_cascade (copilot wrapper)`) actually correct?**
  _`run_cascade tool` has 7 INFERRED edges - model-reasoned connections that need verification._
- **What connects `loads table`, `critical_loads table`, `storm_events table` to the rest of the system?**
  _57 weakly-connected nodes found - possible documentation gaps or missing edges._
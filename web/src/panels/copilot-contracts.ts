/**
 * Frontend mirror of the result models in copilot/tools/schemas.py.
 *
 * Keep this file limited to the five panel-facing output models.  Panels must
 * import these types instead of declaring their own payload shape, so the
 * Python contract remains the one wire-format authority.
 */

export type ArtifactRef = Readonly<{
  artifact_id: string;
  artifact_version: string;
  source_kind: "fixture" | "observed" | "simulated" | "heuristic" | "retrieval";
  source_ref: string;
}>;

export type Unavailable = Readonly<{
  code: "artifact_unavailable" | "invalid_prerequisite" | "unsupported_request" | "insufficient_evidence";
  reason: string;
  retryable: boolean;
}>;

export type AvailableToolOutput = Readonly<{
  status: "available";
  provenance: readonly ArtifactRef[];
  unavailable: null;
}>;

export type UnavailableToolOutput = Readonly<{
  status: "unavailable";
  provenance: readonly ArtifactRef[];
  unavailable: Unavailable;
}>;

export type OutagePoint = Readonly<{
  ts: string;
  p_out: number;
  customers_at_risk: number;
}>;

export type PredictOutageData = AvailableToolOutput & Readonly<{
  county_fips: string;
  county_name: string;
  scenario_id: "uri_2021" | "beryl_2024" | "helene_2024" | "forecast_72h";
  horizon_h: number;
  peak_p_out: number;
  peak_ts: string;
  customers_at_risk: number;
  driver: string;
  series: readonly OutagePoint[];
}>;

export type PredictOutageResult = PredictOutageData | UnavailableToolOutput;

export type SiteScoreData = AvailableToolOutput & Readonly<{
  site_id: string;
  name: string;
  kind: string;
  county_fips: string;
  scenario_id: "uri_2021" | "beryl_2024" | "helene_2024" | "forecast_72h";
  unit_mw: 300 | 1000;
  safety_score: number;
  safety_flags: readonly string[];
  grid_value_score: number;
  lol_reduction_mwh: number;
  congestion_relief_pct: number;
  blackstart_reach_mw: number;
  critical_loads_protected: readonly string[];
  regulatory_path: string;
}>;

export type SiteScoreResult = SiteScoreData | UnavailableToolOutput;

export type LineSummary = Readonly<{
  line_id: string;
  from_bus: string;
  to_bus: string;
  kv: number;
  congestion_usd_yr: number;
  uplift_mw: number;
  cost_usd: number;
  mw_per_musd: number;
  ferc_screen_pass: boolean;
  spark_eligible: boolean;
}>;

export type LinesData = AvailableToolOutput & Readonly<{
  region: string;
  tech: "dlr" | "reconductor" | "any";
  lines: readonly LineSummary[];
}>;

export type LinesResult = LinesData | UnavailableToolOutput;

export type Intervention = Readonly<{
  intervention_id: string;
  kind: "site" | "line";
  run_id: string;
  lol_reduction_mwh: number;
  customer_hours_avoided: number;
  critical_loads_protected: readonly string[];
}>;

export type InterventionsData = AvailableToolOutput & Readonly<{
  scenario_id: "uri_2021" | "beryl_2024" | "helene_2024" | "forecast_72h";
  baseline_run_id: string;
  interventions: readonly Intervention[];
  assumptions: readonly string[];
}>;

export type InterventionsResult = InterventionsData | UnavailableToolOutput;

export type CriticalElement = Readonly<{
  element_id: string;
  kind: "line" | "bus" | "gen";
  lost_load_mw: number;
  critical_loads_lost: readonly string[];
  runs: number;
}>;

export type CriticalElementsData = AvailableToolOutput & Readonly<{
  region: string;
  n: number;
  scenario_ids: readonly ("uri_2021" | "beryl_2024" | "helene_2024" | "forecast_72h")[];
  elements: readonly CriticalElement[];
  partial: boolean;
}>;

export type CriticalElementsResult = CriticalElementsData | UnavailableToolOutput;

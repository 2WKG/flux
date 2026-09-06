// GENERATED FILE - DO NOT EDIT.
// Source: copilot/tools/schemas.py. Regenerate: uv run --extra dev python scripts/ci/export_tool_contracts.py

export interface ArtifactRef {
  artifact_id: string;
  artifact_version: string;
  source_kind: "fixture" | "observed" | "simulated" | "heuristic" | "retrieval";
  source_ref: string;
}

export interface CascadeData {
  counties_dark: string[];
  critical_loads_lost: CriticalLoadLoss[];
  hour: number;
  lost_load_mw: number;
  provenance?: ArtifactRef[];
  run_id: string;
  scenario_id: ScenarioId;
  status: ToolStatus;
  steps: number;
  tripped_element_ids: TrippedElement[];
  unavailable?: Unavailable | null;
}

export interface CausalCitation {
  locator: string;
  source_id: string;
}

export interface CausalData {
  answer_numbers: Record<string, number>;
  assumptions: string[];
  citations: CausalCitation[];
  diagnostics: CausalDiagnostic[];
  evidence_rows: Array<Record<string, JsonValue>>;
  interval?: number[] | null;
  method: string;
  provenance?: ArtifactRef[];
  question: CausalQuestion;
  sample: CausalSample;
  sources: CausalSource[];
  status: ToolStatus;
  unavailable?: Unavailable | null;
}

export interface CausalDiagnostic {
  evidence: string;
  name: string;
  status: "pass";
}

export interface CausalQueryInput {
  capacity_mw?: 300 | 1000 | null;
  county_fips?: string | null;
  kind: "attribution" | "effect" | "counterfactual";
  scenario_id?: ScenarioId;
  site_id?: string | null;
  treatment?: "hardening_saidi" | "firm_generation_100mw" | null;
}

export interface CausalQuestion {
  outcome: CausalVariable;
  target_population: CausalTargetPopulation;
  treatment: CausalVariable;
}

export interface CausalSample {
  n_control: number;
  n_total: number;
  n_treated: number;
  period: string;
  unit: string;
}

export interface CausalSource {
  coverage: string;
  locator: string;
  name: string;
  source_id: string;
  version: string;
}

export interface CausalTargetPopulation {
  description: string;
  geography: string;
  time_window: string;
}

export interface CausalVariable {
  definition: string;
  name: string;
  source_id: string;
  unit_or_category: string;
}

export interface CiteData {
  hits: RetrievalHit[];
  provenance?: ArtifactRef[];
  status: ToolStatus;
  unavailable?: Unavailable | null;
}

export interface CiteInput {
  k?: number;
  query: string;
}

export interface CompareInterventionsInput {
  intervention_ids: string[];
  scenario_id: ScenarioId;
}

export interface ContractModel {
}

export interface CriticalElement {
  critical_loads_lost: string[];
  element_id: string;
  kind: "line" | "bus" | "gen";
  lost_load_mw: number;
  runs: number;
}

export interface CriticalElementsData {
  elements: CriticalElement[];
  n: number;
  partial?: boolean;
  provenance?: ArtifactRef[];
  region: string;
  scenario_ids: ScenarioId[];
  status: ToolStatus;
  unavailable?: Unavailable | null;
}

export interface CriticalLoadLoss {
  hour_lost: number;
  id: string;
  kind: "dod" | "hospital" | "water";
  name: string;
}

export interface Intervention {
  critical_loads_protected: string[];
  customer_hours_avoided: number;
  intervention_id: string;
  kind: "site" | "line";
  lol_reduction_mwh: number;
  run_id: string;
}

export interface InterventionsData {
  assumptions: string[];
  baseline_run_id: string;
  interventions: Intervention[];
  provenance?: ArtifactRef[];
  scenario_id: ScenarioId;
  status: ToolStatus;
  unavailable?: Unavailable | null;
}

export type JsonValue = unknown;

export interface LineSummary {
  artifact_id: string;
  congestion_usd_yr: number;
  cost_usd: number;
  ferc_screen_pass: boolean;
  from_bus: string;
  intervention_type: "dlr" | "reconductor";
  kv: number;
  line_id: string;
  mw_per_musd: number;
  scenario_id: string;
  source_class: "observed" | "simulated" | "proxy";
  spark_eligible: boolean;
  status: "available";
  to_bus: string;
  uplift_mw: number;
}

export interface LinesData {
  artifact_id: string;
  lines: LineSummary[];
  provenance?: ArtifactRef[];
  region: string;
  scenario_id: string;
  status: ToolStatus;
  tech: "dlr" | "reconductor" | "any";
  unavailable?: Unavailable | null;
}

export interface OutagePoint {
  customers_at_risk: number;
  p_out: number;
  ts: string;
}

export interface PredictOutageData {
  county_fips: string;
  county_name: string;
  customers_at_risk: number;
  driver: string;
  horizon_h: number;
  peak_p_out: number;
  peak_ts: string;
  provenance?: ArtifactRef[];
  scenario_id: ScenarioId;
  series: OutagePoint[];
  status: ToolStatus;
  unavailable?: Unavailable | null;
}

export interface PredictOutageInput {
  county_fips: string;
  horizon_h?: number;
  scenario_id: ScenarioId;
}

export interface RetrievalHit {
  chunk_id: string;
  content_kind: "fixture" | "source";
  date: string | null;
  doc: string;
  locator: string;
  page: number;
  provenance: Record<string, string>;
  score: number;
  source: string;
  text: string;
  title: string;
  version: string;
}

export interface RunCascadeInput {
  element_ids: string[];
  hour: number;
  scenario_id: ScenarioId;
}

export type ScenarioId = "uri_2021" | "beryl_2024" | "helene_2024" | "forecast_72h";

export interface ScoreSiteInput {
  scenario_id: ScenarioId;
  site_id: string;
  unit_mw: 300 | 1000;
}

export interface SiteScoreData {
  blackstart_reach_mw: number;
  congestion_relief_pct: number;
  county_fips: string;
  critical_loads_protected: string[];
  grid_value_score: number;
  kind: string;
  lol_reduction_mwh: number;
  name: string;
  provenance?: ArtifactRef[];
  regulatory_path: string;
  safety_flags: string[];
  safety_score: number;
  scenario_id: ScenarioId;
  site_id: string;
  status: ToolStatus;
  unavailable?: Unavailable | null;
  unit_mw: 300 | 1000;
}

export interface SqlData {
  columns: string[];
  provenance?: ArtifactRef[];
  row_count: number;
  rows: JsonValue[][];
  status: ToolStatus;
  truncated: boolean;
  unavailable?: Unavailable | null;
}

export interface SqlInput {
  query?: string | null;
  template_id?: string | null;
}

export interface ToolOutput {
  provenance?: ArtifactRef[];
  status: ToolStatus;
  unavailable?: Unavailable | null;
}

export type ToolStatus = "available" | "unavailable";

export interface TopCriticalElementsInput {
  n?: number;
  region: string;
}

export interface TopLinesInput {
  n?: number;
  region: string;
  tech: "dlr" | "reconductor" | "any";
}

export interface TrippedElement {
  cause: "weather" | "overload" | "island" | "forced";
  element_id: string;
  kind: "line" | "trafo" | "gen" | "bus";
  stage: number;
}

export interface Unavailable {
  code: UnavailableCode;
  reason: string;
  retryable?: boolean;
}

export type UnavailableCode = "artifact_unavailable" | "invalid_prerequisite" | "unsupported_request" | "insufficient_evidence";

export interface UnavailableOutput {
  provenance?: ArtifactRef[];
  status: "unavailable";
  unavailable?: Unavailable | null;
}

export type ToolName = "predict_outage" | "run_cascade" | "score_site" | "top_lines" | "sql" | "cite" | "compare_interventions" | "top_critical_elements" | "causal_query";

export interface ToolContracts {
  predict_outage: { input: PredictOutageInput; output: PredictOutageData | UnavailableOutput };
  run_cascade: { input: RunCascadeInput; output: CascadeData | UnavailableOutput };
  score_site: { input: ScoreSiteInput; output: SiteScoreData | UnavailableOutput };
  top_lines: { input: TopLinesInput; output: LinesData | UnavailableOutput };
  sql: { input: SqlInput; output: SqlData | UnavailableOutput };
  cite: { input: CiteInput; output: CiteData | UnavailableOutput };
  compare_interventions: { input: CompareInterventionsInput; output: InterventionsData | UnavailableOutput };
  top_critical_elements: { input: TopCriticalElementsInput; output: CriticalElementsData | UnavailableOutput };
  causal_query: { input: CausalQueryInput; output: CausalData | UnavailableOutput };
}

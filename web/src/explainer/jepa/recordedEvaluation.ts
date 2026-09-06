/**
 * The one recorded EAGLE-I count-JEPA evaluation this section is allowed to quote.
 *
 * `recorded-evaluation.artifact.json` next to this file is a byte-identical copy
 * of the artifact produced by 2WKG-474 (`models/jepa`). Every number the section
 * shows is read out of that file at build time; nothing here restates a value by
 * hand, and nothing here is fetched at runtime.
 *
 * The artifact is *not* on `master`. It lives on the unmerged 2WKG-474 branch,
 * and no product code reads it. Treat the figures below as one recorded
 * experiment with a named split, not as a shipped capability.
 */
import artifact from "./recorded-evaluation.artifact.json";

/** Where the vendored copy came from, so a reader can re-derive it. */
export const ARTIFACT_PROVENANCE = {
  /** Path of the original inside the 2WKG-474 branch. */
  originPath: "data/artifacts/jepa/eaglei-2024-count-v1/jepa_count_forecast_artifact.json",
  originBranch: "joshuawangia/2wkg-474-jepa-train-and-evaluate-an-experimental-eagle-i-count",
  /** `git hash-object` of the copy; identical to the blob on that branch. */
  gitBlobSha1: "1d6edd4deb16d083ac30bf5a4837e4b7b8034b0a",
  /** SHA-256 of the copy's bytes. Asserted by `recordedEvaluation.test.mjs`. */
  contentSha256: "c27a30f8339d8fbe8cda082371c974c8e6a1c4361a31303ef6446e05fc0340e0",
} as const;

export interface CountyForecast {
  readonly county_fips: string;
  readonly county_name: string;
  readonly context_end_utc: string;
  readonly horizon_minutes: number;
  readonly actual_customers_out: readonly number[];
  readonly predicted_customers_out: readonly number[];
}

export interface RecordedEvaluation {
  readonly artifact_kind: string;
  readonly model_version: string;
  readonly status: string;
  readonly architecture: Readonly<Record<string, string>>;
  readonly config: Readonly<Record<string, number>>;
  readonly metrics: Readonly<Record<string, number>>;
  readonly limitations: readonly string[];
  readonly county_forecasts: readonly CountyForecast[];
  readonly forecast: CountyForecast;
  readonly regeneration: { readonly command: string; readonly generated_by_revision: string; readonly note: string };
  readonly scope: {
    readonly cadence_minutes: number;
    readonly context_steps: number;
    readonly target_steps: number;
    readonly requested_county_fips: readonly string[];
    readonly observed_county_fips: readonly string[];
    readonly unavailable_county_fips: readonly { readonly county_fips: string; readonly reason: string }[];
  };
  readonly source: { readonly path: string; readonly provider: string; readonly sha256: string; readonly year: number };
  readonly split: {
    readonly strategy: string;
    readonly train_windows: number;
    readonly holdout_windows: number;
    readonly train_counties: readonly string[];
    readonly holdout_counties: readonly string[];
    readonly county_window_counts: Readonly<Record<string, number>>;
    readonly window_stride_steps: number;
    readonly target_context_overlap_steps: number;
    readonly overlap_verification: string;
  };
  readonly weights: { readonly path: string; readonly sha256: string };
}

export const RECORDED_EVALUATION = artifact as unknown as RecordedEvaluation;

/** The section refuses to render a figure that is not in the artifact. */
export function metric(name: string): number {
  const value = RECORDED_EVALUATION.metrics[name];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Recorded evaluation has no finite metric "${name}"; the section must not invent one.`);
  }
  return value;
}

/** Fields `models/jepa` emits today but this recorded run predates. Never shown as a value. */
export const ABSENT_METRICS = [
  "best_constant_baseline_count_mae",
  "best_constant_baseline_count",
  "train_actual_count_std",
  "holdout_actual_count_std",
] as const;

export function absentMetrics(): readonly string[] {
  return ABSENT_METRICS.filter((name) => !(name in RECORDED_EVALUATION.metrics));
}

/** Minutes of history the context covers, from the recorded cadence and step count. */
export function contextMinutes(): number {
  return RECORDED_EVALUATION.scope.cadence_minutes * RECORDED_EVALUATION.scope.context_steps;
}

export function formatCount(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

/** Ratio of the model's holdout MAE to the persistence baseline's, on the same split. */
export function holdoutVersusPersistence(): number {
  return metric("holdout_count_mae") / metric("persistence_baseline_count_mae");
}

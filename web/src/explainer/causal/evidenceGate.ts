/**
 * A browser-side mirror of the causal layer's evidence gate.
 *
 * The authority is Python: `causal/validation.py` decides whether a persisted
 * artifact may support an effect claim, and `copilot/tools/causal_query.py`
 * turns every failure into the canonical unavailable envelope instead of a
 * plausible number. This module restates those rules so the explainer page can
 * show the gate operating rather than describe it, and so a test pins the
 * mirror against the codes the Python module declares.
 *
 * It reads nothing. There is no fetch, no artifact file, and no registered
 * binding shipped with this page — `EXPLAINER_REGISTRY` is empty on purpose,
 * which is why the page's honest causal-effect result is `artifact_unavailable`.
 */

/** Insufficiency codes declared by `causal/validation.py`. */
export const FIXTURE_NOT_ESTIMABLE = "FIXTURE_NOT_ESTIMABLE";
export const MISSING_IDENTIFICATION = "MISSING_IDENTIFICATION";
export const MISSING_TREATMENT_DEFINITION = "MISSING_TREATMENT_DEFINITION";
export const MISSING_OUTCOME_DEFINITION = "MISSING_OUTCOME_DEFINITION";
export const MISSING_DATA_COVERAGE = "MISSING_DATA_COVERAGE";
export const MISSING_DIAGNOSTICS = "MISSING_DIAGNOSTICS";
export const UNRESOLVED_CITATION = "UNRESOLVED_CITATION";

export const INSUFFICIENCY_CODES = [
  FIXTURE_NOT_ESTIMABLE,
  MISSING_IDENTIFICATION,
  MISSING_TREATMENT_DEFINITION,
  MISSING_OUTCOME_DEFINITION,
  MISSING_DATA_COVERAGE,
  MISSING_DIAGNOSTICS,
  UNRESOLVED_CITATION,
] as const;

export type InsufficiencyCode = (typeof INSUFFICIENCY_CODES)[number];

/** `causal/validation.py::SUPPORTED_ESTIMATION_METHODS`. */
export const SUPPORTED_ESTIMATION_METHODS = ["backdoor.econml.dml.LinearDML", "twfe_only"] as const;

/** `copilot/tools/causal_query.py::UNVERIFIED_TAG`. */
export const UNVERIFIED_TAG = "[UNVERIFIED";

export type UnavailableCode = "artifact_unavailable" | "insufficient_evidence" | "unsupported_request";

export interface PrerequisiteDiagnostic {
  readonly code: InsufficiencyCode;
  readonly criterion: string;
  readonly message: string;
}

export interface ValidationResult {
  readonly estimable: boolean;
  readonly diagnostics: readonly PrerequisiteDiagnostic[];
}

export interface CausalUnavailable {
  readonly status: "unavailable";
  readonly unavailable: { readonly code: UnavailableCode; readonly message: string };
}

export interface CausalAvailable {
  readonly status: "available";
  readonly answerNumbers: { readonly effect: number };
  readonly method: string;
  readonly estimand: string;
  readonly interval: readonly [number, number];
  readonly assumptions: readonly string[];
}

export type CausalResponse = CausalUnavailable | CausalAvailable;

export interface CausalQueryRequest {
  readonly kind: "attribution" | "effect" | "counterfactual";
  readonly countyFips?: string | null;
  readonly scenarioId?: string;
  readonly siteId?: string | null;
  readonly treatment?: string | null;
}

/** A deployment-registered binding from one exact request to one artifact. */
export interface RegisteredArtifact {
  readonly request: CausalQueryRequest;
  readonly artifact: unknown;
}

/**
 * The bindings this page ships: none.
 *
 * The explainer bundle is offline and static, so the only artifact it could
 * embed would be an interface fixture, and `causal/validation.py` refuses those
 * with `FIXTURE_NOT_ESTIMABLE`. Leaving the registry empty is the honest state,
 * not a placeholder.
 */
export const EXPLAINER_REGISTRY: readonly RegisteredArtifact[] = [];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function nonEmpty(value: unknown): boolean {
  return typeof value === "string" && value.trim().length > 0;
}

function labeledVariable(variable: Record<string, unknown>): boolean {
  return ["name", "definition", "unit_or_category", "source_id"].every((field) =>
    nonEmpty(variable[field]),
  );
}

function declaredSourceIds(artifact: Record<string, unknown>): Set<string> {
  const sources = artifact.sources;
  if (!Array.isArray(sources)) return new Set();
  return new Set(
    sources
      .map((source) => record(source).source_id)
      .filter((id): id is string => typeof id === "string"),
  );
}

function hasCoveredData(artifact: Record<string, unknown>): boolean {
  const question = record(artifact.question);
  const treatment = record(question.treatment);
  const outcome = record(question.outcome);
  const population = record(question.target_population);
  const sample = record(artifact.sample);
  const sources = Array.isArray(artifact.sources) ? artifact.sources.map(record) : [];
  const sourceIds = declaredSourceIds(artifact);
  const counts = ["n_total", "n_treated", "n_control"] as const;
  const countsValid = counts.every(
    (field) => Number.isInteger(sample[field]) && (sample[field] as number) >= 0,
  );
  const nTotal = countsValid ? (sample.n_total as number) : 0;
  const sampleComplete =
    nonEmpty(sample.unit) &&
    nonEmpty(sample.period) &&
    countsValid &&
    nTotal > 0 &&
    (sample.n_treated as number) + (sample.n_control as number) <= nTotal;
  const sourceComplete =
    sourceIds.size > 0 &&
    sources.every((source) =>
      ["source_id", "name", "version", "locator", "coverage"].every((field) =>
        nonEmpty(source[field]),
      ),
    );
  const covariates = artifact.covariates;
  return (
    ["description", "geography", "time_window"].every((field) => nonEmpty(population[field])) &&
    sampleComplete &&
    sourceComplete &&
    labeledVariable(treatment) &&
    labeledVariable(outcome) &&
    sourceIds.has(treatment.source_id as string) &&
    sourceIds.has(outcome.source_id as string) &&
    Array.isArray(covariates) &&
    covariates.every(
      (item) => labeledVariable(record(item)) && sourceIds.has(record(item).source_id as string),
    )
  );
}

function citationsResolve(artifact: Record<string, unknown>): boolean {
  const sourceIds = declaredSourceIds(artifact);
  const citations = artifact.citations;
  if (!Array.isArray(citations) || citations.length === 0) return false;
  const evidence = record(artifact.estimate).evidence ?? [];
  if (!Array.isArray(evidence)) return false;
  return [...citations, ...evidence].every(
    (item) => nonEmpty(record(item).locator) && sourceIds.has(record(item).source_id as string),
  );
}

function diagnosticsPass(artifact: Record<string, unknown>): boolean {
  const diagnostics = artifact.diagnostics;
  return (
    Array.isArray(diagnostics) &&
    diagnostics.length > 0 &&
    diagnostics.every(
      (item) =>
        record(item).status === "pass" &&
        nonEmpty(record(item).name) &&
        nonEmpty(record(item).evidence),
    )
  );
}

function explicitMethod(estimate: Record<string, unknown>): boolean {
  return (
    SUPPORTED_ESTIMATION_METHODS.includes(estimate.method as (typeof SUPPORTED_ESTIMATION_METHODS)[number]) &&
    nonEmpty(estimate.estimand)
  );
}

/** True when any string leaf anywhere in the document is tagged `[UNVERIFIED`. */
export function carriesUnverifiedClaim(document: unknown): boolean {
  const stack: unknown[] = [document];
  while (stack.length) {
    const value = stack.pop();
    if (typeof value === "string") {
      if (value.includes(UNVERIFIED_TAG)) return true;
    } else if (Array.isArray(value)) {
      stack.push(...value);
    } else if (isRecord(value)) {
      stack.push(...Object.keys(value), ...Object.values(value));
    }
  }
  return false;
}

/** Mirror of `causal/validation.py::validate_artifact`. Reports criteria, never data. */
export function validateArtifact(artifact: unknown): ValidationResult {
  const document = record(artifact);
  if (document.classification === "interface_fixture") {
    return {
      estimable: false,
      diagnostics: [
        {
          code: FIXTURE_NOT_ESTIMABLE,
          criterion: "classification",
          message: "Interface fixtures cannot support causal effect claims.",
        },
      ],
    };
  }
  const diagnostics: PrerequisiteDiagnostic[] = [];
  const question = record(document.question);
  if (!labeledVariable(record(question.treatment))) {
    diagnostics.push({
      code: MISSING_TREATMENT_DEFINITION,
      criterion: "treatment",
      message: "A labeled treatment definition and provenance are required.",
    });
  }
  if (!labeledVariable(record(question.outcome))) {
    diagnostics.push({
      code: MISSING_OUTCOME_DEFINITION,
      criterion: "outcome",
      message: "A labeled outcome definition and provenance are required.",
    });
  }
  const assumptions = document.assumptions;
  if (!Array.isArray(assumptions) || !assumptions.some((item) => nonEmpty(item))) {
    diagnostics.push({
      code: MISSING_IDENTIFICATION,
      criterion: "identification",
      message: "An explicit identification strategy and assumptions are required.",
    });
  }
  if (!hasCoveredData(document)) {
    diagnostics.push({
      code: MISSING_DATA_COVERAGE,
      criterion: "data_coverage",
      message: "Population, sample, covariate, and source coverage are required.",
    });
  }
  if (!diagnosticsPass(document)) {
    diagnostics.push({
      code: MISSING_DIAGNOSTICS,
      criterion: "diagnostics",
      message: "Required diagnostics must be recorded with passing status.",
    });
  }
  if (!citationsResolve(document)) {
    diagnostics.push({
      code: UNRESOLVED_CITATION,
      criterion: "citations",
      message: "Every citation and estimate evidence entry must name a declared source.",
    });
  }
  const estimate = record(document.estimate);
  if (diagnostics.length === 0 && !explicitMethod(estimate)) {
    diagnostics.push({
      code: MISSING_IDENTIFICATION,
      criterion: "method",
      message: "An estimable artifact requires an explicit estimation method.",
    });
  }
  if (diagnostics.length === 0 && record(document.availability).status !== "available") {
    diagnostics.push({
      code: MISSING_IDENTIFICATION,
      criterion: "availability",
      message: "Only an available artifact may expose a causal effect claim.",
    });
  }
  return { estimable: diagnostics.length === 0, diagnostics };
}

function requestKey(request: CausalQueryRequest): string {
  return JSON.stringify({
    kind: request.kind,
    county_fips: request.countyFips ?? null,
    scenario_id: request.scenarioId ?? "uri_2021",
    site_id: request.siteId ?? null,
    treatment: request.treatment ?? null,
  });
}

function unavailable(code: UnavailableCode, message: string): CausalUnavailable {
  return { status: "unavailable", unavailable: { code, message } };
}

/**
 * Mirror of `copilot/tools/causal_query.py::causal_query`: read one registered
 * artifact or return the canonical unavailable envelope. It never estimates,
 * never guesses a binding, and never carries an effect number on a failure.
 */
export function causalQuery(
  request: CausalQueryRequest,
  registry: readonly RegisteredArtifact[] = EXPLAINER_REGISTRY,
): CausalResponse {
  const key = requestKey(request);
  const registration = registry.find((entry) => requestKey(entry.request) === key);
  if (!registration) {
    return unavailable("artifact_unavailable", "Causal artifact bindings are unavailable.");
  }
  const validation = validateArtifact(registration.artifact);
  if (!validation.estimable) {
    const codes = validation.diagnostics.map((diagnostic) => diagnostic.code).join(", ");
    return unavailable(
      "insufficient_evidence",
      `Causal evidence prerequisites are not met: ${codes}.`,
    );
  }
  if (carriesUnverifiedClaim(registration.artifact)) {
    return unavailable(
      "insufficient_evidence",
      "Causal evidence artifact carries unresolved [UNVERIFIED] claims.",
    );
  }
  const document = record(registration.artifact);
  const estimate = record(document.estimate);
  const interval = record(estimate.interval);
  const effect = estimate.effect;
  const lower = interval.lower;
  const upper = interval.upper;
  if (typeof effect !== "number" || typeof lower !== "number" || typeof upper !== "number") {
    return unavailable(
      "insufficient_evidence",
      "Causal evidence artifact does not fit the response contract (TypeError).",
    );
  }
  const caveats = Array.isArray(estimate.caveats) ? estimate.caveats.filter(nonEmpty) : [];
  return {
    status: "available",
    answerNumbers: { effect },
    method: estimate.method as string,
    estimand: estimate.estimand as string,
    interval: [lower, upper],
    assumptions: [
      ...(Array.isArray(document.assumptions) ? document.assumptions.filter(nonEmpty) : []),
      ...caveats,
    ] as readonly string[],
  };
}

/** The effect request the section shows being refused, stated once. */
export const SECTION_EFFECT_REQUEST: CausalQueryRequest = {
  kind: "effect",
  treatment: "hardening_saidi",
  scenarioId: "uri_2021",
};

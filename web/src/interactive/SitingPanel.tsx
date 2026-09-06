import { createElement, type ReactElement } from "react";

/**
 * Presentation contract for the future `POST /siting/search` adapter.
 *
 * This component deliberately receives already selected, ordered candidates.
 * It does not receive coordinates and it never scores, geocodes, sorts, or
 * otherwise turns browser data into a siting conclusion.
 */
export type SitingSearchEvidence = {
  label: string;
  value: string;
  provenanceRef: string;
};

export type SitingSearchCandidate = {
  id: string;
  label: string;
  evidence: readonly SitingSearchEvidence[];
  limitations: readonly string[];
  provenance: {
    artifactId: string;
    artifactVersion: string;
    sourceKind: string;
  };
};

export type SitingSearchResponse = {
  schemaVersion: "siting-search/v1";
  resultKind: "synthetic_counterfactual";
  scenario: {
    id: string;
    label: string;
    assumptions: readonly string[];
  };
  candidates: readonly SitingSearchCandidate[];
  limitations: readonly string[];
};

export type SitingPanelInput =
  | { state: "ready"; response: unknown }
  | { state: "unavailable"; message?: string }
  | { state: "malformed"; message?: string };

export type SitingPresentation =
  | { state: "synthetic"; response: SitingSearchResponse }
  | { state: "unavailable"; message: string }
  | { state: "malformed"; message: string };

const stringArray = (value: unknown): value is readonly string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string" && item.trim().length > 0);

function isSitingSearchResponse(value: unknown): value is SitingSearchResponse {
  if (!value || typeof value !== "object") return false;
  const response = value as Record<string, unknown>;
  if (response.schemaVersion !== "siting-search/v1" || response.resultKind !== "synthetic_counterfactual") return false;
  if (!response.scenario || typeof response.scenario !== "object") return false;
  const scenario = response.scenario as Record<string, unknown>;
  if (typeof scenario.id !== "string" || typeof scenario.label !== "string" || !stringArray(scenario.assumptions)) return false;
  if (!stringArray(response.limitations) || !Array.isArray(response.candidates)) return false;

  return response.candidates.every((value) => {
    if (!value || typeof value !== "object") return false;
    const candidate = value as Record<string, unknown>;
    if (typeof candidate.id !== "string" || typeof candidate.label !== "string" || !stringArray(candidate.limitations)) return false;
    if (!candidate.provenance || typeof candidate.provenance !== "object" || !Array.isArray(candidate.evidence)) return false;
    const provenance = candidate.provenance as Record<string, unknown>;
    if (!["artifactId", "artifactVersion", "sourceKind"].every((key) => typeof provenance[key] === "string" && provenance[key])) return false;
    return candidate.evidence.length > 0 && candidate.evidence.every((value) => {
      if (!value || typeof value !== "object") return false;
      const evidence = value as Record<string, unknown>;
      return ["label", "value", "provenanceRef"].every((key) => typeof evidence[key] === "string" && evidence[key]);
    });
  });
}

/**
 * Turns a transport/adaptor input into a closed presentational state. Exported
 * so the fixture test can verify the same branch the JSX uses.
 */
export function buildSitingPresentation(input: SitingPanelInput): SitingPresentation {
  if (input.state === "unavailable") {
    return { state: "unavailable", message: input.message ?? "The siting search service is not available in this build." };
  }
  if (input.state === "malformed") {
    return { state: "malformed", message: input.message ?? "The siting search response could not be used." };
  }
  if (!isSitingSearchResponse(input.response)) {
    return { state: "malformed", message: "The siting search response did not match the expected contract." };
  }
  return { state: "synthetic", response: input.response };
}

function Failure({ state, message }: Exclude<SitingPresentation, { state: "synthetic" }>): ReactElement {
  return createElement("section", { "aria-label": "Siting search state", "data-siting-state": state, role: "alert" },
    createElement("h2", null, state === "unavailable" ? "Siting search unavailable" : "Siting response could not be used"),
    createElement("p", null, message),
    createElement("p", null, "No candidate recommendation is displayed. A physical siting recommendation requires a live, validated service response."),
  );
}

/** A bounded presentation surface; fetches and service integration belong to the future adapter. */
export function SitingPanel({ input }: { input: SitingPanelInput }): ReactElement {
  const presentation = buildSitingPresentation(input);
  if (presentation.state !== "synthetic") return createElement(Failure, presentation);

  const { response } = presentation;
  return createElement("section", { "aria-label": "Synthetic siting screening", "data-siting-state": "synthetic" },
    createElement("header", null,
      createElement("p", null, "Synthetic counterfactual screening output"),
      createElement("h2", null, "Candidate comparison"),
      createElement("p", null, "These are scenario-bound model outputs, not physical siting recommendations, licensing findings, or construction decisions."),
    ),
    createElement("section", { "aria-label": "Scenario and assumptions" },
      createElement("h3", null, `Scenario: ${response.scenario.label}`),
      createElement("p", null, `Scenario ID: ${response.scenario.id}`),
      createElement("h4", null, "Assumptions"),
      createElement("ul", null, response.scenario.assumptions.map((assumption) => createElement("li", { key: assumption }, assumption))),
    ),
    response.candidates.length === 0
      ? createElement("p", { role: "status" }, "The synthetic screening response returned no candidates.")
      : createElement("ol", { "aria-label": "Synthetic candidate outputs" }, response.candidates.map((candidate) =>
        createElement("li", { key: candidate.id },
          createElement("article", { "data-siting-candidate": candidate.id },
            createElement("h3", null, candidate.label),
            createElement("h4", null, "Returned evidence"),
            createElement("ul", null, candidate.evidence.map((evidence) => createElement("li", { key: `${evidence.label}:${evidence.provenanceRef}` }, `${evidence.label}: ${evidence.value} (${evidence.provenanceRef})`))),
            createElement("h4", null, "Limitations"),
            createElement("ul", null, candidate.limitations.map((limitation) => createElement("li", { key: limitation }, limitation))),
            createElement("p", null, `Provenance: ${candidate.provenance.sourceKind}; artifact ${candidate.provenance.artifactId} (${candidate.provenance.artifactVersion}).`),
          ),
        ),
      )),
    createElement("section", { "aria-label": "Screening limitations" },
      createElement("h3", null, "Screening limitations"),
      createElement("ul", null, response.limitations.map((limitation) => createElement("li", { key: limitation }, limitation))),
    ),
  );
}

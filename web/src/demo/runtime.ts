import type {
  CascadePlayback,
  ControlRoomProps,
  ControlRoomRegion,
  DemoAvailability,
  ProvenanceNote,
  SuggestedPrompt,
  WeatherFrame,
} from "./ControlRoom";
import type { HistoricalCountForecast } from "./HistoricalForecast";
import type { ComponentFailureAction, TexasModelScene } from "./TexasModelStage";

export interface HistoricalModelInput {
  readonly availability: DemoAvailability;
  readonly label: string;
  readonly provenance: NonNullable<ControlRoomProps["scenarios"][number]["model"]>["provenance"];
  readonly limitations?: readonly string[];
}

export interface PrimaryDemoRuntimeInput {
  readonly regions: readonly ControlRoomRegion[];
  readonly selectedRegionId: ControlRoomProps["selectedRegionId"];
  readonly onRegionChange: NonNullable<ControlRoomProps["onRegionChange"]>;
  /** Weather frames must come from a supplied weather artifact; omitted means unavailable. */
  readonly weather?: readonly WeatherFrame[];
  /** Experimental historical model metadata is displayed only as its supplied status. */
  readonly historicalModel?: HistoricalModelInput;
  /** A qualified persisted cascade readback, when the browser bridge actually supplies one. */
  readonly cascade?: CascadePlayback;
  readonly suggestedPrompts: readonly SuggestedPrompt[];
  readonly onPromptSelect?: ControlRoomProps["onPromptSelect"];
}

/** Makes no request and synthesizes no weather, model measurement, or cascade event. */
export function createPrimaryDemoRuntime(input: PrimaryDemoRuntimeInput): ControlRoomProps {
  return {
    regions: input.regions,
    selectedRegionId: input.selectedRegionId,
    onRegionChange: input.onRegionChange,
    scenarios: [{
      id: "historical-context",
      label: "Historical scenario context",
      description: input.weather?.length
        ? "Weather frames are supplied by the selected scenario artifact."
        : "No browser weather timeline is available for this selected context.",
      availability: input.weather?.length ? "available" : "unavailable",
      weather: input.weather ?? [],
      model: input.historicalModel,
      limitations: input.weather?.length ? undefined : ["Weather symbols are withheld until a weather artifact is supplied."],
    }],
    cascade: input.cascade ?? {
      availability: "unavailable",
      title: "Cascade playback",
      unavailableMessage: "No qualified persisted cascade event is exposed to this browser selection.",
      events: [],
      limitations: ["A modeled cascade is shown only after persisted readback supplies its events and provenance."],
    },
    suggestedPrompts: input.suggestedPrompts,
    onPromptSelect: input.onPromptSelect,
  };
}

/** Maps the persisted `/cascade` readback only when its own qualifier is true. */
export function cascadePlaybackFromPayload(payload: {
  readonly run_id?: string;
  readonly playback_qualified?: boolean;
  readonly topology?: string;
  readonly provenance?: readonly { readonly source_name?: string; readonly source_ref?: string }[];
  readonly limitations?: readonly string[];
  readonly hours?: readonly {
    readonly hour?: number;
    readonly lost_load_mw?: number;
    readonly counties_dark?: readonly string[];
    readonly tripped_element_ids?: readonly { readonly element_id?: string; readonly kind?: string; readonly stage?: number; readonly cause?: string; readonly loading_percent?: number }[];
  }[];
}): CascadePlayback {
  const hour = payload.hours?.[0];
  const qualified = payload.playback_qualified === true && hour !== undefined;
  const events = qualified ? (hour.tripped_element_ids ?? []).flatMap((event, index) => event.element_id ? [{
    id: `${event.stage ?? 0}-${index}-${event.element_id}`,
    stageLabel: `Stage ${event.stage ?? 0} · ${event.kind ?? "element"}`,
    summary: `${event.element_id} ${event.cause ?? "event"}${event.loading_percent === undefined ? "" : ` at ${event.loading_percent}% loading`}.`,
    availability: "available" as const,
  }] : []) : [];
  return {
    availability: qualified && events.length > 0 ? "available" : "unavailable",
    title: "Synthetic Texas cascade playback",
    unavailableMessage: qualified ? "The qualified run contains no displayable event IDs." : "The cascade readback is not qualified for playback.",
    events,
    provenance: payload.provenance?.flatMap((item) => item.source_name || item.source_ref ? [{ label: item.source_name ?? "", detail: item.source_ref }] : []),
    limitations: [...(payload.limitations ?? []), ...(payload.topology ? [payload.topology] : [])],
  };
}

/** Maps the actual `/demo/forecast` nested `data.forecast` record without inference. */
export function historicalForecastFromPayload(payload: {
  readonly status: string;
  readonly reason?: string;
  readonly limitations?: readonly string[];
  readonly provenance?: readonly ProvenanceNote[];
  readonly data?: {
    readonly status?: string;
    readonly model_version?: string;
    readonly forecast?: {
      readonly actual_customers_out?: readonly number[];
      readonly predicted_customers_out?: readonly number[];
      readonly context_end_utc?: string;
      readonly county_fips?: string;
      readonly county_name?: string;
      readonly horizon_minutes?: number;
    };
    readonly scope?: { readonly observed_county_fips?: readonly string[] };
    readonly limitations?: readonly string[];
  };
}): HistoricalCountForecast {
  const forecast = payload.data?.forecast;
  const available = payload.status === "available" && forecast !== undefined
    && (payload.data?.scope?.observed_county_fips?.includes(forecast.county_fips ?? "") ?? false);
  return {
    availability: available ? "available" : "unavailable",
    modelVersion: payload.data?.model_version,
    countyFips: forecast?.county_fips,
    countyName: forecast?.county_name,
    contextEndUtc: forecast?.context_end_utc,
    horizonMinutes: forecast?.horizon_minutes,
    actualCustomersOut: forecast?.actual_customers_out,
    predictedCustomersOut: forecast?.predicted_customers_out,
    provenance: payload.provenance,
    limitations: [...(payload.limitations ?? []), ...(payload.data?.limitations ?? [])],
    reason: payload.reason,
  };
}

export interface ModelGeometryElement {
  readonly element_id?: string;
  readonly resolved?: boolean;
  readonly role?: string;
  readonly geometry?: { readonly type?: string; readonly coordinates?: unknown };
  readonly coordinates?: unknown;
}

export type ModelPayload = {
  readonly status: "available" | "partial" | "unavailable";
  readonly reason?: string;
  readonly data?: {
    readonly topology?: { readonly label?: string; readonly synthetic?: boolean; readonly solver?: string };
    readonly elements?: readonly ModelGeometryElement[];
    readonly capabilities?: { readonly selected_component_failure?: boolean };
  };
};

/** Converts only server-resolved canonical IDs into a Texas model scene. */
export function texasModelSceneFromPayload(payload: ModelPayload, action?: Omit<ComponentFailureAction, "availability">): TexasModelScene {
  const elements = payload.data?.elements ?? [];
  const resolved = elements.flatMap((element) => element.resolved && element.element_id ? [element.element_id] : []);
  const unresolved = elements.flatMap((element) => !element.resolved && element.element_id ? [element.element_id] : []);
  const available = payload.status === "available" && resolved.length > 0 ? "available" : payload.status === "partial" && resolved.length > 0 ? "partial" : "unavailable";
  const canRequestFailure = payload.data?.capabilities?.selected_component_failure === true;
  return {
    availability: available,
    topologyLabel: payload.data?.topology?.label ?? "synthetic model unavailable",
    synthetic: payload.data?.topology?.synthetic === true,
    solver: payload.data?.topology?.solver,
    elementIds: resolved,
    unresolvedElementIds: unresolved,
    action: action ? { ...action, availability: canRequestFailure ? "available" : "unavailable" } : undefined,
    limitations: payload.status === "unavailable" ? [payload.reason ?? "The model endpoint returned unavailable."] : undefined,
  };
}

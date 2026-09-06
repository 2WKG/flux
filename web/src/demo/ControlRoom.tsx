import { useMemo, useState } from "react";

import "./ControlRoom.css";

/** The control room only displays a status asserted by its parent data adapter. */
export type DemoAvailability = "available" | "partial" | "unavailable";
export type RegionId = "texas" | "minnesota";
export type WeatherSymbol = "clear" | "cloudy" | "rain" | "snow" | "wind" | "storm" | "heat" | "unknown";

export interface ProvenanceNote {
  readonly label: string;
  readonly detail?: string;
}

export interface RegionTopology {
  /** Parent-provided display label, for example `synthetic (ACTIVSg2000)`. */
  readonly label: string;
  readonly mode: "synthetic" | "source_backed" | "aggregate" | "unavailable";
  readonly availability: DemoAvailability;
  /** Required before Minnesota can be presented as topology-backed. */
  readonly accepted?: boolean;
  readonly provenance?: readonly ProvenanceNote[];
  readonly limitations?: readonly string[];
}

export interface ControlRoomRegion {
  readonly id: RegionId;
  readonly label: string;
  readonly summary: string;
  readonly topology: RegionTopology;
}

export interface WeatherFrame {
  readonly id: string;
  readonly timeLabel: string;
  /** A parent-supplied condition. The component never derives a weather condition. */
  readonly condition: string;
  readonly symbol: WeatherSymbol;
  readonly detail?: string;
  readonly availability: DemoAvailability;
  readonly provenance?: readonly ProvenanceNote[];
  readonly limitations?: readonly string[];
}

export interface DemoScenario {
  readonly id: string;
  readonly label: string;
  readonly description: string;
  readonly availability: DemoAvailability;
  readonly weather: readonly WeatherFrame[];
  /** Only label a model JEPA when the input provenance explicitly supplies that name. */
  readonly model?: {
    readonly availability: DemoAvailability;
    readonly label: string;
    readonly provenance: readonly ProvenanceNote[];
    readonly limitations?: readonly string[];
  };
  readonly limitations?: readonly string[];
}

export interface CascadeEvent {
  readonly id: string;
  readonly elementId?: string;
  readonly stageLabel: string;
  readonly summary: string;
  readonly availability: DemoAvailability;
  readonly provenance?: readonly ProvenanceNote[];
}

export interface CascadePlayback {
  readonly availability: DemoAvailability;
  /** Opaque server run identity, when a readback or verified live tool supplied one. */
  readonly runId?: string;
  readonly title?: string;
  readonly unavailableMessage?: string;
  /** Playback becomes enabled only when this parent-provided list contains usable events. */
  readonly events: readonly CascadeEvent[];
  readonly provenance?: readonly ProvenanceNote[];
  readonly limitations?: readonly string[];
}

export interface SuggestedPrompt {
  readonly id: string;
  readonly prompt: string;
  readonly availability: DemoAvailability;
  /** A plain-English result supplied by the caller. Missing means no answer is shown. */
  readonly result?: {
    readonly summary: string;
    readonly evidence?: readonly ProvenanceNote[];
    readonly limitations?: readonly string[];
  };
}

export interface ControlRoomProps {
  readonly regions: readonly ControlRoomRegion[];
  readonly selectedRegionId: RegionId;
  readonly scenarios: readonly DemoScenario[];
  readonly selectedScenarioId?: string;
  readonly cascade?: CascadePlayback;
  readonly suggestedPrompts?: readonly SuggestedPrompt[];
  readonly onRegionChange?: (regionId: RegionId) => void;
  readonly onScenarioChange?: (scenarioId: string) => void;
  readonly onPromptSelect?: (prompt: SuggestedPrompt) => void;
  readonly className?: string;
}

const WEATHER_GLYPHS: Readonly<Record<WeatherSymbol, string>> = {
  clear: "☀",
  cloudy: "☁",
  rain: "☂",
  snow: "❄",
  wind: "≋",
  storm: "ϟ",
  heat: "♨",
  unknown: "?",
};

function statusCopy(availability: DemoAvailability): string {
  return availability === "available" ? "Available" : availability === "partial" ? "Partial" : "Unavailable";
}

function Evidence({ notes, limitations }: { notes?: readonly ProvenanceNote[]; limitations?: readonly string[] }) {
  const meaningfulNotes = notes?.flatMap((note) => {
    const label = typeof note.label === "string" ? note.label.trim() : "";
    const detail = typeof note.detail === "string" ? note.detail.trim() : "";
    return label || detail ? [{ label, ...(detail ? { detail } : {}) }] : [];
  }) ?? [];
  if (meaningfulNotes.length === 0 && (!limitations || limitations.length === 0)) return null;
  return <div className="control-room__evidence">
    {meaningfulNotes.length > 0 ? <p><strong>Source:</strong> {meaningfulNotes.map((note) => note.detail ? `${note.label} — ${note.detail}` : note.label).join(" · ")}</p> : null}
    {limitations && limitations.length > 0 ? <p><strong>Limit:</strong> {limitations.join(" ")}</p> : null}
  </div>;
}

/** A Minnesota topology surface is intentionally opt-in at the serial mount seam. */
export function topologyIsDisplayable(region: ControlRoomRegion): boolean {
  if (region.topology.availability !== "available") return false;
  if (region.id !== "minnesota") return region.topology.mode !== "unavailable";
  return Boolean(region.topology.accepted) && region.topology.mode === "source_backed";
}

/** The event list is the sole authority for whether a cascade playback can run. */
export function cascadeIsPlayable(cascade?: CascadePlayback): boolean {
  return Boolean(cascade && cascade.availability === "available" && cascade.events.some((event) => event.availability === "available"));
}

function modelDisplayLabel(model: NonNullable<DemoScenario["model"]>): string {
  const namesJepa = /jepa/i.test(model.label);
  const provenanceNamesJepa = model.provenance.some((note) => /jepa/i.test(`${note.label} ${note.detail ?? ""}`));
  return namesJepa && !provenanceNamesJepa ? "Prediction model" : model.label;
}

export function ControlRoom({
  regions,
  selectedRegionId,
  scenarios,
  selectedScenarioId,
  cascade,
  suggestedPrompts = [],
  onRegionChange,
  onScenarioChange,
  onPromptSelect,
  className = "",
}: ControlRoomProps) {
  const region = regions.find((item) => item.id === selectedRegionId) ?? regions[0];
  const scenario = scenarios.find((item) => item.id === selectedScenarioId) ?? scenarios[0];
  const [selectedWeatherId, setSelectedWeatherId] = useState<string | undefined>(scenario?.weather[0]?.id);
  const [weatherWindowStart, setWeatherWindowStart] = useState(0);
  const [eventIndex, setEventIndex] = useState(0);
  const [selectedPromptId, setSelectedPromptId] = useState<string | undefined>();
  const weather = scenario?.weather.find((frame) => frame.id === selectedWeatherId) ?? scenario?.weather[0];
  const playable = cascadeIsPlayable(cascade);
  const availableEvents = useMemo(() => cascade?.events.filter((event) => event.availability === "available") ?? [], [cascade]);
  const cascadeEvent = availableEvents[Math.min(eventIndex, Math.max(availableEvents.length - 1, 0))];
  const selectedPrompt = suggestedPrompts.find((prompt) => prompt.id === selectedPromptId);

  if (!region || !scenario) {
    return <section className={`control-room ${className}`} aria-label="Flux control room">
      <p className="control-room__unavailable" role="status">Control room unavailable: a region and scenario input are required.</p>
    </section>;
  }

  const selectScenario = (scenarioId: string) => {
    const next = scenarios.find((item) => item.id === scenarioId);
    setSelectedWeatherId(next?.weather[0]?.id);
    setWeatherWindowStart(0);
    setEventIndex(0);
    onScenarioChange?.(scenarioId);
  };

  return <section className={`control-room ${className}`} aria-label="Flux control room" data-demo-module="control-room">
    <header className="control-room__header">
      <div>
        <p className="control-room__kicker">Flux / energy system desk</p>
        <h2>Weather, grid context, and evidence</h2>
      </div>
      <p className="control-room__rule">Every view names its source state before it makes a claim.</p>
    </header>

    <nav className="control-room__regions" aria-label="Region">
      {regions.map((item) => <button key={item.id} type="button" className={item.id === region.id ? "is-selected" : ""} aria-pressed={item.id === region.id} onClick={() => onRegionChange?.(item.id)}>
        <span>{item.label}</span><small>{statusCopy(item.topology.availability)}</small>
      </button>)}
    </nav>

    <section className="control-room__truth" aria-label="Region data status">
      <div>
        <p className="control-room__eyebrow">{region.label} system context</p>
        <h3>{region.summary}</h3>
      </div>
      <div className={`control-room__status status-${region.topology.availability}`}>
        <strong>{region.topology.label}</strong>
        <span>{topologyIsDisplayable(region) ? "Topology view accepted" : region.id === "minnesota" && region.topology.mode !== "aggregate" ? "Topology withheld pending accepted model" : "Topology view unavailable"}</span>
      </div>
      <Evidence notes={region.topology.provenance} limitations={region.topology.limitations} />
    </section>

    <div className="control-room__layout">
      <section className="control-room__weather" aria-labelledby="weather-heading">
        <div className="control-room__section-heading">
          <div><p className="control-room__eyebrow">Scenario weather</p><h3 id="weather-heading">{scenario.label}</h3></div>
          <select aria-label="Scenario" value={scenario.id} onChange={(event) => selectScenario(event.target.value)}>
            {scenarios.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </div>
        <p className="control-room__description">{scenario.description}</p>
        <div className="control-room__timeline" role="list" aria-label="Weather timeline">
          {scenario.weather.slice(weatherWindowStart, weatherWindowStart + 12).map((frame) => <button key={frame.id} type="button" role="listitem" className={frame.id === weather?.id ? "is-selected" : ""} aria-pressed={frame.id === weather?.id} onClick={() => setSelectedWeatherId(frame.id)}>
            <time>{frame.timeLabel}</time><span aria-hidden="true">{WEATHER_GLYPHS[frame.symbol]}</span><strong>{frame.condition}</strong><small>{statusCopy(frame.availability)}</small>
          </button>)}
          {scenario.weather.length > 12 ? <label className="control-room__timeline-more">Hour {weatherWindowStart + 1}–{Math.min(weatherWindowStart + 12, scenario.weather.length)} of {scenario.weather.length}<input type="range" min="0" max={Math.max(0, scenario.weather.length - 12)} value={weatherWindowStart} onChange={(event) => setWeatherWindowStart(Number(event.target.value))} /></label> : null}
        </div>
        {weather ? <div className={`control-room__weather-readout status-${weather.availability}`}>
          <span className="control-room__weather-glyph" aria-hidden="true">{WEATHER_GLYPHS[weather.symbol]}</span>
          <div><p className="control-room__eyebrow">Selected condition</p><h4>{weather.condition}</h4><p>{weather.detail ?? "No measured or projected detail was supplied."}</p></div>
          <Evidence notes={weather.provenance} limitations={weather.limitations} />
        </div> : <p className="control-room__unavailable" role="status">Weather unavailable: this scenario supplied no timeline.</p>}
        <Evidence notes={scenario.model?.provenance} limitations={[...(scenario.limitations ?? []), ...(scenario.model?.limitations ?? [])]} />
        {scenario.model ? <p className={`control-room__model status-${scenario.model.availability}`} data-demo-model-status={scenario.model.availability}><strong>{modelDisplayLabel(scenario.model)}</strong> · {statusCopy(scenario.model.availability)}</p> : <p className="control-room__unavailable" role="status">Prediction model unavailable: no model provenance was supplied.</p>}
      </section>

      <section className="control-room__cascade" aria-labelledby="cascade-heading" data-cascade-playable={String(playable)}>
        <div className="control-room__section-heading"><div><p className="control-room__eyebrow">Cascading failure</p><h3 id="cascade-heading">{cascade?.title ?? "Event playback"}</h3></div><span className={`control-room__status-chip status-${cascade?.availability ?? "unavailable"}`}>{playable ? "Playback ready" : "Unavailable"}</span></div>
        {playable && cascadeEvent ? <>
          <div className="control-room__cascade-stage"><span>Stage {eventIndex + 1} / {availableEvents.length}</span><h4>{cascadeEvent.stageLabel}</h4><p>{cascadeEvent.summary}</p></div>
          <div className="control-room__cascade-controls"><button type="button" onClick={() => setEventIndex((eventIndex - 1 + availableEvents.length) % availableEvents.length)} aria-label="Previous cascade event">←</button><button type="button" onClick={() => setEventIndex((eventIndex + 1) % availableEvents.length)} aria-label="Next cascade event">Next event →</button></div>
          <Evidence notes={[...(cascade?.provenance ?? []), ...(cascadeEvent.provenance ?? [])]} limitations={cascade?.limitations} />
        </> : <div className="control-room__unavailable" role="status"><strong>Cascade playback unavailable.</strong><p>{cascade?.unavailableMessage ?? "No source-backed cascade events were supplied for this selection."}</p><Evidence notes={cascade?.provenance} limitations={cascade?.limitations} /></div>}
      </section>
    </div>

    <section className="control-room__agent" aria-labelledby="agent-heading">
      <div><p className="control-room__eyebrow">Plain-English agent layer</p><h3 id="agent-heading">Ask from the evidence on screen</h3></div>
      {suggestedPrompts.length > 0 ? <div className="control-room__prompt-list">{suggestedPrompts.map((prompt) => <button key={prompt.id} type="button" className={prompt.id === selectedPrompt?.id ? "is-selected" : ""} onClick={() => { setSelectedPromptId(prompt.id); onPromptSelect?.(prompt); }}><span>{prompt.prompt}</span><small>{statusCopy(prompt.availability)}</small></button>)}</div> : <p className="control-room__unavailable" role="status">Suggested prompts unavailable: none were supplied.</p>}
      {selectedPrompt ? selectedPrompt.result ? <article className="control-room__answer"><p className="control-room__eyebrow">Plain-English result</p><p>{selectedPrompt.result.summary}</p><Evidence notes={selectedPrompt.result.evidence} limitations={selectedPrompt.result.limitations} /></article> : <p className="control-room__unavailable" role="status">Answer unavailable: this prompt has no evidence-backed result.</p> : null}
    </section>
  </section>;
}

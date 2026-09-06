import type { DemoAvailability, ProvenanceNote } from "./ControlRoom";

export interface HistoricalCountForecast {
  readonly availability: DemoAvailability;
  readonly modelVersion?: string;
  readonly countyFips?: string;
  readonly countyName?: string;
  readonly contextEndUtc?: string;
  readonly horizonMinutes?: number;
  readonly actualCustomersOut?: readonly number[];
  readonly predictedCustomersOut?: readonly number[];
  readonly provenance?: readonly ProvenanceNote[];
  readonly limitations?: readonly string[];
  readonly reason?: string;
}

/** A historical observed-count trace. It intentionally has no weather icon or forecast-now claim. */
export function HistoricalForecastPanel({ forecast }: { forecast: HistoricalCountForecast }) {
  if (forecast.availability !== "available") return <section className="historical-forecast" aria-label="Historical experimental count trajectory">
    <p className="control-room__eyebrow">Historical experimental count trajectory</p>
    <p className="control-room__unavailable" role="status">Unavailable: {forecast.reason ?? "The reviewed historical trajectory is not available."}</p>
  </section>;
  const actual = forecast.actualCustomersOut ?? [];
  const predicted = forecast.predictedCustomersOut ?? [];
  const rows = Math.max(actual.length, predicted.length);
  return <section className="historical-forecast" aria-label="Historical experimental count trajectory">
    <header><p className="control-room__eyebrow">Historical experimental count trajectory</p><h3>{forecast.countyName ?? forecast.countyFips ?? "Selected county"}</h3></header>
    <p>Observed outage-count context ending {forecast.contextEndUtc ?? "at an undisclosed time"}. This is not a live forecast or weather attribution.</p>
    <dl><div><dt>County FIPS</dt><dd>{forecast.countyFips ?? "Unavailable"}</dd></div><div><dt>Model version</dt><dd>{forecast.modelVersion ?? "Unavailable"}</dd></div><div><dt>Forecast horizon</dt><dd>{forecast.horizonMinutes === undefined ? "Unavailable" : `${forecast.horizonMinutes} minutes`}</dd></div></dl>
    <div className="historical-forecast__table-wrap"><table><thead><tr><th>Step</th><th>Observed customers out</th><th>Experimental predicted customers out</th></tr></thead><tbody>{Array.from({ length: rows }, (_, index) => <tr key={index}><td>{index + 1}</td><td>{actual[index] ?? "Unavailable"}</td><td>{predicted[index] ?? "Unavailable"}</td></tr>)}</tbody></table></div>
    {forecast.limitations?.length ? <p className="control-room__evidence"><strong>Limit:</strong> {forecast.limitations.join(" ")}</p> : null}
  </section>;
}

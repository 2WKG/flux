/**
 * A self-contained teaching section for the experimental EAGLE-I count JEPA.
 *
 * Client-side only, 2-D SVG, no network calls and no rendering imports. It reads
 * one vendored evaluation artifact (see `recordedEvaluation.ts`) and an invented
 * schematic (see `embeddingSchematic.ts`), and shows nothing else. Mounting is
 * somebody else's job: this module exports the section and touches no shared file.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import {
  runSchematicTraining,
  SCHEMATIC_DISCLAIMER,
  SCHEMATIC_HYPERPARAMETERS,
  type SchematicFrame,
  type Vec2,
} from "./embeddingSchematic";
import {
  ARTIFACT_PROVENANCE,
  absentMetrics,
  assertRecordedEvaluation,
  contextMinutes,
  formatCount,
  holdoutVersusPersistence,
  metric,
  RECORDED_EVALUATION as EVAL,
} from "./recordedEvaluation";
import { STATUS_COPY } from "../../source-truth";

const FRAME_MS = 90;
const PLOT = { width: 460, height: 340, pad: 44 } as const;

/** Map the schematic's [-1.2, 1.2] latent square onto the SVG viewBox. */
function project(point: Vec2): { cx: number; cy: number } {
  const span = 2.4;
  return {
    cx: PLOT.pad + ((point.x + 1.2) / span) * (PLOT.width - 2 * PLOT.pad),
    cy: PLOT.height - PLOT.pad - ((point.y + 1.2) / span) * (PLOT.height - 2 * PLOT.pad),
  };
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const listener = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, []);
  return reduced;
}

const SERIES_COLORS = { actual: "#edf5ff", predicted: "#46d7b0" } as const;

/** The recorded holdout trajectory for one county, drawn as two polylines. */
function TrajectoryChart({ countyFips }: { countyFips: string }) {
  const forecast = EVAL.county_forecasts.find((entry) => entry.county_fips === countyFips);
  if (!forecast) return <p>No recorded holdout trajectory for county {countyFips}.</p>;
  const values = [...forecast.actual_customers_out, ...forecast.predicted_customers_out];
  const top = Math.max(...values, 1);
  const width = 460;
  const height = 190;
  const path = (series: readonly number[]) =>
    series
      .map((value, index) => {
        const x = 40 + (index / (series.length - 1)) * (width - 56);
        const y = height - 26 - (value / top) * (height - 46);
        return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  return (
    <figure>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        role="img"
        aria-label={`Recorded held-out ${forecast.county_name} County trajectory: actual customers out against the model's predicted trajectory over ${forecast.horizon_minutes} minutes.`}
      >
        <line x1="40" y1={height - 26} x2={width - 16} y2={height - 26} stroke="#3d5f7c" strokeWidth="1.5" />
        <line x1="40" y1="12" x2="40" y2={height - 26} stroke="#3d5f7c" strokeWidth="1.5" />
        <text x="6" y="18" fill="#c8dded" fontSize="11">{formatCount(top)}</text>
        <text x="30" y={height - 8} fill="#c8dded" fontSize="11">
          {forecast.context_end_utc} + {forecast.horizon_minutes} min
        </text>
        <path d={path(forecast.actual_customers_out)} fill="none" stroke={SERIES_COLORS.actual} strokeWidth="2.5" />
        <path
          d={path(forecast.predicted_customers_out)}
          fill="none"
          stroke={SERIES_COLORS.predicted}
          strokeWidth="2.5"
          strokeDasharray="7 5"
        />
      </svg>
      <figcaption>
        {forecast.county_name} County ({forecast.county_fips}), held-out window ending {forecast.context_end_utc}.
        Solid: recorded EAGLE-I customers out. Dashed: the recorded run&rsquo;s decoded trajectory. Both arrays are
        read verbatim from the artifact; neither is recomputed in the browser.
      </figcaption>
    </figure>
  );
}

/** The animated latent-space schematic. Explicitly not model output. */
function EmbeddingSchematic() {
  const frames = useMemo<readonly SchematicFrame[]>(() => runSchematicTraining(), []);
  const reducedMotion = usePrefersReducedMotion();
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    if (!reducedMotion) setPlaying(true);
  }, [reducedMotion]);

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      setIndex((current) => (current + 1 >= frames.length ? 0 : current + 1));
    }, FRAME_MS);
    return () => clearInterval(timer);
  }, [playing, frames.length]);

  const frame = frames[Math.min(index, frames.length - 1)];
  return (
    <figure className="pipeline">
      <div>
        <p className="eyebrow">SCHEMATIC ILLUSTRATION &mdash; NOT MODEL OUTPUT</p>
        <h3>Prediction happens in embedding space</h3>
        <p>{SCHEMATIC_DISCLAIMER}</p>
      </div>
      <svg
        viewBox={`0 0 ${PLOT.width} ${PLOT.height}`}
        width={PLOT.width}
        height={PLOT.height}
        role="img"
        aria-label={`Schematic latent space at illustrative epoch ${frame.epoch}. ${frame.caption}`}
      >
        <rect x={PLOT.pad} y={PLOT.pad} width={PLOT.width - 2 * PLOT.pad} height={PLOT.height - 2 * PLOT.pad} fill="none" stroke="#23415c" strokeWidth="1.5" />
        <text x={PLOT.pad} y={PLOT.pad - 14} fill="#c8dded" fontSize="11">
          invented 2-D latent space &mdash; the recorded run embeds in {EVAL.config.embedding_dim} dimensions

        </text>
        <defs>
          <marker id="jepa-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="#7fb2ff" />
          </marker>
        </defs>
        {frame.predictions.map((entry) => {
          const context = project(entry.context);
          const predicted = project(entry.predicted);
          const target = project(entry.emaTarget);
          return (
            <g key={entry.windowId}>
              <line x1={context.cx} y1={context.cy} x2={predicted.cx} y2={predicted.cy} stroke="#7fb2ff" strokeWidth="2" markerEnd="url(#jepa-arrow)" />
              <line x1={predicted.cx} y1={predicted.cy} x2={target.cx} y2={target.cy} stroke="#ff7d68" strokeWidth="2" strokeDasharray="4 4" />
              <circle cx={context.cx} cy={context.cy} r="6" fill="#dceeff" />
              <rect x={target.cx - 6} y={target.cy - 6} width="12" height="12" fill="none" stroke="#ffcc66" strokeWidth="2.5" />
              <circle cx={predicted.cx} cy={predicted.cy} r="5" fill="#46d7b0" />
              <text x={context.cx + 9} y={context.cy - 8} fill="#c8dded" fontSize="10">{entry.label}</text>
            </g>
          );
        })}
      </svg>
      <div role="group" aria-label="Schematic animation controls">
        <button type="button" onClick={() => setPlaying(!playing)}>{playing ? "Pause" : "Play"}</button>{" "}
        <label>
          Illustrative epoch{" "}
          <input
            type="range"
            min={0}
            max={frames.length - 1}
            value={index}
            onChange={(event) => {
              setPlaying(false);
              setIndex(Number(event.target.value));
            }}
          />
        </label>
        <p aria-live="polite">
          Illustrative epoch {frame.epoch} of {SCHEMATIC_HYPERPARAMETERS.epochs} &middot; schematic embedding loss{" "}
          {frame.embeddingLoss.toFixed(4)} (unitless, invented). {frame.caption}
        </p>
      </div>
      <figcaption>
        Pale circle: where the context encoder puts six hours of history. Green circle: where the predictor thinks the
        next six hours will land. Amber square: where the EMA target encoder actually puts them. The red dashed gap is
        the entire loss. Nothing in this figure was produced by the recorded model.
      </figcaption>
    </figure>
  );
}

/** The recorded train/held-out split, which is what makes any figure above readable. */
function SplitTable() {
  const total = EVAL.split.train_windows + EVAL.split.holdout_windows;
  const holdoutShare = (EVAL.split.holdout_windows / total) * 100;
  return (
    <article className="method-entry">
      <h3>The split every figure on this page refers to</h3>
      <p>
        Strategy: <strong>{EVAL.split.strategy}</strong>. Windows are ordered in time and the last{" "}
        {holdoutShare.toFixed(1)}% are held out, so no training window ends after a held-out window begins. Each window
        advances by its full context-plus-target span ({EVAL.split.window_stride_steps} steps of{" "}
        {EVAL.scope.cadence_minutes} minutes), giving {EVAL.split.target_context_overlap_steps} steps of
        target-into-later-context overlap. {EVAL.split.overlap_verification}
      </p>
      <table>
        <thead>
          <tr><th>Slice</th><th>Windows</th><th>Counties</th></tr>
        </thead>
        <tbody>
          <tr><td>Train</td><td>{EVAL.split.train_windows}</td><td>{EVAL.split.train_counties.join(", ")}</td></tr>
          <tr><td>Held out</td><td>{EVAL.split.holdout_windows}</td><td>{EVAL.split.holdout_counties.join(", ")}</td></tr>
        </tbody>
      </table>
      <p>
        The same three counties appear in both slices; this is a split in <em>time</em>, not across counties, so it says
        nothing about a county the model never saw. Per-county window counts:{" "}
        {Object.entries(EVAL.split.county_window_counts).map(([fips, count]) => `${fips}: ${count}`).join(" · ")}.
      </p>
      {EVAL.scope.unavailable_county_fips.length > 0 && (
        <p>
          Requested but unavailable:{" "}
          {EVAL.scope.unavailable_county_fips.map((entry) => `${entry.county_fips} (${entry.reason})`).join("; ")}. It is
          named rather than silently dropped.
        </p>
      )}
    </article>
  );
}

function MetricsTable() {
  const missing = absentMetrics();
  const rows: readonly [string, string][] = [
    ["Held-out count MAE", formatCount(metric("holdout_count_mae"))],
    ["Held-out count RMSE", formatCount(metric("holdout_count_rmse"))],
    ["Persistence baseline MAE (same split)", formatCount(metric("persistence_baseline_count_mae"))],
    ["Persistence baseline RMSE (same split)", formatCount(metric("persistence_baseline_count_rmse"))],
    ["Held-out embedding MSE (normalised latent space)", metric("holdout_embedding_mse").toFixed(4)],
    ["Training count MAE", formatCount(metric("train_count_mae"))],
    ["Train ÷ held-out MAE ratio", `${metric("train_to_holdout_count_mae_ratio").toFixed(1)}×`],
  ];
  return (
    <article className="method-entry">
      <h3>What one recorded run measured</h3>
      <p>
        Every figure below is read from {ARTIFACT_PROVENANCE.originPath} (SHA-256{" "}
        <code>{ARTIFACT_PROVENANCE.contentSha256.slice(0, 12)}…</code>), produced by revision{" "}
        <code>{EVAL.regeneration.generated_by_revision}</code> from {EVAL.source.provider} {EVAL.source.year}. Counts are
        customers out per 15-minute step.
      </p>
      <table>
        <thead><tr><th>Measure</th><th>Value</th></tr></thead>
        <tbody>{rows.map(([label, value]) => <tr key={label}><td>{label}</td><td>{value}</td></tr>)}</tbody>
      </table>
      <p>
        <strong>Read the ratio before the MAE.</strong> Held-out MAE is {(holdoutVersusPersistence() * 100).toFixed(0)}%
        of the persistence baseline&rsquo;s on the same windows, but training error is{" "}
        {metric("train_to_holdout_count_mae_ratio").toFixed(1)}× the held-out error. The training slice spans a large
        storm and the chronological tail is much calmer, so beating persistence on a calm tail is not evidence of
        storm-time skill. That asymmetry is recorded in the artifact&rsquo;s own limitations, not inferred here.
      </p>
      {missing.length > 0 && (
        <p>
          Not available in this run and therefore not shown:{" "}
          {missing.map((name, position) => (
            <span key={name}>{position > 0 ? ", " : ""}<code>{name}</code></span>
          ))}
          . The
          artifact&rsquo;s regeneration note explains why &mdash; the 1.4 GB source lives under gitignored{" "}
          <code>data/raw/</code>, so the run cannot be reproduced in CI. Re-running{" "}
          <code>{EVAL.regeneration.command.split(" --")[0]}</code> with the source present would emit them.
        </p>
      )}
    </article>
  );
}

/**
 * The exported section. Mount it inside a page; it renders no page chrome of its own
 * beyond its heading, and imports nothing outside this directory.
 */
export function JepaSection() {
  assertRecordedEvaluation(EVAL);
  const [county, setCounty] = useState(EVAL.county_forecasts[0]?.county_fips ?? "");
  return (
    <section aria-labelledby="jepa-section-heading" data-source-status="hypothetical" data-experiment-status={EVAL.status}>
      <div className="pipeline">
        <div>
          <p className="eyebrow">{STATUS_COPY.hypothetical} / experimental JEPA</p>
          <h2 id="jepa-section-heading">Predicting an outage trajectory without predicting the numbers</h2>
          <p>
            County-level EAGLE-I customers-out counts are noisy: utilities report on their own cadence, a single
            re-reported meter can move a county by hundreds, and the same physical storm looks different in two
            neighbouring counties. A model trained to reconstruct those raw counts spends most of its capacity fitting
            reporting artefacts. A joint-embedding predictive architecture avoids that by moving the prediction one
            level up: it encodes the next six hours into a representation, and predicts <em>that representation</em>.
            Detail the representation throws away is detail the loss never asks the model to reproduce.
          </p>
          <p>
            The target is a <strong>trajectory</strong>, not a single number: {EVAL.scope.context_steps} steps of
            history ({contextMinutes() / 60} hours at {EVAL.scope.cadence_minutes}-minute cadence) predict{" "}
            {EVAL.scope.target_steps} steps ahead ({EVAL.forecast.horizon_minutes} minutes). The shape of the recovery
            is the thing being learned, so a prediction can be right about a decline and wrong about its depth.
          </p>
          <p>
            <strong>Status: experimental.</strong> One recorded run exists on the unmerged branch{" "}
            <code>{ARTIFACT_PROVENANCE.originBranch}</code>. No product surface reads its output, and it is not an
            outage probability, a weather forecast, a topology claim, or a cascade result.
          </p>
        </div>
      </div>

      <div className="method">
        <article className="method-entry">
          <h3>The three pieces</h3>
          <table>
            <thead><tr><th>Component</th><th>Recorded description</th></tr></thead>
            <tbody>
              {Object.entries(EVAL.architecture).sort().map(([name, description]) => (
                <tr key={name}><td>{name.replace(/_/g, " ")}</td><td>{description}</td></tr>
              ))}
            </tbody>
          </table>
          <p>
            The target encoder is updated by an exponential moving average (momentum {EVAL.config.ema_momentum}) and
            receives no gradient. Without that stop-gradient both encoders could agree by collapsing to a constant,
            which would drive the loss to zero while predicting nothing.
          </p>
          <p>
            Because the loss lives in embedding space, a low embedding error is not by itself a low count error. Turning
            an embedding back into customers out is a separate decode step, and it is the decoded counts that the MAE
            below measures.
          </p>
        </article>
        <SplitTable />
      </div>

      <EmbeddingSchematic />

      <div className="method">
        <MetricsTable />
        <article className="method-entry">
          <h3>One held-out trajectory, as recorded</h3>
          <div role="group" aria-label="County">
            {EVAL.county_forecasts.map((entry) => (
              <button key={entry.county_fips} type="button" onClick={() => setCounty(entry.county_fips)} aria-pressed={county === entry.county_fips}>
                {entry.county_name}
              </button>
            ))}
          </div>
          <TrajectoryChart countyFips={county} />
        </article>
      </div>

      <div className="pipeline">
        <div>
          <p className="eyebrow">WHAT THIS DOES NOT CLAIM</p>
          <h3>Limitations, recorded with the run</h3>
        </div>
        <ul>
          {EVAL.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
          <li>
            The counties appear in both slices; the split is chronological only, so out-of-county generalisation is
            untested.
          </li>
          <li>
            Model version <code>{EVAL.model_version}</code>, status <code>{EVAL.status}</code>. Nothing here has been
            re-run or re-validated by this page.
          </li>
        </ul>
      </div>
    </section>
  );
}

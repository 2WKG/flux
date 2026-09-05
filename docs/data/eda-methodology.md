# Reproducible EDA and anomaly analysis

**EDA version:** `1.0.0`
**Metric-layer dependency:** `pipelines.metrics.METRIC_LAYER_VERSION == 1.0.0`
**Fixture-contract dependency:** `pipelines.db.SCHEMA_VERSION == 1.0.0`

`pipelines.eda` is the repeatable exploratory workflow over the canonical views
described in [`metric-layer.md`](metric-layer.md). It profiles distributions,
missingness, within-view correlation, segmentation, and period-over-period
change, then ranks anomaly and data-quality candidates by impact. It analyses
only the released KPIs, so every finding names the KPI, its unit, its metric
version, and its lineage. It is exploratory: it proposes candidates for review,
it does not label a row an error.

## Running it

```bash
# First run on a freshly built artifact: install the canonical views (a write).
uv run --extra dev python scripts/run_eda.py data/duck/grid.duckdb --install-views

# Every later run opens the artifact read-only.
uv run --extra dev python scripts/run_eda.py data/duck/grid.duckdb \
  --scenario uri_2021 --report data/eda-report.json --summary data/eda-summary.md
```

The script puts the repository root on `sys.path` itself, so it runs from any
working directory without `PYTHONPATH`. It exits `2` with a named status on
`stderr` (`artifact_missing`, `metric_views_missing`) instead of a traceback
when the artifact path does not exist or the metric layer is absent.

| Parameter | Purpose |
| --- | --- |
| `--view` | Restrict the run to named canonical views; repeatable, defaults to all three |
| `--scenario` | Restrict every view to one `scenario_id` |
| `--robust-z-threshold` | Modified z-score cutoff for anomaly and change candidates (default 3.5) |
| `--min-correlation-rows` | Minimum paired rows before a correlation is reported (default 30) |
| `--install-views` | Open the artifact writable and (re)install the canonical views first; off by default |

By default the artifact is opened **read-only** and the run never mutates the
curated file: a mistyped path is an `artifact_missing` error rather than a new
empty `.duckdb`, and a missing metric layer is a `metric_views_missing` error
rather than a silent install. Pass `--install-views` once after a rebuild to
create the views (view-only DDL from `install_metric_layer`, which itself
rejects a mismatched contract version). Rerunning against a refreshed database
is the intended workflow: outputs are ordered deterministically, and the only
run-dependent fields are `generated_at_utc` and the `database` path as given.
Floating-point statistics are rounded to 12 significant digits before they are
reported, because DuckDB's parallel aggregation may reorder a sum and otherwise
vary in the last place between two runs over an unchanged artifact.

## What is measured

| Analysis | Method | Output |
| --- | --- | --- |
| Profiling | `count`, `min`, `max`, `avg`, `stddev_samp`, `median`, `quantile_cont` at 0.1/0.9, and median absolute deviation per KPI | `views.<view>.profiles.<kpi>.stats` |
| Missingness | Null fraction for every column in the view, not only KPI columns | `views.<view>.missingness` |
| Correlation | Pearson `corr()` between KPI pairs released by the same view, on pairwise-complete rows | `views.<view>.profiles` peer list under `correlations` |
| Segmentation | Row count, non-null count, median, min, and max per contract dimension | `views.<view>.profiles.<kpi>.segments` |
| Change | First difference within one series (`lag` partitioned by the series key, ordered by the view's time column) | `views.<view>.profiles.<kpi>.change` |
| Anomaly candidates | Iglewicz-Hoaglin modified z-score on levels and on first differences | `findings` with code `anomaly_candidate` or `level_shift` |

The modified z-score is `0.6745 * (x - median) / MAD`, where `MAD` is the median
absolute deviation. A value is a candidate at `|z| >= 3.5`, and is reported
`high` severity at `|z| >= 5`, otherwise `medium`. Up to five candidates are
kept per KPI per test, ranked by `|z|`.

A discrete or near-constant measure can collapse `MAD` to zero even when real
outliers exist — a series that steps by one unit per window is the common case.
Iglewicz and Hoaglin's mean-absolute-deviation form is then used instead,
`0.7979 * (x - median) / MeanAD`, and the block records which scale was applied
under `scale` (`mad` or `mean_abs_deviation`). When every value equals the
median, no scale exists and the test is reported unavailable rather than clean.

## Assumptions and limits

- **Grain is the metric layer's, not ours.** Segmentation reports counts,
  medians, and extremes only. It never sums a KPI across prediction windows,
  runs, sites, or scenarios, because the released aggregation rules forbid it.
- **Correlation is linear and within one view.** Pearson `r` assumes a linear
  relationship and is sensitive to outliers; it is descriptive here, never
  causal. Cross-view correlation is not attempted because the views do not
  share a grain. The causal layer owns causal claims.
- **The robust scale assumes a roughly unimodal spread.** MAD-based scoring is
  resistant to a few extreme values, but a genuinely multimodal or heavily
  discretized KPI will produce candidates that review should dismiss.
- **Change analysis assumes ordered snapshots within a series.** It compares
  adjacent points inside one scenario/county or one cascade run only. Gaps in
  the series are visible as large deltas, not interpolated away.
- **Prediction windows are not observations.** `outage_predictions.ts` starts a
  six-hour window, and `cascade_runs.hour` is a simulated offset. A change
  candidate on either is a change in modeled output, never observed history.
- **Synthetic topology stays labelled.** The report's top-level `topology`
  block is derived from the artifact's `ingest_log`: when the ACTIVSg2000 case
  load is recorded there it reads `synthetic ACTIVSg2000` (with the release and
  file), otherwise it is reported `unavailable` with a reason — never assumed.
  Each view also carries a `provenance` block with the distinct `scenario_kind`
  values and `*_source_name` sources of record for the rows in scope, and the
  summary prints both under "Topology and provenance".

## Thresholds and their trade-offs

| Threshold | Default | Why |
| --- | --- | --- |
| `MIN_ROBUST_ROWS` | 8 | Below this a median and MAD are too unstable to score against |
| `MIN_CHANGE_POINTS` | 3 | A series needs at least two differences before a spread is meaningful; shorter series are excluded from the pooled scale and never yield a `level_shift` |
| `MIN_CORRELATION_ROWS` | 30 | Small-sample `r` is dominated by noise |
| `MAX_SEGMENTS_PER_DIMENSION` | 20 | Keeps the summary readable; truncation is flagged per dimension |

## Unavailable is not zero

Every statistic that cannot be computed is reported with a status and a reason,
and is collected in `unavailable_checks`:

| Status | Meaning |
| --- | --- |
| `no_rows` | The view has no rows in scope; its KPIs are unavailable, not zero |
| `insufficient_rows` | Fewer rows than the stated minimum for that test |
| `unavailable` | The test is undefined here, e.g. every value equals the median so no robust scale exists |
| `undefined` | A correlation input has zero variance |
| `not_applicable` | The view has no time grain, so change analysis does not apply |

A missing KPI value is reported as a `missing_measure` finding, never read as
zero. An empty view is a `no_rows` finding, never an empty dashboard panel.

## Prioritization

Findings are sorted by severity, then by impact descending, then by view, KPI,
code, and evidence, so two runs over the same artifact produce the same order.
`impact` is the null fraction for `missing_measure`, `|z|` for the two anomaly
codes, and a fixed rank for structural findings.

| Code | Severity | Impact |
| --- | --- | --- |
| `no_rows` | high | 1.0 |
| `missing_measure` | high at >= 5% missing, otherwise medium | null fraction |
| `anomaly_candidate` | high at `|z| >= 5`, otherwise medium | `|z|` |
| `level_shift` | high at `|z| >= 5`, otherwise medium | `|z|` |
| `zero_variance` | medium | 0.5 |

## Outputs

`scripts/run_eda.py` writes two artifacts and prints the summary. The default
paths below are gitignored; pass `--report`/`--summary` to write elsewhere.

- `data/eda-report.json` — the full machine-readable report: parameters, per-view
  profiles, correlations, segments, change analysis, ranked findings, and the
  unavailable-check list.
- `data/eda-summary.md` — the written insight summary: coverage, the prioritized
  findings table, the follow-up questions each finding raises, and the checks
  that were reported unavailable.

Neither artifact is delivered anywhere yet. No dashboard, notebook, or
notification consumes them; that remains platform work.

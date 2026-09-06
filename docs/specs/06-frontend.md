# 06 — Frontend (`web/`)

> **State scope:** The UI may select a state only when its declared artifacts and validation contract are present. Texas references below describe the repository's topology adapter, which requires its source artifacts and build. [`10-minnesota-demo.md`](10-minnesota-demo.md) is planning authority, not a checked-in Minnesota fixture.

Status: draft, weekend build. Owner: web lane. Depends on spec 05 (copilot API) for every byte of data; the map never reads DuckDB directly.

> **Legacy Texas scope (D-5).** The Texas/ERCOT/ACTIVSg2000 references below are the **legacy**
> path that [`README.md`](README.md) declares superseded by
> [`10-minnesota-demo.md`](10-minnesota-demo.md) as *planning* authority. They stay because they
> describe what the server can serve today (`copilot/routes/layers.py:44`, `:59`); Minnesota
> supersedes them as plan, not as behaviour.
>
> **What `web/` on `master` actually is.** The shipped site is offline and static. `web/src/main.tsx`
> mounts a shell that routes two pages (`web/src/router/index.ts`), each loaded as its own bundle
> chunk: the scenario explorer at `/` and the method explainer at `/explainer` (2WKG-478).
> `web/src/pages/MainPage.tsx` imports `data/demo/bundle.json` at build time and
> `web/test/static-demo.test.mjs:17-27` forbids the literal `fetch(` in both the source and the
> built bundle. None of the deck.gl/MapLibre map described below is wired, and none of the routes
> in *Inputs* is called by the shipped entry.

## Purpose

The one screen the judges see. For a selected state with validated topology, a deck.gl + MapLibre map can show a scenario/hour timeline, line loading, county outage risk, storm polygon, cascade playback, site pins, critical loads, line-upgrade ranking, and the "Ask" box wired to `POST /ask`. The repository's 2000-bus Texas adapter requires its source artifacts and build. The checked-in five-bus preview is geographic-neutral and cannot be relabelled as a state result.

State-aware: the app must show only the selected state's available artifacts and limitations. State-context ingestion does not make topology layers available. Texas (`uri_2021`, hour 0) remains the planned topology-backed path; another state needs a validated network and model contract before the same views can be enabled.

## Inputs

| Input | Source | Notes |
| --- | --- | --- |
| `GET /scenarios` | spec 05 | scenario picker |
| `GET /layers/{name}` | spec 05 | GeoJSON for geometry; Arrow IPC for `outage_risk`, `eaglei`, `national_hex` |
| `POST /site-score`, `GET /cascade`, `GET /predictions`, `GET /lines/top` | spec 05 | click-driven cards. `POST /cascade` and `POST /predict` were listed here and **do not exist** (D-3); the persisted reads `GET /cascade` (`copilot/routes/predictions.py:445`) and `GET /predictions` (`:248`) are what `master` serves |
| `POST /ask` SSE | spec 05 | Ask box |
| Basemap tiles | OpenFreeMap (re-verified 2026-09-05 by `curl`: all five style URLs return 200 `application/json`): `https://tiles.openfreemap.org/styles/positron` (light), `https://tiles.openfreemap.org/styles/dark` (dark, default for the demo), also `liberty`, `bright`, `fiord`. No API key. Attribution required (openfreemap.org, verified): "OpenFreeMap © OpenMapTiles Data from OpenStreetMap"; the styles' `openmaptiles` source points at `https://tiles.openfreemap.org/planet`, whose TileJSON carries that attribution string, so MapLibre's default `AttributionControl` renders it automatically — do not pass `attributionControl: false`. Glyphs: `https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf`. | Fallback: Protomaps self-hosted PMTiles — `@protomaps/basemaps` 5.7.2 (npm latest, verified: ESM `index.d.ts` exports `layers(source, flavor, options?)` and `namedFlavor(name)`) `layers("protomaps", namedFlavor("dark"))` with a `pmtiles://` source (needs the `pmtiles` package's `Protocol` registered on maplibre) and glyphs `https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf` (curl 200). **Neither `@protomaps/basemaps` nor `pmtiles` is in `web/package.json` yet** — add both only if the fallback is built. The Protomaps *hosted* API URL/key page was not fetched — treat hosted Protomaps as `[UNVERIFIED]`; if OpenFreeMap is down at demo time, ship a Texas-extent PMTiles file in `web/public/` instead. |
| `VITE_API_URL` | env | default `http://localhost:8000` |

## Outputs

- A Vite SPA at `http://localhost:5173` (dev) / `web/dist` (static build, servable by the copilot FastAPI as `/` if we want one process).
- No persistence beyond URL state (`?scenario=uri_2021&h=3&site=…&view=tx|us`) so a demo step is a link.

## Algorithm or Design

### Stack (versions introspected from `web/node_modules` 2026-09-05)

- `vite` 8.2.2, `react` 19.2.8, `typescript` 5.9.3, `pnpm`.
- `deck.gl` 9.3.11 (`@deck.gl/core`, `@deck.gl/layers`, `@deck.gl/geo-layers`, `@deck.gl/mapbox`, `@deck.gl/react`, plus `@deck.gl/aggregation-layers` already in package.json). Verified exports: `GeoJsonLayer, ScatterplotLayer, PathLayer, PolygonLayer, IconLayer, TextLayer` from `@deck.gl/layers`; `H3HexagonLayer` (and `TripsLayer`) from `@deck.gl/geo-layers`; `MapboxOverlay` (the only export) from `@deck.gl/mapbox`. **`@deck.gl/extensions` is not a direct dependency** — it is present transitively via the `deck.gl` umbrella (9.3.11) but `PathStyleExtension` (dashed tripped lines) must be imported from `@deck.gl/extensions`, so add it to `package.json` explicitly.
- `maplibre-gl` 6.7.0 + `react-map-gl` 8.1.3 (import from `react-map-gl/maplibre` — verified: that entry re-exports `@vis.gl/react-maplibre` 8.1.3, which exports `Map` (default), `useControl`, `AttributionControl`, `Source`, `Layer`, `useMap`, `MapProvider`, and types `MapProps`, `MapRef`).
- deck.gl ↔ MapLibre integration: `MapboxOverlay` from `@deck.gl/mapbox` in **interleaved** mode (`MapboxOverlayProps = Omit<DeckProps, …> & {interleaved?: boolean}` verified in `mapbox-overlay.d.ts`; deck.gl docs' compatibility table: interleaved requires maplibre-gl-js v3+ — 6.7.0 satisfies), so lines render under basemap labels via the per-layer `beforeId` (`LayerOverlayProps {slot?, beforeId?}` in `@deck.gl/mapbox/dist/types.d.ts`). Attach with react-map-gl's `useControl`.
- `h3-js` 4.5.0 only if we aggregate client-side; default is server-precomputed hex (`/layers/national_hex`) so h3-js is not needed for the demo.
- `apache-arrow` 21.2.0 to read Arrow IPC (`tableFromIPC` verified as an exported function); `@loaders.gl/arrow` not required.
- `zustand` 5.0.15 (`create`, `createStore`, `useStore` exported) for the state model; `@tanstack/react-query` 5.102.8 (`QueryClient`, `QueryClientProvider`, `useQuery`, `useQueries` verified) for fetch caching (static layers cached forever, scenario layers keyed by params).
- Tailwind 4 + shadcn/ui for panels (dark theme). Lucide icons. `react-markdown` for the Ask bubble. **None of `tailwindcss`, `lucide-react`, `react-markdown` (nor shadcn) is installed in `web/` yet** — Sat AM scaffold adds them.

### State model (`web/src/state/store.ts`, zustand)

```ts
type View = "tx" | "us";
type Selection =
  | { kind: "none" }
  | { kind: "county"; fips: string }
  | { kind: "line"; lineId: string }
  | { kind: "bus"; busId: string }
  | { kind: "site"; siteId: string }
  | { kind: "critical"; id: string };

interface AppState {
  view: View;
  scenarioId: ScenarioId;              // "uri_2021" | "beryl_2024" | "helene_2024" | "forecast_72h"
  hour: number;                        // 0..scenario.hours-1
  playing: boolean;                    // timeline play/pause
  speed: 1 | 2 | 4;                    // hours per second
  layers: Record<LayerName, boolean>;  // visibility toggles
  selection: Selection;
  compareSiteId: string | null;        // second site for the "vs Houston" question
  unitMw: 300 | 1000;
  cascadeRunId: string | null;         // null = scenario default run
  counterfactualSiteId: string | null; // when set, cascade layer shows the run WITH the site online (spec 04 writes a second cascade_run keyed by site)
  compareActual: boolean;              // EAGLE-I vs predicted split slider
  ask: { open: boolean; messages: AskMessage[]; streaming: boolean };
  // actions
  setHour, play, pause, step(+1|-1), setScenario, select, toggleLayer, setView, ...
}
```

`hour` is the single clock. Every time-dependent layer derives from `(scenarioId, hour)`. Derived selectors (memoized): `countyRiskAtHour`, `trippedUpToHour`, `darkCountiesAtHour`, `criticalLostAtHour`, `stormPolygonAtHour`.

URL sync: a tiny effect writes `view, scenario, h, site, cf` to `history.replaceState` (throttled 250 ms) and reads them on boot.

### Data loading (`web/src/data/`)

- `api.ts`: typed fetchers; GeoJSON parsed with `response.json()`, Arrow with `tableFromIPC(await response.arrayBuffer())`.
- `queries.ts`: react-query hooks. Static (`buses`, `lines`, `gens`, `counties`, `critical_loads`, `sites`) `staleTime: Infinity`. Scenario-keyed (`outage_risk`, `cascade`, `storm`, `eaglei`) keyed by `[name, scenarioId]` — fetched **once per scenario** for the whole time range; the hour scrub never hits the network.
- `outage_risk` Arrow (≈254 counties × 72–168 hours ≈ 40k rows) is reshaped once into `Map<fips, Float32Array(hours)>` for O(1) lookup during scrub.
- `cascade` JSON is expanded into `trippedAtHour: Map<elementId, hour>` and `darkAtHour: Map<fips, hour>`; a county is dark at `h` iff `darkAtHour.get(fips) <= h`.
- `national_hex` Arrow is loaded lazily on first `view = "us"`; the **503 `unavailable` envelope with `details.reason: "not_built"`** (`copilot/routes/layers.py:236-237`, `copilot/api/errors.py:76-83`) hides the toggle with a tooltip "national model not built". It is not a 404, and it is not a bare `{"not_built": true}` body (D-2).
- Prefetch on boot: everything for the boot scenario, plus `sites` for `unitMw=300`, so demo steps 2–4 need no spinner. Other scenarios prefetch after idle.

### Layers (`web/src/map/layers/`) — one file per layer, each exports `(state, data) => Layer | null`

| # | Layer (LayerName) | deck.gl type | Data | Encoding | Demo step |
| --- | --- | --- | --- | --- | --- |
| 1 | `lines` — line loading | `GeoJsonLayer` (LineString, `lineWidthUnits:"pixels"`) or `PathLayer` if we pre-flatten | `/layers/lines?scenario_id&hour` props `loading_pct`; at hour `h` the tripped set from cascade overrides | width by `kv` (69→1px … 500→4px); color ramp by `loading_pct` (0–60 grey, 60–90 amber, 90–100 orange, >100 red); tripped → dashed dark red (`getDashArray: [number, number]` accessor + `dashJustified` from `PathStyleExtension` in `@deck.gl/extensions` 9.3.11, verified `path-style-extension.d.ts`) and drawn on a second thin layer so they stay visible | 1, 3 |
| 2 | `outage_risk` — county choropleth | `GeoJsonLayer` (Polygon, `filled`, `stroked:false`, `extruded:false`) | `counties` geometry + `outage_risk` series | fill alpha by `p_out` at `hour` (sequential ramp, 6 steps); `updateTriggers.getFillColor: [hour, scenarioId]`; when `compareActual` is on, a second `GeoJsonLayer` with EAGLE-I `customers_out` and a CSS split slider clipping the two canvases (simplest split: two `DeckGL` overlays is expensive — instead one layer, and the split toggles per-feature color source by screen-x using a `getFillColor` that reads a uniform `splitX` via `updateTriggers`; fallback: side-by-side toggle button) | 2 |
| 3 | `storm` — animated storm polygon | `PolygonLayer` | `/layers/storm` feature for `hour` (and `hour-1` for a trailing ghost at 30 % alpha) | fill by `severity`; `transitions: {getPolygon: 400}` for smooth motion between hours | 2, 3 |
| 4 | `cascade` — playback | not a separate geometry layer: it *drives* `lines` (tripped set), `outage_risk` (dark counties overlay in near-black), and a `ScatterplotLayer` pulse on the bus that trips at exactly `hour` (`radiusMinPixels 6→18` via `transitions`) | `cascade` JSON | element trips appear in hour order; the pulse plays once per newly tripped element | 3, 4 (counterfactual run) |
| 5 | `critical_loads` — pins | `IconLayer` (atlas: base, hospital, water) with `ScatterplotLayer` halo | `/layers/critical_loads` + `criticalLostAtHour` | green halo → red when lost at `≤ hour`; `sizeUnits:"pixels"`, `sizeMinPixels 18` | 3, 4 |
| 6 | `sites` — candidate-site pins | `ScatterplotLayer` (`radiusUnits:"pixels"`, radius by `grid_value_score`) + `TextLayer` rank label for top 5 | `/layers/sites?scenario_id&unit_mw` | color by `safety_score` (red<40, amber<70, green); selected site gets a white ring layer; `pickable` → opens `SiteCard` | 4, 5 |
| 7 | `line_upgrades` — Idea 3 screen | `GeoJsonLayer` LineString | `/layers/line_upgrades?tech` | color by `mw_per_musd` quantiles (viridis-ish 5 steps); `ferc_screen_pass` → thicker; `spark_eligible` → dashed; replaces `lines` while the "Upgrades" mode is on | (extra screen, between 4 and 5 if time) |
| 8 | `buses` / `gens` | `ScatterplotLayer` | static | tiny grey dots; `gens` sized by MW, coal `retiring` orange — hidden by default above zoom 5 | 1 |
| 9 | `national_hex` — scale view | `H3HexagonLayer` (`@deck.gl/geo-layers`) | `/layers/national_hex?res=4` (~3–5k hexes at res 4 for CONUS) | `getElevation` by `gen_mw`, fill by `lines` density; `extruded`, pitch 45 | 6 |

Common: `pickable` only on layers with a card (`counties`, `lines`, `sites`, `critical_loads`); `autoHighlight` on those. All colors come from `web/src/map/palette.ts` (one file, dark theme, colorblind-safe ramps).

### Map container (`web/src/map/MapView.tsx`)

- `<Map mapStyle={STYLE_URL} initialViewState={TX_VIEW} mapLib={maplibregl}>` from `react-map-gl/maplibre`. Verified `MapProps` (`@vis.gl/react-maplibre` 8.1.3 `map.d.ts`): `mapLib?: MapLib | Promise<MapLib>` (optional — the maplibre entry imports maplibre-gl itself), `mapStyle?: string | StyleSpecification`, `initialViewState?`, and all maplibre `MapOptions` except `style|container|bounds|fitBoundsOptions|center` pass through — including `attributionControl?: false | AttributionControlOptions` (maplibre-gl 6.7.0 d.ts). Leave `attributionControl` unset (default control shows the OpenFreeMap TileJSON attribution); do not write the bare boolean `attributionControl` prop — its type is `false | options`, not `true`.
- `<DeckOverlay layers={layers} interleaved />` — a `useControl(() => new MapboxOverlay({interleaved: true}))` wrapper, `overlay.setProps({layers})` (verified `MapboxOverlay.setProps(props: MapboxOverlayProps)`) on every render; layers ordered as the table above with a `beforeId` pointing at a label layer. **`waterway-name` does not exist in the OpenFreeMap `dark` style** (fetched 2026-09-05; its `symbol` layers are `water_name, road_oneway, road_oneway_opposite, highway_name_other, highway_name_motorway, place_other, place_suburb, place_village, place_town, place_city, place_city_large, place_state, …`). Default to `beforeId: "water_name"` (the first symbol layer in `dark`) but still read `map.getStyle().layers` at runtime and pick the first `type === "symbol"` layer, since ids differ across `positron`/`liberty`.
- View presets: `TX_VIEW = {longitude:-99.3, latitude:31.2, zoom:5.6}`, `US_VIEW = {longitude:-98, latitude:38.5, zoom:3.6, pitch:45}`; `flyTo` between them (2.5 s) on `view` change.
- Tooltip: `getTooltip` → small HTML with 2–3 props; cards are React panels, not tooltips.

### Ask box (`web/src/ask/`)

- `AskPanel.tsx`: right-side drawer, message list, input, suggested-question chips (the two demo questions + 2 regression ones).
- `useAsk.ts`: `fetch(`${API}/ask`, {method:"POST", body})` creates an opaque `attempt_id`, verifies the matching `X-Flux-Attempt-Id` response header, then reads `response.body.getReader()`. The parser (`web/src/ask/sse.ts`) splits on `\n\n`, parses `event:`/`data:`/`id:`, validates the v1 `seq`/`id` envelope, and ignores every line starting with `:`. The event contract is `docs/research/sse-event-schema.md`; `EventSource` is not usable for POST.
- Rendering per event: `lifecycle` opens the attempt; `text` appends to the current assistant bubble (markdown via `react-markdown`, minimal); `tool_call` renders a collapsed chip from `tool`/`input` with spinner; `tool_result` fills the chip (✓/✗ + `elapsed_ms`) and is expandable to the JSON; `citation` adds a footnote entry and highlights `[doc p.N]` tokens in the text as links to the footnote; `done` shows the badge: green "verified" or amber "n unverified numbers" (hover lists them); `error` shows its safe message at `data.error.message` in an inline red line.
- **Map linkage:** on `tool_call` the UI reacts — `score_site` → selects that site and opens its card; `run_cascade` → sets `hour` and plays the cascade; `predict_outage` → selects the county; `top_lines` → switches to the Upgrades mode and highlights the returned line ids. This is what makes step 5 visual.
- Context sent with every question: `{scenario_id, hour, selected_site_id, compare_site_id, selected_element_id, unit_mw}` from the store.
- Abort: an `AbortController` per question; new question cancels the previous stream.

### Keyboard / demo controls (`web/src/controls/`)

| Key | Action |
| --- | --- |
| `Space` | play / pause hour |
| `←` / `→` | hour −1 / +1 (Shift: ±6) |
| `Home` / `End` | hour 0 / last |
| `1`–`4` | scenario `uri_2021`, `beryl_2024`, `helene_2024`, `forecast_72h` |
| `N` | toggle national view |
| `C` | toggle cascade layer; `Shift+C` toggle counterfactual (site online) run |
| `S` | toggle sites layer; `U` upgrades mode; `A` actual-vs-predicted split |
| `/` | focus Ask box; `Esc` closes drawer |
| `D1`…`D6` (i.e. `d` then digit) | jump to demo step preset (scenario, hour, view, layers, selection) — presets in `web/src/demo/steps.ts` |

Timeline bar (`Timeline.tsx`): scrubber over `0..hours-1`, hour label with the scenario's real timestamp (`ts_start + hour`), play/pause, speed 1×/2×/4×, tick marks where critical loads are lost.

### Component tree (file paths)

```
web/
  index.html
  vite.config.ts
  src/
    main.tsx                      # QueryClientProvider + App
    App.tsx                       # layout grid: MapView | LeftRail | RightDrawer | Timeline
    state/store.ts                # zustand store + selectors
    state/url.ts                  # URL <-> state sync
    data/api.ts                   # fetchers (GeoJSON/Arrow/JSON), types from ../types
    data/queries.ts               # react-query hooks
    data/reshape.ts               # Arrow -> typed maps (outage series, cascade maps)
    types/api.ts                  # TS types mirroring spec 05 responses
    map/MapView.tsx               # react-map-gl Map + DeckOverlay + flyTo
    map/DeckOverlay.tsx           # useControl(MapboxOverlay)
    map/palette.ts
    map/layers/{lines,outageRisk,storm,cascadePulse,criticalLoads,sites,lineUpgrades,buses,nationalHex}.ts
    map/useLayers.ts              # composes the layer array from state + data (useMemo)
    panels/LeftRail.tsx           # scenario picker, layer toggles, legend, view toggle
    panels/ScenarioPicker.tsx
    panels/LayerToggles.tsx
    panels/Legend.tsx
    panels/RightDrawer.tsx        # hosts one of: SiteCard | CountyCard | LineCard | CriticalPanel | UpgradesTable
    panels/SiteCard.tsx           # safety card + grid-value card + "run counterfactual" + "compare with…" + "Ask why"
    panels/CountyCard.tsx         # predicted p_out series vs EAGLE-I actual (small sparkline, two series)
    panels/LineCard.tsx           # loading, kv, DLR vs reconductor economics (from line_upgrade_scores)
    panels/CriticalPanel.tsx      # list of critical loads, status at hour, hour lost; turns red
    panels/UpgradesTable.tsx      # top-10 by mw_per_musd with FERC/SPARK flags (Idea 3 screen)
    controls/Timeline.tsx
    controls/Hotkeys.tsx          # keydown handler -> store actions
    ask/AskPanel.tsx ask/useAsk.ts ask/sse.ts ask/ToolChip.tsx ask/Footnotes.tsx
    demo/steps.ts                 # the six presets
    demo/StepStrip.tsx            # tiny 1–6 strip bottom-left (hidden with `H`)
```

### Props of the load-bearing components

```ts
// SiteCard
{ siteId: string; scenarioId: ScenarioId; unitMw: 300|1000;
  onRunCounterfactual(siteId): void; onCompare(siteId): void; onAsk(question: string): void }
// CriticalPanel
{ items: Array<{id; name; kind:"dod"|"hospital"|"water"; mw; hourLost: number|null}>; hour: number }
// Timeline
{ hour; hours; playing; speed; marks: number[]; onChange(h); onPlay(); onPause(); onSpeed(s) }
// AskPanel
{ open; messages: AskMessage[]; streaming; onAsk(q); onClose() }
// AskMessage
{ role:"user"|"assistant"; text; tools: ToolEvent[]; citations: Citation[]; done?: DoneEvent }
```

### Performance budget

Target: **60 fps while scrubbing the hour** on the Texas twin on a MacBook (M-series) — that is 2,000 buses, ~3,200 lines, 254 counties, ~150 critical loads, ~30 sites.

- Scrubbing must not re-upload geometry. Only accessors change: `getFillColor` (counties), `getColor`/`getDashArray` (lines), `getRadius` (pulse), `getPolygon` (storm). Use `updateTriggers` keyed on `hour` so deck.gl re-runs accessors without rebuilding buffers; geometry `data` references stay identical (react-query returns stable objects).
- Per-frame accessor work must be O(n) hash lookups: `riskAtHour.get(fips)[hour]`, `trippedAtHour.get(id) <= hour`. No array `.find` in accessors.
- `useLayers` is a `useMemo` on `[data refs, hour, scenarioId, toggles, selection]`; layer objects are recreated (cheap) but data is not.
- County polygons simplified server-side (spec 05: ≤ 5 kB/county) → < 1.3 MB GeoJSON; lines ≤ 3 MB gzipped. Boot-to-interactive < 3 s on localhost.
- Storm polygon transition 400 ms; hour playback at 1×/s means one accessor pass per second, far under budget; at 4× still fine.
- National: res-4 H3 for CONUS (~3–5k hexes, extruded) is trivial; **do not** draw 82k buses / 100k+ lines as GeoJSON — that is the case the hex layer exists for. If a "lines at national" look is wanted, serve res-5 hex with line density only.
- Measure with deck.gl's metrics callback — in 9.3.11 it is the experimental, underscore-prefixed `_onMetrics?: (metrics: DeckMetrics) => void` on `DeckProps` (verified `core/dist/lib/deck.d.ts`; there is no public `onMetrics`), passed through `MapboxOverlay` props → `metrics.fps`, rendered in a hidden dev badge (`F` key). Expect it to rename in a minor release.
- Escape hatch if fps drops: switch `lines` from `GeoJsonLayer` to a pre-flattened `PathLayer` with binary attributes (`LayerData = {length: number, attributes?: Record<string, TypedArray | Buffer | BinaryAttribute>}` verified in `core/dist/types/layer-props.d.ts`; e.g. `data: {length, attributes:{getPath:{value,size:2}, …}}`) built once in `reshape.ts`.

## Interfaces

- API: exactly spec 05's routes and shapes; TS types in `src/types/api.ts` are hand-mirrored (no codegen this weekend) with a single `assertShape` dev check per layer on first load. SSE types are hand-mirrored only from `docs/research/sse-event-schema.md` v1, never a second local protocol.
- Env: `VITE_API_URL` (default `http://localhost:8000`), `VITE_BASEMAP_STYLE` (default `https://tiles.openfreemap.org/styles/dark`), `VITE_NATIONAL=1` to show the national toggle even if `/layers/national_hex` is unavailable (503, `details.reason: "not_built"`) (renders an empty layer with a "not built" label — for slide rehearsal only).
- Scripts: `pnpm dev`, `pnpm build` (`tsc -b && vite build`), `pnpm preview` exist in `web/package.json`; **`pnpm typecheck` and `pnpm lint` do not yet** — add `"typecheck": "tsc -b --noEmit"` and an eslint script (no eslint config is installed either) before criterion 1 can be run.
- Store actions are the only way to mutate state; panels never call the API for writes (there are none).

## Acceptance criteria

1. `pnpm build` and `pnpm typecheck` pass with zero errors; no `any`.
2. Boot on `http://localhost:5173` shows the dark basemap with Texas lines, buses hidden, counties faint, attribution visible, in < 3 s with the copilot API warm.
3. Scenario picker lists the four scenario ids from `/scenarios`; switching to `uri_2021` and pressing `Space` animates hours 0→N with the choropleth and storm polygon changing every hour and the FPS badge ≥ 55 throughout (Chrome, M-series laptop).
4. `A` toggles the actual (EAGLE-I) vs predicted comparison; both render for the same hour and the county card shows both series when a county is clicked.
5. With cascade on, stepping `→` from hour 0 shows lines turning dashed red in the order given by `/layers/cascade`; at the hour a critical load is lost, its pin halo turns red and `CriticalPanel` moves it to the "lost" group with the hour — the Uri default run must show a DoD installation lost at hour 3 (the demo line).
6. Sites layer shows all Texas candidates (≥ 30 per pitch) with rank labels for the top 5; clicking #1 opens `SiteCard` with safety score, flags, grid-value score, `lol_reduction_mwh`, `congestion_relief_pct`, `blackstart_reach_mw`, and protected critical loads — all values equal to `POST /site-score` for that id.
7. `Shift+C` (or the card button) switches the cascade layer to the counterfactual run for the selected site; the same hour-3 installation stays green and the card shows "customer-hours avoided" only if that number is returned by the API (never computed in the UI).
8. Upgrades mode (`U`) recolors lines by `mw_per_musd`, opens `UpgradesTable` with the top 10 from `/lines/top?region=ERCOT`, and clicking a row highlights the line and opens `LineCard` with DLR vs reconductor cost/uplift.
9. Ask: typing Q1 from spec 05 streams text; tool chips appear before any digits in the text; `score_site` chips select/open the corresponding site cards on the map; citations render as footnotes; the `done` badge shows verified state.
10. `N` flies to the national view and renders the H3 hex layer (or the "not built" label under `VITE_NATIONAL=1`) at ≥ 55 fps with pitch 45; `N` again returns to Texas.
11. URL round-trip: reloading `?scenario=uri_2021&h=3&site=<id>&cf=1` restores scenario, hour, selection and counterfactual mode.
12. Every demo preset `D1`–`D6` lands on the storyboard state below without a fetch spinner (prefetch verified in the network tab).
13. Losing the API mid-stream shows the error line in the Ask panel and the map stays interactive (no unhandled promise rejections in console).
14. Lighthouse-free sanity: no console errors on boot; bundle < 2.5 MB gzipped (deck.gl + maplibre dominate).
15. **Mutation probes (each must turn red; run by hand before rehearsal, reset after):**
    - (a) delete `updateTriggers.getFillColor` from the `outage_risk` layer → a Playwright/vitest-browser check that samples a county's fill at hour 0 vs hour 36 must fail (colour freezes because deck.gl does not re-run the accessor).
    - (b) set `interleaved: false` on the overlay → a check that `map.getLayer(<first symbol id>)` renders above deck's lines (pixel sample on a label glyph over a red line) must fail.
    - (c) hardcode `beforeId: "waterway-name"` → deck.gl must throw/warn on the missing layer id and the overlay smoke test must fail; this pins the runtime-lookup rule.
    - (d) make the SSE parser skip only the literal `: ping` line → a test feeding `: ping - 2026-09-05T00:00:00Z\n\n` followed by a `text` event must fail (the comment line is mis-parsed as a malformed event).
    - (e) in `SiteCard`, sum two `lol_reduction_mwh` values client-side and render the total → criterion 6/7's "every rendered number equals a field in the `POST /site-score` response" test must fail.
    If any probe stays green, the criterion it targets is an assertion that cannot fail and must be rewritten.

## Demo hook — storyboard per step

| Step | Preset state (`demo/steps.ts`) | What the audience sees | Spoken beat |
| --- | --- | --- | --- |
| 1 | `view:"us"` → auto-fly to `tx` after 3 s; layers `lines, gens`; scenario `uri_2021`, hour 0 | national hex, fly-in to Texas lines coloured by base loading | "This is the grid as public data lets us see it." (say "topology is synthetic" here) |
| 2 | `tx`; layers `outage_risk, storm, lines`; `playing:true` speed 2×, stops at hour 36; then `compareActual:true` | counties light up as the storm polygon crosses; split to EAGLE-I actual; click Travis county → card with both series | "Uri, replayed. Left: our prediction. Right: what actually happened." |
| 3 | `tx`; layers `lines, cascade, critical_loads, outage_risk`; hour 0, play at 1× to hour 3 | lines trip in sequence; pulse on each tripped bus; at hour 3 the Fort Hood/Cavazos pin goes red; `CriticalPanel` turns red | "At hour three, a defense installation loses supply." |
| 4 | `tx`; layers `sites, critical_loads, cascade`; `selection:{site:#1}`; `unitMw:300`; then `counterfactualSiteId:#1`, play to hour 3 | 30 site pins ranked; card for #1 (safety + grid value); flip to counterfactual: same storm, installation stays green; card shows avoided MWh from the API | "Thirty Texas coal sites, ranked. Pick number one. Same storm, this site online." |
| 4b (if time) | `U` upgrades mode | lines by MW per $M; top-10 table with FERC/SPARK flags | "The twin also tells you which existing wires to upgrade." |
| 5 | Ask drawer open; `compareSiteId:` Houston-area site; chip Q1 | chips: score_site ×2 → cite; map opens both site cards; answer with citations + verified badge | "Why this site over the one near Houston?" |
| 6 | `view:"us"`, layers `national_hex` | extruded hex CONUS | "This scales. The architecture has a slot for real utility data under CEII." |

`StepStrip` shows 1–6 with the active step; the presenter uses `d1`…`d6` or the strip.

## Risks / unknowns

- **Interleaved overlay + label `beforeId`:** OpenFreeMap `dark` symbol layer ids were fetched 2026-09-05 (first is `water_name`; `waterway-name` does not exist) but other styles differ — read them at runtime and fall back to overlaid mode (`interleaved:false`) if no symbol layer is found. Loses "under labels" only.
- **Split-screen actual-vs-predicted** is the fiddliest visual; the fallback is a toggle (`A` swaps colour source) plus the county-card sparkline. Decide by Saturday night; do not spend > 1 h on the split.
- **Hurricane Beryl / Helene** storm polygons depend on spec 02 output; if only Uri has a polygon, hide the storm layer for other scenarios (empty FeatureCollection renders nothing — already handled).
- **National hex** depends on spec 01 building the 82k join; the `VITE_NATIONAL=1` stub keeps step 6 rehearsable as a slide-like view.
- **GeoJsonLayer accessor cost on 254 polygons × multi-ring** is fine, but if counties come in unsimplified (> 10 MB) fps will drop — enforce spec 05's simplification, not a client fix.
- **OpenFreeMap availability** at demo time (public, keyless): pre-warm by loading the app 10 min before; fallback PMTiles file for Texas extent in `web/public/tx.pmtiles` if the connection is unreliable (Protomaps self-host path verified; hosted API not).
- **react-map-gl 8 + maplibre-gl 6 API drift:** `react-map-gl/maplibre` entry, `useControl`, `MapProps` and `MapboxOverlay({interleaved})` / `setProps` were introspected from the installed packages 2026-09-05 (ledger: `docs/specs/verification/05-06.md`). Still `[UNVERIFIED]`: the exact `useControl` + `MapboxOverlay` React wiring example (deck.gl "Using with React" guide page was not fetched) — write it from the `IControl` types and test at install time.
- **SSE through Vite proxy** buffers by default — call the API origin directly with CORS (spec 05 sets `CORS_ORIGINS`), do not proxy `/ask`.

## Weekend time-box (hours)

| Block | Hours | Deliverable |
| --- | --- | --- |
| Sat AM | 2 | scaffold (Vite/React/TS/Tailwind/shadcn), `MapView` + `DeckOverlay` with basemap, `lines` + `buses` static layers, store + URL sync |
| Sat PM | 3 | data hooks + Arrow reshape; `outage_risk` choropleth + `storm` + `Timeline` + hotkeys; FPS badge |
| Sat eve | 3 | cascade playback (tripped lines, pulse, dark counties), `critical_loads` + `CriticalPanel` |
| Sun AM | 3 | `sites` + `SiteCard` + counterfactual toggle + `CountyCard`; `line_upgrades` + `UpgradesTable` + `LineCard` |
| Sun PM | 2 | Ask drawer: SSE parser, chips, citations, map linkage, verified badge |
| Sun PM | 1 | national hex view + fly-to; demo presets `D1–D6` + `StepStrip` |
| Sun eve | 1 | polish, legend, palette pass, rehearsal with copilot; build + preview |
| **Total** | **15** | |

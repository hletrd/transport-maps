# Global Transport-Time Map — Design

**Date:** 2026-09-03
**Status:** Superseded in part — see "As built (2026-09)" below

## As built (2026-09)

The pipeline and the page were built from this spec and diverged as they went.
The table lists every claim below that no longer holds; the rest reads as
written. Current values live in `src/transport_maps/config.py`,
`calibration.toml` (which holds the ground speeds and urban factor too, since
task B2 on 2026-10-02) and `README.md`.

| Spec claim | As built |
|---|---|
| "The site makes no runtime API calls" (Summary) | Two: OpenStreetMap's Nominatim for address search and click-to-address (on request only) and the Google tag for page-view counting (`web/app.js`, `web/index.html`) |
| D9: Google Routes API (TRANSIT) for city↔airport legs | Google Routes in DRIVE mode, used offline only, to fit the per-road-class ground speeds (`calibrate/ground.py`, `scripts/calibrate_ground.py`); no transit legs |
| D10: AWS S3 + CloudFront | nginx on `atik.kr` (`deploy/`) |
| D12: res-5 cells match GRIP4's 5-arcmin cells | Solver grid is H3 resolution 6, refined to 7 in dense regions; a res-6 cell (36 km²) is smaller than a GRIP4 cell |
| ~150 origins | 553 in `data/origins.toml` |
| Vite + React 19 + TypeScript | One vanilla ES-module page (`web/index.html`, `web/app.js`) |
| Flight times fitted from FR24 / FlightAware | Fitted from adsb.lol globe history (ODbL); `calibration.toml [meta]` |
| Protomaps basemap, `basemap.pmtiles` ~100 MB | No basemap; `water.pmtiles` (867 MB) built from OSM water polygons and HydroLAKES cuts the bands to the coast |
| 548,557 res-5 cells (~253 km², ~8.5 km edge) | 4,091,715 res-6 land cells (36 km², 3.7 km edge, 6.5 km across), refined to res 7 (5.2 km², 2.4 km across) |
| Ground speeds 85/60/40/25/5 km/h | By GRIP4 class: roadless 5, highway 104, primary 57, secondary 50, tertiary 18, local 25 km/h. Only highway, primary, secondary and tertiary (classes 1-4) are fitted, against 2,998 Google Routes journeys; roadless and local roads keep published-figure defaults, because the fit returned a negative time per kilometre for roadless terrain and drew local roads from 116 km across four journeys (`calibration.toml [ground]`, read by `graph/ground.py`) |
| Rail 250/80 km/h with 140/56 services per week | 200/75 km/h, no headway model (`calibration.toml [rail]`) |
| Rail sinuosity 1.15 | `detour_factor = 1.2` |
| Transfer table | `processing_min`, `disembark_min`, `border_min` and `connection_min` tables in `calibration.toml` |
| 600k nodes, 4M edges, minutes per origin | About 10 M cells; a full build takes hours (`cli.py`) |
| Google TRANSIT sampled per origin | Never done |
| `.bin` 162 KB (82,983 cells) | 181,480 B (90,740 res-4 cells; `hover_cells.bin` gives the ordering) |
| Eleven bands | 37 bands (`config.BAND_EDGES_MIN`) |
| Contour lines | None |
| "The frontend never learns how the numbers were made; the pipeline never learns how they are drawn" (Architecture) | False both ways, by design: the page prints the pipeline's per-mode prose (`modeDetail`), and the bands overlap by a one-cell rim that is gap-free only if the page draws the faster band on top (`fill-sort-key`). Both rules are written down in `docs/contract.md` |
| EC2 / S3 / CloudFront | nginx (`deploy/`) |

## Summary

A static website showing a spinnable 3D globe. The user picks a starting city from a
list; the globe paints a continuous isochrone surface — colored bands of expected
door-to-door travel time — covering all land on Earth. Air, rail, ferry and ground
transit are modeled as one connected network, so the bands bend along high-speed rail
corridors and bloom around airline hubs.

Everything is precomputed offline. The site makes no runtime API calls and needs no
backend.

## Goals

- Answer "from here, how long does it take to reach anywhere on Earth?" at a glance.
- Treat rail as a first-class mode, not a footnote — HSR visibly reshapes the surface.
- Publish numbers that are honest about waiting, not best-case fantasy connections.
- Ship an artifact that is legally clean to redistribute publicly.
- Keep the pipeline reproducible: re-runnable from open inputs plus a small config.

## Non-Goals

- Not a trip planner. It does not book, price, or produce dated itineraries.
- Not schedule-accurate. It models expected times, not "the 08:15 to Frankfurt".
- Not street-level. Intra-city routing is out of scope; a metro area is a few cells.

## Decision Log

Every choice made during design, with the alternatives passed on. Any of these can be
revisited in a later iteration without re-deriving the reasoning.

| # | Decision | Chosen | Passed on | Why |
|---|---|---|---|---|
| D1 | Geographic scope | Global — one origin city, destinations worldwide | Single country/region; single metro; continental+intercontinental split | Air is the backbone of the story; rail and transit serve the legs |
| D2 | Origin selection | Pick from a curated city list, all precomputed | Fixed single origin; click-anywhere; address search | Static site, zero backend, instant switching; arbitrary origins need live global routing |
| D3 | Travel-time data | Open data + model calibrated from real flights | Paid schedule API as the dataset; real GTFS everywhere; pure distance approximation | Redistribution-safe and reproducible; calibration recovers most of the accuracy |
| D4 | Rendering | Continuous isochrone surface | Colored destination dots; country choropleth; surface + dots | Reads as a single legible field; dots look sparse, choropleth hides in-country variation |
| D5 | Audience | Public website | Local-only; private-then-public; public under enterprise licence | Forces the redistribution-clean design, which is the durable choice anyway |
| D6 | Ground legs | Rail graph (OSM) + per-cell road speed field | Uniform ground speed; full Valhalla/OSRM planet routing; both | Honors rail properly at a fraction of the build cost of planet routing |
| D7 | Time semantics | Expected door-to-door, "leave now" | Fastest possible itinerary; departure-time-aware; both toggleable | Frequency-aware waiting is the honest number and the one calibration improves most |
| D8 | Presentation | Pure 3D globe, always | Globe that flattens on zoom; flat Mercator; flat Equal Earth | Matches a global-reach subject; no Mercator polar distortion |
| D9 | Paid APIs | Google Routes API (TRANSIT) for city↔airport legs | Guessing access times; Amazon Location Service | User prefers Google/Amazon; replaces the weakest guess in the model for ~$5–25 |
| D10 | Hosting | AWS S3 + CloudFront, serving PMTiles | GCP Cloud Storage + CDN; Cloudflare Pages | User prefers Google/Amazon; one storage tech for basemap and isochrones, no per-tile pricing |
| D11 | Route network source | Wikipedia "Airlines and destinations" tables + OurAirports | OpenFlights routes.dat (stale, 2014); OpenSky (licence forbids); paid schedules (cannot redistribute) | Only open, current, redistributable global route network |
| D12 | Road speed field source | GRIP4 5-arcmin road-density rasters | Planet OSM highway parsing; Natural Earth roads | 5 arcmin (~8x8 km) matches H3 res-5 cell size almost exactly; CC-0; removes the pipeline's heaviest stage |
| D13 | Antarctica | Excluded from the cell universe | Include with a special case | H3 cannot polyfill a pole-wrapping shape, and it has no scheduled service |
| D14 | Route frequency | Fitted gravity model, coefficients calibrated | Ship observed frequencies; assume uniform frequency | Wikipedia gives the network but not frequency; a fitted model keeps observed data out of `dist/` |
| D15 | Calibration data source | **adsb.lol** (free API + daily historical archives, no key, ODbL 1.0) | FR24 API ($119.95/mo min); FlightAware AeroAPI (pay-per-query); OpenSky (licence forbids) | Feeding earns free FR24/FlightAware *accounts* but not API access — those are separately priced. adsb.lol is free, keyed to nobody, and ODbL, so unlike D3 its derived data may be **redistributed with attribution and share-alike** rather than only fitted-from |

### Choices deliberately deferred

- Number of origin cities beyond the v1 set of ~150.
- Whether to add a "fastest possible" layer alongside "expected" (D7 alternative).
- Whether to add real GTFS for rail in high-coverage countries (D3 alternative).

## Architecture

Two halves with a documented file format between them. The frontend never learns how
the numbers were made; the pipeline never learns how they are drawn.

```
OFFLINE PIPELINE (Python 3.14 + uv)          SHIPPED ARTIFACT        FRONTEND
─────────────────────────────────────        ────────────────        ────────
OurAirports ─┐                                origins/{iata}.pmtiles  Vite + React 19
Wikipedia   ─┼→ build graph ─→ Dijkstra ─→    origins/{iata}.bin   →  MapLibre GL JS 5
OSM rail    ─┤   (one graph)   (per origin)   origins/{iata}.json     projection: globe
OSM roads   ─┤                                index.json
OSM ferries ─┘
calibration.toml (fitted from FR24/FlightAware)
```

Pipeline stages are separate modules with explicit inputs and outputs, each runnable
and testable alone:

| Module | Responsibility |
|---|---|
| `sources/` | Fetch and cache raw inputs. One module per source. |
| `graph/` | Build the multi-modal graph. No I/O beyond its inputs. |
| `solve/` | Single-source Dijkstra from the origin node, one run per origin. Pure computation. |
| `contour/` | Dissolve per-cell times into banded polygons. |
| `emit/` | Write PMTiles, binary arrays, JSON indices. |
| `calibrate/` | One-off: fit coefficients from enterprise flight data. |

## Data Sources and Licensing

| Source | Use | Licence | Ships? |
|---|---|---|---|
| OurAirports | Airport coordinates, size, IATA/ICAO | Public domain | Yes |
| Wikipedia airport pages | Airline route network (who flies A→B) | CC-BY-SA | Yes, attributed |
| OpenStreetMap | Rail lines, stations, ferry routes | ODbL | Yes, attributed |
| GRIP4 road density | Per-cell ground speed field | CC-0 | Yes, attributed |
| Protomaps basemap | Globe basemap tiles | Open, OSM-derived | Yes, self-hosted |
| Google Routes API | City↔airport transit times | Commercial | Derived values only |
| FR24 / FlightAware | Model calibration | Commercial, no redistribution | **No — coefficients only** |

### The redistribution rule

Superseded in part by D15: with adsb.lol's ODbL data the firewall is no longer
strictly required, since ODbL permits redistribution under attribution and
share-alike — the same terms this project already meets for OpenStreetMap. The
firewall is kept anyway. It costs nothing, and it keeps the door open to
sampling a proprietary provider later without re-auditing what may ship.

The original constraint, which still applies to any FR24 or FlightAware data:

**No flight record from either provider is ever written to the shipped artifact.**

Calibration reads samples, fits ~20 coefficients, writes `calibration.toml`, and
discards the samples. `calibration.toml` is committed and human-readable — anyone can
audit that it contains physics, not data. This is enforced by a pipeline test that
fails if any shipped file traces to a provider response.

## The Travel-Time Model

One unified graph. One Dijkstra per origin. That is the entire algorithm.

### Nodes

| Type | Approx. count | Notes |
|---|---|---|
| Hex cells | 548,557 | H3 resolution 5, land excluding Antarctica (~253 km²/cell, ~8.5 km edge) |
| Airports | ~4,000 | Filtered to those with scheduled passenger service |
| Rail stations | ~10,000 | Intercity and high-speed; commuter-only stations excluded |
| Ferry terminals | ~2,000 | OSM `route=ferry` endpoints |

### Edges

| Edge | Weight |
|---|---|
| hex ↔ hex (6 neighbors) | centroid distance ÷ cell ground speed |
| hex ↔ transport node | connect node to its containing cell, plus access time |
| airport → airport | block time + expected wait |
| station → station | OSM line length ÷ line speed class + expected wait |
| terminal → terminal | ferry crossing time + expected wait |
| any mode change | transfer penalty (below) |

### Ground speed field

Each land cell gets an effective speed from the highest-grade road class present in it,
read from the GRIP4 density rasters:

| Best GRIP road class in cell | Effective speed |
|---|---|
| motorway | 85 km/h |
| trunk / primary | 60 km/h |
| secondary / tertiary | 40 km/h |
| residential / unclassified | 25 km/h |
| none | 5 km/h |

This is deliberately coarse: at ~8.5 km cell edge it represents "how fast you traverse
this terrain", including road-based public transport, not a specific route.

### Rail speed classes

Derived from OSM tags, falling back down the list when tags are absent:

Rail is read from OSM `type=route, route=train` relations, which carry an ordered stop
list. A route counts as high-speed when any member way is tagged `highspeed=yes`.

| Route class | Effective speed | Assumed frequency |
|---|---|---|
| high-speed | 250 km/h | 140 /week |
| conventional | 80 km/h | 56 /week |

Relations carry no timetable, so frequency is a per-class assumption rather than a fitted
value. Track is never straight between stops, so distances are scaled by a sinuosity
factor of 1.15.

### Flight block time

```
block = taxi_out(airport_size) + airborne(great_circle_distance) + taxi_in(airport_size)
```

`airborne` is fitted per distance band rather than assuming constant cruise speed, since
short hops spend proportionally far more time climbing and descending. All three terms
come from `calibration.toml`.

### Expected wait — "leave now" semantics

The published number answers: **you decide to leave at a uniformly random moment — how
long until you arrive?** This is the semantic that makes low-frequency routes correctly
expensive, and it is stated plainly in the UI.

```
headway   = 168 hours / flights_per_week
E[wait]   = headway / 2
```

A twice-daily route costs ~6 hours of expected waiting. A weekly route costs ~3.5 days.
This is why remote islands correctly resolve to *days* away rather than hours.

### Transfer penalties

| Transfer | Cost |
|---|---|
| ground → air, international | 90 min |
| ground → air, domestic | 60 min |
| air → air | `max(minimum_connection_time(airport), headway/2)` |
| air → ground | 45 min |
| ground → rail | 15 min |
| rail → rail | `max(10 min, headway/2)` |
| ground → ferry | 30 min |

### Solver

Single-source Dijkstra from the origin city node over the combined graph using `scipy.sparse.csgraph`. The graph is
roughly 600k nodes and 4M edges, so a single origin solves in seconds and the full
150-origin run is minutes, not hours.

## Calibration

A one-off script, re-runnable when the model drifts. It samples real flights via the
FR24 flight-summary endpoint and FlightAware AeroAPI, then regresses:

- Airborne time vs. great-circle distance, by distance band and aircraft class
- Taxi-out and taxi-in overhead by airport size class
- Realistic minimum connection time per hub
- Observed route frequency, used twice: to fit the **gravity frequency model**
  (`flights_per_week = base * size_weight[dep] * size_weight[arr] * distance_km ^ decay`),
  since Wikipedia supplies the route network but no frequencies; and to **validate
  coverage** of that network, reporting the percentage of real routes it captures

Fit on 80% of the sample, report mean absolute error on the held-out 20%. The MAE is
committed alongside the coefficients so accuracy claims are auditable.

Google Routes API (TRANSIT mode) is called once per origin city and per major
destination metro to measure real city↔airport transit times. Only the resulting
durations are retained.

## Shipped Artifact

| File | Size | Purpose |
|---|---|---|
| `index.json` | ~20 KB | Origin city list with coordinates and display names |
| `origins/{iata}.pmtiles` | 0.5–1.5 MB | Dissolved isochrone band polygons |
| `origins/{iata}.bin` | 162 KB | H3 res-4 uint16 minutes array (82,983 cells), for hover readout |
| `origins/{iata}.json` | ~200 KB | Transport nodes with arrival time and predecessor, for route inspection |
| `basemap.pmtiles` | ~100 MB | Protomaps globe basemap, served once |

Only the selected origin's files are fetched, so a page view costs roughly 1–2 MB
beyond the basemap.

### Isochrone bands

Eleven bands, spaced roughly logarithmically because the interesting structure is at
the short end:

`0–2h · 2–4 · 4–6 · 6–9 · 9–12 · 12–18 · 18–24 · 24–36 · 36–48 · 48–72 · 72h+`

## Frontend

Vite + React 19 + TypeScript (ESNext), MapLibre GL JS 5 with `projection: 'globe'`,
always on. PMTiles are read directly via the `pmtiles` protocol handler — no tile
server.

| Element | Behavior |
|---|---|
| Globe | Spinnable, zoomable; great-circle paths render correctly |
| Isochrone bands | Fill layers, perceptually uniform colorblind-safe sequential ramp legible against a dark globe |
| Contour lines | Thin strokes at band edges |
| Hover | Readout of expected time at the cursor, from the `.bin` array |
| Click a node | Route breakdown that produced that time, e.g. `ICN → DXB → GRU · 31h 20m` |
| City picker | Searchable list of origins |
| Legend | Band scale plus a plain-language note on "leave now" semantics |

The exact color ramp is selected at implementation time under the `dataviz` guidance,
against these requirements: perceptually uniform, colorblind-safe, and legible in both
light and dark surroundings.

## Build and Deploy

The pipeline runs locally or on an EC2 instance for the OSM-heavy stages. Output syncs
to S3 and is served through CloudFront.

OSM handling avoids a full planet import: Geofabrik regional extracts are filtered with
`osmium tags-filter` down to railway, ferry and highway-class ways before any parsing,
which reduces the working set by well over an order of magnitude.

## Testing and Error Handling

The pipeline fails loudly rather than silently shipping a broken surface. Every stage
validates its output and aborts with a specific diagnostic.

| Check | Failure condition |
|---|---|
| Source integrity | Airport without coordinates; route referencing an unknown airport |
| Graph connectivity | Disconnected component containing a scheduled-service airport |
| Coverage | Land cell with no reachable path, beyond a known-unreachable allowlist (Antarctic interior) |
| Licence firewall | Any shipped file traceable to an FR24 or FlightAware response |

Tests:

- **Unit** — speed field assignment, wait model, block-time fit, band dissolution.
- **Golden** — known-good door-to-door times for a fixed set of city pairs, asserted
  within tolerance. Seoul→Tokyo, Seoul→London, Seoul→a remote Pacific island.
- **Invariant** — along a single mode, time never decreases as distance from the origin
  grows; every band polygon is topologically valid; bands nest without overlap.
- **Calibration holdout** — MAE on the 20% held-out flight sample stays within a
  committed threshold.

## Risks

| Risk | Mitigation |
|---|---|
| Wikipedia route tables are uneven in coverage and freshness | Validate against the FR24 sample; publish measured coverage percentage; treat a coverage drop as a build failure |
| OSM rail speed tags are sparse in much of the world | Class-based fallbacks; validate against published journey times on known HSR corridors |
| Ground speed field is coarse and will look wrong somewhere | Documented as a terrain-traversal estimate, not a route; visible in the UI copy |
| Model drift as networks change | Calibration and route scrape are re-runnable; coverage report makes staleness visible |

## Future Iterations

Ordered by expected value:

1. Add a "fastest possible" layer toggle alongside "expected" (D7 alternative).
2. Expand the origin list past ~150 cities — pipeline re-run, no code change.
3. Real GTFS for rail in high-coverage countries: EU, Japan, Korea, US (D3 alternative).
4. Seasonal variation — summer vs. winter route networks differ substantially.
5. Departure-time-aware mode, if a redistributable schedule source becomes available.

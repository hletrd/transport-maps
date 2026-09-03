# Transport-Time Data Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the offline Python pipeline that turns open geodata into per-origin isochrone artifacts (PMTiles bands, hover array, route index) for the global transport-time globe.

**Architecture:** One unified multi-modal graph over H3 res-5 land cells plus airport, rail-station and ferry-terminal nodes. A single-source Dijkstra per origin city produces a per-cell time surface, which is dissolved into isochrone bands and emitted as static files. The pipeline is built as a walking skeleton first — air-only with uniform ground speed, producing a real viewable map by Task 6 — then each real mode is layered in.

**Tech Stack:** Python 3.14 (uv), h3-py 4.5, scipy.sparse.csgraph, shapely 2.1, polars, pyosmium, httpx, tippecanoe (PMTiles output), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md`

## Global Constraints

- Python `>=3.14`; all dependencies added with `uv add` (resolves latest) — never hand-pin a version.
- H3 resolution **5** for the solver grid (**548,557** land cells, measured); resolution **4** for the
  shipped hover array (**82,983** cells = 165,966 bytes as `uint16`).
- All times are **integer minutes**. `65535` is the unreachable sentinel and must fit `uint16`.
- Band edges in minutes, exactly: `(120, 240, 360, 540, 720, 1080, 1440, 2160, 2880, 4320)` — 10 edges, 11 bands.
- Time semantics are **"leave now"**: expected wait for any timetabled leg is `headway / 2`.
- **Licence firewall:** no FR24 or FlightAware record may ever reach `dist/`. Only fitted coefficients in `calibration.toml`.
- Every source module caches raw downloads under `data/cache/` and is re-runnable offline once cached.
- h3-py v4 names only: `latlng_to_cell`, `cell_to_latlng`, `cell_to_parent`, `grid_disk`, `geo_to_cells`, `cells_to_h3shape`, `h3shape_to_geo`, `great_circle_distance`. The v3 names raise `AttributeError`.

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | uv project, deps, pytest and ruff config |
| `calibration.toml` | Fitted coefficients. Committed, human-auditable, contains no records |
| `src/transport_maps/config.py` | Paths, H3 resolutions, band edges, sentinels |
| `src/transport_maps/cli.py` | argparse entry point for every stage |
| `src/transport_maps/sources/landmask.py` | Natural Earth land → H3 res-5 cell universe |
| `src/transport_maps/sources/airports.py` | OurAirports → scheduled-service airport table |
| `src/transport_maps/sources/routes.py` | Wikipedia "Airlines and destinations" → route network |
| `src/transport_maps/sources/osm.py` | Geofabrik download + `osmium tags-filter` |
| `src/transport_maps/graph/nodes.py` | Node registry: stable integer index per cell/airport/station/terminal |
| `src/transport_maps/graph/ground.py` | Per-cell ground speed field, hex↔hex edges |
| `src/transport_maps/graph/air.py` | Block-time model, airport→airport edges |
| `src/transport_maps/graph/rail.py` | Rail station→station edges |
| `src/transport_maps/graph/ferry.py` | Ferry terminal→terminal edges |
| `src/transport_maps/graph/transfers.py` | Mode-change penalties, expected-wait model |
| `src/transport_maps/graph/build.py` | Assembles the scipy CSR matrix |
| `src/transport_maps/solve/dijkstra.py` | Single-source solve per origin |
| `src/transport_maps/contour/bands.py` | Cells → dissolved band polygons |
| `src/transport_maps/emit/geojson.py` | Band GeoJSON (skeleton output) |
| `src/transport_maps/emit/tiles.py` | GeoJSON → tippecanoe → `.pmtiles` |
| `src/transport_maps/emit/hover.py` | res-4 `uint16` `.bin` |
| `src/transport_maps/emit/routes_json.py` | Node arrival times + predecessors |
| `src/transport_maps/emit/index.py` | `index.json` origin list |
| `src/transport_maps/calibrate/*` | FR24 / AeroAPI / Google clients and the regression fit |
| `tests/` | Mirrors `src/`, plus `tests/fixtures/` and `tests/test_golden.py` |

---

# Phase A — Walking Skeleton

Produces a real, viewable isochrone dataset for one origin using air travel plus a uniform ground speed. Everything after Phase A replaces a placeholder model with a real one, never restructures.

## Task 1: Project scaffold and config

**Files:**
- Create: `pyproject.toml`, `src/transport_maps/__init__.py`, `src/transport_maps/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: `config.SOLVE_RES: int`, `config.HOVER_RES: int`, `config.BAND_EDGES_MIN: tuple[int, ...]`, `config.UNREACHABLE: int`, `config.CACHE: Path`, `config.BUILD: Path`, `config.DIST: Path`, `config.ensure_dirs() -> None`

- [ ] **Step 1: Initialise the uv project and add dependencies**

```bash
uv init --package --name transport-maps --python 3.14
uv add h3 httpx polars numpy scipy shapely pyarrow selectolax
uv add --dev pytest ruff
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_config.py
from transport_maps import config


def test_band_edges_strictly_increasing():
    edges = config.BAND_EDGES_MIN
    assert len(edges) == 10
    assert all(a < b for a, b in zip(edges, edges[1:]))


def test_unreachable_sentinel_fits_uint16_and_exceeds_all_bands():
    assert config.UNREACHABLE == 65535
    assert config.UNREACHABLE > config.BAND_EDGES_MIN[-1]


def test_hover_resolution_is_coarser_than_solve_resolution():
    assert config.HOVER_RES < config.SOLVE_RES
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'transport_maps.config'`

- [ ] **Step 4: Write the implementation**

```python
# src/transport_maps/config.py
"""Project-wide constants and paths. No I/O beyond directory creation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CACHE = DATA / "cache"
BUILD = DATA / "build"
DIST = ROOT / "dist"

# H3 resolution for the solver grid: 589,157 land cells at ~253 km^2 each.
SOLVE_RES = 5
# H3 resolution for the shipped hover array: 84,164 land cells -> 168 KB as uint16.
HOVER_RES = 4

# Upper edge of each isochrone band, in minutes. The 11th band is open-ended.
BAND_EDGES_MIN: tuple[int, ...] = (120, 240, 360, 540, 720, 1080, 1440, 2160, 2880, 4320)

# uint16 sentinel for "no path exists".
UNREACHABLE = 65535


def ensure_dirs() -> None:
    for d in (CACHE, BUILD, DIST):
        d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 6: Add data directories to .gitignore**

```bash
printf 'data/\ndist/\n.venv/\n__pycache__/\n.pytest_cache/\n.ruff_cache/\n' > .gitignore
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src/ tests/
git commit -S -m "feat(config): 🎉 scaffold uv project and pipeline constants"
```

---

## Task 2: Land mask — the cell universe

Everything downstream indexes on this cell set, so it is built first and cached.

**Files:**
- Create: `src/transport_maps/sources/__init__.py`, `src/transport_maps/sources/landmask.py`
- Test: `tests/sources/test_landmask.py`

**Interfaces:**
- Consumes: `config.SOLVE_RES`, `config.CACHE`, `config.BUILD`
- Produces: `landmask.land_cells(res: int) -> list[str]` (H3 cell ids, cached to `data/build/land_cells_r{res}.parquet`)

- [ ] **Step 1: Write the failing test**

```python
# tests/sources/test_landmask.py
import h3
import pytest

from transport_maps import config
from transport_maps.sources import landmask


@pytest.fixture(scope="module")
def cells() -> set[str]:
    return set(landmask.land_cells(config.SOLVE_RES))


def test_cell_count_matches_measured_baseline(cells):
    # Measured: 548,557 cells from 6,657 non-Antarctic parts at contain="overlap".
    assert 500_000 < len(cells) < 620_000


@pytest.mark.parametrize("name,lat,lon", [
    ("Seoul", 37.5665, 126.9780),
    ("Sahara", 23.0, 10.0),
])
def test_continental_land_is_covered(cells, name, lat, lon):
    assert h3.latlng_to_cell(lat, lon, config.SOLVE_RES) in cells


@pytest.mark.parametrize("name,lat,lon", [
    ("Reykjavik", 64.1460, -21.9400),
    ("Male", 4.1755, 73.5093),
    ("Honolulu", 21.3150, -157.8580),
    ("Nauru", -0.5477, 166.9209),
])
def test_islands_and_coastlines_are_covered(cells, name, lat, lon):
    """Regression guard: contain="center" deletes every one of these."""
    assert h3.latlng_to_cell(lat, lon, config.SOLVE_RES) in cells


@pytest.mark.parametrize("name,lat,lon", [
    ("mid-Pacific", 0.0, -160.0),
    ("N.Atlantic", 45.0, -40.0),
])
def test_open_ocean_is_excluded(cells, name, lat, lon):
    assert h3.latlng_to_cell(lat, lon, config.SOLVE_RES) not in cells
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sources/test_landmask.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'transport_maps.sources.landmask'`

- [ ] **Step 3: Write the implementation**

Three findings from validating this against the real dataset — all three are load-bearing, do not simplify them away:

1. `ne_10m_land` is **11 features containing 6,837 polygon parts**. Passing the whole
   multipolygon to H3 raises `H3FailedError` at res 5. You must explode to single
   polygons and cellify each one.
2. Part index 0 is **Antarctica** (bounds reach -90 lat). It wraps the South Pole and
   H3's polyfill cannot handle it. Antarctica has no scheduled public transport and is
   on the spec's known-unreachable allowlist, so drop any part whose max latitude is
   below -60.
3. The default `contain='center'` drops any cell whose centre falls offshore, which
   erodes every coastline and deletes small island nations outright — Reykjavik and
   Male both come back as ocean. Use `h3shape_to_cells_experimental(..., contain='overlap')`
   so a cell is kept if it overlaps land at all.

```bash
uv add pyogrio
```

```python
# src/transport_maps/sources/landmask.py
"""Natural Earth land polygons -> the H3 cell universe."""

import h3
import httpx
import polars as pl
import pyogrio
import shapely

from transport_maps import config

LAND_URL = "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"

# Parts reaching below this latitude are Antarctic. H3 cannot polyfill a shape
# containing a pole, and Antarctica has no scheduled service, so it is excluded.
ANTARCTICA_MAX_LAT = -60.0

_MULTIPOLYGON_TYPE_ID = 6


def _download() -> "pathlib.Path":
    config.ensure_dirs()
    cached = config.CACHE / "ne_10m_land.zip"
    if not cached.exists():
        r = httpx.get(LAND_URL, follow_redirects=True, timeout=180)
        r.raise_for_status()
        cached.write_bytes(r.content)
    return cached


def _land_parts() -> list[shapely.Geometry]:
    """Single polygons covering land, excluding Antarctica."""
    path = _download().resolve()
    _meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    geom_column = next(c for c in table.schema.names if "geom" in c.lower())
    geoms = shapely.from_wkb(table.column(geom_column).to_pylist())

    parts: list[shapely.Geometry] = []
    for g in geoms:
        if shapely.get_type_id(g) == _MULTIPOLYGON_TYPE_ID:
            parts.extend(shapely.get_parts(g))
        else:
            parts.append(g)

    kept = [p for p in parts if p.bounds[3] > ANTARCTICA_MAX_LAT]
    if not kept:
        raise RuntimeError("no land parts parsed from Natural Earth archive")
    return kept


def land_cells(res: int) -> list[str]:
    """H3 cells at `res` overlapping land. Cached to parquet."""
    config.ensure_dirs()
    out = config.BUILD / f"land_cells_r{res}.parquet"
    if out.exists():
        return pl.read_parquet(out)["cell"].to_list()

    cells: set[str] = set()
    failures: list[tuple[float, ...]] = []
    for poly in _land_parts():
        try:
            shape = h3.geo_to_h3shape(poly)
            cells.update(h3.h3shape_to_cells_experimental(shape, res, contain="overlap"))
        except Exception:
            failures.append(poly.bounds)

    if failures:
        raise RuntimeError(f"{len(failures)} land parts failed to cellify: {failures[:5]}")

    ordered = sorted(cells)
    pl.DataFrame({"cell": ordered}).write_parquet(out)
    return ordered
```

Add `import pathlib` at the top for the return annotation, or drop the annotation.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sources/test_landmask.py -v`
Expected: 9 passed. First run downloads 3.3 MB and takes about **5 minutes** to cellify
(measured: 296.8 s for 6,657 parts at res 5); later runs read the parquet in under a second.
The run must report **0 failures** — any failure means an Antarctic part slipped through.

- [ ] **Step 5: Commit**

```bash
git add src/transport_maps/sources/ tests/sources/ pyproject.toml uv.lock
git commit -S -m "feat(sources): 🗺️ derive H3 land cell universe from Natural Earth"
```

---

## Task 3: Airport table

**Files:**
- Create: `src/transport_maps/sources/airports.py`
- Test: `tests/sources/test_airports.py`

**Interfaces:**
- Consumes: `config.CACHE`, `config.BUILD`
- Produces: `airports.scheduled_airports() -> pl.DataFrame` with columns `iata: str`, `name: str`, `lat: f64`, `lon: f64`, `size: str` (one of `large`, `medium`, `small`), `country: str`

- [ ] **Step 1: Write the failing test**

```python
# tests/sources/test_airports.py
import pytest

from transport_maps.sources import airports


@pytest.fixture(scope="module")
def df():
    return airports.scheduled_airports()


def test_required_columns_present(df):
    assert set(df.columns) >= {"iata", "name", "lat", "lon", "size", "country"}


def test_incheon_present_with_correct_coordinates(df):
    icn = df.filter(df["iata"] == "ICN")
    assert len(icn) == 1
    assert icn["lat"][0] == pytest.approx(37.46, abs=0.05)
    assert icn["lon"][0] == pytest.approx(126.44, abs=0.05)
    assert icn["size"][0] == "large"


def test_no_missing_coordinates_and_plausible_count(df):
    assert df["lat"].null_count() == 0
    assert df["lon"].null_count() == 0
    assert 2_000 < len(df) < 6_000


def test_iata_codes_are_unique_three_letter(df):
    assert df["iata"].n_unique() == len(df)
    assert df["iata"].str.len_chars().min() == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sources/test_airports.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/transport_maps/sources/airports.py
"""OurAirports -> airports with scheduled passenger service."""

import httpx
import polars as pl

from transport_maps import config

AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

SIZE_BY_TYPE = {
    "large_airport": "large",
    "medium_airport": "medium",
    "small_airport": "small",
}

REQUIRED_SOURCE_COLUMNS = {
    "type", "name", "latitude_deg", "longitude_deg",
    "iso_country", "scheduled_service", "iata_code",
}


def _download() -> bytes:
    config.ensure_dirs()
    cached = config.CACHE / "ourairports.csv"
    if not cached.exists():
        r = httpx.get(AIRPORTS_URL, follow_redirects=True, timeout=120)
        r.raise_for_status()
        cached.write_bytes(r.content)
    return cached.read_bytes()


def scheduled_airports() -> pl.DataFrame:
    out = config.BUILD / "airports.parquet"
    if out.exists():
        return pl.read_parquet(out)

    raw = pl.read_csv(_download(), infer_schema_length=10_000)
    missing = REQUIRED_SOURCE_COLUMNS - set(raw.columns)
    if missing:
        raise RuntimeError(f"OurAirports schema changed; missing columns: {sorted(missing)}")

    df = (
        raw.filter(
            (pl.col("scheduled_service") == "yes")
            & pl.col("type").is_in(list(SIZE_BY_TYPE))
            & pl.col("iata_code").is_not_null()
            & (pl.col("iata_code").str.len_chars() == 3)
        )
        .select(
            pl.col("iata_code").alias("iata"),
            pl.col("name"),
            pl.col("latitude_deg").alias("lat"),
            pl.col("longitude_deg").alias("lon"),
            pl.col("type").replace_strict(SIZE_BY_TYPE).alias("size"),
            pl.col("iso_country").alias("country"),
        )
        .drop_nulls(["lat", "lon"])
        .unique(subset=["iata"], keep="first")
        .sort("iata")
    )
    df.write_parquet(out)
    return df
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sources/test_airports.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/transport_maps/sources/airports.py tests/sources/test_airports.py
git commit -S -m "feat(sources): ✈️ load scheduled-service airports from OurAirports"
```

---

## Task 4: Flight block-time model

The first piece of `calibration.toml`. Ships with defensible defaults now; Task 13 refits them from real flights.

**Files:**
- Create: `calibration.toml`, `src/transport_maps/graph/__init__.py`, `src/transport_maps/graph/air.py`
- Test: `tests/graph/test_air.py`

**Interfaces:**
- Consumes: `airports.scheduled_airports()`
- Produces: `air.load_calibration() -> Calibration` (frozen dataclass), `air.block_time_min(distance_km: float, dep_size: str, arr_size: str, cal: Calibration) -> int`, `air.expected_wait_min(flights_per_week: float) -> int`

- [ ] **Step 1: Write the failing test**

Reference points come from published block times: ICN→NRT is 1257.7 km great-circle and blocks about 2 h 20 m gate to gate; ICN→LHR is roughly 8,880 km and blocks about 13 h.

```python
# tests/graph/test_air.py
import pytest

from transport_maps.graph import air


@pytest.fixture(scope="module")
def cal():
    return air.load_calibration()


def test_short_haul_block_time_matches_published(cal):
    # ICN -> NRT, 1257.7 km, both large airports.
    assert air.block_time_min(1257.7, "large", "large", cal) == pytest.approx(140, abs=25)


def test_long_haul_block_time_matches_published(cal):
    # ICN -> LHR, ~8880 km.
    assert air.block_time_min(8880.0, "large", "large", cal) == pytest.approx(780, abs=60)


def test_block_time_is_monotonic_in_distance(cal):
    times = [air.block_time_min(d, "large", "large", cal) for d in (500, 2000, 6000, 12000)]
    assert times == sorted(times)


def test_small_airports_have_less_taxi_overhead_than_large(cal):
    big = air.block_time_min(1000.0, "large", "large", cal)
    small = air.block_time_min(1000.0, "small", "small", cal)
    assert small < big


def test_expected_wait_is_half_the_headway():
    # 7 flights/week -> 24 h headway -> 12 h expected wait.
    assert air.expected_wait_min(7.0) == 720
    # 14 flights/week -> 12 h headway -> 6 h expected wait.
    assert air.expected_wait_min(14.0) == 360


def test_zero_frequency_is_unreachable():
    assert air.expected_wait_min(0.0) == air.NO_SERVICE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/graph/test_air.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `calibration.toml` with pre-calibration defaults**

```toml
# calibration.toml
#
# Fitted coefficients for the flight time model. This file contains NO flight
# records from any provider -- only regression outputs. See the licence firewall
# note in the design spec.
#
# Values below are pre-calibration defaults derived from published block times.
# Task 13 replaces them with a fit over sampled real flights.

[meta]
calibrated = false
sample_size = 0
holdout_mae_min = 0.0

[airborne]
# airborne_min = climb_descent_penalty_min + 60 * distance_km / cruise_kmh
climb_descent_penalty_min = 25.0
cruise_kmh = 800.0

[taxi_out_min]
large = 17.0
medium = 12.0
small = 8.0

[taxi_in_min]
large = 9.0
medium = 6.0
small = 4.0
```

- [ ] **Step 4: Write the implementation**

```python
# src/transport_maps/graph/air.py
"""Flight block-time and expected-wait models."""

import math
import tomllib
from dataclasses import dataclass

from transport_maps import config

MINUTES_PER_WEEK = 7 * 24 * 60
# Sentinel weight for a route with no service. Large but finite so Dijkstra
# never selects it while still keeping the matrix free of infinities.
NO_SERVICE = 10**7


@dataclass(frozen=True)
class Calibration:
    climb_descent_penalty_min: float
    cruise_kmh: float
    taxi_out_min: dict[str, float]
    taxi_in_min: dict[str, float]
    calibrated: bool


def load_calibration(path=None) -> Calibration:
    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    return Calibration(
        climb_descent_penalty_min=raw["airborne"]["climb_descent_penalty_min"],
        cruise_kmh=raw["airborne"]["cruise_kmh"],
        taxi_out_min=raw["taxi_out_min"],
        taxi_in_min=raw["taxi_in_min"],
        calibrated=raw["meta"]["calibrated"],
    )


def block_time_min(distance_km: float, dep_size: str, arr_size: str, cal: Calibration) -> int:
    """Gate-to-gate time in whole minutes."""
    airborne = cal.climb_descent_penalty_min + 60.0 * distance_km / cal.cruise_kmh
    total = cal.taxi_out_min[dep_size] + airborne + cal.taxi_in_min[arr_size]
    return int(round(total))


def expected_wait_min(flights_per_week: float) -> int:
    """"Leave now" semantics: expected wait is half the headway."""
    if flights_per_week <= 0:
        return NO_SERVICE
    headway = MINUTES_PER_WEEK / flights_per_week
    return int(round(headway / 2.0))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/graph/test_air.py -v`
Expected: 6 passed

Sanity check the two anchors by hand: ICN→NRT gives `17 + (25 + 60*1257.7/800) + 9 = 145` min; ICN→LHR gives `17 + (25 + 60*8880/800) + 9 = 717` min.

- [ ] **Step 6: Commit**

```bash
git add calibration.toml src/transport_maps/graph/ tests/graph/
git commit -S -m "feat(graph): 🛫 add flight block-time and expected-wait models"
```

---

## Task 5: Airline route network from Wikipedia

The only open, current, redistributable global route network. Destination cells in the
"Airlines and destinations" tables link to airport articles, so resolve those links
through Wikidata property `P238` (IATA airport code) rather than fuzzy-matching city
names — that is the difference between a reliable parse and a guessing game.

Wikipedia gives which pairs are flown but **not how often**. Frequency comes from a
fitted gravity model (`frequency_model` below), whose coefficients Task 13 regresses
against observed frequencies. No observed frequency is ever shipped.

**Files:**
- Create: `src/transport_maps/sources/wikidata.py`, `src/transport_maps/sources/routes.py`
- Modify: `calibration.toml` (add `[frequency]`)
- Modify: `src/transport_maps/graph/air.py` (add `frequency_model`)
- Test: `tests/sources/test_routes.py`, `tests/fixtures/icn_airlines_table.html`

**Interfaces:**
- Consumes: `airports.scheduled_airports()`
- Produces: `wikidata.iata_for_titles(titles: list[str]) -> dict[str, str]`, `routes.parse_destinations(html: str) -> list[str]` (wiki article titles), `routes.route_network() -> pl.DataFrame` with columns `src: str`, `dst: str`, `air.frequency_model(dep_size, arr_size, distance_km, cal) -> float`

- [ ] **Step 1: Write the failing test for the HTML parser**

Save a real fragment first so the test does not hit the network:

```bash
mkdir -p tests/fixtures
curl -sL "https://en.wikipedia.org/api/rest_v1/page/html/Incheon_International_Airport" \
  -o tests/fixtures/icn_airlines_table.html
```

```python
# tests/sources/test_routes.py
from pathlib import Path

from transport_maps.sources import routes

FIXTURE = Path(__file__).parent.parent / "fixtures" / "icn_airlines_table.html"


def test_parses_destination_article_titles_from_real_page():
    titles = routes.parse_destinations(FIXTURE.read_text(encoding="utf-8"))
    assert len(titles) > 50
    # Narita and Los Angeles are long-standing ICN destinations.
    assert any("Narita" in t for t in titles)
    assert any("Los_Angeles" in t or "Los Angeles" in t for t in titles)


def test_ignores_non_destination_links():
    titles = routes.parse_destinations(FIXTURE.read_text(encoding="utf-8"))
    # Citation, file and category links must not leak into the destination list.
    assert not any(t.startswith(("File:", "Category:", "Help:", "#cite")) for t in titles)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sources/test_routes.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the destination-table parser**

```python
# src/transport_maps/sources/routes.py
"""Wikipedia 'Airlines and destinations' tables -> airline route network."""

import re
import urllib.parse

import httpx
import polars as pl
from selectolax.parser import HTMLParser

from transport_maps import config
from transport_maps.sources import airports, wikidata

REST_HTML = "https://en.wikipedia.org/api/rest_v1/page/html/{title}"

_SKIP_PREFIXES = ("File:", "Category:", "Help:", "Template:", "Special:", "Portal:")
_HEADING_RE = re.compile(r"airlines?\s+and\s+destinations", re.I)


def parse_destinations(html: str) -> list[str]:
    """Wiki article titles linked from the Airlines and destinations table(s)."""
    tree = HTMLParser(html)
    titles: list[str] = []

    for table in tree.css("table"):
        if not _table_is_destinations(table):
            continue
        for anchor in table.css("a[href]"):
            href = anchor.attributes.get("href", "")
            if not href.startswith("./") and "/wiki/" not in href:
                continue
            title = href.split("/wiki/")[-1] if "/wiki/" in href else href[2:]
            title = urllib.parse.unquote(title.split("#")[0])
            if not title or title.startswith(_SKIP_PREFIXES):
                continue
            titles.append(title)

    # Preserve order, drop duplicates.
    return list(dict.fromkeys(titles))


def _table_is_destinations(table) -> bool:
    """True when the table sits under an 'Airlines and destinations' heading."""
    node = table
    for _ in range(40):
        node = node.prev
        while node is not None and node.tag == "-text":
            node = node.prev
        if node is None:
            return False
        if node.tag in {"h2", "h3", "section"} and _HEADING_RE.search(node.text() or ""):
            return True
        if node.tag in {"h2", "h3"}:
            return False
    return False
```

`selectolax` walks siblings with `.prev`; if the REST HTML wraps sections in `<section>`
elements, the loop finds the enclosing heading through the section's own text. Verify by
running the test — if `_table_is_destinations` returns `False` for every table, print
`[t.tag for t in tree.css('table')]` and the nearest preceding heading to see the real
structure, then adjust the traversal.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/sources/test_routes.py -v`
Expected: 2 passed

- [ ] **Step 5: Write the failing test for Wikidata IATA resolution**

```python
# append to tests/sources/test_routes.py
import pytest

from transport_maps.sources import wikidata


@pytest.mark.network
def test_resolves_article_titles_to_iata_codes():
    got = wikidata.iata_for_titles([
        "Narita International Airport",
        "Incheon International Airport",
        "Seoul",  # a city, not an airport -> must be absent
    ])
    assert got["Narita International Airport"] == "NRT"
    assert got["Incheon International Airport"] == "ICN"
    assert "Seoul" not in got
```

Register the marker so it can be deselected offline:

```toml
# append to pyproject.toml
[tool.pytest.ini_options]
markers = ["network: hits a live API"]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/sources/test_routes.py -m network -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'transport_maps.sources.wikidata'`

- [ ] **Step 7: Implement Wikidata resolution**

```python
# src/transport_maps/sources/wikidata.py
"""Resolve Wikipedia article titles to IATA codes via Wikidata property P238."""

import json

import httpx

from transport_maps import config

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
IATA_PROPERTY = "P238"
BATCH = 50
HEADERS = {"User-Agent": "transport-maps/0.1 (open-data isochrone build)"}


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _qids_for_titles(client: httpx.Client, titles: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for batch in _chunks(titles, BATCH):
        r = client.get(WIKIPEDIA_API, params={
            "action": "query", "format": "json", "redirects": "1",
            "prop": "pageprops", "ppprop": "wikibase_item",
            "titles": "|".join(batch),
        })
        r.raise_for_status()
        data = r.json().get("query", {})
        # Follow redirects back to the title we asked for.
        alias = {r_["to"]: r_["from"] for r_ in data.get("redirects", [])}
        for page in data.get("pages", {}).values():
            qid = page.get("pageprops", {}).get("wikibase_item")
            if not qid:
                continue
            title = page.get("title", "")
            out[alias.get(title, title)] = qid
    return out


def _iata_for_qids(client: httpx.Client, qids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for batch in _chunks(qids, BATCH):
        r = client.get(WIKIDATA_API, params={
            "action": "wbgetentities", "format": "json",
            "props": "claims", "ids": "|".join(batch),
        })
        r.raise_for_status()
        for qid, entity in r.json().get("entities", {}).items():
            claims = entity.get("claims", {}).get(IATA_PROPERTY, [])
            for claim in claims:
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(value, str) and len(value) == 3:
                    out[qid] = value.upper()
                    break
    return out


def iata_for_titles(titles: list[str]) -> dict[str, str]:
    """Article title -> IATA code, omitting titles that are not airports."""
    config.ensure_dirs()
    cache_path = config.CACHE / "wikidata_iata.json"
    cache: dict[str, str] = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    unknown = [t for t in titles if t not in cache]
    if unknown:
        with httpx.Client(timeout=60, headers=HEADERS, follow_redirects=True) as client:
            qids = _qids_for_titles(client, unknown)
            iata = _iata_for_qids(client, sorted(set(qids.values())))
        for title in unknown:
            qid = qids.get(title)
            cache[title] = iata.get(qid, "") if qid else ""
        cache_path.write_text(json.dumps(cache, sort_keys=True))

    return {t: cache[t] for t in titles if cache.get(t)}
```

Note the cache stores `""` for non-airports so they are never re-queried.

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/sources/test_routes.py -m network -v`
Expected: 1 passed

- [ ] **Step 9: Add the frequency model and its calibration defaults**

Append to `calibration.toml`:

```toml
[frequency]
# Gravity model for weekly frequency on a route that is known to exist:
#   flights_per_week = base * size_weight[dep] * size_weight[arr] * (distance_km ^ decay)
# Coefficients are refitted in Task 13 against observed frequencies. No observed
# frequency is ever written to dist/.
base = 42.0
decay = -0.35

[frequency.size_weight]
large = 1.0
medium = 0.55
small = 0.25
```

Append to `src/transport_maps/graph/air.py`:

```python
# extend the Calibration dataclass with these fields
#     frequency_base: float
#     frequency_decay: float
#     frequency_size_weight: dict[str, float]
# and read them in load_calibration() from raw["frequency"].

MIN_FLIGHTS_PER_WEEK = 0.5


def frequency_model(dep_size: str, arr_size: str, distance_km: float, cal: Calibration) -> float:
    """Estimated weekly frequency for a route known to exist."""
    w = cal.frequency_size_weight
    freq = (
        cal.frequency_base
        * w[dep_size]
        * w[arr_size]
        * max(distance_km, 1.0) ** cal.frequency_decay
    )
    return max(freq, MIN_FLIGHTS_PER_WEEK)
```

- [ ] **Step 10: Write and run the frequency model test**

```python
# append to tests/graph/test_air.py
def test_frequency_falls_with_distance(cal):
    near = air.frequency_model("large", "large", 1000.0, cal)
    far = air.frequency_model("large", "large", 10000.0, cal)
    assert near > far


def test_frequency_falls_with_airport_size(cal):
    big = air.frequency_model("large", "large", 2000.0, cal)
    small = air.frequency_model("small", "small", 2000.0, cal)
    assert big > small


def test_frequency_never_below_floor(cal):
    assert air.frequency_model("small", "small", 19000.0, cal) >= air.MIN_FLIGHTS_PER_WEEK
```

Run: `uv run pytest tests/graph/test_air.py -v`
Expected: 9 passed

- [ ] **Step 11: Assemble the full route network**

```python
# append to src/transport_maps/sources/routes.py
def _fetch_page_html(client: httpx.Client, title: str) -> str | None:
    r = client.get(REST_HTML.format(title=urllib.parse.quote(title, safe="")))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.text


def route_network() -> pl.DataFrame:
    """Directed airport pairs with scheduled service. Cached to parquet."""
    out = config.BUILD / "routes.parquet"
    if out.exists():
        return pl.read_parquet(out)

    apts = airports.scheduled_airports()
    valid = set(apts["iata"].to_list())
    titles_by_iata = _wikipedia_titles(apts)

    pairs: set[tuple[str, str]] = set()
    headers = {"User-Agent": "transport-maps/0.1 (open-data isochrone build)"}
    with httpx.Client(timeout=60, headers=headers, follow_redirects=True) as client:
        for iata, title in titles_by_iata.items():
            html = _fetch_page_html(client, title)
            if html is None:
                continue
            dest_titles = parse_destinations(html)
            for dest_iata in wikidata.iata_for_titles(dest_titles).values():
                if dest_iata in valid and dest_iata != iata:
                    pairs.add((iata, dest_iata))
                    pairs.add((dest_iata, iata))  # scheduled service is bidirectional

    if len(pairs) < 20_000:
        raise RuntimeError(f"route network implausibly small: {len(pairs)} pairs")

    df = pl.DataFrame(sorted(pairs), schema=["src", "dst"], orient="row")
    df.write_parquet(out)
    return df


def _wikipedia_titles(apts: pl.DataFrame) -> dict[str, str]:
    """IATA -> Wikipedia article title, from the OurAirports wikipedia_link column."""
    raw = pl.read_csv(config.CACHE / "ourairports.csv", infer_schema_length=10_000)
    linked = raw.filter(
        pl.col("iata_code").is_in(apts["iata"]) & pl.col("wikipedia_link").is_not_null()
    )
    titles: dict[str, str] = {}
    for iata, link in zip(linked["iata_code"], linked["wikipedia_link"]):
        if "/wiki/" in link:
            titles[iata] = urllib.parse.unquote(link.split("/wiki/")[-1].split("#")[0])
    return titles
```

- [ ] **Step 12: Run the network build and sanity-check it**

This crawls a few thousand Wikipedia pages. Expect 20–60 minutes on the first run; it is
cached afterwards. Run it once and check the result:

```bash
uv run python -c "
from transport_maps.sources import routes
df = routes.route_network()
print('pairs:', len(df))
print('ICN destinations:', len(df.filter(df['src']=='ICN')))
print('has ICN->NRT:', len(df.filter((df['src']=='ICN') & (df['dst']=='NRT'))) == 1)
"
```

Expected: tens of thousands of pairs, ICN with well over 100 destinations, `ICN->NRT` present.

- [ ] **Step 13: Commit**

```bash
git add src/transport_maps/sources/routes.py src/transport_maps/sources/wikidata.py \
        src/transport_maps/graph/air.py calibration.toml tests/ pyproject.toml uv.lock
git commit -S -m "feat(sources): 🌐 build airline route network from Wikipedia and Wikidata"
```

---

## Task 6: Node registry and graph assembly

**Files:**
- Create: `src/transport_maps/graph/nodes.py`, `src/transport_maps/graph/ground.py`, `src/transport_maps/graph/build.py`
- Test: `tests/graph/test_nodes.py`, `tests/graph/test_build.py`

**Interfaces:**
- Consumes: `landmask.land_cells`, `airports.scheduled_airports`, `routes.route_network`, `air.block_time_min`, `air.expected_wait_min`, `air.frequency_model`
- Produces: `nodes.NodeIndex` with `.cells: list[str]`, `.n_cells: int`, `.n: int`, `.cell_index(cell: str) -> int`, `.airport_index(iata: str) -> int`, `nodes.build_index() -> NodeIndex`, `ground.hex_edges(idx) -> Edges`, `build.build_graph(idx) -> scipy.sparse.csr_matrix`, where `Edges = tuple[np.ndarray, np.ndarray, np.ndarray]` of `(rows, cols, minutes)`

- [ ] **Step 1: Write the failing test for the node registry**

```python
# tests/graph/test_nodes.py
import pytest

from transport_maps.graph import nodes


@pytest.fixture(scope="module")
def idx():
    return nodes.build_index()


def test_cells_occupy_the_low_indices(idx):
    assert idx.cell_index(idx.cells[0]) == 0
    assert idx.cell_index(idx.cells[-1]) == idx.n_cells - 1


def test_airports_occupy_the_high_indices(idx):
    assert idx.airport_index("ICN") >= idx.n_cells
    assert idx.airport_index("ICN") < idx.n


def test_every_airport_maps_into_a_land_cell(idx):
    # Airports sit on land; the overlap containment mode guarantees coverage.
    assert idx.airport_cell_index("ICN") < idx.n_cells


def test_unknown_lookups_raise(idx):
    with pytest.raises(KeyError):
        idx.airport_index("ZZZ")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/graph/test_nodes.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the node registry**

```python
# src/transport_maps/graph/nodes.py
"""Stable integer indices for every node in the multi-modal graph.

Layout: land cells occupy [0, n_cells), then airports. Keeping cells first means
the per-cell time surface is simply `distances[:n_cells]`.
"""

from dataclasses import dataclass

import h3

from transport_maps import config
from transport_maps.sources import airports, landmask


@dataclass(frozen=True)
class NodeIndex:
    cells: list[str]
    airports: list[str]
    _cell_pos: dict[str, int]
    _airport_pos: dict[str, int]
    _airport_cell: dict[str, int]

    @property
    def n_cells(self) -> int:
        return len(self.cells)

    @property
    def n(self) -> int:
        return len(self.cells) + len(self.airports)

    def cell_index(self, cell: str) -> int:
        return self._cell_pos[cell]

    def airport_index(self, iata: str) -> int:
        return self._airport_pos[iata]

    def airport_cell_index(self, iata: str) -> int:
        return self._airport_cell[iata]


def build_index() -> NodeIndex:
    cells = landmask.land_cells(config.SOLVE_RES)
    cell_pos = {c: i for i, c in enumerate(cells)}

    apts = airports.scheduled_airports()
    codes: list[str] = []
    airport_cell: dict[str, int] = {}
    for iata, lat, lon in zip(apts["iata"], apts["lat"], apts["lon"]):
        cell = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
        pos = cell_pos.get(cell)
        if pos is None:
            # Airport on a cell the land mask missed; skip rather than corrupt the graph.
            continue
        codes.append(iata)
        airport_cell[iata] = pos

    airport_pos = {code: len(cells) + i for i, code in enumerate(codes)}
    return NodeIndex(cells, codes, cell_pos, airport_pos, airport_cell)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/graph/test_nodes.py -v`
Expected: 4 passed. If `test_every_airport_maps_into_a_land_cell` fails, the land mask
used `contain='center'` rather than `'overlap'` — go back and fix Task 2.

- [ ] **Step 5: Write the failing test for graph assembly**

```python
# tests/graph/test_build.py
import numpy as np
import pytest

from transport_maps.graph import build, nodes


@pytest.fixture(scope="module")
def idx():
    return nodes.build_index()


@pytest.fixture(scope="module")
def csr(idx):
    return build.build_graph(idx)


def test_matrix_is_square_and_matches_node_count(csr, idx):
    assert csr.shape == (idx.n, idx.n)


def test_all_weights_are_positive_and_finite(csr):
    data = csr.data
    assert np.isfinite(data).all()
    assert (data > 0).all()


def test_neighbouring_land_cells_are_connected(csr, idx):
    import h3
    seoul = h3.latlng_to_cell(37.5665, 126.9780, 5)
    u = idx.cell_index(seoul)
    assert csr[u].nnz >= 2


def test_incheon_reaches_narita_directly(csr, idx):
    u, v = idx.airport_index("ICN"), idx.airport_index("NRT")
    assert csr[u, v] > 0
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/graph/test_build.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 7: Implement ground edges**

Phase A uses a single uniform speed. Task 9 replaces `cell_speed_kmh` with the OSM-derived
field; nothing else in this module changes.

```python
# src/transport_maps/graph/ground.py
"""Hex-to-hex ground edges."""

import h3
import numpy as np

from transport_maps.graph.nodes import NodeIndex

# Phase A placeholder, replaced by the OSM speed field in Task 9.
UNIFORM_GROUND_KMH = 45.0


def cell_speed_kmh(idx: NodeIndex) -> np.ndarray:
    """Effective ground speed per cell, indexed by cell position."""
    return np.full(idx.n_cells, UNIFORM_GROUND_KMH, dtype=np.float64)


def hex_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Directed edges between adjacent land cells, weighted in minutes.

    Traversing from u into v is charged at v's speed, so slow terrain costs you
    on entry regardless of which side you approach from.
    """
    speeds = cell_speed_kmh(idx)
    centroids = np.array([h3.cell_to_latlng(c) for c in idx.cells], dtype=np.float64)

    rows: list[int] = []
    cols: list[int] = []
    for u, cell in enumerate(idx.cells):
        for neighbour in h3.grid_disk(cell, 1):
            if neighbour == cell:  # grid_disk includes the centre cell
                continue
            v = idx._cell_pos.get(neighbour)
            if v is not None:
                rows.append(u)
                cols.append(v)

    r = np.asarray(rows, dtype=np.int64)
    c = np.asarray(cols, dtype=np.int64)
    dist_km = _haversine_km(centroids[r], centroids[c])
    minutes = dist_km / speeds[c] * 60.0
    return r, c, minutes


def _haversine_km(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    lat1, lon1 = np.radians(a[:, 0]), np.radians(a[:, 1])
    lat2, lon2 = np.radians(b[:, 0]), np.radians(b[:, 1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(h))
```

- [ ] **Step 8: Implement graph assembly**

```python
# src/transport_maps/graph/build.py
"""Assemble the multi-modal graph as a scipy CSR matrix."""

import numpy as np
import scipy.sparse as sp

from transport_maps.graph import air, ground
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import airports, routes

# Phase A constants, split by domestic/international in Task 12.
AIRPORT_ACCESS_MIN = 75.0   # arrive, check in, clear security
AIRPORT_EGRESS_MIN = 45.0   # deplane, immigration, baggage


def _air_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cal = air.load_calibration()
    apts = airports.scheduled_airports()
    meta = {
        iata: (lat, lon, size)
        for iata, lat, lon, size in zip(apts["iata"], apts["lat"], apts["lon"], apts["size"])
    }
    known = set(idx.airports)

    rows: list[int] = []
    cols: list[int] = []
    minutes: list[float] = []
    net = routes.route_network()
    for src, dst in zip(net["src"], net["dst"]):
        if src not in known or dst not in known:
            continue
        (lat1, lon1, size1) = meta[src]
        (lat2, lon2, size2) = meta[dst]
        import h3
        d = h3.great_circle_distance((lat1, lon1), (lat2, lon2), unit="km")
        block = air.block_time_min(d, size1, size2, cal)
        wait = air.expected_wait_min(air.frequency_model(size1, size2, d, cal))
        rows.append(idx.airport_index(src))
        cols.append(idx.airport_index(dst))
        minutes.append(float(block + wait))

    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )


def _access_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows: list[int] = []
    cols: list[int] = []
    minutes: list[float] = []
    for iata in idx.airports:
        cell = idx.airport_cell_index(iata)
        node = idx.airport_index(iata)
        rows.append(cell); cols.append(node); minutes.append(AIRPORT_ACCESS_MIN)
        rows.append(node); cols.append(cell); minutes.append(AIRPORT_EGRESS_MIN)
    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )


def build_graph(idx: NodeIndex) -> sp.csr_matrix:
    parts = [ground.hex_edges(idx), _air_edges(idx), _access_edges(idx)]
    rows = np.concatenate([p[0] for p in parts])
    cols = np.concatenate([p[1] for p in parts])
    data = np.concatenate([p[2] for p in parts])

    if not np.isfinite(data).all() or (data <= 0).any():
        raise RuntimeError("graph contains non-positive or non-finite edge weights")

    coo = sp.coo_matrix((data, (rows, cols)), shape=(idx.n, idx.n))
    return coo.tocsr()
```

- [ ] **Step 9: Run test to verify it passes**

Run: `uv run pytest tests/graph/test_build.py -v`
Expected: 4 passed. Assembly takes 1–3 minutes and roughly 1 GB of RAM.

- [ ] **Step 10: Commit**

```bash
git add src/transport_maps/graph/ tests/graph/
git commit -S -m "feat(graph): 🕸️ assemble multi-modal graph with air and ground edges"
```

---

## Task 7: Solver, isochrone bands, and the first real map

The end of the walking skeleton. After this task you can open a real global isochrone
surface in a browser.

**Files:**
- Create: `src/transport_maps/solve/__init__.py`, `src/transport_maps/solve/dijkstra.py`, `src/transport_maps/contour/__init__.py`, `src/transport_maps/contour/bands.py`, `src/transport_maps/emit/__init__.py`, `src/transport_maps/emit/geojson.py`, `src/transport_maps/cli.py`
- Test: `tests/solve/test_dijkstra.py`, `tests/contour/test_bands.py`, `tests/test_golden.py`

**Interfaces:**
- Consumes: `build.build_graph`, `nodes.NodeIndex`
- Produces: `dijkstra.solve_from(csr, source: int) -> np.ndarray` (float minutes, `inf` where unreachable), `dijkstra.origin_node(idx, lat, lon) -> int`, `bands.band_of(minutes: float) -> int`, `bands.band_feature_collection(idx, cell_minutes: np.ndarray) -> dict`, `geojson.write_bands(path, fc) -> None`

- [ ] **Step 1: Write the failing test for the solver**

```python
# tests/solve/test_dijkstra.py
import numpy as np
import scipy.sparse as sp

from transport_maps.solve import dijkstra


def test_solves_a_tiny_hand_built_graph():
    #  0 --5--> 1 --2--> 2 ,  0 --20--> 2
    m = sp.csr_matrix(np.array([
        [0.0, 5.0, 20.0],
        [0.0, 0.0, 2.0],
        [0.0, 0.0, 0.0],
    ]))
    d = dijkstra.solve_from(m, 0)
    assert d[0] == 0.0
    assert d[1] == 5.0
    assert d[2] == 7.0  # via node 1, not the direct 20


def test_unreachable_nodes_are_infinite():
    m = sp.csr_matrix(np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]))
    d = dijkstra.solve_from(m, 0)
    assert np.isinf(d[2])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/solve/test_dijkstra.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the solver**

```python
# src/transport_maps/solve/dijkstra.py
"""Single-source shortest path over the multi-modal graph."""

import h3
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra as _dijkstra

from transport_maps import config
from transport_maps.graph.nodes import NodeIndex


def solve_from(csr: sp.csr_matrix, source: int) -> np.ndarray:
    """Minutes from `source` to every node. Unreachable nodes are inf."""
    return _dijkstra(csgraph=csr, directed=True, indices=source)


def origin_node(idx: NodeIndex, lat: float, lon: float) -> int:
    """Graph node for an origin city centre."""
    cell = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    try:
        return idx.cell_index(cell)
    except KeyError as exc:
        raise ValueError(f"origin ({lat}, {lon}) is not on a land cell") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/solve/test_dijkstra.py -v`
Expected: 2 passed

- [ ] **Step 5: Write the failing test for bands**

```python
# tests/contour/test_bands.py
import numpy as np

from transport_maps import config
from transport_maps.contour import bands


def test_band_boundaries_are_inclusive_of_the_lower_band():
    assert bands.band_of(0.0) == 0
    assert bands.band_of(119.0) == 0
    assert bands.band_of(120.0) == 0      # exactly 2h is still the first band
    assert bands.band_of(121.0) == 1


def test_beyond_the_last_edge_is_the_open_ended_band():
    last = len(config.BAND_EDGES_MIN)
    assert bands.band_of(config.BAND_EDGES_MIN[-1] + 1) == last
    assert bands.band_of(float("inf")) == bands.UNREACHABLE_BAND


def test_feature_collection_has_one_feature_per_occupied_band():
    class FakeIndex:
        cells = ["8530e08ffffffff", "8530e087fffffff"]
        n_cells = 2
    fc = bands.band_feature_collection(FakeIndex(), np.array([10.0, 5000.0]))
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2
    assert {f["properties"]["band"] for f in fc["features"]} == {0, 10}
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/contour/test_bands.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 7: Implement band dissolution**

`h3.cells_to_h3shape` merges adjacent cells into polygons and handles holes, so no
external dissolve step is needed.

```python
# src/transport_maps/contour/bands.py
"""Per-cell minutes -> dissolved isochrone band polygons."""

import bisect

import h3
import numpy as np

from transport_maps import config

UNREACHABLE_BAND = -1


def band_of(minutes: float) -> int:
    """Band index for a time. Values above the last edge fall in the open band."""
    if not np.isfinite(minutes):
        return UNREACHABLE_BAND
    return bisect.bisect_left(config.BAND_EDGES_MIN, minutes)


def band_feature_collection(idx, cell_minutes: np.ndarray) -> dict:
    """GeoJSON FeatureCollection, one MultiPolygon feature per occupied band."""
    if len(cell_minutes) < idx.n_cells:
        raise ValueError("cell_minutes shorter than the cell universe")

    by_band: dict[int, list[str]] = {}
    for pos, cell in enumerate(idx.cells):
        band = band_of(float(cell_minutes[pos]))
        if band == UNREACHABLE_BAND:
            continue
        by_band.setdefault(band, []).append(cell)

    features = []
    for band in sorted(by_band):
        shape = h3.cells_to_h3shape(by_band[band], tight=True)
        features.append({
            "type": "Feature",
            "properties": {
                "band": band,
                "max_minutes": (
                    config.BAND_EDGES_MIN[band]
                    if band < len(config.BAND_EDGES_MIN)
                    else None
                ),
            },
            "geometry": h3.h3shape_to_geo(shape),
        })

    return {"type": "FeatureCollection", "features": features}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/contour/test_bands.py -v`
Expected: 3 passed

- [ ] **Step 9: Write the GeoJSON writer and the CLI**

```python
# src/transport_maps/emit/geojson.py
import json
from pathlib import Path


def write_bands(path: Path, feature_collection: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feature_collection), encoding="utf-8")
```

```python
# src/transport_maps/cli.py
"""Pipeline entry point."""

import argparse

from transport_maps import config
from transport_maps.contour import bands
from transport_maps.emit import geojson
from transport_maps.graph import build, nodes
from transport_maps.solve import dijkstra


def main() -> None:
    parser = argparse.ArgumentParser(prog="transport-maps")
    sub = parser.add_subparsers(dest="command", required=True)

    solve = sub.add_parser("solve", help="solve one origin and write band GeoJSON")
    solve.add_argument("--lat", type=float, required=True)
    solve.add_argument("--lon", type=float, required=True)
    solve.add_argument("--name", required=True, help="origin slug, used for the filename")

    args = parser.parse_args()
    if args.command == "solve":
        idx = nodes.build_index()
        csr = build.build_graph(idx)
        source = dijkstra.origin_node(idx, args.lat, args.lon)
        minutes = dijkstra.solve_from(csr, source)
        fc = bands.band_feature_collection(idx, minutes[: idx.n_cells])
        out = config.DIST / f"{args.name}.bands.geojson"
        geojson.write_bands(out, fc)
        print(f"wrote {out} with {len(fc['features'])} bands")
```

Register the entry point in `pyproject.toml`:

```toml
[project.scripts]
transport-maps = "transport_maps.cli:main"
```

- [ ] **Step 10: Produce the first real map**

```bash
uv run transport-maps solve --lat 37.5665 --lon 126.9780 --name seoul
```

Expected: `dist/seoul.bands.geojson`, 8–11 band features. Open it at
[geojson.io](https://geojson.io) and confirm it looks like a plausible travel-time
surface centred on Korea. **This is the walking-skeleton milestone.**

- [ ] **Step 11: Write the golden test**

```python
# tests/test_golden.py
"""Door-to-door times for known city pairs, asserted within tolerance.

These are deliberately loose in Phase A (air plus uniform ground) and tighten as
real modes land. Update the tolerances, never the expectations, as the model improves.
"""

import h3
import numpy as np
import pytest

from transport_maps import config
from transport_maps.graph import build, nodes
from transport_maps.solve import dijkstra

SEOUL = (37.5665, 126.9780)
TOKYO = (35.6762, 139.6503)
LONDON = (51.5072, -0.1276)


@pytest.fixture(scope="module")
def solved():
    idx = nodes.build_index()
    csr = build.build_graph(idx)
    minutes = dijkstra.solve_from(csr, dijkstra.origin_node(idx, *SEOUL))
    return idx, minutes


def _minutes_at(idx, minutes, latlon) -> float:
    return float(minutes[idx.cell_index(h3.latlng_to_cell(*latlon, config.SOLVE_RES))])


def test_seoul_to_tokyo_is_a_half_day_or_less(solved):
    idx, minutes = solved
    assert 120 < _minutes_at(idx, minutes, TOKYO) < 720


def test_seoul_to_london_is_longer_than_seoul_to_tokyo(solved):
    idx, minutes = solved
    assert _minutes_at(idx, minutes, LONDON) > _minutes_at(idx, minutes, TOKYO)


def test_seoul_to_london_is_under_two_days(solved):
    idx, minutes = solved
    assert _minutes_at(idx, minutes, LONDON) < 2880


def test_the_vast_majority_of_land_is_reachable(solved):
    idx, minutes = solved
    reachable = np.isfinite(minutes[: idx.n_cells]).mean()
    assert reachable > 0.90
```

- [ ] **Step 12: Run the golden test**

Run: `uv run pytest tests/test_golden.py -v`
Expected: 4 passed

- [ ] **Step 13: Commit**

```bash
git add src/transport_maps/solve/ src/transport_maps/contour/ src/transport_maps/emit/ \
        src/transport_maps/cli.py pyproject.toml tests/
git commit -S -m "feat(solve): 🎯 solve isochrones and emit band GeoJSON"
```

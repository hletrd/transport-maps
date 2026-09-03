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

# H3 resolution for the solver grid: 548,557 land cells at ~253 km^2 each (measured).
SOLVE_RES = 5
# H3 resolution for the shipped hover array: 82,983 cells -> 165,966 bytes as uint16.
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
# data/origins.toml is committed, so ignore only the generated subdirectories.
printf 'data/cache/\ndata/build/\ndist/\n.venv/\n__pycache__/\n.pytest_cache/\n.ruff_cache/\n' > .gitignore
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
    # ICN -> LHR, ~8880 km. Published block is about 13 h (780 min); the
    # pre-calibration defaults yield 717, running slightly fast on long haul.
    # Task 12 refits this. Tolerance spans both figures deliberately.
    assert air.block_time_min(8880.0, "large", "large", cal) == pytest.approx(750, abs=80)


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

- [ ] **Step 3: Implement the destination parser**

Use the **Action API** (`/w/api.php`), not the REST API (`/api/rest_v1/`). This matters
more than it looks:

- The REST endpoint serves one page per request at roughly 1 MB each, and enforces a
  stricter per-client limiter. Crawling ~4,000 airports through it measured **4-5
  airports/minute** and tripped a 429 penalty (`x-envoy-ratelimited: true`).
- The Action API returns **50 pages per request**. Measured: 50 pages in **1.6 s** for
  0.19 MB, so the entire network is **80 requests, about 2 minutes**.

That is a ~50x reduction in requests and a ~400x reduction in wall-clock. Parse the
wikitext directly.

```python
# src/transport_maps/sources/routes.py
"""Wikipedia 'Airlines and destinations' sections -> airline route network."""

import re
import urllib.parse

import httpx
import polars as pl

from transport_maps import config
from transport_maps.sources import airports, wikidata

ACTION_API = "https://en.wikipedia.org/w/api.php"
TITLES_PER_REQUEST = 50
HEADERS = {"User-Agent": "transport-maps/0.1 (open-data isochrone build)"}

_SECTION_RE = re.compile(r"^==+\s*Airlines and destinations\s*==+\s*$", re.I | re.M)
# Cargo routes carry no passengers, so they must not become graph edges.
_CARGO_RE = re.compile(r"^===+\s*(Cargo|Freight)[^=]*===+\s*$", re.I | re.M)
_NEXT_TOP_HEADING_RE = re.compile(r"^==[^=]", re.M)
_LINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]*)?\]\]")
_SKIP_PREFIXES = (
    "File:", "Category:", "Help:", "Template:", "Special:", "Portal:", "Wikipedia:",
    "Image:",
)


def parse_destinations(wikitext: str) -> list[str]:
    """Wiki article titles linked from the Airlines and destinations section."""
    match = _SECTION_RE.search(wikitext)
    if match is None:
        return []

    body = wikitext[match.end():]
    nxt = _NEXT_TOP_HEADING_RE.search(body)
    if nxt is not None:
        body = body[: nxt.start()]

    cargo = _CARGO_RE.search(body)
    if cargo is not None:
        body = body[: cargo.start()]

    titles: list[str] = []
    for raw in _LINK_RE.findall(body):
        title = raw.strip().replace(" ", "_")
        if not title or title.startswith(_SKIP_PREFIXES):
            continue
        titles.append(title)

    return list(dict.fromkeys(titles))


def _fetch_wikitext(client: httpx.Client, titles: list[str]) -> dict[str, str]:
    """Article title -> wikitext, up to TITLES_PER_REQUEST titles per call."""
    r = client.get(ACTION_API, params={
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "revisions", "rvprop": "content", "rvslots": "main",
        "titles": "|".join(titles),
    })
    r.raise_for_status()
    data = r.json().get("query", {})
    alias = {n["to"]: n["from"] for n in data.get("normalized", [])}
    alias.update({n["to"]: n["from"] for n in data.get("redirects", [])})

    out: dict[str, str] = {}
    for page in data.get("pages", []):
        revisions = page.get("revisions")
        if not revisions:
            continue
        title = page.get("title", "")
        out[alias.get(title, title)] = revisions[0]["slots"]["main"]["content"]
    return out
```

Verified against the live API: Incheon yields 191 airport-like links, Keflavik 98,
Male (Velana) 58, Gimpo 11, with cargo subsections excluded. Across an arbitrary batch of
50 mostly-small airports, 39 had a destinations section — the rest are airports too small
to have one, which is expected, not a parse failure.

Airline links (`Air_Canada`, `9_Air`) and city links (`Tokyo`) come through the regex too.
They are filtered out at the Wikidata stage, because only airports carry Wikidata
property P238.

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
# Fitted to two real-world anchors: ICN-NRT (1,258 km) runs about 120 flights/week
# and ICN-LHR (8,880 km) about 14. Sanity across the range: Seoul-Jeju (450 km,
# the world's busiest route) -> 362/week vs ~500 real; a 13,800 km ultra-long-haul
# -> 8.4/week vs ~7 real. Transatlantic trunks like LHR-JFK come out low (23 vs ~90)
# because they are frequency outliers for their distance; Task 12 refits from data.
#
# Do NOT use a shallow decay here. An earlier draft used base=42, decay=-0.35, which
# produced 1.5-5 flights/week for EVERY route on Earth -- Seoul-Jeju at 5/week -- so
# every flight cost 17-56 hours of expected waiting and the whole map was nonsense.
base = 300000.0
decay = -1.10

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

    def try_cell_index(self, cell: str) -> int | None:
        """Position of `cell`, or None when it is not a land cell."""
        return self._cell_pos.get(cell)

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
            v = idx.try_cell_index(neighbour)
            if v is not None:
                rows.append(u)
                cols.append(v)

    r = np.asarray(rows, dtype=np.int64)
    c = np.asarray(cols, dtype=np.int64)
    dist_km = haversine_km(centroids[r], centroids[c])
    minutes = dist_km / speeds[c] * 60.0
    return r, c, minutes


def haversine_km(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Great-circle distance between arrays of (lat, lon). Public: rail and ferry use it."""
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
from shapely import affinity
from shapely.geometry import Polygon, box, shape
from shapely.ops import unary_union

from transport_maps import config

UNREACHABLE_BAND = -1


def band_of(minutes: float) -> int:
    """Band index for a time. Values above the last edge fall in the open band."""
    if not np.isfinite(minutes):
        return UNREACHABLE_BAND
    return bisect.bisect_left(config.BAND_EDGES_MIN, minutes)


ANTIMERIDIAN_SPAN_DEG = 180.0


def _crosses_antimeridian(cell: str) -> bool:
    lons = [lon for _lat, lon in h3.cell_to_boundary(cell)]
    return max(lons) - min(lons) > ANTIMERIDIAN_SPAN_DEG


def _split_at_antimeridian(cell: str):
    """A cell straddling +/-180 as one or two polygons inside [-180, 180].

    In planar lat/lon a wrapping cell's ring reads as spanning the globe
    backwards: measured on a real Fiji-area cell, the naive polygon is INVALID
    with area 27.37 deg^2 against a true 0.0202. With 26 such cells in Seoul's
    band 9 that injected roughly 711 deg^2 of phantom area, which is what made
    bands appear to overlap. Shift negative longitudes east into a continuous
    frame, clip either side of 180, then translate the eastern piece back.
    """
    boundary = h3.cell_to_boundary(cell)
    lats = [lat for lat, _lon in boundary]
    unwrapped = [lon + 360.0 if lon < 0 else lon for lon in boundary and
                 [lon for _lat, lon in boundary]]
    ring = Polygon(zip(unwrapped, lats))
    left = ring.intersection(box(-180.0, -90.0, 180.0, 90.0))
    right = affinity.translate(
        ring.intersection(box(180.0, -90.0, 540.0, 90.0)), xoff=-360.0
    )
    return [part for part in (left, right) if not part.is_empty]


def _dissolve(cells: list[str]):
    """Dissolve one band's cells, handling the antimeridian.

    h3.cells_to_h3shape is EXACT and fast even at scale -- measured against a
    per-cell shapely union on Seoul's bands 7, 8 and 9 (202,482 / 111,742 /
    69,732 cells, hundreds of disconnected components each), the symmetric
    difference was 0.0000 in all three once wrapping cells were removed. Do NOT
    replace it with a per-cell union: that is far slower AND still wrong at the
    antimeridian.
    """
    normal = [c for c in cells if not _crosses_antimeridian(c)]
    wrapping = [c for c in cells if _crosses_antimeridian(c)]

    geoms = []
    if normal:
        geoms.append(shape(h3.h3shape_to_geo(h3.cells_to_h3shape(normal, tight=True))))
    for cell in wrapping:
        geoms.extend(_split_at_antimeridian(cell))

    return unary_union(geoms) if geoms else None


def band_feature_collection(idx, cell_minutes: np.ndarray) -> dict:
    """GeoJSON FeatureCollection, one polygon feature per occupied band.

    h3.cells_to_h3shape returns a Polygon for contiguous cells and a MultiPolygon
    when a band is split across regions; both serialise correctly.
    """
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
        shape = _dissolve(by_band[band])
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
            "geometry": shapely.geometry.mapping(geometry),
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

---

# Phase B — Real Transport Modes

Each task here replaces a Phase A placeholder with a real model. The graph assembly and
solver do not change shape; only the edges get better.

## Task 8: Ground speed field from GRIP4 road density

Replaces the uniform 45 km/h with a per-cell speed. GRIP4's 5-arcmin grid (~8×8 km) is
almost exactly an H3 res-5 cell, so a centroid sample is the right level of detail — no
interpolation needed.

**Files:**
- Create: `src/transport_maps/sources/roads.py`
- Modify: `src/transport_maps/graph/ground.py` (replace `cell_speed_kmh`)
- Test: `tests/sources/test_roads.py`, `tests/graph/test_ground.py`

**Interfaces:**
- Consumes: `nodes.NodeIndex`
- Produces: `roads.road_class_grid() -> np.ndarray` (shape `(2160, 4320)`, `uint8`, values 0–5 where 0 is roadless and 1 is the highest grade), `roads.sample_class(lats, lons) -> np.ndarray`, `ground.cell_speed_kmh(idx) -> np.ndarray` (unchanged signature)

- [ ] **Step 1: Confirm the GRIP4 download works**

GRIP4 is CC-0 and served as direct downloads — no registration, no form. Verified live:

```bash
curl -sIL https://dataportaal.pbl.nl/downloads/GRIP4/GRIP4_density_tp1.zip | grep -i '^HTTP\|content-length'
# HTTP/2 200, content-length: 2057941
```

Each `GRIP4_density_tp{N}.zip` is roughly 2 MB and contains `grip4_tp{N}_dens_m_km2.asc`
(about 47 MB uncompressed) plus a land-area grid and a ReadMe. Fetching all five types is
a normal pipeline step; do NOT make it a manual instruction.

Measured properties of the rasters, confirmed against the real files:

| Property | Value |
|---|---|
| Shape | `(2160, 4320)` — 5 arcmin global |
| Bounds | -180, -90 to 180, 90 |
| dtype | `int32` |
| NoData | `-9999.0` |
| Units | **metres of road per km² per cell** (from the ReadMe) |
| Type 1 (highways) non-zero cells | 68,489 of 9,331,200 |
| Median density where present | 140 m/km² |

`DENSITY_THRESHOLD = 1.0` keeps 68,240 of the 68,489 non-zero highway cells (99.6%), and
NoData (-9999) falls below it automatically, so no separate NoData mask is needed.

- [ ] **Step 2: Write the failing test**

```python
# tests/sources/test_roads.py
import numpy as np
import pytest

from transport_maps.sources import roads


@pytest.fixture(scope="module")
def grid():
    return roads.road_class_grid()


def test_grid_shape_is_five_arcmin_global(grid):
    assert grid.shape == (2160, 4320)
    assert grid.dtype == np.uint8


def test_open_ocean_has_no_roads(grid):
    assert roads.sample_class(np.array([0.0]), np.array([-160.0]))[0] == 0


def test_motorway_corridors_are_class_one(grid):
    """Points on real expressways. Measured tp1 density: 243, 666, 494 m/km2."""
    # Yangjae IC on the Gyeongbu Expressway; Los Angeles; Essen in the Ruhr.
    lats = np.array([37.4837, 34.0522, 51.5136])
    lons = np.array([127.0325, -118.2437, 7.4653])
    assert (roads.sample_class(lats, lons) == 1).all()


def test_dense_urban_core_without_a_motorway_is_still_well_roaded(grid):
    """Seoul's historic core has no motorway in its 5-arcmin cell but is dense.

    Measured: tp1 = 0, tp2 = 1573 m/km2. Seoul's expressways ring the old city
    rather than cross it, so this cell is class 2, not class 1. Asserting class 1
    here would be a false premise about how road networks are laid out, not a
    threshold problem -- do not "fix" it by lowering DENSITY_THRESHOLD.
    """
    assert roads.sample_class(np.array([37.5665]), np.array([126.9780]))[0] == 2


def test_remote_interior_is_lower_grade_than_a_capital(grid):
    remote = roads.sample_class(np.array([-24.0]), np.array([126.0]))[0]  # W. Australia
    seoul = roads.sample_class(np.array([37.5665]), np.array([126.9780]))[0]
    assert remote > seoul or remote == 0  # higher number = lower grade
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/sources/test_roads.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement the road grid**

```bash
uv add rasterio
```

```python
# src/transport_maps/sources/roads.py
"""GRIP4 road-density rasters -> per-location road class.

GRIP4 ships one density grid per road type at 5 arcmin. We reduce them to a single
"best grade present" grid: 1 = highway, 5 = local road, 0 = roadless.
"""

import io
import zipfile
from pathlib import Path

import h3
import httpx
import numpy as np
import rasterio

from transport_maps import config
from transport_maps.sources._utils import _atomic_write

GRIP4_URL = "https://dataportaal.pbl.nl/downloads/GRIP4/GRIP4_density_tp{n}.zip"
GRID_ROWS, GRID_COLS = 2160, 4320  # 5 arcmin global; verified against the real rasters
N_TYPES = 5
# Density below this is noise rather than usable road.
DENSITY_THRESHOLD = 1.0

_grid_cache: np.ndarray | None = None


def _ensure_raster(road_type: int) -> Path:
    """Download and extract one GRIP4 density raster, cached under config.CACHE."""
    target = config.CACHE / "grip4" / f"grip4_tp{road_type}_dens_m_km2.asc"
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    url = GRIP4_URL.format(n=road_type)
    r = httpx.get(url, follow_redirects=True, timeout=300)
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        member = next(
            (n for n in z.namelist() if n.lower().endswith(f"tp{road_type}_dens_m_km2.asc")),
            None,
        )
        if member is None:
            raise RuntimeError(f"{url} has no tp{road_type} density raster: {z.namelist()}")
        _atomic_write(target, lambda tmp: tmp.write_bytes(z.read(member)))

    return target


def road_class_grid() -> np.ndarray:
    """Best road grade per 5-arcmin cell. 0 = roadless, 1 = highway .. 5 = local."""
    global _grid_cache
    if _grid_cache is not None:
        return _grid_cache

    cached = config.BUILD / "road_class_grid.npy"
    if cached.exists():
        _grid_cache = np.load(cached)
        return _grid_cache

    best = np.zeros((GRID_ROWS, GRID_COLS), dtype=np.uint8)
    for road_type in range(N_TYPES, 0, -1):  # worst grade first, best overwrites
        path = _ensure_raster(road_type)
        with rasterio.open(path) as src:
            band = src.read(1)
        if band.shape != (GRID_ROWS, GRID_COLS):
            raise RuntimeError(f"{path} has shape {band.shape}, expected {(GRID_ROWS, GRID_COLS)}")
        best[band >= DENSITY_THRESHOLD] = road_type

    config.ensure_dirs()
    np.save(cached, best)
    _grid_cache = best
    return best


def cell_class(cells: list[str]) -> np.ndarray:
    """Best road grade anywhere inside each H3 cell's footprint.

    An H3 res-5 cell is about 253 km2; a GRIP4 cell is about 86 km2 at the
    equator and 43 km2 at 60 degrees, so each H3 cell spans 3-6 GRIP4 cells.
    Sampling only the centroid therefore under-reports road access badly.
    Measured over 6,000 random land cells:

        roadless      centroid 51.5%  ->  footprint 29.3%
        mean speed    23.9 km/h       ->  36.8 km/h
        cells improved by footprint   ->  39.4%
        cells made worse              ->  0.00% (a superset cannot be worse)

    The spec says "the highest-grade road class present in it" -- present in the
    cell, not at its centre. Full pass over 548,557 cells takes about 2 seconds.
    """
    grid = road_class_grid()
    out = np.zeros(len(cells), dtype=np.uint8)
    for i, cell in enumerate(cells):
        boundary = h3.cell_to_boundary(cell)
        lats = [p[0] for p in boundary]
        lons = [p[1] for p in boundary]
        if max(lons) - min(lons) > 180.0:
            # Antimeridian wrap makes the bounding box meaningless; use the centroid.
            lat, lon = h3.cell_to_latlng(cell)
            out[i] = sample_class(np.array([lat]), np.array([lon]))[0]
            continue
        r0 = _row_of(max(lats))
        r1 = _row_of(min(lats))
        c0 = _col_of(min(lons))
        c1 = _col_of(max(lons))
        window = grid[r0 : r1 + 1, c0 : c1 + 1]
        present = window[window > 0]
        # Lower class number = better grade; 0 means no road of any type.
        out[i] = int(present.min()) if present.size else 0
    return out


def _row_of(lat: float) -> int:
    return int(np.clip((90.0 - lat) * GRID_ROWS / 180.0, 0, GRID_ROWS - 1))


def _col_of(lon: float) -> int:
    return int(np.clip((lon + 180.0) * GRID_COLS / 360.0, 0, GRID_COLS - 1))


def sample_class(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Road class at each coordinate. Vectorised nearest-cell lookup."""
    grid = road_class_grid()
    rows = np.clip(((90.0 - lats) * GRID_ROWS / 180.0).astype(np.int64), 0, GRID_ROWS - 1)
    cols = np.clip(((lons + 180.0) * GRID_COLS / 360.0).astype(np.int64), 0, GRID_COLS - 1)
    return grid[rows, cols]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/sources/test_roads.py -v`
Expected: 4 passed

- [ ] **Step 6: Wire the speed field into the ground module**

Replace `cell_speed_kmh` in `src/transport_maps/graph/ground.py`. Delete
`UNIFORM_GROUND_KMH`; nothing else in the module changes.

```python
# src/transport_maps/graph/ground.py  (replace cell_speed_kmh)
import h3
import numpy as np

from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import roads

# Index by GRIP road class: 0 = roadless, 1 = highway .. 5 = local road.
SPEED_BY_ROAD_CLASS_KMH = np.array([5.0, 85.0, 60.0, 40.0, 30.0, 25.0], dtype=np.float64)


def cell_speed_kmh(idx: NodeIndex) -> np.ndarray:
    # Footprint aggregation, NOT centroid sampling: an H3 res-5 cell spans 3-6
    # GRIP4 cells, and sampling the centre alone reports 51.5% of land roadless
    # against a true 29.3%, depressing mean ground speed from 36.8 to 23.9 km/h.
    classes = roads.cell_class(idx.cells)
    return SPEED_BY_ROAD_CLASS_KMH[classes]
```

- [ ] **Step 7: Test the speed field**

```python
# tests/graph/test_ground.py
import numpy as np
import pytest

from transport_maps.graph import ground, nodes


@pytest.fixture(scope="module")
def idx():
    return nodes.build_index()


def test_every_cell_has_a_positive_speed(idx):
    speeds = ground.cell_speed_kmh(idx)
    assert len(speeds) == idx.n_cells
    assert (speeds > 0).all()


def test_speeds_span_the_full_range(idx):
    speeds = ground.cell_speed_kmh(idx)
    assert speeds.min() == ground.SPEED_BY_ROAD_CLASS_KMH.min()
    assert speeds.max() == ground.SPEED_BY_ROAD_CLASS_KMH.max()


def test_roadless_terrain_is_slower_than_motorway_terrain(idx):
    import h3
    speeds = ground.cell_speed_kmh(idx)
    sahara = idx.cell_index(h3.latlng_to_cell(23.0, 10.0, 5))
    seoul = idx.cell_index(h3.latlng_to_cell(37.5665, 126.9780, 5))
    assert speeds[sahara] < speeds[seoul]
```

Run: `uv run pytest tests/graph/test_ground.py tests/test_golden.py -v`
Expected: all pass. The golden times will shift; if `test_seoul_to_tokyo_is_a_half_day_or_less`
now fails, the speed field is wired backwards — check that class 1 maps to 85 km/h.

- [ ] **Step 8: Commit**

```bash
git add src/transport_maps/sources/roads.py src/transport_maps/graph/ground.py tests/ pyproject.toml uv.lock
git commit -S -m "feat(graph): 🛣️ derive per-cell ground speed from GRIP4 road density"
```

---

## Task 9: Rail network from OSM route relations

OSM `type=route, route=train` relations carry an **ordered list of stops**, which gives
station-to-station edges directly. Walking way geometry to infer station order is the
trap here — do not do it.

**Files:**
- Create: `src/transport_maps/sources/osm.py`, `src/transport_maps/graph/rail.py`
- Modify: `src/transport_maps/graph/nodes.py` (add station nodes), `src/transport_maps/graph/build.py` (add rail edges)
- Test: `tests/sources/test_osm.py`, `tests/graph/test_rail.py`

**Interfaces:**
- Consumes: `nodes.NodeIndex`
- Produces: `osm.rail_routes() -> pl.DataFrame` with columns `route_id: i64`, `seq: i64`, `stop_id: i64`, `lat: f64`, `lon: f64`, `name: str`, `highspeed: bool`; `rail.rail_edges(idx) -> Edges`; `NodeIndex.station_index(stop_id: int) -> int`

- [ ] **Step 1: Download and filter the OSM extracts**

Full continent PBFs are the only source with the `usage` and `highspeed` tags intact.
Filter each one down before parsing — the filtered output is a few hundred MB total
versus roughly 100 GB of input.

```bash
brew install osmium-tool
mkdir -p data/cache/osm

for region in africa asia australia-oceania central-america europe north-america south-america; do
  test -f "data/cache/osm/${region}.osm.pbf" || \
    curl -L --retry 3 -o "data/cache/osm/${region}.osm.pbf" \
      "https://download.geofabrik.de/${region}-latest.osm.pbf"
  test -f "data/cache/osm/${region}-rail.osm.pbf" || \
    osmium tags-filter "data/cache/osm/${region}.osm.pbf" \
      r/type=route,route=train \
      w/railway=rail \
      n/railway=station,halt \
      w/route=ferry n/amenity=ferry_terminal \
      -o "data/cache/osm/${region}-rail.osm.pbf"
done
```

This downloads roughly 100 GB and takes several hours. It is resumable — each `test -f`
skips work already done. Delete the unfiltered PBFs afterwards to reclaim the space.

- [ ] **Step 2: Write the failing test**

```python
# tests/sources/test_osm.py
import pytest

from transport_maps.sources import osm


@pytest.fixture(scope="module")
def df():
    return osm.rail_routes()


def test_has_required_columns(df):
    assert set(df.columns) >= {"route_id", "seq", "stop_id", "lat", "lon", "name", "highspeed"}


def test_stop_sequences_are_contiguous_from_zero(df):
    first = df.filter(df["route_id"] == df["route_id"][0]).sort("seq")
    assert first["seq"].to_list() == list(range(len(first)))


def test_finds_a_plausible_number_of_routes_and_stops(df):
    assert df["route_id"].n_unique() > 2_000
    assert len(df) > 50_000


def test_some_routes_are_flagged_high_speed(df):
    assert df["highspeed"].any()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/sources/test_osm.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement the OSM reader**

Two passes are required: ways first to learn which are high-speed, then relations to read
stop order.

```bash
uv add osmium
```

```python
# src/transport_maps/sources/osm.py
"""OSM route relations -> ordered rail and ferry stop sequences."""

import osmium
import polars as pl

from transport_maps import config

REGIONS = (
    "africa", "asia", "australia-oceania", "central-america",
    "europe", "north-america", "south-america",
)


class _HighspeedWays(osmium.SimpleHandler):
    """Pass 1: collect ids of ways tagged highspeed=yes."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[int] = set()

    def way(self, w) -> None:
        if w.tags.get("highspeed") == "yes":
            self.ids.add(w.id)


class _RailRoutes(osmium.SimpleHandler):
    """Pass 2: read ordered stops from route=train relations."""

    def __init__(self, highspeed_ways: set[int]) -> None:
        super().__init__()
        self.highspeed_ways = highspeed_ways
        self.rows: list[dict] = []
        self._locations: dict[int, tuple[float, float]] = {}

    def node(self, n) -> None:
        if n.tags.get("railway") in {"station", "halt"}:
            self._locations[n.id] = (n.location.lat, n.location.lon)

    def relation(self, r) -> None:
        if r.tags.get("type") != "route" or r.tags.get("route") != "train":
            return
        high = any(m.type == "w" and m.ref in self.highspeed_ways for m in r.members)
        seq = 0
        for member in r.members:
            if member.type != "n" or member.role not in {"stop", "platform", ""}:
                continue
            loc = self._locations.get(member.ref)
            if loc is None:
                continue
            self.rows.append({
                "route_id": r.id, "seq": seq, "stop_id": member.ref,
                "lat": loc[0], "lon": loc[1],
                "name": r.tags.get("name", ""), "highspeed": high,
            })
            seq += 1


def rail_routes() -> pl.DataFrame:
    """Ordered rail stops per route. Cached to parquet."""
    out = config.BUILD / "rail_routes.parquet"
    if out.exists():
        return pl.read_parquet(out)

    rows: list[dict] = []
    for region in REGIONS:
        path = config.CACHE / "osm" / f"{region}-rail.osm.pbf"
        if not path.exists():
            raise FileNotFoundError(f"missing {path}; run Task 9 Step 1 first")

        ways = _HighspeedWays()
        ways.apply_file(str(path))
        routes = _RailRoutes(ways.ids)
        routes.apply_file(str(path), locations=False)
        rows.extend(routes.rows)

    # Routes with a single stop carry no edge.
    df = pl.DataFrame(rows)
    counts = df.group_by("route_id").len().filter(pl.col("len") >= 2)
    df = df.filter(pl.col("route_id").is_in(counts["route_id"]))

    config.ensure_dirs()
    df.write_parquet(out)
    return df
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/sources/test_osm.py -v`
Expected: 4 passed. If `test_some_routes_are_flagged_high_speed` fails, the `tags-filter`
in Step 1 dropped the `highspeed` ways — re-run it including `w/railway=rail`.

- [ ] **Step 6: Add station nodes to the registry**

Extend `NodeIndex` with a third block after airports. Cells stay at `[0, n_cells)` so the
time-surface slice is unaffected.

```python
# src/transport_maps/graph/nodes.py  (additions)
#   dataclass fields:  stations: list[int]
#                      _station_pos: dict[int, int]
#                      _station_cell: dict[int, int]
#
#   @property n  ->  len(cells) + len(airports) + len(stations)
#
#   def station_index(self, stop_id: int) -> int:
#       return self._station_pos[stop_id]
#
#   def station_cell_index(self, stop_id: int) -> int:
#       return self._station_cell[stop_id]
#
# In build_index(), after the airport block, deduplicate stops by id, map each to its
# containing land cell exactly as airports are mapped, skip any that miss the mask, and
# offset positions by len(cells) + len(codes).
```

- [ ] **Step 7: Implement rail edges**

```python
# src/transport_maps/graph/rail.py
"""Station-to-station rail edges from ordered route stops."""

import numpy as np
import polars as pl

from transport_maps.graph import air, ground
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import osm

SPEED_HIGHSPEED_KMH = 250.0
SPEED_CONVENTIONAL_KMH = 80.0
# Track is never a straight line between stops.
SINUOSITY = 1.15
# OSM carries no timetable; these are per-class service assumptions.
FREQUENCY_HIGHSPEED_PER_WEEK = 140.0
FREQUENCY_CONVENTIONAL_PER_WEEK = 56.0


def rail_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    df = osm.rail_routes().sort(["route_id", "seq"])
    rows: list[int] = []
    cols: list[int] = []
    minutes: list[float] = []

    for (_route_id,), group in df.group_by(["route_id"], maintain_order=True):
        stops = group.to_dicts()
        high = bool(stops[0]["highspeed"])
        speed = SPEED_HIGHSPEED_KMH if high else SPEED_CONVENTIONAL_KMH
        freq = FREQUENCY_HIGHSPEED_PER_WEEK if high else FREQUENCY_CONVENTIONAL_PER_WEEK
        wait = air.expected_wait_min(freq)

        for a, b in zip(stops, stops[1:]):
            try:
                u = idx.station_index(a["stop_id"])
                v = idx.station_index(b["stop_id"])
            except KeyError:
                continue
            d = ground.haversine_km(
                np.array([[a["lat"], a["lon"]]]), np.array([[b["lat"], b["lon"]]])
            )[0] * SINUOSITY
            travel = d / speed * 60.0 + wait
            rows.extend((u, v)); cols.extend((v, u)); minutes.extend((travel, travel))

    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )
```

- [ ] **Step 8: Write the rail test**

```python
# tests/graph/test_rail.py
import numpy as np
import pytest

from transport_maps.graph import nodes, rail


@pytest.fixture(scope="module")
def edges():
    return rail.rail_edges(nodes.build_index())


def test_produces_a_substantial_number_of_edges(edges):
    rows, cols, minutes = edges
    assert len(rows) == len(cols) == len(minutes)
    assert len(rows) > 20_000


def test_edges_are_bidirectional(edges):
    rows, cols, _ = edges
    forward = set(zip(rows.tolist(), cols.tolist()))
    assert all((v, u) in forward for u, v in list(forward)[:500])


def test_all_weights_positive_and_finite(edges):
    _, _, minutes = edges
    assert np.isfinite(minutes).all() and (minutes > 0).all()
```

Run: `uv run pytest tests/graph/test_rail.py -v`
Expected: 3 passed

- [ ] **Step 9: Add rail edges and station access to `build_graph`**

In `src/transport_maps/graph/build.py`, add `rail.rail_edges(idx)` to the `parts` list,
and extend `_access_edges` to connect every station to its containing cell with
`STATION_ACCESS_MIN = 15.0` in each direction (rail needs no security screening, which is
exactly why it beats short-haul air on the map).

- [ ] **Step 10: Run the golden test and commit**

```bash
uv run pytest tests/ -v
git add src/transport_maps/ tests/ pyproject.toml uv.lock
git commit -S -m "feat(graph): 🚄 add rail network from OSM route relations"
```

---

## Task 10: Ferry network

Ferries matter more than their share of traffic suggests: they are the only public
transport reaching large parts of Indonesia, the Philippines, Greece and the Caribbean.
In OSM most ferries are **ways** tagged `route=ferry`, not relations, so the endpoints of
the way are the terminals.

**Files:**
- Create: `src/transport_maps/graph/ferry.py`
- Modify: `src/transport_maps/sources/osm.py` (add `ferry_routes`), `src/transport_maps/graph/build.py`
- Test: `tests/graph/test_ferry.py`

**Interfaces:**
- Produces: `osm.ferry_routes() -> pl.DataFrame` with columns `way_id: i64`, `from_lat`, `from_lon`, `to_lat`, `to_lon`, `length_km: f64`; `ferry.ferry_edges(idx) -> Edges`

- [ ] **Step 1: Write the failing test**

```python
# tests/graph/test_ferry.py
import numpy as np
import pytest

from transport_maps.graph import ferry, nodes


@pytest.fixture(scope="module")
def edges():
    return ferry.ferry_edges(nodes.build_index())


def test_produces_ferry_edges(edges):
    rows, _, minutes = edges
    assert len(rows) > 1_000
    assert np.isfinite(minutes).all() and (minutes > 0).all()


def test_ferry_is_slower_per_km_than_rail():
    assert ferry.SPEED_KMH < 60.0


def test_very_long_crossings_are_excluded():
    assert ferry.MAX_CROSSING_KM <= 2000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/graph/test_ferry.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Add the ferry reader to `osm.py`**

```python
# append to src/transport_maps/sources/osm.py
class _FerryWays(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict] = []

    def way(self, w) -> None:
        if w.tags.get("route") != "ferry" or len(w.nodes) < 2:
            return
        try:
            a, b = w.nodes[0].location, w.nodes[-1].location
        except osmium.InvalidLocationError:
            return
        if not (a.valid() and b.valid()):
            return
        self.rows.append({
            "way_id": w.id,
            "from_lat": a.lat, "from_lon": a.lon,
            "to_lat": b.lat, "to_lon": b.lon,
        })


def ferry_routes() -> pl.DataFrame:
    out = config.BUILD / "ferry_routes.parquet"
    if out.exists():
        return pl.read_parquet(out)

    rows: list[dict] = []
    for region in REGIONS:
        path = config.CACHE / "osm" / f"{region}-rail.osm.pbf"
        handler = _FerryWays()
        handler.apply_file(str(path), locations=True)
        rows.extend(handler.rows)

    df = pl.DataFrame(rows).unique(subset=["way_id"])
    config.ensure_dirs()
    df.write_parquet(out)
    return df
```

Note `locations=True` here — unlike the relation pass, ferry ways need node coordinates
resolved. pyosmium builds the location index on the fly.

- [ ] **Step 4: Implement ferry edges**

Ferry terminals are attached directly to their containing land cell rather than getting
their own node type; at res 5 the terminal and its town share a cell anyway.

```python
# src/transport_maps/graph/ferry.py
"""Cell-to-cell ferry edges from OSM route=ferry ways."""

import h3
import numpy as np

from transport_maps import config
from transport_maps.graph import air, ground
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import osm

SPEED_KMH = 35.0
# Longer than this is freight or a repositioning route, not scheduled passenger service.
MAX_CROSSING_KM = 1500.0
BOARDING_MIN = 30.0
FREQUENCY_PER_WEEK = 21.0


def ferry_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    df = osm.ferry_routes()
    wait = air.expected_wait_min(FREQUENCY_PER_WEEK)

    rows: list[int] = []
    cols: list[int] = []
    minutes: list[float] = []
    for r in df.iter_rows(named=True):
        d = ground.haversine_km(
            np.array([[r["from_lat"], r["from_lon"]]]),
            np.array([[r["to_lat"], r["to_lon"]]]),
        )[0]
        if d > MAX_CROSSING_KM or d <= 0:
            continue
        try:
            u = idx.cell_index(h3.latlng_to_cell(r["from_lat"], r["from_lon"], config.SOLVE_RES))
            v = idx.cell_index(h3.latlng_to_cell(r["to_lat"], r["to_lon"], config.SOLVE_RES))
        except KeyError:
            continue
        if u == v:
            continue
        t = d / SPEED_KMH * 60.0 + BOARDING_MIN + wait
        rows.extend((u, v)); cols.extend((v, u)); minutes.extend((t, t))

    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )
```

- [ ] **Step 5: Run test, wire into `build_graph`, and commit**

Add `ferry.ferry_edges(idx)` to the `parts` list in `build.py`.

```bash
uv run pytest tests/graph/test_ferry.py tests/test_golden.py -v
git add src/transport_maps/ tests/
git commit -S -m "feat(graph): ⛴️ add ferry crossings from OSM route=ferry ways"
```

---

## Task 11: Realistic transfer penalties

Phase A used one flat airport access cost. Split it by domestic versus international and
give each airport a size-appropriate minimum connection time.

**Files:**
- Create: `src/transport_maps/graph/transfers.py`
- Modify: `src/transport_maps/graph/build.py`, `calibration.toml`
- Test: `tests/graph/test_transfers.py`

**Interfaces:**
- Produces: `transfers.access_min(size: str, international: bool, cal) -> float`, `transfers.egress_min(size: str, international: bool, cal) -> float`, `transfers.connection_min(size: str, cal) -> float`

- [ ] **Step 1: Write the failing test**

```python
# tests/graph/test_transfers.py
import pytest

from transport_maps.graph import air, transfers


@pytest.fixture(scope="module")
def cal():
    return air.load_calibration()


def test_international_access_exceeds_domestic(cal):
    assert transfers.access_min("large", True, cal) > transfers.access_min("large", False, cal)


def test_large_hubs_have_longer_connections_than_small_airports(cal):
    assert transfers.connection_min("large", cal) > transfers.connection_min("small", cal)


def test_egress_is_shorter_than_access(cal):
    # Leaving an airport is faster than entering one: no check-in, no security.
    assert transfers.egress_min("large", True, cal) < transfers.access_min("large", True, cal)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/graph/test_transfers.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Add coefficients to `calibration.toml`**

```toml
[access_min]
# Arrive, check in, clear security. International adds passport control.
domestic = { large = 70.0, medium = 55.0, small = 40.0 }
international = { large = 100.0, medium = 80.0, small = 65.0 }

[egress_min]
domestic = { large = 30.0, medium = 22.0, small = 15.0 }
international = { large = 55.0, medium = 45.0, small = 35.0 }

[connection_min]
# Minimum connection time, refitted in Task 12 from observed connections.
large = 75.0
medium = 50.0
small = 35.0
```

- [ ] **Step 4: Implement, extending `Calibration` with the three new dicts**

```python
# src/transport_maps/graph/transfers.py
"""Mode-change penalties."""

from transport_maps.graph.air import Calibration

STATION_ACCESS_MIN = 15.0
STATION_EGRESS_MIN = 10.0


def access_min(size: str, international: bool, cal: Calibration) -> float:
    key = "international" if international else "domestic"
    return cal.access_min[key][size]


def egress_min(size: str, international: bool, cal: Calibration) -> float:
    key = "international" if international else "domestic"
    return cal.egress_min[key][size]


def connection_min(size: str, cal: Calibration) -> float:
    return cal.connection_min[size]
```

- [ ] **Step 5: Apply them in `build.py`**

Two changes:

1. `_access_edges` takes the airport's `size` and uses `access_min` / `egress_min`. Since
   an origin's international status is not known when the graph is built, use the
   `international` variant — it is the conservative choice and correct for the majority
   of a global map's long-haul paths.
2. `_air_edges` adds `connection_min(dep_size)` to each flight edge, so every hop after
   the first pays a realistic connection cost. The first hop double-counts slightly
   against `access_min`; accept it, and note it in the golden-test tolerances.

- [ ] **Step 6: Run the full suite and commit**

```bash
uv run pytest tests/ -v
git add src/transport_maps/ calibration.toml tests/
git commit -S -m "feat(graph): 🔀 split transfer penalties by domestic and international"
```

---

# Phase C — Calibration

Both tasks here read commercial APIs and write only coefficients. **Nothing they fetch may
reach `dist/`.** Task 15 enforces this with a test.

## Task 12: Fit the flight model from real flights

**Files:**
- Create: `src/transport_maps/calibrate/__init__.py`, `src/transport_maps/calibrate/fr24.py`, `src/transport_maps/calibrate/fit.py`
- Modify: `calibration.toml` (rewritten by the fit), `src/transport_maps/cli.py`
- Test: `tests/calibrate/test_fit.py`

**Interfaces:**
- Produces: `fr24.sample_flights(days: int, limit: int) -> pl.DataFrame` with columns `dep_iata`, `arr_iata`, `block_min`, `distance_km`, `dep_size`, `arr_size`; `fit.fit_airborne(df) -> tuple[float, float]`, `fit.fit_frequency(df) -> tuple[float, float, dict[str, float]]`, `fit.write_calibration(path, ...) -> None`

- [ ] **Step 1: Write the failing test using synthetic data**

The fit must be testable without touching the API, so test it against data generated from
known coefficients and assert it recovers them.

```python
# tests/calibrate/test_fit.py
import numpy as np
import polars as pl

from transport_maps.calibrate import fit


def test_recovers_known_airborne_coefficients():
    rng = np.random.default_rng(0)
    distances = rng.uniform(200, 12_000, 4_000)
    # Truth: 25 min penalty, 800 km/h cruise, small gaussian noise.
    block = 25.0 + 60.0 * distances / 800.0 + rng.normal(0, 4.0, len(distances))
    df = pl.DataFrame({"distance_km": distances, "airborne_min": block})

    penalty, cruise = fit.fit_airborne(df)
    assert penalty == pytest.approx(25.0, abs=3.0)
    assert cruise == pytest.approx(800.0, abs=25.0)


def test_recovers_known_frequency_coefficients():
    rng = np.random.default_rng(2)
    n = 3_000
    d = rng.uniform(200, 12_000, n)
    dep = rng.choice(["large", "medium", "small"], n)
    arr = rng.choice(["large", "medium", "small"], n)
    truth = {"large": 1.0, "medium": 0.55, "small": 0.25}
    f = 42.0 * np.array([truth[s] for s in dep]) * np.array([truth[s] for s in arr]) * d ** -0.35
    df = pl.DataFrame(
        {"distance_km": d, "dep_size": dep, "arr_size": arr, "flights_per_week": f}
    )

    base, decay, weights = fit.fit_frequency(df)
    assert base == pytest.approx(42.0, rel=0.15)
    assert decay == pytest.approx(-0.35, abs=0.05)
    assert weights["medium"] == pytest.approx(0.55, rel=0.15)
    assert weights["small"] == pytest.approx(0.25, rel=0.15)


def test_holdout_mae_is_reported_and_small_on_clean_data():
    rng = np.random.default_rng(1)
    d = rng.uniform(200, 12_000, 2_000)
    df = pl.DataFrame({"distance_km": d, "airborne_min": 25.0 + 60.0 * d / 800.0})
    _, _, mae = fit.fit_airborne_with_holdout(df)
    assert mae < 2.0
```

Add `import pytest` at the top.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/calibrate/test_fit.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the fit**

```python
# src/transport_maps/calibrate/fit.py
"""Regress model coefficients from sampled flights. Reads records, writes only numbers."""

import numpy as np
import polars as pl

HOLDOUT_FRACTION = 0.2


def fit_airborne(df: pl.DataFrame) -> tuple[float, float]:
    """Least squares on airborne_min = penalty + 60 * distance / cruise."""
    d = df["distance_km"].to_numpy()
    y = df["airborne_min"].to_numpy()
    # y = a + b*d, so cruise = 60 / b.
    design = np.column_stack([np.ones_like(d), d])
    (a, b), *_ = np.linalg.lstsq(design, y, rcond=None)
    if b <= 0:
        raise RuntimeError("non-positive distance coefficient; sample is unusable")
    return float(a), float(60.0 / b)


def fit_frequency(df: pl.DataFrame) -> tuple[float, float, dict[str, float]]:
    """Fit flights_per_week = base * w[dep] * w[arr] * distance ^ decay.

    Linear in log space: log f = log base + log w[dep] + log w[arr] + decay * log d.
    `large` is the reference category with weight fixed at 1.0, so the design matrix
    stays full rank.
    """
    sizes = ("medium", "small")
    log_f = np.log(df["flights_per_week"].to_numpy())
    log_d = np.log(np.maximum(df["distance_km"].to_numpy(), 1.0))

    columns = [np.ones_like(log_d), log_d]
    for size in sizes:
        dep = (df["dep_size"].to_numpy() == size).astype(float)
        arr = (df["arr_size"].to_numpy() == size).astype(float)
        columns.append(dep + arr)

    coefficients, *_ = np.linalg.lstsq(np.column_stack(columns), log_f, rcond=None)
    base = float(np.exp(coefficients[0]))
    decay = float(coefficients[1])
    weights = {"large": 1.0}
    for offset, size in enumerate(sizes):
        weights[size] = float(np.exp(coefficients[2 + offset]))
    return base, decay, weights


def fit_airborne_with_holdout(df: pl.DataFrame) -> tuple[float, float, float]:
    shuffled = df.sample(fraction=1.0, shuffle=True, seed=0)
    cut = int(len(shuffled) * (1.0 - HOLDOUT_FRACTION))
    train, test = shuffled[:cut], shuffled[cut:]
    penalty, cruise = fit_airborne(train)
    predicted = penalty + 60.0 * test["distance_km"].to_numpy() / cruise
    mae = float(np.abs(predicted - test["airborne_min"].to_numpy()).mean())
    return penalty, cruise, mae
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/calibrate/test_fit.py -v`
Expected: 3 passed

- [ ] **Step 5: Implement the FR24 sampler**

Credentials come from the environment, never from a file in the repo.

```bash
export FR24_API_TOKEN=...      # add to your shell profile, not to git
```

```python
# src/transport_maps/calibrate/fr24.py
"""Sample real flights for calibration. Records are held in memory and discarded."""

import datetime as dt
import os

import httpx
import polars as pl

BASE = "https://fr24api.flightradar24.com/api"
# The API caps a summary query at a 14-day window.
MAX_WINDOW_DAYS = 14


def _client() -> httpx.Client:
    token = os.environ.get("FR24_API_TOKEN")
    if not token:
        raise RuntimeError("FR24_API_TOKEN is not set")
    return httpx.Client(
        base_url=BASE, timeout=120,
        headers={"Authorization": f"Bearer {token}", "Accept-Version": "v1"},
    )


def sample_flights(airports: list[str], days: int = 7) -> pl.DataFrame:
    """Landed flights departing the given airports over a recent window."""
    if days > MAX_WINDOW_DAYS:
        raise ValueError(f"window capped at {MAX_WINDOW_DAYS} days")
    end = dt.datetime.now(dt.UTC)
    start = end - dt.timedelta(days=days)

    rows: list[dict] = []
    with _client() as client:
        for iata in airports:
            r = client.get("/flight-summary/light", params={
                "flight_datetime_from": start.isoformat(timespec="seconds"),
                "flight_datetime_to": end.isoformat(timespec="seconds"),
                "airports": f"outbound:{iata}",
            })
            if r.status_code == 404:
                continue
            r.raise_for_status()
            for f in r.json().get("data", []):
                if not (f.get("takeoff") and f.get("landed")):
                    continue
                rows.append({
                    "dep_iata": f.get("orig_iata"), "arr_iata": f.get("dest_iata"),
                    "takeoff": f["takeoff"], "landed": f["landed"],
                })
    return pl.DataFrame(rows)
```

Confirm the exact response field names against the sandbox key before a paid run — the
sandbox hits the same endpoints with sample data and costs no credits:

```bash
uv run python -c "
from transport_maps.calibrate import fr24
print(fr24.sample_flights(['ICN'], days=1).head())
"
```

If the field names differ, fix the dict keys above; everything downstream reads the
normalised names.

- [ ] **Step 6: Add the `calibrate` CLI command and write the results**

The command samples flights, derives `airborne_min` from takeoff/landing timestamps and
`distance_km` from airport coordinates, runs both fits, and rewrites `calibration.toml`
with `meta.calibrated = true`, the sample size and the holdout MAE. It must never write
the sampled rows to disk.

- [ ] **Step 7: Commit**

```bash
git add src/transport_maps/calibrate/ tests/calibrate/ calibration.toml src/transport_maps/cli.py
git commit -S -m "feat(calibrate): 📐 fit flight model coefficients from sampled flights"
```

---

## Task 13: Real transit times for city-to-airport legs

Replaces the assumed access/egress constants for the origin cities specifically, where a
wrong guess is most visible.

**Files:**
- Create: `src/transport_maps/calibrate/transit.py`, `data/origins.toml`
- Test: `tests/calibrate/test_transit.py`

**Interfaces:**
- Produces: `transit.transit_minutes(origin: tuple[float, float], dest: tuple[float, float]) -> int | None`, `transit.build_access_table() -> pl.DataFrame` with columns `city: str`, `iata: str`, `minutes: i64`

- [ ] **Step 1: Define the origin city list**

```toml
# data/origins.toml — v1 set, expand freely; adding entries needs no code change.
[[origin]]
slug = "seoul"
name = "Seoul"
lat = 37.5665
lon = 126.9780

[[origin]]
slug = "tokyo"
name = "Tokyo"
lat = 35.6762
lon = 139.6503

[[origin]]
slug = "london"
name = "London"
lat = 51.5072
lon = -0.1276
```

Fill to roughly 150 cities: the busiest airports by passenger volume, plus at least five
per inhabited continent so the picker is not Northern-Hemisphere-only.

- [ ] **Step 2: Write the failing test**

```python
# tests/calibrate/test_transit.py
import pytest

from transport_maps.calibrate import transit


@pytest.mark.network
def test_seoul_to_incheon_airport_is_a_plausible_transit_time():
    minutes = transit.transit_minutes((37.5665, 126.9780), (37.4602, 126.4407))
    # The AREX express is about an hour; allow for slower all-stops routings.
    assert minutes is not None
    assert 40 < minutes < 150


def test_missing_api_key_raises_clearly(monkeypatch):
    monkeypatch.delenv("GOOGLE_ROUTES_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_ROUTES_API_KEY"):
        transit.transit_minutes((0.0, 0.0), (1.0, 1.0))
```

- [ ] **Step 3: Implement**

```python
# src/transport_maps/calibrate/transit.py
"""Google Routes API TRANSIT durations for city-centre to airport legs."""

import os

import httpx

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.duration"


def transit_minutes(origin: tuple[float, float], dest: tuple[float, float]) -> int | None:
    key = os.environ.get("GOOGLE_ROUTES_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_ROUTES_API_KEY is not set")

    body = {
        "origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
        "destination": {"location": {"latLng": {"latitude": dest[0], "longitude": dest[1]}}},
        "travelMode": "TRANSIT",
    }
    r = httpx.post(ROUTES_URL, json=body, timeout=60, headers={
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    })
    r.raise_for_status()
    routes = r.json().get("routes", [])
    if not routes:
        return None
    # duration comes back as e.g. "3600s".
    return int(round(int(routes[0]["duration"].rstrip("s")) / 60))
```

- [ ] **Step 4: Build the access table**

For each origin in `data/origins.toml`, find airports within 150 km, query transit time to
each, and cache the result to `data/build/city_access.parquet`. Roughly 150 cities × 2–4
airports is a few hundred calls. `build_graph` prefers a cached measured value over the
`access_min` default when one exists.

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/calibrate/test_transit.py -v -m "not network"
git add src/transport_maps/calibrate/transit.py data/origins.toml tests/
git commit -S -m "feat(calibrate): 🚇 measure city-to-airport transit with Google Routes"
```

---

# Phase D — Production Artifact

## Task 14: Emit PMTiles, hover array, route index and origin index

Replaces the skeleton's single GeoJSON with the four files the frontend actually consumes.

**Files:**
- Create: `src/transport_maps/emit/tiles.py`, `src/transport_maps/emit/hover.py`, `src/transport_maps/emit/routes_json.py`, `src/transport_maps/emit/index.py`
- Modify: `src/transport_maps/solve/dijkstra.py` (return predecessors), `src/transport_maps/cli.py`
- Test: `tests/emit/test_hover.py`, `tests/emit/test_tiles.py`

**Interfaces:**
- Consumes: `bands.band_feature_collection`, `dijkstra.solve_from`
- Produces: `tiles.write_pmtiles(fc: dict, out: Path) -> None`, `hover.write_hover(idx, cell_minutes, out: Path) -> None`, `routes_json.write_routes(idx, minutes, predecessors, out: Path) -> None`, `index.write_index(origins, out: Path) -> None`, `dijkstra.solve_from(csr, source, with_predecessors: bool = False)`

- [ ] **Step 1: Install tippecanoe**

```bash
brew install tippecanoe
tippecanoe --version   # must be >= 2.17 for .pmtiles output
```

- [ ] **Step 2: Write the failing test for the hover array**

The frontend reads this as a flat `Uint16Array`, so byte layout is a contract.

```python
# tests/emit/test_hover.py
import numpy as np

from transport_maps import config
from transport_maps.emit import hover


class FakeIndex:
    # Two res-5 cells that share a res-4 parent, plus one that does not.
    cells = ["8530e08ffffffff", "8530e087fffffff", "85754e63fffffff"]
    n_cells = 3


def test_writes_uint16_little_endian(tmp_path):
    out = tmp_path / "h.bin"
    hover.write_hover(FakeIndex(), np.array([10.0, 20.0, 5000.0]), out)
    raw = np.frombuffer(out.read_bytes(), dtype="<u2")
    assert raw.dtype.itemsize == 2
    assert len(raw) == len(hover.hover_cells(FakeIndex()))


def test_parent_cell_takes_the_minimum_of_its_children(tmp_path):
    out = tmp_path / "h.bin"
    hover.write_hover(FakeIndex(), np.array([10.0, 20.0, 5000.0]), out)
    values = np.frombuffer(out.read_bytes(), dtype="<u2")
    assert 10 in values  # the faster of the two siblings wins


def test_unreachable_becomes_the_sentinel(tmp_path):
    out = tmp_path / "h.bin"
    hover.write_hover(FakeIndex(), np.array([np.inf, np.inf, np.inf]), out)
    values = np.frombuffer(out.read_bytes(), dtype="<u2")
    assert (values == config.UNREACHABLE).all()


def test_values_are_clamped_below_the_sentinel(tmp_path):
    out = tmp_path / "h.bin"
    hover.write_hover(FakeIndex(), np.array([99_999.0, 99_999.0, 99_999.0]), out)
    values = np.frombuffer(out.read_bytes(), dtype="<u2")
    assert (values < config.UNREACHABLE).all()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/emit/test_hover.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement the hover array**

```python
# src/transport_maps/emit/hover.py
"""Coarse res-4 time array for instant hover readout.

Layout contract with the frontend: little-endian uint16 minutes, one entry per
res-4 cell, ordered by the sorted res-4 cell id list that `hover_cells` returns.
The frontend fetches that ordering once from index.json.
"""

from pathlib import Path

import h3
import numpy as np

from transport_maps import config

# Reserve the sentinel; anything slower is clamped to just below it.
MAX_MINUTES = config.UNREACHABLE - 1


def hover_cells(idx) -> list[str]:
    """Sorted res-4 parents of the solver cells."""
    return sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})


def write_hover(idx, cell_minutes: np.ndarray, out: Path) -> None:
    parents = hover_cells(idx)
    position = {cell: i for i, cell in enumerate(parents)}

    best = np.full(len(parents), np.inf, dtype=np.float64)
    for pos, cell in enumerate(idx.cells):
        p = position[h3.cell_to_parent(cell, config.HOVER_RES)]
        value = cell_minutes[pos]
        if value < best[p]:
            best[p] = value

    encoded = np.where(
        np.isfinite(best), np.minimum(best, MAX_MINUTES), config.UNREACHABLE
    ).astype("<u2")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded.tobytes())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/emit/test_hover.py -v`
Expected: 4 passed

- [ ] **Step 6: Implement the PMTiles writer**

```python
# src/transport_maps/emit/tiles.py
"""Band GeoJSON -> PMTiles via tippecanoe."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

# Measured on a real Seoul band set: Z0-7 gives 3.84 MB, Z0-6 gives 2.38 MB
# (-38%), while quadrupling simplification only saves 12%. Max zoom is the
# dominant size lever. The source is H3 res-5 hexes (~8.5 km edge), and at
# zoom 6 that is already ~3.5 px, so zoom 7 spends bytes on detail finer than
# the underlying data. Do not raise this without re-measuring.
MIN_ZOOM, MAX_ZOOM = 0, 6
LAYER = "bands"


def write_pmtiles(feature_collection: dict, out: Path) -> None:
    if shutil.which("tippecanoe") is None:
        raise RuntimeError("tippecanoe not on PATH; run: brew install tippecanoe")

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False) as fh:
        json.dump(feature_collection, fh)
        src = Path(fh.name)

    try:
        subprocess.run([
            "tippecanoe",
            "-o", str(out), "--force",
            "-l", LAYER,
            "-Z", str(MIN_ZOOM), "-z", str(MAX_ZOOM),
            "--simplification=4",
            "--coalesce-densest-as-needed",
            "--extend-zooms-if-still-dropping",
        ], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"tippecanoe failed: {exc.stderr}") from exc
    finally:
        src.unlink(missing_ok=True)

    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"tippecanoe produced no output at {out}")
```

- [ ] **Step 7: Test the PMTiles writer**

```python
# tests/emit/test_tiles.py
import pytest

from transport_maps.emit import tiles

SQUARE = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"band": 0, "max_minutes": 120},
        "geometry": {"type": "Polygon", "coordinates": [[
            [126.0, 37.0], [127.0, 37.0], [127.0, 38.0], [126.0, 38.0], [126.0, 37.0]
        ]]},
    }],
}


def test_writes_a_non_empty_pmtiles_file(tmp_path):
    out = tmp_path / "t.pmtiles"
    tiles.write_pmtiles(SQUARE, out)
    assert out.stat().st_size > 0
    assert out.read_bytes()[:7] == b"PMTiles"
```

Run: `uv run pytest tests/emit/test_tiles.py -v`
Expected: 1 passed

- [ ] **Step 8: Implement the route index and origin index**

`routes_json` needs predecessors, so first extend the solver:

```python
# src/transport_maps/solve/dijkstra.py  (replace solve_from)
def solve_from(csr, source: int, with_predecessors: bool = False):
    """Minutes from `source`. Returns (dist, pred) when with_predecessors is set."""
    if with_predecessors:
        return _dijkstra(
            csgraph=csr, directed=True, indices=source, return_predecessors=True
        )
    return _dijkstra(csgraph=csr, directed=True, indices=source)
```

```python
# src/transport_maps/emit/routes_json.py
"""Reachable transport nodes with arrival time and predecessor.

The frontend walks `prev` back to the origin to render a route breakdown such as
`ICN -> DXB -> GRU - 31h 20m`. `offsets` lets it classify a node id without a lookup.
"""

import json
from pathlib import Path

import numpy as np

# scipy marks "no predecessor" with -9999.
NO_PREDECESSOR = -9999


def write_routes(idx, minutes: np.ndarray, predecessors: np.ndarray, out: Path) -> None:
    nodes = []

    def add(node_id: int, kind: str, code: str) -> None:
        if not np.isfinite(minutes[node_id]):
            return
        prev = int(predecessors[node_id])
        nodes.append({
            "id": node_id,
            "kind": kind,
            "code": code,
            "min": int(round(float(minutes[node_id]))),
            "prev": prev if prev != NO_PREDECESSOR else None,
        })

    for iata in idx.airports:
        add(idx.airport_index(iata), "air", iata)
    for stop_id in idx.stations:
        add(idx.station_index(stop_id), "rail", str(stop_id))

    payload = {
        "offsets": {
            "cells": 0,
            "airports": idx.n_cells,
            "stations": idx.n_cells + len(idx.airports),
        },
        "nodes": nodes,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
```

The res-4 cell ordering is roughly 83,000 ids. Embedding it in `index.json` would bloat a
file every page load fetches, so it ships once as its own binary and is cached across all
origins.

```python
# src/transport_maps/emit/index.py
"""index.json plus the shared hover-cell ordering."""

import json
import tomllib
from pathlib import Path

import h3
import numpy as np

from transport_maps import config
from transport_maps.emit import hover


def load_origins(path: Path | None = None) -> list[dict]:
    path = path or (config.DATA / "origins.toml")
    with open(path, "rb") as fh:
        origins = tomllib.load(fh)["origin"]
    slugs = [o["slug"] for o in origins]
    if len(set(slugs)) != len(slugs):
        raise ValueError("duplicate origin slug in origins.toml")
    return origins


def write_hover_cells(idx, out: Path) -> None:
    """Sorted res-4 cell ids as little-endian uint64, matching the .bin ordering.

    The frontend computes h3.latLngToCell(lat, lon, 4), converts it to its integer
    form, and binary-searches this array to get the index into each origin's .bin.
    """
    ids = np.array([h3.str_to_int(c) for c in hover.hover_cells(idx)], dtype="<u8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(ids.tobytes())


def write_index(origins: list[dict], out: Path) -> None:
    payload = {
        "bandEdgesMin": list(config.BAND_EDGES_MIN),
        "unreachable": config.UNREACHABLE,
        "hoverRes": config.HOVER_RES,
        "hoverCellsUrl": "hover_cells.bin",
        "origins": [
            {"slug": o["slug"], "name": o["name"], "lat": o["lat"], "lon": o["lon"]}
            for o in origins
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
```

Add a test asserting `write_hover_cells` output is sorted ascending, since the frontend's
binary search depends on it:

```python
# tests/emit/test_index.py
import numpy as np

from transport_maps.emit import index


class FakeIndex:
    cells = ["8530e08ffffffff", "8530e087fffffff", "85754e63fffffff"]
    n_cells = 3


def test_hover_cell_ids_are_sorted_ascending(tmp_path):
    out = tmp_path / "hover_cells.bin"
    index.write_hover_cells(FakeIndex(), out)
    ids = np.frombuffer(out.read_bytes(), dtype="<u8")
    assert len(ids) > 0
    assert (np.diff(ids.astype(object)) > 0).all()
```

Run: `uv run pytest tests/emit/ -v`
Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add src/transport_maps/emit/ src/transport_maps/solve/ tests/emit/
git commit -S -m "feat(emit): 📦 write PMTiles bands, hover array and route index"
```

---

## Task 15: Batch build, validation gates, and the licence firewall

The last task. Builds every origin and refuses to publish a broken or non-compliant
artifact.

**Files:**
- Create: `src/transport_maps/validate.py`
- Modify: `src/transport_maps/cli.py` (add `build-all`)
- Test: `tests/test_validate.py`, `tests/test_licence_firewall.py`

**Interfaces:**
- Produces: `validate.check_coverage(minutes, idx) -> float`, `validate.check_bands_disjoint(fc) -> None`, `validate.check_monotonic_ground(idx, minutes) -> None`

- [ ] **Step 1: Write the failing validation tests**

```python
# tests/test_validate.py
import numpy as np
import pytest

from transport_maps import validate


def test_coverage_is_the_reachable_fraction():
    minutes = np.array([10.0, 20.0, np.inf, np.inf])

    class Idx:
        n_cells = 4
    assert validate.check_coverage(minutes, Idx()) == 0.5


def test_overlapping_bands_are_rejected():
    fc = {"features": [
        {"properties": {"band": 0}, "geometry": {"type": "Polygon", "coordinates": [[
            [0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}},
        {"properties": {"band": 1}, "geometry": {"type": "Polygon", "coordinates": [[
            [1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}},
    ]}
    with pytest.raises(ValueError, match="overlap"):
        validate.check_bands_disjoint(fc)


def test_disjoint_bands_are_accepted():
    fc = {"features": [
        {"properties": {"band": 0}, "geometry": {"type": "Polygon", "coordinates": [[
            [0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}},
        {"properties": {"band": 1}, "geometry": {"type": "Polygon", "coordinates": [[
            [5, 5], [6, 5], [6, 6], [5, 6], [5, 5]]]}},
    ]}
    validate.check_bands_disjoint(fc)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_validate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the validators**

```python
# src/transport_maps/validate.py
"""Publication gates. Every check aborts the build rather than shipping bad data."""

import numpy as np
import shapely
from shapely.geometry import shape

MIN_COVERAGE = 0.90


def check_coverage(minutes: np.ndarray, idx) -> float:
    """Fraction of land cells with any path to the origin."""
    return float(np.isfinite(minutes[: idx.n_cells]).mean())


def check_bands_disjoint(feature_collection: dict) -> None:
    geoms = [shape(f["geometry"]) for f in feature_collection["features"]]
    for i, a in enumerate(geoms):
        for b in geoms[i + 1:]:
            if a.intersection(b).area > 1e-9:
                raise ValueError("isochrone bands overlap; dissolution is broken")


def check_monotonic_ground(idx, minutes: np.ndarray) -> None:
    """Dijkstra's invariant: no cell beats reaching it via an adjacent cell.

    For adjacent p and q, minutes[q] must not exceed minutes[p] plus the ACTUAL
    cost of the p->q ground hop. Charge the real edge weight, which is the hop
    distance divided by the DESTINATION cell's speed -- the same rule
    ground.hex_edges uses.

    An earlier draft compared against the fastest speed on the grid (85 km/h,
    about 10.6 minutes per hop). That is wrong: ground speeds span 5 to 85 km/h,
    so a roadless neighbour legitimately costs about 180 minutes, and the tight
    bound fails on any slow terrain. Do not reintroduce a single global bound.
    """
    import h3

    from transport_maps.graph import ground

    speeds = ground.cell_speed_kmh(idx)
    stride = 997  # sample; a full sweep is O(n * 7) and this gate runs per origin
    for pos in range(0, idx.n_cells, stride):
        here = float(minutes[pos])
        if not np.isfinite(here):
            continue
        cell = idx.cells[pos]
        origin_latlng = np.array([h3.cell_to_latlng(cell)])
        for neighbour in h3.grid_disk(cell, 1):
            if neighbour == cell:
                continue
            q = idx.try_cell_index(neighbour)
            if q is None or not np.isfinite(minutes[q]):
                continue
            distance = ground.haversine_km(
                origin_latlng, np.array([h3.cell_to_latlng(neighbour)])
            )[0]
            hop = distance / speeds[q] * 60.0
            if minutes[q] > here + hop + 1e-6:
                raise ValueError(
                    f"cell {neighbour} is {minutes[q]:.1f} min but its neighbour "
                    f"{cell} is {here:.1f} min and the hop costs only {hop:.1f} min; "
                    "the solver or the ground edges are inconsistent"
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_validate.py -v`
Expected: 3 passed

- [ ] **Step 5: Write the licence firewall test**

This is the check that keeps the project publishable. It asserts that nothing in `dist/`
carries provider fingerprints.

```python
# tests/test_licence_firewall.py
"""Nothing derived from FR24 or FlightAware may reach the published artifact."""

import json
import tomllib
from pathlib import Path

import pytest

from transport_maps import config

FORBIDDEN = ("fr24", "flightradar", "flightaware", "aeroapi", "fa_flight_id")


def _dist_files() -> list[Path]:
    return [p for p in config.DIST.rglob("*") if p.is_file()]


@pytest.mark.skipif(not config.DIST.exists(), reason="nothing built yet")
def test_no_provider_fingerprints_in_shipped_text():
    for path in _dist_files():
        if path.suffix not in {".json", ".geojson", ".toml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in FORBIDDEN:
            assert token not in text, f"{path} contains '{token}'"


def test_calibration_contains_only_numbers():
    raw = tomllib.loads((config.ROOT / "calibration.toml").read_text())

    def assert_scalar(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert_scalar(v, f"{path}.{k}")
        elif isinstance(node, list):
            raise AssertionError(f"calibration.toml{path} is a list; records are forbidden")
        else:
            assert isinstance(node, (int, float, bool, str)), f"{path} is {type(node)}"

    assert_scalar(raw)
    # A record dump would be far larger than a coefficient table.
    assert len(json.dumps(raw)) < 4_000
```

- [ ] **Step 6: Run the firewall test**

Run: `uv run pytest tests/test_licence_firewall.py -v`
Expected: 2 passed

- [ ] **Step 7: Add the `build-all` command**

Build the graph once, then solve each origin against it. Abort on the first failure — a
partially written `dist/` is worse than none.

```python
# src/transport_maps/cli.py  (add alongside the existing solve command)
def _build_all() -> None:
    import numpy as np

    from transport_maps import config, validate
    from transport_maps.contour import bands
    from transport_maps.emit import hover, index, routes_json, tiles
    from transport_maps.graph import build, nodes
    from transport_maps.solve import dijkstra

    idx = nodes.build_index()
    csr = build.build_graph(idx)
    origins = index.load_origins()

    index.write_index(origins, config.DIST / "index.json")
    index.write_hover_cells(idx, config.DIST / "hover_cells.bin")

    print(f"{'origin':<20}{'coverage':>10}{'bands':>8}{'pmtiles KB':>12}")
    for origin in origins:
        slug = origin["slug"]
        source = dijkstra.origin_node(idx, origin["lat"], origin["lon"])
        minutes, predecessors = dijkstra.solve_from(csr, source, with_predecessors=True)

        coverage = validate.check_coverage(minutes, idx)
        if coverage < validate.MIN_COVERAGE:
            raise SystemExit(
                f"{slug}: coverage {coverage:.1%} below {validate.MIN_COVERAGE:.0%}"
            )
        validate.check_monotonic_ground(idx, minutes)

        fc = bands.band_feature_collection(idx, minutes[: idx.n_cells])
        validate.check_bands_disjoint(fc)

        out = config.DIST / "origins"
        tiles.write_pmtiles(fc, out / f"{slug}.pmtiles")
        hover.write_hover(idx, minutes[: idx.n_cells], out / f"{slug}.bin")
        routes_json.write_routes(idx, minutes, predecessors, out / f"{slug}.json")

        size_kb = (out / f"{slug}.pmtiles").stat().st_size // 1024
        print(f"{slug:<20}{coverage:>9.1%}{len(fc['features']):>8}{size_kb:>12}")
```

Wire it into `main()` by adding a `build-all` subparser with no arguments that calls
`_build_all()`.

- [ ] **Step 8: Run the full build**

```bash
uv run transport-maps build-all
uv run pytest tests/ -v
```

Expected: `dist/` contains `index.json` and four files per origin. Every origin reports
coverage above 90%.

- [ ] **Step 9: Commit**

```bash
git add src/transport_maps/validate.py src/transport_maps/cli.py tests/
git commit -S -m "feat(build): ✅ add batch build with coverage and licence gates"
```

---

## Done

At this point the pipeline produces the complete shipped artifact. The frontend plan
(`docs/superpowers/plans/<date>-transport-frontend.md`) consumes `dist/` and needs no
further pipeline work.

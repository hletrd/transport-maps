"""Hex-to-hex ground edges."""

import logging

import h3
import numpy as np

from transport_maps import config
from transport_maps.graph import refine, transfers
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import countries, motorways, roads, urban

logger = logging.getLogger(__name__)


#: calibration.toml [ground] keys in class order: GRIP4's 0 roadless .. 5
#: local, then 6, a cell an OSM motorway crosses (MOTORWAY_CLASS).
GROUND_KEYS = ("roadless_kmh", "highway_kmh", "primary_kmh", "secondary_kmh",
               "tertiary_kmh", "local_kmh", "motorway_kmh")
#: The class of a cell an OSM motorway or expressway crosses
#: (sources/motorways.py), whatever GRIP4 graded it. GRIP4's own "highways"
#: grade (class 1) cannot tell an expressway from an old national highway.
MOTORWAY_CLASS = 6


def load_ground_calibration(path=None) -> tuple[np.ndarray, float]:
    """calibration.toml [ground] and [land_border]: the speed per road class
    (GRIP4's six, then MOTORWAY_CLASS) and the land-border crossing time,
    read once.

    The speed table is a mixture -- classes 1-4 and 6 FITTED against Google
    Routes journeys, roadless (0) and local (5) published-figure defaults --
    and calibration.toml says which is which and why. It lived here as a
    literal until task B2 (2026-10-02), with the same values;
    tests/test_calibration_moved.py pins them.
    """
    import tomllib

    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    table = raw["ground"]
    missing = [k for k in GROUND_KEYS if k not in table]
    if missing:
        raise ValueError(f"{path} [ground] is missing {', '.join(missing)}")
    speeds = np.array([float(table[k]) for k in GROUND_KEYS], dtype=np.float64)
    if not (speeds > 0).all():
        raise ValueError(f"{path} [ground] speeds must be positive; got {speeds.tolist()}")
    return speeds, float(raw["land_border"]["crossing_min"])


# Index by road class: 0 = roadless, 1 = highway .. 5 = local road (GRIP4),
# 6 = OSM motorway.
# Provenance per class is in calibration.toml [ground]. Read ONCE, at import:
# the land-border time used to be re-parsed from the file by every caller,
# including the per-origin monotonicity gate, so an edit to calibration.toml
# during a build could check origins against a constant the graph was not
# weighted with (ARCH-8).
SPEED_BY_ROAD_CLASS_KMH, LAND_BORDER_MIN = load_ground_calibration()

#: Road classes an income multiplier scales (highway .. tertiary, motorway):
#: the FITTED ones. Roadless is walking pace and local a published default.
#: The motorway class is scaled because that fitted better out of fold than
#: one motorway speed everywhere (calibration.toml [ground]).
INCOME_SCALED_CLASSES = (1, 2, 3, 4, 6)


def load_road_model(path=None) -> tuple[np.ndarray, float]:
    """calibration.toml [ground_income] and [ground] end_min: the speed
    multiplier per World Bank income group (sources/countries.INCOME_GROUPS
    order) and the minutes every road journey pays at its two ends. Both
    FITTED with the class speeds (scripts/calibrate_ground.py); provenance in
    calibration.toml."""
    import tomllib

    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    table = raw["ground_income"]
    missing = [k for k in countries.INCOME_GROUPS if k not in table]
    if missing:
        raise ValueError(f"{path} [ground_income] is missing {', '.join(missing)}")
    mult = np.array([float(table[k]) for k in countries.INCOME_GROUPS], dtype=np.float64)
    end = float(raw["ground"]["end_min"])
    if not (mult > 0).all() or end < 0:
        raise ValueError(f"{path}: income multipliers must be positive and end_min >= 0; "
                         f"got {mult.tolist()}, {end}")
    return mult, end


# Read once, at import, like the speeds above.
INCOME_SPEED_MULTIPLIER, END_MINUTES = load_road_model()


#: calibration.toml [ground_motorway] keys, by sources/motorways.limit_band_of
#: band 1 .. 3 (band 0, no signed limit, is [ground] motorway_kmh).
MOTORWAY_LIMIT_KEYS = ("under_95_kmh", "from_95_kmh", "from_115_kmh")


def load_motorway_and_region(path=None) -> tuple[np.ndarray, np.ndarray]:
    """calibration.toml [ground_motorway] and [ground_region]: the motorway
    speed per signed-limit band (no signed limit first, [ground]
    motorway_kmh), and the speed multiplier per driving region
    (sources/countries.DRIVING_REGIONS; index 0, every other country, is 1).
    Both FITTED with the class speeds; provenance in calibration.toml."""
    import tomllib

    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    mw = raw["ground_motorway"]
    missing = [k for k in MOTORWAY_LIMIT_KEYS if k not in mw]
    if missing:
        raise ValueError(f"{path} [ground_motorway] is missing {', '.join(missing)}")
    limit = np.array([float(raw["ground"]["motorway_kmh"])]
                     + [float(mw[k]) for k in MOTORWAY_LIMIT_KEYS], dtype=np.float64)
    reg = raw["ground_region"]
    missing = [k for k in countries.DRIVING_REGIONS if k not in reg]
    if missing:
        raise ValueError(f"{path} [ground_region] is missing {', '.join(missing)}")
    region = np.array([1.0] + [float(reg[k]) for k in countries.DRIVING_REGIONS], dtype=np.float64)
    if not ((limit > 0).all() and (region > 0).all()):
        raise ValueError(f"{path}: motorway speeds and region multipliers must be positive; "
                         f"got {limit.tolist()}, {region.tolist()}")
    return limit, region


MOTORWAY_SPEED_BY_LIMIT_KMH, REGION_SPEED_MULTIPLIER = load_motorway_and_region()

# Directed edge slots preallocated per cell: six ring neighbours plus the
# cross-resolution pairs along split seams. Measured at 8.0 per cell over the
# res-6/7 universe (82 M edges over 10.2 M cells); the guard below turns an
# overflow into a message instead of a bare IndexError hours into a build.
EDGE_SLOTS_PER_CELL = 8


def _land_border_min() -> float:
    """calibration.toml [land_border] crossing_min, as read at import."""
    return LAND_BORDER_MIN


def grip_class(idx: NodeIndex) -> np.ndarray:
    """GRIP4 road class per cell. Computed on the base grid and carried down to
    the fine children: the rasters are 5 arc-minutes, coarser than either grid,
    so a child's class is its parent's, and the per-cell footprint pass over
    ten million cells would buy nothing."""
    if len(getattr(idx, "base_cells", [])):
        return refine.expand(roads.cell_class(idx.base_cells), idx)
    return roads.cell_class(idx.cells)


#: The class a cell crossed by any OSM motorway or trunk is raised to when
#: GRIP4 grades it below that (TRUNK_RAISED): GRIP4 misses roads OSM has. The
#: coast road from Tawau to its airport is OSM trunk and GRIP4 roadless and
#: tertiary, so the 27 km run went 145 km round inland (rebuild 32: 216 min).
TRUNK_FLOOR_CLASS = 2
TRUNK_RAISED = (0, 4, 5)


def cell_class(idx: NodeIndex, rule: str | None = None) -> np.ndarray:
    """Road class per cell: GRIP4's (`grip_class`), raised to
    TRUNK_FLOOR_CLASS where any OSM motorway or trunk crosses a cell GRIP4
    grades roadless, tertiary or local, and to MOTORWAY_CLASS where an OSM
    motorway (under `rule`, sources/motorways.RULE if None) crosses the cell.
    Per index cell, fine children included -- a motorway crosses a few of a
    split cell's children, not all of them. The refinement itself
    (graph/nodes, refine.dense_mask) still reads GRIP4 alone, so the cell
    universe does not move with it."""
    cls = grip_class(idx)
    trunk = motorways.motorway_mask(idx, "any")
    cls = np.where(trunk & np.isin(cls, TRUNK_RAISED), TRUNK_FLOOR_CLASS, cls)
    return np.where(motorways.motorway_mask(idx, rule or motorways.RULE), MOTORWAY_CLASS, cls)


def city_distance(idx: NodeIndex) -> np.ndarray:
    """Per index cell, the distance to the nearest city in that city's
    built-up radii (sources/urban.scaled_city_distance), on the base grid and
    carried down."""
    if len(getattr(idx, "base_cells", [])):
        s, _pop = urban.scaled_city_distance(list(idx.base_cells))
        return refine.expand(s, idx)
    s, _pop = urban.scaled_city_distance(list(idx.cells))
    return s


def built_up_mask(idx: NodeIndex) -> np.ndarray:
    """The cells whose roads [urban] built_up_factor slows: inside a city's
    own built-up radius times built_up_extent."""
    return city_distance(idx) < urban.URBAN_BUILT_UP_EXTENT


def cell_income(idx: NodeIndex, country: np.ndarray | None = None) -> np.ndarray:
    """sources/countries.INCOME_GROUPS index per cell, from its country."""
    if country is None:
        country = countries.cell_country(idx.cells)
    return countries.cell_income_group(country)


def cell_speed_kmh(idx: NodeIndex, classes: np.ndarray | None = None,
                   country: np.ndarray | None = None) -> np.ndarray:
    """Effective ground speed per cell, indexed by cell position.

    `classes` is `cell_class(idx)` when the caller already has it: the build
    does (cli._build_all_locked), and deriving it again is a ~4 M-cell raster
    pass (PR-5).
    """
    # Footprint aggregation, NOT centroid sampling: an H3 cell's window spans 1-4
    # GRIP4 cells, and sampling the centre alone reports 51.5% of land roadless
    # against a true 29.3%, depressing mean ground speed from 36.8 to 23.9 km/h.
    if classes is None:
        classes = cell_class(idx)
    speeds = SPEED_BY_ROAD_CLASS_KMH[classes].astype(np.float64)
    # A motorway is priced by its signed limit (the highest among the OSM
    # ways crossing the cell), not one speed for every expressway: Cairo ->
    # Alexandria's desert motorway is signed 100-120 and drove at the speed
    # of the country's average one (rebuild 32: 214 min against 151).
    motorway = classes == MOTORWAY_CLASS
    if motorway.any():
        band = motorways.limit_band_of(motorways.motorway_limit(idx))
        speeds[motorway] = MOTORWAY_SPEED_BY_LIMIT_KMH[band[motorway]]
    # The same grade of road is driven faster in a rich country than a poor
    # one: one speed per class was 23% too slow on North American town
    # journeys and 24% too fast in low-income countries (2026-10-15 audit of
    # rebuild 30's fit). A fitted multiplier per World Bank income group, and
    # one for North America on top of its income group's (rebuild 33).
    if country is None:
        country = countries.cell_country(idx.cells)
    scaled = np.isin(classes, INCOME_SCALED_CLASSES)
    mult = (INCOME_SPEED_MULTIPLIER[cell_income(idx, country)]
            * REGION_SPEED_MULTIPLIER[countries.cell_driving_region(country)])
    speeds[scaled] *= mult[scaled]
    # GRIP4 gives a cell the grade of its BEST road, so a dense city cell with a
    # motorway through it is charged at motorway speed, and the hex path runs
    # straight across a city on those cells: London -> LHR went 22 km of
    # highway cells in 23 min against Google's 45. Inside a city's own
    # built-up radius, which scales with its population, the fitted factor
    # stands for the streets a journey actually takes.
    # Only where there are roads to be congested. A roadless cell is already at
    # walking pace, and traffic does not make walking slower.
    #
    # And a city's core a second time (rebuild 34): inside half its built-up
    # radius every departure ran slow -- 58 major airports from their city
    # centres came out 1.125 observed/model against 1.041 from towns around
    # them -- and the whole-radius factor could not price that without
    # slowing the suburbs ([urban] core_factor).
    near = city_distance(idx)
    roads = classes > 0
    speeds = np.where(roads & (near < urban.URBAN_BUILT_UP_EXTENT),
                      speeds / urban.URBAN_BUILT_UP_FACTOR, speeds)
    speeds = np.where(roads & (near < urban.URBAN_CORE_EXTENT),
                      speeds / urban.URBAN_CORE_FACTOR, speeds)
    return speeds


def cell_zones(country) -> np.ndarray:
    """Immigration zone per cell from its ISO3 country ("" where none)."""
    return np.array([transfers.immigration_zone(countries.iso2(c)) if c else ""
                     for c in country])


#: Border-control port areas on land Natural Earth does not draw, whose cells
#: therefore took a neighbour's country (countries._fill_blanks) and with it a
#: zone that charged a second crossing. (name, (lat_min, lat_max, lon_min,
#: lon_max), zone, why, source). Only cells whose centroid is in no country
#: polygon are relabelled; land the polygons do cover keeps its own zone.
#:
#: A third zone between two cannot be priced exactly on edges alone: no entry
#: and exit charge on such a run gives one crossing from A to B and none from
#: A back to A (that needs a copy of the run per zone). A run-wide "transit"
#: rule tried on 2026-10-16 marked 9,896 cells along borders and slowed 13 M
#: cells from Hong Kong by up to 161 min, so the cases are listed, each with
#: the zone that makes its real traffic pay one crossing.
PORT_ZONES = (
    ("Hong Kong-Zhuhai-Macau Bridge: the Zhuhai-Macau port island, its "
     "landing and its link to Macau",
     (22.205, 22.252, 113.560, 113.630), "HK",
     "The bridge lands on a reclaimed island where Zhuhai and Macau both clear "
     "arrivals from Hong Kong; its cells took China from Zhuhai, so Hong Kong "
     "-> Macau paid HK -> CN -> MO, 90 min of border (2 h 40 against ~1 h 57, "
     "2026-10-16). In Hong Kong's zone, the bridge's far end, a journey from "
     "Hong Kong to either city pays one crossing; Zhuhai <-> Macau keeps its "
     "own land border at Gongbei, which does not cross the island.",
     "https://en.wikipedia.org/wiki/Hong_Kong%E2%80%93Zhuhai%E2%80%93Macau_Bridge"),
    ("Head of the Gulf of Aqaba, off Eilat",
     (29.475, 29.508, 34.925, 34.965), "IL",
     "Egypt and Jordan share no land border: between them 'a small strip of "
     "Israeli territory juts out' at Eilat, and the land route runs Taba "
     "crossing -> Eilat -> Wadi Araba crossing. The sea cells at the head of "
     "the gulf took Egypt and Jordan from their shores, so Taba -> Aqaba "
     "crossed EG -> JO once, straight over the water (64 min, rebuild 33). In "
     "Israel's zone a journey round the head pays both crossings it really "
     "pays, and Egypt -> Israel and Israel -> Jordan still pay one each.",
     "https://en.wikipedia.org/wiki/Gulf_of_Aqaba"),
    ("Mid Gulf of Aqaba, where the Egyptian and Jordanian fills meet",
     (29.378, 29.410, 34.868, 34.922), "IL",
     "The 1:10m land mask takes the narrow gulf's cells as land and the fill "
     "splits them down the middle, Egypt to the west and Jordan to the east, so "
     "the graph had an Egypt - Jordan land border in mid-gulf (29.38-29.41 N) "
     "that no road crosses: with the head of the gulf fixed above, Taba -> "
     "Aqaba took it at one crossing (88 min). The four cells where the two "
     "fills meet, in Israel's zone, make that shortcut pay both crossings the "
     "road round the head pays. The coastal cells keep their country, so a "
     "journey along either coast is unchanged.",
     "https://en.wikipedia.org/wiki/Gulf_of_Aqaba"),
    ("Gibraltar's North Mole, the Tanger Med ferry berth",
     (36.150, 36.162, -5.372, -5.358), "GI",
     "The Gibraltar - Tanger Med ferry (FRS/DFDS, one to two a week) berths at "
     "the North Mole, reclaimed land Natural Earth's coast leaves at sea; its "
     "cell took Spain from La Linea, so Gibraltar -> Tangier by that ferry "
     "paid GI -> ES at the land border and ES -> MA at sea (Gibraltar -> "
     "Tangier 249 min by Algeciras, rebuild 33). In Gibraltar's zone the "
     "ferry pays the one crossing it makes.",
     "https://www.ferryhopper.com/en/ferry-routes/direct/gibraltar-tangier"),
)


def _sea_centroid(cells: list[str]) -> np.ndarray:
    """True per cell whose centroid is in no country polygon."""
    import shapely
    from shapely import STRtree

    geoms, _codes = countries._polygons()
    ll = np.array([h3.cell_to_latlng(c) for c in cells]).reshape(-1, 2)
    hit, _ = STRtree(geoms).query(shapely.points(ll[:, 1], ll[:, 0]), predicate="within")
    out = np.ones(len(cells), dtype=bool)
    out[np.unique(hit)] = False
    return out


def port_zones(idx) -> dict[int, str]:
    """Graph position -> zone for the PORT_ZONES cells: index cells (either
    resolution) with their centroid inside a row's box and in no country."""
    found: dict[int, str] = {}
    for _name, (lat0, lat1, lon0, lon1), zone, _why, _src in PORT_ZONES:
        poly = h3.LatLngPoly([(lat0, lon0), (lat0, lon1), (lat1, lon1), (lat1, lon0)])
        cand = []
        for res in (config.SOLVE_RES, config.FINE_RES):
            for c in h3.polygon_to_cells(poly, res):
                pos = idx.try_cell_index(c)
                if pos is not None:
                    cand.append((pos, c))
        if not cand:
            continue
        sea = _sea_centroid([c for _, c in cand])
        for (pos, _c), is_sea in zip(cand, sea, strict=True):
            if is_sea:
                found[pos] = zone
    return found


def zones_at(idx, country) -> np.ndarray:
    """The zone per cell the edge builders charge borders by: cell_zones, with
    PORT_ZONES applied."""
    zone = cell_zones(country)
    over = port_zones(idx)
    if over:
        width = max(zone.dtype.itemsize // 4, max(len(z) for z in over.values()))
        zone = zone.astype(f"<U{width}")
        for pos, z in over.items():
            zone[pos] = z
        logger.info("%d cell(s) given a border port's zone (PORT_ZONES)", len(over))
    return zone


def hex_edges(idx: NodeIndex, speeds: np.ndarray | None = None,
              country: np.ndarray | None = None, zone: np.ndarray | None = None
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Directed edges between adjacent land cells, weighted in minutes.

    Traversing from u into v is charged at v's speed, so slow terrain costs you
    on entry regardless of which side you approach from.

    `speeds`, `country` and `zone` are computed here when not given. The build
    computes them once and passes them down (graph/build.build_graph): each is
    a pass over ~10 M cells, and they were being derived four times over before
    the first origin was solved (PR-5).
    """
    if speeds is None:
        speeds = cell_speed_kmh(idx, country=country)
    centroids = np.array([h3.cell_to_latlng(c) for c in idx.cells], dtype=np.float64)

    # Adjacency alone asserts that every border on Earth can be walked across.
    # Some cannot, and a road route through the inter-Korean border made Seoul
    # reachable overland from Vladivostok.
    if country is None:
        country = countries.cell_country(idx.cells)
    if zone is None:
        zone = zones_at(idx, country)
    crossing_min = _land_border_min()

    # Preallocated: at 82 million edges, three Python lists peaked at 19 GB
    # in the build's parent process, which five forked workers then inherit.
    cap = EDGE_SLOTS_PER_CELL * len(idx.cells)
    rows = np.empty(cap, dtype=np.int32)
    cols = np.empty(cap, dtype=np.int32)
    extra = np.zeros(cap, dtype=np.float64)
    m = 0
    blocked = 0
    severed_edges = 0
    crossings = 0
    fine_attr = getattr(idx, "fine", np.zeros(0, dtype=bool))
    fine = fine_attr if len(fine_attr) == len(idx.cells) else np.zeros(len(idx.cells), dtype=bool)
    # Neighbours with open water between them and no bridge or tunnel
    # (graph/landmass). Empty when the fixed-link extracts are absent.
    severed = getattr(idx, "severed", frozenset())

    def add(u: int, v: int) -> None:
        nonlocal blocked, severed_edges, crossings, m
        if countries.is_closed(country[u], country[v]):
            blocked += 1
            return
        if (u, v) in severed:
            severed_edges += 1
            return
        if m >= cap:
            raise RuntimeError(
                f"ground edge capacity exceeded: more than {EDGE_SLOTS_PER_CELL} edges per "
                f"cell over {len(idx.cells):,} cells; raise EDGE_SLOTS_PER_CELL after "
                "measuring the new split fraction")
        rows[m] = u
        cols[m] = v
        if zone[u] and zone[v] and zone[u] != zone[v]:
            extra[m] = crossing_min
            crossings += 1
        m += 1

    # A fine cell's ring neighbour may lie in an unsplit base cell; then the
    # fine cell and that base cell are adjacent, in both directions. Several
    # of the ring neighbours can share one base parent, so the pair is added
    # once -- coo_matrix SUMS duplicates, which would double the weight.
    cross: set[tuple[int, int]] = set()
    for u, cell in enumerate(idx.cells):
        for neighbour in h3.grid_ring(cell, 1):
            v = idx.try_cell_index(neighbour)
            if v is not None:
                add(u, v)
            elif fine[u]:
                v = idx.try_cell_index(h3.cell_to_parent(neighbour, config.SOLVE_RES))
                if v is not None and (u, v) not in cross:
                    cross.add((u, v))
                    add(u, v)
                    add(v, u)
    rows, cols, extra = rows[:m], cols[:m], extra[:m]
    if blocked:
        logger.info("%d ground edge(s) cut at closed land borders", blocked)
    if severed_edges:
        logger.info("%d ground edge(s) cut across open water with no bridge or tunnel",
                    severed_edges)
    if crossings:
        logger.info("%d ground edge(s) charged %.0f min for a border crossing",
                    crossings, crossing_min)

    r = rows.astype(np.int64)
    c = cols.astype(np.int64)
    dist_km = haversine_km(centroids[r], centroids[c])
    minutes = dist_km / speeds[c] * 60.0 + extra
    return r, c, minutes


def haversine_km(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Great-circle distance between arrays of (lat, lon).

    Public: `graph/build._ferry_edges` calls it. It used to say "rail and ferry
    use it", and rail does not -- `graph/rail.py` has no import of this module
    at all and carries its own `_haversine_km` with a different signature and
    the same formula. Anyone who trusted the old sentence and changed the
    distance maths here would have missed rail entirely.
    """
    lat1, lon1 = np.radians(a[:, 0]), np.radians(a[:, 1])
    lat2, lon2 = np.radians(b[:, 0]), np.radians(b[:, 1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(h))

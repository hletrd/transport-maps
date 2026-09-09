import maplibregl from "./vendor/maplibre-gl.js";
import * as pmtiles from "./vendor/pmtiles.js";
import * as h3 from "./vendor/h3.js";

// Sequential ramps, brightest where the journey is shortest. Multi-hue on
// purpose: a SINGLE hue cannot separate eleven bands on a dark ground.
// Measured adjacent-pair separation in OKLab (x100) -- below about 8 two bands
// are hard to tell apart at all. The earlier single-hue amber sat at 4.4-4.8
// throughout, which is why China and Siberia read as one flat mass.
// Lightness is strictly monotonic in all three, which is what a sequential
// ramp actually requires; hue rotation supplies the separation lightness
// alone cannot.

const BG = "#0a0b0d", SEA = "#0f1114";
// Land no scheduled service reaches. A tone, not a colour: it must read as
// "no route" rather than as the far end of the time ramp.
const UNCHARTED = "#4a4d50";
// Space behind the globe: darker than every scheme's sea (measured by
// scripts/check_ramps.py), which is what lets the globe's edge be seen.
const SPACE = "#050609";
const UNREACHABLE_BAND = -1;

const $ = (id) => document.getElementById(id);
const proto = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", proto.tile);

const meta = await (await fetch("./index.json")).json();
const UNREACHABLE = meta.unreachable ?? 65535;
const HOVER_RES = meta.hoverRes ?? 4;
// The surface is solved per res-5 cell (~8 km); the readout array is res 4
// (~22 km, the min of seven children) to stay small. The highlight must show
// the SOLVED cell -- outlining the readout parent drew a hexagon seven times
// the size of anything the map was actually computed from.
const SOLVE_RES = meta.solveRes ?? 5;
const EDGES = meta.bandEdgesMin ?? [];

// shared, origin-independent cell ordering — fetched once
const hoverCells = new BigUint64Array(
  await (await fetch("./" + (meta.hoverCellsUrl || "hover_cells.bin"))).arrayBuffer()
);
const RAMPS = {
  // Adjacent-pair separation measured in OKLab (x100); below about 8 two bands
  // are hard to tell apart. Lightness is strictly monotonic in every ramp,
  // which is what a sequential scale actually requires. `sea` is the scheme's
  // own water: darker than its darkest band, lighter than space, so the globe
  // stands off the page. scripts/check_ramps.py measures all of this.
  muted:    { name: "Muted",    sea: "#171a22", c: ["#faefc5","#f6d59d","#f5b87c","#ef9b6a","#e38065","#cf6a6a","#b35a6f","#934e6e","#724566","#543b57","#3a2c4b"] },
  vivid:    { name: "Vivid",    sea: "#15122c", c: ["#fff7a8","#ffd557","#ffad19","#ff8200","#ff5327","#fe1d59","#df0a7c","#b3218b","#842f88","#563275","#2b2764"] },
  warm:     { name: "Warm",     sea: "#1e1512", c: ["#fbeec9","#f5d7a0","#efbe78","#e7a457","#db8b3f","#ca7335","#b46036","#99523b","#7c463c","#613a38","#4b2b2e"] },
  ice:      { name: "Ice",      sea: "#0f172b", c: ["#eaf6fb","#c3e4f4","#9cd2ec","#76bee3","#52a9d7","#3893c7","#277cb2","#1f6699","#1e5080","#203d62","#212a46"] },
  forest:   { name: "Forest",   sea: "#101c15", c: ["#f2f6da","#d7e9ae","#b8d98a","#96c76e","#73b45c","#549f52","#3e894a","#317244","#2b5c3c","#274630","#233126"] },
  mono:     { name: "Mono",     sea: "#17181b", c: ["#f4f4f4","#dddddd","#c6c6c6","#b0b0b0","#9a9a9a","#858585","#717171","#5d5d5d","#4a4a4a","#373737","#262626"] },
  ember:    { name: "Ember",    sea: "#1d1414", c: ["#fff3c4","#ffd787","#ffb556","#ff9031","#fa691d","#e64415","#c52d19","#a0201d","#7c1b22","#571a28","#331a2b"] },
  rose:     { name: "Rose",     sea: "#1c141b", c: ["#fde9ef","#f9cad9","#f5abc5","#ed8cb3","#df6da1","#cb5190","#af3c80","#902d70","#70255f","#50214d","#31203a"] },
  sand:     { name: "Sand",     sea: "#1b1711", c: ["#fbf3e2","#eedfb8","#e1c991","#d3b270","#c29a56","#b08443","#9b7035","#845d2d","#6c4c2b","#553d27","#3d2e23"] },
  twilight: { name: "Twilight", sea: "#131629", c: ["#fdf5a6","#d8e48d","#abd48c","#7fc391","#5aaf98","#44989c","#38809b","#346794","#364e84","#34366c","#2c264a"] },
  copper:   { name: "Copper",   sea: "#1c1512", c: ["#fff0e0","#f8d6bd","#efbc9b","#e4a27c","#d68960","#c47148","#ae5c37","#95492b","#7a3b2a","#5d3026","#422523"] },
  lavender: { name: "Lavender", sea: "#161426", c: ["#f5f0fb","#e2d7f5","#cfbfee","#bba7e5","#a690d9","#9179ca","#7c64b8","#6750a3","#523f89","#3f316b","#2e264c"] },
};

let rampName = "muted";

// Bands are as many as index.json says (37 now, on a geometric ladder), and
// each scheme is eleven control points. Colors are interpolated in OKLab so
// the gradient is perceptually even; interpolating hex channels would dip
// through muddy grays between hues.
function hexToOklab(h) {
  const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  const l = Math.cbrt(0.4122214708 * c[0] + 0.5363325363 * c[1] + 0.0514459929 * c[2]);
  const m = Math.cbrt(0.2119034982 * c[0] + 0.6806995451 * c[1] + 0.1073969566 * c[2]);
  const s = Math.cbrt(0.0883024619 * c[0] + 0.2817188376 * c[1] + 0.6299787005 * c[2]);
  return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
          1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
          0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s];
}
function oklabToHex([L, a, b]) {
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.2914855480 * b;
  const l = l_ ** 3, m = m_ ** 3, s = s_ ** 3;
  const rgb = [ 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
               -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
               -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s]
    .map((v) => Math.max(0, Math.min(1, v)))
    .map((v) => (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055))
    .map((v) => Math.round(v * 255).toString(16).padStart(2, "0"));
  return "#" + rgb.join("");
}
function expandRamp(control, n) {
  const lab = control.map(hexToOklab);
  return Array.from({ length: n }, (_, i) => {
    const t = (i / (n - 1)) * (lab.length - 1);
    const k = Math.min(Math.floor(t), lab.length - 2), f = t - k;
    return oklabToHex(lab[k].map((v, j) => v + (lab[k + 1][j] - v) * f));
  });
}
const N_BANDS = (meta.bandEdgesMin?.length ?? 10) + 1;
let BANDS = expandRamp(RAMPS[rampName].c, N_BANDS);

let hoverTimes = null;          // Uint16Array for the active origin
let hoverAir = null;            // arrival-airport ordinal per hover cell
let hoverModes = null;          // rail / ferry / road minutes per hover cell
let routes = null;              // {offsets, byId} for walking the leg chain
let active = null;
const NO_AIRPORT = 0xFFFF;

// ---- settings, remembered per viewer ----
const store = {
  get(k, d) {
    try { const v = localStorage.getItem(k); return v === null ? d : v === "1"; }
    catch { return d; }
  },
  set(k, v) { try { localStorage.setItem(k, v ? "1" : "0"); } catch { /* private mode */ } },
};
try { const r = localStorage.getItem("ramp"); if (r && RAMPS[r]) { rampName = r; BANDS = expandRamp(RAMPS[r].c, N_BANDS); } }
catch { /* private mode */ }
let lockNorth = store.get("lockNorth", false);
let namePlaces = store.get("namePlaces", true);

// ---- legend ----
function paintLegend() {
  $("tints").replaceChildren(...BANDS.map((c) => {
    const s = document.createElement("span"); s.style.background = c; return s;
  }));
}
paintLegend();

// Segments are equal width but the time scale is not linear, so a tick must sit
// at its own band boundary. Placing evenly spaced labels under uneven bands is
// how a legend ends up lying about the thing it explains.
const SHOWN_HOURS = [1, 2, 4, 8, 16, 24, 48, 72];
$("scale").replaceChildren(...EDGES.flatMap((mins, i) => {
  const hours = mins / 60;
  // Edges sit on a geometric ladder, so a round hour may not fall exactly on
  // one; label the nearest edge to each and skip duplicates.
  const nearest = SHOWN_HOURS.find((h) => Math.abs(hours - h) / h < 0.08);
  if (nearest == null || EDGES.findIndex((e) => Math.abs(e / 60 - nearest) / nearest < 0.08) !== i) return [];
  const el = document.createElement("span");
  el.style.left = `${((i + 1) / BANDS.length) * 100}%`;
  el.textContent = nearest === 72 ? "72+" : String(nearest);
  return [el];
}));

$("credits").textContent = (meta.attribution ?? [])
  .map((s) => `${s.name} (${s.licence})`)
  .join(" · ") || "Attribution missing from index.json.";

// ---- gazetteer, so a reading can name where it is ----
let places = null;
fetch("./places.json")
  .then((r) => (r.ok ? r.json() : null))
  .then((p) => {
    if (!p) return;
    // Flat typed arrays: 7,000 objects would be re-read on every pointer move.
    places = {
      lat: Float32Array.from(p.places, (x) => x[3]),
      lon: Float32Array.from(p.places, (x) => x[4]),
      rows: p.places,
    };
    // Labels, so a zoomed view says roughly where it is. DOM markers rather
    // than a symbol layer: MapLibre text needs a glyph server, which the CSP
    // blocks, and markers render in the page's own typeface. The gazetteer is
    // ordered largest-first, so rank is the row index; more labels appear as
    // the zoom rises.
    const labelPool = p.places.slice(0, 900).map((r, i) => {
      // A label that names one of the departure cities is a button: clicking
      // it departs from there. Matched by distance, since the gazetteer and
      // origins.toml spell a few names differently.
      const origin = originNear(r[3], r[4]);
      const el = document.createElement(origin ? "button" : "div");
      el.className = origin ? "lbl origin" : "lbl";
      el.textContent = r[0];
      if (origin) {
        el.type = "button";
        el.title = `Depart from ${origin.name}`;
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();            // not a destination pin
          $("here").textContent = "";
          if (origin.slug !== active?.slug) paintOrigin(origin);
        });
      }
      const m = new maplibregl.Marker({ element: el, anchor: "top" })
        .setLngLat([r[4], r[3]]);
      return { m, rank: i, on: false };
    });
    const showLabels = () => {
      const z = map.getZoom();
      const n = z < 2.2 ? 0 : z < 3 ? 40 : z < 4 ? 120 : z < 5.5 ? 350 : 900;
      // Largest cities claim their screen space first; a smaller one whose
      // label would land within the gap of one already placed is skipped, so
      // the map thins itself rather than piling names on top of each other.
      const placed = [];
      const gapX = 70, gapY = 16;
      // A DOM marker does not know the globe hides its far side: project()
      // happily returns on-disc coordinates for Lima while the view faces
      // Beijing. Anything more than ~85 degrees of arc from the view centre
      // is behind the horizon and must not be drawn.
      const ctr = map.getCenter();
      const rad = Math.PI / 180;
      const sinC = Math.sin(ctr.lat * rad), cosC = Math.cos(ctr.lat * rad);
      const onNearSide = (ll) => {
        const cosArc = sinC * Math.sin(ll.lat * rad)
          + cosC * Math.cos(ll.lat * rad) * Math.cos((ll.lng - ctr.lng) * rad);
        return cosArc > Math.cos(85 * rad);
      };
      for (const l of labelPool) {
        let want = l.rank < n && onNearSide(l.m.getLngLat());
        if (want) {
          const pt = map.project(l.m.getLngLat());
          want = pt.x > -50 && pt.y > -20 && pt.x < window.innerWidth + 50
              && pt.y < window.innerHeight + 20
              && !placed.some((q) => Math.abs(q.x - pt.x) < gapX && Math.abs(q.y - pt.y) < gapY);
          if (want) placed.push(pt);
        }
        if (want && !l.on) { l.m.addTo(map); l.on = true; }
        else if (!want && l.on) { l.m.remove(); l.on = false; }
      }
    };
    // On every frame of a move, not only at rest: otherwise nothing appears
    // during a zoom-in until it stops, and a rotation can drag far-side
    // labels into view before the moveend filter removes them.
    let pending = 0;
    const onMove = () => {
      if (pending) return;
      pending = requestAnimationFrame(() => { pending = 0; showLabels(); });
    };
    map.on("move", onMove);
    showLabels();
  })
  .catch(() => { /* the map is still readable without names */ });

function nearestPlace(lat, lon) {
  if (!places) return null;
  const rad = Math.PI / 180;
  const cosLat = Math.cos(lat * rad);
  let best = -1, bestD = Infinity;
  for (let i = 0; i < places.lat.length; i++) {
    // Equirectangular is plenty to rank candidates and avoids 7,000 trig calls.
    const dy = places.lat[i] - lat;
    const dx = (places.lon[i] - lon) * cosLat;
    const d = dy * dy + dx * dx;
    if (d < bestD) { bestD = d; best = i; }
  }
  if (best < 0) return null;
  const [name, region, country] = places.rows[best];
  const km = Math.sqrt(bestD) * 111.32;
  return { name, region, country, km };
}

// ---- globe ----
const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8, sources: {}, layers: [
      { id: "space", type: "background", paint: { "background-color": BG } }
    ],
    sky: { "sky-color": BG, "horizon-color": "#1b1f26", "fog-color": BG }
  },
  center: [30, 22], zoom: 1.35, minZoom: 0.6, maxZoom: 11,
  // The globe projection can look at the poles; the default latitude
  // clamp is a Mercator constraint that does not apply here.
  maxPitch: 0, renderWorldCopies: false,
  attributionControl: false, dragRotate: true
});

await new Promise((r) => map.on("load", r));
// For scripts/browser_verify.sh only: lets the post-deploy check ask the map
// whether the water layer actually rendered rather than trusting a 200.
window.__map = map;
// MapLibre is pinned to 5.24 (see web/README.md); this is its projection API.
map.setProjection({ type: "globe" });
// A faint atmosphere at the limb, so the globe's edge reads against space
// even where the sea is nearly as dark. Fades out once the horizon leaves
// the screen.
map.setSky({
  "sky-color": SPACE, "horizon-color": "#2a3346", "fog-color": SPACE,
  "fog-ground-blend": 0, "horizon-fog-blend": 0.8, "sky-horizon-blend": 0.9,
  "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 0.75, 3, 0.6, 6, 0]
});

map.addSource("sphere", { type: "geojson", data: { type: "Feature", geometry: { type: "Polygon",
  coordinates: [[[-180,-90],[180,-90],[180,90],[-180,90],[-180,-90]]] } } });
map.addLayer({ id: "sphere", type: "fill", source: "sphere",
  paint: { "fill-color": SEA, "fill-opacity": 1 } });

// The coast. Bands are painted one cell past the shore (contour/grid.py) and
// this static water layer, built once from OpenStreetMap coastlines, cuts
// them back to the real outline. It sits above the bands and below the
// borders and the cursor; paintOrigin inserts each origin's bands beneath it.
map.addSource("water", { type: "vector", url: "pmtiles://./water.pmtiles" });
map.addLayer({ id: "water", type: "fill", source: "water", "source-layer": "water",
  paint: { "fill-color": SEA, "fill-opacity": 1 } });
// Sea and lakes take the colour scheme's own ground, so switching schemes
// recolours the water as well as the land.
function paintSea() {
  const sea = RAMPS[rampName]?.sea ?? SEA;
  for (const id of ["sphere", "water"])
    if (map.getLayer(id)) map.setPaintProperty(id, "fill-color", sea);
}
paintSea();

// The hovered cell, outlined so the reading has a visible footprint.
map.addSource("hover", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
map.addLayer({ id: "hover-line", type: "line", source: "hover",
  paint: { "line-color": "#ffffff", "line-width": 1.5, "line-opacity": 0.85 } });
map.addLayer({ id: "hover-fill", type: "fill", source: "hover",
  paint: { "fill-color": "#ffffff", "fill-opacity": 0.10 } });

// Your own position, once geolocation answers.
map.addSource("me", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
map.addLayer({ id: "me-halo", type: "circle", source: "me",
  paint: { "circle-radius": 9, "circle-color": "#ffffff", "circle-opacity": 0.18 } });
map.addLayer({ id: "me-dot", type: "circle", source: "me",
  paint: { "circle-radius": 4, "circle-color": "#ffffff",
           "circle-stroke-color": "#0a0b0d", "circle-stroke-width": 1.5 } });

// International boundaries, drawn above the bands and below the labels.
fetch("./borders.json").then((r) => (r.ok ? r.json() : null)).then((g) => {
  if (!g) return;
  map.addSource("borders", { type: "geojson", data: g });
  // Appended on top: this fetch resolves AFTER paintOrigin has added the
  // bands, so inserting before "hover-line" put the borders under them and
  // they were invisible. Add last, then lift the hover and position layers
  // back above.
  map.addLayer({ id: "borders", type: "line", source: "borders",
    paint: { "line-color": "#ffffff", "line-opacity": 0.42,
             "line-width": ["interpolate", ["linear"], ["zoom"], 1, 0.6, 5, 1.1] } });
  for (const id of ["hover-fill", "hover-line", "me-halo", "me-dot"])
    if (map.getLayer(id)) map.moveLayer(id);
}).catch(() => {});

let hoveredCell = null;
function highlight(lat, lon) {
  const cell = h3.latLngToCell(lat, lon, SOLVE_RES);
  if (cell === hoveredCell) return;
  hoveredCell = cell;
  const ring = h3.cellToBoundary(cell).map(([la, lo]) => [lo, la]);
  ring.push(ring[0]);
  map.getSource("hover").setData({ type: "FeatureCollection", features: [
    { type: "Feature", geometry: { type: "Polygon", coordinates: [ring] } }] });
}
function clearHighlight() {
  hoveredCell = null;
  map.getSource("hover").setData({ type: "FeatureCollection", features: [] });
}

function applyLockNorth() {
  if (lockNorth) {
    map.setBearing(0);
    map.setPitch(0);
    map.dragRotate.disable();
    map.touchZoomRotate.disableRotation();
    map.keyboard.disableRotation();
  } else {
    map.dragRotate.enable();
    map.touchZoomRotate.enableRotation();
    map.keyboard.enable();
  }
  syncNeedle();
}

function syncNeedle() {
  $("needle").setAttribute("transform", `rotate(${-map.getBearing()})`);
}
map.on("rotate", syncNeedle);

function bandColorExpression() {
  return ["match", ["get", "band"],
    UNREACHABLE_BAND, UNCHARTED,
    ...BANDS.flatMap((c, i) => [i, c]), UNCHARTED];
}

function paintOrigin(o) {
  active = o;
  for (const id of ["band-seams", "bands"]) if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource("bands")) map.removeSource("bands");

  map.addSource("bands", { type: "vector", url: `pmtiles://./origins/${o.slug}.pmtiles` });
  map.addLayer({
    id: "bands", type: "fill", source: "bands", "source-layer": "bands",
    // Neighbouring bands overlap by one cell (see contour/bands.py) and the
    // faster one must win, so paint slow to fast: higher sort key draws
    // later. Unreachable land goes underneath everything.
    layout: {
      "fill-sort-key": ["case", ["<", ["get", "band"], 0], -1000, ["-", ["get", "band"]]]
    },
    paint: {
      "fill-color": bandColorExpression(),
      "fill-opacity": 1
    }
  }, "water");

  hoverTimes = null;
  fetch(`./origins/${o.slug}.bin`)
    .then((r) => {
      if (!r.ok) throw new Error(`${r.status} fetching ${o.slug}.bin`);
      return r.arrayBuffer();
    })
    .then((b) => { hoverTimes = new Uint16Array(b); renderPins(); renderLegs(); })
    .catch((err) => {
      console.error("hover data unavailable:", err);
      $("where").textContent = `Hover data unavailable for ${o.name}.`;
    });

  // The leg breakdown is a progressive extra: an origin built before these
  // files existed still shows times, just without the itinerary.
  hoverAir = null; routes = null; hoverModes = null;
  fetch(`./origins/${o.slug}.modes.bin`)
    .then((r) => (r.ok ? r.arrayBuffer() : null))
    .then((b) => { if (b) hoverModes = new Uint16Array(b); renderLegs(); })
    .catch(() => {});
  fetch(`./origins/${o.slug}.air.bin`)
    .then((r) => (r.ok ? r.arrayBuffer() : null))
    .then((b) => { if (b) hoverAir = new Uint16Array(b); renderLegs(); })
    .catch(() => {});
  fetch(`./origins/${o.slug}.json`)
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      if (!j) return;
      routes = { offsets: j.offsets, byId: new Map(j.nodes.map((n) => [n.id, n])) };
      renderLegs();
    })
    .catch(() => {});

  map.flyTo({ center: [o.lon, o.lat], zoom: 1.9, speed: 0.75, curve: 1.5 });
  for (const b of document.querySelectorAll(".results button"))
    b.setAttribute("aria-current", String(b.dataset.slug === o.slug));
  $("origin-name").textContent = o.name;
  renderPins();
}

// ---- readout ----
const fmtCoord = (lat, lon) =>
  `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? "N" : "S"} ${Math.abs(lon).toFixed(2)}°${lon >= 0 ? "E" : "W"}`;

function fmtTime(min) {
  if (min == null) return ["—", ""];
  if (min >= UNREACHABLE) return ["∞", "no route"];
  const h = Math.floor(min / 60), m = Math.round(min % 60);
  if (h < 1) return [String(m), "min"];
  if (h < 48) return [String(h), m ? `h ${String(m).padStart(2,"0")}m` : "h"];
  return [String(Math.floor(h / 24)), `days ${h % 24}h`];
}

function cellIndex(lat, lon) {
  const id = BigInt("0x" + h3.latLngToCell(lat, lon, HOVER_RES));
  let lo = 0, hi = hoverCells.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1, v = hoverCells[mid];
    if (v === id) return mid;
    if (v < id) lo = mid + 1; else hi = mid - 1;
  }
  return -1;                          // ocean, or outside the land mask
}

function lookup(lat, lon) {
  if (!hoverTimes) return null;
  const i = cellIndex(lat, lon);
  return i < 0 ? null : hoverTimes[i];
}

// Walk the shortest-path tree back from where the journey landed. The chain is
// cell -> A_dep -> B_arr -> B_dep -> C_arr, so a connection shows up as an
// arrival immediately followed by a departure at the same airport.
function legsTo(lat, lon) {
  if (!hoverAir || !routes) return null;
  const i = cellIndex(lat, lon);
  if (i < 0) return null;
  const ordinal = hoverAir[i];
  if (ordinal === NO_AIRPORT) return [];        // overland the whole way

  const { cells, airports, stations } = routes.offsets;
  const count = (stations - airports) / 2;      // departures AND arrivals
  let node = routes.byId.get(airports + count + ordinal);
  const chain = [];
  while (node && chain.length < 24) {
    chain.push(node);
    node = node.prev == null ? null : routes.byId.get(node.prev);
  }
  return chain.reverse();
}

function renderLegs() {
  const box = $("legs");
  if (!pinB) { box.hidden = true; return; }

  const total = lookup(pinB.lat, pinB.lon);
  const chain = legsTo(pinB.lat, pinB.lon);
  if (total == null || total >= UNREACHABLE || chain == null) { box.hidden = true; return; }

  const rows = [];
  const dur = (m) => { const [b, u] = fmtTime(m); return `${b}${u ? " " + u : ""}`; };
  // A code like SHE or FNJ means nothing to most readers: hovering it names
  // the airport and its country. Modes explain how they were modelled.
  const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  const ap = (code) => {
    const a = airports.find((x) => x[0] === code);
    return a ? `<span class="ap" tabindex="0" data-tip="${esc(a[1])}, ${esc(a[2])}">${code}</span>` : code;
  };
  const mode = (name) => {
    const tip = meta.modeDetail?.[name];
    return tip ? `<span class="mode" tabindex="0" data-tip="${esc(tip)}">${name}</span>` : name;
  };

  // "Surface transport, 5 h" says nothing useful. Rail, road and ferry differ
  // enormously in what they imply, and the surface leg is a large share of most
  // journeys, so name the three separately when the data is there.
  const surface = () => {
    if (!hoverModes) return [];
    const i = cellIndex(pinB.lat, pinB.lon);
    if (i < 0) return [];
    const names = ["rail", "ferry", "highway", "major road", "minor road", "track"];
    const n = names.length;
    return names.map((name, k) => [name, hoverModes[i * n + k]])
      .filter(([, m]) => m >= 1)
      .sort((a, b) => b[1] - a[1])
      .map(([name, m]) => [dur(m), `by <b>${mode(name)}</b>`]);
  };

  if (chain.length === 0) {
    // No flight was involved. Saying "overland" would be a claim we cannot
    // support: the journey may well have gone by rail or ferry, both of which
    // are in the graph but are not itemised here -- listing them would mean
    // shipping 57,000 station nodes per origin to name a handful of them.
    const parts = surface();
    if (parts.length) rows.push(...parts);
    else rows.push([dur(total), "No flight on this route — surface travel"]);
  } else {
    rows.push([dur(chain[0].min), `To <b>${ap(chain[0].code)}</b>, and through the airport`]);
    for (let k = 1; k < chain.length; k++) {
      const a = chain[k - 1], b = chain[k];
      const t = dur(b.min - a.min);
      if (b.kind === "arr") rows.push([t, `Fly <b>${ap(a.code)} → ${ap(b.code)}</b>`]);
      else rows.push([t, `Connect at <b>${ap(b.code)}</b>`]);
    }
    const landed = chain[chain.length - 1];
    if (total > landed.min) {
      const parts = surface();
      if (parts.length) {
        rows.push([dur(total - landed.min), `Onward from <b>${ap(landed.code)}</b>, of which:`]);
        rows.push(...parts);
      } else {
        rows.push([dur(total - landed.min),
                   `From <b>${ap(landed.code)}</b> onward by surface transport`]);
      }
    }
  }
  rows.push([dur(total), "Door to door", true]);

  const frag = document.createDocumentFragment();
  const h = document.createElement("h2");
  h.textContent = "Route";
  frag.append(h);
  for (const [t, text, isTotal] of rows) {
    const d = document.createElement("div");
    d.className = isTotal ? "leg total" : "leg";
    const ts = document.createElement("span"); ts.className = "t"; ts.textContent = t;
    const ds = document.createElement("span"); ds.className = "d"; ds.innerHTML = text;
    d.append(ts, ds); frag.append(d);
  }
  box.replaceChildren(frag);
  box.hidden = false;
}

// The painted band comes from the res-5 polygon actually under the cursor,
// while the time array is res-4 and takes the FASTEST of each cell's children.
// So the number can be optimistic against the colour it sits on. Reading the
// band from the rendered geometry costs nothing and lets the readout say which
// band you are in rather than quietly contradicting it.
function bandRangeAt(point) {
  if (!map.getLayer("bands")) return null;
  const hit = map.queryRenderedFeatures(point, { layers: ["bands"] });
  if (!hit.length) return null;
  // Bands overlap by a one-cell rim and the fastest is painted on top, so
  // the band under the cursor is the smallest non-negative one hit.
  let b = null;
  for (const h of hit) {
    const v = h.properties.band;
    if (v >= 0 && (b == null || v < b)) b = v;
  }
  if (b == null) b = hit[0].properties.band;
  if (b === UNREACHABLE_BAND) return "no scheduled route";
  const lo = b === 0 ? 0 : EDGES[b - 1] / 60;
  const hi = b < EDGES.length ? EDGES[b] / 60 : null;
  const f = (h) => (h < 10 ? h.toFixed(1).replace(/\.0$/, "") : Math.round(h));
  return hi == null ? `over ${f(lo)} h` : `${f(lo)}–${f(hi)} h`;
}

function describe(lat, lon) {
  if (!namePlaces) return fmtCoord(lat, lon);
  const p = nearestPlace(lat, lon);
  if (!p) return fmtCoord(lat, lon);
  const where = [p.region && p.region !== p.name ? p.region : null, p.country]
    .filter(Boolean).join(", ");
  // Beyond a couple of hundred kilometres the nearest town is not where you
  // are, so say "near" rather than implying the cursor is on it.
  const lead = p.km > 60 ? `near ${p.name}` : p.name;
  return `<b>${lead}</b>${where ? ` — ${where}` : ""}`;
}

let raf = 0;
map.on("mouseout", () => { $("tip").hidden = true; clearHighlight(); });
map.on("mousemove", (e) => {
  if (raf) return;
  raf = requestAnimationFrame(() => {
    raf = 0;
    const { lat, lng } = e.lngLat;
    const t = lookup(lat, lng);
    const [big, unit] = fmtTime(t);
    $("time").innerHTML = t == null ? "—" : `${big}<small>${unit}</small>`;
    const band = bandRangeAt(e.point);
    $("where").innerHTML = t == null
      ? "Open water."
      : `${describe(lat, lng)}<br>${fmtCoord(lat, lng)}`
        + `${band ? " · " + band : ""}${active ? " · from " + active.name : ""}`;

    const tip = $("tip");
    if (t == null) { tip.hidden = true; clearHighlight(); return; }
    highlight(lat, lng);
    const p = nearestPlace(lat, lng);
    const where = p ? (p.km > 60 ? `near ${p.name}` : p.name) + (p.country ? `, ${p.country}` : "")
                    : fmtCoord(lat, lng);
    tip.innerHTML = `<b>${big}${unit ? " " + unit : ""}</b> <i>${where}</i>`;
    tip.hidden = false;
    // Offset so the pointer never covers it; flip when near the right edge.
    const x = e.originalEvent.clientX, y = e.originalEvent.clientY;
    const w = tip.offsetWidth;
    tip.style.left = `${x + 16 + w > window.innerWidth ? x - w - 12 : x + 16}px`;
    tip.style.top = `${y + 14}px`;
  });
});

// ---- point to point ----
let pinB = null;

function renderPins() {
  const box = $("pins");
  if (!active) { box.replaceChildren(); return; }
  const rows = [["From", active.name]];
  if (pinB) {
    const t = lookup(pinB.lat, pinB.lon);
    const [big, unit] = fmtTime(t);
    rows.push(["To", pinB.label]);
    rows.push(["Time", t == null ? "not on land" : `${big} ${unit}`.trim()]);
  } else {
    rows.push(["To", "click the chart"]);
  }
  box.replaceChildren(...rows.map(([k, v]) => {
    const d = document.createElement("div");
    const ks = document.createElement("span"); ks.className = "k"; ks.textContent = k;
    const vs = document.createElement("span"); vs.className = "val"; vs.textContent = v;
    d.append(ks, vs); return d;
  }));
  // The clicked point can also become the departure, when a departure city
  // is near it. This is how you pick a city by clicking the chart.
  const near = pinB && originNear(pinB.lat, pinB.lon);
  if (near && near.slug !== active.slug) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "depart";
    b.textContent = `Depart from ${near.name}`;
    b.addEventListener("click", () => {
      $("here").textContent = "";
      pinB = null;
      paintOrigin(near);
    });
    box.append(b);
  }
}

map.on("click", (e) => {
  const { lat, lng } = e.lngLat;
  const p = nearestPlace(lat, lng);
  pinB = { lat, lon: lng, label: p ? (p.km > 60 ? `near ${p.name}` : p.name)
                                  : fmtCoord(lat, lng) };
  $("route").open = true;
  renderPins();
  renderLegs();
  reverseGeocode(lat, lng);
});

function haversineKm(la1, lo1, la2, lo2) {
  const r = Math.PI / 180, dLa = (la2 - la1) * r, dLo = (lo2 - lo1) * r;
  const a = Math.sin(dLa / 2) ** 2 + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dLo / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(a));
}
// Departure city within reach of a point, if any. 80 km covers a metro area
// without claiming the next city over.
function originNear(lat, lon, maxKm = 80) {
  let best = null, bestKm = maxKm;
  for (const o of meta.origins) {
    const km = haversineKm(lat, lon, o.lat, o.lon);
    if (km < bestKm) { best = o; bestKm = km; }
  }
  return best;
}

$("clear-pins").addEventListener("click", () => { pinB = null; renderPins(); renderLegs(); });

// ---- city and airport list ----
const cities = meta.origins.slice().sort((a, b) => a.name.localeCompare(b.name));
const bySlug = new Map(cities.map((c) => [c.slug, c]));
// Airports are searchable by code ("JFK") or name. Picking one drops it as the
// DESTINATION -- only the 157 cities have a computed surface to depart from.
let airports = [];
fetch("./airports.json")
  .then((r) => (r.ok ? r.json() : null))
  .then((a) => { if (a) airports = a.airports; })
  .catch(() => {});
function render(filter = "") {
  const f = filter.trim().toLowerCase();
  const hits = f ? cities.filter((c) => c.name.toLowerCase().includes(f)) : cities;
  const list = document.createDocumentFragment();

  // Airports first when the query looks like a code, so "jfk" is one keystroke
  // from the answer; otherwise after the cities.
  const apHits = f.length >= 2
    ? airports.filter((a) => a[0].toLowerCase() === f || a[1].toLowerCase().includes(f))
               .slice(0, 12)
    : [];
  const airportRows = apHits.map((a) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.dataset.airport = a[0];
    const name = document.createElement("span");
    name.innerHTML = `<b>${a[0]}</b> ${a[1]}`;
    const coord = document.createElement("span");
    coord.className = "coord";
    coord.textContent = `${a[2]} · destination`;
    b.append(name, coord); li.append(b);
    return li;
  });
  if (f.length === 3 && apHits.some((a) => a[0].toLowerCase() === f)) list.append(...airportRows);

  for (const c of hits) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.dataset.slug = c.slug;
    b.setAttribute("aria-current", String(active?.slug === c.slug));
    const name = document.createElement("span");
    name.textContent = c.name;
    const coord = document.createElement("span");
    coord.className = "coord";
    coord.textContent = `${c.lat.toFixed(1)}, ${c.lon.toFixed(1)}`;
    b.append(name, coord);
    li.append(b);
    list.append(li);
  }
  if (!(f.length === 3 && apHits.some((a) => a[0].toLowerCase() === f))) list.append(...airportRows);
  $("results").replaceChildren(list);
  scheduleAddressSearch(filter.trim());
}

// ---- address search ----
// Anything the local lists cannot answer goes to OpenStreetMap's Nominatim:
// a street, a landmark, a village. One request per pause in typing, never
// more than one a second, which is what its usage policy asks.
const NOMINATIM = "https://nominatim.openstreetmap.org";
let addressTimer = null, addressSeq = 0;
function scheduleAddressSearch(q) {
  clearTimeout(addressTimer);
  const old = $("results").querySelector(".addresses");
  if (old) old.remove();
  if (q.length < 4) return;
  addressTimer = setTimeout(() => searchAddress(q), 900);
}
async function searchAddress(q) {
  const seq = ++addressSeq;
  let hits = [];
  try {
    const r = await fetch(`${NOMINATIM}/search?format=jsonv2&limit=6&q=${encodeURIComponent(q)}`,
                          { headers: { "Accept-Language": navigator.language || "en" } });
    if (r.ok) hits = await r.json();
  } catch { return; }
  if (seq !== addressSeq || $("q").value.trim() !== q) return;   // stale
  const box = $("results");
  const old = box.querySelector(".addresses");
  if (old) old.remove();
  if (!hits.length) return;
  const ul = document.createElement("ul");
  ul.className = "addresses";
  const head = document.createElement("li");
  head.className = "head";
  head.textContent = "Addresses";
  ul.append(head);
  for (const h of hits) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.geo = `${h.lat},${h.lon}`;
    b.dataset.label = h.display_name;
    const name = document.createElement("span");
    name.textContent = h.display_name.split(",").slice(0, 3).join(",");
    const coord = document.createElement("span");
    coord.className = "coord";
    coord.textContent = h.display_name.split(",").slice(3).join(",").trim() || h.type;
    b.append(name, coord); li.append(b); ul.append(li);
  }
  const credit = document.createElement("li");
  credit.className = "credit";
  credit.textContent = "Search by Nominatim © OpenStreetMap contributors";
  ul.append(credit);
  box.append(ul);
}

// A clicked point gets a proper address, one request per click.
let reverseSeq = 0;
async function reverseGeocode(lat, lon) {
  const seq = ++reverseSeq;
  try {
    const r = await fetch(`${NOMINATIM}/reverse?format=jsonv2&zoom=14&lat=${lat}&lon=${lon}`,
                          { headers: { "Accept-Language": navigator.language || "en" } });
    if (!r.ok) return;
    const j = await r.json();
    if (seq !== reverseSeq || !pinB || pinB.lat !== lat) return;
    if (j.display_name) {
      const a = j.address || {};
      const short = [a.road || a.neighbourhood || a.suburb, a.city || a.town || a.village || a.county, a.state, a.country]
        .filter(Boolean).filter((v, i, arr) => arr.indexOf(v) === i).join(", ");
      pinB.label = short || j.display_name;
      renderPins();
    }
  } catch { /* offline or rate-limited: the gazetteer name stays */ }
}
$("results").addEventListener("click", (e) => {
  const gb = e.target.closest("button[data-geo]");
  if (gb) {
    const [lat, lon] = gb.dataset.geo.split(",").map(Number);
    pinB = { lat, lon, label: gb.dataset.label.split(",").slice(0, 3).join(",") };
    map.flyTo({ center: [lon, lat], zoom: 8, speed: 0.9 });
    $("route").open = true;
    renderPins(); renderLegs();
    return;
  }
  const ab = e.target.closest("button[data-airport]");
  if (ab) {
    const a = airports.find((x) => x[0] === ab.dataset.airport);
    if (!a) return;
    pinB = { lat: a[3], lon: a[4], label: `${a[0]} — ${a[1]}` };
    map.flyTo({ center: [a[4], a[3]], zoom: 5, speed: 0.9 });
    $("route").open = true;
    renderPins(); renderLegs();
    return;
  }
  const b = e.target.closest("button[data-slug]");
  if (!b) return;
  // The geolocation line is set once and would otherwise keep claiming
  // "showing Seoul" while the chart shows whatever was just picked.
  $("here").textContent = "";
  paintOrigin(bySlug.get(b.dataset.slug));
});
$("q").addEventListener("input", (e) => render(e.target.value));
render();

// ---- controls ----
$("compass").addEventListener("click", () => {
  map.easeTo({ bearing: 0, pitch: 0, duration: 420 });
});

const lockBox = $("lock-north");
lockBox.checked = lockNorth;
lockBox.addEventListener("change", () => {
  lockNorth = lockBox.checked;
  store.set("lockNorth", lockNorth);
  applyLockNorth();
});

const placesBox = $("show-places");
placesBox.checked = namePlaces;
placesBox.addEventListener("change", () => {
  namePlaces = placesBox.checked;
  store.set("namePlaces", namePlaces);
});

function paintRampPicker() {
  $("ramps").replaceChildren(...Object.entries(RAMPS).map(([key, r]) => {
    const b = document.createElement("button");
    b.dataset.ramp = key;
    b.setAttribute("aria-current", String(key === rampName));
    const nm = document.createElement("span");
    nm.className = "nm"; nm.textContent = r.name;
    const strip = document.createElement("span");
    strip.className = "strip";
    for (const c of r.c) {
      const sw = document.createElement("span"); sw.style.background = c; strip.append(sw);
    }
    b.append(nm, strip);
    return b;
  }));
}
paintRampPicker();

$("ramps").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-ramp]");
  if (!b) return;
  rampName = b.dataset.ramp;
  BANDS = expandRamp(RAMPS[rampName].c, N_BANDS);
  try { localStorage.setItem("ramp", rampName); } catch { /* private mode */ }
  paintLegend();
  paintRampPicker();
  // Repaint in place; the tiles are already loaded.
  if (map.getLayer("bands"))
    map.setPaintProperty("bands", "fill-color", bandColorExpression());
  paintSea();
  if (map.getLayer("band-seams"))
    map.setPaintProperty("band-seams", "line-color", bandColorExpression());
});

applyLockNorth();

// Small screens: the readout joins the bottom sheet and the panels start
// closed, so the globe gets the screen. Re-evaluated on rotation.
const SMALL = window.matchMedia("(max-width: 860px)");
function layoutForSize() {
  const reading = document.querySelector(".reading");
  const rail = document.querySelector(".rail");
  if (SMALL.matches) {
    if (!document.getElementById("sheet-toggle")) {
      // A grab handle that folds the whole sheet down to one strip, so the
      // globe can have the entire phone when you want it to.
      const t = document.createElement("button");
      t.id = "sheet-toggle"; t.className = "sheet-toggle"; t.type = "button";
      t.setAttribute("aria-label", "Collapse or expand the panel");
      t.innerHTML = "<span></span>";
      t.addEventListener("click", () => {
        const folded = rail.classList.toggle("folded");
        t.setAttribute("aria-expanded", String(!folded));
      });
      rail.prepend(t);
    }
    if (reading.parentElement !== rail) rail.insertBefore(reading, document.getElementById("sheet-toggle").nextSibling);
    for (const d of rail.querySelectorAll("details")) d.open = false;
  } else if (reading.parentElement === rail) {
    document.body.insertBefore(reading, document.getElementById("tip"));
    $("departure").open = true;
  }
}
layoutForSize();
SMALL.addEventListener("change", layoutForSize);
// There is no pointer on a phone.
if (window.matchMedia("(pointer: coarse)").matches)
  $("where").textContent = "Tap the chart to read a passage.";

const FALLBACK = bySlug.get("seoul") ?? cities[0];

function nearest(lat, lon) {
  const rad = Math.PI / 180;
  let best = FALLBACK, bestD = Infinity;
  for (const c of cities) {
    const dLat = (c.lat - lat) * rad;
    const dLon = (c.lon - lon) * rad;
    const a = Math.sin(dLat / 2) ** 2 +
      Math.cos(lat * rad) * Math.cos(c.lat * rad) * Math.sin(dLon / 2) ** 2;
    const d = 2 * Math.asin(Math.sqrt(a));
    if (d < bestD) { bestD = d; best = c; }
  }
  return best;
}

// Draw at once from the fallback; geolocation may never answer, and making the
// first frame wait on a permission prompt is exactly the initial wait we do not
// want. If a position arrives later, quietly re-centre on the nearest city.
paintOrigin(FALLBACK);
$("here").textContent = "Showing Seoul. Allow location to start from the city nearest you.";

if (navigator.geolocation) {
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const { latitude: la, longitude: lo } = pos.coords;
      const c = nearest(la, lo);
      $("here").textContent = `${c.name} is the nearest charted city to you.`;
      map.getSource("me").setData({ type: "FeatureCollection", features: [
        { type: "Feature", geometry: { type: "Point", coordinates: [lo, la] } }] });
      if (c.slug !== active?.slug) paintOrigin(c);
      // The surface is the nearest city's, but the view opens on where you are.
      map.once("moveend", () => map.flyTo({ center: [lo, la], zoom: 3.2, speed: 0.8 }));
    },
    () => { $("here").textContent = "Location unavailable — showing Seoul."; },
    { timeout: 8000, maximumAge: 900000 }
  );
}

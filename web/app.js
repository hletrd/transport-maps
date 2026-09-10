import maplibregl from "./vendor/maplibre-gl.js";
import * as pmtiles from "./vendor/pmtiles.js";
import * as h3 from "./vendor/h3.js";

// Sequential ramps, brightest where the journey is shortest. Multi-hue on
// purpose: a SINGLE hue cannot separate this many bands on a dark ground.
// scripts/check_ramps.py measures adjacent-anchor separation in OKLab (x100):
// the floor is 6, the target 8; the earlier single-hue amber sat at 4.4-4.8
// throughout, which is why China and Siberia read as one flat mass. The 37
// bands interpolated between anchors are necessarily closer (about 2 apart);
// the legend ticks and the readout's band range carry that finer distinction.
// Lightness is strictly monotonic in every scheme, which is what a sequential
// ramp actually requires; hue rotation supplies the separation lightness
// alone cannot.

const BG = "#0a0b0d", SEA = "#0f1114";
// Space behind the globe: darker than every scheme's sea (measured by
// scripts/check_ramps.py), which is what lets the globe's edge be seen.
const SPACE = "#050609";
const UNREACHABLE_BAND = -1;

const $ = (id) => document.getElementById(id);
const proto = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", proto.tile);

// Anything that reaches the DOM from a dataset (GeoNames, OurAirports,
// Nominatim, OpenStreetMap station names) goes through this first.
const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// A blank globe with no message is the failure mode this page has shipped
// twice. If the two files everything depends on cannot be read, say so where
// the reading would have been, then stop. On a phone the readout sits under
// the bottom sheet until the layout runs, so the sheet is hidden as well.
function fatal(msg) {
  document.body.classList.add("fatal");
  $("time").textContent = "—";
  $("where").textContent = msg;
  throw new Error(msg);
}
async function fetchOk(url) {
  const r = await fetch(url).catch((e) => fatal(`Could not reach ${url} (${e.message}).`));
  if (!r.ok) fatal(`Could not load ${url} (HTTP ${r.status}).`);
  return r;
}
const loadJSON = (url) => fetchOk(url).then((r) => r.json().catch(() => fatal(`${url} is not valid JSON.`)));
async function loadCells(url) {
  const b = await (await fetchOk(url)).arrayBuffer();
  if (!b.byteLength || b.byteLength % 8) fatal(`${url} is ${b.byteLength} bytes, not whole 8-byte cells.`);
  return new BigUint64Array(b);
}

const meta = await loadJSON("./index.json");
// A valid JSON body is not yet a valid index: an index.json written by
// another tool, or truncated to {}, threw on cities[0] with no message.
if (!Array.isArray(meta.origins) || !meta.origins.length || !Array.isArray(meta.bandEdgesMin))
  fatal("index.json lists no departure cities or band edges.");
const UNREACHABLE = meta.unreachable ?? 65535;
// The emitter writes the sentinel for anything at or beyond 65,534 minutes
// (45 days); read it the same way, so an old array never prints a duration.
const MAX_MINUTES = UNREACHABLE - 1;
const HOVER_RES = meta.hoverRes ?? 4;
// The surface is solved per res-6 cell (~6.5 km across), refined to res 7
// (2.4 km) in dense regions; the readout array is res 4 (~45 km) and holds
// each parent's CENTRE child's value, to stay small. The highlight shows the
// solved base cell -- outlining the readout parent drew a hexagon seven times
// the size of anything the map was computed from. (Where the surface was
// refined, the outline is still the res-6 parent: finding C3, cycle 3.)
const SOLVE_RES = meta.solveRes ?? 6;
const EDGES = meta.bandEdgesMin;
// Channel order of .modes.bin, from the emitter when index.json carries it.
const MODE_NAMES = meta.modeChannels ?? ["rail", "ferry", "highway", "major road", "minor road", "track"];

// shared, origin-independent cell ordering — fetched once
const hoverCells = await loadCells("./" + (meta.hoverCellsUrl || "hover_cells.bin"));
if (meta.hoverCellCount != null && meta.hoverCellCount !== hoverCells.length)
  fatal(`index.json expects ${meta.hoverCellCount} hover cells but hover_cells.bin has ${hoverCells.length}: the two files come from different builds.`);

const RAMPS = {
  // Eleven anchors per scheme; adjacent-anchor separation in OKLab (x100) is
  // at least 6 and aimed at 8. Lightness is strictly monotonic in every ramp,
  // which is what a sequential scale actually requires. `sea` is the scheme's
  // own water: darker than its darkest band, lighter than space, so the globe
  // stands off the page. `grey` is the scheme's "no scheduled route" tone,
  // chosen so it is at least 8 from every one of the 37 painted bands -- one
  // shared grey sat 0.9 from a Mono band. scripts/check_ramps.py measures all
  // of this.
  muted:    { name: "Muted",    sea: "#171a22", grey: "#5d5d5d", c: ["#faefc5","#f6d59d","#f5b87c","#ef9b6a","#e38065","#cf6a6a","#b35a6f","#934e6e","#724566","#543b57","#3a2c4b"] },
  vivid:    { name: "Vivid",    sea: "#15122c", grey: "#484848", c: ["#fff7a8","#ffd557","#ffad19","#ff8200","#ff5327","#fe1d59","#df0a7c","#b3218b","#842f88","#563275","#2b2764"] },
  warm:     { name: "Warm",     sea: "#1e1512", grey: "#606060", c: ["#fbeec9","#f5d7a0","#efbe78","#e7a457","#db8b3f","#ca7335","#b46036","#99523b","#7c463c","#613a38","#4b2b2e"] },
  ice:      { name: "Ice",      sea: "#0f172b", grey: "#484848", c: ["#eaf6fb","#c3e4f4","#9cd2ec","#76bee3","#52a9d7","#3893c7","#277cb2","#1f6699","#1e5080","#203d62","#212a46"] },
  forest:   { name: "Forest",   sea: "#101c15", grey: "#585858", c: ["#f2f6da","#d7e9ae","#b8d98a","#96c76e","#73b45c","#549f52","#3e894a","#317244","#2b5c3c","#274630","#233126"] },
  mono:     { name: "Mono",     sea: "#17181b", grey: "#473f70", c: ["#f4f4f4","#dddddd","#c6c6c6","#b0b0b0","#9a9a9a","#858585","#717171","#5d5d5d","#4a4a4a","#373737","#262626"] },
  ember:    { name: "Ember",    sea: "#1d1414", grey: "#484848", c: ["#fff3c4","#ffd787","#ffb556","#ff9031","#fa691d","#e64415","#c52d19","#a0201d","#7c1b22","#571a28","#331a2b"] },
  rose:     { name: "Rose",     sea: "#1c141b", grey: "#484848", c: ["#fde9ef","#f9cad9","#f5abc5","#ed8cb3","#df6da1","#cb5190","#af3c80","#902d70","#70255f","#50214d","#31203a"] },
  sand:     { name: "Sand",     sea: "#1b1711", grey: "#595e63", c: ["#fbf3e2","#eedfb8","#e1c991","#d3b270","#c29a56","#b08443","#9b7035","#845d2d","#6c4c2b","#553d27","#3d2e23"] },
  twilight: { name: "Twilight", sea: "#131629", grey: "#484848", c: ["#fdf5a6","#d8e48d","#abd48c","#7fc391","#5aaf98","#44989c","#38809b","#346794","#364e84","#34366c","#2c264a"] },
  copper:   { name: "Copper",   sea: "#1c1512", grey: "#4d4d4d", c: ["#fff0e0","#f8d6bd","#efbc9b","#e4a27c","#d68960","#c47148","#ae5c37","#95492b","#7a3b2a","#5d3026","#422523"] },
  lavender: { name: "Lavender", sea: "#161426", grey: "#484848", c: ["#f5f0fb","#e2d7f5","#cfbfee","#bba7e5","#a690d9","#9179ca","#7c64b8","#6750a3","#523f89","#3f316b","#2e264c"] },
};

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
const N_BANDS = EDGES.length + 1;

// How each surface mode is modelled, when index.json predates the emitter
// that ships the calibrated sentence (builds before modeDetail existed).
const MODE_FALLBACK = {
  "rail": "Scheduled trains from OpenStreetMap route relations, stop to stop, plus boarding time.",
  "ferry": "Scheduled ferry routes from OpenStreetMap, sailing time plus time at the terminals.",
  "highway": "Motorways and expressways at a fitted free-flow speed, halved inside cities.",
  "major road": "Primary and secondary roads at fitted speeds, halved inside cities.",
  "minor road": "Tertiary and local roads at fitted speeds, halved inside cities.",
  "track": "No mapped road: walking pace.",
};
const NO_AIRPORT = 0xFFFF;
const NO_RAIL = 0xFFFF;

// ---- module state, declared before any function that assigns it ----
// Every `let` the handlers write lives here, above the code that runs them.
// They used to be declared mid-file, after paintOrigin and renderLegs, and
// worked only because the first call sat at the very end of the module; the
// planned reordering of start-up would have thrown a ReferenceError after the
// map existed -- a blank page with no useful error.
let rampName = "muted";
let BANDS;
let lockNorth, namePlaces;
let places = null;              // gazetteer: flat typed arrays plus the rows
let hoveredCell = null;
let raf = 0;
let pinB = null;                // the destination, once one is set
let airports = [];              // OurAirports rows, for search and the route
let addressSeq = 0, reverseSeq = 0;
let active = null;              // the departure city
// Everything fetched per departure. One object, replaced on every switch and
// guarded by a generation counter: a slow earlier origin's response can no
// longer land on top of the newer one's arrays (it used to, for four of the
// five files, and the pins then printed the new city's name with the old
// city's number).
let originGen = 0, originAbort = null;
const origin = { times: null, failed: null, air: null, modes: null, routes: null, rail: null };
let lastPointer = null;         // {lat, lng, point} of the last reading, re-run when data lands
// The readout's resting copy; a phone has no pointer.
const IDLE_PROMPT = window.matchMedia("(pointer: coarse)").matches
  ? "Tap the map to read a travel time. Tap a city name to depart from it."
  : $("where").textContent;

// ---- settings, remembered per viewer ----
const store = {
  get(k, d) {
    try { const v = localStorage.getItem(k); return v === null ? d : v === "1"; }
    catch { return d; }
  },
  set(k, v) { try { localStorage.setItem(k, v ? "1" : "0"); } catch { /* private mode */ } },
};
try { const r = localStorage.getItem("ramp"); if (r && RAMPS[r]) rampName = r; }
catch { /* private mode */ }
BANDS = expandRamp(RAMPS[rampName].c, N_BANDS);
lockNorth = store.get("lockNorth", false);
namePlaces = store.get("namePlaces", true);
const greyOf = () => RAMPS[rampName]?.grey ?? "#4a4d50";

// ---- one time notation for the whole page ----
// Under an hour in minutes, otherwise hours and minutes; hours keep counting
// past 48 (the legend runs to 72 h). Four notations used to coexist: "5h
// 11m", "5 h 11m", "2 days 2h" and "48–72 h".
function fmtTime(min) {
  if (min == null) return ["—", ""];
  if (min >= MAX_MINUTES) return ["∞", "no scheduled route"];
  const total = Math.round(min);             // round once, so 119.6 is 2 h, not "1 h 60 min"
  const h = Math.floor(total / 60), m = total % 60;
  if (h < 1) return [String(m), "min"];
  return [String(h), m ? `h ${m} min` : "h"];
}
const fmtDur = (m) => { const [b, u] = fmtTime(m); return u ? `${b} ${u}` : b; };
// Compact form for the legend ticks and band ranges: "45 min", "3 h 45",
// "16 h". Six of the thirty-seven bands are under an hour, and without the
// first branch every one of them printed "0 h 45" beside a #time reading
// "45 min" -- two notations for one quantity, in the same sentence, in the
// cells around the departure city where everyone looks first.
function fmtTick(min) {
  const total = Math.round(min);
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60), m = total % 60;
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}

// ---- legend ----
function paintLegend() {
  $("tints").replaceChildren(...BANDS.map((c) => {
    const s = document.createElement("span"); s.style.background = c; return s;
  }));
  // The two tones outside the ramp, so the grey of Antarctica or Siberia and
  // the scheme's sea are named rather than left for the reader to guess.
  $("sw-uncharted").style.background = greyOf();
  $("sw-sea").style.background = RAMPS[rampName]?.sea ?? SEA;
}
paintLegend();

// Segments are equal width but the time scale is not linear, so a tick must sit
// at its own band boundary AND say that boundary's value. The edges are a
// geometric ladder, so most round hours do not fall on one; labelling the
// nearest edge with the round hour put "72+" on the 67 h edge and "4" on
// 3 h 45, and printing the edge as a decimal ("3.8") misstated it by three
// minutes the other way. Now: aim at a spread of targets, snap to the nearest
// edge (an exact hour wins when it is about as close), print that edge's own
// hours and minutes, and drop any label that would overprint its neighbour
// once measured on screen.
const TICK_TARGETS_MIN = [60, 300, 1440, 4320];
function paintScale() {
  const picked = new Set();
  for (const t of TICK_TARGETS_MIN) {
    let best = -1, bestErr = Infinity;
    EDGES.forEach((e, i) => {
      let err = Math.abs(Math.log(e / t));
      if (e % 60 === 0) err *= 0.6;             // prefer an exact hour when it is nearly as close
      if (err < bestErr) { bestErr = err; best = i; }
    });
    if (best >= 0) picked.add(best);
  }
  const scale = $("scale");
  scale.replaceChildren(...[...picked].sort((a, b) => a - b).map((i) => {
    const el = document.createElement("span");
    el.style.left = `${((i + 1) / N_BANDS) * 100}%`;
    el.dataset.min = String(EDGES[i]);
    el.textContent = fmtTick(EDGES[i]) + (i === EDGES.length - 1 ? "+" : "");
    el.title = `${EDGES[i]} minutes from the departure city, door to door`;
    if (i === EDGES.length - 1) el.classList.add("last");   // right-anchored, never overhangs
    return el;
  }));
  prune(scale);
}

// Measured, not assumed: two labels closer than 8 px read as one number.
//
// Three bugs lived in six lines. `scale.children` is a LIVE HTMLCollection, so
// removing during for...of skipped the element after every removal. The later
// label of an overlapping pair was always the one dropped, which meant the
// ceiling ("72 h+") went first -- the one tick a reader needs to know the
// scale ends. And it ran once, at module load, in the fallback face under
// font-display:swap, so the measurement belonged to a viewport and a typeface
// the page may never have had again.
function prune(scale) {
  const els = [...scale.children];              // snapshot: removal must not shift the walk
  let prev = null;
  for (const el of els) {
    if (!prev) { prev = el; continue; }
    if (el.getBoundingClientRect().left >= prev.getBoundingClientRect().right + 8) {
      prev = el; continue;
    }
    // The ceiling survives every collision: it is the one tick that tells a
    // reader where the scale ends, and dropping the LATER label always threw
    // it away first. Otherwise the newcomer loses, which keeps the leading
    // tick that carries the unit.
    if (el.classList.contains("last")) { prev.remove(); prev = el; }
    else el.remove();
  }
}
paintScale();
// Re-measure when the box or the typeface changes: at load the labels were
// laid out at whatever width the window happened to be, in whatever face had
// arrived, and never again.
addEventListener("resize", paintScale);
if (document.fonts?.ready) document.fonts.ready.then(paintScale).catch(() => {});

// Credits: the pipeline's list from index.json, plus what the PAGE itself
// adds (the address search), so a build whose index.json predates a source
// still credits it. GeoNames and HydroLAKES are listed here too for the
// build that predates their rows; tests/emit/test_index.py keeps the licence
// strings in step with the emitter's.
const PAGE_CREDITS = [
  { name: "GeoNames", licence: "CC BY 4.0", url: "https://www.geonames.org/" },
  { name: "HydroLAKES", licence: "CC BY 4.0", url: "https://www.hydrosheds.org/products/hydrolakes" },
  { name: "Nominatim (OpenStreetMap)", licence: "ODbL 1.0", url: "https://nominatim.org/" },
];
{
  const seen = new Map();
  for (const s of [...(meta.attribution ?? []), ...PAGE_CREDITS]) if (!seen.has(s.name)) seen.set(s.name, s);
  const el = $("credits");
  el.replaceChildren();
  let first = true;
  for (const s of seen.values()) {
    if (!first) el.append(" · ");
    first = false;
    const a = document.createElement("a");
    a.href = s.url; a.rel = "noopener"; a.target = "_blank";
    a.textContent = s.name;
    el.append(a, ` (${s.licence})`);
  }
  if (first) el.textContent = "Attribution missing from index.json.";
}
$("n-cities").textContent = String(meta.origins.length);
// When the data was built, once index.json says so.
if (meta.builtAt) {
  const d = new Date(meta.builtAt);
  if (!Number.isNaN(d.getTime()))
    $("built").textContent = `Data built on ${d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" })}.`;
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
// even where the sea is nearly as dark. Under the globe projection only
// atmosphere-blend acts (MapLibre 5 disables the sky there); the other keys
// take effect if the projection ever changes back to Mercator.
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
// A dark halo under the white line. White alone measured 1.15:1 against the
// palest band -- the ring around the departure city, where every visitor
// points first, was invisible. The halo reads 17.0:1 there and disappears
// into the darkest bands, where the white line is already unmissable.
map.addLayer({ id: "hover-halo", type: "line", source: "hover",
  paint: { "line-color": "#0a0b0d", "line-width": 3.5, "line-opacity": 0.55 } });
map.addLayer({ id: "hover-line", type: "line", source: "hover",
  paint: { "line-color": "#ffffff", "line-width": 1.5, "line-opacity": 0.9 } });
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
  for (const id of ["hover-halo", "hover-fill", "hover-line", "me-halo", "me-dot"])
    if (map.getLayer(id)) map.moveLayer(id);
}).catch(() => {});

// A flyTo arc becomes a cut when the visitor asked for less motion.
const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");
function moveTo(opts) { if (REDUCED_MOTION.matches) map.jumpTo(opts); else map.flyTo(opts); }

// Whether a point is on the visible face of the globe: project() happily
// returns on-disc coordinates for Lima while the view faces Beijing.
function onNearSide(lat, lng) {
  const ctr = map.getCenter(), rad = Math.PI / 180;
  const cosArc = Math.sin(ctr.lat * rad) * Math.sin(lat * rad)
    + Math.cos(ctr.lat * rad) * Math.cos(lat * rad) * Math.cos((lng - ctr.lng) * rad);
  return cosArc > Math.cos(85 * rad);
}

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
  const grey = greyOf();
  return ["match", ["get", "band"],
    UNREACHABLE_BAND, grey,
    ...BANDS.flatMap((c, i) => [i, c]), grey];
}

// ---- gazetteer, so a reading can name where it is ----
// The departure city always carries its own label: it is what the visitor is
// looking at, and the gazetteer ranks Seoul 22nd, Tokyo 24th and Paris 201st,
// far outside the opening view's budget of eighteen.
const originLabel = document.createElement("button");
originLabel.type = "button";
originLabel.className = "lbl origin";
originLabel.setAttribute("aria-current", "true");
originLabel.tabIndex = -1;
originLabel.addEventListener("click", (ev) => ev.stopPropagation());
const originMarker = new maplibregl.Marker({ element: originLabel, anchor: "top" });
let originMarkerOn = false;
let showLabels = () => {};

fetch("./places.json")
  .then((r) => (r.ok ? r.json() : null))
  .then((p) => {
    if (!p) return;
    // Flat typed arrays: 34,000 objects would be re-read on every pointer move.
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
      // it departs from there. Matched by distance (15 km: the same city under
      // a spelling that differs between the gazetteer and origins.toml, not the
      // next town over -- "Incheon" used to be a button that departed from
      // Seoul). Any other label swallows its click: it is not a destination.
      const origin = originNear(r[3], r[4], 15);
      const el = document.createElement(origin ? "button" : "div");
      el.className = origin ? "lbl origin" : "lbl";
      el.textContent = r[0];
      if (origin) {
        el.type = "button";
        el.tabIndex = -1;                  // the city list is the keyboard path
        el.title = `Depart from ${origin.name}`;
        el.dataset.slug = origin.slug;
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();            // not a destination pin
          $("here").textContent = "";
          if (origin.slug !== active?.slug) paintOrigin(origin, { keepZoom: true });
        });
      } else {
        el.addEventListener("click", (ev) => ev.stopPropagation());
      }
      const m = new maplibregl.Marker({ element: el, anchor: "top" })
        .setLngLat([r[4], r[3]]);
      return { m, rank: i, on: false, lat: r[3], lon: r[4], slug: origin?.slug };
    });
    showLabels = () => {
      const z = map.getZoom();
      // The opening view (zoom 1.9) must show some names: the first line of
      // copy says to click one. Eighteen is the largest cities, no clutter.
      const n = z < 1.2 ? 0 : z < 2.2 ? 18 : z < 3 ? 40 : z < 4 ? 120 : z < 5.5 ? 350 : 900;
      // Largest cities claim their screen space first; a smaller one whose
      // label would land within the gap of one already placed is skipped, so
      // the map thins itself rather than piling names on top of each other.
      const placed = [];
      const gapX = 70, gapY = 16;
      const collides = (pt) => placed.some((q) => Math.abs(q.x - pt.x) < gapX && Math.abs(q.y - pt.y) < gapY);
      // The departure city first, so everything else yields to it.
      if (active && onNearSide(active.lat, active.lon)) {
        const pt = map.project([active.lon, active.lat]);
        placed.push(pt);
        if (!originMarkerOn) { originMarker.addTo(map); originMarkerOn = true; }
      } else if (originMarkerOn) { originMarker.remove(); originMarkerOn = false; }
      for (const l of labelPool) {
        let want = l.rank < n && onNearSide(l.lat, l.lon);
        if (want) {
          const pt = map.project(l.m.getLngLat());
          want = pt.x > -50 && pt.y > -20 && pt.x < window.innerWidth + 50
              && pt.y < window.innerHeight + 20 && !collides(pt);
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
    // Equirectangular is plenty to rank candidates and avoids 34,000 trig calls.
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
// Up to 60 km the place is where you are; up to 250 km it is "near"; beyond
// that the nearest town says nothing about the spot (Antarctica read "near
// Port-aux-Français", 3,000 km away) and only the coordinates are honest.
function placeLead(p) {
  if (!p || p.km > 250) return null;
  return p.km > 60 ? `near ${p.name}` : p.name;
}

// ---- the departure city ----
function paintOrigin(o, { keepZoom = false } = {}) {
  active = o;
  const gen = ++originGen;
  originAbort?.abort();
  const ctl = originAbort = new AbortController();
  const sig = ctl.signal;

  if (map.getLayer("bands")) map.removeLayer("bands");
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

  // Nothing of the previous origin survives the switch: the arrays are nulled
  // in one synchronous pass, and every response below is applied only while
  // this switch is still the latest one.
  origin.times = null; origin.failed = null; origin.air = null;
  origin.modes = null; origin.routes = null; origin.rail = null;
  const current = () => gen === originGen;
  const settle = () => {
    if (!current()) return;
    renderPins(); renderLegs();
    // The reading under the pointer (or the last tap) is redone once the
    // times land; with no pointer yet, the idle prompt replaces "loading".
    if (lastPointer) rereadPointer();
    else if (origin.times && $("where").textContent.startsWith("Loading")) $("where").textContent = IDLE_PROMPT;
  };
  // An array from another build has another cell ordering: it would render
  // plausible, silently wrong times for every cell, which dist/ does during
  // every rebuild.
  const checked = (b, width, name) => {
    if (b.byteLength !== hoverCells.length * width)
      throw new Error(`${name} has ${Math.floor(b.byteLength / width)} entries but hover_cells.bin has ${hoverCells.length}: the files come from different builds`);
    return new Uint16Array(b);
  };
  const get = (url) => fetch(url, { signal: sig });

  // Station naming exists only in builds whose index.json says so; asking an
  // older build for it was two 404s per origin switch.
  if (meta.railDetail) Promise.all([
    get(`./origins/${o.slug}.rail.bin`).then((r) => (r.ok ? r.arrayBuffer() : null)),
    get(`./origins/${o.slug}.rail.json`).then((r) => (r.ok ? r.json() : null)),
  ]).then(([b, j]) => {
    if (!current() || !b || !j) return;
    origin.rail = { idx: checked(b, 2, `${o.slug}.rail.bin`), table: j.stations };
    settle();
  }).catch((err) => { if (current() && !sig.aborted) console.warn("rail detail unavailable:", err.message); });
  get(`./origins/${o.slug}.bin`)
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status} fetching ${o.slug}.bin`);
      return r.arrayBuffer();
    })
    .then((b) => { if (!current()) return; origin.times = checked(b, 2, `${o.slug}.bin`); settle(); })
    .catch((err) => {
      if (!current() || sig.aborted) return;
      console.error("hover data unavailable:", err);
      origin.failed = err.message;       // so the readout says "unavailable", not "loading"
      $("where").textContent = `Times unavailable for ${o.name}: ${err.message}.`;
      renderPins();
    });
  // The leg breakdown is a progressive extra: an origin built before these
  // files existed still shows times, just without the itinerary.
  get(`./origins/${o.slug}.modes.bin`)
    .then((r) => (r.ok ? r.arrayBuffer() : null))
    .then((b) => { if (!current() || !b) return; origin.modes = checked(b, 2 * MODE_NAMES.length, `${o.slug}.modes.bin`); settle(); })
    .catch((err) => { if (current() && !sig.aborted) console.warn("mode breakdown unavailable:", err.message); });
  get(`./origins/${o.slug}.air.bin`)
    .then((r) => (r.ok ? r.arrayBuffer() : null))
    .then((b) => { if (!current() || !b) return; origin.air = checked(b, 2, `${o.slug}.air.bin`); settle(); })
    .catch((err) => { if (current() && !sig.aborted) console.warn("arrival airports unavailable:", err.message); });
  get(`./origins/${o.slug}.json`)
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      if (!current() || !j) return;
      origin.routes = { offsets: j.offsets, byId: new Map(j.nodes.map((n) => [n.id, n])) };
      settle();
    })
    .catch((err) => { if (current() && !sig.aborted) console.warn("routes unavailable:", err.message); });

  // Keep the visitor's zoom when they chose the city from the globe (they
  // were reading a region); the list and the permalink open the world view.
  const zoom = keepZoom ? Math.min(Math.max(map.getZoom(), 1.9), 6) : 1.9;
  moveTo({ center: [o.lon, o.lat], zoom, speed: 0.75, curve: 1.5 });
  for (const b of document.querySelectorAll(".results button[data-slug]"))
    b.setAttribute("aria-current", String(b.dataset.slug === o.slug));
  $("origin-name").textContent = o.name;
  originLabel.textContent = o.name;
  originLabel.title = `Departure city: ${o.name}`;
  originMarker.setLngLat([o.lon, o.lat]);
  showLabels();
  // The readout belongs to the departure it names: say the new one is
  // loading rather than keep the old figure beside the new header.
  $("time").textContent = "—";
  $("where").textContent = `Loading the times from ${o.name}…`;
  // The address bar follows the departure, so the view can be shared.
  try {
    const url = new URL(location.href);
    url.searchParams.set("from", o.slug);
    history.replaceState(null, "", url);
  } catch { /* file:// or a sandbox without history */ }
  renderPins();
}

// ---- readout ----
const fmtCoord = (lat, lon) =>
  `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? "N" : "S"} ${Math.abs(lon).toFixed(2)}°${lon >= 0 ? "E" : "W"}`;

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

// null: not land (known from hover_cells.bin alone, so the sea never reads
// "loading"); undefined: land whose times have not arrived, or failed.
function lookup(lat, lon) {
  const i = cellIndex(lat, lon);
  if (i < 0) return null;
  return origin.times ? origin.times[i] : undefined;
}

// Walk the shortest-path tree back from where the journey landed. The chain is
// cell -> A_dep -> B_arr -> B_dep -> C_arr, so a connection shows up as an
// arrival immediately followed by a departure at the same airport.
function legsTo(lat, lon) {
  if (!origin.air || !origin.routes) return null;
  const i = cellIndex(lat, lon);
  if (i < 0) return null;
  const ordinal = origin.air[i];
  if (ordinal === NO_AIRPORT) return [];        // overland the whole way

  const { airports: airOff, stations } = origin.routes.offsets;
  const count = (stations - airOff) / 2;        // departures AND arrivals
  let node = origin.routes.byId.get(airOff + count + ordinal);
  const chain = [];
  while (node && chain.length < 24) {
    chain.push(node);
    node = node.prev == null ? null : origin.routes.byId.get(node.prev);
  }
  return chain.reverse();
}

function railVia(i) {
  const rail = origin.rail;
  if (!rail || i < 0) return "";
  const k = rail.idx[i];
  if (k === NO_RAIL || !rail.table[k]) return "";
  const [station, line] = rail.table[k];
  if (!station && !line) return "";
  return ` via ${station || "a station"}${line ? ` (${line})` : ""}`;
}

function renderLegs() {
  const box = $("legs");
  if (!pinB) { box.hidden = true; return; }

  const total = lookup(pinB.lat, pinB.lon);
  const chain = legsTo(pinB.lat, pinB.lon);
  if (total == null || total >= MAX_MINUTES || chain == null) { box.hidden = true; return; }

  const rows = [];
  // A code like SHE or FNJ means nothing to most readers: hovering it names
  // the airport and its country. Modes explain how they were modelled.
  const ap = (code) => {
    const a = airports.find((x) => x[0] === code);
    return a ? `<span class="ap" tabindex="0" data-tip="${esc(a[1])}, ${esc(a[2])}">${esc(code)}</span>` : esc(code);
  };
  const mode = (name) => {
    const tip = meta.modeDetail?.[name] ?? MODE_FALLBACK[name];
    return tip ? `<span class="mode" tabindex="0" data-tip="${esc(tip)}">${esc(name)}</span>` : esc(name);
  };

  // "Surface transport, 5 h" says nothing useful. Rail, road and ferry differ
  // enormously in what they imply, and the surface leg is a large share of most
  // journeys, so name the three separately when the data is there.
  const surface = () => {
    if (!origin.modes) return [];
    const i = cellIndex(pinB.lat, pinB.lon);
    if (i < 0) return [];
    const n = MODE_NAMES.length;
    return MODE_NAMES.map((name, k) => [name, origin.modes[i * n + k]])
      .filter(([, m]) => m >= 1)
      .sort((a, b) => b[1] - a[1])
      .map(([name, m]) => [fmtDur(m), `by <b>${mode(name)}</b>${name === "rail" ? esc(railVia(i)) : ""}`]);
  };

  if (chain.length === 0) {
    // No flight was involved: itemise the surface modes when the data is
    // there, otherwise say only what is known.
    const parts = surface();
    if (parts.length) rows.push(...parts);
    else rows.push([fmtDur(total), "No flight on this journey: surface travel"]);
  } else {
    rows.push([fmtDur(chain[0].min), `To <b>${ap(chain[0].code)}</b>, and through the airport`]);
    for (let k = 1; k < chain.length; k++) {
      const a = chain[k - 1], b = chain[k];
      const t = fmtDur(b.min - a.min);
      if (b.kind === "arr") rows.push([t, `Fly <b>${ap(a.code)} → ${ap(b.code)}</b>`]);
      else rows.push([t, `Connect at <b>${ap(b.code)}</b>`]);
    }
    const landed = chain[chain.length - 1];
    if (total > landed.min) {
      const parts = surface();
      if (parts.length) {
        rows.push([fmtDur(total - landed.min), `Onward from <b>${ap(landed.code)}</b>`]);
        // modes.bin sums surface minutes over the WHOLE journey, the access leg
        // to the first airport included, so these rows are not a breakdown of
        // the onward figure and must not be headed as one.
        rows.push(["", "Surface travel over the whole journey:"]);
        rows.push(...parts);
      } else {
        rows.push([fmtDur(total - landed.min),
                   `From <b>${ap(landed.code)}</b> onward by surface transport`]);
      }
    }
  }
  rows.push([fmtDur(total), "Door to door", true]);

  const frag = document.createDocumentFragment();
  const h = document.createElement("h2");
  h.textContent = `Journey to ${pinB.label}`;
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

// The band range beside the number is derived from that number, not from the
// polygon under the cursor.
//
// It used to come from queryRenderedFeatures. Below map zoom 7 -- the opening
// view and most reading zooms -- the only band features rendered are the
// coarse LODs, and those value a parent by the MINIMUM over its children
// (contour/bands.py), while the readout's number is the res-4 array's CENTRE
// child. So the range described the fastest child and the number described
// the centre one: "10 h" above "0 h 30 - 1 h". Reproduced on a synthetic
// res-6/7 index.
//
// The edges follow the emitter's own convention: band k is (EDGES[k-1],
// EDGES[k]], matching np.searchsorted(edges, m, side="left").
function bandRangeOf(min) {
  if (min == null) return null;
  if (min >= MAX_MINUTES) return "no scheduled route";
  let b = 0;
  while (b < EDGES.length && min > EDGES[b]) b++;
  const lo = b === 0 ? 0 : EDGES[b - 1];
  const hi = b < EDGES.length ? EDGES[b] : null;
  return hi == null ? `over ${fmtTick(lo)}` : `${fmtTick(lo)} – ${fmtTick(hi)}`;
}

function describe(lat, lon) {
  if (!namePlaces) return fmtCoord(lat, lon);
  const p = nearestPlace(lat, lon);
  const lead = placeLead(p);
  if (!lead) return fmtCoord(lat, lon);
  const where = [p.region && p.region !== p.name ? p.region : null, p.country]
    .filter(Boolean).join(", ");
  return `<b>${esc(lead)}</b>${where ? ` — ${esc(where)}` : ""}`;
}

// The reading for a point: the big number and the line under it. Shared by
// the pointer and by a tap, which used to update only the pins and left the
// last pointer reading -- a different continent -- above them.
function showReading(lat, lng, point) {
  lastPointer = { lat, lng, point };
  const t = lookup(lat, lng);
  const [big, unit] = fmtTime(t);
  $("time").innerHTML = t == null ? "—" : `${big}<small>${unit}</small>`;
  const band = bandRangeOf(t);
  $("where").innerHTML = t === undefined
    ? (origin.failed
        ? `Times unavailable for ${esc(active.name)}.`
        : `Loading the times from ${esc(active?.name ?? "the departure city")}…`)
    : t === null ? "Open water."
    : `${describe(lat, lng)}<br>${fmtCoord(lat, lng)}`
      + `${band ? " · " + band : ""}${active ? " · from " + esc(active.name) : ""}`;
  return t;
}
// Once an origin's times land, the reading under the pointer (or the last
// tap) is redone, so it never keeps saying "loading".
function rereadPointer() {
  if (!lastPointer) return;
  const { lat, lng } = lastPointer;
  // The stored screen point may have moved with the map (an origin switch
  // flies to the new city); project the coordinates afresh, and skip the
  // band when the place is now on the far side of the globe.
  const point = onNearSide(lat, lng) ? map.project([lng, lat]) : null;
  showReading(lat, lng, point);
}

map.on("mouseout", () => { $("tip").hidden = true; clearHighlight(); });
map.on("mousemove", (e) => {
  if (raf) return;
  raf = requestAnimationFrame(() => {
    raf = 0;
    const { lat, lng } = e.lngLat;
    const t = showReading(lat, lng, e.point);
    const tip = $("tip");
    if (t == null) { tip.hidden = true; clearHighlight(); return; }
    highlight(lat, lng);
    const p = nearestPlace(lat, lng);
    const lead = placeLead(p);
    const where = lead ? lead + (p.country ? `, ${p.country}` : "") : fmtCoord(lat, lng);
    const [big, unit] = fmtTime(t);
    tip.innerHTML = t >= MAX_MINUTES
      ? `<b>No scheduled route</b> <i>· ${esc(where)}</i>`
      : `<b>${big}${unit ? " " + unit : ""}</b> <i>door to door · ${esc(where)}</i>`;
    tip.hidden = false;
    // Offset so the pointer never covers it; flip when near an edge.
    const x = e.originalEvent.clientX, y = e.originalEvent.clientY;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = `${x + 16 + w > window.innerWidth ? x - w - 12 : x + 16}px`;
    tip.style.top = `${y + 14 + h > window.innerHeight ? y - h - 12 : y + 14}px`;
  });
});

// ---- point to point ----
function renderPins() {
  const box = $("pins");
  if (!active) { box.replaceChildren(); return; }
  const rows = [["From", active.name]];
  if (pinB) {
    const t = lookup(pinB.lat, pinB.lon);
    rows.push(["To", pinB.label]);
    rows.push(["Time", t === undefined ? (origin.failed ? "unavailable" : "loading…")
      : t === null ? "open water" : t >= MAX_MINUTES ? "no scheduled route" : `${fmtDur(t)}, door to door`]);
  } else {
    rows.push(["To", "click anywhere on the map"]);
  }
  box.replaceChildren(...rows.map(([k, v]) => {
    const d = document.createElement("div");
    const ks = document.createElement("span"); ks.className = "k"; ks.textContent = k;
    const vs = document.createElement("span"); vs.className = "val"; vs.textContent = v;
    d.append(ks, vs); return d;
  }));
  if (pinB?.geocoded) {
    const c = document.createElement("div");
    c.className = "credit";
    c.textContent = "address by Nominatim © OpenStreetMap contributors";
    box.append(c);
  }
  // The clicked point can also become the departure, when a departure city
  // is near it. This is how you pick a city by clicking the map.
  const near = pinB && originNear(pinB.lat, pinB.lon);
  if (near && near.slug !== active.slug) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "btn depart";
    b.textContent = `Depart from ${near.name}`;
    b.addEventListener("click", () => {
      $("here").textContent = "";
      pinB = null;
      paintOrigin(near, { keepZoom: true });
    });
    box.append(b);
  }
}

function unfoldSheet() {
  const rail = document.querySelector(".rail");
  if (!rail.classList.contains("folded")) return;
  rail.classList.remove("folded");
  $("sheet-toggle")?.setAttribute("aria-expanded", "true");
}

map.on("click", (e) => {
  const { lat, lng } = e.lngLat;
  const t = showReading(lat, lng, e.point);
  // Open water and unreached land are not destinations: no pin, no panel,
  // and no request to Nominatim for a point with nothing to say.
  if (t === null || (t != null && t >= MAX_MINUTES)) return;
  const p = nearestPlace(lat, lng);
  pinB = { lat, lon: lng, label: placeLead(p) ?? fmtCoord(lat, lng), geocoded: false };
  $("route").open = true;
  unfoldSheet();
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

function clearRoute() { pinB = null; renderPins(); renderLegs(); }
$("clear-pins").addEventListener("click", clearRoute);

// ---- city and airport list ----
// Accents are folded on both sides, so "Sao Paulo", "Zurich" and "Bogota"
// match the cities spelt São Paulo, Zürich and Bogotá.
const fold = (s) => String(s).normalize("NFD").replace(/\p{M}/gu, "").replace(/ı/g, "i").toLowerCase();
const cities = meta.origins.slice().sort((a, b) => a.name.localeCompare(b.name));
for (const c of cities) c.key = fold(c.name);
const bySlug = new Map(cities.map((c) => [c.slug, c]));
// Airports are searchable by code ("JFK") or name. Picking one drops it as the
// DESTINATION -- only the departure cities in index.json have a computed surface.
fetch("./airports.json")
  .then((r) => (r.ok ? r.json() : null))
  .then((a) => { if (a) airports = a.airports.map((row) => Object.assign(row, { key: fold(row[1]) })); })
  .catch(() => {});
function render(filter = "") {
  const f = fold(filter.trim());
  const hits = f ? cities.filter((c) => c.key.includes(f)) : cities;
  const list = document.createDocumentFragment();
  const row = (b) => { const li = document.createElement("li"); li.setAttribute("role", "none"); li.append(b); return li; };

  // Airports first when the query looks like a code, so "jfk" is one keystroke
  // from the answer; otherwise after the cities.
  const apHits = f.length >= 2
    ? airports.filter((a) => a[0].toLowerCase() === f || a.key.includes(f)).slice(0, 12)
    : [];
  const airportRows = apHits.map((a) => {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "option"); b.tabIndex = -1;
    b.dataset.airport = a[0];
    const name = document.createElement("span");
    const code = document.createElement("b"); code.textContent = a[0];
    name.append(code, ` ${a[1]}`);
    const coord = document.createElement("span");
    coord.className = "coord";
    coord.textContent = `${a[2]} · destination`;
    b.append(name, coord);
    return row(b);
  });
  const codeFirst = f.length === 3 && apHits.some((a) => a[0].toLowerCase() === f);
  if (codeFirst) list.append(...airportRows);

  for (const c of hits) {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "option"); b.tabIndex = -1;
    b.dataset.slug = c.slug;
    b.setAttribute("aria-current", String(active?.slug === c.slug));
    const name = document.createElement("span");
    name.textContent = c.name;
    const coord = document.createElement("span");
    coord.className = "coord";
    coord.textContent = `${c.lat.toFixed(1)}, ${c.lon.toFixed(1)}`;
    b.append(name, coord);
    list.append(row(b));
  }
  if (!codeFirst) list.append(...airportRows);
  // Silence read as "nothing happened"; say what the list did not find and
  // where to look next.
  if (f && !hits.length && !apHits.length) {
    const li = document.createElement("li");
    li.className = "empty"; li.setAttribute("role", "none");
    li.textContent = `No departure city or airport matches “${filter.trim()}”. Press Enter or “Search address” to look it up.`;
    list.append(li);
  }
  const box = $("results");
  box.replaceChildren(list);
  // Roving tabindex: one stop in the tab order (the first row), the arrow
  // keys walk the rest. 157 rows used to be 157 tab stops between the search
  // box and the next panel.
  const first = box.querySelector("button");
  if (first) first.tabIndex = 0;
}

// ---- address search ----
// Anything the local lists cannot answer goes to OpenStreetMap's Nominatim:
// a street, a landmark, a village. Only on an explicit search -- Enter with
// no city match, or the button -- never per keystroke: Nominatim's usage
// policy forbids autocomplete, and the typed query is the one a person meant.
// The policy also caps the whole site at one request per second, so search
// and reverse lookups share one queue with the latest request winning.
const NOMINATIM = "https://nominatim.openstreetmap.org";
const NOMINATIM_GAP_MS = 1100;
let nominatimNext = 0;
let nominatimQueue = Promise.resolve();
function nominatim(path, isStale) {
  const run = async () => {
    if (isStale()) return null;
    const wait = nominatimNext - Date.now();
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    if (isStale()) return null;
    nominatimNext = Date.now() + NOMINATIM_GAP_MS;
    const r = await fetch(`${NOMINATIM}${path}`, { headers: { "Accept-Language": navigator.language || "en" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  };
  const p = nominatimQueue.then(run);
  nominatimQueue = p.catch(() => {});
  return p;
}
async function searchAddress(q) {
  const box = $("results");
  box.querySelector(".addresses")?.remove();
  const seq = ++addressSeq;
  const ul = document.createElement("ul");
  ul.className = "addresses";
  ul.setAttribute("role", "none");
  const head = document.createElement("li");
  head.className = "head"; head.setAttribute("role", "none");
  ul.append(head);
  box.append(ul);
  if (q.length < 3) { head.textContent = "Type at least three characters to search an address."; return; }
  head.textContent = "Searching addresses…";
  let hits = [], failed = false;
  try {
    const j = await nominatim(`/search?format=jsonv2&limit=6&q=${encodeURIComponent(q)}`, () => seq !== addressSeq);
    if (j === null) return;
    if (Array.isArray(j)) hits = j; else failed = true;   // an error body arrives as an object
  } catch { failed = true; }
  // A newer search, or a changed query, supersedes this one: its results
  // must not reappear under a different filter.
  if (seq !== addressSeq || $("q").value.trim() !== q) return;
  ul.replaceChildren(head);
  head.textContent = failed ? "Address search is unavailable right now."
    : hits.length ? "Addresses (each becomes the destination)" : `No address found for “${q}”.`;
  for (const h of hits) {
    const li = document.createElement("li");
    li.setAttribute("role", "none");
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "option"); b.tabIndex = -1;
    b.dataset.geo = `${h.lat},${h.lon}`;
    b.dataset.label = h.display_name;
    const name = document.createElement("span");
    name.textContent = h.display_name.split(",").slice(0, 3).join(",");
    const coord = document.createElement("span");
    coord.className = "coord";
    coord.textContent = `${h.display_name.split(",").slice(3).join(",").trim() || h.type} · destination`;
    b.append(name, coord); li.append(b); ul.append(li);
  }
  const credit = document.createElement("li");
  credit.className = "credit"; credit.setAttribute("role", "none");
  credit.textContent = "Search by Nominatim © OpenStreetMap contributors";
  ul.append(credit);
}

// A clicked point gets a proper address. Cached by rounded coordinate, so
// repeated clicks near one place cost nothing; the latest click wins.
const reverseCache = new Map();
async function reverseGeocode(lat, lon) {
  const seq = ++reverseSeq;
  const key = `${lat.toFixed(3)},${lon.toFixed(3)}`;
  try {
    let j = reverseCache.get(key);
    if (!j) {
      j = await nominatim(`/reverse?format=jsonv2&zoom=14&lat=${lat}&lon=${lon}`, () => seq !== reverseSeq);
      if (j === null) return;
      if (reverseCache.size > 200) reverseCache.clear();
      reverseCache.set(key, j);
    }
    if (seq !== reverseSeq || !pinB || pinB.lat !== lat) return;
    if (j.display_name) {
      const a = j.address || {};
      const short = [a.road || a.neighbourhood || a.suburb, a.city || a.town || a.village || a.county, a.state, a.country]
        .filter(Boolean).filter((v, i, arr) => arr.indexOf(v) === i).join(", ");
      pinB.label = short || j.display_name;
      pinB.geocoded = true;
      renderPins(); renderLegs();
    }
  } catch { /* offline or rate-limited: the gazetteer name stays */ }
}
$("results").addEventListener("click", (e) => {
  const gb = e.target.closest("button[data-geo]");
  if (gb) {
    const [lat, lon] = gb.dataset.geo.split(",").map(Number);
    pinB = { lat, lon, label: gb.dataset.label.split(",").slice(0, 3).join(","), geocoded: true };
    moveTo({ center: [lon, lat], zoom: 8, speed: 0.9 });
    $("route").open = true;
    renderPins(); renderLegs();
    return;
  }
  const ab = e.target.closest("button[data-airport]");
  if (ab) {
    const a = airports.find((x) => x[0] === ab.dataset.airport);
    if (!a) return;
    pinB = { lat: a[3], lon: a[4], label: `${a[0]} — ${a[1]}`, geocoded: false };
    moveTo({ center: [a[4], a[3]], zoom: 5, speed: 0.9 });
    $("route").open = true;
    renderPins(); renderLegs();
    return;
  }
  const b = e.target.closest("button[data-slug]");
  if (!b) return;
  // The geolocation line is set once and would otherwise keep claiming
  // "showing Seoul" while the map shows whatever was just picked.
  $("here").textContent = "";
  paintOrigin(bySlug.get(b.dataset.slug));
});
$("q").addEventListener("input", (e) => render(e.target.value));
// Enter picks the first match: a city departs, an airport becomes the
// destination; with no local match it searches the address. Arrows walk the
// list; Escape clears the filter, then the route.
$("q").addEventListener("keydown", (e) => {
  const q = e.target.value.trim();
  if (e.key === "Enter") {
    e.preventDefault();
    const first = q ? $("results").querySelector("button[data-slug], button[data-airport]") : null;
    if (first) first.click(); else searchAddress(q);
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    $("results").querySelector("button")?.focus();
  } else if (e.key === "Escape") {
    if (q) { e.target.value = ""; render(); } else if (pinB) clearRoute();
  }
});
$("results").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const items = [...$("results").querySelectorAll("button")];
  const i = items.indexOf(document.activeElement);
  if (i < 0) return;
  e.preventDefault();
  const next = e.key === "ArrowDown" ? items[Math.min(i + 1, items.length - 1)] : (i === 0 ? $("q") : items[i - 1]);
  for (const it of items) it.tabIndex = -1;
  if (next !== $("q")) next.tabIndex = 0;
  next.focus();
});
$("find-address").addEventListener("click", () => searchAddress($("q").value.trim()));
document.addEventListener("keydown", (e) => {
  // Escape anywhere with a route open clears it, unless a field is using it.
  if (e.key === "Escape" && pinB && document.activeElement !== $("q")) clearRoute();
});
render();

// ---- controls ----
$("compass").addEventListener("click", () => {
  map.easeTo({ bearing: 0, pitch: 0, duration: REDUCED_MOTION.matches ? 0 : 420 });
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
    b.type = "button";
    b.dataset.ramp = key;
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(key === rampName));
    b.setAttribute("aria-current", String(key === rampName));
    b.tabIndex = key === rampName ? 0 : -1;
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

function pickRamp(key) {
  rampName = key;
  BANDS = expandRamp(RAMPS[rampName].c, N_BANDS);
  try { localStorage.setItem("ramp", rampName); } catch { /* private mode */ }
  paintLegend();
  paintRampPicker();
  // Repaint in place; the tiles are already loaded.
  if (map.getLayer("bands"))
    map.setPaintProperty("bands", "fill-color", bandColorExpression());
  paintSea();
}
$("ramps").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-ramp]");
  if (b) pickRamp(b.dataset.ramp);
});
$("ramps").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const keys = Object.keys(RAMPS), i = keys.indexOf(rampName);
  e.preventDefault();
  pickRamp(keys[(i + (e.key === "ArrowDown" ? 1 : keys.length - 1)) % keys.length]);
  $("ramps").querySelector(`button[data-ramp="${rampName}"]`)?.focus();
});

applyLockNorth();

// Small screens: the readout joins the bottom sheet and the panels start
// closed, so the globe gets the screen. Re-evaluated on rotation; the panels
// are closed only on the first entry into the small layout, not on every
// rotation of a phone (which used to fold the route being read).
const SMALL = window.matchMedia("(max-width: 860px)");
let smallEntered = false;
function layoutForSize() {
  const reading = document.querySelector(".reading");
  const rail = document.querySelector(".rail");
  if (SMALL.matches) {
    if (!document.getElementById("sheet-toggle")) {
      // A grab handle that folds the sheet down to the handle and the legend
      // strip, so the globe can have the phone when you want it to. The
      // legend never folds away.
      const t = document.createElement("button");
      t.id = "sheet-toggle"; t.className = "sheet-toggle"; t.type = "button";
      t.setAttribute("aria-label", "Collapse or expand the panel");
      t.setAttribute("aria-expanded", "true");
      t.innerHTML = "<span></span>";
      t.addEventListener("click", () => {
        const folded = rail.classList.toggle("folded");
        t.setAttribute("aria-expanded", String(!folded));
      });
      rail.prepend(t);
    }
    if (reading.parentElement !== rail) rail.insertBefore(reading, document.getElementById("sheet-toggle").nextSibling);
    if (!smallEntered) { for (const d of rail.querySelectorAll("details")) d.open = false; smallEntered = true; }
  } else if (reading.parentElement === rail) {
    document.body.insertBefore(reading, document.getElementById("tip"));
    rail.classList.remove("folded");
    $("departure").open = true;
  }
}
layoutForSize();
SMALL.addEventListener("change", layoutForSize);
// There is no pointer on a phone.
$("where").textContent = IDLE_PROMPT;

// The departure named in the address (?from=slug) wins over the default; an
// unknown slug is ignored rather than a blank globe.
const FALLBACK = bySlug.get("seoul") ?? cities[0];
let requested = null;
try { requested = bySlug.get(new URL(location.href).searchParams.get("from") ?? "") ?? null; } catch { /* no URL API */ }

function nearest(lat, lon) {
  let best = FALLBACK, bestKm = Infinity;
  for (const c of cities) {
    const km = haversineKm(lat, lon, c.lat, c.lon);
    if (km < bestKm) { bestKm = km; best = c; }
  }
  return best;
}

// Draw at once from the fallback; geolocation may never answer, and making the
// first frame wait on a permission prompt is exactly the initial wait we do not
// want. If a position arrives later, quietly re-centre on the nearest city.
paintOrigin(requested ?? FALLBACK);
$("here").textContent = `Showing ${(requested ?? FALLBACK).name}.`;

// Location only on request. A permission prompt on load, before the page has
// said what it is for, is the one thing every browser now warns about, and
// it fired here on every first visit.
const locate = $("locate");
if (!navigator.geolocation) locate.hidden = true;
locate.addEventListener("click", () => {
  locate.disabled = true;
  $("here").textContent = "Locating…";
  // A dismissed permission prompt fires neither callback; do not stay disabled.
  const release = setTimeout(() => { locate.disabled = false; }, 10000);
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      clearTimeout(release);
      locate.disabled = false;
      const { latitude: la, longitude: lo } = pos.coords;
      const c = nearest(la, lo);
      $("here").textContent = `${c.name} is the nearest departure city to you.`;
      map.getSource("me").setData({ type: "FeatureCollection", features: [
        { type: "Feature", geometry: { type: "Point", coordinates: [lo, la] } }] });
      // The surface is the nearest city's, but the view opens on where you
      // are. Only wait for a move if one was actually started: waiting for
      // "the next moveend" otherwise hijacks the visitor's next drag.
      const view = { center: [lo, la], zoom: 3.2, speed: 0.8 };
      // Under reduced motion paintOrigin's jumpTo has already fired moveend
      // synchronously, so waiting for the next one would wait for the
      // visitor's drag: move now instead.
      if (c.slug !== active?.slug && !REDUCED_MOTION.matches) { paintOrigin(c); map.once("moveend", () => moveTo(view)); }
      else { if (c.slug !== active?.slug) paintOrigin(c); moveTo(view); }
    },
    () => { clearTimeout(release); locate.disabled = false; $("here").textContent = `Location unavailable — showing ${active?.name ?? FALLBACK.name}.`; },
    { timeout: 8000, maximumAge: 900000 }
  );
});

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
  $("time").textContent = "";
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
// `.length` on BOTH: an empty bandEdgesMin passed this check and then threw
// inside expandRamp at module top level, which is the same blank globe with no
// console error that the origins check was added to prevent.
if (!Array.isArray(meta.origins) || !meta.origins.length
    || !Array.isArray(meta.bandEdgesMin) || !meta.bandEdgesMin.length)
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
// The reading tier. When index.json advertises it, the number printed under
// the pointer comes from a res-6 array -- the grid the base band is painted
// from and the grid the hover ring already outlines -- instead of from the
// res-4 array above. Absent (a build made before the tier existed, or a
// connection that never delivered it), every reading falls back to res 4 and
// the page says which it used, so it is never silently one or the other.
const READING_RES = meta.readingRes ?? null;
const READING_PARENT_RES = meta.readingParentRes ?? 3;
// Published rather than recomputed: 342 instead of 343 finds the right block
// and then reads the wrong slot inside it, which stays in range and is wrong
// almost everywhere.
const READING_SLOTS = meta.readingSlots ?? 343;
const EDGES = meta.bandEdgesMin;
// Channel order of .modes.bin, from the emitter when index.json carries it.
const MODE_NAMES = meta.modeChannels ?? ["rail", "ferry", "highway", "major road", "minor road", "track"];

// shared, origin-independent cell ordering — fetched once
const hoverCells = await loadCells("./" + (meta.hoverCellsUrl || "hover_cells.bin"));
if (meta.hoverCellCount != null && meta.hoverCellCount !== hoverCells.length)
  fatal(`index.json expects ${meta.hoverCellCount} hover cells but hover_cells.bin has ${hoverCells.length}: the two files come from different builds.`);

// Antarctica is charted so the globe has no hole in it, but it has no
// scheduled passenger service, so every one of its cells is unreachable by
// construction. src/transport_maps/validate.py excludes them from the coverage
// gate by name and explains why; the departure card counted them, so every
// city printed the same "10.2% has no scheduled route from here" -- a fact
// about the dataset, not about the city -- and every reach figure was diluted
// by the same 8.54% of the grid.
//
// The exclusion needs one latitude per hover cell: 90,740 h3.cellToLatLng
// calls, measured at 50.3 ms. That is too much to spend on the load path, so
// it runs in idle slices while the first origin's arrays are still in flight
// and finishes synchronously if something asks for it first.
const KNOWN_UNREACHABLE_MAX_LAT = -60.0;
let chartedMask = null, chartedCount = 0, chartedDone = 0;
function chartedSlice(budget) {
  if (!chartedMask) chartedMask = new Uint8Array(hoverCells.length);
  const end = Math.min(hoverCells.length, chartedDone + budget);
  for (let i = chartedDone; i < end; i++) {
    if (h3.cellToLatLng(hoverCells[i].toString(16))[0] > KNOWN_UNREACHABLE_MAX_LAT) {
      chartedMask[i] = 1;
      chartedCount++;
    }
  }
  chartedDone = end;
  return chartedDone === hoverCells.length;
}
function charted() {
  while (!chartedSlice(hoverCells.length)) { /* finish it now */ }
  return chartedMask;
}
(function primeCharted() {
  // The fallback used to hand back `timeRemaining: () => 8` -- a CONSTANT, so
  // the budget test three lines down never tripped and the whole 90,740-cell
  // pass ran inside one setTimeout(0) task. The comment above measures that
  // pass at 50.3 ms and calls it "too much to spend on the load path", which
  // is exactly what it was spending, on every browser without the real API.
  //
  // That is not a rare browser. requestIdleCallback is disabled by default in
  // every shipping Safari (desktop and iOS), so this was every iPhone and iPad
  // visitor: a 50 ms main-thread block while the page is still loading.
  // A real clock makes the existing loop yield as it was written to.
  const idle = globalThis.requestIdleCallback
    || ((fn) => setTimeout(() => {
      const start = performance.now();
      fn({ timeRemaining: () => Math.max(0, 8 - (performance.now() - start)) });
    }, 0));
  idle(function step(deadline) {
    // ~8000 cells per millisecond of measured budget, floor of one slice.
    while (chartedDone < hoverCells.length && deadline.timeRemaining() > 1) chartedSlice(4000);
    if (chartedDone < hoverCells.length) idle(step);
  });
})();

// The ocean, independent of the colour scheme. Each scheme already carries
// its own `sea`, and "scheme" keeps that -- but the sea is most of the globe
// and wanting it a different colour is not the same wish as wanting different
// bands.
//
// These are NOT free choices. scripts/check_ramps.py enforces three things on
// any sea: lighter than SPACE (or the globe's edge disappears into the page),
// darker than the darkest band of EVERY scheme (or the darkest band stops
// reading as land), and at least MIN_GREY_DELTA_E from every one of the 37
// painted bands of every scheme (or the sea reads as a band). That leaves a
// lightness window of roughly 0.17 to 0.22 in OKLab, so what varies here is
// hue, not brightness. Each was found by searching that window and is
// measured by tests/web/test_ramps.py against all twelve schemes; the worst
// margin of the five is charcoal, at 8.8 against a floor of 8.
const OCEANS = {
  scheme:   { name: "Match the scheme", sea: null },
  deep:     { name: "Deep blue", sea: "#00142b" },
  teal:     { name: "Teal",      sea: "#001619" },
  forest:   { name: "Forest",    sea: "#051902" },
  umber:    { name: "Umber",     sea: "#210d00" },
  charcoal: { name: "Charcoal",  sea: "#131112" },
};

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
  "minor road": "Tertiary roads at a fitted speed; local roads at a published-figure "
                + "default. Both halved inside cities.",
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
//: True while #where holds "Loading the times from …" rather than a reading or
//: the idle prompt. settle() used to detect that by string-matching the
//: element, which any other writer could defeat.
let whereIsLoading = false;
let lastPointer = null;         // {lat, lng, point} of the last reading, re-run when data lands
// The one comparison the page offers: the figure read at the current pin from
// the PREVIOUS departure city. Switching city used to discard it -- Turkmenabat
// is 14 h 39 min from Seoul and 18 h 22 min from Tokyo, and nothing on screen
// ever said so. Captured before the arrays are dropped, keyed to the pin it
// was measured at, cleared when the pin moves.
let lastFrom = null;
let firstPaint = true;          // the opening view is jumped to, not flown to
// The readout's resting copy; a phone has no pointer.
const COARSE = window.matchMedia("(pointer: coarse)").matches;
// The small-layout breakpoint. Declared here beside COARSE, above every reader,
// rather than beside layoutForSize() 2,260 lines down: openRoutePanel consults
// it, and U25 shipped a blank page from a const read before its declaration.
const SMALL = window.matchMedia("(max-width: 860px)");
const IDLE_PROMPT = COARSE
  ? "Tap the map to read a travel time. Tap a city name to depart from it."
  : $("where").textContent;
// What stands where the number goes before there is a number. It used to be an
// em dash at 50px -- the largest element on the page at rest, and the first
// thing a visitor saw. The height is reserved in CSS so nothing jumps when the
// first reading lands.
const IDLE_TIME = `<span class="idle">${COARSE ? "Tap" : "Point"} anywhere on the globe `
  + "for the travel time from your departure city, door to door.</span>";
function clearTime(msg) {
  $("time").innerHTML = msg === undefined ? IDLE_TIME : `<span class="idle">${esc(msg)}</span>`;
}

// ---- settings, remembered per viewer ----
const store = {
  get(k, d) {
    try { const v = localStorage.getItem(k); return v === null ? d : v === "1"; }
    catch { return d; }
  },
  set(k, v) { try { localStorage.setItem(k, v ? "1" : "0"); } catch { /* private mode */ } },
};
// Object.hasOwn, not `RAMPS[r]`: "constructor", "toString" and "__proto__"
// are all truthy on any object literal, so localStorage.ramp = "constructor"
// set rampName to a prototype method, and the next line threw at module top
// level -- before fatal() could report anything. A blank globe with nothing in
// the console is this project's signature failure.
try { const r = localStorage.getItem("ramp"); if (r && Object.hasOwn(RAMPS, r)) rampName = r; }
catch { /* private mode */ }
// Object.hasOwn for the same reason as the ramp above: a stored "constructor"
// or "__proto__" is truthy on any object literal and would reach paintSea as
// a prototype method.
let oceanName = "scheme";
// What the sea is actually painted with: the chosen ocean, or the scheme's
// own when "Match the scheme" is selected. The legend key, the globe and the
// picker's own swatch must all agree, and before this they read it three
// different ways.
const seaNow = () => OCEANS[oceanName]?.sea ?? RAMPS[rampName]?.sea ?? SEA;
try { const o = localStorage.getItem("ocean"); if (o && Object.hasOwn(OCEANS, o)) oceanName = o; }
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
  // seaNow(), not the ramp's: the legend's "open water" key has to be the
  // colour the globe's water actually is, or the key stops being a key.
  $("sw-sea").style.background = seaNow();
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
// The Map constructor throws SYNCHRONOUSLY when WebGL is unavailable
// ("Failed to initialize WebGL", quoted from the vendored bundle), and
// everything that fills this page runs after it: the city list, the ramp
// picker, layoutForSize, paintOrigin. So fatal() was never reached and the
// shell stayed up with an empty list -- and a <canvas> HAS already been
// created by then, so CLAUDE.md's "confirm the canvas exists" passes on a
// page that cannot draw anything. The page already owns the right sentence,
// but it lives in <noscript>, which by definition cannot render when
// JavaScript ran and WebGL did not.
if (!(() => {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch { return false; }
})()) {
  fatal("This browser cannot draw the globe: it needs WebGL, which is "
      + "unavailable or switched off. Hardware acceleration in the browser's "
      + "settings is the usual cause.");
}

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
  attributionControl: false, dragRotate: true,
  // MapLibre labels its own canvas "Map", and that string -- not #map's
  // aria-label, which is on the container -- is what a screen reader reads
  // when focus lands on the canvas. WCAG 4.1.2.
  locale: {
    "Map.Title": "Globe shaded by travel time from the departure city. "
      + "Arrow keys pan, plus and minus zoom, Enter sets a destination.",
  }
});

// The only listener MapLibre has for `error` is a console.error, so a missing
// origins/{slug}.pmtiles, or a server that stops honouring byte ranges, gave a
// sea-coloured globe with a full legend, a working readout and no message.
// index.json and hover_cells.bin go through fatal(); all five per-origin
// fetches have a .catch; the tile archive had nothing.
//: The map source id for the coastline archive. Declared here, above its only
//: two readers, so `noteTileTrouble` and `addSource` cannot drift apart and
//: leave the notice naming the wrong layer.
const WATER_SOURCE = "water";
map.on("error", (e) => {
  const msg = e?.error?.message || String(e?.error || "unknown map error");
  console.error("map error:", msg);
  // A tile or source failure is not fatal to the page -- the readout still
  // works from the arrays -- but it must not be silent.
  //
  // It WAS silent. This used to test the message text against
  // /pmtiles|tile|source/i, and pmtiles.js emits none of those words: its real
  // failures read "Bad response code: 404" and "archive does not appear to
  // support HTTP Byte Serving". Served the real dist/ with the archives
  // withheld, the page measured bandsRendered:0, waterRendered:0 and
  // #tiletrouble still hidden -- a blank globe with nothing said about it,
  // which CLAUDE.md's deploy rule records as having shipped twice. The guard
  // passed review because its verification fired a synthetic error carrying the
  // literal string "pmtiles".
  //
  // MapLibre already names the failing source on the event. Use that; keep the
  // message test only as a fallback for errors raised outside a source.
  if (e?.sourceId || /pmtiles|tile|source/i.test(msg)) noteTileTrouble(msg, e?.sourceId);
});
// This used to write into #where, which showReading rewrites on every pointer
// frame: the one sentence that explains a blank globe was erased milliseconds
// after it appeared. And `tileTroubleShown` latched for the session, so it
// could never return -- including for a DIFFERENT origin's missing .pmtiles
// later on. Its own element, cleared when the next origin's tiles load.
//
// The message also has to say which layer failed. Both the band tiles and the
// coastline arrive as .pmtiles, and "the globe is blank" is wrong when it is
// the water that is missing and the bands are fine.
let tileTroubleFor = null;
function noteTileTrouble(msg, sourceId) {
  const el = document.getElementById("tiletrouble");
  if (!el) return;
  // sourceId is the map's own answer to "which layer?"; the URL in the message
  // is a guess that only worked while the message happened to carry one.
  const water = sourceId ? sourceId === WATER_SOURCE : /water\.pmtiles/i.test(msg);
  const key = (water ? "water:" : "bands:") + (active?.slug || "");
  if (tileTroubleFor === key) return;      // do not restate the same failure
  tileTroubleFor = key;
  el.textContent = water
    ? "The coastline could not be loaded, so the map has no shoreline. The "
      + "bands and the travel times are unaffected. (" + msg.slice(0, 120) + ")"
    : "The shaded bands could not be loaded, so the globe is blank. The travel "
      + "times below are still correct. (" + msg.slice(0, 120) + ")";
  el.hidden = false;
}
function clearTileTrouble() {
  tileTroubleFor = null;
  const el = document.getElementById("tiletrouble");
  if (el) { el.hidden = true; el.textContent = ""; }
}

// ...and a load that never fires at all. `await map.on("load")` had no timeout,
// so a WebGL context lost during setup left this promise pending for ever with
// nothing on screen and nothing in the console.
await Promise.race([
  new Promise((r) => map.on("load", r)),
  new Promise((_, reject) => setTimeout(
    () => reject(new Error("the globe did not finish loading within 20 seconds")), 20000)),
]).catch((e) => fatal(`${e.message}. Reloading the page usually clears it.`));
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
map.addSource(WATER_SOURCE, { type: "vector", url: "pmtiles://./water.pmtiles" });
map.addLayer({ id: "water", type: "fill", source: WATER_SOURCE, "source-layer": "water",
  paint: { "fill-color": SEA, "fill-opacity": 1 } });
// Sea and lakes take the colour scheme's own ground, so switching schemes
// recolours the water as well as the land.
function paintSea() {
  const sea = seaNow();
  for (const id of ["sphere", "water"])
    if (map.getLayer(id)) map.setPaintProperty(id, "fill-color", sea);
}
paintSea();

// The hovered cell, outlined so the reading has a visible footprint.
map.addSource("hover", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
// A dark halo under the white line. White alone measured 1.15:1 against the
// palest band -- the ring around the departure city, where every visitor
// points first, was invisible. The halo ships at line-opacity 0.55, so what
// reaches the eye is the COMPOSITE, #767260, at 4.19:1 on band 0 -- clear of
// WCAG 2.2 SC 1.4.11's 3:1, and the figure this comment used to give (17.0:1,
// the unblended colour) was four times the delivered value. It disappears
// into the darkest bands, where the white line is already unmissable.
map.addLayer({ id: "hover-halo", type: "line", source: "hover",
  paint: { "line-color": "#0a0b0d", "line-width": 3.5, "line-opacity": 0.55 } });
map.addLayer({ id: "hover-line", type: "line", source: "hover",
  paint: { "line-color": "#ffffff", "line-width": 1.5, "line-opacity": 0.9 } });
map.addLayer({ id: "hover-fill", type: "fill", source: "hover",
  paint: { "fill-color": "#ffffff", "fill-opacity": 0.10 } });

// ---- the journey, drawn on the globe ----
// The itinerary panel already lists the legs; this is the same walk of the
// same chain, so the line and the text cannot disagree -- renderLegs() calls
// renderRoute() and nothing else builds it.
//
// White over a dark halo, the treatment the hover ring already uses, because
// it has to read on all 37 bands of twelve schemes and on any ocean. Flights
// are solid and ground legs dashed: the flight path is a real great circle,
// while a ground leg is a straight line between two points the model never
// claimed to route between, and it should not pretend otherwise.
map.addSource("route", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
map.addLayer({ id: "route-halo", type: "line", source: "route",
  layout: { "line-cap": "round", "line-join": "round" },
  paint: { "line-color": "#0a0b0d", "line-width": 4.5, "line-opacity": 0.5 } });
map.addLayer({ id: "route-air", type: "line", source: "route",
  filter: ["==", ["get", "kind"], "air"],
  layout: { "line-cap": "round", "line-join": "round" },
  paint: { "line-color": "#ffffff", "line-width": 1.6, "line-opacity": 0.92 } });
// line-dasharray is not data-driven in MapLibre, so the two kinds need two
// layers rather than one expression.
map.addLayer({ id: "route-ground", type: "line", source: "route",
  filter: ["==", ["get", "kind"], "ground"],
  layout: { "line-cap": "butt", "line-join": "round" },
  paint: { "line-color": "#ffffff", "line-width": 1.4, "line-opacity": 0.75,
           "line-dasharray": [2, 2.5] } });

// Your own position, once geolocation answers.
map.addSource("me", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
map.addLayer({ id: "me-halo", type: "circle", source: "me",
  paint: { "circle-radius": 9, "circle-color": "#ffffff", "circle-opacity": 0.18 } });
map.addLayer({ id: "me-dot", type: "circle", source: "me",
  paint: { "circle-radius": 4, "circle-color": "#ffffff",
           "circle-stroke-color": "#0a0b0d", "circle-stroke-width": 1.5 } });

// The destination itself. The point-to-point panel described a point the map
// never drew: `pinB` had no source, no layer and no marker anywhere, so the
// itinerary named a place with nothing on the globe to say where it was.
// Accent, not white, so it cannot be mistaken for "you are here".
map.addSource("pin", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
map.addLayer({ id: "pin-halo", type: "circle", source: "pin",
  paint: { "circle-radius": 10, "circle-color": "#e48f35", "circle-opacity": 0.22 } });
map.addLayer({ id: "pin-dot", type: "circle", source: "pin",
  paint: { "circle-radius": 4.5, "circle-color": "#e48f35",
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
  for (const id of ["route-halo", "route-ground", "route-air",
                    "hover-halo", "hover-fill", "hover-line",
                    "pin-halo", "pin-dot", "me-halo", "me-dot"])
    if (map.getLayer(id)) map.moveLayer(id);
}).catch(() => {});

// A flyTo arc becomes a cut when the visitor asked for less motion.
const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");
function moveTo(opts) { if (REDUCED_MOTION.matches) map.jumpTo(opts); else map.flyTo(opts); }

// The globe was framed for 1280x800 and clipped everywhere else. The opening
// zoom was the literal 1.9 whatever the window, so at 390x844 the sphere spans
// x -64 to 454 -- a quarter of it off-screen -- and at 844x390 it loses a fifth
// off the top and bottom, with the east limb behind the rail. The zoom only
// ever comes DOWN from 1.9: a desktop window keeps exactly the framing it has.
//
// The measured diameter at zoom 1.9 is 518 px, and the globe scales by 2^zoom,
// so the zoom that fits a given diameter is 1.9 + log2(want / 518).
const GLOBE_PX_AT_1_9 = 518;
function panelBox() {
  // The rail is a right-hand column on a desktop and a bottom sheet on a
  // phone; ask the element rather than re-deriving the breakpoints.
  const r = document.querySelector(".rail")?.getBoundingClientRect();
  if (!r || !r.width) return { right: 0, bottom: 0 };
  const side = r.left > innerWidth * 0.5;
  return { right: side ? Math.max(0, innerWidth - r.left) : 0,
           bottom: side ? 0 : Math.max(0, innerHeight - r.top) };
}
function viewPadding() {
  const { right, bottom } = panelBox();
  // Nudge the centre out of the panel's half, so the departure city is
  // centred in what the visitor can actually see.
  return { top: 0, left: 0, right: Math.min(right, innerWidth * 0.45),
           bottom: Math.min(bottom, innerHeight * 0.45) };
}
let framedZoom = 1.9;
function openingZoom() {
  const { right, bottom } = panelBox();
  const want = Math.min(innerWidth - right, innerHeight - bottom) * 0.88;
  framedZoom = (want > 0) ? Math.min(1.9, 1.9 + Math.log2(want / GLOBE_PX_AT_1_9)) : 1.9;
  return framedZoom;
}
// Re-frame when the window changes shape -- a rotated phone would otherwise
// keep the portrait framing -- but only while the visitor is still at the
// opening view. Once they have zoomed in they are reading a region, and
// moving the camera under them would be worse than a clipped limb.
addEventListener("resize", () => {
  const wasFramed = map.getZoom() <= framedZoom + 0.01;
  const z = openingZoom();
  if (wasFramed) map.jumpTo({ zoom: z, padding: viewPadding() });
  fitReading();
});

// Whether a point is on the visible face of the globe: project() happily
// returns on-disc coordinates for Lima while the view faces Beijing.
//: How far outside the globe's silhouette a pointer may stray and still be
//: treated as pointing at the Earth. The round-trip error below IS that
//: distance in pixels, so this is a literal tolerance, not a magic number.
const OFF_GLOBE_PX = 2;

// Is this screen point actually ON the globe?
//
// It has to be asked, because MapLibre's unproject does not say. Past the
// silhouette it CLAMPS to the nearest point on the limb and returns that same
// coordinate for every pixel further out: measured at zoom 2, every sample
// from 200 px to 640 px from centre returned 154.87W 8.50N, while the round
// trip drifted from 30 px to 470 px. So the page reported a real town with a
// real travel time for a pointer sitting in black sky -- at 225 degrees it
// read "Munster, Lower Saxony, Germany, 16 h 58 min" with the cursor 600 px
// out in space, and a click there would have pinned a destination in Germany.
//
// project(unproject(p)) round-trips exactly on the globe and misses by the
// distance outside it beyond the limb, which makes it both the test and the
// measure.
function onGlobe(point) {
  if (!point) return false;
  const back = map.project(map.unproject(point));
  return Math.hypot(back.x - point.x, back.y - point.y) <= OFF_GLOBE_PX;
}

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
    // enableRotation(), not enable(). MapLibre's KeyboardHandler keeps
    // `_enabled` and `_rotationDisabled` as separate flags: disableRotation()
    // sets the second, and enable() clears only the first -- which was never
    // set, because nothing ever called disable(). So unticking "Lock to
    // north" restored bearing and pitch for the mouse and for touch and
    // silently left the keyboard locked for the rest of the session.
    map.keyboard.enableRotation();
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
// A dotted label is a dot plus a name, in that order, because the dot is what
// sits on the coordinate. textContent would wipe the dot, so both label paths
// go through here.
function setDottedLabel(el, name) {
  const dot = el.querySelector(".dot") || document.createElement("span");
  dot.className = "dot";
  el.replaceChildren(dot, document.createTextNode(name));
}

const originLabel = document.createElement("button");
originLabel.type = "button";
originLabel.className = "lbl origin";
originLabel.setAttribute("aria-current", "true");
originLabel.tabIndex = -1;
originLabel.addEventListener("click", (ev) => ev.stopPropagation());
// anchor "left", not "top". A label that carries a dot is claiming the dot
// marks the city -- but with anchor "top" the coordinate is the top-centre of
// the whole box, which is in the middle of the TEXT, and the dot sits to its
// left. Measured live at zoom 5: the dot was 23 px from Tokyo, 27 from
// Beijing, 32 from Shanghai and 34 from Hangzhou, the error growing with the
// width of the name -- 20 to 30 km on the ground. Anchoring left puts the
// element's left edge, vertically centred, on the point -- and the dot is
// placed there by CSS, so no pixel offset is needed and none can go stale
// when the font size changes.
const originMarker = new maplibregl.Marker({ element: originLabel, anchor: "left" });
// MapLibre stamps role="button" aria-label="Map marker" on every marker
// element, so the departure city announced as "Map marker, button, current"
// and its visible name was nowhere in its accessible name (WCAG 2.2 SC 2.5.3,
// Label in Name). Set after construction, which is when MapLibre has applied
// its defaults.
const nameMarker = (el, label) => {
  if (label) { el.setAttribute("aria-label", label); el.setAttribute("role", "button"); }
  else { el.removeAttribute("aria-label"); el.removeAttribute("role"); }
};
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
    // The departure block names the city's region and country from the
    // gazetteer, which usually lands after the first paint.
    renderDeparture();
    // ...and so does the departure LIST, for the four names shared by two
    // cities each. render() has one data-driven call site, in settle(), which
    // fires when {slug}.bin arrives -- 181 KB against this file's 1.8 MB, so
    // the list is almost always built before the gazetteer that would tell
    // "Suzhou" from "Suzhou". Rebuild once, here, and only when there is
    // something to disambiguate: with no duplicate names nothing in a row
    // depends on `places` at all.
    if (ambiguousNames().size) render($("q").value);
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
      // Not `origin`: that is the module-level record of the CURRENT
      // departure's fetched arrays, and shadowing it here -- inside the one
      // file whose state block exists to keep those names straight -- is how
      // the next reader of this closure gets it wrong.
      const cityHere = originNear(r[3], r[4], 15);
      const el = document.createElement(cityHere ? "button" : "div");
      el.className = cityHere ? "lbl origin" : "lbl";
      if (cityHere) {
        setDottedLabel(el, r[0]);
        el.type = "button";
        el.tabIndex = -1;                  // the city list is the keyboard path
        el.title = `Depart from ${cityHere.name}`;
        el.dataset.slug = cityHere.slug;
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();            // not a destination pin
          $("here").textContent = "";
          if (cityHere.slug !== active?.slug) paintOrigin(cityHere, { keepZoom: true });
        });
      } else {
        el.textContent = r[0];
        el.addEventListener("click", (ev) => ev.stopPropagation());
      }
      // A name with a dot is anchored by its dot; a bare place name keeps the
      // conventional treatment of hanging below its point.
      const m = new maplibregl.Marker(
        { element: el, anchor: cityHere ? "left" : "top" })
        .setLngLat([r[4], r[3]]);
      // A label that departs is a button and says so; every other label is
      // map furniture, not a control, and was being announced as a button
      // that does nothing.
      if (cityHere) el.dataset.label = `Depart from ${cityHere.name}`;
      nameMarker(el, cityHere ? el.dataset.label : null);
      return { m, rank: i, on: false, lat: r[3], lon: r[4], slug: cityHere?.slug };
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
        if (!originMarkerOn) {
          originMarker.addTo(map); originMarkerOn = true;
          nameMarker(originLabel, `${active.name}, the departure city`);
        }
      } else if (originMarkerOn) { originMarker.remove(); originMarkerOn = false; }
      for (const l of labelPool) {
        let want = l.rank < n && onNearSide(l.lat, l.lon);
        if (want) {
          const pt = map.project(l.m.getLngLat());
          want = pt.x > -50 && pt.y > -20 && pt.x < window.innerWidth + 50
              && pt.y < window.innerHeight + 20 && !collides(pt);
          if (want) placed.push(pt);
        }
        if (want && !l.on) {
          l.m.addTo(map); l.on = true;
          // AFTER addTo, not before. Marker.addTo() re-applies
          // role="button" aria-label="Map marker" behind hasAttribute
          // guards, so removing them at construction did nothing: 29 of 29
          // plain labels still announced as "Map marker, button" (WCAG
          // 4.1.2). Origin labels survived only because their branch SETS
          // the attributes rather than removing them.
          nameMarker(l.m.getElement(), l.slug ? l.m.getElement().dataset.label : null);
        } else if (!want && l.on) { l.m.remove(); l.on = false; }
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
// How far this city actually reaches, from the array already in memory: no
// new request, no rebuild. Thresholds a person thinks in -- half a day, a
// day, two days -- as a share of the charted land the hover grid covers.
const REACH_STEPS = [[720, "12 hours"], [1440, "a day"], [2880, "two days"]];
// Wrapper for the same reason as renderLegs: the card's height is one of the
// two inputs to fitReading, and every early return changes it.
function renderDeparture() { renderDepartureInto(); fitReading(); }
function renderDepartureInto() {
  const box = $("depart");
  if (!box) return;
  if (!active) { box.hidden = true; return; }
  box.hidden = false;
  $("depart-city").textContent = active.name;
  const p = places ? nearestPlace(active.lat, active.lon) : null;
  $("depart-where").textContent = p
    ? [p.region && p.region !== active.name ? p.region : null, p.country].filter(Boolean).join(", ")
    : "";

  const t = origin.times;
  const reach = $("depart-reach");
  if (!t || !t.length) {
    reach.replaceChildren();
    $("depart-note").textContent = origin.failed
      ? "Travel times for this city are unavailable."
      : "Reading the travel times…";
    return;
  }
  const mask = charted();
  let unreached = 0, denom = 0;
  const counts = REACH_STEPS.map(() => 0);
  for (let i = 0; i < t.length; i++) {
    if (!mask[i]) continue;               // Antarctica: unreachable by construction
    denom++;
    const v = t[i];
    if (v >= MAX_MINUTES) { unreached++; continue; }
    for (let k = 0; k < REACH_STEPS.length; k++) if (v <= REACH_STEPS[k][0]) counts[k]++;
  }
  const pct = (n) => `${(100 * n / (denom || 1)).toFixed(1)}%`;
  reach.replaceChildren(...REACH_STEPS.flatMap(([, label], k) => {
    const dt = document.createElement("dt"); dt.textContent = `Within ${label}`;
    const dd = document.createElement("dd"); dd.textContent = pct(counts[k]);
    return [dt, dd];
  }));
  // "from here" was wrong, and identically wrong from every departure city:
  // a cell counts as unreached when no scheduled service reaches it at ALL,
  // which is a property of that cell's isolation, not of where you started.
  // Eight origins on six continents printed the same 1.851 %.
  $("depart-note").textContent =
    `Share of charted land outside Antarctica, door to door. `
    + `${pct(unreached)} is reached by no scheduled service from anywhere, `
    + `so it is the same share from every departure city.`;
}

// ?from= carried the departure and nothing else, so the interesting half of a
// reading could not be shared: the link reopened the city, not the journey.
// `to` is "lat,lon" rounded to five decimals -- about a metre, far finer than
// the 5.4 km cell the answer is drawn from, and short enough to read.
function syncPermalink() {
  try {
    const url = new URL(location.href);
    if (active) url.searchParams.set("from", active.slug); else url.searchParams.delete("from");
    if (pinB) url.searchParams.set("to", `${pinB.lat.toFixed(5)},${pinB.lon.toFixed(5)}`);
    else url.searchParams.delete("to");
    history.replaceState(null, "", url);
  } catch { /* file:// or a sandbox without history */ }
}

// The times array the city list was last built from; see settle().
let listTimesFor = null;

// Names shared by more than one departure city, computed once, LAZILY.
// `cities` is declared several hundred lines below this point, so an IIFE
// here reads it in its temporal dead zone and throws at module scope --
// before the map exists, with a blank page and (as this repository has
// twice shipped) nothing useful in the console afterwards. Written that
// way first; caught by opening the page.
let _ambiguous = null;
function ambiguousNames() {
  if (_ambiguous) return _ambiguous;
  const seen = new Set();
  _ambiguous = new Set();
  for (const c of cities) (seen.has(c.name) ? _ambiguous : seen).add(c.name);
  return _ambiguous;
}
// "slower than from Suzhou" is useless when you have just switched between
// the two cities called Suzhou; say which one.
function lastFromLabel() {
  if (!lastFrom) return "";
  if (!ambiguousNames().has(lastFrom.name)) return lastFrom.name;
  const c = bySlug.get(lastFrom.slug);
  const where = c && cityCountry(c);
  return where ? `${lastFrom.name} (${where})` : lastFrom.name;
}
function cityCountry(c) {
  if (c.country) return c.country;
  const p = places ? nearestPlace(c.lat, c.lon) : null;
  return (p && (p.country || p.region)) || "";
}

function captureComparison() {
  if (!pinB || !active) return (lastFrom = null);
  const t = lookup(pinB.lat, pinB.lon);
  // The SLUG, not only the name: the comparison was suppressed whenever the
  // two cities shared a name, which is exactly the pair a visitor is most
  // likely to click, since the list sorts by name and puts them adjacent.
  lastFrom = (typeof t === "number" && t < MAX_MINUTES)
    ? { slug: active.slug, name: active.name, min: t, lat: pinB.lat, lon: pinB.lon } : null;
}

function paintOrigin(o, { keepZoom = false } = {}) {
  // U13 landed only its #tip half. Four of the five call sites tested the slug
  // and the results-list handler did not, so clicking the row you are ALREADY
  // departing from -- the highlighted one, aria-current="true", the obvious
  // thing to click to "go back to Seoul" -- removed and re-added the bands
  // layer, aborted and re-issued about 700 KB of fetches, blanked the
  // itinerary, announced a no-op, rebuilt 553 rows, and (keepZoom defaults to
  // false) flew the camera back to the world view, discarding the region the
  // visitor was reading.
  //
  // The guard belongs here rather than at the fifth call site, so a sixth
  // cannot reintroduce it. A failed origin is still retryable: that is the one
  // case where re-picking the active city has something to do.
  if (o.slug === active?.slug && !origin.failed) return;
  if (o.slug !== active?.slug) captureComparison();
  active = o;
  const gen = ++originGen;
  originAbort?.abort();
  const ctl = originAbort = new AbortController();
  const sig = ctl.signal;

  clearTileTrouble();
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
      "fill-opacity": 1,
      // MapLibre defaults fill-antialias to true, which draws a 1px
      // antialiased outline around EVERY polygon in fill-outline-color
      // (itself defaulting to fill-color). At a shared rim the top polygon's
      // edge pixel is only partly covered, so it composites with the band
      // underneath and lands darker than either: a hairline tracing the
      // boundary. With 37 bands, most of them one cell wide near the origin,
      // almost every hexagon edge IS a band boundary -- so the map read as
      // hexagons with outlines drawn between them.
      //
      // Measured on the bands layer alone, everything else hidden, at z7.2:
      // 236 one-pixel dark seams with antialiasing, 15 without. The two
      // renders differ by 22,484 px, 89% of them in runs one or two pixels
      // wide, running in several directions -- hexagon rims.
      //
      // Turning it off costs an aliased edge, but only where the band mass
      // meets something of a different colour. Adjacent bands are one ramp
      // step apart (OKLab dE about 2), so an aliased edge between them is
      // invisible; the coast is covered by the water layer above. That leaves
      // the outer silhouette, which is measured in the commit that set this.
      "fill-antialias": false
    }
  }, "water");

  // Nothing of the previous origin survives the switch: the arrays are nulled
  // in one synchronous pass, and every response below is applied only while
  // this switch is still the latest one.
  origin.times = null; origin.failed = null; origin.air = null;
  origin.modes = null; origin.routes = null; origin.rail = null;
  // 10 MB per origin. Dropped on the switch rather than kept per city, so the
  // page holds one reading array at a time however many cities are visited.
  origin.reading = null;
  const current = () => gen === originGen;
  const settle = () => {
    if (!current()) return;
    renderPins(); renderLegs(); renderDeparture();
    // The city list carries a door-to-door time per row now, so it is stale
    // until the arrays land -- and stale again on every origin switch. Once
    // per arrival, not once per settle: settle() runs five times an origin,
    // and rebuilding 553 rows five times is four rebuilds nobody sees.
    if (origin.times && listTimesFor !== origin.times) {
      listTimesFor = origin.times;
      render($("q").value);
      // paintOrigin announces "Loading travel times" and nothing resolved it:
      // #status kept saying so until a reading was committed, which may be
      // never. Once per arrival, on the same guard as the list rebuild.
      announce(`Travel times from ${originName()} are ready. `
        + "Move the pointer over the map, or choose a destination.");
    }
    // The reading under the pointer (or the last tap) is redone once the
    // times land; with no pointer yet, the idle prompt replaces "loading".
    if (lastPointer) rereadPointer();
    // This used to string-match #where for "Loading", so ANY other writer
    // between the two -- the tile-trouble notice did exactly this -- left
    // "Loading the times from Seoul…" on screen for the rest of the session.
    // A flag says what the state is; the text says what the state looks like.
    else if (origin.times && whereIsLoading) {
      $("where").textContent = IDLE_PROMPT;
      whereIsLoading = false;
      // ...and the number's space stops saying "Reading the travel times" once
      // they have been read. Without this it said so for the rest of the
      // session, which is the same defect the departure card had.
      clearTime();
    }
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

  // The reading tier: one whole fetch, off the critical path, abortable on an
  // origin switch. Deliberately not range requests -- the deploy gzips
  // `location ~* \.bin$`, nginx cannot serve a byte range out of a gzipped
  // response, and a browser cannot opt out of Accept-Encoding, so a ranged
  // .bin comes back 200 with the WHOLE body and slicing it would read block 0
  // for every point on Earth with no error anywhere.
  const loadReading = () => {
    if (!READING_RES || !meta.readingUrlSuffix) return;
    // An explicit request not to spend the visitor's bytes on something the
    // page can already do without. The res-4 reading stands, and the line
    // under the number says so.
    if (navigator.connection && navigator.connection.saveData) return;
    loadReadingParents().then((cells) => {
      if (!cells || !current()) return null;
      return get(`./origins/${o.slug}${meta.readingUrlSuffix}`)
        .then((r) => (r.ok ? r.arrayBuffer() : null))
        .then((b) => {
          if (!b || !current()) return;
          // Same refusal the other five arrays get.
          origin.reading = checkedReading(b, cells.length,
                                          `${o.slug}${meta.readingUrlSuffix}`);
          // The number under the pointer and every row of the city list were
          // read off the coarse grid; both are redone once, in place. Not
          // settle(): that would re-announce "travel times are ready" to a
          // screen reader for data that was already there.
          if (lastPointer) rereadPointer();
          render($("q").value);
          renderDeparture();
        });
    }).catch((err) => {
      if (current() && !sig.aborted) console.warn("finer readings unavailable:", err.message);
    });
  };

  // Station naming exists only in builds whose index.json says so; asking an
  // older build for it was two 404s per origin switch.
  if (meta.railDetail) Promise.all([
    get(`./origins/${o.slug}.rail.bin`).then((r) => (r.ok ? r.arrayBuffer() : null)),
    get(`./origins/${o.slug}.rail.json`).then((r) => (r.ok ? r.json() : null)),
  ]).then(([b, j]) => {
    if (!current() || !b || !j) return;
    // T13 hardened {slug}.json's shape and stopped one file short of its
    // sibling. railVia() does rail.table[k] on every rail-served cell, so a
    // .rail.json without a stations array threw out of the click handler and
    // left the PREVIOUS destination's itinerary on screen, with no error.
    if (!Array.isArray(j.stations)) {
      console.warn(`${o.slug}.rail.json has no stations array; station names unavailable`);
      return;
    }
    origin.rail = { idx: checked(b, 2, `${o.slug}.rail.bin`), table: j.stations };
    settle();
  }).catch((err) => { if (current() && !sig.aborted) console.warn("rail detail unavailable:", err.message); });
  get(`./origins/${o.slug}.bin`)
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status} fetching ${o.slug}.bin`);
      return r.arrayBuffer();
    })
    .then((b) => {
      if (!current()) return;
      origin.times = checked(b, 2, `${o.slug}.bin`);
      settle();
      // Only now: the res-4 array is what makes the page usable, and the
      // reading array is 10 MB against its 181 KB. Starting them together
      // would put the big one in front of the small one on a mobile link for
      // a reading the small one can already answer to within a band.
      loadReading();
    })
    .catch((err) => {
      if (!current() || sig.aborted) return;
      console.error("hover data unavailable:", err);
      origin.failed = err.message;       // so the readout says "unavailable", not "loading"
      $("where").textContent = `Times unavailable for ${o.name}: ${err.message}.`;
      // #time was left on the string paintOrigin put there, so the page said
      // "Reading the travel times from Nairobi…" in 50 px directly above
      // "Times unavailable for Nairobi" -- the two halves of the readout
      // contradicting each other, with #where, #status and the departure card
      // all already correct. Not the idle prompt either: inviting a visitor to
      // point at a globe that has no numbers is its own small lie.
      clearTime("Travel times unavailable.");
      // renderDeparture, not only renderPins: without it the card's own
      // "Travel times for this city are unavailable." string was unreachable
      // and it sat on "Reading the travel times..." for ever. And announce()
      // or #status keeps saying "Loading travel times" with nothing ever
      // correcting it (WCAG 4.1.3).
      announce(`Travel times for ${o.name} could not be loaded.`);
      renderPins();
      renderLegs();
      renderDeparture();
      // ...and the 553-row city list, which settle() rebuilds only when
      // origin.times arrives -- so on the failure path it never rebuilt at
      // all. It kept the PREVIOUS city's times under the new city's caption,
      // marked the new departure as a destination with a travel time to the
      // city you are departing from, and left the old departure showing
      // "departing". Every other per-origin surface was fixed in cycle 6 and
      // this one was missed. Clearing the stamp first, or render() would
      // rebuild from the stale array it is still holding.
      listTimesFor = null;
      render($("q").value);
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
      // {slug}.json is the one per-origin file no length check can cover: the
      // four .bin files are validated against hoverCells.length, but a rebuild
      // that changes only the dense-split rule leaves the res-4 parent set
      // bit-identical while offsets.airports moves by millions. Check the
      // shape here, so a mismatched file is "unavailable" rather than a
      // TypeError in the click path.
      const off = j && j.offsets;
      if (!off || !Number.isFinite(off.airports) || !Number.isFinite(off.stations)
          || !Array.isArray(j.nodes)) {
        console.warn(`${o.slug}.json has no usable offsets/nodes; routes unavailable`);
        return;
      }
      origin.routes = { offsets: off, byId: new Map(j.nodes.map((n) => [n.id, n])) };
      settle();
    })
    .catch((err) => { if (current() && !sig.aborted) console.warn("routes unavailable:", err.message); });

  // Keep the visitor's zoom when they chose the city from the globe (they
  // were reading a region); the list and the permalink open the world view.
  const opening = openingZoom();
  const zoom = keepZoom ? Math.min(Math.max(map.getZoom(), opening), 6) : opening;
  const view = { center: [o.lon, o.lat], zoom, padding: viewPadding() };
  // The FIRST paint jumps. The departure city is known before the map is even
  // constructed, so flying to it from an arbitrary opening centre spent about
  // two seconds animating a view no visitor had seen or asked for -- the tell
  // being that the reduced-motion path settles two seconds sooner. Every
  // later switch still flies: there the visitor has a view to be carried from.
  if (firstPaint) { firstPaint = false; map.jumpTo(view); }
  else moveTo({ ...view, speed: 0.75, curve: 1.5 });
  for (const b of document.querySelectorAll(".results button[data-slug]"))
    b.setAttribute("aria-current", String(b.dataset.slug === o.slug));
  $("origin-name").textContent = o.name;
  setDottedLabel(originLabel, o.name);
  originLabel.title = `Departure city: ${o.name}`;
  originMarker.setLngLat([o.lon, o.lat]);
  nameMarker(originLabel, `${o.name}, the departure city`);
  showLabels();
  // The readout belongs to the departure it names: say the new one is
  // loading rather than keep the old figure beside the new header.
  clearTime(`Reading the travel times from ${o.name}…`);
  $("where").textContent = `Loading the times from ${o.name}…`;
  whereIsLoading = true;
  // #tip is written on mousemove and hidden on mouseout, and nothing else
  // touched it. Departing by CLICKING A GLOBE LABEL leaves the pointer on the
  // canvas, so the previous city's door-to-door figure went on floating at the
  // cursor beside the new city's readout: two numbers for one place. The other
  // three switch paths were safe only because they leave the canvas.
  $("tip").hidden = true;
  // The address bar follows the departure, so the view can be shared.
  syncPermalink();
  // renderLegs too, not just renderPins. The itinerary belongs to the OLD
  // city and its arrays have just been dropped, so leaving it on screen put a
  // Seoul route under "Loading the times from Tokyo…" -- and, if the new
  // origin's files 404, it stayed there permanently beside "Times unavailable
  // for Tokyo".
  renderPins(); renderLegs(); renderDeparture();
  announce(`Departing from ${o.name}. Loading travel times.`);
}

// ---- readout ----
const fmtCoord = (lat, lon) =>
  `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? "N" : "S"} ${Math.abs(lon).toFixed(2)}°${lon >= 0 ? "E" : "W"}`;

// ---- the reading tier ----
// Shared by every origin (the block set does not vary with the departure
// city), so it is fetched once and only when the first origin's reading array
// is fetched -- never on the boot path, where it would be 117 KB in front of
// the first paint for a number the res-4 array can already answer.
let readingParents = null;
let readingParentsWanted = null;

function loadReadingParents() {
  if (readingParentsWanted) return readingParentsWanted;
  const url = "./" + (meta.readingParentsUrl || "reading_parents.bin");
  readingParentsWanted = loadCells(url).then((cells) => {
    readingParents = checkedParents(cells, meta.readingParentCount, url);
    return readingParents;
  }).catch((err) => {
    // Not fatal: the res-4 array still answers every reading. Clearing the
    // promise lets the next origin switch try again rather than leaving the
    // page on the coarse grid for the rest of the session.
    console.warn("finer readings unavailable:", err.message);
    readingParentsWanted = null;
    return null;
  });
  return readingParentsWanted;
}

// The two refusals the reading tier needs, as plain functions of their
// arguments so they can be RUN in a test rather than grepped for. The first
// version of this guard was `assert "meta.readingParentCount" in APP`, which
// stayed green when the comparison itself was replaced by `false`, because
// the name survived in the error message.
function checkedParents(cells, expected, url) {
  if (expected != null && expected !== cells.length)
    throw new Error(`index.json expects ${expected} reading blocks but ${url} has `
      + `${cells.length}: the two files come from different builds`);
  return cells;
}

// An array from another build is the right length for ITS directory and the
// wrong length for this one. Reading it anyway would print plausible times
// from the wrong places rather than fail, which is the failure mode this
// format has instead of a crash.
function checkedReading(b, blocks, name) {
  const want = blocks * READING_SLOTS * 2;
  if (b.byteLength !== want)
    throw new Error(`${name} is ${b.byteLength} bytes, expected ${want} `
      + `(${blocks} blocks x ${READING_SLOTS} slots): the files come from different builds`);
  return new Uint16Array(b);
}

// The slot of a cell inside its res-3 block: the h3 digits BELOW the parent
// resolution, read as a base-7 number. h3 packs fifteen 3-bit digits under the
// resolution nibble, digit r at bits (45-3r)..(47-3r).
//
// Deliberately NOT h3.cellToChildPos. The two res-3 pentagons that hold land
// have 286 children rather than 343, and for 285 of those 286 the two
// orderings disagree; one of the two contains Dalian, a departure city. For a
// hexagon parent they agree on all 343, so a test that used only hexagons
// would not tell them apart. src/transport_maps/emit/hover.py computes the
// same base-7 number, and tests/web/test_reading_slot.py runs both.
function readingSlot(id) {
  let slot = 0;
  for (let r = READING_PARENT_RES + 1; r <= READING_RES; r++)
    slot = slot * 7 + Number((id >> BigInt(45 - 3 * r)) & 7n);
  return slot;
}

// Position of a point's reading in the block array, or -1 when the block is
// not one that holds land.
function readingIndex(lat, lon) {
  const cell = h3.latLngToCell(lat, lon, READING_RES);
  const parent = BigInt("0x" + h3.cellToParent(cell, READING_PARENT_RES));
  let lo = 0, hi = readingParents.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1, v = readingParents[mid];
    if (v === parent) return mid * READING_SLOTS + readingSlot(BigInt("0x" + cell));
    if (v < parent) lo = mid + 1; else hi = mid - 1;
  }
  return -1;
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

// null: not land (known from hover_cells.bin alone, so the sea never reads
// "loading"); undefined: land whose times have not arrived, or failed.
function lookup(lat, lon) {
  // Whether the point is LAND is still decided by the res-4 cell list, which
  // is the only file that ships an explicit land set: a res-3 block holds
  // land but 18.3% of its slots do not, and those carry the same sentinel a
  // genuinely unreachable cell does. Asking the reading tier "is this sea?"
  // would answer "no route" for every one of them.
  const i = cellIndex(lat, lon);
  if (i < 0) return null;
  if (origin.reading && readingParents) {
    const j = readingIndex(lat, lon);
    if (j >= 0) return origin.reading[j];
  }
  return origin.times ? origin.times[i] : undefined;
}

// Which grid the last reading came from, for the line that says so.
function readingGrid() {
  return origin.reading && readingParents ? READING_RES : HOVER_RES;
}

// Walk the shortest-path tree back from where the journey landed. The chain is
// cell -> A_dep -> B_arr -> B_dep -> C_arr, so a connection shows up as an
// arrival immediately followed by a departure at the same airport.
// Longitudes made continuous, so a leg across the antimeridian is drawn the
// short way instead of all the way round the world.
function unwrap(pts) {
  const out = [pts[0].slice()];
  for (let i = 1; i < pts.length; i++) {
    const prev = out[i - 1], p = pts[i].slice();
    while (p[0] - prev[0] > 180) p[0] -= 360;
    while (p[0] - prev[0] < -180) p[0] += 360;
    out.push(p);
  }
  return out;
}

// A flight is a great circle, not a straight line in longitude and latitude:
// Seoul to New York passes near the pole, and drawn flat it would cross the
// Pacific instead. Sampled, then unwrapped.
function greatCircle(a, b) {
  const rad = Math.PI / 180, deg = 180 / Math.PI;
  const [lo1, la1] = [a[0] * rad, a[1] * rad], [lo2, la2] = [b[0] * rad, b[1] * rad];
  const d = 2 * Math.asin(Math.sqrt(
    Math.sin((la2 - la1) / 2) ** 2 +
    Math.cos(la1) * Math.cos(la2) * Math.sin((lo2 - lo1) / 2) ** 2));
  if (!(d > 1e-9)) return unwrap([a, b]);
  const n = Math.max(2, Math.min(64, Math.round(d * deg / 2)));
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const f = i / n;
    const A = Math.sin((1 - f) * d) / Math.sin(d), B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(la1) * Math.cos(lo1) + B * Math.cos(la2) * Math.cos(lo2);
    const y = A * Math.cos(la1) * Math.sin(lo1) + B * Math.cos(la2) * Math.sin(lo2);
    const z = A * Math.sin(la1) + B * Math.sin(la2);
    pts.push([Math.atan2(y, x) * deg, Math.atan2(z, Math.hypot(x, y)) * deg]);
  }
  return unwrap(pts);
}

// The same chain renderLegsInto walks, in the same order, with the same
// meaning: chain[0] is the airport reached from the departure city by ground,
// an "arr" node is a flight from the node before it, a "dep" node is a
// connection at the airport already stood in, and the last node is where the
// journey lands before going on to the pin by ground.
function renderRoute() {
  const src = map.getSource("route");
  if (!src) return;
  const clear = () => src.setData({ type: "FeatureCollection", features: [] });
  if (!pinB || !active) return clear();
  const total = lookup(pinB.lat, pinB.lon);
  const chain = legsTo(pinB.lat, pinB.lon);
  if (total == null || total >= MAX_MINUTES || chain == null) return clear();

  const at = (code) => { const a = airports.find((x) => x[0] === code); return a && [a[4], a[3]]; };
  const same = (p, q) => p && q && Math.abs(p[0] - q[0]) < 1e-6 && Math.abs(p[1] - q[1]) < 1e-6;
  const from = [active.lon, active.lat], to = [pinB.lon, pinB.lat];
  const feats = [];
  const add = (coords, kind) => {
    if (coords && coords.length > 1)
      feats.push({ type: "Feature", properties: { kind },
                   geometry: { type: "LineString", coordinates: coords } });
  };

  if (!chain.length) {
    if (!same(from, to)) add(unwrap([from, to]), "ground");
  } else {
    const first = at(chain[0].code);
    if (first && !same(from, first)) add(unwrap([from, first]), "ground");
    for (let k = 1; k < chain.length; k++) {
      if (chain[k].kind !== "arr") continue;      // a connection stays put
      const a = at(chain[k - 1].code), b = at(chain[k].code);
      if (a && b) add(greatCircle(a, b), "air");
    }
    const last = at(chain[chain.length - 1].code);
    if (last && !same(last, to)) add(unwrap([last, to]), "ground");
  }
  src.setData({ type: "FeatureCollection", features: feats });
}

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
  // An empty chain HERE cannot mean "no flight" -- that case returned [] above,
  // on the NO_AIRPORT sentinel. It means the ordinal did not resolve, and
  // rendering it as [] made the page state positively "No flight on this
  // journey: surface travel", with a full surface breakdown, for a journey
  // that flew. null is the honest answer: the route is unavailable.
  if (!chain.length) return null;
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

// Wrapper so every early return still re-fits the column (U6).
function renderLegs() { renderLegsInto(); renderRoute(); fitReading(); }
function renderLegsInto() {
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
    return a ? `<span class="ap" tabindex="0" data-tip="${esc(a[1])}, ${esc(countryName(a[2]))}">${esc(code)}</span>` : esc(code);
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
  // The line drawn on the globe ships with no key anywhere a visitor can read
  // -- "solid is the flown leg, dashed is the ground" lived only in a code
  // comment beside renderRoute(). Say it under the itinerary the line belongs
  // to, and only when there is a line: with no air leg there is nothing solid
  // to distinguish and the sentence would be noise.
  const flown = rows.some(([, text]) => /\bby air\b|onward by/.test(String(text)))
    || chain.some((c) => c.kind === "arr");
  const key = document.createElement("p");
  key.className = "linekey";
  key.textContent = flown
    ? "On the globe, the solid arc is the flight and the dashed lines are the journeys to and from the airports."
    : "On the globe, the dashed line joins your departure to your destination over the ground.";
  frag.append(key);
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
//: Which of the equal-width legend segments a reading falls in, or -1 for a
//: cell with no scheduled route. bandRangeOf used to compute this and throw it
//: away, so the legend could not say where on it you were reading.
function bandIndexOf(min) {
  if (min == null || min >= MAX_MINUTES) return -1;
  let b = 0;
  while (b < EDGES.length && min > EDGES[b]) b++;
  return b;
}
// The legend is a scale with no "you are here". Marking the band under the
// pointer turns eleven anonymous colours into a reading you can place.
let bandMark = null;
// paintLegend() replaces the strip's children, which detaches this marker.
// It does NOT need to null it: `isConnected` below is false afterwards and the
// same node is re-appended. An earlier version had paintLegend reset the
// binding, and because paintLegend runs at module scope well above this `let`,
// that was a temporal-dead-zone ReferenceError thrown before the map was
// created -- the exact failure CLAUDE.md records as having blanked this site
// twice. Caught by opening the page, which is why that rule exists.
function markBand(min) {
  const strip = $("tints");
  if (!strip) return;
  const b = bandIndexOf(min);
  const n = strip.children.length - (bandMark && bandMark.isConnected ? 1 : 0);
  if (b < 0 || n <= 0) { if (bandMark) bandMark.hidden = true; return; }
  if (!bandMark) { bandMark = document.createElement("div"); bandMark.className = "mark"; }
  if (!bandMark.isConnected) strip.append(bandMark);
  bandMark.hidden = false;
  bandMark.style.left = `${(100 * (b + 0.5)) / n}%`;
}

function bandRangeOf(min) {
  if (min == null) return null;
  if (min >= MAX_MINUTES) return "no scheduled route";
  const b = bandIndexOf(min);
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
  // === null, not == null. Loose equality caught `undefined` -- land whose
  // times have not arrived or have FAILED -- as well as `null` (open water),
  // so clearTime() ran with no argument and replaced "Travel times
  // unavailable." with the idle prompt on the first pointer move onto land.
  // The failure notice survived exactly one mouse move. Three lines below,
  // the same function already distinguishes the two correctly for #where.
  if (t === null) clearTime();
  else if (t === undefined) clearTime(origin.failed ? "Travel times unavailable." : undefined);
  else $("time").innerHTML = `${esc(big)}<small>${esc(unit)}</small>`;
  const band = bandRangeOf(t);
  markBand(t);
  // A real reading, or the failure notice, ends the loading state; only the
  // "Loading the times from …" branch below leaves it standing.
  whereIsLoading = t === undefined && !origin.failed;
  $("where").innerHTML = t === undefined
    ? (origin.failed
        ? `Times unavailable for ${esc(active.name)}.`
        : `Loading the times from ${esc(active?.name ?? "the departure city")}…`)
    : t === null ? "Open water."
    : `${describe(lat, lng)}<br>${fmtCoord(lat, lng)}`
      + `${band ? " · " + band : ""}${active ? " · from " + esc(active.name) : ""}`
      // The ring is drawn at SOLVE_RES. When the reading tier has not landed
      // the NUMBER comes from a cell about seven times wider than that ring,
      // which is a real discrepancy between what is outlined and what is
      // printed -- so it is named rather than left for the visitor to assume
      // the two agree. Nothing is added once they do agree.
      + (READING_RES && readingGrid() !== READING_RES
          ? " · read from a wider cell than the outline" : "");
  return t;
}
// One live region for the whole page, written only when a reading is
// COMMITTED. The pointer must never reach it: showReading runs once per
// animation frame, and announcing sixty times a second is the same as
// announcing nothing.
const originName = () => active?.name ?? "the departure city";
function announce(text) {
  const el = $("status");
  if (el) el.textContent = text;
}
function announceReading(lat, lng, t, label) {
  if (t === undefined) return announce(`Times not yet loaded for ${active?.name ?? "the departure city"}.`);
  if (t === null) return announce("Open water: no destination there.");
  const p = !label && namePlaces ? nearestPlace(lat, lng) : null;
  const where = label || (p && placeLead(p)) || fmtCoord(lat, lng);
  if (t >= MAX_MINUTES) return announce(`${where}: no scheduled route from ${active?.name ?? ""}.`);
  announce(`${where}: ${fmtDur(t)} from ${active?.name ?? "the departure city"}, door to door.`);
}

// Once an origin's times land, the reading under the pointer (or the last
// tap) is redone, so it never keeps saying "loading".
function rereadPointer() {
  // A pinned destination owns the headline, so when the arrays land it is the
  // PIN that has to be re-read, not the last place the pointer happened to be.
  const from = pinB ? { lat: pinB.lat, lng: pinB.lon } : lastPointer;
  if (!from) return;
  const { lat, lng } = from;
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
    // Space is not a place. Off the globe, treat it exactly as the pointer
    // leaving the canvas does: hide the tip, drop the highlight, and leave the
    // last real reading standing rather than inventing one.
    if (!onGlobe(e.point)) { $("tip").hidden = true; clearHighlight(); return; }
    const { lat, lng } = e.lngLat;
    // A COMMITTED reading owns the headline. Once a destination is pinned the
    // big number is that destination's answer, not whatever the pointer is
    // passing over -- it used to be overwritten by the very next mouse move,
    // so the figure you clicked for survived about a tenth of a second.
    // Hovering still explores: the tooltip below follows the pointer and
    // carries the hovered time, the ring still moves, and clearing the route
    // hands the headline back.
    const t = pinB ? lookup(lat, lng) : showReading(lat, lng, e.point);
    const tip = $("tip");
    if (t == null) { tip.hidden = true; clearHighlight(); return; }
    highlight(lat, lng);
    // The setting is respected in describe() and announceReading() and was
    // ignored here -- so unticking a box labelled "Name the place under the
    // cursor" left the panel reading 37.57N 126.98E while the tip glued to
    // the cursor went on saying "Seoul, South Korea".
    const p = namePlaces ? nearestPlace(lat, lng) : null;
    const lead = p && placeLead(p);
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
function drawPin() {
  const src = map.getSource("pin");
  if (!src) return;
  src.setData({ type: "FeatureCollection", features: pinB
    ? [{ type: "Feature", geometry: { type: "Point", coordinates: [pinB.lon, pinB.lat] } }]
    : [] });
}

function renderPins() {
  drawPin();
  const box = $("pins");
  if (!active) { box.replaceChildren(); return; }
  const rows = [["From", active.name]];
  if (pinB) {
    const t = lookup(pinB.lat, pinB.lon);
    rows.push(["To", pinB.label]);
    rows.push(["Time", t === undefined ? (origin.failed ? "unavailable" : "loading…")
      : t === null ? "open water" : t >= MAX_MINUTES ? "no scheduled route" : `${fmtDur(t)}, door to door`]);
    // "3 h 43 min slower than from Seoul": the figure you were looking at
    // before you switched city, against the one you are looking at now.
    if (lastFrom && typeof t === "number" && t < MAX_MINUTES
        && lastFrom.lat === pinB.lat && lastFrom.lon === pinB.lon
        && lastFrom.slug !== active.slug) {
      const d = Math.round(t) - Math.round(lastFrom.min);
      rows.push(["Versus", d === 0
        ? `the same as from ${lastFromLabel()}`
        : `${fmtDur(Math.abs(d))} ${d > 0 ? "slower" : "faster"} than from ${lastFromLabel()}`]);
    }
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
      // Clearing the pin and switching city in one synchronous handler: no
      // mouse move can happen in between, so a stale lastPointer would be
      // re-read by settle() a few hundred ms later and printed as a current
      // reading for a place the pointer left long ago. Worst on touch, which
      // has no pointer to overwrite it afterwards.
      pinB = null; lastPointer = null;
      paintOrigin(near, { keepZoom: true });
    });
    box.append(b);
  }
}

// Both search routes to a destination end here, so neither can forget half the
// job. They used to call renderPins()+renderLegs() and nothing else, which
// left the 50 px headline reading the PREVIOUS destination's time
// while the itinerary below it described the new one: from Seoul, clicking
// Keene NH and then searching JFK showed "19 h 51 min" over an itinerary
// totalling 17 h 17 min. From a fresh load it showed an em dash over a full
// journey. Search is the only keyboard and screen-reader path to a
// destination, and the page advertises it. (The map click keeps its own body:
// it has a real pointer position to show the reading at, and it deliberately
// does NOT open the panel for open water, where a search for a named place
// should say why it found nothing.)
function commitDestination(lat, lon, label, { geocoded = false } = {}) {
  const t = showReading(lat, lon, onNearSide(lat, lon) ? map.project([lon, lat]) : null);
  if (lastFrom && (lastFrom.lat !== lat || lastFrom.lon !== lon)) lastFrom = null;
  // A point with no journey is not a destination: keep the reading, which now
  // says why, and drop the pin. `undefined` means the arrays are still in
  // flight, so the pin stays and settles when they land.
  pinB = (t === null || (t != null && t >= MAX_MINUTES))
    ? null
    : { lat, lon, label, geocoded };
  openRoutePanel();
  unfoldSheet();
  announceReading(lat, lon, t, label);   // after the reveal: see #status, below
  renderPins();
  renderLegs();
  revealReading();
  syncPermalink();
  return t;
}

function unfoldSheet() {
  const rail = document.querySelector(".rail");
  if (!rail.classList.contains("folded")) return;
  rail.classList.remove("folded");
  $("sheet-toggle")?.setAttribute("aria-expanded", "true");
}

// Opening the Route panel as a SIDE EFFECT of reading a cell must not scroll
// the answer away. On a phone the reading lives inside the rail, above both
// panels, so bringing #route into view scrolled #time and the whole legend
// out: measured at 390x844 on a clean load, one tap left rail.scrollTop at
// 297 with #time at y=149, above the sheet top of 405, and #tints and #scale
// gone. CLAUDE.md: the legend is always visible.
//
// Opening the panel BY TAPPING ITS SUMMARY still scrolls -- that is T27, and
// the city list really is what you want to see then. The difference is who
// asked, so the flag is set at the call site.
function openRoutePanel() {
  const d = $("route");
  // Suppressing the scroll-into-view is a SMALL-layout measure: there the
  // panel opening under the reading would shove the answer off a phone. On the
  // desktop the rail is a tall scrolling column and the guard did the opposite
  // of its job -- at 1280x800 choosing a destination left "Clear" and "Copy
  // link to this journey" at y 972-1000 with rail.scrollTop still 0, so the
  // two things you do next were below the fold with no cue they existed.
  if (!d.open && SMALL.matches) d.dataset.noScroll = "1";
  d.open = true;
}

// ...and the answer itself is scrolled back into view if anything else moved
// it. On the desktop layout the reading is position:fixed and this is a no-op.
function revealReading() {
  const reading = document.querySelector(".reading");
  const rail = reading?.closest(".rail");
  if (!rail) return;
  const box = reading.getBoundingClientRect(), view = rail.getBoundingClientRect();
  if (box.top >= view.top && box.bottom <= view.bottom) return;
  reading.scrollIntoView({ block: "nearest", behavior: REDUCED_MOTION.matches ? "auto" : "smooth" });
}

// U6: .depart-card is fixed at top:104 and grows down; .reading is fixed at
// bottom:14 and grows up; both are 306px wide in the same column at z-index 6
// and neither knew the other's height. At 1280x800 a nine-leg itinerary put
// them 43px into each other, covering the reach list's last row and the whole
// "Share of charted land ... door to door" note -- the line the modelling rule
// requires. The itinerary is the elastic part and already scrolls, so it is
// what gets bounded; the legend above it never moves.
const MIN_LEGS_PX = 96;
function fitReading() {
  const reading = document.querySelector(".reading");
  const legs = $("legs");
  if (!reading || !legs) return;
  legs.style.maxHeight = "";
  document.body.classList.remove("crowded");
  // The small layout puts the reading in the scrolling rail; nothing is fixed
  // and nothing can overlap.
  if (reading.closest(".rail") || legs.hidden) return;
  const card = document.querySelector(".depart-card");
  const rest = reading.offsetHeight - legs.offsetHeight;
  const floor = (n) => innerHeight - 14 - n - rest;
  // NOT offsetParent: it is null for a position:fixed element, so the card
  // measured as absent and the clamp never fired (1 px of overlap survived
  // the first attempt at this).
  const shown = card && !card.hidden && getComputedStyle(card).display !== "none";
  const cardBottom = shown ? card.getBoundingClientRect().bottom + 10 : 0;
  let room = floor(cardBottom);
  if (room < MIN_LEGS_PX && cardBottom) {
    // No arrangement fits both. The answer wins: the card's figures are a
    // summary of the city, the itinerary is what was just asked for.
    document.body.classList.add("crowded");
    const mast = document.querySelector(".mast");
    room = floor(mast ? mast.getBoundingClientRect().bottom + 10 : 0);
  }
  legs.style.maxHeight = Math.max(MIN_LEGS_PX, Math.min(room, 0.34 * innerHeight)) + "px";
}

// Setting a destination, from a click or from a key press. One body, because
// the two used to be one body and a promise: the globe is role="application"
// with a name that says "click to set a destination", which is not something a
// keyboard visitor can do. Arrows turned it and +/- zoomed it, and then the
// page's whole point was unreachable without a pointer. Enter now does at the
// centre of the view what a click does under the cursor.
function setDestination(lat, lng, point) {
  const t = showReading(lat, lng, point);
  // Open water and unreached land are not destinations: no pin, no panel,
  // and no request to Nominatim for a point with nothing to say.
  if (t === null || (t != null && t >= MAX_MINUTES)) return;
  const p = nearestPlace(lat, lng);
  if (lastFrom && (lastFrom.lat !== lat || lastFrom.lon !== lng)) lastFrom = null;
  pinB = { lat, lon: lng, label: placeLead(p) ?? fmtCoord(lat, lng), geocoded: false };
  openRoutePanel();
  unfoldSheet();
  announceReading(lat, lng, t);
  renderPins();
  renderLegs();
  revealReading();
  syncPermalink();
  // The setting is called "Name the place under the cursor" and the privacy
  // section promises that unticking it "stops the second kind entirely" --
  // the second kind being exactly this call. It was made unconditionally:
  // namePlaces gated only the LOCAL places.json lookups, so a visitor who had
  // turned naming off still sent every clicked coordinate to Nominatim. The
  // page was telling them otherwise, in writing, on the live site.
  if (namePlaces) reverseGeocode(lat, lng);
}

map.on("click", (e) => {
  // A click in space is not a destination; without this it pinned whatever
  // the limb clamped to.
  if (!onGlobe(e.point)) return;
  setDestination(e.lngLat.lat, e.lngLat.lng, e.point);
});
// The keyboard route to the same thing. The map container is what MapLibre
// gives keyboard focus, so the listener goes there; Enter and Space are the
// two keys a role="application" surface is expected to answer to, and Space
// would otherwise scroll the page behind the globe.
$("map").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
  // A modified key press belongs to the browser, not to the globe.
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  e.preventDefault();
  const c = map.getCenter();
  const point = map.project(c);
  // The centre of the view can be off the globe at a shallow pitch, exactly as
  // a click can be; refuse it the same way rather than reading a clamped
  // coordinate out of empty space (USER-6).
  if (!onGlobe(point)) return announce("The centre of the view is not on the globe.");
  setDestination(c.lat, c.lng, point);
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

function clearRoute() {
  // lastPointer has to go with the pin. While a destination is pinned the
  // hover branch takes lookup() and never calls showReading, which is the only
  // writer of lastPointer -- so it freezes at the pin and stops following the
  // mouse. rereadPointer() then resurrects that dismissed location as a live
  // headline reading the next time an origin's arrays land. See the "Depart
  // from" handler for the reproduction that needs no mouse move at all.
  pinB = null; lastFrom = null; lastPointer = null;
  renderPins(); renderLegs(); syncPermalink();
  // The headline was the pin's; with the pin gone it would otherwise sit there
  // as a number for a destination that is no longer shown. Hand it back to the
  // pointer, which fills it again on the next move.
  clearTime();
  $("where").textContent = IDLE_PROMPT;
  markBand(null);
}
$("clear-pins").addEventListener("click", clearRoute);
$("copy-link").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  const said = (msg) => {
    btn.textContent = msg;
    announce(msg);
    setTimeout(() => { btn.textContent = "Copy link to this journey"; }, 2400);
  };
  // clipboard.writeText needs a secure context and can be refused outright;
  // saying so is better than a button that appears to do nothing.
  try {
    await navigator.clipboard.writeText(location.href);
    said("Link copied");
  } catch {
    said("Copy failed — the link is in the address bar");
  }
});

// ---- city and airport list ----
// Accents are folded on both sides, so "Sao Paulo", "Zurich" and "Bogota"
// match the cities spelt São Paulo, Zürich and Bogotá.
const fold = (s) => String(s).normalize("NFD").replace(/\p{M}/gu, "").replace(/ı/g, "i").toLowerCase();
const cities = meta.origins.slice().sort((a, b) => a.name.localeCompare(b.name));
for (const c of cities) c.key = fold(c.name);
const bySlug = new Map(cities.map((c) => [c.slug, c]));
// Airports are searchable by code ("JFK") or name. Picking one drops it as the
// DESTINATION -- only the departure cities in index.json have a computed surface.
// airports.json ships the ISO-2 code; places.json resolves a country NAME, so
// one results list read "Seoul - Seoul, South Korea" beside "JFK ... - US".
// Intl.DisplayNames is in the platform, needs no data and no network.
const countryName = (() => {
  let dn = null;
  try { dn = new Intl.DisplayNames(["en"], { type: "region" }); } catch { /* older engine */ }
  const cache = new Map();
  return (code) => {
    if (!code) return "";
    if (!cache.has(code)) {
      let name = code;
      try { name = dn?.of(code) || code; } catch { /* not a region code */ }
      cache.set(code, name);
    }
    return cache.get(code);
  };
})();

fetch("./airports.json")
  .then((r) => (r.ok ? r.json() : null))
  .then((a) => {
    if (!a) return;
    airports = a.airports.map((row) => Object.assign(row, { key: fold(row[1]) }));
    // The drawn journey resolves every one of its points through this table,
    // and so does the itinerary's airport naming. Before it lands, every
    // lookup returns undefined and the globe draws ZERO route features against
    // a complete ICN -> EWR itinerary printed beside it -- which falsifies the
    // drawing code's own comment that "the line and the text cannot disagree".
    // Reachable on any cold load, and reliably through a ?to= permalink, which
    // restores the destination while this fetch is still in flight.
    //
    // renderLegs, not the drawing half alone: it redraws BOTH from one walk of
    // the chain, which is the invariant test_app_constants.py pins (one call
    // site, so the line and the text can never be two interpretations).
    if (pinB) renderLegs();
  })
  .catch(() => {});
function render(filter = "") {
  const f = fold(filter.trim());
  const hits = f ? cities.filter((c) => c.key.includes(f)) : cities;
  const list = document.createDocumentFragment();
  const row = (b) => { const li = document.createElement("li"); li.setAttribute("role", "none"); li.append(b); return li; };

  // Airports first when the query looks like a code, so "jfk" is one keystroke
  // from the answer; otherwise after the cities.
  // Ranked, not alphabetical by IATA code. "tok" used to return ACC Kotoka,
  // ENT Eniwetok, FYN Koktokay and GTA Gatokae before HND, because the list
  // ships in code order and was sliced at twelve: the answer was buried under
  // nine airports nobody meant. Exact code first, then a name that starts with
  // the query, then a word inside the name, then any substring -- and within
  // each, the larger airport, which airports.json has always carried in a
  // column the page ignored.
  const SIZE_RANK = { large: 0, medium: 1, small: 2 };
  const rankAirport = (a) => {
    if (a[0].toLowerCase() === f) return 0;
    if (a.key.startsWith(f)) return 1;
    return (" " + a.key).includes(" " + f) ? 2 : 3;
  };
  // Ranked ONCE into a temporary, then sorted on the stored rank. Calling
  // rankAirport from inside the comparator ran it O(n log n) times, and the
  // pathological query is the word "airport" itself: each of its six
  // two-letter substrings matches about 99% of the 4,008 names. Measured on
  // one desktop core, airport stage only, no DOM: "portland" cost 20.0 ms
  // across three keystrokes and "airport" 36.8 ms; ranking first is 4.5x
  // faster. A mid-range phone was landing at 65-125 ms per keystroke.
  const apHits = f.length >= 2
    ? airports.filter((a) => a[0].toLowerCase() === f || a.key.includes(f))
        .map((a) => ({ a, r: rankAirport(a), s: SIZE_RANK[a[5]] ?? 3, n: a[1].length }))
        .sort((x, y) => x.r - y.r || x.s - y.s
          // The plainer name wins a tie: "Tokyo Haneda International Airport"
          // over "Tokushima Awaodori Airport / JMSDF Tokushima Air Base".
          || x.n - y.n
          || x.a[1].localeCompare(y.a[1]))
        .slice(0, 12)
        .map((e) => e.a)
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
    coord.textContent = `${countryName(a[2])} · destination`;
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
    // Four origin names in the 553-origin set belong to two cities each
    // (Hyderabad, Suzhou, Fuzhou, Taizhou), and the list sorts by name, so
    // each pair arrives as two adjacent identical rows with nothing to choose
    // between them. index.json carries `country` when origins.toml has it;
    // otherwise the gazetteer already loaded answers it.
    if (ambiguousNames().has(c.name)) {
      const where = cityCountry(c);
      if (where) {
        const q = document.createElement("i");
        q.className = "disambig";
        q.textContent = ` ${where}`;
        name.append(q);
      }
    }
    // Was a latitude and a longitude to one decimal, which answers a question
    // nobody arrives with. The page could not say how long it takes to reach a
    // named city at all: typing "London" and pressing Enter DEPARTS from
    // London, because cities are departures only. The figure costs a lookup
    // per row from an array already in memory -- all 157 measured at 4.5 ms.
    const val = document.createElement("span");
    val.className = "rowtime";
    if (active?.slug === c.slug) {
      val.textContent = "departing";
    } else {
      const t = lookup(c.lat, c.lon);
      val.textContent = t == null || t === undefined ? ""
        : t >= MAX_MINUTES ? "no route"
        : fmtDur(t);
      if (typeof t === "number" && t < MAX_MINUTES) {
        val.title = `${fmtDur(t)} from ${active.name}, door to door`;
      }
      // A screen reader read the row as "London 15 h 15 min" -- the time TO
      // London -- on a row that DEPARTS from London when activated. The
      // accessible name has to carry both halves; the title cannot, because
      // touch has no hover.
      b.setAttribute("aria-label", val.textContent
        ? `${c.name}. ${val.textContent === "no route" ? "No route" : val.textContent}`
          + `${val.textContent === "no route" ? "" : " to get there"}`
          + ` from ${active?.name ?? "here"}, door to door. Choose to depart from ${c.name}.`
        : `${c.name}. Choose to depart from ${c.name}.`);
    }
    b.append(name, val);
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
  // Filtering 553 origins down to none changed the list and said nothing: the
  // live region is the only channel a screen-reader user has for "your query
  // matched nothing". Announced only when a filter is active, so the
  // once-per-origin rebuild in settle() stays silent.
  if (f) {
    const n = hits.length + apHits.length;
    announce(n
      ? `${n} match${n === 1 ? "" : "es"} for “${filter.trim()}”.`
      : `No match for “${filter.trim()}”. Press Enter or Search address to look it up.`);
  }
  const cap = $("listcap");
  if (cap) {
    cap.textContent = active
      ? `Each time is how long it takes to reach that city from ${active.name}, door to door. Choosing one departs from it instead.`
      : "Each time is how long it takes to reach that city, door to door. Choosing one departs from it instead.";
  }
  const box = $("results");
  // settle() rebuilds this list once per origin, about a second after a city
  // is clicked -- and replaceChildren throws keyboard focus to <body>, on the
  // only keyboard route to a departure city. Remember which row had it and
  // give it back to the row with the same slug.
  const hadFocus = box.contains(document.activeElement)
    ? document.activeElement.dataset?.slug : null;
  box.replaceChildren(list);
  // Roving tabindex: one stop in the tab order, the arrow keys walk the rest.
  // 157 rows used to be 157 tab stops between the search box and the next
  // panel. That stop is the CURRENT DEPARTURE, not row 1: with 553 origins,
  // tabbing in landed on "Aba" and focusing it reset scrollTop from 11,418 to
  // 0, undoing by keyboard the very scroll that puts the current departure in
  // view. A keyboard visitor arrived at the top of an alphabet with no sign
  // which city the page was measuring from.
  const first = box.querySelector(`button[aria-current="true"][data-slug]`)
    ?? box.querySelector("button");
  if (first) first.tabIndex = 0;
  if (hadFocus) {
    const again = box.querySelector(`button[data-slug="${cssEscape(hadFocus)}"]`);
    if (again) { again.tabIndex = 0; again.focus({ preventScroll: true }); }
  }
  // The list opens at the top -- so with 553 origins, Seoul is row 364 of 461,
  // about 9,540 px down a 12,072 px scroll box, and the visitor is looking at
  // "Aba" with no sign that a departure city is selected at all. Put the
  // current departure in view. Only when nothing is being typed: while
  // filtering, the top of the list IS the answer.
  if (!f && active) {
    const here = box.querySelector(`button[aria-current="true"][data-slug]`);
    if (here && !inView(box, here)) {
      box.scrollTop = here.offsetTop - box.clientHeight / 2 + here.offsetHeight / 2;
    }
  } else if (f) {
    // ...and a filtered list must start at ITS top. replaceChildren does not
    // reset scrollTop; the browser silently clamps the old value to the new,
    // much shorter, scroll height. Typing "lond" left scrollTop at 152 -- the
    // new maximum -- so London itself rendered at y 146-172 against a box at
    // y 298-618 and the visible list began at "STN London Stansted Airport",
    // under a live region announcing "9 matches". The answer was on screen in
    // the DOM and off screen to the visitor.
    box.scrollTop = 0;
  }
}
//: CSS.escape is not in every browser this page supports, and a slug can carry
//: a hyphen but never a quote, so a conservative fallback is enough.
function cssEscape(s) {
  return globalThis.CSS?.escape ? CSS.escape(s) : String(s).replace(/[^\w-]/g, "");
}
function inView(box, el) {
  const top = el.offsetTop - box.scrollTop;
  return top >= 0 && top + el.offsetHeight <= box.clientHeight;
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
  // PREPEND, not append. With 553 origins the results list is ~12,000 px tall,
  // so appending put "Type at least three characters" at viewport y 12,326 in
  // a box that ends at 471: the visitor pressed "Search address", nothing
  // visible happened, and the button read as broken. What the search has to
  // say belongs where the search box is.
  box.prepend(ul);
  box.scrollTop = 0;
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
  // Both staleness guards above can pass while render() -- which settle() runs
  // once per origin, up to a second after a city click -- has already called
  // replaceChildren on #results and detached this <ul>. Writing into a
  // detached node produces nothing, silently. Re-attach if that happened.
  if (!ul.isConnected) {
    const live = $("results");
    live.querySelector(".addresses")?.remove();
    live.prepend(ul);
    live.scrollTop = 0;
  }
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
  // The cache key was rounded to three decimals -- about 110 m, well inside
  // the zoom-14 result this asks for -- and then the full double was sent to
  // Nominatim anyway. So the coarsening bought a cache hit and published a
  // precision it did not need: the exact point a visitor clicked, to a
  // third-party server, when 110 m answers the same question. Send what the
  // cache is keyed on.
  const qlat = lat.toFixed(3), qlon = lon.toFixed(3);
  const key = `${qlat},${qlon}`;
  try {
    let j = reverseCache.get(key);
    if (!j) {
      j = await nominatim(`/reverse?format=jsonv2&zoom=14&lat=${qlat}&lon=${qlon}`, () => seq !== reverseSeq);
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
    moveTo({ center: [lon, lat], zoom: 8, speed: 0.9 });
    commitDestination(lat, lon, gb.dataset.label.split(",").slice(0, 3).join(","),
                      { geocoded: true });
    return;
  }
  const ab = e.target.closest("button[data-airport]");
  if (ab) {
    const a = airports.find((x) => x[0] === ab.dataset.airport);
    if (!a) return;
    moveTo({ center: [a[4], a[3]], zoom: 5, speed: 0.9 });
    commitDestination(a[3], a[4], `${a[0]} — ${a[1]}`);
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

// A single-pointer alternative to pinching, which is half of WCAG 2.2 SC
// 2.5.7 -- rotating the globe still needs a drag -- and the fastest way to
// zoom on a phone. Disabled at the ends so the control never lies about what
// it will do.
const zoomBy = (d) => map.easeTo({ zoom: map.getZoom() + d, duration: REDUCED_MOTION.matches ? 0 : 260 });
$("zoom-in").addEventListener("click", () => zoomBy(1));
$("zoom-out").addEventListener("click", () => zoomBy(-1));
const syncZoomButtons = () => {
  const z = map.getZoom();
  $("zoom-in").disabled = z >= map.getMaxZoom() - 0.01;
  $("zoom-out").disabled = z <= map.getMinZoom() + 0.01;
};
map.on("zoom", syncZoomButtons);
syncZoomButtons();

// Opening a panel on a short window put its content below the fold with no
// cue that anything had happened: at 390x844, tapping "Departure" left
// #results at y=844, the whole city list off screen. The rail is the
// scrolling box, so bring the panel that just opened into it.
for (const d of document.querySelectorAll(".rail details.panel")) {
  d.addEventListener("toggle", () => {
    const skip = d.dataset.noScroll;
    delete d.dataset.noScroll;
    if (!d.open || skip) return;
    const rail = d.closest(".rail");
    if (!rail) return;
    const box = d.getBoundingClientRect(), view = rail.getBoundingClientRect();
    if (box.bottom <= view.bottom && box.top >= view.top) return;
    d.scrollIntoView({ block: "nearest", behavior: REDUCED_MOTION.matches ? "auto" : "smooth" });
  });
}

// A <details> does not open for a fragment link, so the always-visible
// "Privacy" credit would scroll to a closed panel and appear to do nothing.
for (const a of document.querySelectorAll('a[href^="#"]')) {
  a.addEventListener("click", (e) => {
    const target = document.getElementById(a.getAttribute("href").slice(1));
    if (!target) return;
    e.preventDefault();
    for (let d = target.closest("details"); d; d = d.parentElement?.closest("details")) d.open = true;
    target.scrollIntoView({ block: "nearest", behavior: REDUCED_MOTION.matches ? "auto" : "smooth" });
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  });
}

// The route's own explanations, painted outside .legs so its scroll box
// cannot clip them. Hover and focus both, so a tap on a phone works too.
const legTip = $("legtip");
function hideLegTip() { legTip.hidden = true; }
function showLegTip(el) {
  const text = el.dataset.tip;
  if (!text) return hideLegTip();
  legTip.textContent = text;
  legTip.hidden = false;
  const r = el.getBoundingClientRect();
  const w = legTip.offsetWidth, h = legTip.offsetHeight;
  legTip.style.left = `${Math.min(Math.max(8, r.left), Math.max(8, innerWidth - w - 8))}px`;
  legTip.style.top = `${r.top - h - 6 < 8 ? r.bottom + 6 : r.top - h - 6}px`;
}
{
  const legs = $("legs");
  legs.addEventListener("mouseover", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (el) showLegTip(el); else hideLegTip();
  });
  legs.addEventListener("mouseleave", hideLegTip);
  legs.addEventListener("focusin", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (el) showLegTip(el);
  });
  legs.addEventListener("focusout", hideLegTip);
  legs.addEventListener("scroll", hideLegTip, { passive: true });
  addEventListener("resize", hideLegTip);
}

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
  // Nothing re-rendered, so the visible reading kept its old form until the
  // next pointer move -- and on a coarse pointer there is no next move, so the
  // control appeared to do nothing at all.
  if (lastPointer) rereadPointer();
  $("tip").hidden = true;
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
  // "Match the scheme" shows whatever the scheme's sea is, so its swatch
  // has to follow a scheme change.
  paintOceanPicker();
}
$("ramps").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-ramp]");
  if (b) pickRamp(b.dataset.ramp);
});

function paintOceanPicker() {
  const scheme = RAMPS[rampName]?.sea ?? SEA;   // what "Match the scheme" means

  document.documentElement.style.setProperty("--ocean-now", scheme);
  $("oceans").replaceChildren(...Object.entries(OCEANS).map(([key, o]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.ocean = key;
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(key === oceanName));
    b.setAttribute("aria-current", String(key === oceanName));
    b.tabIndex = key === oceanName ? 0 : -1;
    const sw = document.createElement("span");
    sw.className = o.sea ? "sw" : "sw follow";
    sw.style.background = o.sea || scheme;
    const nm = document.createElement("span");
    nm.textContent = o.name;
    b.append(sw, nm);
    return b;
  }));
}
paintOceanPicker();

function pickOcean(key) {
  if (!Object.hasOwn(OCEANS, key)) return;
  oceanName = key;
  try { localStorage.setItem("ocean", oceanName); } catch { /* private mode */ }
  paintSea();
  paintOceanPicker();
  paintLegend();          // the "open water" key swatch is the sea colour
}
$("oceans").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-ocean]");
  if (b) pickOcean(b.dataset.ocean);
});
// One roving-tabindex handler for both radio groups. The ocean picker had a
// click listener and nothing else, so five of its six colours could not be
// reached at all: only the checked radio is a tab stop (the radiogroup
// pattern), and with no arrow handling Tab left the group entirely. That is
// WCAG 2.1.1 at Level A, and it applied to a control whose whole purpose is
// choosing between six things.
//
// All four arrows, plus Home and End, because a radiogroup's orientation is
// not something a visitor can see: the ramp picker answered ArrowDown and
// ArrowUp only, so half the obvious keys did nothing there too.
function rovingRadios(host, keysOf, currentOf, pick, attr) {
  host.addEventListener("keydown", (e) => {
    const keys = keysOf();
    if (!keys.length) return;
    const i = keys.indexOf(currentOf());
    let next;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") next = keys[(i + 1) % keys.length];
    else if (e.key === "ArrowUp" || e.key === "ArrowLeft") next = keys[(i + keys.length - 1) % keys.length];
    else if (e.key === "Home") next = keys[0];
    else if (e.key === "End") next = keys[keys.length - 1];
    else return;
    e.preventDefault();
    pick(next);
    // After pick() the group is rebuilt, so the element to focus is looked up
    // again rather than held across the repaint.
    host.querySelector(`button[data-${attr}="${next}"]`)?.focus();
  });
}
rovingRadios($("ramps"), () => Object.keys(RAMPS), () => rampName, pickRamp, "ramp");
rovingRadios($("oceans"), () => Object.keys(OCEANS), () => oceanName, pickOcean, "ocean");

applyLockNorth();

// Small screens: the readout joins the bottom sheet and the panels start
// closed, so the globe gets the screen. Re-evaluated on rotation; the panels
// are closed only on the first entry into the small layout, not on every
// rotation of a phone (which used to fold the route being read).
let smallEntered = false;
function layoutForSize() {
  const reading = document.querySelector(".reading");
  const card = document.querySelector(".depart-card");
  const rail = document.querySelector(".rail");
  document.body.classList.toggle("smallui", SMALL.matches);
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
    // Under the reading, above the panels: the figures belong with the answer.
    if (card && card.parentElement !== rail) rail.insertBefore(card, reading.nextSibling);
    if (!smallEntered) { for (const d of rail.querySelectorAll("details")) d.open = false; smallEntered = true; }
  } else if (reading.parentElement === rail) {
    document.body.insertBefore(reading, document.getElementById("tip"));
    // BACK INTO .topleft, not into <body>. The card has no position of its
    // own -- it is a flex child of the fixed column that also holds the
    // masthead -- so appending it to <body> dropped it to the document origin
    // as a static block, 269 x 96 px of it directly under the masthead, with
    // the h1 winning elementFromPoint over the departure city's own button.
    // Reachable by any tablet rotated portrait to landscape, and by any
    // window dragged across 860 px; two of the four viewports CLAUDE.md's
    // deploy rule names sit on opposite sides of that breakpoint, so a
    // verification pass that RESIZES rather than reloads walks straight in.
    const topleft = document.querySelector(".topleft");
    if (card && topleft) topleft.append(card);
    rail.classList.remove("folded");
    $("departure").open = true;
  }
  fitReading();
}
layoutForSize();
SMALL.addEventListener("change", layoutForSize);
// There is no pointer on a phone.
$("where").textContent = IDLE_PROMPT;

// The departure named in the address (?from=slug) wins over the default; an
// unknown slug is ignored rather than a blank globe -- but SAY so, because
// silently swallowing it and then rewriting the address made a mistyped link
// indistinguishable from a working one.
const FALLBACK = bySlug.get("seoul") ?? cities[0];
let requested = null, requestedPin = null, badSlug = "";
try {
  const q = new URL(location.href).searchParams;
  const want = q.get("from") ?? "";
  requested = bySlug.get(want) ?? null;
  if (want && !requested) badSlug = want;
  // ?to=lat,lon -- validated to the same standard as the slug: two finite
  // numbers in range, or nothing at all. Anything else is dropped, never
  // trusted into lookup() or the DOM.
  const to = (q.get("to") ?? "").split(",");
  if (to.length === 2) {
    const la = Number(to[0]), lo = Number(to[1]);
    if (Number.isFinite(la) && Number.isFinite(lo) && Math.abs(la) <= 90 && Math.abs(lo) <= 180) {
      requestedPin = { lat: la, lon: lo };
    }
  }
} catch { /* no URL API */ }

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
// The signal boot.js's watchdog waits for. It must be a fact about THIS
// module having run to the end, not about anything the visitor can change:
// the watchdog used to count `.results button[data-slug]`, which is the
// SEARCH-FILTERED city list, so typing an airport code -- which this page
// invites, and which matches no city -- emptied it and the watchdog declared
// a perfectly healthy page broken twenty-five seconds later.
document.documentElement.dataset.appReady = "1";
// Through sayHere, like every other outcome written here: a ?from= slug that
// names no city is a failure a visitor needs told about, and painting it into
// a plain <p> said it only to whoever was looking at that corner.
sayHere(badSlug
  ? `No departure city called "${badSlug}"; showing ${(requested ?? FALLBACK).name}.`
  : `Showing ${(requested ?? FALLBACK).name}.`);
// The destination from the address, once the origin's arrays have landed --
// the reading needs them, and the map needs somewhere to fly to.
if (requestedPin) {
  const { lat, lon } = requestedPin;
  moveTo({ center: [lon, lat], zoom: 4.2, speed: 1.2 });
  const restore = () => {
    if (!origin.times) return false;
    const p = namePlaces ? nearestPlace(lat, lon) : null;
    commitDestination(lat, lon, (p && placeLead(p)) || fmtCoord(lat, lon));
    return true;
  };
  if (!restore()) {
    let tries = 0;
    const t = setInterval(() => { if (restore() || ++tries > 40) clearInterval(t); }, 250);
  }
}

// Location only on request. A permission prompt on load, before the page has
// said what it is for, is the one thing every browser now warns about, and
// it fired here on every first visit.
const locate = $("locate");
// Write the locate line and announce it in one call, so the two cannot drift:
// every outcome of this button is both visible and spoken, and the empty
// string clears the line without announcing silence.
function sayHere(text) {
  $("here").textContent = text;
  if (text) announce(text);
}
if (!navigator.geolocation) locate.hidden = true;
locate.addEventListener("click", () => {
  locate.disabled = true;
  sayHere("Locating…");
  // A dismissed permission prompt fires neither callback; do not stay disabled.
  // Clear the status line as well as the button: a dismissed prompt fires
  // neither callback, so re-enabling the button alone left "Locating…" on
  // screen for the rest of the session.
  const release = setTimeout(() => {
    locate.disabled = false;
    if ($("here").textContent === "Locating…") sayHere("");
  }, 10000);
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      clearTimeout(release);
      locate.disabled = false;
      const { latitude: la, longitude: lo } = pos.coords;
      const c = nearest(la, lo);
      // #here is a plain <p>: painting it is silent to a screen reader,
      // and #status never changed, so the locate button had no outcome at
      // all for anyone not looking at that corner (WCAG 2.2 SC 4.1.3).
      // The page keeps exactly ONE live region by policy (T4), so this
      // goes through it rather than making #here a second one.
      sayHere(`${c.name} is the nearest departure city to you.`);
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
    () => { clearTimeout(release); locate.disabled = false;
      sayHere(`Location unavailable — showing ${active?.name ?? FALLBACK.name}.`); },
    { timeout: 8000, maximumAge: 900000 }
  );
});

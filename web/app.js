import maplibregl from "./vendor/maplibre-gl.js";
import * as pmtiles from "./vendor/pmtiles.js";
import * as h3 from "./vendor/h3.js";

// Sequential single hue on a dark ground: brightest where the journey is
// shortest, fading outward. Lightness is strictly monotonic in OKLCH
// (0.90 -> 0.46), which is the property a sequential ramp actually needs --
// the categorical CVD checks do not apply to a ramp read as magnitude.
const BANDS = ["#ffd6a8","#f8c58d","#f2b372","#eba156","#e48f35","#dd7c00",
               "#cb7108","#b86616","#a55b1c","#93511f","#814720"];
const BG = "#0a0b0d", SEA = "#0f1114";
// Land no scheduled service reaches. A tone, not a colour: it must read as
// "no route" rather than as the far end of the time ramp.
const UNCHARTED = "#23262b";
const UNREACHABLE_BAND = -1;

const $ = (id) => document.getElementById(id);
const proto = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", proto.tile);

const meta = await (await fetch("./index.json")).json();
const UNREACHABLE = meta.unreachable ?? 65535;
const HOVER_RES = meta.hoverRes ?? 4;
const EDGES = meta.bandEdgesMin ?? [];

// shared, origin-independent cell ordering — fetched once
const hoverCells = new BigUint64Array(
  await (await fetch("./" + (meta.hoverCellsUrl || "hover_cells.bin"))).arrayBuffer()
);
let hoverTimes = null;          // Uint16Array for the active origin
let hoverAir = null;            // arrival-airport ordinal per hover cell
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
let lockNorth = store.get("lockNorth", false);
let namePlaces = store.get("namePlaces", true);

// ---- legend ----
$("tints").replaceChildren(...BANDS.map((c) => {
  const s = document.createElement("span"); s.style.background = c; return s;
}));

// Segments are equal width but the time scale is not linear, so a tick must sit
// at its own band boundary. Placing evenly spaced labels under uneven bands is
// how a legend ends up lying about the thing it explains.
const SHOWN_HOURS = [2, 6, 12, 24, 48, 72];
$("scale").replaceChildren(...EDGES.flatMap((mins, i) => {
  const hours = mins / 60;
  if (!SHOWN_HOURS.includes(hours)) return [];
  const el = document.createElement("span");
  el.style.left = `${((i + 1) / BANDS.length) * 100}%`;
  el.textContent = hours === 72 ? "72+" : String(hours);
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
// MapLibre is pinned to 5.24 (see web/README.md); this is its projection API.
map.setProjection({ type: "globe" });

map.addSource("sphere", { type: "geojson", data: { type: "Feature", geometry: { type: "Polygon",
  coordinates: [[[-180,-90],[180,-90],[180,90],[-180,90],[-180,-90]]] } } });
map.addLayer({ id: "sphere", type: "fill", source: "sphere",
  paint: { "fill-color": SEA, "fill-opacity": 1 } });

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

function paintOrigin(o) {
  active = o;
  if (map.getLayer("bands")) map.removeLayer("bands");
  if (map.getSource("bands")) map.removeSource("bands");

  map.addSource("bands", { type: "vector", url: `pmtiles://./origins/${o.slug}.pmtiles` });
  map.addLayer({
    id: "bands", type: "fill", source: "bands", "source-layer": "bands",
    paint: {
      "fill-color": ["match", ["get", "band"],
        UNREACHABLE_BAND, UNCHARTED,
        ...BANDS.flatMap((c, i) => [i, c]), UNCHARTED],
      "fill-opacity": 1
    }
  });

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
  hoverAir = null; routes = null;
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

  if (chain.length === 0) {
    rows.push([dur(total), "Overland the whole way — no flight"]);
  } else {
    rows.push([dur(chain[0].min), `To <b>${chain[0].code}</b>, and through the airport`]);
    for (let k = 1; k < chain.length; k++) {
      const a = chain[k - 1], b = chain[k];
      const t = dur(b.min - a.min);
      if (b.kind === "arr") rows.push([t, `Fly <b>${a.code} → ${b.code}</b>`]);
      else rows.push([t, `Connect at <b>${b.code}</b>`]);
    }
    const landed = chain[chain.length - 1];
    if (total > landed.min)
      rows.push([dur(total - landed.min), `From <b>${landed.code}</b> to the destination`]);
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
  const b = hit[0].properties.band;
  if (b === UNREACHABLE_BAND) return "no scheduled route";
  const lo = b === 0 ? 0 : EDGES[b - 1] / 60;
  const hi = b < EDGES.length ? EDGES[b] / 60 : null;
  return hi == null ? `over ${lo} h` : `${lo}–${hi} h band`;
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
}

map.on("click", (e) => {
  const { lat, lng } = e.lngLat;
  const p = nearestPlace(lat, lng);
  pinB = { lat, lon: lng, label: p ? (p.km > 60 ? `near ${p.name}` : p.name)
                                  : fmtCoord(lat, lng) };
  $("route").open = true;
  renderPins();
  renderLegs();
});

$("clear-pins").addEventListener("click", () => { pinB = null; renderPins(); renderLegs(); });

// ---- city list ----
const cities = meta.origins.slice().sort((a, b) => a.name.localeCompare(b.name));
const bySlug = new Map(cities.map((c) => [c.slug, c]));
function render(filter = "") {
  const f = filter.trim().toLowerCase();
  const hits = f ? cities.filter((c) => c.name.toLowerCase().includes(f)) : cities;
  const list = document.createDocumentFragment();
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
  $("results").replaceChildren(list);
}
$("results").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-slug]");
  if (b) paintOrigin(bySlug.get(b.dataset.slug));
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

applyLockNorth();

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
      const c = nearest(pos.coords.latitude, pos.coords.longitude);
      $("here").textContent = `${c.name} is the nearest charted city to you.`;
      if (c.slug !== active?.slug) paintOrigin(c);
    },
    () => { $("here").textContent = "Location unavailable — showing Seoul."; },
    { timeout: 8000, maximumAge: 900000 }
  );
}

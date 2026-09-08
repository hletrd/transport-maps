import maplibregl from "./vendor/maplibre-gl.js";
import * as pmtiles from "./vendor/pmtiles.js";
import * as h3 from "./vendor/h3.js";

// Sequential single-hue ink on paper: dense near the origin, fading to a pale
// tint far away. Validated monotonic in OKLCH lightness (0.342 -> 0.885), the
// focal band at 10.1:1 on the #efe7d9 ground and the palest still separable at
// 1.16:1. One hue deliberately: magnitude, not category.
const BANDS = ["#6c0e00","#7a2600","#883a1b","#964d32","#a35f48","#b1725d",
               "#be8472","#cb9787","#d8aa9c","#e4bdb2","#f1d1c8"];
const PAPER = "#efe7d9", SEA = "#e7ddcb", UNCHARTED = "#ded2bc";

const $ = (id) => document.getElementById(id);
const proto = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", proto.tile);

const meta = await (await fetch("./index.json")).json();
const UNREACHABLE = meta.unreachable ?? 65535;
const HOVER_RES = meta.hoverRes ?? 4;

// shared, origin-independent cell ordering — fetched once
const hoverCells = new BigUint64Array(
  await (await fetch("./" + (meta.hoverCellsUrl || "hover_cells.bin"))).arrayBuffer()
);
let hoverTimes = null;          // Uint16Array for the active origin
let active = null;

// ---- legend swatches ----
$("tints").replaceChildren(...BANDS.map((c) => {
  const s = document.createElement("span"); s.style.background = c; return s;
}));

// Attribution is read from the artifact, never hardcoded here: a copy in the
// frontend can drift from the data it claims to describe, and this is a licence
// obligation. emit/index.py writes [{name, licence, url, usedFor}].
$("credits").textContent = (meta.attribution ?? [])
  .map((s) => `${s.name} (${s.licence})`)
  .join(" · ") || "Attribution missing from index.json.";

// ---- globe ----
const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8, sources: {}, layers: [
      { id: "space", type: "background", paint: { "background-color": PAPER } }
    ],
    sky: { "sky-color": PAPER, "horizon-color": "#dccfb6", "fog-color": PAPER }
  },
  center: [30, 22], zoom: 1.35, minZoom: 0.6, maxZoom: 6,
  attributionControl: false, dragRotate: true
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

await new Promise((r) => map.on("load", r));
// MapLibre is pinned to 5.24 (see web/README.md); this is its projection API.
map.setProjection({ type: "globe" });

// faint sphere so unreachable land and ocean still read as a planet
map.addSource("sphere", { type: "geojson", data: { type: "Feature", geometry: { type: "Polygon",
  coordinates: [[[-180,-85],[180,-85],[180,85],[-180,85],[-180,-85]]] } } });
map.addLayer({ id: "sphere", type: "fill", source: "sphere",
  paint: { "fill-color": SEA, "fill-opacity": 1 } });

function paintOrigin(o) {
  active = o;
  if (map.getLayer("bands")) map.removeLayer("bands");
  if (map.getSource("bands")) map.removeSource("bands");

  map.addSource("bands", { type: "vector", url: `pmtiles://./origins/${o.slug}.pmtiles` });
  map.addLayer({
    id: "bands", type: "fill", source: "bands", "source-layer": "bands",
    paint: {
      "fill-color": ["match", ["get", "band"],
        ...BANDS.flatMap((c, i) => [i, c]), UNCHARTED],
      "fill-opacity": 0.94
    }
  });                                 // appended last => draws above "sphere"

  hoverTimes = null;
  fetch(`./origins/${o.slug}.bin`)
    .then((r) => {
      if (!r.ok) throw new Error(`${r.status} fetching ${o.slug}.bin`);
      return r.arrayBuffer();
    })
    .then((b) => { hoverTimes = new Uint16Array(b); })
    .catch((err) => {
      // Without this the readout silently reports open water everywhere.
      console.error("hover data unavailable:", err);
      $("where").textContent = `Hover data unavailable for ${o.name}.`;
    });

  map.flyTo({ center: [o.lon, o.lat], zoom: 1.9, speed: 0.75, curve: 1.5 });
  for (const b of document.querySelectorAll(".results button"))
    b.setAttribute("aria-current", String(b.dataset.slug === o.slug));
  $("origin-name").textContent = o.name;
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

// binary search the sorted shared cell array
function lookup(lat, lon) {
  if (!hoverTimes) return null;
  const id = BigInt("0x" + h3.latLngToCell(lat, lon, HOVER_RES));
  let lo = 0, hi = hoverCells.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1, v = hoverCells[mid];
    if (v === id) return hoverTimes[mid];
    if (v < id) lo = mid + 1; else hi = mid - 1;
  }
  return null;                        // ocean, or outside the land mask
}

map.on("mousemove", (e) => {
  const t = lookup(e.lngLat.lat, e.lngLat.lng);
  const [big, unit] = fmtTime(t);
  $("time").innerHTML = t == null ? "—" : `${big}<small>${unit}</small>`;
  $("where").textContent = t == null
    ? "Open water."
    : `${fmtCoord(e.lngLat.lat, e.lngLat.lng)}${active ? " — from " + active.name : ""}`;
});

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

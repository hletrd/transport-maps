import maplibregl from "./vendor/maplibre-gl.js";
import * as pmtiles from "./vendor/pmtiles.js";
import * as h3 from "./vendor/h3.js";

const BANDS = ["#cde2fb","#b7d3f6","#9ec5f4","#86b6ef","#6da7ec","#5598e7",
               "#3987e5","#2a78d6","#256abf","#1c5cab","#184f95"];

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
$("scale").innerHTML = BANDS.map((c) => `<span style="background:${c}"></span>`).join("");

// ---- attribution, from the artifact itself ----
(function credits() {
  const a = meta.attribution;
  const parts = !a ? [] :
    Array.isArray(a) ? a.map((x) => (typeof x === "string" ? x : `${x.source ?? x.name} (${x.licence ?? x.license ?? ""})`))
                     : Object.entries(a).map(([k, v]) => `${k} (${v})`);
  $("credits").innerHTML = parts.length
    ? "Data " + parts.join(" · ")
    : "Data: OurAirports · Wikipedia CC-BY-SA · OpenStreetMap ODbL · GRIP4 CC-0 · Natural Earth";
})();

// ---- globe ----
const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8, sources: {}, layers: [
      { id: "space", type: "background", paint: { "background-color": "#0a0c10" } }
    ],
    sky: { "sky-color": "#0a0c10", "horizon-color": "#141a26", "fog-color": "#0a0c10" }
  },
  center: [30, 22], zoom: 1.35, minZoom: 0.6, maxZoom: 6,
  attributionControl: false, dragRotate: true
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

function goGlobe() {
  try { map.setProjection({ type: "globe" }); }        // maplibre 6
  catch { try { map.setProjection("globe"); } catch {} } // older signature
}

await new Promise((r) => map.on("load", r));
goGlobe();

// faint sphere so unreachable land and ocean still read as a planet
map.addSource("sphere", { type: "geojson", data: { type: "Feature", geometry: { type: "Polygon",
  coordinates: [[[-180,-85],[180,-85],[180,85],[-180,85],[-180,-85]]] } } });
map.addLayer({ id: "sphere", type: "fill", source: "sphere",
  paint: { "fill-color": "#101623", "fill-opacity": 0.9 } });

function paintOrigin(o) {
  active = o;
  if (map.getLayer("bands")) map.removeLayer("bands");
  if (map.getSource("bands")) map.removeSource("bands");

  map.addSource("bands", { type: "vector", url: `pmtiles://./origins/${o.slug}.pmtiles` });
  map.addLayer({
    id: "bands", type: "fill", source: "bands", "source-layer": "bands",
    paint: {
      "fill-color": ["match", ["get", "band"],
        ...BANDS.flatMap((c, i) => [i, c]), "#141a26"],
      "fill-opacity": 0.94
    }
  }, "sphere");                       // under the veil, over the sphere? see below
  // keep bands above the sphere
  map.moveLayer("bands");

  hoverTimes = null;
  fetch(`./origins/${o.slug}.bin`)
    .then((r) => r.arrayBuffer())
    .then((b) => { hoverTimes = new Uint16Array(b); })
    .catch(() => { hoverTimes = null; });

  map.flyTo({ center: [o.lon, o.lat], zoom: 1.9, speed: 0.75, curve: 1.5 });
  for (const b of document.querySelectorAll(".results button"))
    b.setAttribute("aria-current", String(b.dataset.slug === o.slug));
  $("hint").textContent = `${o.name} · ${fmtCoord(o.lat, o.lon)}`;
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

const cross = $("cross");
map.on("mousemove", (e) => {
  cross.style.left = e.point.x + "px";
  cross.style.top = e.point.y + "px";
  cross.classList.add("on");
  const t = lookup(e.lngLat.lat, e.lngLat.lng);
  const [big, unit] = fmtTime(t);
  $("time").innerHTML = t == null ? "—" : `${big}<small>${unit}</small>`;
  $("where").textContent = t == null
    ? "Open water."
    : `${fmtCoord(e.lngLat.lat, e.lngLat.lng)}${active ? " — from " + active.name : ""}`;
});
map.on("mouseout", () => cross.classList.remove("on"));

// ---- city list ----
const cities = meta.origins.slice().sort((a, b) => a.name.localeCompare(b.name));
function render(filter = "") {
  const f = filter.trim().toLowerCase();
  const hits = f ? cities.filter((c) => c.name.toLowerCase().includes(f)) : cities;
  $("results").innerHTML = hits.slice(0, 400).map((c) => `
    <li><button data-slug="${c.slug}" aria-current="${active?.slug === c.slug}">
      <span>${c.name}</span><span class="coord">${c.lat.toFixed(1)}, ${c.lon.toFixed(1)}</span>
    </button></li>`).join("");
  for (const b of document.querySelectorAll(".results button"))
    b.onclick = () => paintOrigin(cities.find((c) => c.slug === b.dataset.slug));
}
$("q").addEventListener("input", (e) => render(e.target.value));
render();

paintOrigin(cities.find((c) => c.slug === "seoul") || cities[0]);
map.once("idle", () => $("boot").classList.add("gone"));
setTimeout(() => $("boot").classList.add("gone"), 6000);

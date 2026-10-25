// Only immutable public data can use the CDN. Page code and APIs stay direct.
const PROBE = "/delivery-probe-v1.bin";
const PROBE_BYTES = 16384;
const STORAGE_KEY = "worldmap.delivery.v1";
const CHOICE_TTL = 5 * 60 * 1000;

export function preferCDN(direct, cdn) {
  return Number.isFinite(cdn) && (!Number.isFinite(direct)
    || (cdn < direct * 0.8 && direct - cdn >= 20));
}

export function createDataDelivery({origin, root, cdn, storage = null, saveData = false,
  fetcher = (...args) => globalThis.fetch(...args), timing = globalThis.performance,
  now = () => performance.now(), wallTime = () => Date.now(),
  probeTimeout = 3000, headerTimeout = 1800, stallTimeout = 3000, bodyTimeout = 30000}) {
  const directOrigin = new URL(origin).origin;
  const base = new URL(root, directOrigin);
  const cdnOrigin = cdn ? new URL(cdn).origin : null;
  const enabled = !saveData && cdnOrigin && cdnOrigin !== directOrigin
    && cdnOrigin.startsWith("https://") && base.origin === directOrigin
    && /^\/data\/[A-Za-z0-9_-]+\/$/.test(base.pathname);
  let choice = "direct", failed = false, disposed = false, started = null, fallbacks = 0;
  const measurements = {direct: null, cdn: null};
  const probes = new Set();
  if (enabled) {
    try {
      const saved = JSON.parse(storage?.getItem(STORAGE_KEY) || "null");
      const age = wallTime() - saved?.at;
      if (saved?.cdn === cdnOrigin && age >= 0 && age < CHOICE_TTL
          && (saved.choice === "direct" || saved.choice === "cdn")) choice = saved.choice;
    } catch { /* Storage can be unavailable; direct delivery still works. */ }
  }

  function remember() {
    try { storage?.setItem(STORAGE_KEY, JSON.stringify({choice, cdn: cdnOrigin, at: wallTime()})); }
    catch { /* A routing hint must never prevent a request. */ }
  }

  function eligible(input, options) {
    // Request objects and custom/authenticated requests retain native fetch
    // semantics. Only the page's plain public-data GETs can change hosts.
    if (typeof input !== "string" && !(input instanceof URL)) return null;
    const headers = new Headers(options?.headers);
    if ([...headers.keys()].some(name => !["accept", "range", "if-match"].includes(name))) return null;
    const url = new URL(typeof input === "string" ? input : input.url || input.href, directOrigin);
    const method = options?.method || input?.method || "GET";
    return enabled && url.origin === directOrigin && !url.search
      && url.pathname.startsWith(base.pathname)
      && /^\/data\/[A-Za-z0-9_-]+\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_.-]+$/.test(url.pathname)
      && (method === "GET" || method === "HEAD") ? url : null;
  }

  async function measure(host) {
    const url = new URL(PROBE, host).href;
    let duration = null;
    for (let round = 0; round < 2; round++) {
      const ctrl = new AbortController();
      probes.add(ctrl);
      const begin = now();
      let timer;
      try {
        await Promise.race([
          (async () => {
            const response = await fetcher(url, {signal: ctrl.signal, cache: "no-store",
              credentials: "omit", referrerPolicy: "no-referrer", priority: "low"});
            if (!response.ok || response.headers.get("X-Worldmap-Probe") !== "1") throw new Error("Invalid probe");
            if ((await response.arrayBuffer()).byteLength !== PROBE_BYTES) throw new Error("Truncated probe");
          })(),
          new Promise((_, reject) => { timer = setTimeout(() => {
            const error = new DOMException("Probe timed out", "TimeoutError");
            ctrl.abort(error); reject(error);
          }, probeTimeout); }),
        ]);
        // Network timing excludes main-thread work that can delay promise callbacks.
        const entries = timing?.getEntriesByName?.(url) || [];
        const entry = entries.filter(e => e.startTime >= begin - 1 && e.responseEnd > e.startTime).at(-1);
        duration = entry ? entry.responseEnd - entry.startTime : now() - begin;
      } finally {
        clearTimeout(timer);
        probes.delete(ctrl);
      }
    }
    return duration;
  }

  function start() {
    if (started) return started;
    if (!enabled || disposed) return Promise.resolve();
    // Warm once, then compare network time. Neither probe blocks the map.
    started = Promise.all(["direct", "cdn"].map(async route => {
      try { measurements[route] = await measure(route === "direct" ? directOrigin : cdnOrigin); }
      catch { measurements[route] = null; }
      if (failed || disposed) return;
      const d = measurements.direct, c = measurements.cdn;
      if (Number.isFinite(d) || Number.isFinite(c)) {
        choice = preferCDN(d, c) ? "cdn" : "direct";
        remember();
      }
    }));
    return started;
  }

  async function fromCDN(url, options) {
    const ctrl = new AbortController(), signal = options.signal;
    const abort = () => ctrl.abort(signal.reason);
    signal?.throwIfAborted();
    signal?.addEventListener("abort", abort, {once: true});
    let timer, reader;
    const wait = (promise, ms) => Promise.race([promise, new Promise((_, reject) => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const error = new DOMException("Data delivery stalled", "TimeoutError");
        ctrl.abort(error); reject(error);
      }, Math.max(0, ms));
    })]);
    try {
      const response = await wait(fetcher(new URL(url.pathname, cdnOrigin).href,
        {...options, signal: ctrl.signal, credentials: "omit", referrerPolicy: "no-referrer"}), headerTimeout);
      if (!response.ok) throw new Error(`CDN HTTP ${response.status}`);
      const range = new Headers(options.headers).get("Range");
      let expected = null;
      if (range) {
        const asked = /^bytes=(\d+)-(\d+)$/.exec(range);
        const got = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get("Content-Range") || "");
        if (!asked || !got || response.status !== 206 || +got[1] !== +asked[1]
            || +got[2] !== Math.min(+asked[2], +got[3] - 1) || +got[2] < +got[1]) {
          throw new Error("CDN returned an invalid byte range");
        }
        expected = +got[2] - +got[1] + 1;
      }
      if ((options.method || "GET") === "HEAD") return response;
      reader = response.body.getReader();
      const chunks = [];
      let length = 0;
      const end = now() + bodyTimeout;
      while (true) {
        const {done, value} = await wait(reader.read(), Math.min(stallTimeout, end - now()));
        if (done) break;
        length += value.byteLength;
        if (length > 64 * 1024 * 1024 || (expected !== null && length > expected)) throw new Error("Oversized CDN response");
        chunks.push(value);
      }
      if (expected !== null && length !== expected) throw new Error("Truncated CDN range");
      const bytes = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      if (url.pathname.endsWith(".json")) JSON.parse(new TextDecoder().decode(bytes));
      const headers = new Headers(response.headers);
      headers.delete("Content-Encoding");
      headers.set("Content-Length", String(length));
      return new Response(bytes, {status: response.status, statusText: response.statusText, headers});
    } catch (error) {
      ctrl.abort(error);
      throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reader?.releaseLock();
    }
  }

  async function fetchData(input, options = {}) {
    const url = eligible(input, options);
    if (!url || choice !== "cdn" || failed) return fetcher(input, options);
    try { return await fromCDN(url, options); }
    catch (error) {
      // A city switch is cancellation, not evidence that the CDN failed.
      if (options.signal?.aborted) throw options.signal.reason || error;
      choice = "direct"; failed = true; fallbacks++; remember();
      return fetcher(url.href, options);
    }
  }

  return {start, fetch: fetchData,
    getState: () => ({choice, measurements: {...measurements}, fallbacks, enabled: Boolean(enabled)}),
    dispose() { disposed = true; for (const ctrl of probes) ctrl.abort(); },
  };
}

// PMTiles Source interface. Keep one canonical cache key across both routes.
export function createRoutedSource(url, fetcher, EtagMismatch,
  userAgent = globalThis.navigator?.userAgent || "") {
  let reload = false;
  const windowsChrome = /Windows/.test(userAgent) && /Chrome|Chromium|Edg|OPR|Brave/.test(userAgent);
  return {
    getKey: () => url,
    async getBytes(offset, length, signal, etag) {
      const request = (last, cache) => fetcher(url, {signal, cache,
        headers: {Range: `bytes=${offset}-${last}`}});
      let response = await request(offset + length - 1, reload ? "reload" : windowsChrome ? "no-store" : undefined);
      if (offset === 0 && response.status === 416) {
        const match = /^bytes \*\/(\d+)$/.exec(response.headers.get("Content-Range") || "");
        if (!match || +match[1] < 1) throw new Error("Invalid PMTiles archive size");
        response = await request(+match[1] - 1, "reload");
      }
      const value = response.headers.get("ETag");
      const actual = value && !value.startsWith("W/") ? value : undefined;
      if (response.status === 416 || (etag && actual && etag !== actual)) {
        reload = true;
        throw new EtagMismatch("The PMTiles archive changed between byte ranges");
      }
      if (!response.ok) throw new Error(`PMTiles HTTP ${response.status}`);
      if (response.status === 200 && (offset !== 0 || !response.headers.has("Content-Length")
          || +response.headers.get("Content-Length") > length)) throw new Error("PMTiles byte ranges unavailable");
      const data = await response.arrayBuffer();
      if (data.byteLength > length) throw new Error("Oversized PMTiles range");
      return {data, etag: actual, cacheControl: response.headers.get("Cache-Control") || undefined,
        expires: response.headers.get("Expires") || undefined};
    },
  };
}

function afterFirstPaint(task) {
  if (performance.getEntriesByName("first-contentful-paint").length) task();
  else if (typeof PerformanceObserver !== "undefined" && PerformanceObserver.supportedEntryTypes?.includes("paint")) {
    const observer = new PerformanceObserver(list => {
      if (list.getEntries().some(entry => entry.name === "first-contentful-paint")) {
        observer.disconnect();
        task();
      }
    });
    observer.observe({type: "paint", buffered: true});
    addEventListener("pagehide", () => observer.disconnect(), {once: true});
  } else requestAnimationFrame(() => requestAnimationFrame(task));
}

function browserDelivery() {
  if (typeof document === "undefined" || location.origin !== "https://worldmap.atik.kr") return null;
  const root = document.querySelector('meta[name="worldmap-data-root"]')?.content;
  const cdn = document.querySelector('meta[name="worldmap-data-cdn"]')?.content;
  if (!root || cdn !== "https://worldmap-data.atik.kr") return null;
  let storage = null;
  try { storage = sessionStorage; } catch { /* Private browsing may deny it. */ }
  const route = createDataDelivery({origin: location.origin, root, cdn, storage,
    saveData: Boolean(navigator.connection?.saveData)});
  window.__dataDelivery = route;
  addEventListener("pagehide", () => route.dispose(), {once: true});
  return route;
}

export const dataDelivery = browserDelivery();
if (typeof document !== "undefined") afterFirstPaint(() => {
  for (const link of document.querySelectorAll("link[data-after-paint]")) {
    const apply = () => { link.media = "all"; };
    if (link.sheet) apply();
    else link.addEventListener("load", apply, {once: true});
  }
  dataDelivery?.start();
});
export const dataFetch = (input, options) => dataDelivery
  ? dataDelivery.fetch(input, options) : globalThis.fetch(input, options);

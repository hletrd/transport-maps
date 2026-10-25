// Keep map tiles and the basic time array ahead of optional route downloads.
// Completion follows rendered tiles, not the arrival of a PMTiles header.
export function createMapLoading(map, box, {retry, now = () => performance.now(), maxWait = 12000} = {}) {
  const title = box.querySelector("b"), detail = box.querySelector(".sub");
  const elapsed = box.querySelector(".elapsed"), bar = box.querySelector(".bar");
  const button = box.querySelector("button"), waiters = new Set();
  let busy = true, times = false, failed = false, began = now(), timer;
  const put = (element, text) => { if (element.textContent !== text) element.textContent = text; };
  const release = () => { for (const done of [...waiters]) done(); };
  function tick() {
    if (!busy || failed) return;
    const seconds = Math.floor((now() - began) / 1000);
    put(elapsed, seconds ? `${seconds} s` : "");
    put(detail, seconds >= 5 ? "Still loading. You can choose another city."
      : "Downloading the map and travel times.");
  }
  function check() {
    if (!busy || failed || !times || !map.getSource("bands") || !map.isStyleLoaded()
        || map.isMoving() || !map.areTilesLoaded()) return;
    busy = false;
    box.hidden = true;
    map.getContainer().setAttribute("aria-busy", "false");
    clearInterval(timer);
    release();
  }
  function begin(name) {
    busy = true; times = false; failed = false; began = now();
    put(title, `Loading map from ${name}…`);
    box.hidden = false; button.hidden = true; bar.hidden = false;
    map.getContainer().setAttribute("aria-busy", "true");
    clearInterval(timer);
    tick();
    timer = setInterval(tick, 1000);
  }
  function fail(message) {
    failed = true;
    box.hidden = false; bar.hidden = true; button.hidden = false;
    put(title, "Map could not finish loading");
    put(detail, message); put(elapsed, "");
    map.getContainer().setAttribute("aria-busy", "false");
    clearInterval(timer);
    release();
  }
  function wait(signal) {
    if (signal?.aborted) return Promise.reject(signal.reason);
    if (!busy || failed) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const done = (error) => {
        clearTimeout(limit); waiters.delete(done);
        signal?.removeEventListener("abort", abort);
        error ? reject(error) : resolve();
      };
      const abort = () => done(signal.reason || new DOMException("Cancelled", "AbortError"));
      // A broken tile must not permanently withhold otherwise usable routes.
      const limit = setTimeout(done, maxWait);
      waiters.add(done);
      signal?.addEventListener("abort", abort, {once: true});
    });
  }
  const again = () => retry?.();
  button.addEventListener("click", again);
  map.on("render", check);
  return {begin, fail, wait, timesReady() { times = true; map.triggerRepaint(); },
    dispose() {
      clearInterval(timer); release(); map.off("render", check);
      button.removeEventListener("click", again);
    },
  };
}

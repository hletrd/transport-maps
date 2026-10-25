// Fine readings and route overrides are committed together, one region at a time.
export function createDetailReader({base, slug, parents, slots, channels,
  blocks = 32, indexSuffix = '.over.index.bin', readingSuffix = '.r6.bin',
  overrideSuffix = '.over.bin', signal, onLoad = () => {}, onError = () => {},
  fetcher = globalThis.fetch}) {
  if (![parents, slots, channels, blocks].every(Number.isInteger)
      || parents < 1 || slots < 1 || channels < 1 || blocks < 1 || blocks > 64) {
    throw new Error('Invalid regional reading layout');
  }
  const size = blocks * slots, total = parents * slots;
  const cache = new Map(), pending = new Map();
  let indexWanted = null, retryAt = 0, queued = -1;

  async function range(url, first, length, bytes) {
    const last = first + length - 1;
    const response = await fetcher(url, {signal, headers: {Range: `bytes=${first}-${last}`}});
    const match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get('Content-Range') || '');
    if (response.status !== 206 || !match || Number(match[1]) !== first
        || Number(match[2]) !== last || Number(match[3]) !== bytes) {
      await response.body?.cancel();
      throw new Error(`${url}: the server did not return the requested byte range`);
    }
    const data = await response.arrayBuffer();
    if (data.byteLength !== length) throw new Error(`${url}: truncated byte range`);
    return data;
  }

  function directory() {
    if (!indexWanted) indexWanted = (async () => {
      const url = `${base}${slug}${indexSuffix}`;
      const response = await fetcher(url, {signal});
      if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
      const data = await response.arrayBuffer();
      if (data.byteLength !== (parents + 2) * 4) throw new Error(`${url}: invalid region directory length`);
      const values = new Uint32Array(data), count = values[0], offsets = values.subarray(1);
      if (count > total || offsets[0] !== 0 || offsets[parents] !== count
          || offsets.some((n, i) => n > count || (i > 0 && n < offsets[i - 1]))) {
        throw new Error(`${url}: invalid region directory offsets`);
      }
      return {count, offsets};
    })().catch(error => { indexWanted = null; throw error; });
    return indexWanted;
  }

  async function load(group) {
    const firstBlock = group * blocks, lastBlock = Math.min(parents, firstBlock + blocks);
    const firstSlot = firstBlock * slots, slotCount = (lastBlock - firstBlock) * slots;
    const timesWanted = range(`${base}${slug}${readingSuffix}`, firstSlot * 2, slotCount * 2, total * 2);
    const routesWanted = (async () => {
      const {count, offsets} = await directory();
      const first = offsets[firstBlock], n = offsets[lastBlock] - first;
      if (!n) return {slots: new Uint32Array(), airport: new Uint16Array(), modes: new Uint16Array()};
      const url = `${base}${slug}${overrideSuffix}`, bytes = count * (6 + 2 * channels);
      const [indices, airports, modes] = await Promise.all([
        range(url, first * 4, n * 4, bytes),
        range(url, count * 4 + first * 2, n * 2, bytes),
        range(url, count * 6 + first * channels * 2, n * channels * 2, bytes),
      ]);
      const selected = new Uint32Array(indices);
      if (selected.some((n, i) => n < firstSlot || n >= firstSlot + slotCount
          || (i > 0 && n <= selected[i - 1]))) throw new Error(`${url}: invalid regional route slots`);
      return {slots: selected, airport: new Uint16Array(airports), modes: new Uint16Array(modes)};
    })();
    const [times, routes] = await Promise.all([timesWanted, routesWanted]);
    return {times: new Uint16Array(times), routes};
  }

  function request(index) {
    if (!Number.isInteger(index) || index < 0 || index >= total || signal?.aborted) return Promise.resolve(false);
    const group = Math.floor(index / size);
    if (cache.has(group)) return Promise.resolve(true);
    if (pending.has(group)) return pending.get(group);
    if (Date.now() < retryAt) return Promise.resolve(false);
    if (pending.size >= 2) { queued = index; return Promise.resolve(false); }
    const work = load(group).then(chunk => {
      if (signal?.aborted) return false;
      cache.set(group, chunk);
      while (cache.size > 64) cache.delete(cache.keys().next().value);
      onLoad();
      return true;
    }).catch(error => {
      if (!signal?.aborted) { retryAt = Date.now() + 15000; onError(error); }
      return false;
    }).finally(() => {
      pending.delete(group);
      if (queued >= 0) { const next = queued; queued = -1; request(next); }
    });
    pending.set(group, work);
    return work;
  }

  return {
    request,
    get(index) { return cache.get(Math.floor(index / size))?.times[index % size]; },
    route(index) {
      const routes = cache.get(Math.floor(index / size))?.routes;
      if (!routes) return null;
      let lo = 0, hi = routes.slots.length - 1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1, value = routes.slots[mid];
        if (value === index) return {airport: routes.airport[mid], modes: routes.modes.subarray(mid * channels, (mid + 1) * channels)};
        if (value < index) lo = mid + 1; else hi = mid - 1;
      }
      return null;
    },
  };
}

#!/usr/bin/env bash
# Deploy the rebuilt dist and verify it end to end. Refuses to deploy a build
# whose artifacts disagree with each other -- a mismatched hover array and cell
# ordering renders a blank globe with no console error, which has shipped once.
set -euo pipefail
cd /Users/hletrd/flash-shared/transport-maps

echo "=== 1. artifact consistency ==="
python3 - <<'PY'
import json, pathlib, sys
d = pathlib.Path("dist")
n_cells = (d/"hover_cells.bin").stat().st_size // 8
idx = json.load(open(d/"index.json"))
bad = []
warn = []
for o in idx["origins"]:
    s = o["slug"]
    for suffix, width in ((".bin", 2), (".air.bin", 2), (".modes.bin", 12), (".rail.bin", 2)):
        p = d/"origins"/f"{s}{suffix}"
        if not p.exists():
            # The rail detail is optional on the page (it appears when present);
            # every other array is required and must agree in length.
            (warn if suffix == ".rail.bin" else bad).append(f"{s}{suffix} missing"); continue
        if p.stat().st_size // width != n_cells:
            bad.append(f"{s}{suffix} has {p.stat().st_size//width} entries, expected {n_cells}")
    if not (d/"origins"/f"{s}.pmtiles").exists():
        bad.append(f"{s}.pmtiles missing")
print(f"  hover cells {n_cells:,} | origins {len(idx['origins'])} | bands {len(idx['bandEdgesMin'])+1} | solveRes {idx.get('solveRes')}")
for extra in ("places.json", "airports.json", "borders.json", "water.pmtiles"):
    if not (d/extra).exists(): bad.append(f"{extra} missing")
print(f"  attribution {[a['name'] for a in idx['attribution']]}")
if warn:
    print(f"  note: {len(warn)} optional file(s) absent, e.g. {warn[0]} (rail detail ships with the next full build)")
if bad:
    print("  MISMATCHES:", *bad[:10], sep="\n    "); sys.exit(1)
print("  every origin has pmtiles + bin + air.bin + modes.bin, all lengths agree; gazetteer, airports, borders, water tiles present")
PY

echo "=== 1b. page copy agrees with index.json ==="
# The page must not state a city count the data contradicts: the copy said
# 553 cities while index.json listed 157. Any three-digit "N cities" or
# "N departures" in the page has to equal the number of origins.
N=$(python3 -c 'import json; print(len(json.load(open("dist/index.json"))["origins"]))')
stated=$(grep -oE '[0-9]{3} (cities|departure)' web/index.html | grep -oE '^[0-9]{3}' | sort -u || true)
for s in $stated; do
  if [ "$s" != "$N" ]; then
    echo "  web/index.html says '$s cities/departures' but index.json lists $N origins; fix the copy before deploying"
    exit 1
  fi
done
echo "  index.html city count (${stated:-none stated}) agrees with index.json ($N origins)"

echo "=== 2. copy web assets and deploy ==="
rsync -a --exclude 'README.md' web/ dist/
rsync -a --delete --info=progress2 dist/ atik.kr:/var/www/worldmap/ 2>&1 | tail -c 200; echo

echo "=== 3. live checks ==="
for f in index.json app.js index.html places.json airports.json borders.json origins/seoul.air.bin origins/seoul.modes.bin; do
  printf "  %-26s %s\n" "$f" "$(curl -s -o /dev/null -w '%{http_code}' "https://worldmap.atik.kr/$f")"
done
printf "  %-26s %s\n" "seoul.pmtiles range" "$(curl -s -o /dev/null -w '%{http_code}' -r 0-99 https://worldmap.atik.kr/origins/seoul.pmtiles)"
printf "  %-26s %s\n" "water.pmtiles range" "$(curl -s -o /dev/null -w '%{http_code}' -r 0-99 https://worldmap.atik.kr/water.pmtiles)"

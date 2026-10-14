#!/usr/bin/env bash
# Filter each continent's full extract to motorway and trunk ways, for the
# ground model's OSM motorway class (sources/motorways.py).
#
# Reads the full extracts scripts/osm_fixed_links.sh keeps ({region}.osm.pbf)
# and downloads nothing: a region whose full extract is absent is skipped and
# said so. Writes {region}-roads.osm.pbf beside them -- a name sources/osm.py
# (which globs *-rail.osm.pbf) and sources/fixed_links.py ({region}.osm.pbf)
# do not read. osmium keeps the matched ways' referenced nodes and every tag,
# so sources/motorways.py decides which trunks count from motorway=,
# expressway=, motorroad= and maxspeed= itself; links (ramps) are left out.
# The header's replication timestamp survives the filter, as for rail.
#
# Regions run in parallel: each pass is one sequential read of one extract.
# Measured on h200 (2026-10-15): 573 s wall for all seven, 8.3 GB summed
# RSS, 424 MB out (sources/motorways.py has the parse cost).
#
#   ./scripts/osm_roads.sh
#   OSM_REPLACE=1 ./scripts/osm_roads.sh asia
set -uo pipefail
D="${OSM_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data/cache/osm}"
REPLACE="${OSM_REPLACE:-0}"
REGIONS=("$@")
[ ${#REGIONS[@]} -eq 0 ] && REGIONS=(europe asia north-america south-america africa australia-oceania central-america)
IONICE=(); command -v ionice >/dev/null 2>&1 && IONICE=(ionice -c 3)
one() {
  local r=$1 raw="$D/$1.osm.pbf" out="$D/$1-roads.osm.pbf" tmp="$D/$1-roads.new.osm.pbf"
  if [ -f "$out" ] && [ "$REPLACE" != 1 ]; then echo "[skip] $r already filtered"; return; fi
  [ -f "$raw" ] || { echo "[FAIL] $r: no $raw (scripts/osm_fixed_links.sh keeps it)"; return; }
  local t0=$SECONDS
  if nice -n 19 ${IONICE[@]+"${IONICE[@]}"} osmium tags-filter --overwrite "$raw" \
       w/highway=motorway,trunk -o "$tmp"; then
    mv "$tmp" "$out"; echo "[done] $r -> $(du -h "$out" | cut -f1) in $((SECONDS - t0)) s"
  else
    rm -f "$tmp"; echo "[FAIL] filter $r"
  fi
}
for r in "${REGIONS[@]}"; do one "$r" & done
wait
echo "[ALL DONE]"

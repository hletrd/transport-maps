#!/usr/bin/env bash
# Download continent PBFs, filter each to rail/ferry, delete the raw file.
#
# Run this where the bandwidth is. About 100 GB comes down and roughly 300 MB
# survives the filter, so doing it on a laptop link is hours of waiting for a
# result you could have scp'd in seconds.
#
# Sequential on purpose: Geofabrik is a free mirror, not a CDN to hammer.
# Rate-limited and niced because this host also serves the live site: an
# unthrottled 33 GB pull plus a CPU-bound filter made the site time out.
# Resumable at two levels: an existing *-rail.osm.pbf is skipped entirely, and
# curl -C - continues a partial download instead of starting over. Without the
# resume flag a dropped connection 14 GB into a 15 GB extract silently threw
# the whole thing away and began again.
# Each raw extract this script downloads is deleted as soon as it is filtered
# so peak disk stays near one continent. A raw extract that was already there
# -- the one scripts/osm_fixed_links.sh keeps for the bridge parse -- is
# filtered in place and left alone.
#
#   OSM_DIR=~/osm ./scripts/osm_rail.sh
#   OSM_REPLACE=1 OSM_DIR=~/osm ./scripts/osm_rail.sh asia   # re-filter Geofabrik's current file
# then copy the filtered extracts to data/cache/osm/ on the build machine.
#
# OSM_REPLACE=1 is how `build-all` refreshes a rail extract that has fallen
# behind Geofabrik (sources/geofabrik.py, G2): the existing *-rail.osm.pbf is
# rebuilt rather than skipped, and replaced only once the filter succeeds.
set -uo pipefail
D="${OSM_DIR:-$HOME/osm}"; mkdir -p "$D"
REPLACE="${OSM_REPLACE:-0}"
REGIONS=("$@")
[ ${#REGIONS[@]} -eq 0 ] && REGIONS=(europe asia north-america south-america africa australia-oceania central-america)
# ionice is Linux-only; nice alone elsewhere.
IONICE=(); command -v ionice >/dev/null 2>&1 && IONICE=(ionice -c 3)
for r in "${REGIONS[@]}"; do
  raw="$D/$r.osm.pbf"; out="$D/$r-rail.osm.pbf"; downloaded=0
  if [ -f "$out" ] && [ "$REPLACE" != 1 ]; then echo "[skip] $r already filtered"; continue; fi
  if [ ! -f "$raw" ]; then
    # A DATED file, named by the region's replication state, and the resume
    # pinned to it -- the reasoning is in scripts/osm_fixed_links.sh. Resolving
    # `-latest` instead pinned nothing for europe, whose redirect target is
    # itself a `-latest` path.
    pin="$raw.source"
    if [ -f "$raw.part" ] && [ -f "$pin" ]; then
      url=$(cat "$pin"); echo "[resume] $r from $url"
    else
      day=$(curl -fsS --max-time 60 "https://download.geofabrik.de/$r-updates/state.txt" \
            | sed -nE 's/^timestamp=20([0-9]{2})-([0-9]{2})-([0-9]{2}).*/\1\2\3/p')
      [ -n "$day" ] || { echo "[FAIL] $r: no timestamp in $r-updates/state.txt"; continue; }
      url="https://download.geofabrik.de/$r-$day.osm.pbf"
      rm -f "$raw.part"; echo "$url" > "$pin"; echo "[get ] $r from $url"
    fi
    curl -fL -C - --no-progress-meter --limit-rate 8M --retry 5 --retry-delay 5 \
      -o "$raw.part" "$url" || { echo "[FAIL] download $r"; continue; }
    want=$(curl -fsSI --max-time 60 "$url" | awk 'tolower($1)=="content-length:"{v=$2} END{print v+0}')
    got=$(wc -c < "$raw.part" | tr -d ' ')
    [ "$want" -gt 0 ] && [ "$got" -eq "$want" ] \
      || { echo "[FAIL] $r: $got B on disk, $want B at $url; left as .part"; continue; }
    mv "$raw.part" "$raw"; downloaded=1
  fi
  echo "[filt] $r ($(du -h "$raw" | cut -f1))"
  # `r/route=train`, not `r/type=route,route=train`: in an osmium expression
  # the comma lists VALUES of one key, so that read "type is `route` or
  # `route=train`" and kept every route relation on Earth -- bus, hiking,
  # bicycle, road -- with all their member ways and nodes (CR-16 / K11).
  # sources/osm.py reads only `type=route` + `route=train` relations, and
  # every service tier, heritage (`service=tourism`) included, is a tag on
  # those, so nothing it parses is lost. Members of a kept relation are still
  # kept, which is how its stop nodes survive.
  # Written beside the old extract and renamed over it, so a failed filter
  # leaves the previous one in use. The name must end in .osm.pbf for osmium
  # to pick the format, and must not end in -rail.osm.pbf, which
  # sources/osm.py globs for.
  tmp="$D/$r-rail.new.osm.pbf"
  if nice -n 19 ${IONICE[@]+"${IONICE[@]}"} osmium tags-filter --overwrite "$raw" \
       r/route=train w/railway=rail n/railway=station,halt \
       w/route=ferry n/amenity=ferry_terminal -o "$tmp"; then
    mv "$tmp" "$out"
    [ "$downloaded" = 1 ] && rm -f "$raw"
    echo "[done] $r -> $(du -h "$out" | cut -f1)"
  else
    rm -f "$tmp"; echo "[FAIL] filter $r"
  fi
done
echo "[ALL DONE]"; ls -la "$D"

#!/usr/bin/env bash
# Download continent PBFs, filter each to rail/ferry, delete the raw file.
#
# Run this where the bandwidth is. About 100 GB comes down and roughly 300 MB
# survives the filter, so doing it on a laptop link is hours of waiting for a
# result you could have scp'd in seconds.
#
# Sequential on purpose: Geofabrik is a free mirror, not a CDN to hammer.
# Resumable -- an existing *-rail.osm.pbf is skipped, and each raw extract is
# deleted as soon as it is filtered so peak disk stays near one continent.
#
#   OSM_DIR=~/osm ./scripts/osm_rail.sh
# then copy the filtered extracts to data/cache/osm/ on the build machine.
set -uo pipefail
D="${OSM_DIR:-$HOME/osm}"; mkdir -p "$D"
for r in europe asia north-america south-america africa australia-oceania central-america; do
  raw="$D/$r.osm.pbf"; out="$D/$r-rail.osm.pbf"
  if [ -f "$out" ]; then echo "[skip] $r already filtered"; continue; fi
  if [ ! -f "$raw" ]; then
    echo "[get ] $r"
    curl -fL --retry 3 --retry-delay 5 -o "$raw.part" \
      "https://download.geofabrik.de/$r-latest.osm.pbf" || { echo "[FAIL] download $r"; continue; }
    mv "$raw.part" "$raw"
  fi
  echo "[filt] $r ($(du -h "$raw" | cut -f1))"
  if osmium tags-filter --overwrite "$raw" \
       r/type=route,route=train w/railway=rail n/railway=station,halt \
       w/route=ferry n/amenity=ferry_terminal -o "$out"; then
    rm -f "$raw"; echo "[done] $r -> $(du -h "$out" | cut -f1)"
  else
    echo "[FAIL] filter $r"
  fi
done
echo "[ALL DONE]"; ls -la "$D"

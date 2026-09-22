#!/usr/bin/env bash
# Download full Geofabrik extracts and keep only FIXED LINKS -- bridges and
# tunnels -- so the graph can tell a strait you can drive across from one you
# cannot.
#
# Separate from scripts/osm_rail.sh on purpose. That script filters to rail and
# ferries and then DELETES the raw extract, which is why this data is not
# already on disk; it also skips a region whose output exists, so running it
# again would not produce highways. This writes `*-links.osm.pbf` and never
# touches `*-rail.osm.pbf`.
#
#   scripts/osm_fixed_links.sh australia-oceania      # one region
#   scripts/osm_fixed_links.sh                        # all seven
set -uo pipefail
D="${OSM_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data/cache/osm}"
mkdir -p "$D"
REGIONS=("$@")
[ ${#REGIONS[@]} -eq 0 ] && REGIONS=(europe asia north-america south-america africa australia-oceania central-america)
for r in "${REGIONS[@]}"; do
  raw="$D/$r.osm.pbf"
  if [ -f "$raw" ]; then echo "[skip] $r raw already present"; continue; fi
  if [ ! -f "$raw" ]; then
    # `-latest` is rebuilt daily. Resolving it afresh on every restart and then
    # resuming the old .part appended one day's bytes to another's: the europe
    # extract came out with a 2026-09-18 header, 9.9 MB longer than the
    # 2026-09-18 file, and failed to decompress hours later. So a resume is
    # pinned to the dated URL the download STARTED from, recorded beside it.
    pin="$raw.source"
    if [ -f "$raw.part" ]; then
      [ -f "$pin" ] || { echo "[FAIL] $r: $raw.part exists with no recorded source URL," \
                              "so it cannot be resumed safely; move it aside first"; continue; }
      url=$(cat "$pin"); echo "[resume] $r from $url"
    else
      # Pin a DATED file, never `-latest`: for europe `-latest` redirects to a
      # mirror path that is itself `europe-latest.osm.pbf`, so pinning the
      # redirect target pinned nothing -- and a splice ends with the last
      # day's bytes, so it even has the length the size check expects. The
      # region's replication state names the day of its current extract.
      day=$(curl -fsS --max-time 60 "https://download.geofabrik.de/$r-updates/state.txt" \
            | sed -nE 's/^timestamp=20([0-9]{2})-([0-9]{2})-([0-9]{2}).*/\1\2\3/p')
      [ -n "$day" ] || { echo "[FAIL] $r: no timestamp in $r-updates/state.txt"; continue; }
      url="https://download.geofabrik.de/$r-$day.osm.pbf"
      curl -fsSI --max-time 60 "$url" >/dev/null || { echo "[FAIL] $r: $url is not there"; continue; }
      echo "$url" > "$pin"; echo "[get ] $r from $url"
    fi
    curl -fL -C - --no-progress-meter --limit-rate 8M --retry 5 --retry-delay 5 \
      -o "$raw.part" "$url" || { echo "[FAIL] download $r"; continue; }
    # Finalise only a file whose length is exactly that of the file it claims
    # to be; a splice would otherwise surface only as a decode error mid-parse.
    want=$(curl -fsSI --max-time 60 "$url" | awk 'tolower($1)=="content-length:"{v=$2} END{print v+0}')
    got=$(stat -f%z "$raw.part")
    [ "$want" -gt 0 ] && [ "$got" -eq "$want" ] \
      || { echo "[FAIL] $r: $got B on disk, $want B at $url; left as .part"; continue; }
    mv "$raw.part" "$raw"
  fi
  echo "[filt] $r ($(/usr/bin/du -h "$raw" | awk '{print $1}'))"
  echo "[keep] $r raw retained ($(/usr/bin/du -h "$raw" | awk '{print $1}')) for the Python pass"
  # The `osmium` COMMAND-LINE tool is not installed here -- only the Python
  # binding the pipeline already depends on. Filtering therefore happens in
  # sources/fixed_links.py, which reads this raw extract and writes a parquet
  # of spans; the raw can be deleted once that cache exists.
done
echo "[ALL DONE]"

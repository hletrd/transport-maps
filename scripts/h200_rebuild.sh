#!/usr/bin/env bash
# Run a full rebuild on h200: the full map and the three avoid-a-mode
# variants side by side, each in its own checkout, then publish-ready checks.
#
#   bash scripts/h200_rebuild.sh start [SERVICE_DATE]   # on h200, from $W/repo
#   bash scripts/h200_rebuild.sh status                 # done/total, rate, problems
#   bash scripts/h200_rebuild.sh finish                 # variants in, reindex, check
#
# Then, from the operator's machine: scripts/deploy_solver.sh (the bundle is
# in $W/repo/data/build/solver) and scripts/deploy_from_h200.sh.
#
# What rebuilds 27-28 learned, written down here rather than re-learned:
#   - One build per checkout (dist/.build.lock), so each variant has its own
#     hard-linked copy of the repo ($W/repo-air, -ferry, -rail) and its own venv.
#   - h200's container shares 8,192 pids with vLLM and friends (~7,400 used);
#     tippecanoe and every library pool are capped to stay inside it, and the
#     start refuses when the headroom is not there (WORKERS_* below).
#   - No numactl. --preferred=0 put every worker's memory on node 0; measured,
#     an origin with remote memory took 17.0 min against 14.2 min local.
#   - Inputs are checked against their upstreams ONCE (`transport-maps inputs`,
#     G2), then every build runs --offline: a network hiccup must not stop a
#     10-hour run, and all four must read the same snapshot. Each variant
#     checkout gets the full tree's data/cache mirrored in with hard links --
#     a cp -al copy made earlier would otherwise keep the old inputs.
#   - --skip-existing, so a restart resumes instead of starting over: an
#     origin is skipped only when its record matches THIS run's inputs and
#     graph (progress.py). NOT TRANSPORT_MAPS_RESUME_TRUST_RECORDS: rebuild 28
#     needed it while the graph hash was not deterministic (fixed since), and
#     it accepts any intact record whatever it was built from -- a new rebuild
#     started with it would skip every origin and republish the last build.
set -euo pipefail
: "${W:=/default/worldmap}"
# Split so the four finish together, from rebuild 28's rates per worker: full
# map 1.5 origins an hour, no-air 10.7, no-ferry and no-rail 3.1 each.
: "${WORKERS_FULL:=48}" "${WORKERS_AIR:=8}" "${WORKERS_FERRY:=24}" "${WORKERS_RAIL:=24}"
# Rebuild 28: 124 workers held ~350 pids above the other services' ~7,400 --
# a worker's two threads plus tippecanoe's while it runs -- so ~3 each.
: "${PIDS_PER_WORKER:=3}"
TREES=(repo repo-air repo-ferry repo-rail)
EXCLUDES=("" air ferry rail)
WORKERS=("$WORKERS_FULL" "$WORKERS_AIR" "$WORKERS_FERRY" "$WORKERS_RAIL")
LOGS=(rebuild.log variant-air.log variant-ferry.log variant-rail.log)

env_for_build() {
  export UV_PYTHON_INSTALL_DIR=$W/uv-python UV_CACHE_DIR=$W/uv-cache PATH=$W/tools/bin:$PATH
  export NUMPY_MADVISE_HUGEPAGE=0 TRANSPORT_MAPS_OSM_MAX_AGE_DAYS=30
  unset TRANSPORT_MAPS_RESUME_TRUST_RECORDS
  export TIPPECANOE_MAX_THREADS=2 POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
         MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 RAYON_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
}

checkouts() {  # every variant tree at the full tree's commit, with its own venv
  local head t
  head=$(git -C "$W/repo" -c safe.directory='*' rev-parse HEAD)
  for t in "${TREES[@]:1}"; do
    if [ ! -d "$W/$t/.git" ]; then
      mkdir -p "$W/$t"
      (cd "$W/repo" && for e in $(ls -A | grep -vx -e dist -e .venv); do cp -al "$e" "$W/$t/$e"; done)
    fi
    git -C "$W/$t" -c safe.directory='*' fetch -q "$W/repo" HEAD
    git -C "$W/$t" -c safe.directory='*' checkout -q --detach "$head"
    (cd "$W/$t" && uv sync -q)
    # The inputs the full tree just checked, the same files by hard link.
    rsync -a --delete --link-dest="$W/repo/data/cache/" "$W/repo/data/cache/" "$W/$t/data/cache/"
    rm -f "$W/$t/dist/.build.lock"
  done
  rm -f "$W/repo/dist/.build.lock"
  echo "checkouts at ${head:0:7}"
}

pids_headroom() {  # refuse a start the container cannot hold
  local want=0 n cur max
  for n in "${WORKERS[@]}"; do want=$((want + n * PIDS_PER_WORKER)); done
  cur=$(cat /sys/fs/cgroup/pids.current 2>/dev/null || echo 0)
  max=$(cat /sys/fs/cgroup/pids.max 2>/dev/null || echo max)
  [ "$max" = max ] && return 0
  if [ $((cur + want + 200)) -gt "$max" ]; then
    echo "!! $cur of $max pids in use; ${#WORKERS[@]} builds would add ~$want."
    echo "   Lower WORKERS_* or wait for the other services to release some."
    exit 1
  fi
  echo "pids: $cur of $max in use, builds add ~$want"
}

start() {
  local date=${1:-$(date +%F)} i
  env_for_build
  export TRANSPORT_MAPS_SERVICE_DATE=$date
  pids_headroom
  echo "checking inputs against their upstreams $(date '+%m-%d %H:%M')"
  (cd "$W/repo" && uv run transport-maps inputs) | tee -a "$W/inputs.log"
  checkouts
  for i in "${!TREES[@]}"; do
    local tree=${TREES[$i]} ex=${EXCLUDES[$i]} n=${WORKERS[$i]} log=$W/${LOGS[$i]}
    (
      cd "$W/$tree"
      echo "restart ($n workers, service date $date) ${ex:+--exclude $ex} $(date '+%m-%d %H:%M')" >> "$log"
      TRANSPORT_MAPS_WORKERS=$n nice -n 10 uv run transport-maps build-all --offline --skip-existing \
        ${ex:+--exclude "$ex"} >> "$log" 2>&1
      echo "exit $? at $(date '+%m-%d %H:%M')" >> "$log"
    ) &
    sleep 20
  done
  echo "started; logs in $W/{${LOGS[*]// /,}}"
}

records_of() {  # records_of <index>: the .progress directory of that build
  local i=$1
  if [ -z "${EXCLUDES[$i]}" ]; then echo "$W/repo/dist/.progress"
  else echo "$W/${TREES[$i]}/dist/v/no-${EXCLUDES[$i]}/.progress"; fi
}

status() {
  local i p log r total
  total=$(python3 -c "import tomllib;print(len(tomllib.load(open('$W/repo/data/origins.toml','rb'))['origin']))" 2>/dev/null || echo "?")
  for i in "${!TREES[@]}"; do
    p=$(records_of "$i"); log=$W/${LOGS[$i]}
    r=$(grep -nE '^restart' "$log" 2>/dev/null | tail -1 | cut -d: -f1)
    printf '%-9s %5s/%s  last 30 min %4s  errors %s  %s\n' "${EXCLUDES[$i]:-full}" \
      "$(grep -l '"complete"' "$p"/*.json 2>/dev/null | wc -l)" "$total" \
      "$(find "$p" -name '*.json' -mmin -30 -exec grep -l '"complete"' {} + 2>/dev/null | wc -l)" \
      "$(awk -v r="${r:-0}" 'NR>r && /tippecanoe failed|Traceback|refusing|GateFailure/' "$log" 2>/dev/null | wc -l)" \
      "$(awk -v r="${r:-0}" 'NR>r && /^exit/' "$log" 2>/dev/null | tail -1)"
  done
  echo "pids $(cat /sys/fs/cgroup/pids.current 2>/dev/null)/$(cat /sys/fs/cgroup/pids.max 2>/dev/null)"
}

finish() {
  local i log last
  for i in "${!TREES[@]}"; do
    log=$W/${LOGS[$i]}
    last=$(awk "/^restart/{r=NR} END{print r}" "$log")
    awk -v r="$last" 'NR>r && /^exit/' "$log" | tail -1 | grep -q '^exit 0 ' \
      || { echo "!! ${TREES[$i]} has not finished with exit 0 (see $log)"; exit 1; }
  done
  mkdir -p "$W/repo/dist/v"
  for i in 1 2 3; do
    rm -rf "$W/repo/dist/v/no-${EXCLUDES[$i]}"
    cp -al "$W/${TREES[$i]}/dist/v/no-${EXCLUDES[$i]}" "$W/repo/dist/v/"
  done
  env_for_build
  cd "$W/repo"
  uv run transport-maps reindex
  uv run python scripts/check_variants.py --dist dist
  echo "ready: deploy_solver.sh, then deploy_from_h200.sh, from the operator's machine"
}

case "${1:-}" in
  start) shift; start "$@" ;;
  status) status ;;
  finish) finish ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac

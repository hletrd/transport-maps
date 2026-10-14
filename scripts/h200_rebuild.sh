#!/usr/bin/env bash
# Run a full rebuild on h200: the full map and the three avoid-a-mode
# variants side by side, each in its own checkout, then publish-ready checks.
#
#   bash scripts/h200_rebuild.sh start [SERVICE_DATE]   # on h200, from $W/repo
#   bash scripts/h200_rebuild.sh status                 # done/total, rate, problems
#   bash scripts/h200_rebuild.sh finish                 # variants in, reindex, check
#   bash scripts/h200_rebuild.sh split MAP TREE [N]     # MAP's last part in a free TREE
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
# map 1.5 origins an hour, no-air 10.7, no-ferry and no-rail 3.1 each. Each
# build also checks its count against MemAvailable (cli._requested_workers):
# on 2026-10-10, at the old 12 GB a worker, 48 full-map workers were refused;
# at the measured 7 GB (2026-10-11) the same 693 GB holds 76.
: "${WORKERS_FULL:=30}" "${WORKERS_AIR:=4}" "${WORKERS_FERRY:=15}" "${WORKERS_RAIL:=15}"
# The owner's limit (2026-10-15): this project runs about 64 threads on h200
# at a time. Each worker is one busy thread (a tile write adds tippecanoe's two
# for a moment), so the four maps' workers add up to CPU_LIMIT -- rebuild 28's
# split scaled to 64 -- and a start that asks for more is refused. Where the
# threads run is left to the scheduler: no CPU pinning.
: "${CPU_LIMIT:=64}"
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
    # These checkouts are this script's; an edit made in one during a build (a
    # hot-patch belongs in the repo, committed) would otherwise stop the move
    # -- rebuild 29's first start did, on rebuild 28's patches. Say what goes.
    git -C "$W/$t" -c safe.directory='*' status --short --untracked-files=no \
      | sed "s|^|  discarding in $t: |"
    git -C "$W/$t" -c safe.directory='*' checkout -q -f --detach "$head"
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
  local date=${1:-$(date +%F)} i sum=0
  for i in "${WORKERS[@]}"; do sum=$((sum + i)); done
  if [ "$sum" -gt "$CPU_LIMIT" ]; then
    echo "!! ${sum} workers over the ${CPU_LIMIT}-thread limit; lower WORKERS_*"; exit 1
  fi
  env_for_build
  export TRANSPORT_MAPS_SERVICE_DATE=$date
  pids_headroom
  echo "checking inputs against their upstreams $(date '+%m-%d %H:%M')"
  (cd "$W/repo" && uv run transport-maps inputs) | tee -a "$W/inputs.log"
  checkouts
  for i in "${!TREES[@]}"; do
    local tree=${TREES[$i]} ex=${EXCLUDES[$i]} n=${WORKERS[$i]} log=$W/${LOGS[$i]}
    (
      # Not under the script's -e: a build that fails must still write its
      # exit line. Rebuild 29's full map refused at the memory pre-flight and
      # the subshell died silently before `exit` was logged.
      set +e
      cd "$W/$tree"
      touch "$W/.started-$tree"           # status counts records newer than this
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
    # Only records this run wrote: the previous build's complete ones are
    # still on disk until each origin is redone, and counted 1464/1464.
    printf '%-9s %5s/%s  last 30 min %4s  errors %s  %s\n' "${EXCLUDES[$i]:-full}" \
      "$(find "$p" -name '*.json' -newer "$W/.started-${TREES[$i]}" -exec grep -l '"complete"' {} + 2>/dev/null | wc -l)" "$total" \
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

exited() {  # exited <log>: the exit line after the latest restart, if any
  local r; r=$(grep -nE '^restart' "$1" | tail -1 | cut -d: -f1)
  awk -v r="${r:-0}" 'NR>r && /^exit/' "$1" | tail -1
}

stop_build() {  # stop_build <tree>: end that checkout's build-all, wait for its workers
  local u c
  for u in $(ps -eo pid,cmd | awk '/uv run transport-maps build-all/{print $1}'); do
    [ "$(readlink "/proc/$u/cwd")" = "$W/$1" ] || continue
    for c in $(pgrep -P "$u"); do pkill -TERM -P "$c"; kill -TERM "$c"; done; kill -TERM "$u"
  done
  while ps -eo cmd | grep -q "[/]default/worldmap/$1/.venv/bin/transport-maps"; do sleep 5; done
  rm -f "$W/$1/dist/.build.lock"
}

split() {  # split <full|air|ferry|rail> <free checkout> [workers]
  local map=$1 tail=$2 i main log ex tlog ih gh wt wm todo r k n only
  for i in "${!TREES[@]}"; do [ "${EXCLUDES[$i]:-full}" = "$map" ] && break; done
  [ "${EXCLUDES[$i]:-full}" = "$map" ] || { echo "!! map is full, air, ferry or rail"; exit 2; }
  main=${TREES[$i]} log=$W/${LOGS[$i]} ex=${EXCLUDES[$i]} wm=${WORKERS[$i]} tlog=$W/split-$map.log
  [ "$tail" != "$main" ] && [ -d "$W/$tail/.git" ] || { echo "!! $tail is not another checkout"; exit 2; }
  if ps -eo pid,cmd | awk '/uv run transport-maps build-all/{print $1}' \
       | while read -r u; do [ "$(readlink "/proc/$u/cwd")" = "$W/$tail" ] && echo busy; done | grep -q busy; then
    echo "!! $tail is still building"; exit 1
  fi
  env_for_build
  export TRANSPORT_MAPS_SERVICE_DATE
  TRANSPORT_MAPS_SERVICE_DATE=$(grep -oE 'service date [0-9-]+' "$log" | tail -1 | cut -d' ' -f3)
  read -r ih gh < <(grep -h 'skip-existing:' "$log" | tail -1 \
                    | sed -E 's/.*inputs ([0-9a-f]+) \/ graph ([0-9a-f]+).*/\1 \2/')
  [ -n "${gh:-}" ] || { echo "!! no inputs/graph hashes in $log yet"; exit 1; }
  # The tail checkout must be this build's code and inputs, or its graph hash
  # differs and none of its records would be accepted.
  git -C "$W/$tail" -c safe.directory='*' checkout -q -f --detach \
    "$(git -C "$W/$main" -c safe.directory='*' rev-parse HEAD)"
  rsync -a --delete --link-dest="$W/repo/data/cache/" "$W/repo/data/cache/" "$W/$tail/data/cache/"
  # Workers the memory pre-flight accepts, by its own figures.
  wt=${3:-$(cd "$W/$main" && .venv/bin/python -c "
from transport_maps.cli import PARENT_GB, WORKER_PEAK_GB
avail = next(int(l.split()[1]) for l in open('/proc/meminfo') if l.startswith('MemAvailable:')) / 2**20
print(max(0, int((0.8 * avail - PARENT_GB) // WORKER_PEAK_GB)))")}
  # The tail runs beside main's own workers; together they stay inside the
  # thread limit.
  [ "$wt" -gt $((CPU_LIMIT - wm)) ] && wt=$((CPU_LIMIT - wm))
  [ "$wt" -ge 8 ] || { echo "!! only $wt workers would fit"; exit 1; }
  todo=$(cd "$W/$main" && .venv/bin/python scripts/h200_split.py todo "$map" "$W/$main" "$ih" "$gh")
  r=$(echo "$todo" | tr ',' '\n' | grep -c .)
  # The tail's share, less what main does during the tail's ~10-minute setup.
  k=$(( r * wt / (wm + wt) - wm * 10 / 17 ))
  [ "$k" -ge 10 ] || { echo "only $r left; not worth a tail"; exit 0; }
  only=$(echo "$todo" | tr ',' '\n' | tail -n "$k" | paste -sd, -)
  n=$(cd "$W/$main" && .venv/bin/python -c "
from transport_maps.emit import index
s = [o['slug'] for o in index.load_origins()]
print(len(s) - s.index('${only%%,*}'))")
  echo "split $map: $r left; the last $k (roster tail of $n) to $tail, $wt workers $(date '+%m-%d %H:%M')" | tee -a "$log"
  (
    set +e
    cd "$W/$tail" && rm -f dist/.build.lock
    echo "restart (split $map tail, $wt workers) $(date '+%m-%d %H:%M')" >> "$tlog"
    TRANSPORT_MAPS_WORKERS=$wt nice -n 10 uv run transport-maps build-all --offline --skip-existing \
      ${ex:+--exclude "$ex"} --only "$only" >> "$tlog" 2>&1
    echo "exit $? at $(date '+%m-%d %H:%M')" >> "$tlog"
  ) &
  # Main fixed its list at start and would rebuild the tail's origins in the
  # same order: stop it once it holds everything before the tail range.
  until [ "$(cd "$W/$main" && .venv/bin/python scripts/h200_split.py lack "$map" "$W/$main" "$W/$tail" "$n" "$ih" "$gh")" = 0 ] \
        || [ -n "$(exited "$log")" ]; do sleep 60; done
  [ -n "$(exited "$log")" ] || { echo "split $map: main holds everything before the tail; stopping it $(date '+%m-%d %H:%M')" | tee -a "$log"; stop_build "$main"; }
  until [ -n "$(exited "$tlog")" ]; do sleep 60; done
  (cd "$W/$main" && .venv/bin/python scripts/h200_split.py merge "$map" "$W/$main" "$W/$tail" "$ih" "$gh") | tee -a "$log"
  (
    set +e
    cd "$W/$main"
    echo "restart (split $map: final pass over every origin, service date $TRANSPORT_MAPS_SERVICE_DATE) $(date '+%m-%d %H:%M')" >> "$log"
    TRANSPORT_MAPS_WORKERS=$wm nice -n 10 uv run transport-maps build-all --offline --skip-existing \
      ${ex:+--exclude "$ex"} >> "$log" 2>&1
    echo "exit $? at $(date '+%m-%d %H:%M')" >> "$log"
  )
}

case "${1:-}" in
  start) shift; start "$@" ;;
  split) shift; split "$@" ;;
  status) status ;;
  finish) finish ;;
  *) sed -n '2,11p' "$0"; exit 2 ;;
esac

#!/usr/bin/env bash
# Deploy the rebuilt dist and verify it end to end. Refuses to deploy a build
# whose artifacts disagree with each other -- a mismatched hover array and cell
# ordering renders a blank globe with no error, which has shipped once.
#
#   scripts/deploy_verify.sh               # full: gate dist/, sync web/ into it, run the page-asset
#                                          # gate (licence firewall + every tests/web/ test), check
#                                          # free space on the server, rsync, then live checks.
#                                          # scripts/browser_verify.sh is a SEPARATE stage and is
#                                          # not run from here -- CLAUDE.md's deploy rule means it
#                                          # must still be run before a deploy counts as done.
#   scripts/deploy_verify.sh --page-only   # web/ only: no dist gate, no --delete (a page fix
#                                          # while a rebuild owns dist/); the page reads every
#                                          # new index.json field with a fallback, so it is safe
#
# Host, server root and URL come from deploy/.env (see deploy/.env.example).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[ -f deploy/.env ] && source deploy/.env
: "${DEPLOY_HOST:=atik.kr}" "${DEPLOY_ROOT:=/var/www/worldmap}" "${SITE_URL:=https://worldmap.atik.kr}"
MODE=full
[ "${1:-}" = "--page-only" ] && MODE=page
LOG="$(mktemp -t deploy_verify.XXXXXX)"
RSYNC_COMMON=(-a --chmod=D755,F644 --exclude-from=deploy/rsync-excludes.txt)

# Gate over the page assets that actually ship. check_dist inspects the binary
# artifacts and the licence firewall used to run before web/ was merged into
# dist/, so index.html, app.js, llms.txt and vendor/ were covered by neither --
# and --page-only, which ships nothing but those files, ran no gate at all.
# The vendored-bundle pins (the CVE-2026-85061 patch) and the CSP inline-script
# hash added in cycle 2 were tests that never ran on the deploy path.
page_gate() {
  echo "=== page-asset gate: licence firewall, vendor pins, CSP hash, obligations ==="
  # The firewall test file now scans web/ as well as dist/, so this covers the
  # assets --page-only actually publishes; before, it read whatever the last
  # full deploy had left in dist/.
  # The list was hand-typed and omitted tests/web/test_ramps.py -- the
  # band-colour separation CLAUDE.md makes a standing rule and the only thing
  # that measures it -- and tests/web/test_water.py. A test's teeth should not
  # depend on whether someone remembered its filename, so this runs the whole
  # tests/web/ directory plus the licence firewall. It is 87 tests and about
  # two seconds; the previous five files were not meaningfully cheaper.
  uv run pytest -q -p no:cacheprovider \
    tests/test_licence_firewall.py tests/web/ tests/emit/test_water.py
}

if [ "$MODE" = full ]; then
  echo "=== 1. artifact consistency ==="
  # A build rewrites dist/origins in place; its lock (or, for a build started
  # before the lock existed, a build-all process that is actually working)
  # means dist/ is a mixed generation. Orphaned workers of a killed build sit
  # at 0 % CPU for days and must not block every deploy: only a process above
  # 1 % CPU counts. Reaping the orphans is the owner's call.
  if [ -e dist/.build.lock ]; then
    echo "  dist/.build.lock exists: a build-all is running or died holding it; refusing to deploy a mixed dist/"
    exit 1
  fi
  # `|| true`: grep exits 1 when nothing matches, and under `set -euo pipefail`
  # that aborted the whole script -- silently, with status 1 and no message --
  # every time NO build was running. The healthy path had never once executed.
  busy=$(/bin/ps -axo pid=,pcpu=,command= | grep -E "transport-maps build-all|transport_maps.cli build-all" | grep -v grep | awk '$2 >= 1 {print $1}' | tr '\n' ' ' || true)
  if [ -n "$busy" ]; then
    echo "  a build-all is running (pids $busy); refusing to deploy a mixed dist/"
    exit 1
  fi
  uv run python scripts/check_dist.py --dist dist --web web
  echo "=== 2. assemble and deploy ==="
  # The page-owned subtrees are mirrored WITH --delete so a removed vendor
  # file does not linger in dist/ (14 dead woff2 did, cached for a year).
  rsync -a --delete web/vendor/ dist/vendor/
  rsync "${RSYNC_COMMON[@]}" --exclude 'vendor/' web/ dist/
  # The page-asset gate runs AFTER the merge and BEFORE the push, so it scans
  # the index.html, app.js, llms.txt and vendor/ that are about to ship. Run
  # before the merge (as the licence firewall was) it scanned the PREVIOUS
  # deploy's copies and said nothing about the new ones.
  page_gate
  # --delay-updates stages the ENTIRE new payload alongside the old one before
  # it renames anything, so the peak requirement is both sets at once. The
  # pending payload is about 14 GB against roughly 2.6 GB live -- a five-fold
  # growth that has never been rehearsed -- and there was no free-space check
  # anywhere. Running out mid-rename produces exactly the mixed dist/ that
  # step 1 exists to prevent, on the server, where no gate can see it.
  #
  # Read-only: `df -Pk` over the connection rsync is about to use. A server
  # that will not answer is a warning, not a refusal -- this must not be a new
  # way for a good deploy to fail.
  need_kb=$(/usr/bin/du -sk dist | awk '{print $1}')
  want_kb=$(( need_kb * 23 / 10 ))          # the new payload plus the old set, plus 15%
  free_kb=$(ssh -o BatchMode=yes "$DEPLOY_HOST" "df -Pk $DEPLOY_ROOT | awk 'NR==2{print \$4}'" 2>/dev/null || true)
  if [ -z "$free_kb" ]; then
    echo "  could not read free space on $DEPLOY_HOST; continuing without the check"
  elif [ "$free_kb" -lt "$want_kb" ]; then
    echo "  $DEPLOY_HOST:$DEPLOY_ROOT has $((free_kb/1024/1024)) GiB free; --delay-updates stages"
    echo "  the new payload ($((need_kb/1024/1024)) GiB) beside the old one, so it needs about"
    echo "  $((want_kb/1024/1024)) GiB. Refusing before any byte moves: an rsync that runs out"
    echo "  mid-rename leaves the mixed dist/ this script exists to prevent."
    exit 1
  else
    echo "  free space ok: $((free_kb/1024/1024)) GiB available, about $((want_kb/1024/1024)) GiB needed"
  fi
  # --delete-delay and --delay-updates: every file is uploaded to a temp name
  # first and the renames happen at the end, so the window in which a visitor
  # sees a new index.json beside old origin arrays is seconds, not minutes.
  if ! rsync "${RSYNC_COMMON[@]}" --delete --delete-delay --delay-updates \
        dist/ "$DEPLOY_HOST:$DEPLOY_ROOT/" >"$LOG" 2>&1; then
    echo "  rsync failed; log: $LOG"; tail -20 "$LOG"; exit 1
  fi
  echo "  synced $(grep -c . "$LOG" || true) rsync lines; log: $LOG"
else
  echo "=== page-only deploy: web/ without the dist gate and without --delete ==="
  uv run python scripts/check_dist.py --web web --copy-only
  page_gate
  if ! rsync "${RSYNC_COMMON[@]}" web/ "$DEPLOY_HOST:$DEPLOY_ROOT/" >"$LOG" 2>&1; then
    echo "  rsync failed; log: $LOG"; tail -20 "$LOG"; exit 1
  fi
fi

echo "=== 3. live checks ==="
# These used to PRINT ten status codes and assert none of them: a deploy in
# which places.json, airports.json or borders.json 404'd still ended with
# "ALL CHECKS PASSED". Each probe now fails the deploy. The range probes are
# the only regression detector for PMTiles byte serving, so they assert 206
# specifically -- a server that answers 200 to a Range request has stopped
# byte-serving and the globe goes blank with no console error.
live_fail=0
probe() {  # probe <label> <url-path> <expected> [curl args...]
  local label="$1" path="$2" want="$3"; shift 3
  local got; got=$(curl -s -o /dev/null -w '%{http_code}' "$@" "$SITE_URL/$path" || echo 000)
  printf "  %-26s %s\n" "$label" "$got"
  [ "$got" = "$want" ] || { echo "  !! $path returned $got, expected $want"; live_fail=1; }
}
# The origin probed is the first one the DEPLOYED index.json lists, not a
# hard-coded "seoul": a build whose origin set changed must still be checked.
LIVE_SLUG=$(curl -sf "$SITE_URL/index.json" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["origins"][0]["slug"])' 2>/dev/null || true)
: "${LIVE_SLUG:=seoul}"
for f in index.json app.js index.html places.json airports.json borders.json \
         "origins/$LIVE_SLUG.air.bin" "origins/$LIVE_SLUG.modes.bin" "origins/$LIVE_SLUG.bin"; do
  probe "$f" "$f" 200
done
probe "$LIVE_SLUG.pmtiles range" "origins/$LIVE_SLUG.pmtiles" 206 -r 0-99
probe "water.pmtiles range" "water.pmtiles" 206 -r 0-99
[ "$live_fail" -eq 0 ] || { echo "!! live checks failed"; exit 1; }
# Report (not yet assert -- the corrected nginx conf is an owner install) the
# security headers on the page assets; absent CSP means the old conf is live.
for f in "" app.js index.json; do
  h=$(curl -sI "$SITE_URL/$f" | tr -d '\r' | grep -ci "^content-security-policy:" || true)
  printf "  %-26s CSP header: %s\n" "/${f}" "$([ "$h" -gt 0 ] && echo present || echo ABSENT)"
done

echo "=== 4. open it in a browser ==="
# No deploy is done until the page has been opened and checked (CLAUDE.md):
# a 200 proves nothing about whether the page runs.
"$ROOT/scripts/browser_verify.sh" "$SITE_URL/"

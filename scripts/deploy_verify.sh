#!/usr/bin/env bash
# Deploy the rebuilt dist and verify it end to end. Refuses to deploy a build
# whose artifacts disagree with each other -- a mismatched hover array and cell
# ordering renders a blank globe with no error, which has shipped once.
#
#   scripts/deploy_verify.sh               # full: gate dist/, sync web/ into it, rsync, live checks
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
  busy=$(/bin/ps -axo pid=,pcpu=,command= | grep -E "transport-maps build-all|transport_maps.cli build-all" | grep -v grep | awk '$2 >= 1 {print $1}' | tr '\n' ' ')
  if [ -n "$busy" ]; then
    echo "  a build-all is running (pids $busy); refusing to deploy a mixed dist/"
    exit 1
  fi
  uv run python scripts/check_dist.py --dist dist --web web
  echo "=== 1b. licence firewall on the artifact ==="
  uv run pytest -q -p no:cacheprovider tests/test_licence_firewall.py
  echo "=== 2. assemble and deploy ==="
  # The page-owned subtrees are mirrored WITH --delete so a removed vendor
  # file does not linger in dist/ (14 dead woff2 did, cached for a year).
  rsync -a --delete web/vendor/ dist/vendor/
  rsync "${RSYNC_COMMON[@]}" --exclude 'vendor/' web/ dist/
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
  if ! rsync "${RSYNC_COMMON[@]}" web/ "$DEPLOY_HOST:$DEPLOY_ROOT/" >"$LOG" 2>&1; then
    echo "  rsync failed; log: $LOG"; tail -20 "$LOG"; exit 1
  fi
fi

echo "=== 3. live checks ==="
for f in index.json app.js index.html places.json airports.json borders.json origins/seoul.air.bin origins/seoul.modes.bin; do
  printf "  %-26s %s\n" "$f" "$(curl -s -o /dev/null -w '%{http_code}' "$SITE_URL/$f")"
done
printf "  %-26s %s\n" "seoul.pmtiles range" "$(curl -s -o /dev/null -w '%{http_code}' -r 0-99 "$SITE_URL/origins/seoul.pmtiles")"
printf "  %-26s %s\n" "water.pmtiles range" "$(curl -s -o /dev/null -w '%{http_code}' -r 0-99 "$SITE_URL/water.pmtiles")"
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

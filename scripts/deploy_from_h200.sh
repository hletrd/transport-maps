#!/usr/bin/env bash
# Deploy a build from the machine that built it straight to the web host.
#
#   scripts/deploy_from_h200.sh
#
# Run from this machine, deploy_verify.sh moves every changed byte of dist/ to
# the web host, and for a build made on h200 that is two hops through
# aws-proxy: rebuild 28 (2026-10-06) took ~2.5 h to pull 110 GB at ~13 MB/s
# and ~3.3 h more to push 144 GiB. h200 reaches the web host directly at
# ~160 MB/s. So this runs the SAME deploy_verify.sh on h200, against the
# build's own dist/, then opens the page from here:
#
#   1. h200's checkout is moved to this commit (a git bundle; no credentials
#      needed there), and refused if it has local changes;
#   2. the static files build-all does not make -- water.pmtiles,
#      borders.pmtiles, borders.json, places.json, airports.json -- are copied
#      from this dist/ (deploy_verify mirrors dist/ with --delete, so a file
#      missing there would be deleted from the site);
#   3. deploy_verify.sh runs on h200 with BROWSER_VERIFY=by-caller, every gate
#      intact, through a key that can only rsync into the web root and run
#      deploy_verify's four read-only checks (deploy/worldmap-deploy-gate.sh);
#   4. browser_verify.sh runs here, and its status is this script's.
#
# The solver bundle still goes through scripts/deploy_solver.sh from here: it
# restarts a service, which that key cannot do.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[ -f deploy/.env ] && source deploy/.env
: "${BUILD_HOST:=h200}" "${BUILD_ROOT:=/default/worldmap}"
: "${BUILD_REPO:=$BUILD_ROOT/repo}" "${DEPLOY_ROOT:=/var/www/worldmap}"
: "${SITE_URL:=https://worldmap.atik.kr}" "${WEB_HOST:=atik.kr}"
STATIC=(water.pmtiles borders.pmtiles borders.json places.json airports.json)

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "!! uncommitted changes: the build host must run a commit, not this tree"; exit 1
fi
HEAD=$(git rev-parse HEAD)

echo "=== 1. build host checkout -> ${HEAD:0:7} ==="
THEIRS=$(ssh -o BatchMode=yes "$BUILD_HOST" \
  "git -C '$BUILD_REPO' -c safe.directory='*' rev-parse HEAD" 2>/dev/null || true)
BUNDLE=$(mktemp -t deploy-bundle.XXXXXX)
trap 'rm -f "$BUNDLE"' EXIT
if [ -n "$THEIRS" ] && git merge-base --is-ancestor "$THEIRS" "$HEAD" 2>/dev/null \
   && [ "$THEIRS" != "$HEAD" ]; then
  git bundle create -q "$BUNDLE" "$THEIRS..HEAD"
else
  git bundle create -q "$BUNDLE" HEAD
fi
scp -q "$BUNDLE" "$BUILD_HOST:$BUILD_ROOT/.deploy.bundle"
ssh -o BatchMode=yes "$BUILD_HOST" "set -e; cd '$BUILD_REPO'
  g() { git -c safe.directory='*' \"\$@\"; }
  if [ -n \"\$(g status --porcelain --untracked-files=no)\" ]; then
    echo '!! the build host checkout has local changes; refusing to move it'; exit 1
  fi
  g fetch -q '$BUILD_ROOT/.deploy.bundle' HEAD && g checkout -q --detach FETCH_HEAD
  [ \"\$(g rev-parse HEAD)\" = '$HEAD' ] || { echo '!! checkout did not land on $HEAD'; exit 1; }
  rm -f '$BUILD_ROOT/.deploy.bundle'"
echo "  $BUILD_HOST:$BUILD_REPO is at ${HEAD:0:7}"

echo "=== 2. static files build-all does not make ==="
for f in "${STATIC[@]}"; do
  [ -s "dist/$f" ] || { echo "!! dist/$f is missing here; it would be deleted from the site"; exit 1; }
done
rsync -a --rsync-path="$BUILD_ROOT/tools/bin/rsync" "${STATIC[@]/#/dist/}" "$BUILD_HOST:$BUILD_REPO/dist/"
echo "  ${STATIC[*]}"

echo "=== 3. deploy_verify.sh on $BUILD_HOST ==="
# The web host under its own alias: the deploy key, the web host's pinned host
# key, nothing from the account's other ssh settings.
ssh -o BatchMode=yes "$BUILD_HOST" "set -euo pipefail
  mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/config
  if ! grep -q '^Host worldmap-web\$' ~/.ssh/config; then
    printf '%s\n' 'Host worldmap-web' '  HostName $WEB_HOST' '  User ubuntu' \
      '  IdentityFile $BUILD_ROOT/.deploy-ssh/id_ed25519' '  IdentitiesOnly yes' \
      '  UserKnownHostsFile $BUILD_ROOT/.deploy-ssh/known_hosts' \
      '  StrictHostKeyChecking yes' '  BatchMode yes' >> ~/.ssh/config
  fi
  export PATH='$BUILD_ROOT/tools/bin':\$PATH UV_PYTHON_INSTALL_DIR='$BUILD_ROOT/uv-python' \
         UV_CACHE_DIR='$BUILD_ROOT/uv-cache' NUMPY_MADVISE_HUGEPAGE=0
  cd '$BUILD_REPO'
  DEPLOY_HOST=worldmap-web DEPLOY_ROOT='$DEPLOY_ROOT' RSYNC_DEST=worldmap-web:./ \
    SITE_URL='$SITE_URL' BROWSER_VERIFY=by-caller bash scripts/deploy_verify.sh"

echo "=== 4. open it in a browser (from here) ==="
exec "$ROOT/scripts/browser_verify.sh" "$SITE_URL/"

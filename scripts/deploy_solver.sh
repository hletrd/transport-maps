#!/usr/bin/env bash
# Ship the on-demand solver to the web host and prove it answers.
#
#     bash scripts/deploy_solver.sh [BUNDLE_DIR]
#
# BUNDLE_DIR defaults to data/build/solver, which every full `build-all` writes
# (src/transport_maps/service/bundle.py). Ships, in order:
#   1. the service code -- transport_maps/{__init__,config,snap}.py and
#      service/, nothing that imports the graph package;
#   2. numpy, scipy and h3 at the versions this checkout runs, into the
#      host's own venv;
#   3. the bundle, beside the live one, then swapped in by rename. ONE copy is
#      kept (owner, 2026-10-02: "release -> just keep one"): the previous
#      bundle survives only until the new one has answered a real solve;
#   4. the systemd unit and the nginx site, each only when it differs, nginx
#      only after `nginx -t` passes and rolled back if it does not.
# Then it asks the live service for Seoul -> Gumi through nginx and refuses to
# finish unless a number comes back.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f deploy/.env ] && . deploy/.env
DEPLOY_HOST=${DEPLOY_HOST:-atik.kr}
SITE_URL=${SITE_URL:-https://worldmap.atik.kr}
BUNDLE=${1:-data/build/solver}
HOME_DIR=/home/ubuntu/worldmap-solver

[ -f "$BUNDLE/meta.json" ] || { echo "no bundle at $BUNDLE (run build-all first)"; exit 1; }
echo "=== bundle: $(python3 -c "import json,sys;m=json.load(open(sys.argv[1]));print(m['nCells'],'cells',m['nnz'],'edges',m['identity'].get('buildId','?'))" "$BUNDLE/meta.json")"

echo "=== service code"
ssh -o BatchMode=yes "$DEPLOY_HOST" "mkdir -p $HOME_DIR/app/transport_maps/service"
rsync -a src/transport_maps/__init__.py src/transport_maps/config.py src/transport_maps/snap.py \
  "$DEPLOY_HOST:$HOME_DIR/app/transport_maps/"
rsync -a --delete --exclude __pycache__ src/transport_maps/service/ \
  "$DEPLOY_HOST:$HOME_DIR/app/transport_maps/service/"

echo "=== dependencies"
PINS=$(uv run python -c "import numpy, scipy, h3; print(f'numpy=={numpy.__version__} scipy=={scipy.__version__} h3=={h3.__version__}')")
ssh -o BatchMode=yes "$DEPLOY_HOST" "cd $HOME_DIR && { [ -x .venv/bin/python ] || ~/.local/bin/uv venv -q --python 3.14 .venv; } && ~/.local/bin/uv pip install -q --python .venv/bin/python $PINS"
echo "  $PINS"

echo "=== bundle upload"
rsync -a --delete "$BUNDLE/" "$DEPLOY_HOST:$HOME_DIR/bundle.new/"
# The site's hover_cells.bin beside the bundle: the service compares its own
# res-4 order with it at start and refuses to serve /api/map in another order
# (service/hovermap.py). From dist/ -- the same build the bundle came from,
# which deploy_verify.sh's solver_gate holds the release to.
if [ -f dist/hover_cells.bin ]; then
  rsync -a dist/hover_cells.bin "$DEPLOY_HOST:$HOME_DIR/bundle.new/hover_cells.bin"
  echo "  hover_cells.bin shipped beside the bundle"
fi

echo "=== unit and nginx"
scp -q deploy/worldmap-solver.service deploy/worldmap.atik.kr.conf "$DEPLOY_HOST:/tmp/"
ssh -o BatchMode=yes "$DEPLOY_HOST" 'set -e
if ! cmp -s /tmp/worldmap-solver.service /etc/systemd/system/worldmap-solver.service; then
  sudo install -m 644 -o root -g root /tmp/worldmap-solver.service /etc/systemd/system/worldmap-solver.service
  sudo systemctl daemon-reload; sudo systemctl enable -q worldmap-solver; echo "  unit installed"
fi
if ! cmp -s /tmp/worldmap.atik.kr.conf /etc/nginx/sites-available/worldmap.atik.kr; then
  sudo cp -p /etc/nginx/sites-available/worldmap.atik.kr /tmp/worldmap.atik.kr.prev
  sudo install -m 644 -o root -g root /tmp/worldmap.atik.kr.conf /etc/nginx/sites-available/worldmap.atik.kr
  if sudo nginx -t 2>/dev/null; then sudo systemctl reload nginx; echo "  nginx site installed"
  else sudo install -m 644 -o root -g root /tmp/worldmap.atik.kr.prev /etc/nginx/sites-available/worldmap.atik.kr
       echo "  nginx -t FAILED; previous site restored"; exit 1; fi
fi
rm -f /tmp/worldmap-solver.service /tmp/worldmap.atik.kr.conf'

echo "=== swap and restart"
ssh -o BatchMode=yes "$DEPLOY_HOST" "set -e; cd $HOME_DIR
rm -rf previous; [ -d current ] && mv current previous; mv bundle.new current
sudo systemctl restart worldmap-solver"

# Up when the port accepts; a solve then proves the bundle and the code agree.
probe() {
  curl -s -m 60 "$SITE_URL/api/solve?from=37.56650,126.97800&to=36.10000,128.40000"
}
ok=""
for _ in $(seq 1 30); do
  body=$(probe || true)
  case $body in *'"status":"ok"'*'"minutes":'[0-9]*) ok=$body; break ;; esac
  sleep 2
done
if [ -z "$ok" ]; then
  echo "  the solver did not answer: ${body:-nothing}"
  echo "  restoring the previous bundle"
  ssh -o BatchMode=yes "$DEPLOY_HOST" "cd $HOME_DIR && [ -d previous ] && rm -rf current && mv previous current && sudo systemctl restart worldmap-solver" || true
  exit 1
fi
echo "  Seoul -> Gumi through nginx: $ok"
# And the whole map from one point: the array must have the site's length.
map=$(curl -s -m 90 "$SITE_URL/api/map?from=37.80000,127.25000" || true)
case $map in
  *'"status":"ok"'*'"mapVersion":'*) echo "  /api/map: $(printf '%s' "$map" | head -c 160)..." ;;
  *) echo "  /api/map did not answer a map: $(printf '%s' "${map:-nothing}" | head -c 200)"; exit 1 ;;
esac
ssh -o BatchMode=yes "$DEPLOY_HOST" "rm -rf $HOME_DIR/previous $HOME_DIR/bundle-test"
echo "SOLVER DEPLOYED"

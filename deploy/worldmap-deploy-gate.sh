#!/bin/sh
# Forced command for the build host's deploy key on the web host.
#
# Installed as /usr/local/bin/worldmap-deploy-gate (root-owned) and named in
# ~ubuntu/.ssh/authorized_keys as
#
#   from="<build host egress IP>",restrict,command="/usr/local/bin/worldmap-deploy-gate" ssh-ed25519 ...
#
# The key lives on a shared machine (h200), so it can do exactly what
# scripts/deploy_verify.sh asks of the web host and nothing else: rsync inside
# the web root (through rrsync, which refuses any path outside it) and the four
# read-only checks below, matched as whole strings and then run as written
# HERE -- the incoming command is never evaluated. Anything else is refused.
# deploy/README.md, "Deploying from the build host", has the install steps.

ROOT=/var/www/worldmap
SOLVER_META=/home/ubuntu/worldmap-solver/current/meta.json

case "${SSH_ORIGINAL_COMMAND:-}" in
  "rsync --server "*)
    exec /usr/bin/rrsync "$ROOT" ;;
  "df -Pk '$ROOT' | awk 'NR==2{print \$4}'")
    df -Pk "$ROOT" | awk 'NR==2{print $4}' ;;
  "sha256sum '$ROOT/hover_cells.bin'")
    sha256sum "$ROOT/hover_cells.bin" ;;
  "sha256sum '$ROOT/reading_parents.bin'")
    sha256sum "$ROOT/reading_parents.bin" ;;
  "python3 -c \"import json;print(json.load(open('$SOLVER_META'))['identity'].get('buildId',''))\"")
    python3 -c "import json;print(json.load(open('$SOLVER_META'))['identity'].get('buildId',''))" ;;
  *)
    echo "worldmap-deploy-gate: refused: ${SSH_ORIGINAL_COMMAND:-<no command>}" >&2
    exit 1 ;;
esac

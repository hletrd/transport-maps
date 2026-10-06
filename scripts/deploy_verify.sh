#!/usr/bin/env bash
# Deploy the rebuilt dist and verify it end to end. Refuses to deploy a build
# whose artifacts disagree with each other -- a mismatched hover array and cell
# ordering renders a blank globe with no error, which has shipped once.
#
#   scripts/deploy_verify.sh               # full: gate dist/, sync web/ into it, run the page-asset
#                                          # gate (licence firewall + every tests/web/ test), check
#                                          # free space on the server, rsync, then live checks,
#                                          # ENDING with scripts/browser_verify.sh against the
#                                          # deployed URL (step 4). Under `set -euo pipefail` its
#                                          # exit code is this script's, so a page that does not
#                                          # RUN fails the deploy, which is CLAUDE.md's rule.
#                                          # (This block said browser_verify "is not run from
#                                          # here" until cycle 6. The stage was added in 29c6330
#                                          # and the sentence contradicting it in 83fb802 -- the
#                                          # commit that corrected this header for DOC3-14.)
#   scripts/deploy_from_h200.sh            # the same full deploy, run ON the build host so the
#                                          # build's files go straight to the web host; the
#                                          # browser stage then runs from this machine
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

# What --delay-updates will actually stage: the files that differ from the
# live set, in KiB. Measured by rsync's own dry run over the same flags, not by
# `du dist`: a rebuild of the three variant sets changed 56 of 108 GiB, and
# counting the whole tree refused a deploy that needed half the free space.
# Unchanged files are not copied, so they cost nothing to stage. Falls back to
# the whole tree when the dry run cannot answer -- the conservative figure.
# An index.json that offers the on-demand solver must find, on the server, the
# bundle written by the SAME build (emit/index._solver_matches made the same
# check locally). Otherwise the time from an exact point is computed on
# another graph than the map beside it. scripts/deploy_solver.sh ships it.
solver_gate() {
  local want have
  want=$(python3 -c "import json;d=json.load(open('dist/index.json'));print(d.get('buildId','') if d.get('solver') else '')")
  [ -n "$want" ] || return 0
  have=$(ssh -o BatchMode=yes "$DEPLOY_HOST" \
    "python3 -c \"import json;print(json.load(open('/home/ubuntu/worldmap-solver/current/meta.json'))['identity'].get('buildId',''))\"" 2>/dev/null || true)
  if [ "$have" != "$want" ]; then
    echo "  index.json offers the solver for build $want, but the server's bundle is '${have:-none}'."
    echo "  Run scripts/deploy_solver.sh first."
    exit 1
  fi
  echo "  solver bundle on the server matches build $want"
}

# A full rebuild changes every origin's files, which on the web host is more
# than it has free to stage in one --delay-updates pass (2026-10: ~145 GB
# changed against 70 GB free). It can still go a batch of origins at a time,
# each batch staged and renamed together, PROVIDED the files every origin is
# read against -- hover_cells.bin and reading_parents.bin -- are byte-identical
# on both sides: then an origin from the new build and one from the old are
# each consistent with the one layout the page holds, and index.json (last)
# only changes what is listed. A changed layout refuses instead (above).
layouts_identical() {
  local f l r
  for f in hover_cells.bin reading_parents.bin; do
    l=$(shasum -a 256 "dist/$f" 2>/dev/null | awk '{print $1}')
    r=$(ssh -o BatchMode=yes "$DEPLOY_HOST" "sha256sum '$DEPLOY_ROOT/$f'" 2>/dev/null | awk '{print $1}')
    if [ -z "$l" ] || [ "$l" != "$r" ]; then
      echo "  $f differs from the server's (or is missing)"
      return 1
    fi
  done
  echo "  hover_cells.bin and reading_parents.bin match the server's: origins can go in batches"
}

# The files of each batch of CHUNK origins, relative to dist/: the full set's
# and every variant's for the same slugs, so a departure never pairs its map
# with another build's avoid-a-mode files.
CHUNK=${CHUNK:-150}
chunk_lists() {  # chunk_lists <outdir>: writes <outdir>/chunk-NNNN, one per batch
  local out=$1 slugs n=0 i=0 list
  slugs=$(ls dist/origins | sed -n 's/\.pmtiles$//p' | sort)
  for slug in $slugs; do
    if [ $((n % CHUNK)) -eq 0 ]; then i=$((i + 1)); list=$(printf '%s/chunk-%04d' "$out" "$i"); : > "$list"; fi
    (cd dist && ls -d origins/"$slug".* v/*/origins/"$slug".* 2>/dev/null) >> "$list"
    n=$((n + 1))
  done
}

list_kb() {  # list_kb <list>: KiB on disk of the files <list> names, paths under dist/
  # Summed over every line, not read off a `du -c` total: xargs splits a
  # 5,400-path batch into more than one du, each with its own total, and the
  # last alone (~850 MB) stood for a 15 GB batch in the free-space check.
  (cd dist && xargs /usr/bin/du -k < "$1") | awk '{s += $1} END {print s + 0}'
}

chunked_sync() {
  local dir list kb free
  dir=$(mktemp -d)
  chunk_lists "$dir"
  for list in "$dir"/chunk-*; do
    kb=$(list_kb "$list")
    free=$(ssh -o BatchMode=yes "$DEPLOY_HOST" "df -Pk '$DEPLOY_ROOT' | awk 'NR==2{print \$4}'" 2>/dev/null || true)
    case ${free:-x} in *[!0-9]*) echo "  could not read free space; stopping between batches"; exit 1 ;; esac
    if [ "$free" -lt $((kb * 13 / 10)) ]; then
      echo "  $(basename "$list"): needs $((kb/1024)) MB staged, $((free/1024)) MB free; stopping between batches"
      exit 1
    fi
    if ! rsync "${RSYNC_COMMON[@]}" --delay-updates --files-from="$list" \
          dist/ "$DEPLOY_HOST:$DEPLOY_ROOT/" >>"$LOG" 2>&1; then
      echo "  rsync failed in $(basename "$list"); log: $LOG"; tail -20 "$LOG"; exit 1
    fi
    echo "  $(basename "$list"): $(wc -l < "$list" | tr -d ' ') files, $((kb/1024)) MB"
  done
  rm -rf "$dir"
  # What is left is small: index.json, the variant markers, the page, and
  # deletions. The ordinary single pass below finishes it.
}

transfer_kb() {
  local bytes
  bytes=$(rsync "${RSYNC_COMMON[@]}" --delete --dry-run --stats \
            dist/ "$DEPLOY_HOST:$DEPLOY_ROOT/" 2>/dev/null \
          | awk -F': ' '/^Total transferred file size/{gsub(/[^0-9]/, "", $2); print $2}')
  case ${bytes:-} in
    ""|*[!0-9]*) /usr/bin/du -sk dist | awk '{print $1}' ;;
    *) echo $(( bytes / 1024 + 1 )) ;;
  esac
}

# Gate over the page assets that actually ship. check_dist inspects the binary
# artifacts and the licence firewall used to run before web/ was merged into
# dist/, so index.html, app.js, llms.txt and vendor/ were covered by neither --
# and --page-only, which ships nothing but those files, ran no gate at all.
# The vendored-bundle pins (and the CVE-2026-85061 fix they carry) and the CSP inline-script
# hash added in cycle 2 were tests that never ran on the deploy path.
page_gate() {
  echo "=== page-asset gate: licence firewall, vendor pins, CSP hash, obligations ==="
  # The firewall test file now scans web/ as well as dist/, so this covers the
  # assets --page-only actually publishes; before, it read whatever the last
  # full deploy had left in dist/.
  # The list was hand-typed and omitted tests/web/test_ramps.py -- the
  # band-colour separation CLAUDE.md makes a standing rule and the only thing
  # that measures it -- and the water test, which lives under tests/emit/ and
  # which this comment used to place under tests/web/, where no such file has
  # ever existed. A test's teeth should not depend on whether someone
  # remembered its filename, so this runs the whole tests/web/ directory plus
  # the licence firewall: 139 tests and about two seconds at the time of
  # writing, and it grows by itself. The count is here to say the order of
  # magnitude, not to be kept exact.
  #
  # tests/web/test_parses.py is why this stage is worth having at all: nothing
  # else in the repository parses app.js, and a syntax error in it would
  # otherwise be rsynced live before step 4 ever opened a browser.
  #
  # A SKIP IS A FAILURE HERE. pytest exits 0 when a test skips, and 22 of the
  # files under tests/web/ skip themselves when `node` is not on PATH -- 19 of
  # them, measured, including test_parses.py and the only legend-tick
  # enforcement. So on a host without node this whole stage printed a row of
  # dots and returned success while checking none of the things the paragraph
  # above says it checks. That is not hypothetical on this machine: `node`
  # here resolves to ~/.local/state/fnm_multishells/<pid>_<ts>/bin/node, an
  # fnm PER-SHELL-SESSION path, so a deploy from launchd, from cron, or from
  # any shell fnm did not initialise has no node and would have sailed through.
  #
  # Checked up front, so the operator gets one clear sentence rather than a
  # green run they have to count the dots in.
  if ! command -v node >/dev/null 2>&1; then
    echo "  !! node is not on PATH, so the page gate cannot parse app.js."
    echo "     19 of the tests/web/ files would skip themselves and this stage"
    echo "     would exit 0 without checking the page at all. Refusing: a"
    echo "     syntax error in app.js would otherwise be rsynced live."
    exit 1
  fi
  # ...and belt as well as braces: node is not the only reason a test can
  # skip, and any new skip in this set is a check that silently stopped
  # running. `tee` keeps the run visible on the operator's screen while
  # leaving a copy to count the skips in.
  # Lint before the tests. `ruff check` is one of this repository's two gates
  # and NOTHING invoked it: no CI, no pre-commit, and zero references in
  # either deploy script. It was a gate by convention only, which is to say
  # it was whatever the last person to run it by hand had left it as.
  echo "  ruff check ."
  if ! uv run ruff check . ; then
    echo "  !! ruff check failed. Refusing."
    exit 1
  fi

  local out rc=0 collected
  out="$(mktemp -t page_gate.XXXXXX)"
  # The floor. Counting failures proves nothing FAILED; it does not prove
  # anything RAN, and this stage has now twice been able to report success
  # over an almost-empty run. So collect first and require that every test
  # collected is accounted for below. Cheap: collection is under a second.
  collected=$(uv run pytest -q -p no:cacheprovider --collect-only \
    tests/test_licence_firewall.py tests/web/ tests/emit/test_water.py 2>/dev/null \
    | grep -oE '[0-9]+ test(s)? collected' | grep -oE '^[0-9]+' || true)
  # `|| rc=$?` and not a bare pipeline: under `set -e` a failing pytest would
  # abort the script here and never reach the checks below, so the refusals
  # would not compose. pipefail is already set, so rc is pytest's status and
  # not tee's. `-rs` prints one line per skip WITH ITS REASON, which is what
  # lets the two kinds of skip be told apart.
  uv run pytest -q -rs -p no:cacheprovider \
    tests/test_licence_firewall.py tests/web/ tests/emit/test_water.py \
    2>&1 | tee "$out" || rc=$?
  if [ "$rc" -ne 0 ]; then
    rm -f "$out"
    echo "  !! page-asset gate failed (pytest exit $rc)"
    exit "$rc"
  fi

  # grep, not `sed -n 's/.*[^0-9]...'`: pytest writes "421 passed, 3 skipped"
  # when something ran and "3 skipped in 0.12s" when NOTHING did, and the
  # leading-digit form is exactly the all-skipped case this check exists for.
  # `|| true` on every one of these for the same reason the free-space check
  # below carries one: grep exits 1 when nothing matches, which is the
  # HEALTHY case here, and under `set -euo pipefail` that aborts the whole
  # script silently. This script has already shipped that exact bug once.
  local n_skipped n_dist_skips n_passed other
  count_of() { grep -oE "[0-9]+ $1" "$out" | tail -1 | grep -oE '^[0-9]+' || true; }
  n_skipped=$(count_of skipped)
  n_passed=$(count_of passed)
  # pytest exits 0 on every one of these, and each means a test that did not
  # run or did not run as itself. C15-2 closed `skipped` and left the rest:
  # `3 passed, 421 deselected` sailed through, and pyproject.toml already
  # carries `-m 'not network and not real_multi_band'`, so ONE `pytestmark`
  # on tests/web/test_parses.py -- the file the paragraph above calls the
  # reason this stage is worth having -- silently removed it from the gate.
  for kind in deselected xfailed xpassed error errors; do
    other=$(count_of "$kind")
    if [ -n "${other:-}" ] && [ "$other" -gt 0 ]; then
      echo "  !! $other test(s) in the page gate reported '$kind'."
      echo "     pytest exits 0 on that, so this stage would have reported"
      echo "     success while checking less than it claims. Refusing."
      rm -f "$out"
      exit 1
    fi
  done

  # A skip because nothing is BUILT has not stopped checking anything --
  # there is nothing to check, and tests/test_licence_firewall.py asserts
  # that a skip is the correct answer for an unbuilt tree. A skip for any
  # other reason (no node, a missing dependency, a condition someone added
  # later) is a check that silently stopped running, which is the hole
  # C15-2 closed and which stays closed.
  #
  # The two are told apart by the sentinel tests/conftest.py's
  # skip_without_dist() puts in the reason, which `-rs` prints. Without this,
  # C15-2's rule broke --page-only -- the one mode documented as not needing
  # dist/ -- on every clone, because dist/ is gitignored.
  # `-rs` groups identical skips as "SKIPPED [N] path: reason", so the count
  # is the sum of the bracketed N, NOT the number of lines. Counting lines
  # under-reports every grouped skip and refuses a --page-only run that
  # should pass -- measured: 3 lines for 7 skipped tests.
  n_dist_skips=$(grep -E '^SKIPPED \[[0-9]+\].*needs a built dist/' "$out" \
    | grep -oE '^SKIPPED \[[0-9]+\]' | grep -oE '[0-9]+' \
    | awk '{n += $1} END {print n + 0}' || true)
  rm -f "$out"
  : "${n_skipped:=0}" "${n_dist_skips:=0}" "${n_passed:=0}"
  if [ "$n_skipped" -gt "$n_dist_skips" ]; then
    echo "  !! $((n_skipped - n_dist_skips)) test(s) in the page gate SKIPPED"
    echo "     for a reason other than an unbuilt dist/. pytest exits 0 on a"
    echo "     skip, so this stage would have reported success while checking"
    echo "     less than it claims. Refusing."
    exit 1
  fi
  if [ "$n_dist_skips" -gt 0 ] && [ -f dist/index.json ]; then
    echo "  !! $n_dist_skips test(s) skipped for an unbuilt dist/, but"
    echo "     dist/index.json is present. Those tests had something to read"
    echo "     and did not read it. Refusing."
    exit 1
  fi
  if [ -n "${collected:-}" ] && [ "$((n_passed + n_dist_skips))" -ne "$collected" ]; then
    echo "  !! the page gate collected $collected test(s) but only"
    echo "     $n_passed passed and $n_dist_skips skipped for an unbuilt dist/."
    echo "     $((collected - n_passed - n_dist_skips)) are unaccounted for. Refusing."
    exit 1
  fi
  if [ -z "${collected:-}" ] || [ "$collected" -lt 1 ]; then
    echo "  !! the page gate collected no tests at all. Refusing."
    exit 1
  fi
  echo "  page gate: $n_passed passed, $n_dist_skips skipped for an unbuilt dist/, of $collected collected"
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
  solver_gate
  # --delay-updates stages the new payload alongside the old one before it
  # renames anything, so the peak requirement is the payload plus whatever the
  # old set already occupies. The 553-origin payload measures 15.69 GiB against
  # roughly 2.6 GB live when this check was written -- a six-fold growth that
  # had never been rehearsed -- and there was no free-space check anywhere.
  # Running out mid-rename produces exactly the mixed dist/ that step 1 exists
  # to prevent, on the server, where no gate can see it.
  #
  # Read-only: `df -Pk` over the connection rsync is about to use. A server
  # that will not answer is a warning, not a refusal -- this must not be a new
  # way for a good deploy to fail.
  need_kb=$(transfer_kb)
  # x1.3, not x2.3. The old set is ALREADY on the disk, so `df` has already
  # excluded it from the free figure; adding it back counted it twice and
  # demanded 36.1 GiB for a measured 15.69 GiB dist. --delay-updates stages the
  # NEW payload beside the old one, so the transient requirement is the payload
  # plus a margin, which is what V26 specified and what the run it was written
  # for actually measured: 18 GB peak for a ~16 GB payload.
  want_kb=$(( need_kb * 13 / 10 ))          # the staged payload, plus 30%
  # $DEPLOY_ROOT quoted for the REMOTE shell too. Unquoted, a root with a
  # space in it made df read its first word -- usually /, a different
  # filesystem with different free space -- and the guard that exists to stop a
  # half-written dist/ reaching the server silently measured somewhere else.
  free_kb=$(ssh -o BatchMode=yes "$DEPLOY_HOST" \
    "df -Pk '$DEPLOY_ROOT' | awk 'NR==2{print \$4}'" 2>/dev/null || true)
  # Whatever came back is REMOTE OUTPUT, and every use of it below is an
  # arithmetic context: `[ "$free_kb" -lt ... ]` and `$(( free_kb/1024/1024 ))`.
  # Bash evaluates a name inside `$(( ))` by evaluating its VALUE as an
  # arithmetic expression, and an array subscript inside one is a command
  # substitution -- so a host answering `MODE[$(...)]` instead of a number runs
  # that command on the operator's machine. Demonstrated: a stub ssh returning
  # `MODE[$(id -un > PWNED)]` wrote the file locally. `set -u` is not a
  # defence; it only decides which already-set name works as the subscript.
  #
  # The remote is the owner's own server, so this is not a realistic attacker
  # today. It is a shell-injection primitive sitting in the one script that
  # reaches out to another machine, and it costs one `case` to close.
  case ${free_kb:-} in
    "") ;;                       # ssh failed; the branch below says so
    *[!0-9]*)
      echo "  $DEPLOY_HOST returned a non-numeric free-space figure; ignoring it"
      free_kb="" ;;
  esac
  if [ -z "$free_kb" ]; then
    echo "  could not read free space on $DEPLOY_HOST; continuing without the check"
  elif [ "$free_kb" -lt "$want_kb" ]; then
    echo "  $DEPLOY_HOST:$DEPLOY_ROOT has $((free_kb/1024/1024)) GiB free; --delay-updates stages"
    echo "  the changed files ($((need_kb/1024/1024)) GiB) beside the old ones, so it needs about"
    echo "  $((want_kb/1024/1024)) GiB -- more than is free, so not in one pass."
    if layouts_identical; then
      chunked_sync
    else
      echo "  Refusing before any byte moves: the cell layout changed, so origins cannot"
      echo "  be swapped a batch at a time, and an rsync that runs out mid-rename leaves"
      echo "  the mixed dist/ this script exists to prevent."
      exit 1
    fi
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
for f in index.json app.js index.html places.json airports.json \
         "origins/$LIVE_SLUG.air.bin" "origins/$LIVE_SLUG.modes.bin" "origins/$LIVE_SLUG.bin"; do
  probe "$f" "$f" 200
done
# The page says the libraries' "copyright notices and licence texts are served
# with them" and links this directory. It returned 403 for as long as the link
# existed: nginx has `index index.html` and no autoindex, and the directory had
# no index.html. The five .txt files served 200 with nothing linking to them,
# so BSD-3-Clause section 2 and Apache-2.0 section 4 were unmet in practice
# while every gate passed -- tests/web/test_vendor.py asserted only that the
# href STRING appeared in the HTML, which is exactly what a link to a 403 does.
# Probing the URL the page actually offers is the only check that can see it.
probe "vendor/licences/ (the page's only link to the notices)" "vendor/licences/" 200
for f in vendor/licences/maplibre-gl.LICENSE.txt vendor/licences/pmtiles.LICENSE.txt \
         vendor/licences/h3-js.LICENSE.txt vendor/licences/h3-js.NOTICE.txt \
         vendor/licences/fflate.LICENSE.txt vendor/OFL.txt; do
  probe "$f" "$f" 200
done
probe "$LIVE_SLUG.pmtiles range" "origins/$LIVE_SLUG.pmtiles" 206 -r 0-99
probe "water.pmtiles range" "water.pmtiles" 206 -r 0-99
probe "borders.pmtiles range" "borders.pmtiles" 206 -r 0-99
[ "$live_fail" -eq 0 ] || { echo "!! live checks failed"; exit 1; }
# The security headers are ASSERTED, on every asset class the page loads. This
# used to print "CSP header: present" for three paths and assert nothing,
# because the corrected nginx conf was an owner install still to come. It is
# installed now, and a header that silently disappears is exactly what nginx
# does when a location gains an add_header of its own (E3: add_header does not
# merge across levels), so the next such edit must fail a deploy rather than be
# found by a reviewer.
#
# The expected values are READ from deploy/worldmap-security-headers.conf --
# the file the server includes -- not copied here, so tightening the CSP or the
# Permissions-Policy (browsing-topics=() and the other three advertising APIs)
# changes the check with it. Each header must be present and equal to the
# conf's value exactly: a substring test would accept a CSP with a source
# appended, or a Permissions-Policy missing its last four entries. The parse is
# itself checked -- a conf it cannot read would otherwise expect nothing and
# pass everything.
check_security_headers() {  # check_security_headers <conf> <url-path>...
  local conf="$1" path hdrs bad=0; shift
  for path in "$@"; do
    hdrs=$(curl -sI "$SITE_URL/$path" 2>&1 | tr -d '\r' || true)
    python3 - "$conf" "/$path" "$hdrs" <<'PY' || bad=1
import re
import sys

conf, label, raw = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(conf, encoding="utf-8").read()
want = {m.group(1).lower(): m.group(2) for m in re.finditer(
    r'^\s*add_header\s+([A-Za-z-]+)\s+"([^"]*)"\s+always\s*;', text, re.M)}
required = {"content-security-policy", "strict-transport-security", "x-frame-options",
            "referrer-policy", "permissions-policy", "x-content-type-options"}
if not required <= want.keys():
    print(f"  !! could not read {sorted(required - want.keys())} from {conf}; "
          "the header check would expect nothing")
    sys.exit(1)
got = {}
for line in raw.splitlines():
    name, sep, value = line.partition(":")
    if sep and " " not in name.strip():
        got.setdefault(name.strip().lower(), []).append(value.strip())
bad = []
for name, value in sorted(want.items()):
    have = got.get(name, [])
    if not have:
        bad.append(f"{name} ABSENT")
    elif any(v != value for v in have):
        bad.append(f"{name} is {' | '.join(have)!r}, the conf says {value!r}")
for b in bad:
    print(f"  !! {label}: {b}")
if bad:
    sys.exit(1)
print(f"  {label:<26} security headers: all {len(want)} match the conf")
PY
  done
  return $bad
}
check_security_headers "$ROOT/deploy/worldmap-security-headers.conf" \
    "" app.js index.json hover_cells.bin water.pmtiles "origins/$LIVE_SLUG.pmtiles" \
  || { echo "!! the live security headers do not match deploy/worldmap-security-headers.conf"; exit 1; }

echo "=== 4. open it in a browser ==="
# No deploy is done until the page has been opened and checked (CLAUDE.md):
# a 200 proves nothing about whether the page runs.
#
# BROWSER_VERIFY=by-caller is for a run on the build host, which has no
# browser: scripts/deploy_from_h200.sh sets it there and runs
# browser_verify.sh from the operator's machine as its very next step, and
# exits with that check's status. Nothing else sets it.
if [ "${BROWSER_VERIFY:-}" = "by-caller" ]; then
  echo "  not from this host: the caller runs scripts/browser_verify.sh next"
else
  "$ROOT/scripts/browser_verify.sh" "$SITE_URL/"
fi

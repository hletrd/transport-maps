#!/usr/bin/env bash
# Post-deploy browser verification. Exits non-zero on any failed check.
#   scripts/browser_verify.sh                        # the live site (SITE_URL from deploy/.env)
#   scripts/browser_verify.sh http://127.0.0.1:8899/ # a local dist
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/deploy/.env" ] && source "$ROOT/deploy/.env"
: "${SITE_URL:=https://worldmap.atik.kr}"
URL="${1:-$SITE_URL/}"
URL="${URL%/}/"
SHOTS="$(mktemp -d -t browser_verify.XXXXXX)"
# Expected counts come from the deployed index.json, never from a literal:
# 157 cities and 37 swatches were hard-coded here and would have blocked the
# correct 553-origin deploy. The legend shows one swatch per band in .tints
# plus two keys in .keys, for "no scheduled route" and "open water".
IDX=$(curl -sf "${URL}index.json") || { echo "!! could not fetch ${URL}index.json"; exit 1; }
read -r CITIES BANDS < <(printf '%s' "$IDX" | python3 -c 'import json, sys
d = json.load(sys.stdin); print(len(d["origins"]), len(d["bandEdgesMin"]) + 1)')
[ -n "${BANDS:-}" ] || { echo "!! index.json has no origins/bandEdgesMin"; exit 1; }
TINTS=$((BANDS + 2))
# One entry per colour scheme, counted from the RAMPS table SPECIFICALLY.
# The old heuristic grepped the whole file for `  name: {` lines, which also
# matched the OCEANS table -- a different thing, six sea colours -- so it asked
# the page for 18 schemes when 12 exist, and failed the deploy on a page that
# was correct. Parse the block; do not pattern-match the file.
SCHEMES=$(python3 -c 'import re,sys; s=open(sys.argv[1],encoding="utf-8").read(); m=re.search(r"const RAMPS = \{(.*?)\n\};", s, re.S); print(len(re.findall(r"^\s{2}[a-z]+:\s*\{", m.group(1), re.M)) if m else 0)' "$ROOT/web/app.js")
[ "${SCHEMES:-0}" -ge 6 ] || { echo "!! could not read the RAMPS table from web/app.js"; exit 1; }
# The resting list is capped: at 553 origins it is 14,486 px and at 1,464 it is
# 38,357, which nobody scrolls and every keystroke rebuilt. This asked for one
# row per origin, which was right when the list showed all of them and is a
# stale assumption now -- so it asks for the capped number instead, AND for the
# footer that names the true total, which is the thing that makes a cap honest.
# Read from app.js, not a literal, for the same reason SCHEMES is.
CAP=$(python3 -c 'import re,sys; m=re.search(r"const UNFILTERED_CAP = (\d+);", open(sys.argv[1],encoding="utf-8").read()); print(m.group(1) if m else 0)' "$ROOT/web/app.js")
[ "${CAP:-0}" -ge 1 ] || { echo "!! could not read UNFILTERED_CAP from web/app.js"; exit 1; }
ROWS=$CITIES
[ "$CITIES" -gt "$CAP" ] && ROWS=$CAP
echo "expecting $ROWS of $CITIES cities in the list (cap $CAP), $BANDS bands ($TINTS swatches) from index.json; $SCHEMES schemes; screenshots in $SHOTS"

# The departure city the phone checks tap near, from index.json rather than a
# literal. Both tap checks below used a hardcoded [120, 40], which is in the
# Bohai Sea: that point's res-4 cell is land and reads 580 min from Tokyo, but
# its res-6 cell is not, so the reading tier holds the padding sentinel for it
# (emit/hover.py) and the page prints "no scheduled route". setDestination
# then returns before it opens the panel or unfolds the sheet, correctly --
# an unreachable point is not a destination -- so one check reported a defect
# on a page that was right, and the other went green because the scroll it
# exists to detect could not happen.
read -r OLON OLAT < <(printf '%s' "$IDX" | python3 -c 'import json, sys
o = next(x for x in json.load(sys.stdin)["origins"] if x["slug"] == "tokyo")
print(o["lon"], o["lat"])')
[ -n "${OLAT:-}" ] || { echo "!! index.json has no tokyo origin for the phone checks to tap"; exit 1; }

# One tap, at a point the page can actually read. The point is CHOSEN, not
# assumed: near the departure city, the canvas must be topmost under it -- the
# topmost element at the city's own coordinate is SPAN.dot, its label's own
# dot, measured with real CDP input, and every label calls stopPropagation
# because a label is not a destination -- and the page's own hover reading
# there must already be a number. Dispatching straight at the canvas element,
# as both checks used to, skips hit testing, so they could have passed where no
# finger could reproduce them.
#   tap_js <lon> <lat> <js-object-literal to merge into the result>
# `on(sel)` is in scope for the caller's literal: is that element inside the
# rail's visible box.
tap_js() {
  cat <<JS
(()=>{const m=window.__map;
  m.jumpTo({center:[$1,$2],zoom:7,bearing:0,pitch:0});
  const wait=(ms)=>new Promise(r=>setTimeout(r,ms));
  return (async()=>{
   await wait(1200);
   const c=document.querySelector("#map canvas"),r=c.getBoundingClientRect();
   const p=m.project([$1,$2]);
   const num=(s)=>/^[0-9]/.test(s.trim());
   let pick=null;
   for(const [dx,dy] of [[0,0],[0,-40],[40,0],[-40,0],[0,40],[80,-80],[-80,-80],[0,-120],[120,0]]){
     const x=r.left+p.x+dx,y=r.top+p.y+dy;
     if(x<r.left||y<r.top||x>r.right||y>r.bottom) continue;
     if(document.elementFromPoint(x,y)!==c) continue;
     c.dispatchEvent(new MouseEvent("mousemove",{clientX:x,clientY:y,bubbles:true}));
     await wait(260);
     if(num(document.getElementById("time").textContent)){ pick={x,y,dx,dy}; break; }
   }
   if(!pick) return JSON.stringify({picked:false});
   const o={clientX:pick.x,clientY:pick.y,bubbles:true};
   c.dispatchEvent(new MouseEvent("mousedown",o));
   c.dispatchEvent(new MouseEvent("mouseup",o));
   c.dispatchEvent(new MouseEvent("click",o));
   await wait(1600);
   const rl=document.querySelector(".rail"),v=rl.getBoundingClientRect();
   const on=(s)=>{const b=document.querySelector(s).getBoundingClientRect();return b.top>=v.top-1&&b.bottom<=v.bottom+1};
   return JSON.stringify(Object.assign({picked:true,at:[pick.dx,pick.dy]}, $3));
  })();})()
JS
}
# Wait for a CONDITION, never for a number of seconds. Both cold loads used to
# `sleep 15` / `sleep 10` and then read: the waits were chosen against a
# 553-origin build and every data assertion read straight after them, so as
# index.json grew to 1,464 origins and the reading tier to ~10 MB they became
# the mechanism behind the gate failures recorded on correct code (C12-8,
# V13-28; commits 9d7c484 and 5cf7ad2 are the same shape). A bigger number only
# moves the cliff.
#   wait_until <ceiling seconds> <what> <js that returns true when ready>
# The ceiling is a ceiling: it returns the moment the page answers true. When
# it is reached it says so and sets fail=1 -- the checks after it still run, so
# the output names WHICH part never arrived, and the cleanup at the end still
# happens.
wait_until() {
  local limit=$1 what=$2 js=$3 got="" t0=$SECONDS
  while [ $((SECONDS - t0)) -lt "$limit" ]; do
    got=$(agent-browser eval "$js" 2>&1 | tail -1 | tr -d '\\"')
    if [ "$got" = "true" ]; then
      echo "  ready after $((SECONDS - t0)) s: $what"
      return 0
    fi
    sleep 1
  done
  echo "  !! waited ${limit} s for $what and it never happened (last answer: ${got:-nothing})."
  echo "     The checks below read a page that was not ready; this is the failure to fix first."
  fail=1
  return 1
}
# One number out of an eval's JSON, read whole and compared as a number -- so
# `"departing":1` can no longer be satisfied by 1000-1464 the way the old
# unanchored substring was. Empty output means the key was absent: the caller
# must treat that as a failure, never as zero.
json_num() { printf '%s' "$2" | sed -n "s/.*\"$1\":\([0-9][0-9]*\).*/\1/p"; }
# The city list's counts, compared with EACH OTHER and with the row count
# rather than against a literal width. `"durations":[1-9][0-9]` asserted ten
# timed rows -- at the cap of 60 that let 49 rows go blank -- and
# `"departing":1` matched any count from 1 to 1999.
#   - exactly one row is the current departure;
#   - no row is blank: a blank `.rowtime` is a row rendered before the
#     per-origin array landed, i.e. the page the old fixed sleep could catch;
#   - every row is a travel time, "no route" or "departing" -- the counts must
#     add up to the rows -- and at least one is a travel time;
#   - a capped resting list is the quickest $CAP to reach (capCities), so when
#     the roster exceeds the cap it shows nothing unreachable.
check_city_list() {
  local cl=$1 rows dur nr blank dep bad=0
  rows=$(json_num rows "$cl"); dur=$(json_num durations "$cl"); nr=$(json_num noRoute "$cl")
  blank=$(json_num blank "$cl"); dep=$(json_num departing "$cl")
  if [ -z "$rows" ] || [ -z "$dur" ] || [ -z "$nr" ] || [ -z "$blank" ] || [ -z "$dep" ]; then
    echo "  !! could not read the city-list counts; every check on them would pass vacuously"
    return 1
  fi
  [ "$dep" -eq 1 ] || { echo "  !! $dep rows are marked as the current departure, not exactly one"; bad=1; }
  if [ "$blank" -ne 0 ]; then
    echo "  !! $blank of $rows city rows carry no travel time at all"; bad=1
  elif [ $((dur + nr + dep)) -ne "$rows" ]; then
    echo "  !! $((rows - dur - nr - dep)) of $rows city rows read as neither a time, \"no route\" nor \"departing\""; bad=1
  fi
  [ "$dur" -ge 1 ] || { echo "  !! the city list carries no travel times"; bad=1; }
  if [ "$CITIES" -gt "$CAP" ] && [ "$nr" -ne 0 ]; then
    echo "  !! the resting list is the quickest $CAP to reach, yet $nr of its rows have no route"; bad=1
  fi
  return $bad
}
# Only the browser processes THIS run starts are killed at the end: another
# agent's session on the same machine must survive a verification pass.
BEFORE=$(/bin/ps -ax -o pid=,command= | grep -E "\.agent-browser/" | grep -v grep | awk '{print $1}' | sort)
cd "$SHOTS"
agent-browser close >/dev/null 2>&1
# agent-browser keeps the viewport between runs, so the "desktop" checks below
# silently ran at whatever size the last session left -- 390x844 after a phone
# pass, which put the route click into the Pacific and failed two checks that
# have nothing to do with the route.
agent-browser set viewport 1280 800 >/dev/null 2>&1
fail=0
agent-browser open "$URL" >/dev/null 2>&1
# Ready means everything the desktop checks below read straight away: the map
# and its style and tiles (the water count), every capped row timed (the
# per-origin array has landed and the list was re-ranked), and the departure's
# own label (places.json). body.fatal ends the wait at once -- the page has
# answered, and the fatal check below reports it.
READY_JS='(()=>{if(document.body.classList.contains("fatal"))return true;
  const m=window.__map;
  if(!m||!document.querySelector("#map canvas")||!m.isStyleLoaded()||!m.areTilesLoaded())return false;
  const t=[...document.querySelectorAll(".results button[data-slug] .rowtime")].map(s=>s.textContent.trim());
  return t.length===__ROWS__&&t.every(x=>x!=="")
    &&!!document.querySelector(".lbl.origin[aria-current=\"true\"]")})()'
wait_until 90 "the opening view: map, $ROWS timed rows, departure label" "${READY_JS//__ROWS__/$ROWS}"
echo "=== data-level checks (desktop) ==="
R=$(agent-browser eval '(()=>{const q=s=>document.querySelector(s);return JSON.stringify({
  fatal:document.body.classList.contains("fatal"), where:(q("#where")||{}).textContent.slice(0,160),
  canvas:!!q("#map canvas"), cities:document.querySelectorAll(".results button[data-slug]").length,
  tints:document.querySelectorAll(".tints span, .keys .sw").length, ramps:document.querySelectorAll("#ramps button").length,
  disclaimer:!!q(".disclaimer") && q(".disclaimer").offsetParent !== null,
  originLabel:!!Array.from(document.querySelectorAll(".lbl.origin")).find(b=>b.getAttribute("aria-current")==="true")})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  $R"
# body.fatal is boot.js saying the page could not start, and index.html turns
# it into display:none over the entire side rail. It was checked by nothing.
# Two live defects would have walked past this gate without it: the analytics
# tag blocked by a content blocker (cycle 5, three reviewers), and a
# temporal-dead-zone ReferenceError thrown before the map was created (cycle 5,
# found by opening the page and by nothing else -- `node --check` passes, since
# a TDZ error is valid syntax). CLAUDE.md records that class of failure as
# having blanked this site twice.
# ...and body.fatal being false proves nothing if boot.js never loaded: its
# ABSENCE disarms the blank-page detector and makes the check below pass. Ask
# the server for it before trusting the answer.
if ! curl -sfI "${URL}boot.js" >/dev/null 2>&1; then
  echo "  !! boot.js is not served: the blank-page detector is absent, and the"
  echo "     body.fatal check below would pass for that reason alone."
  fail=1
fi
echo "$R" | grep -q '"fatal":false' || {
  echo "  !! body.fatal is set: boot.js says the page could not start."
  echo "     #where: $(echo "$R" | sed -n 's/.*"where":"\([^"]*\)".*/\1/p')"
  fail=1
}
echo "$R" | grep -q '"canvas":true' || fail=1
echo "$R" | grep -q "\"tints\":$TINTS," || { echo "  !! expected $TINTS legend swatches ($BANDS bands + 2)"; fail=1; }
echo "$R" | grep -q "\"cities\":$ROWS," || { echo "  !! expected $ROWS cities in the list (cap $CAP of $CITIES)"; fail=1; }
# A capped list that does not say so has silently lost the rest. This is the
# check that keeps the cap honest, and it must read the TRUE total -- so it
# fails both if the footer is missing and if it names the wrong number.
if [ "$CITIES" -gt "$CAP" ]; then
  MORE=$(agent-browser eval '(()=>{const el=document.querySelector(".results .listmore");
    return JSON.stringify({present:!!el,text:el?el.textContent.trim().slice(0,120):""})})()' 2>&1 | tail -1 | tr -d '\\')
  echo "  list footer: $MORE"
  echo "$MORE" | grep -q '"present":true' || {
    echo "  !! the list is capped at $CAP of $CITIES and says nothing about the rest"; fail=1; }
  # The count is grouped on the page, so compare against the grouped form.
  # Written without nested quoting: the first version was
  # `python3 -c 'print(f"{int(__import__(\"sys\").argv[1]):,}")'`, whose
  # backslashes the shell ate -- python printed a SyntaxError, GROUPED came
  # back EMPTY, and `grep -q ""` matches anything. The check passed on every
  # page, including one with no footer at all. A gate that cannot fail is the
  # thing CLAUDE.md rates worse than no gate, so this one proves it is not
  # empty before it is used.
  GROUPED=$(python3 -c "print(f'{$CITIES:,}')")
  [ -n "$GROUPED" ] || { echo "  !! could not format the expected total; the footer check would pass vacuously"; fail=1; }
  echo "$MORE" | grep -q "$GROUPED" || {
    echo "  !! the list footer does not name the true total ($GROUPED)"; fail=1; }
fi
# A VISIBLE disclaimer element, not the <noscript> text this used to certify.
echo "$R" | grep -q '"disclaimer":true' || { echo "  !! no visible .disclaimer element"; fail=1; }
echo "$R" | grep -q '"originLabel":true' || { echo "  !! the departure city has no label on the opening view"; fail=1; }
# Every city row answers "how long to X", which the page could not say at all:
# typing a city name and pressing Enter DEPARTS from it. The rows used to end
# in a latitude and a longitude.
CL=$(agent-browser eval '(()=>{const bs=[...document.querySelectorAll(".results button[data-slug]")];
  const t=bs.map(b=>(b.querySelector(".rowtime")||{}).textContent||"");
  const dur=t.filter(x=>/^\d+\s*h|^\d+\s*min/.test(x)).length;
  const coords=t.filter(x=>/^-?\d+\.\d,\s*-?\d+\.\d$/.test(x)).length;
  const clipped=bs.filter(b=>{const s=b.querySelector(".rowtime");return s&&s.scrollWidth>s.clientWidth+1}).length;
  return JSON.stringify({rows:bs.length,durations:dur,coords:coords,clipped:clipped,
   noRoute:t.filter(x=>x==="no route").length,blank:t.filter(x=>x.trim()==="").length,
   departing:t.filter(x=>x==="departing").length})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  city list: $CL"
check_city_list "$CL" || fail=1
echo "$CL" | grep -q '"coords":0,' || { echo "  !! the city list still ends in coordinates"; fail=1; }
echo "$CL" | grep -q '"clipped":0,' || { echo "  !! a travel time is clipped in the city list"; fail=1; }
# Where the rows ARE is a separate question from whether they exist, and the
# page got it wrong twice with nothing to show for it: the list rendered the
# right rows, announced the right count, and scrolled to a position that put
# them off screen. Measure the boxes, do not trust the count.
#   - the current departure must be inside the visible list (offsetTop was
#     measured against .rail, so the scroll overshot by 131-176 px and the list
#     opened on "Shaoguan ... Srinagar");
#   - a filtered list must start at its own top (replaceChildren leaves the old
#     scrollTop, which the browser clamps: typing "lond" put London itself
#     126 px above the box while the visible list began at "STN London
#     Stansted Airport").
VIS=$(agent-browser eval '(()=>{const box=document.getElementById("results");
  const here=box.querySelector("button[aria-current=\"true\"][data-slug]");
  if(!here)return JSON.stringify({err:"no current departure row"});
  const b=box.getBoundingClientRect(),h=here.getBoundingClientRect();
  return JSON.stringify({name:here.textContent.trim().slice(0,24),
    inView:h.top>=b.top-1&&h.bottom<=b.bottom+1,
    above:Math.round(b.top-h.top),scrollTop:Math.round(box.scrollTop),
    parent:(here.offsetParent||{}).id||"(none)"})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  current departure in view: $VIS"
echo "$VIS" | grep -q '"inView":true' || { echo "  !! the current departure is scrolled out of the visible list"; fail=1; }
echo "$VIS" | grep -q '"parent":"results"' || { echo "  !! .results is not the offsetParent the scroll maths assumes"; fail=1; }
agent-browser eval '(()=>{const q=document.getElementById("q");q.value="lond";q.dispatchEvent(new Event("input",{bubbles:true}));return 1})()' >/dev/null 2>&1; sleep 2
FIL=$(agent-browser eval '(()=>{const box=document.getElementById("results");
  const bs=[...box.querySelectorAll("button[data-slug],button[data-code]")];
  const b=box.getBoundingClientRect();
  const shown=bs.filter(x=>{const r=x.getBoundingClientRect();return r.top>=b.top-1&&r.bottom<=b.bottom+1});
  return JSON.stringify({rows:bs.length,scrollTop:Math.round(box.scrollTop),
    firstVisible:(shown[0]||{textContent:""}).textContent.trim().slice(0,28),
    hidden:bs.length-shown.length})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  filtered list: $FIL"
echo "$FIL" | grep -q '"scrollTop":0' || { echo "  !! a filtered list keeps the unfiltered scroll position and hides its own matches"; fail=1; }
agent-browser eval '(()=>{const q=document.getElementById("q");q.value="";q.dispatchEvent(new Event("input",{bubbles:true}));return 1})()' >/dev/null 2>&1; sleep 2
# The coast is a separate static tileset drawn above the bands. A missing or
# empty water.pmtiles shows no console error -- the shore just goes back to
# being hex-shaped -- so ask the map whether water features actually rendered.
W=$(agent-browser eval '(()=>{const m=window.__map;if(!m||!m.getLayer("water"))return "no water layer";
  const n=m.queryRenderedFeatures({layers:["water"]}).length;const b=m.queryRenderedFeatures({layers:["bands"]}).length;
  return JSON.stringify({waterFeatures:n,bandFeatures:b,bandsBelowWater:m.getStyle().layers.findIndex(l=>l.id==="bands")<m.getStyle().layers.findIndex(l=>l.id==="water")})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  $W"
echo "$W" | grep -qE '"waterFeatures":[1-9]' || { echo "  !! water layer rendered nothing"; fail=1; }
echo "$W" | grep -q '"bandsBelowWater":true' || { echo "  !! bands are painted above the coast"; fail=1; }
# Route summary with surface modes. The point is PROJECTED from real
# coordinates, not taken as a fraction of the canvas: a fraction depends on the
# viewport and the framing, and at a phone width the old one landed in the sea.
agent-browser eval '(()=>{const m=window.__map,p=m.project([100,62]);const c=document.querySelector("#map canvas"),r=c.getBoundingClientRect();
  const o={clientX:r.left+p.x,clientY:r.top+p.y,bubbles:true};
  c.dispatchEvent(new MouseEvent("mousedown",o));c.dispatchEvent(new MouseEvent("mouseup",o));c.dispatchEvent(new MouseEvent("click",o));return 1})()' >/dev/null 2>&1
sleep 4
L=$(agent-browser eval 'document.getElementById("legs").innerText.replace(/\n/g," | ")' 2>&1 | tail -1 | tr -d '\\')
echo "  route: ${L:0:220}"
echo "$L" | grep -qiE "by (highway|major road|minor road|rail|ferry|track)" || { echo "  !! no surface mode itemised"; fail=1; }
# airport codes and modes in the route carry explanations; schemes number twelve
T=$(agent-browser eval '(()=>JSON.stringify({ap:document.querySelectorAll("#legs .ap").length,mode:document.querySelectorAll("#legs .mode").length,tip:(document.querySelector("#legs .ap")||{}).dataset?.tip||"",schemes:document.querySelectorAll("#ramps button").length,sky:!!(window.__map.getSky&&window.__map.getSky())}))()' 2>&1 | tail -1 | tr -d '\\')
echo "  tooltips/schemes: ${T:0:200}"
echo "$T" | grep -qE '"ap":[1-9]' && echo "$T" | grep -qE '"mode":[1-9]' || { echo "  !! route lacks airport/mode explanations"; fail=1; }
echo "$T" | grep -q "\"schemes\":$SCHEMES," || { echo "  !! expected $SCHEMES colour schemes"; fail=1; }
# address search reaches Nominatim and lists results. It runs only on an explicit
# search (Enter with no city match, or the button), never per keystroke.
agent-browser eval '(()=>{const q=document.getElementById("q");q.value="Gangnam-daero, Seoul";q.dispatchEvent(new Event("input",{bubbles:true}));q.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",bubbles:true}));return 1})()' >/dev/null 2>&1; sleep 6
A=$(agent-browser eval 'document.querySelectorAll(".results .addresses button[data-geo]").length' 2>&1 | tail -1 | tr -d '\\"')
echo "  address results: $A"
[ "${A:-0}" -ge 1 ] || { echo "  !! address search returned nothing"; fail=1; }
agent-browser eval '(()=>{const q=document.getElementById("q");q.value="";q.dispatchEvent(new Event("input",{bubbles:true}));return 1})()' >/dev/null 2>&1
# click to depart: an origin-city label is a button that switches the tiles.
#
# Polls for the label instead of sleeping 6 s for it. The labels come from
# places.json, 1.8 MB, which now shares the connection with the 10 MB reading
# tier -- the same reason the permalink check stopped sleeping 12 s. When the
# gazetteer had not landed there was no `.lbl.origin` to click, and BOTH
# failures fired: "no origin label was clickable" and, because the source was
# still the first origin's, "clicking an origin label did not change the
# departure". The second message named a defect the page did not have.
#
# The assertion is also no longer "the url stopped saying seoul". It is "the
# url CHANGED from whatever it was", read before the click, so the check does
# not depend on which origin index.json happens to list first -- the same
# hardcoded-geography mistake the phone taps made with [120, 40].
agent-browser eval 'window.__map.jumpTo({center:[135,35],zoom:4.6});1' >/dev/null 2>&1
C=$(agent-browser eval '(()=>{const m=window.__map;
  return new Promise((res)=>{
   const t0=Date.now();
   const poll=setInterval(()=>{
    const all=[...document.querySelectorAll(".lbl.origin")];
    const b=all.find((x)=>x.getAttribute("aria-current")!=="true");
    if(b){ clearInterval(poll);
      const before=m.getSource("bands").url, name=b.textContent.trim();
      b.click();
      const p2=setInterval(()=>{
        const now=m.getSource("bands").url;
        if(now!==before){ clearInterval(p2);
          res(JSON.stringify({clicked:name,labels:all.length,from:before,to:now,
            waitedMs:Date.now()-t0})); }
      },100);
      setTimeout(()=>{ clearInterval(p2);
        res(JSON.stringify({clicked:name,labels:all.length,from:before,
          to:m.getSource("bands").url,unchanged:true}));},8000);
      return; }
    if(Date.now()-t0>25000){ clearInterval(poll);
      res(JSON.stringify({noLabel:true,labels:all.length,
        to:m.getSource("bands").url})); }
   },250);});})()' 2>&1 | tail -1 | tr -d '\\')
echo "  clicked label: $C"
# Three distinct failures, so the output names the one that happened.
echo "$C" | grep -q '"noLabel":true' && { echo "  !! no origin label was clickable within 25 s (the gazetteer never arrived)"; fail=1; }
echo "$C" | grep -q '"unchanged":true' && { echo "  !! clicking an origin label did not change the departure"; fail=1; }
echo "$C" | grep -qE '"to":"pmtiles://\./origins/[a-z0-9-]+\.pmtiles"' || { echo "  !! the bands source is not an origin archive ($C)"; fail=1; }
# low zoom: the coarse level must paint, the coast must be there, and the
# borders layer must have rendered features (a 404 on borders.json or a failed
# addLayer used to pass because the old check looked at the map canvas).
Z=$(agent-browser eval '(()=>{const m=window.__map;m.jumpTo({center:[127,36],zoom:3.4});return 1})()' >/dev/null 2>&1; sleep 7; agent-browser eval '(()=>{const m=window.__map;return JSON.stringify({z:m.getZoom(),bands:m.queryRenderedFeatures({layers:["bands"]}).length,water:m.queryRenderedFeatures({layers:["water"]}).length,borders:!!m.getLayer("borders")&&m.queryRenderedFeatures({layers:["borders"]}).length})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  zoom 3: $Z"
echo "$Z" | grep -qE '"bands":[1-9]' && echo "$Z" | grep -qE '"water":[1-9]' || { echo "  !! nothing painted at zoom 3"; fail=1; }
echo "$Z" | grep -qE '"borders":[1-9]' || { echo "  !! the borders layer rendered nothing"; fail=1; }
agent-browser screenshot "$SHOTS/verify_zoom3.png" >/dev/null 2>&1
# A permalink selects its departure AND restores the destination -- and now
# the colours, the camera and the settings too, so a pasted link shows what
# the sharer was looking at rather than the reader's own defaults.
#
# The address is PARSED here, not pattern-matched. This check used to assert
# the literal prefix `?from=tokyo&to=`, which is a claim about parameter ORDER
# that nothing guarantees and that nothing about the page's behaviour depends
# on: the moment a third parameter was written between the two, a page whose
# address carried the destination correctly failed a check about whether the
# address carried the destination. Same lesson as the RAMPS count above --
# parse the thing, do not grep it.
agent-browser open "${URL}?from=tokyo&to=62.00243,99.78787&scheme=ember&sea=teal&north=1&at=62.00243,99.78787,4.20" >/dev/null 2>&1; sleep 6
# Poll for the page to have applied the link rather than sleeping a fixed time.
# The fixed 12 s was chosen when an origin was a 181 KB array; it now also
# fetches a ~10 MB resolution-6 reading tier, and the sleep silently became too
# short -- every one of the eight assertions below failed against a live page
# that was demonstrably correct a few seconds later. A gate that fails on
# correct code teaches people to ignore it.
for _ in $(seq 1 20); do
  READY=$(agent-browser eval '(()=>{const n=document.getElementById("origin-name");
    return !!(n && n.textContent && n.textContent.trim() && document.querySelector("#legs .leg.total"))})()' 2>&1 | tail -1 | tr -d '\\"')
  [ "$READY" = "true" ] && break
  sleep 1
done
P=$(agent-browser eval '(()=>{const q=new URLSearchParams(location.search);
  const o={};for(const [k,v] of q) o[k]=v;
  return JSON.stringify({from:document.getElementById("origin-name").textContent,
  time:document.getElementById("time").innerText.replace(/\n/g," "),
  pinned:!!document.querySelector("#legs .leg.total"),
  params:o,
  ramp:[...document.querySelectorAll("#ramps button")].filter(b=>b.getAttribute("aria-current")==="true").map(b=>b.dataset.ramp).join(""),
  ocean:[...document.querySelectorAll("#oceans button")].filter(b=>b.getAttribute("aria-current")==="true").map(b=>b.dataset.ocean).join(""),
  north:document.getElementById("lock-north").checked})})()' 2>&1 | tail -1 | tr -d '\')
echo "  permalink: $P"
echo "$P" | grep -q '"from":"Tokyo"' || { echo "  !! ?from=tokyo did not select Tokyo"; fail=1; }
echo "$P" | grep -q '"pinned":true' || { echo "  !! ?to= did not restore the destination"; fail=1; }
echo "$P" | grep -qE '"time":"[0-9]' || { echo "  !! ?to= restored no reading"; fail=1; }
echo "$P" | grep -q '"to":"62.00243,99.78787"' || { echo "  !! the address bar dropped the destination"; fail=1; }
echo "$P" | grep -q '"from":"tokyo"' || { echo "  !! the address bar dropped the departure"; fail=1; }
# The rest of the state a pasted link is meant to carry. Each is checked at
# BOTH ends: the page applied it, and the address still says so.
echo "$P" | grep -q '"ramp":"ember"' || { echo "  !! ?scheme= did not apply the colour scheme"; fail=1; }
echo "$P" | grep -q '"ocean":"teal"' || { echo "  !! ?sea= did not apply the ocean colour"; fail=1; }
echo "$P" | grep -q '"north":true' || { echo "  !! ?north= did not apply"; fail=1; }
echo "$P" | grep -q '"scheme":"ember"' || { echo "  !! the address bar dropped the colour scheme"; fail=1; }
echo "$P" | grep -q '"sea":"teal"' || { echo "  !! the address bar dropped the ocean colour"; fail=1; }
echo "$P" | grep -qE '"at":"[-0-9]' || { echo "  !! the address bar dropped the camera"; fail=1; }
# ...and a slug that does not exist must SAY so, not be silently swallowed and
# then written out of the address bar as though the link had worked.
agent-browser open "${URL}?from=atlantis" >/dev/null 2>&1
# Poll instead of reading once after a fixed sleep. #here is written at module
# scope right after paintOrigin, but that is downstream of index.json -- now
# 553 origins, not 157 -- and of app.js parsing, so on a cold cache a single
# read at t+10s caught the page before the message landed and reported a
# defect that two independent reproductions afterwards could not confirm.
# Same ceiling, but it stops as soon as the answer is there.
B=""
for _ in $(seq 1 20); do
  sleep 1
  B=$(agent-browser eval 'document.getElementById("here").textContent' 2>&1 | tail -1)
  case "$B" in *[Nn]"o departure city called"*) break;; esac
done
echo "  ?from=atlantis -> $B"
echo "$B" | grep -qi "no departure city called" || { echo "  !! an unknown ?from= slug is swallowed silently"; fail=1; }
agent-browser open "${URL}?from=tokyo" >/dev/null 2>&1
# The JFK search below reads Tokyo's own travel times, so ready is Tokyo
# selected with its array landed (every row timed), not merely the page up.
TOKYO_JS='(()=>{if(document.body.classList.contains("fatal"))return true;
  const n=document.getElementById("origin-name"),m=window.__map;
  if(!m||!m.isStyleLoaded()||!n||n.textContent.trim()!=="Tokyo")return false;
  const t=[...document.querySelectorAll(".results button[data-slug] .rowtime")].map(s=>s.textContent.trim());
  return t.length>0&&t.every(x=>x!=="")})()'
wait_until 90 "?from=tokyo: Tokyo selected and its times landed" "$TOKYO_JS"
echo "=== a searched destination writes the answer, not only the itinerary ==="
# The two search branches used to call renderPins()+renderLegs() and nothing
# else, so the 50px headline kept the PREVIOUS destination's time above an
# itinerary describing the new one. The check is that the two agree.
# Typing and clicking are TWO steps, with a frame between them. render() is
# coalesced to one animation frame now -- a keystroke rebuilds up to 1,464
# rows -- so reading `.results` in the same tick as the input event finds the
# list built for the PREVIOUS query. This check did exactly that and reported
# a defect on a page that was correct: the airport row did not exist yet, the
# click never happened, and the total row it then looked for was absent for
# that reason rather than because the headline disagreed with anything.
#
# The gate was wrong here, not the page: no human types and clicks inside one
# frame, and the two paths that CAN act within one -- Enter and ArrowDown --
# flush the pending render themselves. The assertion below is unchanged.
agent-browser eval '(()=>{const q=document.getElementById("q");q.value="JFK";q.dispatchEvent(new Event("input",{bubbles:true}));return 1})()' >/dev/null 2>&1; sleep 2
agent-browser eval '(()=>{const b=document.querySelector(".results button[data-airport]");if(!b)return 0;b.click();return 1})()' >/dev/null 2>&1; sleep 4
# The total is found by its CLASS, not by counting lines from the end. It was
# `l[l.length-2]`, which assumed the last two lines of #legs were the total's
# time and its label -- so appending anything after the itinerary shifted the
# read by one and the check failed on a page that was correct. It did exactly
# that when the journey-line key landed. A positional read of rendered text is
# the same fragility that produced two false failures in cycle 5.
S=$(agent-browser eval '(()=>{const t=document.querySelector("#legs .leg.total .t");
  const norm=x=>String(x).replace(/\s+/g,"").replace(/min$/,"");
  const head=document.getElementById("time").innerText;
  return JSON.stringify({head:head.replace(/\n/g," "),
   total:t?t.textContent:"(no total row)",agree:!!t&&norm(head)===norm(t.textContent),
   announced:/door to door/.test(document.getElementById("status").textContent)
    && /JFK/.test(document.getElementById("status").textContent)})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  $S"
echo "$S" | grep -q '"agree":true' || { echo "  !! the headline and the itinerary total disagree after a search"; fail=1; }
echo "$S" | grep -q '"announced":true' || { echo "  !! a searched destination is not announced"; fail=1; }
agent-browser eval '(()=>{const q=document.getElementById("q");q.value="";q.dispatchEvent(new Event("input",{bubbles:true}));return 1})()' >/dev/null 2>&1
echo "=== globe labels carry their own names ==="
# Marker.addTo() re-applies role="button" aria-label="Map marker" behind
# hasAttribute guards, so removing them at construction was a no-op: every
# plain label announced as a button that does nothing (WCAG 4.1.2).
agent-browser eval 'window.__map.jumpTo({center:[127,36],zoom:5.2});1' >/dev/null 2>&1; sleep 4
N=$(agent-browser eval '(()=>{const ls=[...document.querySelectorAll(".lbl")];
  return JSON.stringify({labels:ls.length,mapMarker:ls.filter(e=>e.getAttribute("aria-label")==="Map marker").length,
   origin:(document.querySelector(".lbl.origin")||{}).getAttribute?.("aria-label")||""})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  $N"
echo "$N" | grep -q '"mapMarker":0' || { echo "  !! globe labels are announced as \"Map marker\""; fail=1; }
echo "$N" | grep -qE '"origin":"[A-Za-z].*departure city"' || { echo "  !! the departure label does not say its own name"; fail=1; }
echo "=== console ==="
# The old check was `agent-browser console 2>/dev/null | grep -ciE ...`, so a
# dead session, a crashed tab or a CDP disconnect gave empty stdout, grep -ci on
# empty input printed 0, and the gate reported "errors: 0" without having read
# the console at all.
#
# Emptiness alone cannot tell the two apart, and neither can the exit status:
# `agent-browser console` with NO SESSION exits 0 and prints nothing, which is
# byte-identical to a clean console. Measured, after a first attempt at this
# fix turned the silent pass into a false failure on a page whose console was
# simply clean.
#
# So prove the session is answering FIRST, with an eval whose value we know.
# After that a silent console is a clean console, which is the whole point.
# The probe must be tied to THE PAGE UNDER TEST, not merely to the tool
# answering: `agent-browser eval` returns a literal, and even `location.href`,
# on a session sitting at about:blank. Asking the live page for its own URL and
# its own canvas is the only read that cannot succeed on a dead or navigated-away
# tab, which is exactly the state that made a silent console look clean.
LIVE=$(agent-browser eval '(()=>{try{return location.href+"|"+!!document.querySelector("#map canvas")}catch(e){return "throw:"+e.message}})()' 2>&1 | tail -1 | tr -d '\"')
case "$LIVE" in
  "$URL"*"|true"|"${URL%/}"*"|true") ;;
  *) echo "  !! the page under test is not answering ($LIVE); the console read below proves nothing"
     fail=1 ;;
esac
CONSOLE=$(agent-browser console 2>&1 || true)
E=$(printf '%s' "$CONSOLE" | grep -ciE "error|exception" || true)
echo "  errors: $E"; [ "$E" -eq 0 ] || fail=1
echo "=== viewports ==="
# With a route OPEN: .depart-card and .reading only collide once an itinerary
# is on screen, so checking the viewports on an unpinned page cannot see it.
agent-browser eval '(()=>{const m=window.__map,p=m.project([100,62]);const c=document.querySelector("#map canvas"),r=c.getBoundingClientRect();
  const o={clientX:r.left+p.x,clientY:r.top+p.y,bubbles:true};
  c.dispatchEvent(new MouseEvent("mousedown",o));c.dispatchEvent(new MouseEvent("mouseup",o));c.dispatchEvent(new MouseEvent("click",o));return 1})()' >/dev/null 2>&1; sleep 3
# `time` is measured against the viewport box, not offsetParent: offsetParent
# stays truthy for an element scrolled out of its container, which is exactly
# how a tap could push the answer off a phone and pass this check.
# `scale` is the hour ticks; T3 promised a check for them and none was written,
# so the four-viewport pass measured the band strip and never its labels.
# `cardOverlap` is only meaningful on the desktop layout, where .depart-card (a
# child of the fixed .topleft column) and .reading (position:fixed) share the
# same 306px column; in the rail they
# are stacked and share a boundary, which is not an overlap.
# It also compares the card against the MASTHEAD, which nothing did: the card
# was pinned at a hardcoded top:104px while the masthead height follows its own
# text, and they overlapped by 1,722 px on the live desktop layout while every
# gate passed.
CHECK='(()=>{const b=document.body,d=document.documentElement;const q=s=>document.querySelector(s).getBoundingClientRect();
 const rr=q(".reading"),rl=q(".rail"),ms=q(".mast"),cp=q("#compass"),lg=q("#tints"),sc=q("#scale");
 const ov=(a,c)=>!(a.right<c.left-1||c.right<a.left-1||a.bottom<c.top-1||c.bottom<a.top-1);
 const onScreen=x=>x.top>=-1&&x.bottom<=innerHeight+1&&x.width>10;
 const card=document.querySelector(".depart-card");
 const cardFixed=card&&!card.closest(".rail")&&!card.hidden&&getComputedStyle(card).display!=="none";
 return JSON.stringify({vw:innerWidth,vh:innerHeight,canvas:!!document.querySelector("#map canvas"),hScroll:Math.max(b.scrollWidth,d.scrollWidth)>innerWidth+1,
  overlap:ov(ms,cp)||ov(ms,rl)||ov(cp,rl),cardOverlap:!!(cardFixed&&(ov(card.getBoundingClientRect(),rr)||ov(ms,card.getBoundingClientRect()))),
  time:onScreen(q("#time")),legend:onScreen(lg)&&lg.width>40,scale:onScreen(sc)})})()'
for spec in "1280 800 desktop" "820 1180 tablet" "390 844 mobile" "844 390 landscape"; do
  w=${spec%% *}; rest=${spec#* }; h=${rest%% *}; name=${rest#* }
  agent-browser set viewport $w $h >/dev/null 2>&1; sleep 3
  V=$(agent-browser eval "$CHECK" 2>&1 | tail -1 | tr -d '\\'); echo "  $name: $V"
  echo "$V" | grep -q '"canvas":true' && echo "$V" | grep -q '"hScroll":false' && echo "$V" | grep -q '"overlap":false' && echo "$V" | grep -q '"time":true' && echo "$V" | grep -q '"legend":true' || fail=1
  echo "$V" | grep -q '"scale":true' || { echo "  !! the legend's hour ticks are off screen at $name"; fail=1; }
  echo "$V" | grep -q '"cardOverlap":false' || { echo "  !! the departure card and the reading overlap at $name"; fail=1; }
  agent-browser screenshot "$SHOTS/verify_$name.png" >/dev/null 2>&1
done
# Back to desktop after visiting a phone width. The grab handle is created on
# first entry into the small layout and had no display rule outside the phone
# media query, so it survived as UA chrome with a live tab stop and a click
# that toggled a class with no desktop rules. The loop above never returns to
# a wide viewport, so this is its own step.
agent-browser set viewport 1280 800 >/dev/null 2>&1; sleep 2
H=$(agent-browser eval '(()=>{const t=document.getElementById("sheet-toggle");if(!t)return JSON.stringify({display:"absent"});
  return JSON.stringify({display:getComputedStyle(t).display,h:Math.round(t.getBoundingClientRect().height)})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  desktop after a phone width: $H"
echo "$H" | grep -qE '"display":"(none|absent)"' || { echo "  !! the bottom-sheet handle survived the return to desktop"; fail=1; }

# ...and the FULL check here too, not only the handle probe. Coming back UP
# through the breakpoint is a different code path from loading wide: the
# layout switch moves .depart-card and .reading out of the rail, and it put
# the card into <body> as a static block at (0,0) under the masthead --
# 25,912 px of overlap, with the h1 winning elementFromPoint over the
# departure city's button. The loop above never returns to a wide viewport,
# so every gate passed for as long as the defect existed. Two of the four
# viewports CLAUDE.md's deploy rule names sit on opposite sides of 860 px.
R=$(agent-browser eval "$CHECK" 2>&1 | tail -1 | tr -d '\\')
echo "  desktop after a phone width, full check: $R"
echo "$R" | grep -q '"cardOverlap":false' || { echo "  !! the departure card overlaps the masthead or the reading after returning to desktop"; fail=1; }
echo "$R" | grep -q '"overlap":false' || { echo "  !! chrome overlaps after returning to desktop"; fail=1; }
echo "$R" | grep -q '"hScroll":false' || { echo "  !! the page scrolls horizontally after returning to desktop"; fail=1; }
echo "$R" | grep -q '"time":true' || { echo "  !! the reading is off screen after returning to desktop"; fail=1; }
echo "$R" | grep -q '"legend":true' || { echo "  !! the legend is off screen after returning to desktop"; fail=1; }

# The card's PARENT, which the box check alone cannot see: a card correctly
# positioned by accident is still one stylesheet change from (0,0).
PAR=$(agent-browser eval '(()=>{const c=document.querySelector(".depart-card");
  return JSON.stringify({parent:c?c.parentElement.className||c.parentElement.tagName:"absent"})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  departure card parent after returning to desktop: $PAR"
echo "$PAR" | grep -q '"parent":"topleft"' || { echo "  !! the departure card did not return to the .topleft column"; fail=1; }

# Phones: a TAP must leave the answer and the whole legend on screen. Opening
# the Route panel used to scroll the rail (measured scrollTop 297 at 390x844),
# taking #time, #tints and #scale with it -- against CLAUDE.md's standing rule
# that the legend is always visible.
#
# This tapped a hardcoded [120, 40] too, and so it never scrolled anything:
# that point has no journey, setDestination returns before openRoutePanel, and
# the check went green because the thing it exists to detect could not happen.
# tap_js below picks a point that actually reads.
agent-browser set viewport 390 844 >/dev/null 2>&1; sleep 2
S2=$(agent-browser eval "$(tap_js "$OLON" "$OLAT" '{scrollTop:Math.round(document.querySelector(".rail").scrollTop),
   time:on("#time"),tints:on("#tints"),scale:on("#scale"),
   reading:document.getElementById("time").innerText.trim()}')" 2>&1 | tail -1 | tr -d '\\')
echo "  tap on a phone: $S2"
echo "$S2" | grep -q '"picked":true' || { echo "  !! found no point near the departure city that reads a time, so the scroll check proves nothing"; fail=1; }
echo "$S2" | grep -q '"time":true' && echo "$S2" | grep -q '"tints":true' && echo "$S2" | grep -q '"scale":true' \
  || { echo "  !! a tap scrolled the answer or the legend out of the sheet"; fail=1; }

# Phones: with the sheet FOLDED the legend must still be on screen (CLAUDE.md:
# the legend is always visible). Measured WITHOUT tapping -- a tap unfolds the
# sheet on purpose, so the old single check asserted two states at once and
# could never pass both: it went green on the caption only when the tap had
# landed in the sea and written no reading.
agent-browser set viewport 390 844 >/dev/null 2>&1; sleep 2
FOLD=$(agent-browser eval '(()=>{const t=document.getElementById("sheet-toggle");if(!t)return "no toggle";
  if(!document.querySelector(".rail").classList.contains("folded"))t.click();
  return new Promise(res=>setTimeout(()=>{const box=s=>document.querySelector(s).getBoundingClientRect();
   const on=b=>b.width>20&&b.top>=0&&b.bottom<=innerHeight;
   res(JSON.stringify({folded:document.querySelector(".rail").classList.contains("folded"),
    legendOnScreen:on(box("#tints")),keysOnScreen:on(box("#keys")),capOnScreen:on(box(".legend-cap")),
    scaleOnScreen:on(box("#scale"))}))},800))})()' 2>&1 | tail -1 | tr -d '\\')
echo "  folded sheet: $FOLD"
echo "$FOLD" | grep -q '"folded":true' || { echo "  !! the sheet did not fold"; fail=1; }
echo "$FOLD" | grep -q '"legendOnScreen":true' || { echo "  !! the legend is hidden while the sheet is folded"; fail=1; }
# The band strip alone is not the legend: without the two keys the grey and the
# sea colour have no meaning, and without the caption the figures lose the
# door-to-door qualifier the modelling rule requires. The swatch COUNT cannot
# catch this -- display:none leaves the nodes in the DOM.
echo "$FOLD" | grep -q '"keysOnScreen":true' || { echo "  !! the two legend keys are hidden while the sheet is folded"; fail=1; }
echo "$FOLD" | grep -q '"capOnScreen":true' || { echo "  !! the door-to-door caption is hidden while the sheet is folded"; fail=1; }
echo "$FOLD" | grep -q '"scaleOnScreen":true' || { echo "  !! the hour ticks are hidden while the sheet is folded"; fail=1; }
# ...and a tap from the folded state must write the reading, unfold the sheet
# and leave the number it just produced on screen. See tap_js above for why the
# point is chosen rather than hardcoded.
TAP=$(agent-browser eval "$(tap_js "$OLON" "$OLAT" '{folded:document.querySelector(".rail").classList.contains("folded"),
   time:document.getElementById("time").textContent.trim(),
   announced:/door to door/.test(document.getElementById("status").textContent),
   timeOnScreen:on("#time"),legendOnScreen:on("#tints")}')" 2>&1 | tail -1 | tr -d '\\')
echo "  tap from folded: $TAP"
# Reported first: without it, "no tappable point near the departure city" and
# "the tap was ignored" are the same output.
echo "$TAP" | grep -q '"picked":true' || { echo "  !! found no point near the departure city where the canvas is on top and reads a time"; fail=1; }
echo "$TAP" | grep -qE '"time":"[0-9]' || { echo "  !! a tap did not write the reading"; fail=1; }
# The comment above this block has always said the sheet must come back, and
# nothing checked it. unfoldSheet() sits after an early return in
# setDestination, so this is the assertion that notices when a tap stops
# reaching it.
echo "$TAP" | grep -q '"folded":false' || { echo "  !! a tap left the sheet folded, so the reading it wrote is behind it"; fail=1; }
# A hover already writes #time, so "time is a number" alone does NOT prove the
# CLICK did anything. The live region is written only on a committed reading.
# Matched on "door to door" and not on "from": the IDLE status is "Travel times
# from Tokyo are ready...", which contains "from", so that regex reported a
# committed reading on a page that had committed nothing. Caught by rehearsing
# this check against the sea point it used to tap.
echo "$TAP" | grep -q '"announced":true' || { echo "  !! a tap wrote no reading to the live region, so the click committed nothing"; fail=1; }
echo "$TAP" | grep -q '"timeOnScreen":true' || { echo "  !! the reading a tap produced is off screen"; fail=1; }
echo "$TAP" | grep -q '"legendOnScreen":true' || { echo "  !! the legend went off screen after a tap"; fail=1; }

# Phones and tablets: OPENING THE DEPARTURE PANEL must not take the legend with
# it. CLAUDE.md: "The legend is always visible."
#
# The rail's toggle handler brings a panel that just opened into the scrolling
# sheet, and scrollIntoView({block:"nearest"}) on an element TALLER than the
# sheet aligns its bottom -- so one tap on "Departure", the one panel you must
# open to use the site, scrolled .legend from 138.5 visible pixels to 0 at
# 844x390, 202.1 to 0 at 390x844 and 174.2 to 0 at 820x1180. The same failure
# is capped for .legs and suppressed for #route; #departure had neither guard
# and nothing measured it, which is why it shipped.
#
# Measured before AND after the click rather than "is it on screen now": at
# 844x390 the strip is only ~5 px tall and already sits at the edge of the
# sheet, so an absolute assertion would be about the resting layout rather than
# about what the click did.
for spec in "844 390 landscape" "390 844 mobile" "820 1180 tablet"; do
  w=${spec%% *}; rest=${spec#* }; h=${rest%% *}; name=${rest#* }
  agent-browser set viewport $w $h >/dev/null 2>&1; sleep 2
  OPENED=$(agent-browser eval '(()=>{const d=document.getElementById("departure");
    const rail=document.querySelector(".rail");
    if(!rail||!d.closest(".rail"))return JSON.stringify({skip:"rail is not the scrolling sheet"});
    const vis=s=>{const e=document.querySelector(s);if(!e)return -1;
      const b=e.getBoundingClientRect(),v=rail.getBoundingClientRect();
      return Math.round(Math.max(0,Math.min(b.bottom,v.bottom)-Math.max(b.top,v.top)))};
    d.open=false;
    return new Promise(res=>setTimeout(()=>{
      const was={legend:vis(".legend"),tints:vis("#tints"),top:Math.round(rail.scrollTop)};
      d.querySelector("summary").click();
      setTimeout(()=>res(JSON.stringify({was,now:{legend:vis(".legend"),tints:vis("#tints"),
        top:Math.round(rail.scrollTop)},open:d.open})),900);},300))})()' 2>&1 | tail -1 | tr -d '\\')
  echo "  opening Departure at $name: $OPENED"
  case "$OPENED" in *'"skip"'*) continue;; esac
  echo "$OPENED" | grep -q '"open":true' || { echo "  !! the Departure panel did not open at $name, so this check proves nothing"; fail=1; continue; }
  # The panel really is taller than the sheet at these widths; if it stops
  # being so the check is no longer exercising the failure it guards.
  python3 - "$OPENED" <<'PYCHK' || fail=1
import json, sys
# agent-browser returns the page's JSON *string* wrapped in quotes, and the
# caller's `tr -d '\\'` has already removed the escapes, so what arrives is
# `"{"was":...}"`. json.loads stops at char 3 on that. Strip one layer of
# quoting before parsing; parse unquoted input unchanged.
raw = sys.argv[1].strip()
if len(raw) > 1 and raw[0] == '"' and raw[-1] == '"':
    raw = raw[1:-1]
d = json.loads(raw)
was, now = d["was"], d["now"]
ok = True
if was["legend"] <= 0:
    print(f"  !! the legend was already off screen BEFORE opening Departure "
          f"({was}); this check cannot see a regression")
    ok = False
if now["legend"] < was["legend"]:
    print(f"  !! opening Departure cut the legend from {was['legend']} px to "
          f"{now['legend']} px -- CLAUDE.md: the legend is always visible")
    ok = False
if now["tints"] < was["tints"]:
    print(f"  !! opening Departure cut the band strip from {was['tints']} px "
          f"to {now['tints']} px")
    ok = False
sys.exit(0 if ok else 1)
PYCHK
done
agent-browser set viewport 1280 800 >/dev/null 2>&1; sleep 2
# Last, deliberately: this fires two real map errors through the map's own
# error channel, and app.js console.errors each one. Run before the console
# check above and the probe fails the gate with the errors it exists to
# cause -- which it did on its first outing.
echo "=== the notice that explains a blank globe ==="
# The notice that explains a blank globe has to be reachable by the errors that
# actually cause one. It was not: the handler tested the message text against
# /pmtiles|tile|source/i, and pmtiles.js emits none of those words -- its real
# failures read "Bad response code: 404" and "archive does not appear to support
# HTTP Byte Serving". Withholding the archives from a local copy of the real
# dist/ measured bandsRendered:0, waterRendered:0 and #tiletrouble still hidden.
# The old guard passed review because its check fired a synthetic error carrying
# the literal string "pmtiles".
#
# Fire the two REAL messages through the map's own error channel, with the
# sourceId MapLibre attaches, and require the notice to appear and to name the
# right layer. The page is reopened immediately after, which clears it.
TT=$(agent-browser eval '(()=>{const m=window.__map,el=document.getElementById("tiletrouble");
  const fire=(sourceId,message)=>{m.fire("error",{error:new Error(message),sourceId:sourceId});
    return {hidden:el.hidden,text:el.textContent.slice(0,60)};};
  const bands=fire("bands","Bad response code: 404");
  el.hidden=true;el.textContent="";
  const water=fire("water","archive does not appear to support HTTP Byte Serving");
  return JSON.stringify({bands:bands,water:water})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  tile-failure notice: $TT"
echo "$TT" | grep -q '"bands":{"hidden":false' || { echo "  !! a real band-tile failure shows no notice: a blank globe would be silent"; fail=1; }
echo "$TT" | grep -q '"water":{"hidden":false' || { echo "  !! a real coastline failure shows no notice"; fail=1; }
echo "$TT" | grep -q 'The shaded bands could not be loaded' || { echo "  !! the band-tile notice names the wrong layer"; fail=1; }
echo "$TT" | grep -q 'The coastline could not be loaded' || { echo "  !! the coastline notice names the wrong layer"; fail=1; }
agent-browser close >/dev/null 2>&1; sleep 1
# Kill only the browser processes this run started (agent-browser's own
# Chrome tree under ~/.agent-browser/), never the user's Google Chrome and
# never another session's daemon.
AFTER=$(/bin/ps -ax -o pid=,command= | grep -E "\.agent-browser/" | grep -v grep | awk '{print $1}' | sort)
comm -13 <(echo "$BEFORE") <(echo "$AFTER") | while read -r p; do [ -n "$p" ] && kill -9 "$p" 2>/dev/null; done; sleep 1
left=$(/bin/ps -ax -o command= | grep -E "\.agent-browser/" | grep -vc grep)
echo "=== cleanup ===  agent-browser processes left: $left (started by this run: $(comm -13 <(echo "$BEFORE") <(echo "$AFTER") | grep -c . || true))  |  Google Chrome untouched: $(/bin/ps -ax -o command= | grep -c '[G]oogle Chrome.app')"
echo; [ $fail -eq 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit $fail

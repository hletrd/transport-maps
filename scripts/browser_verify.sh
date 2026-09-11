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
echo "expecting $CITIES cities, $BANDS bands ($TINTS swatches) from index.json; $SCHEMES schemes; screenshots in $SHOTS"
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
agent-browser open "$URL" >/dev/null 2>&1; sleep 15
fail=0
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
echo "$R" | grep -q "\"cities\":$CITIES," || { echo "  !! expected $CITIES cities in the list"; fail=1; }
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
   departing:t.filter(x=>x==="departing").length})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  city list: $CL"
echo "$CL" | grep -qE '"durations":[1-9][0-9]' || { echo "  !! the city list carries no travel times"; fail=1; }
echo "$CL" | grep -q '"coords":0' || { echo "  !! the city list still ends in coordinates"; fail=1; }
echo "$CL" | grep -q '"clipped":0' || { echo "  !! a travel time is clipped in the city list"; fail=1; }
echo "$CL" | grep -q '"departing":1' || { echo "  !! the current departure is not marked in the list"; fail=1; }
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
# click to depart: an origin-city label is a button that switches the tiles
agent-browser eval 'window.__map.jumpTo({center:[135,35],zoom:4.6});1' >/dev/null 2>&1; sleep 6
C=$(agent-browser eval '(()=>{const b=Array.from(document.querySelectorAll(".lbl.origin")).find(x=>x.getAttribute("aria-current")!=="true");if(!b)return "no origin label";const n=b.textContent;b.click();return n})()' 2>&1 | tail -1 | tr -d '\\"')
sleep 5
SRC=$(agent-browser eval 'window.__map.getSource("bands").url' 2>&1 | tail -1 | tr -d '\\"')
echo "  clicked label: $C -> $SRC"
echo "$SRC" | grep -q "origins/seoul.pmtiles" && { echo "  !! clicking an origin label did not change the departure"; fail=1; }
# low zoom: the coarse level must paint, the coast must be there, and the
# borders layer must have rendered features (a 404 on borders.json or a failed
# addLayer used to pass because the old check looked at the map canvas).
Z=$(agent-browser eval '(()=>{const m=window.__map;m.jumpTo({center:[127,36],zoom:3.4});return 1})()' >/dev/null 2>&1; sleep 7; agent-browser eval '(()=>{const m=window.__map;return JSON.stringify({z:m.getZoom(),bands:m.queryRenderedFeatures({layers:["bands"]}).length,water:m.queryRenderedFeatures({layers:["water"]}).length,borders:!!m.getLayer("borders")&&m.queryRenderedFeatures({layers:["borders"]}).length})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  zoom 3: $Z"
echo "$Z" | grep -qE '"bands":[1-9]' && echo "$Z" | grep -qE '"water":[1-9]' || { echo "  !! nothing painted at zoom 3"; fail=1; }
echo "$Z" | grep -qE '"borders":[1-9]' || { echo "  !! the borders layer rendered nothing"; fail=1; }
agent-browser screenshot "$SHOTS/verify_zoom3.png" >/dev/null 2>&1
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
# A permalink selects its departure AND restores the destination. ?from=
# carried the departure and nothing else, so the interesting half of a reading
# could not be shared: the link reopened the city, not the journey.
agent-browser open "${URL}?from=tokyo&to=62.00243,99.78787" >/dev/null 2>&1; sleep 12
P=$(agent-browser eval '(()=>JSON.stringify({from:document.getElementById("origin-name").textContent,
  time:document.getElementById("time").innerText.replace(/\n/g," "),
  pinned:!!document.querySelector("#legs .leg.total"),search:location.search}))()' 2>&1 | tail -1 | tr -d '\')
echo "  permalink: $P"
echo "$P" | grep -q '"from":"Tokyo"' || { echo "  !! ?from=tokyo did not select Tokyo"; fail=1; }
echo "$P" | grep -q '"pinned":true' || { echo "  !! ?to= did not restore the destination"; fail=1; }
echo "$P" | grep -qE '"time":"[0-9]' || { echo "  !! ?to= restored no reading"; fail=1; }
echo "$P" | grep -q '"search":"?from=tokyo&to=' || { echo "  !! the address bar dropped the destination"; fail=1; }
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
agent-browser open "${URL}?from=tokyo" >/dev/null 2>&1; sleep 10
echo "=== a searched destination writes the answer, not only the itinerary ==="
# The two search branches used to call renderPins()+renderLegs() and nothing
# else, so the 50px headline kept the PREVIOUS destination's time above an
# itinerary describing the new one. The check is that the two agree.
agent-browser eval '(()=>{const q=document.getElementById("q");q.value="JFK";q.dispatchEvent(new Event("input",{bubbles:true}));
  const b=document.querySelector(".results button[data-airport]");if(!b)return 0;b.click();return 1})()' >/dev/null 2>&1; sleep 4
S=$(agent-browser eval '(()=>{const l=document.getElementById("legs").innerText.split("\n").filter(Boolean);
  const norm=t=>t.replace(/\s+/g,"").replace(/min$/,"");
  return JSON.stringify({head:document.getElementById("time").innerText.replace(/\n/g," "),
   total:(l[l.length-2]||""),agree:norm(document.getElementById("time").innerText)===norm(l[l.length-2]||"x"),
   announced:/JFK/.test(document.getElementById("status").textContent)})})()' 2>&1 | tail -1 | tr -d '\\')
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
echo "=== console ==="; E=$(agent-browser console 2>/dev/null | grep -ciE "error|exception"); echo "  errors: $E"; [ "$E" -eq 0 ] || fail=1
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
# `cardOverlap` is only meaningful on the desktop layout, where .depart-card and
# .reading are both position:fixed in the same 306px column; in the rail they
# are stacked and share a boundary, which is not an overlap.
CHECK='(()=>{const b=document.body,d=document.documentElement;const q=s=>document.querySelector(s).getBoundingClientRect();
 const rr=q(".reading"),rl=q(".rail"),ms=q(".mast"),cp=q("#compass"),lg=q("#tints"),sc=q("#scale");
 const ov=(a,c)=>!(a.right<c.left-1||c.right<a.left-1||a.bottom<c.top-1||c.bottom<a.top-1);
 const onScreen=x=>x.top>=-1&&x.bottom<=innerHeight+1&&x.width>10;
 const card=document.querySelector(".depart-card");
 const cardFixed=card&&!card.closest(".rail")&&!card.hidden&&getComputedStyle(card).display!=="none";
 return JSON.stringify({vw:innerWidth,vh:innerHeight,canvas:!!document.querySelector("#map canvas"),hScroll:Math.max(b.scrollWidth,d.scrollWidth)>innerWidth+1,
  overlap:ov(ms,cp)||ov(ms,rl)||ov(cp,rl),cardOverlap:!!(cardFixed&&ov(card.getBoundingClientRect(),rr)),
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

# Phones: a TAP must leave the answer and the whole legend on screen. Opening
# the Route panel used to scroll the rail (measured scrollTop 297 at 390x844),
# taking #time, #tints and #scale with it -- against CLAUDE.md's standing rule
# that the legend is always visible.
agent-browser set viewport 390 844 >/dev/null 2>&1; sleep 2
agent-browser eval '(()=>{const m=window.__map,p=m.project([120,40]);const c=document.querySelector("#map canvas"),r=c.getBoundingClientRect();
  const o={clientX:r.left+p.x,clientY:r.top+p.y,bubbles:true};
  c.dispatchEvent(new MouseEvent("mousedown",o));c.dispatchEvent(new MouseEvent("mouseup",o));c.dispatchEvent(new MouseEvent("click",o));return 1})()' >/dev/null 2>&1; sleep 3
S2=$(agent-browser eval '(()=>{const rl=document.querySelector(".rail"),v=rl.getBoundingClientRect();
  const on=s=>{const b=document.querySelector(s).getBoundingClientRect();return b.top>=v.top-1&&b.bottom<=v.bottom+1};
  return JSON.stringify({scrollTop:Math.round(rl.scrollTop),time:on("#time"),tints:on("#tints"),scale:on("#scale"),
   reading:document.getElementById("time").innerText.trim()})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  tap on a phone: $S2"
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
# ...and a tap from the folded state must both write the reading AND bring the
# sheet back, so the number it just produced is on screen.
TAP=$(agent-browser eval '(()=>{const m=window.__map,p=m.project([120,40]);
  const c=document.querySelector("#map canvas"),r=c.getBoundingClientRect();const o={clientX:r.left+p.x,clientY:r.top+p.y,bubbles:true};
  c.dispatchEvent(new MouseEvent("mousedown",o));c.dispatchEvent(new MouseEvent("mouseup",o));c.dispatchEvent(new MouseEvent("click",o));
  return new Promise(res=>setTimeout(()=>{const rl=document.querySelector(".rail"),v=rl.getBoundingClientRect();
   const on=s=>{const b=document.querySelector(s).getBoundingClientRect();return b.top>=v.top-1&&b.bottom<=v.bottom+1};
   res(JSON.stringify({folded:rl.classList.contains("folded"),time:document.getElementById("time").textContent.trim(),
    timeOnScreen:on("#time"),legendOnScreen:on("#tints")}))},1600))})()' 2>&1 | tail -1 | tr -d '\\')
echo "  tap from folded: $TAP"
echo "$TAP" | grep -qE '"time":"[0-9]' || { echo "  !! a tap did not write the reading"; fail=1; }
echo "$TAP" | grep -q '"timeOnScreen":true' || { echo "  !! the reading a tap produced is off screen"; fail=1; }
echo "$TAP" | grep -q '"legendOnScreen":true' || { echo "  !! the legend went off screen after a tap"; fail=1; }
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

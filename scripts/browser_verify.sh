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
SCHEMES=$(grep -cE '^ +[a-z]+: +\{ name:' "$ROOT/web/app.js")   # one RAMPS entry per scheme
[ "$SCHEMES" -ge 6 ] || SCHEMES=12
echo "expecting $CITIES cities, $BANDS bands ($TINTS swatches) from index.json; $SCHEMES schemes; screenshots in $SHOTS"
# Only the browser processes THIS run starts are killed at the end: another
# agent's session on the same machine must survive a verification pass.
BEFORE=$(/bin/ps -ax -o pid=,command= | grep -E "\.agent-browser/" | grep -v grep | awk '{print $1}' | sort)
cd "$SHOTS"
agent-browser close >/dev/null 2>&1
agent-browser open "$URL" >/dev/null 2>&1; sleep 15
fail=0
echo "=== data-level checks (desktop) ==="
R=$(agent-browser eval '(()=>{const q=s=>document.querySelector(s);return JSON.stringify({
  canvas:!!q("#map canvas"), cities:document.querySelectorAll(".results button[data-slug]").length,
  tints:document.querySelectorAll(".tints span, .keys .sw").length, ramps:document.querySelectorAll("#ramps button").length,
  disclaimer:!!q(".disclaimer") && q(".disclaimer").offsetParent !== null,
  originLabel:!!Array.from(document.querySelectorAll(".lbl.origin")).find(b=>b.getAttribute("aria-current")==="true")})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  $R"
echo "$R" | grep -q '"canvas":true' || fail=1
echo "$R" | grep -q "\"tints\":$TINTS," || { echo "  !! expected $TINTS legend swatches ($BANDS bands + 2)"; fail=1; }
echo "$R" | grep -q "\"cities\":$CITIES," || { echo "  !! expected $CITIES cities in the list"; fail=1; }
# A VISIBLE disclaimer element, not the <noscript> text this used to certify.
echo "$R" | grep -q '"disclaimer":true' || { echo "  !! no visible .disclaimer element"; fail=1; }
echo "$R" | grep -q '"originLabel":true' || { echo "  !! the departure city has no label on the opening view"; fail=1; }
# The coast is a separate static tileset drawn above the bands. A missing or
# empty water.pmtiles shows no console error -- the shore just goes back to
# being hex-shaped -- so ask the map whether water features actually rendered.
W=$(agent-browser eval '(()=>{const m=window.__map;if(!m||!m.getLayer("water"))return "no water layer";
  const n=m.queryRenderedFeatures({layers:["water"]}).length;const b=m.queryRenderedFeatures({layers:["bands"]}).length;
  return JSON.stringify({waterFeatures:n,bandFeatures:b,bandsBelowWater:m.getStyle().layers.findIndex(l=>l.id==="bands")<m.getStyle().layers.findIndex(l=>l.id==="water")})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  $W"
echo "$W" | grep -qE '"waterFeatures":[1-9]' || { echo "  !! water layer rendered nothing"; fail=1; }
echo "$W" | grep -q '"bandsBelowWater":true' || { echo "  !! bands are painted above the coast"; fail=1; }
# route summary with surface modes: click a Siberian destination from Seoul
agent-browser eval '(()=>{const c=document.querySelector("#map canvas"),r=c.getBoundingClientRect();
  const o={clientX:r.left+r.width*0.44,clientY:r.top+r.height*0.30,bubbles:true};
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
# a permalink selects its departure
agent-browser open "${URL}?from=tokyo" >/dev/null 2>&1; sleep 10
P=$(agent-browser eval 'document.getElementById("origin-name").textContent' 2>&1 | tail -1 | tr -d '\\"')
echo "  ?from=tokyo -> $P"
[ "$P" = "Tokyo" ] || { echo "  !! ?from=tokyo did not select Tokyo"; fail=1; }
echo "=== console ==="; E=$(agent-browser console 2>/dev/null | grep -ciE "error|exception"); echo "  errors: $E"; [ "$E" -eq 0 ] || fail=1
echo "=== viewports ==="
CHECK='(()=>{const b=document.body,d=document.documentElement;const q=s=>document.querySelector(s).getBoundingClientRect();
 const rr=q(".reading"),rl=q(".rail"),ms=q(".mast"),cp=q("#compass"),lg=q("#tints");const ov=(a,c)=>!(a.right<c.left||c.right<a.left||a.bottom<c.top||c.bottom<a.top);
 return JSON.stringify({vw:innerWidth,vh:innerHeight,canvas:!!document.querySelector("#map canvas"),hScroll:Math.max(b.scrollWidth,d.scrollWidth)>innerWidth+1,
  overlap:ov(ms,cp)||ov(ms,rl)||ov(cp,rl),time:!!document.getElementById("time").offsetParent,legend:lg.top>=0&&lg.bottom<=innerHeight&&lg.width>40})})()'
for spec in "1280 800 desktop" "820 1180 tablet" "390 844 mobile" "844 390 landscape"; do
  w=${spec%% *}; rest=${spec#* }; h=${rest%% *}; name=${rest#* }
  agent-browser set viewport $w $h >/dev/null 2>&1; sleep 3
  V=$(agent-browser eval "$CHECK" 2>&1 | tail -1 | tr -d '\\'); echo "  $name: $V"
  echo "$V" | grep -q '"canvas":true' && echo "$V" | grep -q '"hScroll":false' && echo "$V" | grep -q '"overlap":false' && echo "$V" | grep -q '"time":true' && echo "$V" | grep -q '"legend":true' || fail=1
  agent-browser screenshot "$SHOTS/verify_$name.png" >/dev/null 2>&1
done
# Phones: with the sheet FOLDED the legend must still be on screen (CLAUDE.md:
# the legend is always visible) and a tap must show the tapped cell's value.
agent-browser set viewport 390 844 >/dev/null 2>&1; sleep 2
F=$(agent-browser eval '(()=>{const t=document.getElementById("sheet-toggle");if(!t)return "no toggle";t.click();
  const c=document.querySelector("#map canvas"),r=c.getBoundingClientRect();const o={clientX:r.left+r.width*0.5,clientY:r.top+r.height*0.3,bubbles:true};
  c.dispatchEvent(new MouseEvent("mousedown",o));c.dispatchEvent(new MouseEvent("mouseup",o));c.dispatchEvent(new MouseEvent("click",o));
  return new Promise(res=>setTimeout(()=>{const box=s=>document.getElementById(s).getBoundingClientRect();
   const on=b=>b.width>20&&b.top>=0&&b.bottom<=innerHeight;const lg=box("tints");
   res(JSON.stringify({legendOnScreen:lg.width>40&&lg.top>=0&&lg.bottom<=innerHeight,
    keysOnScreen:on(box("keys")),capOnScreen:!!document.querySelector(".rail.folded .legend-cap")&&on(document.querySelector(".legend-cap").getBoundingClientRect()),
    time:document.getElementById("time").textContent.trim()}))},1500))})()' 2>&1 | tail -1 | tr -d '\\')
echo "  folded sheet: $F"
echo "$F" | grep -q '"legendOnScreen":true' || { echo "  !! the legend is hidden while the sheet is folded"; fail=1; }
# The band strip alone is not the legend: without the two keys the grey and the
# sea colour have no meaning, and without the caption the figures lose the
# door-to-door qualifier the modelling rule requires. The swatch COUNT cannot
# catch this -- display:none leaves the nodes in the DOM.
echo "$F" | grep -q '"keysOnScreen":true' || { echo "  !! the two legend keys are hidden while the sheet is folded"; fail=1; }
echo "$F" | grep -q '"capOnScreen":true' || { echo "  !! the door-to-door caption is hidden while the sheet is folded"; fail=1; }
echo "$F" | grep -qE '"time":"[0-9]' || { echo "  !! a tap did not write the reading"; fail=1; }
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

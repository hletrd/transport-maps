#!/usr/bin/env bash
# Post-deploy browser verification. Exits non-zero on any failed check.
#   scripts/browser_verify.sh                      # the live site
#   scripts/browser_verify.sh http://127.0.0.1:8899/   # a local dist
set -u
URL="${1:-https://worldmap.atik.kr/}"
# Expected counts come from the deployed index.json, never from a literal:
# 157 cities and 37 swatches were hard-coded here and would have blocked the
# correct 553-origin deploy. The legend shows one swatch per band plus two
# more, for "no scheduled route" and "open water".
IDX=$(curl -sf "${URL%/}/index.json") || { echo "!! could not fetch ${URL%/}/index.json"; exit 1; }
read -r CITIES BANDS < <(printf '%s' "$IDX" | python3 -c 'import json, sys
d = json.load(sys.stdin); print(len(d["origins"]), len(d["bandEdgesMin"]) + 1)')
[ -n "${BANDS:-}" ] || { echo "!! index.json has no origins/bandEdgesMin"; exit 1; }
TINTS=$((BANDS + 2))
SCHEMES=12   # a page fact: the colour schemes app.js ships
echo "expecting $CITIES cities, $BANDS bands ($TINTS swatches) from index.json; $SCHEMES schemes"
cd /tmp
agent-browser close >/dev/null 2>&1
agent-browser open "$URL" >/dev/null 2>&1; sleep 15
fail=0
echo "=== data-level checks (desktop) ==="
R=$(agent-browser eval '(()=>{const q=s=>document.querySelector(s);return JSON.stringify({
  canvas:!!q("#map canvas"), cities:document.querySelectorAll(".results button").length,
  tints:document.querySelectorAll(".tints span").length, ramps:document.querySelectorAll("#ramps button").length,
  borders:!!q(".maplibregl-canvas"), disclaimer:!!q(".disclaimer") && q(".disclaimer").offsetParent !== null})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  $R"
echo "$R" | grep -q '"canvas":true' || fail=1
echo "$R" | grep -q "\"tints\":$TINTS," || { echo "  !! expected $TINTS legend swatches ($BANDS bands + 2)"; fail=1; }
echo "$R" | grep -q "\"cities\":$CITIES," || { echo "  !! expected $CITIES cities in the list"; fail=1; }
echo "$R" | grep -q '"borders":true' || { echo "  !! no map canvas for the borders layer"; fail=1; }
# A VISIBLE disclaimer element, not the <noscript> text this used to certify.
echo "$R" | grep -q '"disclaimer":true' || { echo "  !! no visible .disclaimer element"; fail=1; }
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
# address search reaches Nominatim and lists results
agent-browser eval '(()=>{const q=document.getElementById("q");q.value="Gangnam-daero, Seoul";q.dispatchEvent(new Event("input",{bubbles:true}));return 1})()' >/dev/null 2>&1; sleep 5
A=$(agent-browser eval 'document.querySelectorAll(".results .addresses button[data-geo]").length' 2>&1 | tail -1 | tr -d '\\"')
echo "  address results: $A"
[ "${A:-0}" -ge 1 ] || { echo "  !! address search returned nothing"; fail=1; }
agent-browser eval '(()=>{const q=document.getElementById("q");q.value="";q.dispatchEvent(new Event("input",{bubbles:true}));return 1})()' >/dev/null 2>&1
# click to depart: an origin-city label is a button that switches the tiles
agent-browser eval 'window.__map.jumpTo({center:[135,35],zoom:4.6});1' >/dev/null 2>&1; sleep 6
C=$(agent-browser eval '(()=>{const b=document.querySelector(".lbl.origin");if(!b)return "no origin label";const n=b.textContent;b.click();return n})()' 2>&1 | tail -1 | tr -d '\\"')
sleep 5
SRC=$(agent-browser eval 'window.__map.getSource("bands").url' 2>&1 | tail -1 | tr -d '\\"')
echo "  clicked label: $C -> $SRC"
echo "$SRC" | grep -q "origins/seoul.pmtiles" && { echo "  !! clicking an origin label did not change the departure"; fail=1; }
# low zoom: the coarse level must paint, and the coast must be there
Z=$(agent-browser eval '(()=>{const m=window.__map;m.jumpTo({center:[127,36],zoom:3.4});return 1})()' >/dev/null 2>&1; sleep 7; agent-browser eval '(()=>{const m=window.__map;return JSON.stringify({z:m.getZoom(),bands:m.queryRenderedFeatures({layers:["bands"]}).length,water:m.queryRenderedFeatures({layers:["water"]}).length})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  zoom 3: $Z"
echo "$Z" | grep -qE '"bands":[1-9]' && echo "$Z" | grep -qE '"water":[1-9]' || { echo "  !! nothing painted at zoom 3"; fail=1; }
agent-browser screenshot /tmp/verify_zoom3.png >/dev/null 2>&1
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
  agent-browser screenshot /tmp/verify_$name.png >/dev/null 2>&1
done
agent-browser close >/dev/null 2>&1; sleep 1
/bin/ps -ax -o pid=,command= | grep -E "\.agent-browser/|agent-browser" | grep -vE "grep|Google Chrome\.app" | awk '{print $1}' | while read p; do kill -9 $p 2>/dev/null; done; sleep 1
left=$(/bin/ps -ax -o command= | grep -E "\.agent-browser/|agent-browser" | grep -vcE "grep|Google Chrome\.app")
echo "=== cleanup ===  agent-browser left: $left  |  Google Chrome untouched: $(/bin/ps -ax -o command= | grep -c '[G]oogle Chrome.app')"
[ "$left" -eq 0 ] || fail=1
echo; [ $fail -eq 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit $fail

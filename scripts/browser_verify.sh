#!/usr/bin/env bash
# Post-deploy browser verification. Exits non-zero on any failed check.
#   scripts/browser_verify.sh                      # the live site
#   scripts/browser_verify.sh http://127.0.0.1:8899/   # a local dist
set -u
URL="${1:-https://worldmap.atik.kr/}"
cd /tmp
agent-browser close >/dev/null 2>&1
agent-browser open "$URL" >/dev/null 2>&1; sleep 15
fail=0
echo "=== data-level checks (desktop) ==="
R=$(agent-browser eval '(()=>{const q=s=>document.querySelector(s);return JSON.stringify({
  canvas:!!q("#map canvas"), cities:document.querySelectorAll(".results button").length,
  tints:document.querySelectorAll(".tints span").length, ramps:document.querySelectorAll("#ramps button").length,
  borders:!!q(".maplibregl-canvas"), disclaimer:document.body.textContent.includes("For reference only")})})()' 2>&1 | tail -1 | tr -d '\\')
echo "  $R"
echo "$R" | grep -q '"canvas":true' || fail=1
echo "$R" | grep -q '"tints":37' || { echo "  !! expected 37 legend swatches"; fail=1; }
echo "$R" | grep -q '"cities":157' || fail=1
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

"""Map readiness controls both the visible wait and optional downloads."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "web/loading.js"


@pytest.fixture
def run(tmp_path):
    module = tmp_path / "loading.mjs"
    module.write_bytes(SOURCE.read_bytes())

    def execute(body):
        script = tmp_path / "test.mjs"
        script.write_text(f"import {{createMapLoading}} from {json.dumps(module.as_uri())};\n" + '''
const parts=Object.fromEntries(['b','.sub','.elapsed','.bar','button'].map(k=>[k,{
 textContent:'',hidden:false,addEventListener(type,fn){this.click=fn;},removeEventListener(){}}]));
const box={hidden:false,querySelector:s=>parts[s]};
const attrs={},listeners={};let loaded=false,style=false,moving=false,clock=0,retries=0;
const map={getSource:()=>({}),isStyleLoaded:()=>style,areTilesLoaded:()=>loaded,isMoving:()=>moving,
 getContainer:()=>({setAttribute:(k,v)=>attrs[k]=v}),triggerRepaint:()=>{},
 on:(type,fn)=>listeners[type]=fn,off:type=>delete listeners[type]};
const loading=createMapLoading(map,box,{now:()=>clock,maxWait:100,retry:()=>retries++});
const frame=()=>listeners.render();
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
''' + body + "\nloading.dispose();\n")
        result = subprocess.run([shutil.which("node"), str(script)], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip())

    return execute


def test_waits_for_source_tiles_times_and_camera_before_hiding_or_downloading(run):
    result = run('''
loading.begin('Tokyo');let requests=0;
const task=loading.wait().then(()=>requests++);
loading.timesReady();loaded=true;frame();await sleep(0);
const headerOnly={hidden:box.hidden,requests};
style=true;moving=true;frame();await sleep(0);
const inMotion={hidden:box.hidden,requests};
moving=false;frame();await task;
console.log(JSON.stringify({headerOnly,inMotion,done:{hidden:box.hidden,requests,busy:attrs['aria-busy']}}));
''')
    assert result["headerOnly"] == result["inMotion"] == {"hidden": False, "requests": 0}
    assert result["done"] == {"hidden": True, "requests": 1, "busy": "false"}


def test_new_departure_does_not_reuse_old_completion_and_cancels_queued_work(run):
    result = run('''
loading.begin('Tokyo');const ctrl=new AbortController();let requests=0,cancelled=false;
const old=loading.wait(ctrl.signal).then(()=>requests++,()=>cancelled=true);
ctrl.abort();loading.begin('London');loaded=style=true;frame();await old;
const waiting={title:parts.b.textContent,hidden:box.hidden,requests,cancelled};
loading.timesReady();frame();console.log(JSON.stringify({waiting,hidden:box.hidden}));
''')
    assert result["waiting"] == {"title": "Loading map from London…", "hidden": False,
                                  "requests": 0, "cancelled": True}
    assert result["hidden"] is True


def test_failure_stops_spinner_offers_retry_and_does_not_block_routes_forever(run):
    result = run('''
loading.begin('Tokyo');let requests=0;const task=loading.wait().then(()=>requests++);
loading.fail('The coastline could not be downloaded.');await sleep(0);const immediate=requests;
await task;parts.button.click();
loaded=style=true;loading.timesReady();frame();
console.log(JSON.stringify({hidden:box.hidden,bar:parts['.bar'].hidden,retry:parts.button.hidden,
 detail:parts['.sub'].textContent,retries,requests,immediate,busy:attrs['aria-busy']}));
''')
    assert result == {"hidden": False, "bar": True, "retry": False,
                      "detail": "The coastline could not be downloaded.", "retries": 1,
                      "requests": 1, "immediate": 1, "busy": "false"}


def test_background_timeout_does_not_claim_the_map_has_loaded(run):
    result = run('''
loading.begin('Tokyo');await loading.wait();
console.log(JSON.stringify({hidden:box.hidden,busy:attrs['aria-busy']}));
''')
    assert result == {"hidden": False, "busy": "true"}

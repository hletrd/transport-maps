"""Run the regional reader against binary fixtures and real Fetch responses."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.web import _js

SOURCE = Path(__file__).resolve().parents[2] / "web/detail.js"


@pytest.fixture
def run(tmp_path):
    node = shutil.which("node")
    assert node, "node is required to verify the regional reader"
    module = tmp_path / "detail.mjs"
    module.write_bytes(SOURCE.read_bytes())

    def execute(body):
        script = tmp_path / "probe.mjs"
        script.write_text(f"import {{createDetailReader}} from {json.dumps(module.as_uri())};\n" + r'''
const bytes = a => new Uint8Array(a.buffer);
const times = bytes(new Uint16Array(Array.from({length:20},(_,i)=>100+i)));
const directory = bytes(new Uint32Array([4,0,1,2,3,3,4]));
const routes = new Uint8Array(40);
routes.set(bytes(new Uint32Array([1,6,9,18])),0);
routes.set(bytes(new Uint16Array([2,3,4,5])),16);
routes.set(bytes(new Uint16Array([1,10,2,20,3,30,4,40])),24);
const calls=[],errors=[]; let loads=0, fault='', gate=null;
const ctl=new AbortController();
async function fetcher(url,options={}) {
  calls.push({url,range:options.headers?.Range});
  await new Promise(r=>setTimeout(r,5));
  if (url.endsWith('.over.index.bin')) {
    if (fault==='directory') return new Response(bytes(new Uint32Array([4,0,2,1,3,3,4])));
    return new Response(directory);
  }
  if (url.endsWith('.over.bin') && gate) await gate;
  const data=url.endsWith('.r6.bin')?times:routes;
  const [,first,last]=/^bytes=(\d+)-(\d+)$/.exec(options.headers.Range).map(Number);
  if (fault==='whole') return new Response(data);
  const end=fault==='wrong-range'?last+1:last;
  const total=fault==='wrong-total'?data.length+2:data.length;
  const body=data.slice(first,fault==='short'?last:last+1);
  return new Response(body,{status:206,headers:{'Content-Range':`bytes ${first}-${end}/${total}`}});
}
const reader=createDetailReader({base:'/data/build/origins/',slug:'seoul',parents:5,slots:4,
  channels:2,blocks:2,signal:ctl.signal,fetcher,onLoad:()=>loads++,onError:e=>errors.push(e.message)});
''' + body)
        done = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=20)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout.strip().splitlines()[-1])

    return execute


def test_reads_only_the_requested_region_and_reuses_it(run):
    result = run('''
const eager=calls.length;
await Promise.all([reader.request(5),reader.request(6)]);
const first=calls.slice(), before=calls.length;
await reader.request(1);
console.log(JSON.stringify({eager,first,reused:before===calls.length,loads,
 value:reader.get(5),outside:reader.get(9)===undefined,airport:reader.route(6).airport,
 modes:Array.from(reader.route(6).modes),absent:reader.route(5)}));
''')
    assert result["eager"] == 0 and result["reused"] and result["loads"] == 1
    assert result["value"] == 105 and result["outside"]
    assert result["airport"] == 3 and result["modes"] == [2, 20] and result["absent"] is None
    requests = result["first"]
    assert len(requests) == 5
    assert [r["range"] for r in requests if r["url"].endswith(".r6.bin")] == ["bytes=0-15"]
    assert [r["range"] for r in requests if r["url"].endswith(".over.bin")] == ["bytes=0-7", "bytes=16-19", "bytes=24-31"]
    assert all(r["url"].startswith("/data/build/origins/") for r in requests)


def test_the_last_short_region_keeps_global_route_slots(run):
    result = run('''
await reader.request(18);
console.log(JSON.stringify({value:reader.get(19),airport:reader.route(18).airport,
 modes:Array.from(reader.route(18).modes),calls}));
''')
    assert result["value"] == 119 and result["airport"] == 5 and result["modes"] == [4, 40]
    assert next(r["range"] for r in result["calls"] if r["url"].endswith(".r6.bin")) == "bytes=32-39"


def test_fine_times_wait_for_the_matching_route_details(run):
    result = run('''
let release; gate=new Promise(r=>release=r);
const work=reader.request(6);
await new Promise(r=>setTimeout(r,35));
const withheld=reader.get(6)===undefined&&reader.route(6)===null&&loads===0;
release();await work;
console.log(JSON.stringify({withheld,value:reader.get(6),airport:reader.route(6).airport,loads}));
''')
    assert result == {"withheld": True, "value": 106, "airport": 3, "loads": 1}


@pytest.mark.parametrize("fault", ["whole", "wrong-range", "wrong-total", "short", "directory"])
def test_bad_responses_keep_the_coarse_fallback_and_back_off(run, fault):
    result = run(f'''
fault={json.dumps(fault)};
const ok=await reader.request(6), before=calls.length;
await reader.request(9);
console.log(JSON.stringify({{ok,unavailable:reader.get(6)===undefined,
 unchanged:calls.length===before,loads,errors:errors.length}}));
''')
    assert result == {"ok": False, "unavailable": True, "unchanged": True, "loads": 0, "errors": 1}


def test_an_aborted_origin_never_publishes_late_results(run):
    result = run('''
const work=reader.request(6);ctl.abort();
await work;
console.log(JSON.stringify({unavailable:reader.get(6)===undefined,loads,errors:errors.length}));
''')
    assert result == {"unavailable": True, "loads": 0, "errors": 0}


@pytest.mark.parametrize("previous,expected", [
    ("JFK: 17 hours, door to door.", "JFK: 1006"),
    ("2 airports match a new search.", "2 airports match a new search."),
])
def test_background_detail_preserves_the_current_announcement(tmp_path, previous, expected):
    script = tmp_path / "announcement.cjs"
    script.write_text(f'''
const status={{textContent:{json.dumps(previous)}}};
const $=id=>id==="status"?status:{{value:"JFK"}};
const pinB={{lat:40,lon:-73,label:"JFK"}};
const rereadFine=()=>{{}},renderPins=()=>{{}},renderLegs=()=>{{}},renderDeparture=()=>{{}},refreshScale=()=>{{}};
const render=()=>{{status.textContent="1 airport matches JFK";}};
const lookup=()=>1006;
const announce=text=>{{status.textContent=text;}};
const announceReading=(lat,lon,time,label)=>announce(label+": "+time);
{_js.function("refreshDetail")}
refreshDetail();console.log(JSON.stringify(status.textContent));
''')
    done = subprocess.run([shutil.which("node"), str(script)], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == expected

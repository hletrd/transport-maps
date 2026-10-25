"""Exercise route selection, privacy boundaries and fallback with Fetch bodies."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "web/delivery.js"


@pytest.fixture
def run(tmp_path):
    node = shutil.which("node")
    assert node, "node is required for delivery tests"
    module = tmp_path / "delivery.mjs"
    module.write_bytes(SOURCE.read_bytes())

    def execute(body):
        script = tmp_path / "test.mjs"
        script.write_text(f"import {{createDataDelivery,createRoutedSource,preferCDN}} from {json.dumps(module.as_uri())};\n" + r'''
const origin='https://map.test',cdn='https://cdn.test',root='/data/build-1/';
const calls=[],saved=new Map();
const storage={getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)};
const cacheCDN=()=>saved.set('worldmap.delivery.v1',JSON.stringify({cdn,choice:'cdn',at:1000}));
let directMs=100,cdnMs=10,fault='',probeFault='',probeHold=null;
const timing={getEntriesByName:url=>[{startTime:100,responseEnd:100+(url.startsWith(cdn)?cdnMs:directMs)}]};
async function fetcher(input,options={}) {
  const url=new URL(typeof input==='string'?input:input.url||input.href,origin);
  calls.push({url:url.href,options});
  if(url.pathname==='/delivery-probe-v1.bin') {
    if(probeHold)await probeHold;
    const invalid=url.origin===cdn&&probeFault;
    return new Response(new Uint8Array(invalid==='length'?5:16384),{
      status:invalid==='http'?503:200,headers:{'X-Worldmap-Probe':invalid==='header'?'bad':'1'}});
  }
  if(url.origin===cdn) {
    if(fault==='http')return new Response('busy',{status:503});
    if(fault==='network')throw new TypeError('Failed to fetch');
    if(fault==='timeout')return new Promise(()=>{});
    if(fault==='abort')return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true}));
    if(fault==='json')return new Response('{broken');
    if(fault==='range')return new Response('entire file');
    if(fault==='bounds')return new Response(new Uint8Array(5),{status:206,headers:{'Content-Range':'bytes 0-4/10'}});
    if(fault==='short')return new Response(new Uint8Array(4),{status:206,headers:{'Content-Range':'bytes 2-6/10'}});
    if(fault==='oversize')return new Response(new Uint8Array(6),{status:206,headers:{'Content-Range':'bytes 2-6/10'}});
    if(fault==='stall')return new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array([1]));}}),
      {status:206,headers:{'Content-Range':'bytes 2-6/10'}});
  }
  if(new Headers(options.headers).has('Range'))return new Response(new Uint8Array([2,3,4,5,6]),
    {status:206,headers:{'Content-Range':'bytes 2-6/10','ETag':'"same"'}});
  return new Response(JSON.stringify({source:url.origin}),{headers:{'Content-Type':'application/json'}});
}
const options={origin,cdn,root,storage,fetcher,timing,now:()=>100,wallTime:()=>1000,
  probeTimeout:30,headerTimeout:15,stallTimeout:15,bodyTimeout:100};
''' + body)
        done = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=15)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout.strip().splitlines()[-1])

    return execute


@pytest.mark.parametrize("direct,cdn,want", [(10, 200, "direct"), (200, 20, "cdn"), (100, 85, "direct")])
def test_selects_a_meaningfully_faster_route_using_network_timing(run, direct, cdn, want):
    result = run(f'''
directMs={direct};cdnMs={cdn};
const route=createDataDelivery(options);await route.start();
const data=await (await route.fetch(root+'places.json')).json();
console.log(JSON.stringify({{state:route.getState(),calls:calls.map(c=>c.url),data}}));
''')
    assert result["state"]["choice"] == want
    assert result["state"]["measurements"] == {"direct": direct, "cdn": cdn}
    assert len([url for url in result["calls"] if url.endswith("delivery-probe-v1.bin")]) == 4
    assert result["data"]["source"] == ("https://cdn.test" if want == "cdn" else "https://map.test")


def test_map_requests_do_not_wait_for_slow_probes(run):
    result = run('''
probeHold=new Promise(()=>{});
const route=createDataDelivery(options);const probing=route.start();
const response=await route.fetch(root+'index.json');
const data=await response.json();
const before=route.getState();route.dispose();await probing;
console.log(JSON.stringify({data,before}));
''')
    assert result["data"]["source"] == "https://map.test"
    assert result["before"]["measurements"] == {"direct": None, "cdn": None}


@pytest.mark.parametrize("fault", ["http", "network", "timeout", "json", "range", "bounds", "short", "oversize", "stall"])
def test_bad_cdn_requests_retry_the_identical_version_on_direct(run, fault):
    ranged = fault in ("range", "bounds", "short", "oversize", "stall")
    result = run(f'''
cacheCDN();fault={json.dumps(fault)};
const route=createDataDelivery(options);
const requestOptions={json.dumps({'headers': {'Range': 'bytes=2-6'}} if ranged else {})};
const path=root+{'"origins/seoul.r6.bin"' if ranged else '"places.json"'};
const response=await route.fetch(path,requestOptions);
const bytes=Array.from(new Uint8Array(await response.arrayBuffer()));
await route.fetch(root+'airports.json');
console.log(JSON.stringify({{state:route.getState(),bytes,calls:calls.map(c=>({{url:c.url,range:new Headers(c.options.headers).get('Range')}}))}}));
''')
    assert result["state"]["choice"] == "direct" and result["state"]["fallbacks"] == 1
    assert result["calls"][0]["url"].replace("https://cdn.test", "https://map.test") == result["calls"][1]["url"]
    assert result["calls"][2]["url"] == "https://map.test/data/build-1/airports.json"
    if ranged:
        assert result["bytes"] == [2, 3, 4, 5, 6]
        assert result["calls"][0]["range"] == result["calls"][1]["range"] == "bytes=2-6"


def test_late_probe_cannot_reenable_a_failed_cdn(run):
    result = run('''
cacheCDN();fault='http';let release;probeHold=new Promise(r=>release=r);
const route=createDataDelivery(options);const probing=route.start();
await route.fetch(root+'index.json');release();await probing;
console.log(JSON.stringify(route.getState()));
''')
    assert result["choice"] == "direct" and result["fallbacks"] == 1


def test_user_cancellation_does_not_retry_or_condemn_the_cdn(run):
    result = run('''
cacheCDN();fault='abort';const route=createDataDelivery(options),ctrl=new AbortController();
const request=route.fetch(root+'index.json',{signal:ctrl.signal});ctrl.abort();
let rejected=false;try{await request;}catch{rejected=true;}
console.log(JSON.stringify({rejected,state:route.getState(),calls:calls.length}));
''')
    assert result["rejected"] and result["calls"] == 1
    assert result["state"]["fallbacks"] == 0 and result["state"]["choice"] == "cdn"


@pytest.mark.parametrize("path", ["/api/solve?from=1,2&to=3,4", "/assets/app.js",
    "/data/build-2/places.json", "/data/build-1/places.json?to=1,2",
    "/data/build-1/../../api/solve", "https://nominatim.openstreetmap.org/search?q=test"])
def test_only_this_release_public_data_can_leave_the_origin(run, path):
    result = run(f'''
cacheCDN();const route=createDataDelivery(options);await route.fetch({json.dumps(path)});
console.log(JSON.stringify(calls.map(c=>c.url)));
''')
    assert len(result) == 1 and not result[0].startswith("https://cdn.test")


def test_cdn_requests_omit_cookies_and_the_page_referrer(run):
    result = run('''
cacheCDN();const route=createDataDelivery(options);
await route.fetch(root+'index.json',{credentials:'include'});
console.log(JSON.stringify({credentials:calls[0].options.credentials,referrer:calls[0].options.referrerPolicy}));
''')
    assert result == {"credentials": "omit", "referrer": "no-referrer"}


def test_save_data_uses_direct_without_probes(run):
    result = run('''
cacheCDN();const route=createDataDelivery({...options,saveData:true});await route.start();
await route.fetch(root+'index.json');console.log(JSON.stringify({state:route.getState(),calls:calls.map(c=>c.url)}));
''')
    assert not result["state"]["enabled"]
    assert result["calls"] == ["https://map.test/data/build-1/index.json"]


@pytest.mark.parametrize("fault", ["http", "header", "length"])
def test_a_fast_but_invalid_probe_cannot_select_the_cdn(run, fault):
    result = run(f'''
probeFault={json.dumps(fault)};directMs=200;cdnMs=1;
const route=createDataDelivery(options);await route.start();
console.log(JSON.stringify(route.getState()));
''')
    assert result["choice"] == "direct" and result["measurements"]["cdn"] is None


def test_explicit_credentials_and_request_objects_stay_on_the_original_host(run):
    result = run('''
cacheCDN();const route=createDataDelivery(options);
await route.fetch(root+'index.json',{headers:{Authorization:'Bearer private'}});
const req=new Request(origin+root+'index.json',{headers:{'X-API-Key':'private'}});
await route.fetch(req);
console.log(JSON.stringify(calls.map(c=>c.url)));
''')
    assert result == ["https://map.test/data/build-1/index.json"] * 2


def test_pmtiles_source_keeps_the_cache_key_and_reloads_changed_etags(run):
    result = run('''
class Changed extends Error{};const seen=[];
const source=createRoutedSource('/data/build-1/a.pmtiles',async(url,o)=>{
 seen.push({url,cache:o.cache,range:new Headers(o.headers).get('Range')});
 return new Response(new Uint8Array(5),{status:206,headers:{ETag:'"new"'}});
},Changed);
let mismatch=false;try{await source.getBytes(10,5,undefined,'"old"');}catch(e){mismatch=e instanceof Changed;}
await source.getBytes(10,5);
console.log(JSON.stringify({key:source.getKey(),mismatch,seen}));
''')
    assert result["key"] == "/data/build-1/a.pmtiles" and result["mismatch"]
    assert result["seen"][1]["cache"] == "reload"
    assert result["seen"][1]["range"] == "bytes=10-14"


def test_pmtiles_source_handles_a_small_archive_range_refusal(run):
    result = run('''
class Changed extends Error{};const seen=[];
const source=createRoutedSource('/data/build-1/a.pmtiles',async(url,o)=>{
 seen.push(o.headers.Range);
 return seen.length===1?new Response(null,{status:416,headers:{'Content-Range':'bytes */127'}})
  :new Response(new Uint8Array(127),{status:206});
},Changed);
const result=await source.getBytes(0,16384);
console.log(JSON.stringify({seen,length:result.data.byteLength}));
''')
    assert result == {"seen": ["bytes=0-16383", "bytes=0-126"], "length": 127}


def test_pmtiles_reuses_header_bytes_for_a_matching_directory_and_respects_abort(run):
    result = run('''
class Changed extends Error{};const seen=[];
const source=createRoutedSource('/data/build-1/a.pmtiles',async(url,o)=>{
 seen.push(new Headers(o.headers).get('Range'));
 return new Response(Uint8Array.from({length:16},(_,i)=>i),{status:206,headers:{ETag:'"same"'}});
},Changed);
await source.getBytes(0,16);
const directory=await source.getBytes(3,5,undefined,'"same"');
const ctrl=new AbortController();ctrl.abort();let aborted=false;
try{await source.getBytes(3,5,ctrl.signal,'"same"');}catch{aborted=true;}
let mismatch=false;
try{await source.getBytes(3,5,undefined,'"other"');}catch(e){mismatch=e instanceof Changed;}
console.log(JSON.stringify({calls:seen,bytes:[...new Uint8Array(directory.data)],aborted,mismatch}));
''')
    assert result == {"calls": ["bytes=0-15", "bytes=3-7"], "bytes": [3, 4, 5, 6, 7],
                      "aborted": True, "mismatch": True}


def test_browser_probes_start_after_the_first_paint_opportunity(tmp_path):
    module = tmp_path / "delivery.mjs"
    module.write_bytes(SOURCE.read_bytes())
    script = tmp_path / "paint.mjs"
    script.write_text(f'''
const frames=[],calls=[];
globalThis.document={{querySelectorAll:()=>[],querySelector:s=>({{content:s.includes('data-root')?'/data/build-1/':'https://worldmap-data.atik.kr'}})}};
globalThis.location=new URL('https://worldmap.atik.kr/');
globalThis.window={{}};globalThis.addEventListener=()=>{{}};
globalThis.requestAnimationFrame=fn=>frames.push(fn);
globalThis.fetch=async url=>{{calls.push(url);return new Response(new Uint8Array(16384),{{headers:{{'X-Worldmap-Probe':'1'}}}});}};
await import({json.dumps(module.as_uri())});
const before=calls.length;frames.shift()();const first=calls.length;
frames.shift()();await window.__dataDelivery.start();
console.log(JSON.stringify({{before,first,after:calls.length}}));
''')
    done = subprocess.run([shutil.which("node"), str(script)], capture_output=True, text=True, timeout=15)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"before": 0, "first": 0, "after": 4}


@pytest.mark.parametrize("production", [True, False])
def test_browser_waits_for_actual_fcp_when_paint_timing_is_available(tmp_path, production):
    module = tmp_path / "delivery.mjs"
    module.write_bytes(SOURCE.read_bytes())
    script = tmp_path / "fcp.mjs"
    script.write_text(f'''
let notify,disconnected=false,styleLoad;const calls=[];
const styles=[{{media:'print',sheet:{{}}}},{{media:'print',sheet:null,addEventListener:(name,fn)=>styleLoad=fn}}];
globalThis.document={{querySelectorAll:()=>styles,querySelector:s=>({{content:s.includes('data-root')?'/data/build-1/':'https://worldmap-data.atik.kr'}})}};
globalThis.location=new URL({json.dumps('https://worldmap.atik.kr/' if production else 'http://localhost:8899/')});globalThis.window={{}};
globalThis.addEventListener=()=>{{}};
globalThis.PerformanceObserver=class {{
 static supportedEntryTypes=['paint'];constructor(fn){{notify=fn;}}
 observe(){{}}disconnect(){{disconnected=true;}}
}};
globalThis.fetch=async url=>{{calls.push(url);return new Response(new Uint8Array(16384),{{headers:{{'X-Worldmap-Probe':'1'}}}});}};
await import({json.dumps(module.as_uri())});
notify({{getEntries:()=>[{{name:'first-paint'}}]}});const before=calls.length,beforeStyles=styles.map(s=>s.media);
notify({{getEntries:()=>[{{name:'first-contentful-paint'}}]}});await window.__dataDelivery?.start();
const whileLoading=styles.map(s=>s.media);styleLoad();
console.log(JSON.stringify({{before,after:calls.length,disconnected,beforeStyles,whileLoading,loaded:styles.map(s=>s.media)}}));
''')
    done = subprocess.run([shutil.which("node"), str(script)], capture_output=True, text=True, timeout=15)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"before": 0, "after": 4 if production else 0, "disconnected": True,
                                     "beforeStyles": ["print", "print"], "whileLoading": ["all", "print"],
                                     "loaded": ["all", "all"]}

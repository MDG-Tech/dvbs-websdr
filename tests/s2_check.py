#!/usr/bin/env python3
"""Actual Chromium DVB-S2 recovery at multiple symbol rates and MODCODs."""
import asyncio,json,time,argparse
from pathlib import Path
from playwright.async_api import async_playwright
from browser_support import browser_binary
ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT/'tools'))
from test_source import test_source
async def main():
    profiles=json.loads(Path('/tmp/dvbs-s2-fixtures.json').read_text());results=[]
    parser=argparse.ArgumentParser();parser.add_argument('--profile');options=parser.parse_args()
    if options.profile:profiles=[p for p in profiles if p['name']==options.profile]
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=browser_binary(),args=['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=await browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto('http://127.0.0.1:8090')
        for profile in profiles:
            raw=Path(profile['path']).read_bytes()
            await page.route('**/s2-fixture.cf32',lambda route:route.fulfill(body=raw,content_type='application/octet-stream'))
            result=await page.evaluate('''async profile=>{
              const raw=await(await fetch('/s2-fixture.cf32')).arrayBuffer();
              return await new Promise((resolve,reject)=>{
                const worker=new Worker('decoder-worker.js');let pos=0,consumed=0,bytes=0,blocks=[],logs=[],info=[];
                const start=performance.now();
                const timer=setTimeout(()=>{worker.terminate();reject(Error('S2 timeout '+JSON.stringify({bytes,consumed,logs,info})));},90000);
                function finish(){clearTimeout(timer);worker.terminate();const out=new Uint8Array(bytes);let k=0;for(const b of blocks){out.set(b,k);k+=b.length;}window.s2TS=out;resolve({bytes,consumed,seconds:(performance.now()-start)/1000,logs,info});}
                function feed(){if(pos<raw.byteLength){const data=raw.slice(pos,pos+262144);pos+=data.byteLength;worker.postMessage({type:'iq',data},[data]);}else worker.postMessage({type:'end'});}
                worker.onerror=e=>reject(Error(e.message));
                worker.onmessage=({data:m})=>{
                  if(m.type==='ready')feed();
                  else if(m.type==='ts'){bytes+=m.data.byteLength;blocks.push(new Uint8Array(m.data));}
                  else if(m.type==='consumed'){consumed++;feed();if(consumed===Math.ceil(raw.byteLength/262144))setTimeout(finish,1500);}
                  else if(m.type==='info' && /MODCOD|LOCK/.test(m.text))info.push(m.text);
                  else if(m.type==='log')logs.push(m.text);
                  else if(m.type==='error'){clearTimeout(timer);reject(Error(m.text));}
                };
                worker.postMessage({type:'start',standard:'DVB-S2',rate:profile.rate,symbolRate:profile.symbolRate,rolloff:.35,fec:'1/2',modcod:0,framesizes:3});
              });
            }''',profile)
            result['name']=profile['name'];print(json.dumps(result),flush=True)
            assert result['bytes']>50000,result
            data=bytes(await page.evaluate('Array.from(window.s2TS)'))
            source=test_source().read_bytes();ref={source[i:i+188] for i in range(0,len(source),188)}
            packets=[data[i:i+188] for i in range(0,len(data),188)]
            result['source_matches']=sum(x in ref for x in packets);result['packets']=len(packets)
            assert result['source_matches']>=len(packets)-5,result
            results.append(result)
            await page.unroute('**/s2-fixture.cf32')
        assert not errors,errors
        await browser.close()
    output=ROOT/'tests/s2-results.json'
    if options.profile and output.exists():results=[p for p in json.loads(output.read_text()) if p['name']!=options.profile]+results
    output.write_text(json.dumps(results,indent=2)+'\n')
asyncio.run(main())

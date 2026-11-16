#!/usr/bin/env python3
"""Real Chromium worker check with a known IQ fixture, no RF transmission."""
import asyncio, json
from pathlib import Path
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/root/.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell',headless=True,args=['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=await browser.new_page(viewport={'width':1400,'height':1100})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto('http://127.0.0.1:8090')
        await page.wait_for_function('document.querySelector("#receiver").options.length===2')
        assert await page.input_value('#receiver')=='1:1'
        fixture=Path('/tmp/dvbs-fixture.cf32').read_bytes()[:65536000]
        await page.route('**/fixture.cf32',lambda route:route.fulfill(body=fixture,content_type='application/octet-stream'))
        result=await page.evaluate('''async () => {
          const raw=await (await fetch('/fixture.cf32')).arrayBuffer();
          return await new Promise((resolve,reject)=>{
            const w=new Worker('decoder-worker.js');let bytes=0,blocks=[], logs=[], consumed=0, position=0;
            function feed(){
              if(position<raw.byteLength){const data=raw.slice(position,position+262144);position+=data.byteLength;w.postMessage({type:'iq',data},[data]);}
              else w.postMessage({type:'end'});
            }
            const timeout=setTimeout(()=>{w.terminate();reject(Error('Decoder timeout '+JSON.stringify({bytes,logs})));},120000);
            w.onerror=e=>reject(Error(e.message));
            w.onmessage=({data:m})=>{
              if(m.type==='ready'){
                feed();
              }else if(m.type==='ts'){bytes+=m.data.byteLength;blocks.push(new Uint8Array(m.data));}
              else if(m.type==='error'){reject(Error(m.text));}
              else if(m.type==='log')logs.push(m.text);
              else if(m.type==='consumed'){
                consumed++;
                feed();
                if(consumed===Math.ceil(raw.byteLength/262144))setTimeout(()=>{
                  clearTimeout(timeout);w.terminate();let out=new Uint8Array(bytes),pos=0;for(const b of blocks){out.set(b,pos);pos+=b.length;}
                  window.testTS=out;
                  resolve({bytes,consumed,logs});
                },1000);
              }
            };
            w.postMessage({type:'start',rate:2048000,symbolRate:333000,fec:'1/2',offset:0});
          });
        }''')
        print('DEMOD',json.dumps(result),flush=True)
        assert result['bytes']>150000, result
        received=await page.evaluate('Array.from(window.testTS)')
        Path('/tmp/dvbs-browser-received.ts').write_bytes(bytes(received))
        media=await page.evaluate('''async()=>await new Promise((resolve,reject)=>{
          const w=new Worker('media-worker.js');let timer=setTimeout(()=>reject(Error('media timeout')),120000);
          w.onerror=e=>reject(Error(e.message));
          w.onmessage=({data:m})=>{if(m.type==='media'){clearTimeout(timer);w.terminate();resolve({videoBytes:m.video.byteLength,audioBytes:m.audio.byteLength});}else if(m.type==='media-error'){clearTimeout(timer);w.terminate();reject(Error(m.text));}};
          const data=window.testTS.buffer.slice(0);w.postMessage({type:'decode',data,duration:3,skip:0},[data]);
        })''')
        print('MEDIA',json.dumps(media),flush=True)
        assert media['videoBytes']>=320*240*4*5
        assert media['audioBytes']>10000
        assert not errors, errors
        await page.screenshot(path=str(ROOT/'tests/interface.png'),full_page=True)
        print('BROWSER ERRORS',errors,flush=True)
        await browser.close()

asyncio.run(main())

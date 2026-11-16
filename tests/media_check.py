#!/usr/bin/env python3
"""Browser H.264/AAC and HEVC/AAC media decoder regression checks."""
import asyncio,json,subprocess,sys
from pathlib import Path
from playwright.async_api import async_playwright
from browser_support import browser_binary
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from test_source import test_source
async def main():
 results=[]
 for codec in ['h264','hevc']:
  args=['ffmpeg','-v','error','-i',str(test_source()),'-t','2','-c:v','libx264' if codec=='h264' else 'libx265','-preset','ultrafast']
  args+=['-tune','zerolatency'] if codec=='h264' else ['-x265-params','pools=1:log-level=error']
  subprocess.run(args+['-c:a','aac','-b:a','32k','-f','mpegts','-y','/tmp/dvbs-'+codec+'.ts'],check=True)
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path=browser_binary(),args=['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
  page=await browser.new_page();await page.goto('http://127.0.0.1:8090')
  for codec in ['h264','hevc']:
   raw=Path('/tmp/dvbs-'+codec+'.ts').read_bytes()
   await page.route('**/media-fixture.ts',lambda route:route.fulfill(body=raw,content_type='video/mp2t'))
   result=await page.evaluate('''async()=>{
    const data=await(await fetch('/media-fixture.ts')).arrayBuffer();
    return await new Promise((resolve,reject)=>{
     const worker=new Worker('media-worker.js');const timer=setTimeout(()=>reject(Error('Media timeout')),30000);
     worker.onerror=e=>reject(Error(e.message));worker.onmessage=({data:m})=>{
      if(m.type==='media'){clearTimeout(timer);worker.terminate();resolve({videoBytes:m.video.byteLength,audioBytes:m.audio.byteLength});}
      else if(m.type==='media-error'){clearTimeout(timer);worker.terminate();reject(Error(m.text));}
     };worker.postMessage({type:'decode',data,duration:2},[data]);
    });
   }''')
   result['codec']=codec;assert result['videoBytes']>320*240*4*5 and result['audioBytes']>100000,result
   results.append(result);print(json.dumps(result),flush=True)
   await page.unroute('**/media-fixture.ts')
  await browser.close()
 (ROOT/'tests/media-results.json').write_text(json.dumps(results,indent=2)+'\n')
asyncio.run(main())

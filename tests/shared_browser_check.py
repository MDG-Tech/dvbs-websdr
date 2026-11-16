#!/usr/bin/env python3
"""Two browser viewers share native decoding and receive TS, never raw IQ."""
import asyncio
import json
from pathlib import Path
import socket
from aiohttp import ClientSession
from playwright.async_api import async_playwright
from browser_support import browser_binary

ROOT=Path(__file__).resolve().parents[1]

async def main():
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    log=(ROOT/'tests/shared-browser-runtime.log').open('w')
    proc=await asyncio.create_subprocess_exec(str(ROOT/'run.sh'),'--port',str(port),
        '--replay-iq','/tmp/dvbs-shared-capture.cf32','--replay-rate','10000000',
        '--replay-center','745000000',stdout=log,stderr=log)
    url=f'http://127.0.0.1:{port}'
    try:
        async with ClientSession() as client:
            for _ in range(100):
                try:
                    if (await client.get(url+'/api/devices')).status==200:break
                except OSError:pass
                await asyncio.sleep(.1)
            async with async_playwright() as p:
                browser=await p.chromium.launch(executable_path=browser_binary(),args=[
                    '--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
                pages=[];errors=[];requests=[]
                for _ in range(2):
                    page=await browser.new_page(viewport={'width':1500,'height':1200})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('request',lambda r:requests.append(r.url))
                    await page.goto(url)
                    await page.wait_for_function('document.querySelector("#receiver").value==="replay"')
                    await page.fill('#center','745')
                    await page.select_option('#capture-rate','10000000')
                    await page.fill('#frequency','741.5')
                    await page.fill('#symbols','1500')
                    assert await page.input_value('#frequency')=='741.5'
                    await page.click('#connect');pages.append(page)
                for page in pages:
                    try:
                        await page.wait_for_function('document.querySelector("#lock").textContent.includes("TS locked")',timeout=35000)
                    except Exception:
                        print(json.dumps(dict(errors=errors,state=await page.locator('#state').text_content(),
                            profile=await page.locator('#profile').text_content(),log=await page.locator('#log').text_content())),flush=True)
                        raise
                    await page.wait_for_function('document.querySelector("#media-status").textContent.includes("decoded frames")',timeout=30000)
                    await page.wait_for_function('document.querySelector("#lock").textContent.includes("TS locked") && document.querySelector("#profile").textContent.includes("8PSK 2/3")',timeout=20000)
                    assert await page.inner_text('#viewers')=='2'
                    assert '8PSK 2/3' in await page.inner_text('#profile')
                    assert '333' in await page.inner_text('#profile')
                assert not any('leandvb' in r or 'decoder-worker' in r for r in requests),requests
                status=await(await client.get(url+'/api/status')).json()
                assert len(status['captures'])==1 and len(status['captures'][0]['channels'])==1,status
                await pages[0].click('#sound')
                assert await pages[0].inner_text('#sound')=='Mute audio'
                async with pages[0].expect_download() as download:
                    await pages[0].click('#download')
                await(await download.value).save_as('/tmp/server-browser-received.ts')
                await pages[0].screenshot(path=str(ROOT/'tests/shared-browser-interface.png'),full_page=True)
                # Waterfall-only keeps reception for other viewers; last viewer frees decoder.
                await pages[1].click('#overview');await pages[1].wait_for_timeout(300)
                status=await(await client.get(url+'/api/status')).json()
                assert status['captures'][0]['channels'][0]['viewers']==1,status
                assert await pages[1].inner_text('#connect')=='Stop receiver'
                await pages[0].click('#connect');await pages[0].wait_for_timeout(300)
                status=await(await client.get(url+'/api/status')).json()
                assert len(status['captures'])==1 and not status['captures'][0]['channels'],status
                # First viewer leaving must not disconnect the remaining overview client.
                assert await pages[1].inner_text('#connect')=='Stop receiver'
                await pages[1].click('#connect')
                assert not errors,errors
                await browser.close()
                result=dict(browser_errors=errors,browser_dvb_worker_loaded=False,
                            shared_capture=True,shared_decoder=True,video_playback=True,
                            audio_activation=True,ts_download_bytes=Path('/tmp/server-browser-received.ts').stat().st_size,
                            overview_without_decoder=True)
                (ROOT/'tests/shared-browser-results.json').write_text(json.dumps(result,indent=2)+'\n')
                print(json.dumps(result,indent=2),flush=True)
    finally:
        proc.terminate()
        try:await asyncio.wait_for(proc.wait(),10)
        except asyncio.TimeoutError:proc.kill();await proc.wait()
        log.close()

asyncio.run(main())

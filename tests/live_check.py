#!/usr/bin/env python3
"""Browser RF check. Start a finite external Pluto test before invoking this."""
import asyncio, json
from pathlib import Path
from playwright.async_api import async_playwright
from browser_support import browser_binary

ROOT=Path(__file__).resolve().parents[1]
async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=browser_binary(),
            args=['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=await browser.new_page(viewport={'width':1400,'height':1100},accept_downloads=True)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto('http://127.0.0.1:8090')
        await page.wait_for_function('document.querySelector("#receiver").value==="1:1"')
        await page.click('#bench');await page.fill('#gain','60');await page.click('#connect')
        try:
            await page.wait_for_function('document.querySelector("#lock").textContent.includes("TS locked")',timeout=12000)
            # Exercise actual waterfall click tuning, displaced about 5 kHz.
            plot=await page.locator('#waterfall').bounding_box()
            await page.mouse.click(plot['x']+plot['width']*(.5+5000/2048000),plot['y']+70)
            await page.wait_for_function('document.querySelector("#lock").textContent.includes("TS locked")',timeout=12000)
            await page.click('#sound')
            assert await page.inner_text('#sound')=='Mute audio'
            for _ in range(6):
                await page.wait_for_timeout(2500)
                stats=await page.evaluate('Object.fromEntries(["state","lock","packets","tei","queue","mer","frequency","media-status"].map(id=>[id,document.getElementById(id).value||document.getElementById(id).textContent]))')
                print(json.dumps(stats),flush=True)
                assert 'TS locked' in stats['lock'],stats
            assert int(stats['packets'].replace(',',''))>2000
            assert 'decoded frames' in stats['media-status']
            async with page.expect_download() as download:
                await page.click('#download')
            await (await download.value).save_as('/tmp/dvbs-live-browser.ts')
            await page.screenshot(path=str(ROOT/'tests/live-interface.png'),full_page=True)
            assert not errors,errors
            (ROOT/'tests/live-stats.json').write_text(json.dumps(stats,indent=2)+'\n')
            print('PASS: RF decode, waterfall click retune, browser playback, audio activation, TS download',flush=True)
        finally:
            if await page.inner_text('#connect')=='Stop receiver':await page.click('#connect')
            await browser.close()

asyncio.run(main())

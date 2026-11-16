#!/usr/bin/env python3
"""Receive-only QO-100 default startup, live retune and IF preset UI checks."""
import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright
from browser_support import browser_binary
ROOT=Path(__file__).resolve().parents[1]
async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path=browser_binary(),args=['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
  page=await browser.new_page(viewport={'width':1500,'height':1200});errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  await page.goto('http://127.0.0.1:8090');await page.wait_for_function('document.querySelector("#receiver").value==="1:1"')
  assert await page.input_value('#standard')=='DVB-S2'
  assert await page.input_value('#capture-rate')=='10000000'
  assert '10491.500000' in await page.inner_text('#tuned')
  await page.click('#connect');await page.wait_for_timeout(8000)
  assert await page.inner_text('#connect')=='Stop receiver',await page.inner_text('#state')
  await page.click('#qo');await page.wait_for_timeout(4000)
  assert await page.input_value('#symbols')=='333'
  assert await page.inner_text('#connect')=='Stop receiver',await page.inner_text('#log')
  plot=await page.locator('#waterfall').bounding_box()
  await page.mouse.click(plot['x']+plot['width']*.65,plot['y']+50)
  await page.wait_for_timeout(3000)
  assert await page.inner_text('#connect')=='Stop receiver',await page.inner_text('#log')
  await page.screenshot(path=str(ROOT/'tests/qo100-interface.png'),full_page=True)
  await page.click('#connect');await page.click('#bench')
  assert await page.input_value('#center')=='739'
  assert await page.input_value('#standard')=='DVB-S'
  assert not errors,errors
  print('PASS: QO-100 default, 10 MS/s overview, live QO-100 preset, waterfall retune, direct IF preset; no page errors.')
  await browser.close()
asyncio.run(main())

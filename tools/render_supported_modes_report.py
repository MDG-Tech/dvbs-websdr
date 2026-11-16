#!/usr/bin/env python3
"""Render the supported-modes report to PDF using the installed Chromium."""
import asyncio
from pathlib import Path
import sys
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tests'))
from browser_support import browser_binary

async def main():
    source = ROOT/'reports/supported-modes.html'
    output = ROOT/'reports/QO100-WebSDR-Supported-Modes.pdf'
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_binary(), args=['--no-sandbox'])
        page = await browser.new_page()
        await page.goto(source.as_uri(), wait_until='load')
        await page.emulate_media(media='print')
        await page.pdf(path=str(output), format='A4', prefer_css_page_size=True,
            print_background=True, display_header_footer=True, header_template='<span></span>',
            footer_template='''<div style="font-family:sans-serif;font-size:8px;color:#647587;width:100%;padding:0 16mm;display:flex;justify-content:space-between;">
              <span>QO-100 WebSDR · Supported modes · code d9a33cb</span>
              <span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>''')
        await browser.close()
    print(output)

asyncio.run(main())

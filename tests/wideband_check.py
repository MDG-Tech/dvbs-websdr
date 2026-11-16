#!/usr/bin/env python3
"""Receive-only 10 MS/s shared overview with no raw IQ sent to clients."""
import asyncio,json,time
from aiohttp import ClientSession,WSMsgType
async def main():
    async with ClientSession('http://127.0.0.1:8090') as client:
        devices=await(await client.get('/api/devices')).json()
        device=next((d for d in devices if d.get('preferred')),devices[0])
        settings=dict(device=device['id'],frequency=745e6,rate=10000000,gain=40,tune=741.5e6,
                      symbols=1500000,standard='DVB-S2',auto_symbols=False,modcod=8,overview=True)
        first=await client.ws_connect('/stream');await first.send_json(settings)
        second=await client.ws_connect('/stream');await second.send_json(settings)
        counts=[0,0];capture=None
        async def consume(ws,index):
            nonlocal capture
            async for message in ws:
                if message.type==WSMsgType.BINARY:
                    assert message.data[:1]==b'F' and len(message.data)==2049
                    counts[index]+=1
                elif message.type==WSMsgType.TEXT:
                    data=json.loads(message.data)
                    assert data['type']!='error',data
                    if data['type']=='capture':capture=data
        tasks=[asyncio.create_task(consume(first,0)),asyncio.create_task(consume(second,1))]
        try:
            await asyncio.sleep(7)
            status=await(await client.get('/api/status')).json()
            assert len(status['captures'])==1 and status['captures'][0]['viewers']==2,status
            assert not status['captures'][0]['channels']
            assert min(counts)>35,counts
            assert capture and capture['samples']/capture['seconds']>9e6,capture
            await first.close();before=counts[1];await asyncio.sleep(1)
            assert counts[1]>before
            print(json.dumps(dict(fft_frames=counts,bytes_per_fft=2049,capture=capture,
                 shared_capture=True,no_iq_or_ts_in_overview=True),indent=2),flush=True)
        finally:
            await first.close();await second.close()
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
asyncio.run(main())

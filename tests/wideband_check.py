#!/usr/bin/env python3
"""Receive-only 10 MS/s overview and selected-channel retuning check."""
import asyncio,json,time
from aiohttp import ClientSession,WSMsgType
async def main():
    async with ClientSession('http://127.0.0.1:8090') as client:
        async with client.ws_connect('/iq') as ws:
            await ws.send_json(dict(device='1:1',frequency=745000000,rate=10000000,gain=40,wide=True,tune=747250000,symbols=333000))
            sequence=0;spectra=0;channels=[];samples=0;start=time.monotonic();retuned=False;last_throughput=None
            async with asyncio.timeout(15):
                while time.monotonic()-start<10:
                    message=await ws.receive()
                    if message.type==WSMsgType.BINARY:
                        sequence+=1;samples+=len(message.data)//8
                        await ws.send_json(dict(type='ack',sequence=sequence))
                    elif message.type==WSMsgType.TEXT:
                        data=json.loads(message.data)
                        if data['type']=='log':print(data['text'],flush=True)
                        if data['type']=='error':raise RuntimeError(data['text'])
                        if data['type']=='spectrum':
                            assert len(data['db'])==2048;spectra+=1
                        if data['type']=='channel':channels.append(data)
                        if data['type']=='throughput':last_throughput=data
                    else:raise RuntimeError(f'Unexpected close: {message}')
                    if not retuned and time.monotonic()-start>4:
                        await ws.send_json(dict(type='tune',tune=741500000,symbols=1500000,rolloff=.35));retuned=True
            assert len(channels)==2 and abs(channels[0]['rate']-10000000/13)<1 and abs(channels[1]['rate']-10000000/3)<1,channels
            assert spectra>40 and samples>4000000
            print(json.dumps(dict(channels=channels,spectra=spectra,channel_samples=samples,throughput=last_throughput),indent=2))
asyncio.run(main())

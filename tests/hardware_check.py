#!/usr/bin/env python3
"""Receive-only multi-user sharing and release checks on both physical SDRs."""
import asyncio,json
from pathlib import Path
from aiohttp import ClientSession,WSMsgType

async def receive_fft(ws, count=4):
    received=0
    async with asyncio.timeout(10):
        while received<count:
            message=await ws.receive()
            if message.type==WSMsgType.BINARY:
                assert message.data[:1]==b'F' and len(message.data)==2049
                received+=1
            elif message.type==WSMsgType.TEXT:
                data=json.loads(message.data)
                assert data['type']!='error',data
    return received

async def main():
    async with ClientSession('http://127.0.0.1:8090') as client:
        devices=await(await client.get('/api/devices')).json()
        assert devices,'At least one SDRone is required'
        for device in devices:
            settings=dict(device=device['id'],frequency=739e6,rate=2048000,gain=40,
                          tune=739e6,symbols=333000,overview=True)
            first=await client.ws_connect('/stream');await first.send_json(settings)
            await receive_fft(first)
            second=await client.ws_connect('/stream');await second.send_json(settings)
            await receive_fft(second)
            status=await(await client.get('/api/status')).json()
            capture=next(s for s in status['captures'] if s['device']==device['id'])
            assert capture['viewers']==2 and not capture['channels'],capture
            assert len(status['captures'])==1,status
            other=next((d for d in devices if d['id']!=device['id']),None)
            if other:
                # A second connected SDR must not be opened for additional users.
                async with client.ws_connect('/stream') as extra:
                    await extra.send_json({**settings,'device':other['id']})
                    async with asyncio.timeout(5):
                        async for message in extra:
                            if message.type==WSMsgType.TEXT:
                                data=json.loads(message.data)
                                if data['type']=='error':
                                    assert 'One SDR supplies all users' in data['text'];break
                assert len((await(await client.get('/api/status')).json())['captures'])==1
            await first.close();await receive_fft(second)
            status=await(await client.get('/api/status')).json()
            assert next(s for s in status['captures'] if s['device']==device['id'])['viewers']==1
            await second.close()
            async with asyncio.timeout(8):
                while not Path('/sys/bus/usb/devices/'+device['port']+':1.0/driver').exists():
                    await asyncio.sleep(.1)
            print(json.dumps(dict(device=device,shared_capture=True,remaining_viewer_continues=True,
                                  driver_restored=True)),flush=True)
        async with asyncio.timeout(8):
            while (await(await client.get('/api/status')).json())['captures']:
                await asyncio.sleep(.1)
        print('PASS: each available SDR tested sequentially; one capture shared by two viewers; Linux drivers restored')
asyncio.run(main())

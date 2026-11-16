#!/usr/bin/env python3
"""Receive-only hardware selection, exclusive ownership and release checks."""
import asyncio, json
from aiohttp import ClientSession, WSMsgType

async def receive_radio(ws):
    blocks=0;radio=None
    async with asyncio.timeout(8):
        while blocks<12 or radio is None:
            msg=await ws.receive()
            if msg.type==WSMsgType.BINARY:
                assert len(msg.data)==262144
                blocks+=1
                await ws.send_json(dict(type='ack',sequence=blocks))
            elif msg.type==WSMsgType.TEXT:
                data=json.loads(msg.data)
                if data['type']=='error':raise RuntimeError(data['text'])
                if data['type']=='radio':radio=data
    return radio,blocks

async def main():
    async with ClientSession('http://127.0.0.1:8090') as session:
        devices=await (await session.get('/api/devices')).json()
        assert len(devices)>=2
        for device in devices:
            settings=dict(device=device['id'],frequency=739000000,rate=2048000,gain=40)
            async with session.ws_connect('/iq') as ws:
                await ws.send_json(settings)
                radio,blocks=await receive_radio(ws)
                assert radio['device']['id']==device['id']
                async with session.ws_connect('/iq') as other:
                    await other.send_json(settings)
                    error=await other.receive_json()
                    assert error['type']=='error' and 'already in use' in error['text']
                print(json.dumps(dict(device=radio['device'],blocks=blocks,exclusive_ownership=True)),flush=True)
            # Wait for explicit device availability by trying a fresh connection.
            for _ in range(30):
                await asyncio.sleep(.1)
                if __import__('pathlib').Path('/sys/bus/usb/devices/'+device['port']+':1.0/driver').exists():break
            else:raise AssertionError('Linux driver was not restored')
        print('Both receivers opened, delivered IQ, rejected duplicate ownership, and restored Linux drivers.')

asyncio.run(main())

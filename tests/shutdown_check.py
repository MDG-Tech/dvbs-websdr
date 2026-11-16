#!/usr/bin/env python3
"""Active native decoder and WebSocket must be cleaned up on server shutdown."""
import asyncio,json,socket
from pathlib import Path
from aiohttp import ClientSession,WSMsgType
ROOT=Path(__file__).resolve().parents[1]
async def main():
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    log=(ROOT/'tests/shutdown-runtime.log').open('w')
    proc=await asyncio.create_subprocess_exec(str(ROOT/'run.sh'),'--port',str(port),
        '--replay-iq','/tmp/dvbs-qpsk-normal-125k.cf32','--replay-rate','500000',
        '--replay-center','739000000',stdout=log,stderr=log)
    children=[]
    try:
        async with ClientSession(f'http://127.0.0.1:{port}') as client:
            for _ in range(100):
                try:
                    if (await client.get('/api/devices')).status==200:break
                except OSError:pass
                await asyncio.sleep(.1)
            async with client.ws_connect('/stream') as ws:
                await ws.send_json(dict(device='replay',frequency=739e6,rate=500000,gain=40,tune=739e6,
                                        symbols=125000,standard='Auto',auto_symbols=True,fec='Auto'))
                async with asyncio.timeout(15):
                    while True:
                        message=await ws.receive()
                        if message.type==WSMsgType.TEXT:
                            data=json.loads(message.data)
                            if data['type']=='decoder' and data['state']=='locked':break
                children=[int(p) for p in Path(f'/proc/{proc.pid}/task/{proc.pid}/children').read_text().split()]
                assert children
                proc.terminate()
                await asyncio.wait_for(proc.wait(),8)
                assert all(not Path(f'/proc/{pid}').exists() for pid in children),children
                print('PASS: SIGTERM with active viewer releases and reaps native decoder; server exits cleanly',flush=True)
    finally:
        if proc.returncode is None:
            proc.kill();await proc.wait()
        log.close()
asyncio.run(main())

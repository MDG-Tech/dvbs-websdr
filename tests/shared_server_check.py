#!/usr/bin/env python3
"""End-to-end native auto-detection, shared capture/decoder and TS fan-out."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import time
from aiohttp import ClientSession, WSMsgType

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tools'))
from transport import TransportValidator
from test_source import test_source


class Consumer:
    def __init__(self, ws):
        self.ws=ws;self.ts=bytearray();self.fft=0;self.detected=None;self.channel=None
        self.selected=asyncio.Event();self.locked=asyncio.Event();self.errors=[];self.binary_types=set()
        self.task=asyncio.create_task(self.read())
    async def read(self):
        async for message in self.ws:
            if message.type==WSMsgType.TEXT:
                data=json.loads(message.data)
                if data['type'] in ('error','selection_error'):self.errors.append(data['text'])
                if data['type']=='selected':
                    self.channel=data.get('channel');self.selected.set()
                if data['type']=='decoder' and data['state']=='locked':
                    self.detected=data;self.locked.set()
            elif message.type==WSMsgType.BINARY:
                self.binary_types.add(message.data[:1])
                if message.data[:1]==b'T':self.ts.extend(message.data[1:])
                elif message.data[:1]==b'F':
                    assert len(message.data)==2049;self.fft+=1
                else:raise AssertionError('IQ or unknown binary frame sent to viewer')
    async def close(self):
        await self.ws.close();await self.task


async def run():
    server_log=(ROOT/'tests/shared-server-runtime.log').open('w')
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    proc=await asyncio.create_subprocess_exec(str(ROOT/'run.sh'),'--port',str(port),'--max-channels','2',
        '--replay-iq','/tmp/dvbs-shared-capture.cf32','--replay-rate','10000000','--replay-center','745000000',
        stdout=server_log,stderr=server_log)
    result={}
    consumers=[]
    async with ClientSession(f'http://127.0.0.1:{port}') as client:
        try:
            for _ in range(100):
                try:
                    if (await client.get('/api/devices')).status==200:break
                except OSError:pass
                await asyncio.sleep(.1)
            else:raise AssertionError('Replay server did not start')
            async def connect(tune, **extra):
                ws=await client.ws_connect('/stream')
                consumer=Consumer(ws);consumers.append(consumer)
                settings=dict(device='replay',frequency=745e6,rate=10000000,gain=40,tune=tune,
                    symbols=1500000,standard='Auto',auto_symbols=True,fec='Auto')
                settings.update(extra)
                await ws.send_json(settings)
                await asyncio.wait_for(consumer.selected.wait(),5)
                return consumer
            first=await connect(741500000)
            await asyncio.wait_for(first.locked.wait(),25)
            assert first.detected['profile']['standard']=='DVB-S2',first.detected
            assert first.detected['profile']['modcod']==13,first.detected
            assert first.detected['profile']['symbols']==333000,first.detected
            second=await connect(741501000,standard='DVB-S2',auto_symbols=False,symbols=333000,modcod=13)
            await asyncio.wait_for(second.locked.wait(),5)
            status=await(await client.get('/api/status')).json()
            assert len(status['captures'])==1 and len(status['captures'][0]['channels'])==1,status
            assert status['captures'][0]['channels'][0]['viewers']==2,status
            assert first.channel==second.channel,(first.channel,second.channel)
            independent=await connect(748250000)
            await asyncio.wait_for(independent.locked.wait(),35)
            assert independent.detected['profile']['standard']=='DVB-S',independent.detected
            assert independent.detected['profile']['symbols']==333000,independent.detected
            assert independent.detected['profile']['fec']=='1/2',independent.detected
            status=await(await client.get('/api/status')).json()
            assert len(status['captures'])==1 and len(status['captures'][0]['channels'])==2,status
            # Decoder cap rejects a new job without changing existing viewers.
            extra_ws=await client.ws_connect('/stream')
            await extra_ws.send_json(dict(device='replay',frequency=745e6,rate=10000000,gain=40,
                tune=745000000,symbols=33000,standard='Auto',auto_symbols=False,fec='Auto'))
            async with asyncio.timeout(5):
                async for message in extra_ws:
                    if message.type==WSMsgType.TEXT and json.loads(message.data)['type']=='error':
                        assert 'capacity' in json.loads(message.data)['text'];break
            await extra_ws.close()
            await asyncio.sleep(3)
            reference=test_source().read_bytes();packets={reference[i:i+188] for i in range(0,len(reference),188)}
            for index,consumer in enumerate(consumers):
                assert not consumer.errors,consumer.errors
                assert len(consumer.ts)>10000 and consumer.fft>10,(len(consumer.ts),consumer.fft)
                validator=TransportValidator();validator.feed(consumer.ts)
                assert validator.confirmed and validator.bad_sync==0
                recovered=[consumer.ts[i:i+188] for i in range(0,len(consumer.ts),188)]
                matches=sum(bytes(p) in packets for p in recovered)
                assert matches>=len(recovered)-5,(matches,len(recovered))
                result[f'viewer{index+1}']=dict(profile=consumer.detected['profile'],packets=len(recovered),
                    source_matches=matches,fft_frames=consumer.fft,binary_types=[x.decode() for x in consumer.binary_types])
            # Retuning one viewer doesn't disturb the original signal's decoder.
            await second.ws.send_json(dict(type='tune',tune=748250000,symbols=1500000,
                standard='Auto',auto_symbols=True,fec='Auto'))
            await asyncio.sleep(.5)
            status=await(await client.get('/api/status')).json()
            assert sorted(j['viewers'] for j in status['captures'][0]['channels'])==[1,2],status
            before=len(first.ts);await independent.close();await asyncio.sleep(.5)
            assert len(first.ts)>before
            await second.close();await asyncio.sleep(.5)
            status=await(await client.get('/api/status')).json()
            assert len(status['captures'][0]['channels'])==1,status
            before=len(first.ts);await asyncio.sleep(.5);assert len(first.ts)>before
            await first.close()
            async with asyncio.timeout(8):
                while (await(await client.get('/api/status')).json())['captures']:
                    await asyncio.sleep(.1)
            result['shared_capture']=True;result['shared_decoder']=True
            result['independent_retuning']=True;result['last_viewer_cleanup']=True
            (ROOT/'tests/shared-server-results.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result,indent=2),flush=True)
        finally:
            for consumer in consumers:
                await consumer.close()
            proc.terminate()
            try:await asyncio.wait_for(proc.wait(),10)
            except asyncio.TimeoutError:proc.kill();await proc.wait()
            server_log.close()

asyncio.run(run())

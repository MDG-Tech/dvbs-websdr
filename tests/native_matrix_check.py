#!/usr/bin/env python3
"""Confirm native Auto detection on representative S2 modulations and rates."""
import asyncio
import json
from pathlib import Path
import socket
import sys
from aiohttp import ClientSession, WSMsgType

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from test_source import test_source

async def main():
    profiles=json.loads(Path('/tmp/dvbs-s2-fixtures.json').read_text())
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--only');options=parser.parse_args()
    names=['qpsk-short-33k','qpsk-normal-125k','16apsk-normal-500k',
           'beacon-normal-1500k','32apsk-normal-2000k']
    reference=test_source().read_bytes();source={reference[i:i+188] for i in range(0,len(reference),188)}
    results=[]
    import subprocess
    fec_path='/tmp/dvbs-fec34.cf32'
    with open(fec_path,'wb') as output:
        subprocess.run([str(ROOT/'native/leandvbtx-s2'),'--standard','DVB-S','--cr','3/4','-f','4','--rrc-rej','30'],input=reference,stdout=output,check=True)
    profiles.append(dict(name='dvbs-fec34',path=fec_path,rate=1332000,symbolRate=333000,standard='DVB-S',fec='3/4'))
    names.append('dvbs-fec34')
    for profile in [p for p in profiles if p['name'] in names and (not options.only or p['name']==options.only)]:
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        log=(ROOT/'tests/native-matrix-runtime.log').open('a')
        proc=await asyncio.create_subprocess_exec(str(ROOT/'run.sh'),'--port',str(port),
            '--replay-iq',profile['path'],'--replay-rate',str(profile['rate']),
            '--replay-center','739000000',stdout=log,stderr=log)
        try:
            async with ClientSession(f'http://127.0.0.1:{port}') as c:
                for _ in range(100):
                    try:
                        if (await c.get('/api/devices')).status==200:break
                    except OSError:pass
                    await asyncio.sleep(.1)
                data=bytearray();detected=None
                async with c.ws_connect('/stream') as ws:
                    # Deliberately misleading rate hint: classification uses the spectrum.
                    await ws.send_json(dict(device='replay',frequency=739e6,rate=profile['rate'],
                        gain=40,tune=739e6,symbols=333000,standard='Auto',auto_symbols=True,fec='Auto'))
                    async with asyncio.timeout(35):
                        while len(data)<12000 or detected is None:
                            message=await ws.receive()
                            if message.type==WSMsgType.TEXT:
                                m=json.loads(message.data)
                                if m['type']=='error':raise AssertionError(m)
                                if m['type']=='decoder' and m['state']=='locked':detected=m
                            elif message.type==WSMsgType.BINARY and message.data[:1]==b'T':
                                data.extend(message.data[1:])
                    assert detected['profile']['standard']==profile.get('standard','DVB-S2')
                    assert detected['profile']['symbols']==profile['symbolRate'],detected
                    if profile.get('standard')=='DVB-S':assert detected['profile']['fec']==profile['fec'],detected
                    else:assert detected['profile']['modcod']==profile['modcod'],detected
                    packets=[bytes(data[i:i+188]) for i in range(0,len(data),188)]
                    assert all(p in source for p in packets),(profile['name'],len(packets))
                    result=dict(name=profile['name'],profile=detected['profile'],packets=len(packets),
                        source_matches=len(packets),trial=detected['trial'])
                    results.append(result);print(json.dumps(result),flush=True)
        finally:
            proc.terminate()
            try:await asyncio.wait_for(proc.wait(),10)
            except asyncio.TimeoutError:proc.kill();await proc.wait()
            log.close()
    output=ROOT/'tests/native-matrix-results.json'
    if options.only and output.exists():results=[p for p in json.loads(output.read_text()) if p['name']!=options.only]+results
    output.write_text(json.dumps(results,indent=2)+'\n')

asyncio.run(main())

#!/usr/bin/env python3
"""Acquisition bounds, PSI validation and isolated slow-client budgets."""
import asyncio
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from detection import Selection, acquisition_plan, estimate_signal
from receiver import Viewer
from transport import TransportValidator
from test_source import test_source


class Socket:
    closed=False
    def __init__(self, stalled=False):
        self.stalled=stalled;self.sent=[];self.gate=asyncio.Event()
    async def send_bytes(self, data):
        if self.stalled:await self.gate.wait()
        self.sent.append(data)
    async def send_json(self, data):self.sent.append(data)
    async def close(self, **kwargs):self.closed=True;self.gate.set()


async def main():
    raw=test_source().read_bytes();v=TransportValidator()
    for i in range(0,len(raw),107):v.feed(raw[i:i+107])
    assert v.confirmed and v.bad_sync==0
    corrupted=bytearray(raw)
    # Corrupt every PSI payload while preserving packet sync and headers.
    for i in range(0,len(corrupted)-187,188):
        pid=((corrupted[i+1]&31)<<8)|corrupted[i+2]
        if pid in (0,4096):corrupted[i+20]^=1
    bad=TransportValidator();bad.feed(corrupted)
    assert not bad.confirmed
    noise=np.ones(16384,dtype=np.float32)*1e-6
    assert estimate_signal(noise,739e6,5e6,739e6,333000) is None
    selection=Selection.parse(dict(tune=739e6,standard='Auto',auto_symbols=True,symbols=1500000),739e6,5e6)
    plan=acquisition_plan(selection,dict(symbols=340000,center=739e6),739e6,5e6)
    assert plan[0].standard=='DVB-S2' and plan[0].symbols==333000
    assert len(plan)<=18 and any(p.standard=='DVB-S' and p.fec=='7/8' for p in plan)
    slow_socket,fast_socket=Socket(True),Socket()
    slow,fast=Viewer(slow_socket),Viewer(fast_socket)
    for _ in range(110):slow.send(b'T'+bytes(188),ts=True)
    fast.send(b'T'+bytes(188),ts=True)
    await asyncio.sleep(.05)
    assert slow.failed and slow_socket.closed and len(fast_socket.sent)==1
    await slow.close();await fast.close()
    print('PASS: fragmented TS, CRC rejection, no noise detection, bounded candidate plan, slow-client isolation')

asyncio.run(main())

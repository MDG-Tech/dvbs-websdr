#!/usr/bin/env python3
"""Compare chunked channel extraction against a continuous reference."""
import sys
from pathlib import Path
import numpy as np
from scipy.signal import lfilter,resample_poly
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from channelizer import Channelizer

rng=np.random.default_rng(123)
x=(rng.normal(size=200000)+1j*rng.normal(size=200000)).astype(np.complex64)
for symbols in [33000,125000,333000,1500000,2000000]:
    c=Channelizer(10e6,symbols,2250000)
    y=np.concatenate([c.process(x[i:i+32768]) for i in range(0,len(x),32768)])
    mixed=x*np.exp(-2j*np.pi*2250000/1e7*np.arange(len(x)))
    expected=lfilter(c.taps,[1],mixed)[::c.decimation]
    error=float(np.max(abs(y-expected)))
    assert error<2e-6,(symbols,error)
    print(symbols,error)

# The full beacon profile lies near the left edge of the 10 MHz overview.
source=np.fromfile('/tmp/dvbs-beacon-normal-1500k.cf32',dtype='<c8')
wide=resample_poly(source,5,3).astype(np.complex64)
wide*=np.exp(-2j*np.pi*3500000/1e7*np.arange(len(wide))).astype(np.complex64)
c=Channelizer(10e6,1500000,-3500000)
selected=np.concatenate([c.process(wide[i:i+32768]) for i in range(0,len(wide),32768)])
selected.tofile('/tmp/dvbs-channelized-beacon.cf32')
import json
manifest=Path('/tmp/dvbs-s2-fixtures.json');profiles=json.loads(manifest.read_text())
profiles=[p for p in profiles if p['name']!='channelized-beacon-1500k']
profiles.append(dict(name='channelized-beacon-1500k',path='/tmp/dvbs-channelized-beacon.cf32',rate=c.output_rate,symbolRate=1500000,modcod=8,short=False))
manifest.write_text(json.dumps(profiles,indent=2))

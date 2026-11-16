#!/usr/bin/env python3
"""Build a DVB-S regression fixture from pinned transmitter sources."""
import subprocess
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
from test_source import test_source
ROOT=Path(__file__).resolve().parents[1]
periodic=Path('/mnt/data/astrometa-dvbs333/periodic.iq')
if periodic.exists():
    x=np.fromfile(periodic,dtype='<i2').reshape(-1,2)
    iq=(x[:,0].astype(np.float32)+1j*x[:,1].astype(np.float32))/32768
else:
    binary=ROOT/'native/leandvbtx'
    subprocess.run(['g++','-O3','-DVERSION="e6416aa"','-I'+str(ROOT/'vendor/leansdr-dvbs'),str(ROOT/'vendor/leansdr-dvbs/apps/leandvbtx.cc'),'-o',str(binary)],check=True)
    raw=subprocess.run([str(binary),'-f','8','--cr','1/2','--rrc-rej','30'],input=test_source().read_bytes()*2,stdout=subprocess.PIPE,check=True).stdout
    iq=np.frombuffer(raw,dtype='<c8')
resample_poly(iq,256,333).astype('<c8').tofile('/tmp/dvbs-fixture.cf32')
print('Prepared /tmp/dvbs-fixture.cf32 at 2.048 MS/s')

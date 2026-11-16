#!/usr/bin/env python3
"""Resample the existing periodic bench waveform for the browser regression check."""
import numpy as np
from scipy.signal import resample_poly
from pathlib import Path
source=Path('/mnt/data/astrometa-dvbs333/periodic.iq')
x=np.fromfile(source,dtype='<i2').reshape(-1,2)
iq=(x[:,0].astype(np.float32)+1j*x[:,1].astype(np.float32))/32768
resample_poly(iq,256,333).astype('<c8').tofile('/tmp/dvbs-fixture.cf32')
print('Prepared /tmp/dvbs-fixture.cf32 at 2.048 MS/s')

#!/usr/bin/env python3
"""Two independent RF channels in one replay capture; never transmits RF."""
from pathlib import Path
import json
import numpy as np
from scipy.signal import resample_poly

rate = 10000000
length = rate*2
out = np.zeros(length, np.complex64)
for name, path, up, down, offset in [
    ('DVB-S', '/tmp/dvbs-fixture.cf32', 625, 128, 3250000),
    ('DVB-S2', '/tmp/dvbs-8psk-short-333k.cf32', 2500, 333, -3500000),
]:
    source = np.fromfile(path, dtype='<c8')
    x = resample_poly(source[:int(len(source)/2)] if name == 'DVB-S' else source, up, down).astype(np.complex64)
    if len(x) < length:
        x = np.tile(x, (length+len(x)-1)//len(x))
    x = x[:length]
    x *= np.exp(2j*np.pi*offset/rate*np.arange(length)).astype(np.complex64)
    out += x*.35
out.tofile('/tmp/dvbs-shared-capture.cf32')
Path('/tmp/dvbs-shared-capture.json').write_text(json.dumps(dict(rate=rate, center=745000000,
    channels=[dict(tune=748250000, standard='DVB-S',symbols=333000,fec='1/2'),
              dict(tune=741500000,standard='DVB-S2',symbols=333000,modcod=13)]),indent=2))
print('Prepared two-channel capture /tmp/dvbs-shared-capture.cf32')

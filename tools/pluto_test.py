#!/usr/bin/env python3
"""Finite low-power Pluto antenna test using the existing DVB-S waveform."""
import argparse
import hashlib
import json
from pathlib import Path
import signal
import time
import iio
import numpy as np

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--iq',type=Path,default=Path('/mnt/data/astrometa-dvbs333/periodic.iq'))
    p.add_argument('--uri',default='usb:1.5.5')
    p.add_argument('--frequency',type=int,default=739000000)
    p.add_argument('--seconds',type=float,default=25)
    p.add_argument('--attenuation',type=float,default=60)
    a=p.parse_args()
    if not 0<a.seconds<=30 or not 40<=a.attenuation<=89.75:
        p.error('Finite antenna test requires 0–30 seconds and 40–89.75 dB internal attenuation')
    raw=a.iq.read_bytes(); meta=json.loads(a.iq.with_suffix('.json').read_text())
    if hashlib.sha256(raw).hexdigest()!=meta['sha256']:
        raise ValueError('Waveform checksum mismatch')
    ctx=iio.Context(a.uri);phy=ctx.find_device('ad9361-phy');tx=ctx.find_device('cf-ad9361-dds-core-lpc')
    lo=phy.find_channel('altvoltage1',True);ch=phy.find_channel('voltage0',True)
    if lo.attrs['powerdown'].value!='1':
        raise RuntimeError('Pluto is already transmitting; stop its existing transmitter first')
    saved={k:ch.attrs[k].value for k in ['hardwaregain','sampling_frequency','rf_bandwidth']}
    oldlo=lo.attrs['frequency'].value; buffer=None
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    try:
        ch.attrs['hardwaregain'].value=str(-a.attenuation)
        ch.attrs['sampling_frequency'].value=str(meta['sample_rate_hz'])
        ch.attrs['rf_bandwidth'].value=str(meta['bandwidth_hz'])
        lo.attrs['frequency'].value=str(a.frequency)
        for c in tx.channels:
            if c.id in ['voltage0','voltage1']:c.enabled=True
            if c.id.startswith('altvoltage') and 'scale' in c.attrs:c.attrs['scale'].value='0'
        buffer=iio.Buffer(tx,meta['samples'],True)
        if buffer.write(bytearray(raw))!=len(raw):raise RuntimeError('Short IQ write')
        buffer.push();lo.attrs['powerdown'].value='0'
        print(json.dumps(dict(state='transmitting',frequency=a.frequency,seconds=a.seconds,attenuation=a.attenuation)),flush=True)
        time.sleep(a.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        lo.attrs['powerdown'].value='1'
        if buffer:buffer.cancel();del buffer
        restore_errors=[]
        for k,v in saved.items():
            try:
                # libiio gain readback may include units ("-10.000000 dB").
                ch.attrs[k].value=v.split()[0]
            except OSError as e:restore_errors.append(f'{k}: {e}')
        try:lo.attrs['frequency'].value=oldlo
        except OSError as e:restore_errors.append(f'frequency: {e}')
        print(json.dumps(dict(state='stopped',tx_powerdown=lo.attrs['powerdown'].value,restore_errors=restore_errors)),flush=True)

if __name__=='__main__':main()

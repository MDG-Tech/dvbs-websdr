#!/usr/bin/env python3
"""Local IQ bridge. DVB-S and media decoding happen entirely in the browser."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import time
import math

ROOT = Path(__file__).resolve().parent
os.environ.setdefault('SOAPY_SDR_PLUGIN_PATH', str(ROOT/'native/build/soapy'))
from aiohttp import web, WSMsgType, ClientConnectionError
import numpy as np
from channelizer import Channelizer


def devices():
    import SoapySDR as S
    found = []
    for d in S.Device.enumerate('driver=soapyMiri'):
        d = dict(d)
        bus, ports = d['serial'].split(':')
        node = Path('/sys/bus/usb/devices') / (bus + '-' + ports)
        try:
            address = int((node / 'devnum').read_text())
        except (OSError, ValueError):
            continue
        found.append(dict(id=d['serial'], index=d['index'], bus=int(bus), address=address,
                          port=node.name, label=f'SDRone / RSP1 · USB {int(bus):03}:{address:03} · port {node.name}',
                          preferred=int(bus)==1 and address==10))
    return found


def capture(args):
    """Isolated native driver process, with stdout reserved for float32 IQ."""
    import SoapySDR as S
    import numpy as np
    stop = False
    def stopping(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    available = devices()
    selected = next((d for d in available if d['id'] == args.device), None)
    if selected is None:
        raise RuntimeError('Selected USB port is no longer available')
    s = S.Device(f"driver=soapyMiri,index={selected['index']},serial={selected['id']}")
    rx = S.SOAPY_SDR_RX
    stream = None
    try:
        s.setSampleRate(rx, 0, args.rate)
        s.setBandwidth(rx, 0, 14000000 if args.rate>=9e6 else
                       8000000 if args.rate>=5e6 else 1536000)
        s.setFrequency(rx, 0, args.frequency)
        s.setGainMode(rx, 0, False)
        s.setGain(rx, 0, args.gain)
        s.writeSetting('biastee', 'false')
        stream = s.setupStream(rx, S.SOAPY_SDR_CF32, [0],
            dict(transfer='ISOC',buffers='128',bufflen='147456',asyncBuffs='16'))
        s.activateStream(stream)
        print(json.dumps(dict(type='radio',rate=s.getSampleRate(rx,0),frequency=s.getFrequency(rx,0),
                              gain=s.getGain(rx,0,'Automatic'),device=selected)), file=sys.stderr, flush=True)
        b = np.empty(32768, np.complex64)
        while not stop:
            result = s.readStream(stream, [b], len(b), timeoutUs=200000)
            if result.ret > 0:
                sys.stdout.buffer.write(b[:result.ret].astype('<c8', copy=False).tobytes())
                sys.stdout.buffer.flush()
            elif result.ret != S.SOAPY_SDR_TIMEOUT:
                # Never silently splice discontinuous samples into the decoder.
                raise RuntimeError(f'Receiver stream discontinuity: {result.ret}')
    finally:
        if stream is not None:
            s.deactivateStream(stream)
            s.closeStream(stream)
        # The Python binding owns the device and invokes unmake in __del__.
        del s


async def api_devices(request):
    return web.json_response(await asyncio.to_thread(devices))


async def websocket(request):
    # Prevent arbitrary websites from opening the local receiver through a browser.
    origin = request.headers.get('Origin')
    if origin and origin != f'{request.scheme}://{request.host}':
        raise web.HTTPForbidden(text='Same-origin receiver access required')
    # IQ is effectively incompressible; per-message deflate wastes CPU and adds jitter.
    ws = web.WebSocketResponse(max_msg_size=4096, heartbeat=20, compress=False)
    await ws.prepare(request)
    proc = None
    reserved = None
    tasks = []
    try:
        msg = await asyncio.wait_for(ws.receive_json(), 15)
        receiver = str(msg['device'])
        if receiver not in [d['id'] for d in await asyncio.to_thread(devices)]:
            raise ValueError('Unknown receiver; refresh the receiver list')
        if receiver in request.app['busy']:
            raise ValueError('Receiver is already in use by another browser')
        frequency, rate, gain = float(msg['frequency']), float(msg['rate']), float(msg['gain'])
        if not (50e6 <= frequency <= 2e9 and rate in (1536000,2048000,5000000,8000000,10000000) and 0 <= gain <= 103):
            raise ValueError('Invalid frequency, sample rate, or gain')
        wide=bool(msg.get('wide',False))
        def channel_parameters(command):
            target=float(command.get('tune',frequency))
            symbol=float(command.get('symbols',333000))
            rolloff=float(command.get('rolloff',.35))
            if not (10000<=symbol<=2000000 and rolloff in (.20,.25,.35) and
                    math.isfinite(target) and abs(target-frequency)+symbol*(1+rolloff)/2<rate*.48):
                raise ValueError('Selected channel is outside usable capture bandwidth')
            return target,symbol
        target,symbol=channel_parameters(msg)
        request.app['busy'].add(receiver)
        reserved = receiver
        proc = await asyncio.create_subprocess_exec(sys.executable, str(ROOT/'server.py'), '--capture',
            '--device',receiver,'--frequency',str(frequency),'--rate',str(rate),'--gain',str(gain),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=524288)
        async def logs():
            async for line in proc.stderr:
                text = line.decode(errors='replace').strip()
                try:
                    data = json.loads(text)
                except ValueError:
                    data = dict(type='log',text=text)
                await ws.send_json(data)
        async def samples():
            # Bound network backlog separately from the browser's DSP queue.
            sequence = 0
            started = time.monotonic()
            channel=None;version=-1;last_fft=0
            if wide:
                import numpy as np
                from channelizer import Channelizer
            while True:
                data = await proc.stdout.readexactly(32768*8)
                if sequence==0:
                    started=time.monotonic()
                if wide:
                    iq=np.frombuffer(data,dtype='<c8')
                    if time.monotonic()-last_fft>.1:
                        window=np.hanning(4096).astype(np.float32)
                        section=iq[:4096]-iq[:4096].mean()
                        spectrum=20*np.log10(np.abs(np.fft.fftshift(np.fft.fft(section*window)))/2048+1e-12)
                        await ws.send_json(dict(type='spectrum',db=spectrum[::2].round(2).tolist()))
                        last_fft=time.monotonic()
                    if state['generation']!=version:
                        version=state['generation']
                        target,symbol=state['channel']
                        channel=Channelizer(rate,symbol,target-frequency)
                        await ws.send_json(dict(type='channel',rate=channel.output_rate,tune=target,generation=version))
                    data=(await asyncio.to_thread(channel.process,iq)).tobytes()
                if sequence - state['ack'] > math.ceil(2*rate/32768)+8:
                    raise RuntimeError('Browser cannot keep up; IQ stream stopped. Reconnect to reacquire.')
                await asyncio.wait_for(ws.send_bytes(data), 3)
                sequence += 1
                state['sent'] = sequence
                if sequence % 64 == 0:
                    await ws.send_json(dict(type='throughput',samples=sequence*32768,
                                            seconds=time.monotonic()-started))
        state = dict(ack=0, sent=0,generation=0,channel=(target,symbol))
        async def commands():
            async for incoming in ws:
                if incoming.type == WSMsgType.TEXT:
                    command = json.loads(incoming.data)
                    if command.get('type') == 'ack':
                        state['ack'] = min(state['sent'], max(state['ack'], int(command['sequence'])))
                    elif command.get('type')=='tune' and wide:
                        state['channel']=channel_parameters(command)
                        state['generation']+=1
                elif incoming.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break
        tasks = [asyncio.create_task(fn()) for fn in (logs, samples, commands)]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (ClientConnectionError, ConnectionResetError):
        pass
    except asyncio.IncompleteReadError:
        if not ws.closed:
            await ws.send_json(dict(type='error',text='Receiver stopped; see hardware log.'))
    except (ValueError, KeyError, RuntimeError, asyncio.TimeoutError) as e:
        if not ws.closed:
            await ws.send_json(dict(type='error',text=str(e)))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if proc and proc.returncode is None:
            proc.terminate()
            async def drain():
                while await proc.stdout.read(262144):
                    pass
            draining=asyncio.create_task(drain())
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            finally:
                draining.cancel()
                await asyncio.gather(draining, return_exceptions=True)
        if reserved:
            request.app['busy'].discard(reserved)
        await ws.close()
    return ws


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8090)
    p.add_argument('--capture', action='store_true')
    p.add_argument('--device')
    p.add_argument('--frequency', type=float, default=739e6)
    p.add_argument('--rate', type=float, default=2048000)
    p.add_argument('--gain', type=float, default=40)
    a = p.parse_args()
    if a.capture:
        capture(a)
        return
    app = web.Application()
    app['busy'] = set()
    app.router.add_get('/api/devices', api_devices)
    app.router.add_get('/iq', websocket)
    app.router.add_get('/', lambda _: web.FileResponse(ROOT/'web/index.html'))
    app.router.add_static('/', ROOT/'web', show_index=False)
    web.run_app(app, host=a.host, port=a.port)

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Shared SDR capture and native DVB-S/S2 decoding; MPEG-TS and FFT go to browsers."""
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
from receiver import ReceiverHub, Viewer


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
    hub = request.app['hub']
    if hub.replay:
        return web.json_response([dict(id='replay', label='IQ fixture replay — not live RF', preferred=True)])
    found = await asyncio.to_thread(devices)
    active_device = next(iter(hub.sessions), None)
    for device in found:
        active = hub.sessions.get(device['id'])
        device['active'] = active.config() if active else None
        device['selectable'] = active_device is None or active_device == device['id']
    return web.json_response(found)


async def websocket(request):
    origin = request.headers.get('Origin')
    if origin and origin != f'{request.scheme}://{request.host}':
        raise web.HTTPForbidden(text='Same-origin receiver access required')
    ws = web.WebSocketResponse(max_msg_size=4096, heartbeat=20, compress=False)
    await ws.prepare(request)
    viewer = Viewer(ws)
    hub = request.app['hub']
    try:
        data = await asyncio.wait_for(ws.receive_json(), 15)
        available = ['replay'] if hub.replay else [d['id'] for d in await asyncio.to_thread(devices)]
        if str(data['device']) not in available:
            raise ValueError('Unknown receiver; refresh the receiver list')
        await hub.attach(viewer, data)
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                try:
                    command = json.loads(message.data)
                    if command.get('type') == 'tune':
                        await hub.select(viewer, command)
                    elif command.get('type') == 'overview':
                        await hub.overview(viewer)
                    elif command.get('type') == 'status':
                        viewer.send(dict(type='server', captures=hub.snapshot()))
                except (ValueError, KeyError, TypeError) as e:
                    viewer.send(dict(type='selection_error', text=str(e)))
            elif message.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
    except (ClientConnectionError, ConnectionError):
        pass
    except (ValueError, KeyError, TypeError, RuntimeError, asyncio.TimeoutError) as e:
        if not ws.closed:
            await ws.send_json(dict(type='error', text=str(e)))
    finally:
        await hub.detach(viewer)
        await viewer.close()
        await ws.close()
    return ws


async def api_status(request):
    return web.json_response(dict(captures=request.app['hub'].snapshot()))


async def cleanup(app):
    await app['hub'].close()


async def shutdown(app):
    hub = app['hub']
    viewers = [v for s in hub.sessions.values() for v in s.viewers]
    # Release native processes/hardware before waiting for WebSocket handshakes.
    await hub.close()
    try:
        await asyncio.wait_for(asyncio.gather(*(v.ws.close(code=1001,message=b'Server shutting down') for v in viewers),
                                            return_exceptions=True), 2)
    except asyncio.TimeoutError:
        pass


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8090)
    p.add_argument('--capture', action='store_true')
    p.add_argument('--device')
    p.add_argument('--frequency', type=float, default=739e6)
    p.add_argument('--rate', type=float, default=2048000)
    p.add_argument('--gain', type=float, default=40)
    p.add_argument('--max-channels',type=int,default=4)
    p.add_argument('--replay-iq',type=Path,help='Explicit QA fixture replay, not live reception')
    p.add_argument('--replay-rate',type=float,default=2048000)
    p.add_argument('--replay-center',type=float,default=739e6)
    a = p.parse_args()
    if a.capture:
        capture(a)
        return
    app = web.Application()
    if not 1<=a.max_channels<=32:
        p.error('--max-channels must be 1–32')
    if a.replay_iq and (not a.replay_iq.is_file() or a.replay_iq.stat().st_size<32768*8 or not 10000<=a.replay_rate<=20000000):
        p.error('Invalid replay file or sample rate')
    if not (ROOT/'native/leandvb-server').is_file():
        p.error('Build the server decoder first: python3 tools/build_server.py')
    app['hub'] = ReceiverHub(max_channels=a.max_channels,replay=a.replay_iq,
                            replay_rate=a.replay_rate,replay_center=a.replay_center)
    app.on_cleanup.append(cleanup)
    app.on_shutdown.append(shutdown)
    app.router.add_get('/api/devices', api_devices)
    app.router.add_get('/stream', websocket)
    app.router.add_get('/api/status', api_status)
    app.router.add_get('/', lambda _: web.FileResponse(ROOT/'web/index.html'))
    app.router.add_static('/', ROOT/'web', show_index=False)
    web.run_app(app, host=a.host, port=a.port)

if __name__ == '__main__':
    main()

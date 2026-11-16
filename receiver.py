"""Shared capture, on-demand native DVB decoding, and bounded TS fan-out."""
import asyncio
from collections import deque
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

from channelizer import Channelizer
from detection import Selection, acquisition_plan, estimate_signal, MODCOD_NAMES
from transport import TransportValidator

ROOT = Path(__file__).resolve().parent


async def terminate_process(proc):
    if proc is None:
        return
    if proc.returncode is None:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
    async def drain(reader):
        if reader:
            while await reader.read(262144):
                pass
    # Call only after other readers have been cancelled.
    drains = [asyncio.create_task(drain(r)) for r in (proc.stdout, proc.stderr)]
    try:
        await asyncio.wait_for(proc.wait(), 3)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    finally:
        for task in drains:
            task.cancel()
        await asyncio.gather(*drains, return_exceptions=True)


class Viewer:
    """A slow socket has its own budget and never backpressures the SDR."""
    def __init__(self, ws):
        self.ws = ws
        self.queue = asyncio.Queue(maxsize=96)
        self.failed = False
        self.session = self.job = None
        self.generation = 0
        self.ts_bytes = 0
        self.task = asyncio.create_task(self.writer())

    def send(self, data, *, ts=False, spectrum=False):
        if self.failed or self.ws.closed:
            return
        if spectrum and self.queue.qsize() > 3:
            return  # discard stale display updates, never TS
        try:
            self.queue.put_nowait((time.monotonic(), self.generation if ts else None, data))
        except asyncio.QueueFull:
            self.failed = True
            asyncio.create_task(self.ws.close(code=1013, message=b'Slow client: reconnect to resume'))

    async def writer(self):
        try:
            while True:
                when, generation, data = await self.queue.get()
                if generation is not None and generation != self.generation:
                    continue
                if time.monotonic()-when > 3:
                    await self.ws.close(code=1013, message=b'Client fell behind; reconnect')
                    return
                if isinstance(data, bytes):
                    await asyncio.wait_for(self.ws.send_bytes(data), 3)
                    if data[:1] == b'T':
                        self.ts_bytes += len(data)-1
                else:
                    await asyncio.wait_for(self.ws.send_json(data), 3)
        except (ConnectionError, asyncio.TimeoutError, RuntimeError):
            self.failed = True
            await self.ws.close(code=1013, message=b'Client connection too slow')

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


class Attempt:
    def __init__(self, job, candidate):
        self.job, self.candidate = job, candidate
        self.proc = None
        self.tasks = []
        self.validator = TransportValidator()
        self.metrics = {}
        self.modcod = 0
        self.locked = asyncio.Event()
        self.failure = asyncio.Event()
        self.failure_text = ''
        self.raw_lock = False
        self.last_status = 0
        self.log_tail = deque(maxlen=6)

    async def start(self):
        j, c = self.job, self.candidate
        self.channelizer = Channelizer(j.session.rate, c.symbols, j.tune-j.session.center)
        args = [str(ROOT/'native/leandvb-server'), '--f32', '--float-scale', '128',
                '-f', str(self.channelizer.output_rate), '--sr', str(c.symbols),
                '--standard', c.standard, '--sampler', 'rrc', '--rrc-rej', '30',
                '--roll-off', str(j.selection.rolloff), '--anf', '0', '--fastlock', '--fd-info', '2']
        if c.standard == 'DVB-S2':
            args += ['--ldpc-bf', '100', '--modcods', str(2**j.selection.modcod if j.selection.modcod else 0x1ffffffe),
                     '--framesizes', str(j.selection.framesizes)]
        else:
            args += ['--cr', c.fec, '--viterbi']
        j.clear_iq()
        self.proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=524288)
        self.tasks = [asyncio.create_task(self.guard(fn())) for fn in (self.feed, self.read_ts, self.read_info)]

    async def guard(self, coroutine):
        try:
            await coroutine
            self.failure_text = 'Native decoder exited: '+'; '.join(self.log_tail)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.failure_text = str(e)
        self.failure.set()

    async def feed(self):
        while True:
            iq = await self.job.iq.get()
            if iq is None:
                raise RuntimeError('IQ discontinuity: restarting channel acquisition')
            selected = await asyncio.to_thread(self.channelizer.process, iq)
            selected = selected-selected.mean()  # input can be a shared read-only view
            self.proc.stdin.write(selected.astype('<c8', copy=False).tobytes())
            await asyncio.wait_for(self.proc.stdin.drain(), 2)

    async def read_info(self):
        async for line in self.proc.stderr:
            text = line.decode(errors='replace').strip()
            words = text.split()
            if len(words) < 2:
                continue
            key = words[0]
            if key in ('FREQ', 'MER', 'VBER', 'SS', 'LOCK', 'FRAMELOCK'):
                try:
                    value = float(words[1])
                    if not math.isfinite(value):
                        continue
                    self.metrics[key] = value
                except ValueError:
                    continue
                if key == 'LOCK':
                    self.raw_lock = words[1] == '1'
            elif key == 'MODCOD' and len(words) == 4:
                self.modcod = int(words[1])
                self.metrics.update(modcod=self.modcod, short=bool(int(words[2])), pilots=bool(int(words[3])))
            elif key not in ('STANDARD','CONSTELLATION','CR','SR','LOCKTIME','CNR'):
                self.log_tail.append(text[:300])
            if time.monotonic()-self.last_status > 1:
                self.job.status(self)
                self.last_status = time.monotonic()

    def profile(self):
        c = self.candidate
        result = dict(standard=c.standard, symbols=c.symbols, tune=self.job.tune,
                      rolloff=self.job.selection.rolloff, channel_rate=self.channelizer.output_rate)
        if c.standard == 'DVB-S2':
            result.update(modcod=self.modcod, modulation=MODCOD_NAMES[self.modcod] if 0 < self.modcod < 29 else 'PLS pending',
                          short=self.metrics.get('short'), pilots=self.metrics.get('pilots'))
        else:
            result.update(fec=c.fec, modulation='QPSK '+c.fec)
        return result

    async def read_ts(self):
        pending = bytearray()
        last_flush = time.monotonic()
        while True:
            data = await self.proc.stdout.read(188*256)
            if not data:
                return
            clean = self.validator.feed(data)
            # PLS alone or a noisy byte stream is not accepted as detection.
            if self.validator.confirmed and self.raw_lock:
                if not self.locked.is_set():
                    self.locked.set()
                    self.job.confirm(self)
                pending.extend(clean)
                if len(pending) >= 188*64 or time.monotonic()-last_flush >= .05:
                    self.job.publish(bytes(pending))
                    pending.clear()
                    last_flush = time.monotonic()

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await terminate_process(self.proc)


class ChannelJob:
    def __init__(self, session, selection, estimate, identifier):
        self.session, self.selection, self.estimate = session, selection, estimate
        self.tune = estimate['center'] if estimate and selection.auto_symbols else selection.tune
        self.id = identifier
        self.viewers = set()
        self.iq = asyncio.Queue(maxsize=max(8, math.ceil(session.rate/32768*.5)))
        self.state = 'searching'
        self.attempt = None
        self.profile = None
        self.ring = deque()
        self.task = None
        self.trial = 0
        self.last_message = {}
        self.output_bytes = 0
        self.output_started = 0

    def start(self):
        self.task = asyncio.create_task(self.run())

    def clear_iq(self):
        while not self.iq.empty():
            self.iq.get_nowait()

    def offer(self, iq):
        if self.iq.full():
            self.clear_iq()
            self.iq.put_nowait(None)
        else:
            self.iq.put_nowait(iq)

    def status(self, attempt=None, **extra):
        a = attempt or self.attempt
        message = dict(type='decoder', channel=self.id, state=self.state,
                       viewers=len(self.viewers), tune=self.tune, trial=self.trial,
                       estimate=self.estimate, requested=asdict(self.selection))
        if a:
            elapsed = time.monotonic()-self.output_started if self.output_started else 0
            # A new tentative PLS during loss of sync must not overwrite the
            # profile that was confirmed by a valid transport stream.
            profile = self.profile if self.state == 'locked' and self.profile else a.profile()
            message.update(profile=profile, metrics=a.metrics.copy(),
                           packets=a.validator.packets, tei=a.validator.tei,
                           bitrate=self.output_bytes*8/elapsed if elapsed >= .5 else 0,
                           mux_bitrate=a.validator.bitrate, iq_queue=self.iq.qsize())
        message.update(extra)
        self.last_message = message
        for viewer in list(self.viewers):
            viewer.send(message)

    def confirm(self, attempt):
        self.state = 'locked'
        self.profile = attempt.profile()
        self.status(attempt, confirmed_by='native lock + TS sync + CRC-valid PAT and PMT')

    def publish(self, data):
        now = time.monotonic()
        if not self.output_started:
            self.output_started = now
        self.output_bytes += len(data)
        self.ring.append((now, data))
        while self.ring and now-self.ring[0][0] > 1:
            self.ring.popleft()
        for viewer in list(self.viewers):
            viewer.send(b'T'+data, ts=True)

    async def run(self):
        try:
            while self.viewers:
                estimate = self.session.estimate(self.selection)
                if estimate and self.selection.auto_symbols:
                    self.estimate = estimate
                    self.tune = estimate['center']
                plan = acquisition_plan(self.selection, self.estimate, self.session.center, self.session.rate)
                if not plan:
                    self.status(message='No candidate fits capture bandwidth; select a smaller rate or another center')
                    await asyncio.sleep(2)
                    continue
                for candidate in plan:
                    if not self.viewers:
                        return
                    async with self.session.hub.probes:
                        self.trial += 1
                        self.state = 'searching'
                        self.profile = None
                        self.ring.clear()
                        self.output_bytes = 0
                        self.output_started = 0
                        self.attempt = a = Attempt(self, candidate)
                        try:
                            await a.start()
                            self.status(message=f'Trying {candidate.standard}, {candidate.symbols/1000:g} ksym/s'
                                        +(f', FEC {candidate.fec}' if candidate.standard == 'DVB-S' else ', PLS auto'))
                            deadline = max(2.5, min(12, 6*32490/candidate.symbols))
                            lock_task = asyncio.create_task(a.locked.wait())
                            fail_task = asyncio.create_task(a.failure.wait())
                            try:
                                await asyncio.wait((lock_task, fail_task), timeout=deadline,
                                                   return_when=asyncio.FIRST_COMPLETED)
                            finally:
                                lock_task.cancel(); fail_task.cancel()
                                await asyncio.gather(lock_task, fail_task, return_exceptions=True)
                            acquired = a.locked.is_set() and not a.failure.is_set()
                            if a.failure.is_set():
                                self.status(message=a.failure_text)
                        except Exception as e:
                            acquired = False
                            self.status(message=str(e))
                    # A locked decoder doesn't occupy a search slot.
                    if acquired:
                        while self.viewers and not a.failure.is_set():
                            await asyncio.sleep(.5)
                            self.status(a)
                            if time.monotonic()-a.validator.last_data > 5:
                                break
                        self.state = 'searching'
                        self.status(message='Transport lost; reacquiring')
                    await a.stop()
                    self.attempt = None
                    if acquired:
                        break  # re-estimate the signal after a lost lock
                await asyncio.sleep(.2)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.state = 'error'
            self.status(message=str(e))
        finally:
            if self.attempt:
                await self.attempt.stop()

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class CaptureSession:
    def __init__(self, hub, device, center, rate, gain):
        self.hub, self.device, self.center, self.rate, self.gain = hub, device, center, rate, gain
        self.viewers, self.jobs = set(), {}
        self.proc = self.task = self.log_task = None
        self.ready = asyncio.Event()
        self.power = None
        self.started = self.last_fft = self.last_stats = 0
        self.samples = 0
        self.last_spectrum = None
        self.next_channel = 0
        self.error = None

    def config(self):
        return dict(device=self.device, frequency=self.center, rate=self.rate, gain=self.gain,
                    viewers=len(self.viewers), replay=self.device == 'replay')

    def broadcast(self, message, **kwargs):
        for viewer in list(self.viewers):
            viewer.send(message, **kwargs)

    def estimate(self, selection):
        return estimate_signal(self.power, self.center, self.rate, selection.tune, selection.symbols)

    async def start(self):
        if self.device != 'replay':
            self.proc = await asyncio.create_subprocess_exec(sys.executable, str(ROOT/'server.py'), '--capture',
                '--device', self.device, '--frequency', str(self.center), '--rate', str(self.rate), '--gain', str(self.gain),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=2097152)
            self.log_task = asyncio.create_task(self.logs())
        self.task = asyncio.create_task(self.read())
        try:
            await asyncio.wait_for(self.ready.wait(), 12)
            if self.error:
                raise RuntimeError(self.error)
        except BaseException:
            await self.close()
            raise

    async def logs(self):
        async for line in self.proc.stderr:
            text = line.decode(errors='replace').strip()
            self.broadcast(dict(type='log', text=text))

    async def read(self):
        file = None
        try:
            if self.device == 'replay':
                file = open(self.hub.replay, 'rb')
            self.started = time.monotonic()
            window = np.hanning(16384).astype(np.float32)
            while True:
                if file:
                    data = file.read(32768*8)
                    if len(data) < 32768*8:
                        file.seek(0)
                        data += file.read(32768*8-len(data))
                    await asyncio.sleep(max(0, self.started+self.samples/self.rate-time.monotonic()))
                else:
                    data = await self.proc.stdout.readexactly(32768*8)
                if not self.samples:
                    self.started = time.monotonic()
                self.samples += 32768
                iq = np.frombuffer(data, dtype='<c8')
                now = time.monotonic()
                if now-self.last_fft > .1:
                    parts = iq.reshape(2, 16384)
                    spectrum = np.fft.fftshift(np.fft.fft((parts-parts.mean(axis=1)[:,None])*window, axis=1), axes=1)
                    power = np.mean(abs(spectrum)**2, axis=0)/(8192**2)
                    self.power = power if self.power is None else self.power*.65+power*.35
                    display = 10*np.log10(self.power.reshape(2048,8).mean(axis=1)+1e-15)
                    self.last_spectrum = b'F'+np.clip((display+140)/140*255, 0, 255).astype(np.uint8).tobytes()
                    self.broadcast(self.last_spectrum, spectrum=True)
                    self.last_fft = now
                    self.ready.set()
                for job in list(self.jobs.values()):
                    job.offer(iq)
                if now-self.last_stats > 1:
                    self.broadcast(dict(type='capture', samples=self.samples, seconds=now-self.started,
                                        viewers=len(self.viewers), decoders=len(self.jobs)))
                    self.last_stats = now
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.error = f'Capture stopped: {e}'
            self.broadcast(dict(type='error', text=self.error))
        finally:
            self.ready.set()
            if file:
                file.close()

    async def close(self):
        for task in (self.task, self.log_task):
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in (self.task,self.log_task) if t), return_exceptions=True)
        await terminate_process(self.proc)


class ReceiverHub:
    def __init__(self, *, max_channels=4, replay=None, replay_rate=2048000, replay_center=739e6):
        self.sessions = {}
        self.lock = asyncio.Lock()
        self.probes = asyncio.Semaphore(2)
        self.max_channels = max_channels
        self.replay, self.replay_rate, self.replay_center = replay, replay_rate, replay_center

    async def attach(self, viewer, data):
        async with self.lock:
            if sum(len(s.viewers) for s in self.sessions.values()) >= 64:
                raise ValueError('Server viewer limit reached (64)')
            device = str(data['device'])
            if self.sessions and device not in self.sessions:
                active = next(iter(self.sessions.values()))
                raise ValueError(f'One SDR supplies all users. Join receiver {active.device}, already capturing '
                                 f'{active.rate/1e6:g} MS/s around {active.center/1e6:g} MHz IF.')
            session = self.sessions.get(device)
            if session is None:
                center, rate, gain = float(data['frequency']), float(data['rate']), float(data['gain'])
                if device == 'replay' and self.replay:
                    center, rate = self.replay_center, self.replay_rate
                elif not (50e6 <= center <= 2e9 and rate in (1536000,2048000,5000000,8000000,10000000) and 0 <= gain <= 103):
                    raise ValueError('Invalid hardware capture configuration')
                Selection.parse(data, center, rate)
                session = CaptureSession(self, device, center, rate, gain)
                await session.start()
                self.sessions[device] = session
            if session.error:
                raise ValueError(session.error+'; disconnect all viewers and restart')
            # Existing viewers retain their hardware configuration.
            try:
                Selection.parse(data, session.center, session.rate)
            except ValueError as e:
                raise ValueError(f'Receiver uses a shared capture at {session.center/1e6:g} MHz IF / '
                                 f'{session.rate/1e6:g} MS/s. Select inside this capture, or stop it after all '
                                 f'viewers leave to choose a wider span. QO-100 WB uses 10 MS/s around 745 MHz IF. {e}') from e
            viewer.session = session
            session.viewers.add(viewer)
            viewer.send(dict(type='welcome', **session.config(), transport='MPEG-TS',
                             protocol='binary F: uint8 FFT -140..0 dB; T: MPEG-TS'))
            if session.last_spectrum:
                viewer.send(session.last_spectrum, spectrum=True)
            try:
                if data.get('overview'):
                    viewer.send(dict(type='selected',state='overview',tune=float(data.get('tune',session.center))))
                else:
                    await self._select(viewer, data)
            except BaseException:
                session.viewers.discard(viewer)
                viewer.session = None
                if not session.viewers:
                    await session.close()
                    self.sessions.pop(device, None)
                raise

    async def _select(self, viewer, data):
        session = viewer.session
        selection = Selection.parse(data, session.center, session.rate)
        estimate = session.estimate(selection)
        key = selection.key(estimate['center'] if estimate and selection.auto_symbols else None)
        job = session.jobs.get(key)
        if job is None:
            measured = estimate['center'] if estimate and selection.auto_symbols else selection.tune
            for existing in session.jobs.values():
                tolerance = max(2000,min(150000,(existing.estimate['symbols'] if existing.estimate else existing.selection.symbols)*.15))
                profile = existing.profile if existing.state == 'locked' else None
                compatible = existing.selection.key()[1:] == selection.key()[1:]
                if profile:
                    compatible = (selection.standard in ('Auto',profile['standard'])
                        and (selection.auto_symbols or selection.symbols == profile['symbols'])
                        and (profile['standard']=='DVB-S2' or selection.fec in ('Auto',profile['fec']))
                        and (profile['standard']=='DVB-S' or selection.modcod in (0,profile.get('modcod')))
                        and (profile['standard']=='DVB-S' or selection.framesizes & (2 if profile.get('short') else 1))
                        and selection.rolloff == profile['rolloff'])
                if compatible and abs(existing.tune-measured) <= tolerance:
                    job = existing
                    break
        if job is None and sum(len(s.jobs) for s in self.sessions.values()) >= self.max_channels:
            # A viewer may replace its own unshared decoder at the limit.
            if not viewer.job or len(viewer.job.viewers) > 1:
                raise ValueError('Server decoder capacity reached; join an existing channel or retry later')
        if viewer.job is job and job is not None:
            if data.get('rescan') and job.state != 'locked':
                await job.close()
                job.attempt = None
                job.trial = 0
                job.start()
            job.status()
            return
        await self._unselect(viewer)
        viewer.generation += 1
        if job is None:
            session.next_channel += 1
            job = ChannelJob(session, selection, estimate, f'{session.device}/{session.next_channel}')
            session.jobs[key] = job
        viewer.job = job
        job.viewers.add(viewer)
        viewer.send(dict(type='selected', channel=job.id, tune=job.tune, requested=asdict(selection), shared=len(job.viewers)>1))
        if job.last_message:
            viewer.send(job.last_message)
        for _, data in job.ring:
            viewer.send(b'T'+data, ts=True)
        job.status()
        if job.task is None:
            job.start()

    async def _unselect(self, viewer):
        job = viewer.job
        if job is None:
            return
        viewer.job = None
        job.viewers.discard(viewer)
        if not job.viewers:
            for key, current in list(job.session.jobs.items()):
                if current is job:
                    del job.session.jobs[key]
            await job.close()
        else:
            job.status()

    async def select(self, viewer, data):
        async with self.lock:
            await self._select(viewer, data)

    async def overview(self, viewer):
        async with self.lock:
            await self._unselect(viewer)
            viewer.generation += 1
            viewer.send(dict(type='selected',state='overview',tune=viewer.session.center))

    async def detach(self, viewer):
        async with self.lock:
            await self._unselect(viewer)
            session = viewer.session
            if session:
                session.viewers.discard(viewer)
                viewer.session = None
                if not session.viewers:
                    await session.close()
                    self.sessions.pop(session.device, None)

    def snapshot(self):
        return [dict(**s.config(), error=s.error, channels=[dict(id=j.id, state=j.state,
            viewers=len(j.viewers), profile=j.profile, trial=j.trial,tune=j.tune,
            requested=asdict(j.selection),estimate=j.estimate) for j in s.jobs.values()]) for s in self.sessions.values()]

    async def close(self):
        async with self.lock:
            for session in list(self.sessions.values()):
                for job in list(session.jobs.values()):
                    await job.close()
                await session.close()
            self.sessions.clear()

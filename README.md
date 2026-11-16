# QO-100 WB multi-user WebSDR

**Only one SDRone is required.** It samples the full WB transponder once;
multiple independent channels are digitally extracted from that same IQ stream.
All users share this one wideband capture. The **server
performs DVB-S/S2 demodulation and FEC** and shares a recovered MPEG transport
stream with everyone watching that signal. Browsers receive **TS, compact FFT
updates and status**; browsers decode video/audio and draw the WebGL waterfall.
No wideband or selected-channel IQ is sent to users.

```text
SDRone → one shared wideband capture → shared FFT → all viewers
                                   ↳ channel A → native DVB decoder → TS → viewers A
                                   ↳ channel B → native DVB decoder → TS → viewers B
```

Video is not transcoded on the server. A user watching an already decoded signal
reuses its decoder, including when compatible manual settings join a confirmed
Auto result. Independent retuning affects only that user's subscription. Decoders
stop when their last subscriber leaves; the capture stops when its last viewer
leaves. **Waterfall only** releases your decoder while keeping the overview.

## Run

On this configured PC:

```sh
cd /root/dvbs-websdr
./run.sh
```

Open <http://127.0.0.1:8090>. Select a receiver, press **Start receiver**, and click
the signal. USB `001:010` / physical port `1-1` is preferred; `001:012` / port
`1-5` is also selectable. Selection follows physical ports rather than changing
Soapy driver indices.

The first viewer defines that receiver's center, sample rate and gain. Other
viewers share that capture and tune independently **within it**. The receiver
list shows active users and adopts the active capture configuration when joining.
Capture settings cannot be changed underneath existing viewers. Wait until everyone leaves to change the physical capture. If several SDRones
are plugged in, selection is available at startup, but only the chosen one is
used; other receivers are not needed or opened for additional channels.

Defaults: QO-100 WB, 10 MS/s around **745 MHz IF**, nominal **9750 MHz LNB LO**,
Auto DVB-S/S2 and automatic common-rate search, with a 1500 ksym/s rate hint.
The 740–750 MHz captured window includes the 740.5–749.5 MHz WB bandplan IF range.

- **QO-100 WB / LNB** selects Auto acquisition with a 333 ksym/s hint.
- **DATV beacon** selects known DVB-S2 / 1500 ksym/s / QPSK 4/5 at 741.5 MHz IF.
- **Direct IF test** restores 739 MHz and a 333 ksym/s hint.
- Center/tune controls use **IF MHz**. Waterfall labels add the LNB LO and LO
  correction to show RF. Set LO to zero for direct IF labels.
- **Reacquire** restarts an unconfirmed search. A confirmed shared decoder is
  retained so another user's playback is not interrupted.
- Capture spans are 1.536, 2.048, 5, 8 and 10 MHz. Stop to change capture settings.

A universal LNB needs an external, DC-isolated power inserter, normally **18 V,
22 kHz off** for low-band horizontal reception. The SDR bias tee stays off and
cannot replace an LNB supply. Actual satellite reception still requires dish
alignment, suitable signal level and an adequately stable LNB.

References: [BATC WB bandplan](https://wiki.batc.org.uk/Es%27hail-2_DATV_Bandplan),
[BATC reception guide](https://wiki.batc.org.uk/Receiving_Oscar_100_DATV_signals).

## Automatic detection

**Auto** searches the selected signal, not every visible transmission at once:

1. Measure the local RRC spectrum's half-power width and refine its center.
   This is a **search estimate**, not a modulation or lock declaration.
2. Rank nearby common symbol rates: 33, 66, 125, 250, 333, 500, 1000, 1500 and
   2000 ksym/s. Up to three nearby rates are tried. Without a reliable spectrum
   estimate, the numeric rate field is used as a hint.
3. Try DVB-S2, with modulation/FEC/frame size/pilots read from PLS signalling.
   If it does not recover a valid TS, try DVB-S QPSK FEC candidates.
4. Report confirmed detection only after **native decoder lock, TS sync and
   CRC-valid PAT and PMT tables**. Search progress and tentative parameters are
   shown separately from confirmed results.

DVB-S FEC search covers 1/2, 2/3, 3/4, 5/6 and 7/8. DVB-S2 supports MODCODs 1–28
(QPSK, 8PSK, 16APSK, 32APSK), normal/short frames and pilots. MODCOD/frame filters
can restrict a known signal. The FEC control applies to DVB-S; S2 FEC comes from
PLS/MODCOD.

For custom symbol rates, weak/overlapping signals or unreliable estimates,
uncheck **Auto common rates** and enter the exact rate (10–2000 ksym/s). You can
also force DVB-S or DVB-S2 and a DVB-S FEC / S2 MODCOD. Roll-off is selected
manually (.35, .25, .20); it is not blindly detected. Acquisition is not guaranteed
for every arbitrary signal, clock error, signal-to-noise ratio or symbol rate.

DVB-S2 uses the pinned LeanDVB receiver's **hard-decision LDPC bit-flipping and
BCH**. Weak-signal performance is limited compared with a soft-decision LDPC
receiver. DVB-S2X, multistream, GSE and ACM/VCM are outside tested scope. See
[server validation](tests/SERVER-VALIDATION.md) for what was actually tested;
no live satellite DVB-S2 lock is claimed by the synthetic tests.

## Bandwidth, playback and limits

Each viewer receives the recovered TS, not float IQ. Examples of TS capacity:

| Transmission | Approximate TS payload |
| --- | --- |
| DVB-S, 333 ksym/s, FEC 1/2 | 0.307 Mbit/s |
| DVB-S2, 1500 ksym/s, QPSK 4/5 | About 2.3 Mbit/s |

The 2048-bin uint8 spectrum at about 10 Hz adds roughly **0.164 Mbit/s** per user,
plus small status/WebSocket overhead. The browser's initial media-codec download
is approximately 31 MiB and can be cached. The server sends the same TS to each
subscriber; unicast network traffic still adds across viewers. Native decoder
CPU usage adds across **distinct channels**, not viewers of the same channel.

Defaults allow **four active decoder jobs**, two simultaneous acquisition probes
and 64 viewers. Change job capacity with `--max-channels N`; a running channel is
not evicted to make space. Actual capacity depends on modulation, symbol rate,
CPU, SDR/USB throughput and network speed. The service opens at most one SDR at a time. Additional selected frequencies
create digital channel decoders, never additional hardware captures.

Per-channel IQ and per-viewer network queues are bounded. Decoder IQ overflow
restarts that decoder's acquisition. A slow network client is disconnected and
cannot backpressure the shared capture or other viewers. Discontinuities reported
by SoapySDR stop the capture rather than silently joining broken IQ.

Browser video/audio decoding uses local FFmpeg WebAssembly in roughly three-second
batches with overlap for tables/keyframes. Current display is 320×240 / 10 fps,
mono 48 kHz. MPEG-2/MP2, H.264/AAC and HEVC/AAC media decoding have been tested.
**Enable audio** requires a user click. **Save received TS** retains the most
recent 32 MiB of original recovered TS; it is not rescaled or transcoded.

For explicit LAN access:

```sh
./run.sh --host 0.0.0.0 --port 8090 --max-channels 4
```

The service defaults to loopback, has no authentication layer and rejects
cross-origin browser WebSocket connections. It never starts a transmitter.

## Build from this Git repository

Sources, patches, build tools and media hashes are tracked. Native builds,
virtual environments, generated WASM, IQ and TS recordings are ignored. No Git
submodules or source files in older project directories are required.

On a Debian-like host:

```sh
sudo apt-get install build-essential cmake pkg-config libusb-1.0-0-dev \
  libsoapysdr-dev python3-soapysdr python3-numpy python3-scipy python3-venv \
  ffmpeg patch
./setup.sh
```

Setup builds project-local libmirisdr and SoapyMiri, the native
`native/leandvb-server`, then verifies/downloads the browser media assets. It does
not replace system SDR libraries. General DVB decoding no longer requires
Emscripten. The historical browser-DVB build tools remain available separately.
The server binary is replaced atomically, so an existing process can finish
using the old binary during a rebuild.

## Tests and explicit IQ replay

Build the server and prepare fixtures first:

```sh
python3 tools/build_server.py
.venv/bin/python tools/prepare_fixture.py
.venv/bin/python tools/prepare_s2_fixtures.py
.venv/bin/python tests/prepare_shared_fixture.py
.venv/bin/python tests/server_unit_check.py
.venv/bin/python tests/shared_server_check.py
.venv/bin/python tests/native_matrix_check.py
.venv/bin/python tests/shared_browser_check.py
```

These checks start isolated replay servers, do not require RF transmission, and
explicitly mark replay in the UI. They validate Auto detection, sharing,
independent channels, slow-client isolation, resource limits, last-user cleanup,
real native TS recovery and actual browser playback. Source TS is taken from the
old bench if available; otherwise FFmpeg generates a local test stream.

With `./run.sh` running, receive-only hardware checks are:

```sh
.venv/bin/python tests/hardware_check.py
.venv/bin/python tests/wideband_check.py
```

Browser tests use `PLAYWRIGHT_CHROMIUM_EXECUTABLE`, an installed cached Chromium,
or Playwright's default. Install it if needed with
`.venv/bin/playwright install chromium`. Optional media-only tests are in
`tests/media_check.py`. Historical browser-DVB tests require Emscripten and
`tools/build_decoder.py` / `--s2`; they are not the production decoder path.

For a deliberate QA replay, never presented as live reception:

```sh
./run.sh --port 8091 --replay-iq /tmp/dvbs-shared-capture.cf32 \
  --replay-rate 10000000 --replay-center 745000000
```

`/api/devices` advertises the replay source instead of hardware. Replay CLI flags
are not accepted from browser requests. No user can select arbitrary server files.

## Streaming API

`/stream` is a same-origin WebSocket. The first JSON message specifies `device`,
`frequency` (capture center Hz), `rate`, `gain`, `tune` (Hz), `symbols` (manual rate
or hint), `standard` (`Auto`, `DVB-S`, `DVB-S2`), `auto_symbols`, `fec`, `modcod`,
`framesizes`, and `rolloff`. `overview: true` requests only the shared waterfall.
Subsequent `{type:"tune", ...selection}` messages change only your subscription;
`{type:"overview"}` releases it. Incompatible tuner changes require stopping the shared capture after everyone
leaves. Requests to open a second SDR while it is active are rejected.

Binary frames have one tag byte:

- ASCII `F`: 2048 uint8 spectrum bins mapping linearly from -140 to 0 dB.
- ASCII `T`: aligned recovered 188-byte MPEG-TS packets.

JSON `welcome`, `selected`, `decoder`, and `capture` messages describe active
settings, search/lock status and shared viewer counts. `selection_error` leaves
the previous subscription active. `/api/status` lists shared captures, jobs and
viewer counts. The former raw-IQ `/iq` endpoint has been removed.

## Repository and licensing

Local Git repository, branch `main`; no remote is configured. See
[vendor provenance](vendor/PROVENANCE.md) for pinned commits, licenses, media
hashes and local adaptations. Original code is GPL-3.0-or-later; see [LICENSE](LICENSE).
Retain corresponding upstream source and dependency build configuration when
redistributing third-party binaries.

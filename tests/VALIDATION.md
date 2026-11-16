> Historical DVB-S baseline. See [QO-100 / DVB-S2 validation](QO100-VALIDATION.md) for the extended receiver.

# Validation — 2026-11-16

## Browser fixture

Real Chromium with WebAssembly and software WebGL, using the existing periodic
DVB-S waveform resampled from 2.664 to 2.048 MS/s. Recovered 151152 TS bytes.
Browser FFmpeg WASM decoded 30 RGBA video frames and 144000 float audio samples
from a three-second batch. No JavaScript page errors. See `browser-results.log`.

## Hardware selection

Opened both SDRone / RSP1-compatible receivers independently:

| USB address | Physical port | Driver index at test time |
| --- | --- | --- |
| 001:010 | 1-1 | 1 |
| 001:012 | 1-5 | 0 |

Each delivered 12 full IQ blocks at 2.048 MS/s. Duplicate ownership was rejected.
Closing each connection restored its msi2500 Linux driver. See
`hardware-results.log`. The browser selected device 010 by default.

## Live 739 MHz antenna link

Pluto cyclic replay of `/mnt/data/astrometa-dvbs333/periodic.iq`, 333000 symbols/s,
QPSK, FEC 1/2, roll-off 0.35, 2.664 MS/s TX, 40 dB internal TX attenuation.
Receiver: USB 001:010, 2.048 MS/s, manual gain request 60, bias tee off.
These settings describe this bench and are not a calibrated sensitivity result.

The final browser run acquired the RF signal, clicked the waterfall approximately
5 kHz away from the original center, reacquired, activated audio, played repeated
three-second video/audio batches, and downloaded the recovered transport stream.
It remained locked for all six subsequent 2.5-second observation intervals.
Final sampled MER was 22.4 dB; browser IQ queue was one block, with no overload.
No JavaScript page errors occurred. See `live-results.log`, `live-stats.json`
and `live-interface.png`.

The downloaded TS contained **3109 packets**, zero bad sync bytes and two
TEI-marked packets. The first five packets differed from the original source
during acquisition; **all remaining 3104 packets matched source packets exactly**.
FFprobe identified the expected 160×120 MPEG-2 video and MP2 audio. Its initial
missing-dimensions message reflects joining before a video sequence header.
See `live-packets.json` and `live-media.json`. Media/IQ recordings are in `/tmp`
and are intentionally excluded from the source project.

The finite TX helper ended with `tx_powerdown=1` and no restoration errors.
Both receivers' Linux drivers were attached after testing. See
`pluto-results.log`. No transmitter is started by the website.

## Scope limits

DVB-S only; no DVB-S2 or full WB transponder coverage. Current capture span is
2.048 MHz. Browser playback is buffered, scaled to 320×240 at 10 fps with mono
48 kHz audio. H.264 is available in the bundled media engine, but this RF run
validated the existing MPEG-2/MP2 test stream. It does not establish live H.264,
weak-signal, long-duration, or other-FEC performance.

#!/usr/bin/env python3
"""Fetch pinned, verified FFmpeg browser assets. No CDN is used at runtime."""
import hashlib,io,tarfile,urllib.request
from pathlib import Path
out=Path(__file__).resolve().parents[1]/'web/vendor'
expected={'ffmpeg-core.js':'b266ab5b952555881dd6310663986994a182acb2b7ff25cf10a25f7a37ac2b21','ffmpeg-core.wasm':'9f57947a5bd530d8f00c5b3f2cb2a3492faa7e5d823315342d6a8656d0a6b7b7'}
with urllib.request.urlopen('https://registry.npmjs.org/@ffmpeg/core/-/core-0.12.10.tgz') as response:
    archive=tarfile.open(fileobj=io.BytesIO(response.read()),mode='r:gz')
for name,digest in expected.items():
    data=archive.extractfile('package/dist/umd/'+name).read()
    if hashlib.sha256(data).hexdigest()!=digest:raise RuntimeError('Media asset checksum mismatch: '+name)
    out.mkdir(exist_ok=True,parents=True);(out/name).write_bytes(data)
    print('Verified '+name)

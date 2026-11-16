"""Locate the original bench stream, or generate a reproducible local test TS."""
from pathlib import Path
import subprocess

def test_source():
    original=Path('/mnt/data/astrometa-dvbs333/source.ts')
    if original.exists():return original
    generated=Path('/tmp/dvbs-websdr-source.ts')
    if not generated.exists():
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=5',
            '-f','lavfi','-i','sine=frequency=1000:sample_rate=48000','-t','4',
            '-c:v','mpeg2video','-b:v','140k','-minrate','140k','-maxrate','140k',
            '-bufsize','280k','-g','5','-c:a','mp2','-b:a','32k','-ar','48000',
            '-muxrate','306882','-f','mpegts',str(generated)],check=True)
    return generated

#!/usr/bin/env python3
"""Generate deterministic DVB-S2 IQ fixtures using the pinned upstream modulator."""
import json,subprocess
from pathlib import Path
from test_source import test_source
ROOT=Path(__file__).resolve().parents[1]
binary=ROOT/'native/leandvbtx-s2'
subprocess.run(['g++','-O3','-DLEANSDR_EXTENSIONS','-DVERSION="84c59e1"','-I'+str(ROOT/'vendor/leansdr-s2'),str(ROOT/'vendor/leansdr-s2/apps/leandvbtx.cc'),'-o',str(binary)],check=True)
source=test_source().read_bytes()
profiles=[dict(name='qpsk-short-33k',symbolRate=33000,modcod=4,short=True),dict(name='qpsk-normal-125k',symbolRate=125000,modcod=8,short=False),dict(name='8psk-short-333k',symbolRate=333000,modcod=13,short=True),dict(name='beacon-normal-1500k',symbolRate=1500000,modcod=8,short=False)]
profiles.extend([
 dict(name='qpsk-short-66k',symbolRate=66000,modcod=4,short=True),
 dict(name='qpsk-short-250k',symbolRate=250000,modcod=8,short=True),
 dict(name='16apsk-normal-500k',symbolRate=500000,modcod=18,short=False),
 dict(name='qpsk-normal-1000k',symbolRate=1000000,modcod=4,short=False),
 dict(name='32apsk-normal-2000k',symbolRate=2000000,modcod=24,short=False)])
for profile in profiles:
    path=Path('/tmp/dvbs-'+profile['name']+'.cf32')
    command=[str(binary),'--standard','DVB-S2','--modcod',str(profile['modcod']),'--pilots','-f','4','--rrc-rej','30']
    if profile['short']:command+=['--shortframes']
    with path.open('wb') as output:subprocess.run(command,input=source,stdout=output,check=True)
    profile.update(path=str(path),rate=profile['symbolRate']*4)
Path('/tmp/dvbs-s2-fixtures.json').write_text(json.dumps(profiles,indent=2))
print(json.dumps(profiles,indent=2))

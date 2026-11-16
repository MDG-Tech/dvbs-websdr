#!/usr/bin/env python3
"""Build the pinned native DVB-S/S2 receiver and its acquisition fixes."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
dest = ROOT / 'native/build/server-decoder'
if dest.exists():
    shutil.rmtree(dest)
shutil.copytree(ROOT / 'vendor/leansdr-s2', dest / 'src')
subprocess.run(['patch', '-p1', '--batch', '-i',
                str(ROOT / 'vendor/patches/leandvb-acquisition.patch')], cwd=dest, check=True)
header = dest / 'src/leansdr/dvbs2.h'
header.write_text(header.read_text().replace('cstln = dcstln;  // Used by GUI', '''cstln = dcstln;  // Used by GUI
        static int reported_pls = -1;
        int code = (pls.modcod<<2) | (pls.sf?2:0) | (pls.pilots?1:0);
        if (code != reported_pls) {
          fprintf(stderr,"MODCOD %d %d %d\\n",pls.modcod,pls.sf,pls.pilots);
          reported_pls=code;
        }'''))
subprocess.run(['g++', '-O3', '-DNDEBUG', '-DLEANSDR_EXTENSIONS',
                '-DVERSION="leansdr-84c59e1-server"', '-I'+str(dest/'src'),
                str(dest/'src/apps/leandvb.cc'), '-o', str(ROOT/'native/leandvb-server.new')], check=True)
(ROOT/'native/leandvb-server.new').replace(ROOT/'native/leandvb-server')
print('Built native/leandvb-server')

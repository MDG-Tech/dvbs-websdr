#!/usr/bin/env python3
"""Build the pinned local LeanDVB sources for an asynchronous browser worker."""
import argparse, pathlib, shutil, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--s2',action='store_true')
args=p.parse_args()
SOURCE = ROOT/'vendor'/('leansdr-s2' if args.s2 else 'leansdr-dvbs')
dest = ROOT / 'native' / ('leansdr-s2' if args.s2 else 'leansdr')
if dest.exists():
    shutil.rmtree(dest)
shutil.copytree(SOURCE, dest / 'src', ignore=shutil.ignore_patterns('LICENSE.txt'))
shutil.copy2(SOURCE / 'LICENSE.txt', dest / 'LICENSE.txt')
if args.s2:
    subprocess.run(['patch','-p1','--batch','-i',str(ROOT/'vendor/patches/leandvb-acquisition.patch')],cwd=dest,check=True)
    bch=dest/'src/leansdr/bch.h'
    bch.write_text(bch.read_text().replace('TGF C[NN]={1,}, B[NN]={1,};',
        'TGF C[NN], B[NN]; memset(C,0,sizeof(C)); memset(B,0,sizeof(B)); C[0]=B[0]=1;'))
    s2=dest/'src/leansdr/dvbs2.h'
    s2.write_text(s2.read_text().replace('cstln = dcstln;  // Used by GUI', '''cstln = dcstln;  // Used by GUI
        static int reported_pls = -1;
        int code = (pls.modcod<<2) | (pls.sf?2:0) | (pls.pilots?1:0);
        if (code != reported_pls) {
          char info[80]; int n=snprintf(info,sizeof(info),"MODCOD %d %d %d\\n",pls.modcod,pls.sf,pls.pilots);
          browser_write(3,info,n); reported_pls=code;
        }'''))
generic = dest / 'src/leansdr/generic.h'
code = generic.read_text().replace('read(fdin,', 'browser_read(fdin,').replace('write(fdout,', 'browser_write(fdout,')
generic.write_text(code)
# LLVM 19 crashes in its general inlining cost analysis on this upstream TU.
# Keep that pass disabled, but inline the small arithmetic hot paths explicitly.
math=dest/'src/leansdr/math.h'
code=math.read_text().replace('inline ', 'inline __attribute__((always_inline)) ')
code=code.replace('  complex<T> operator', '  inline __attribute__((always_inline)) complex<T> operator')
code=code.replace('    complex(', '    __attribute__((always_inline)) complex(')
code=code.replace('  int hamming_weight(', '  inline __attribute__((always_inline)) int hamming_weight(')
code=code.replace('  unsigned char parity(', '  inline __attribute__((always_inline)) unsigned char parity(')
math.write_text(code)
bridge = ROOT / 'native/bridge.h'
bridge.write_text('''#include <emscripten.h>
#include <unistd.h>
EM_ASYNC_JS(int, browser_read, (int fd, void *ptr, unsigned size), {
  while (!Module.iqQueue.length) {
    if (Module.eof) return 0;
    await new Promise(resolve => Module.wakeIQ = resolve);
  }
  const block = Module.iqQueue[0];
  const n = Math.min(size, block.length - Module.iqOffset);
  HEAPU8.set(block.subarray(Module.iqOffset, Module.iqOffset+n), ptr);
  Module.iqOffset += n;
  if (Module.iqOffset === block.length) {
    Module.iqQueue.shift(); Module.iqOffset=0;
    postMessage({type:'consumed'});
  }
  return n;
});
EM_JS(int, browser_write, (int fd, const void *ptr, unsigned size), {
  const data = HEAPU8.slice(ptr, ptr+size);
  if (fd === 1) postMessage({type:'ts', data:data.buffer}, [data.buffer]);
  else postMessage({type:'info', text:new TextDecoder().decode(data)});
  return size;
});
''')
implementation=ROOT/('native/bridge-s2.cc' if args.s2 else 'native/bridge.cc')
implementation.write_text(bridge.read_text())
bridge.write_text('#include <unistd.h>\nextern "C" int browser_read(int,void*,unsigned);\nextern "C" int browser_write(int,const void*,unsigned);\n')
subprocess.run(['em++', str(dest/'src/apps/leandvb.cc'), str(implementation), '-I'+str(dest/'src'),
    '-include', str(bridge), '-O3', '-fno-inline-functions', '-msimd128',
    '-DVERSION="leansdr-'+('84c59e1' if args.s2 else 'e6416aa')+'-browser"',
    *(['-DLEANSDR_EXTENSIONS'] if args.s2 else []),
    '-Wno-format', '-sASYNCIFY', '-sASYNCIFY_STACK_SIZE=4194304', '-sSTACK_SIZE=16777216',
    '-sALLOW_MEMORY_GROWTH', '-sINITIAL_MEMORY=134217728', '-sMAXIMUM_MEMORY=536870912',
    '-sMODULARIZE', '-sEXPORT_NAME=createLeanDVB', '-sENVIRONMENT=worker,node',
    '-sEXPORTED_RUNTIME_METHODS=["callMain"]', '-sINVOKE_RUN=0',
    '-o', str(ROOT/'web/vendor'/('leandvb-s2.js' if args.s2 else 'leandvb.js'))], check=True)

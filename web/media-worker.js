// Independent media worker: recovered RF transport stream is its only input.
importScripts('vendor/ffmpeg-core.js');
let core;
let busy=false;
onmessage=async ({data:m})=>{
  if(m.type!=='decode'||busy)return;
  busy=true;
  try {
    if(!core){
      const response=await fetch('vendor/ffmpeg-core.wasm');
      if(!response.ok)throw Error('Cannot load browser media codecs');
      core=await createFFmpegCore({wasmBinary:await response.arrayBuffer()});
    }
    core.setLogger(()=>{});
    core.FS.writeFile('input.ts',new Uint8Array(m.data));
    const skip=String(m.skip||0), duration=String(m.duration||3);
    const ret=core.exec('-hide_banner','-loglevel','error','-fflags','+genpts+discardcorrupt',
      '-probesize','1000000','-analyzeduration','1000000','-i','input.ts',
      '-ss',skip,'-t',duration,'-map','0:v:0','-an','-vf','scale=320:240,fps=10',
      '-pix_fmt','rgba','-f','rawvideo','video.raw',
      '-ss',skip,'-t',duration,'-map','0:a:0?','-vn','-ac','1','-ar','48000','-f','f32le','audio.raw');
    const video=core.FS.readFile('video.raw');
    let audio=new Uint8Array(0);
    try {audio=core.FS.readFile('audio.raw');}catch{}
    for(const file of ['input.ts','video.raw','audio.raw'])try{core.FS.unlink(file);}catch{}
    core.reset();
    if(!video.length)throw Error('No video frames yet; waiting for program tables and a keyframe ('+ret+')');
    postMessage({type:'media',video:video.buffer,audio:audio.buffer},[video.buffer,audio.buffer]);
  }catch(e){postMessage({type:'media-error',text:String(e)});}
  busy=false;
  postMessage({type:'idle'});
};

const $=id=>document.getElementById(id);
const RATE=2048000, FFT=2048, HISTORY=300;
let ws, decoder, media, ready=false, connected=false, ack=0, queued=0;
let tune=739e6, center=739e6, packets=0, tei=0, lastPacket=0, locked=false;
let tsParts=[], tsSize=0, mediaParts=[], mediaSize=0, mediaBusy=false, overlap=null;
let frameQueue=[], nextFrame=0, audioContext, audioTime=0, audioSources=[];
const log=s=>{const el=$('log');el.textContent=(el.textContent+'\n'+s).slice(-16000);el.scrollTop=el.scrollHeight;};
const state=s=>$('state').textContent=s;
const config=()=>({type:'start',rate:RATE,symbolRate:Number($('symbols').value)*1000,fec:$('fec').value,offset:tune-center});
const capacity=()=>Number($('symbols').value)*1000*2*Number($('fec').value.split('/')[0])/Number($('fec').value.split('/')[1])*188/204/8;

async function refresh(){
  const old=$('receiver').value;
  try {
    const devices=await (await fetch('/api/devices')).json();
    $('receiver').replaceChildren(...devices.map(d=>new Option(d.label,d.id)));
    $('receiver').value=devices.some(d=>d.id===old)?old:(devices.find(d=>d.preferred)||devices[0])?.id||'';
    if(!devices.length)$('receiver').add(new Option('No SDRone receivers found',''));
    $('connect').disabled=!devices.length;
  }catch(e){state('Receiver discovery failed');log(String(e));}
}
$('refresh').onclick=refresh;
await refresh();

function labels(){
  const offset=Number($('offset').value)*1e6;
  $('tuned').innerHTML=((tune+offset)/1e6).toFixed(6)+' <small>MHz '+(offset?'RF':'IF')+'</small>';
  $('axis').replaceChildren(...Array.from({length:7},(_,i)=>{
    const s=document.createElement('span');s.textContent=((center+(i/6-.5)*RATE+offset)/1e6).toFixed(3);return s;
  }));
  const width=Number($('symbols').value)*1000*1.35;
  $('bandwidth').textContent='Occupied bandwidth '+(width/1000).toFixed(1)+' kHz';
  $('selection').style.left=(50+(tune-center-width/2)/RATE*100)+'%';
  $('selection').style.width=(width/RATE*100)+'%';
}
function validTune(){
  const symbol=Number($('symbols').value)*1000;
  if(!Number.isFinite(symbol)||symbol<50000||symbol>1200000)throw Error('Symbol rate must be 50–1200 ksym/s');
  if(Math.abs(tune-center)+symbol*1.35/2>RATE/2)throw Error('Signal is outside captured bandwidth. Change center frequency and restart the receiver.');
}
function restartDecoder(){
  validTune();
  decoder?.terminate(); media?.terminate();
  // Reset acquisition and discard old-generation IQ and media.
  ready=false;queued=0;locked=false;lastPacket=0;packets=0;tei=0;ack=0;
  tsParts=[];tsSize=0;mediaParts=[];mediaSize=0;overlap=null;
  frameQueue=[];nextFrame=0;mediaBusy=false;audioTime=0;
  for(const source of audioSources)try{source.stop();}catch{}
  audioSources=[];
  $('packets').textContent='0';$('tei').textContent='0';$('download').disabled=true;
  $('video-placeholder').style.display='block';
  for(const id of ['mer','carrier','ber'])$(id).textContent='—';
  decoder=new Worker('decoder-worker.js');
  media=new Worker('media-worker.js');
  media.onmessage=({data:m})=>{
    if(m.type==='idle'){mediaBusy=false;decodeMedia();}
    else if(m.type==='media-error'){$('media-status').textContent=m.text;}
    else if(m.type==='media'){
      const v=new Uint8ClampedArray(m.video), count=Math.floor(v.length/(320*240*4));
      if(frameQueue.length>90)frameQueue=[];
      for(let i=0;i<count;i++)frameQueue.push(v.slice(i*320*240*4,(i+1)*320*240*4));
      $('media-status').textContent='Browser playback · '+count+' decoded frames · 320 × 240 / 10 fps';
      if(audioContext?.state==='running'&&m.audio.byteLength){
        const pcm=new Float32Array(m.audio), b=audioContext.createBuffer(1,pcm.length,48000);
        b.copyToChannel(pcm,0);const source=audioContext.createBufferSource();source.buffer=b;source.connect(audioContext.destination);
        audioTime=Math.max(audioTime,audioContext.currentTime+.15);source.start(audioTime);audioTime+=b.duration;
        audioSources.push(source);source.onended=()=>{audioSources=audioSources.filter(s=>s!==source);};
      }
    }
  };
  decoder.onmessage=({data:m})=>{
    if(m.type==='ready'){ready=true;state('Receiving IQ · acquiring DVB-S');}
    else if(m.type==='consumed'){
      queued=Math.max(0,queued-1);ack++;
      // Send current absolute network sequence, including blocks discarded during startup.
      if(ws?.readyState===1)ws.send(JSON.stringify({type:'ack',sequence:networkSequence-queued}));
    }else if(m.type==='ts')receivedTS(new Uint8Array(m.data));
    else if(m.type==='info'){
      for(const line of m.text.trim().split('\n')){
        const [key,value]=line.split(/\s+/);const n=Number(value);
        if(key==='MER')$('mer').textContent=n.toFixed(1)+' dB';
        if(key==='FREQ')$('carrier').textContent=(n/1000).toFixed(2)+' kHz';
        if(key==='VBER')$('ber').textContent=n.toExponential(2);
        if(key==='LOCK')locked=n===1;
      }
    }else if(m.type==='error'){log(m.text);stop();state('Decoder error');}
    else if(m.type==='log')log(m.text);
  };
  decoder.onerror=e=>{log(e.message);stop();state('Decoder worker failed');};
  decoder.postMessage(config());labels();
}
function receivedTS(data){
  for(let i=0;i+187<data.length;i+=188){if(data[i]===0x47){packets++;if(data[i+1]&0x80)tei++;}}
  lastPacket=performance.now();
  $('packets').textContent=packets.toLocaleString();$('tei').textContent=tei.toLocaleString();
  tsParts.push(data);tsSize+=data.length;
  while(tsSize>32*1024*1024){tsSize-=tsParts.shift().length;}
  $('download').disabled=false;
  mediaParts.push(data);mediaSize+=data.length;decodeMedia();
}
function join(parts){const out=new Uint8Array(parts.reduce((n,p)=>n+p.length,0));let i=0;for(const p of parts){out.set(p,i);i+=p.length;}return out;}
function decodeMedia(){
  const bytesPerSecond=capacity(), target=Math.ceil(bytesPerSecond*3/188)*188;
  if(mediaBusy||mediaSize<target)return;
  if(mediaSize>target*4){log('Media decoder fell behind; dropping old playback buffers. TS download is retained.');mediaParts=mediaParts.slice(-Math.ceil(mediaParts.length/3));mediaSize=mediaParts.reduce((n,p)=>n+p.length,0);overlap=null;}
  const data=join(mediaParts), previous=overlap;
  mediaParts=[];mediaSize=0;
  const tail=Math.floor(bytesPerSecond/188)*188;
  overlap=data.slice(Math.max(0,data.length-tail));
  const input=previous?join([previous,data]):data;
  mediaBusy=true;
  media.postMessage({type:'decode',data:input.buffer,skip:previous?1:0,duration:data.length/bytesPerSecond},[input.buffer]);
}
let networkSequence=0;
function stop(){
  ws?.close();ws=null;decoder?.terminate();decoder=null;media?.terminate();media=null;
  connected=false;ready=false;queued=0;locked=false;lastPacket=0;
  frameQueue=[];audioTime=0;
  for(const source of audioSources)try{source.stop();}catch{}
  audioSources=[];
  $('connect').textContent='Start receiver';
  for(const id of ['receiver','refresh','center','gain'])$(id).disabled=false;
  state('Offline');
}
function start(){
  try {
    center=Number($('center').value)*1e6;tune=Number($('frequency').value)*1e6;validTune();
    const gain=Number($('gain').value);
    if(!Number.isFinite(center)||center<50e6||center>2e9||!Number.isFinite(gain)||gain<0||gain>103)throw Error('Check center frequency and gain');
    restartDecoder();networkSequence=0;connected=true;
    ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/iq`);ws.binaryType='arraybuffer';
    ws.onopen=()=>ws.send(JSON.stringify({device:$('receiver').value,frequency:center,rate:RATE,gain}));
    ws.onmessage=({data})=>{
      if(typeof data==='string'){
        const m=JSON.parse(data);
        if(m.type==='error'){log(m.text);stop();state(m.text);}
        else if(m.type==='log')log(m.text);
        else if(m.type==='radio'){log('Opened '+m.device.label+' at '+m.frequency+' Hz, '+m.rate+' samples/s');}
        else if(m.type==='throughput')$('rate').textContent=(m.samples/m.seconds/1e6).toFixed(3)+' MS/s · '+(m.samples*8/m.seconds/1e6).toFixed(1)+' MB/s IQ';
      }else{
        networkSequence++;drawFFT(new Float32Array(data));
        if(ready){queued++;decoder.postMessage({type:'iq',data},[data]);}
        else ws.send(JSON.stringify({type:'ack',sequence:networkSequence}));
        $('queue').textContent=queued;
        if(queued>128){log('Browser DSP cannot keep up with live IQ');stop();state('DSP overload; reconnect to reacquire');}
      }
    };
    ws.onclose=()=>{if(connected){stop();state('Receiver disconnected');}};
    ws.onerror=()=>log('WebSocket connection failed');
    $('connect').textContent='Stop receiver';
    for(const id of ['receiver','refresh','center','gain'])$(id).disabled=true;
    state('Opening receiver…');
  }catch(e){log(String(e));state(e.message);}
}
$('connect').onclick=()=>connected?stop():start();
function retune(){try{tune=Number($('frequency').value)*1e6;validTune();if(connected)restartDecoder();labels();}catch(e){log(e.message);state(e.message);}}
$('decode').onclick=retune;
for(const id of ['frequency','symbols','fec'])$(id).onchange=retune;
$('offset').oninput=labels;
$('center').onchange=()=>{if(!connected){center=Number($('center').value)*1e6;tune=center;$('frequency').value=(tune/1e6).toFixed(6);labels();}};
$('qo').onclick=()=>{$('offset').value=Number($('offset').value)?0:9750;labels();};
$('plot').onclick=e=>{
  const r=$('plot').getBoundingClientRect();
  const half=Number($('symbols').value)*1000*1.35/2;
  tune=center+Math.max(-RATE/2+half,Math.min(RATE/2-half,((e.clientX-r.left)/r.width-.5)*RATE));
  $('frequency').value=(tune/1e6).toFixed(6);retune();
};
$('sound').onclick=async()=>{
  if(!audioContext){audioContext=new AudioContext({sampleRate:48000});await audioContext.resume();$('sound').textContent='Mute audio';return;}
  if(audioContext.state==='suspended'){await audioContext.resume();$('sound').textContent='Mute audio';}
  else {await audioContext.suspend();$('sound').textContent='Enable audio';}
};
$('download').onclick=()=>{
  const url=URL.createObjectURL(new Blob(tsParts,{type:'video/mp2t'}));const a=document.createElement('a');a.href=url;a.download='dvbs-'+(tune/1e6).toFixed(6)+'MHz.ts';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);
};
const video=$('video').getContext('2d');
function animate(now){
  if(frameQueue.length&&now>=nextFrame){video.putImageData(new ImageData(frameQueue.shift(),320,240),0,0);$('video-placeholder').style.display='none';nextFrame=now+100;}
    const good=connected&&locked&&lastPacket>0&&now-lastPacket<1800;
  $('lock').textContent=good?'● TS locked':connected?'○ Searching':'○ Offline';$('lock').classList.toggle('good',good);
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);

// FFT from a contiguous slice of each IQ block. Rendering stays in WebGL.
const re=new Float32Array(FFT), im=new Float32Array(FFT), db=new Float32Array(FFT);
const hann=Float32Array.from({length:FFT},(_,i)=>.5-.5*Math.cos(2*Math.PI*i/(FFT-1)));
const spectrum=$('spectrum'), ctx=spectrum.getContext('2d');
const canvas=$('waterfall'), gl=canvas.getContext('webgl',{antialias:false,preserveDrawingBuffer:true});
if(!gl) {state('WebGL unavailable');throw Error('A WebGL-capable browser is required');}
canvas.width=FFT;canvas.height=HISTORY;
function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;}
const program=gl.createProgram();
gl.attachShader(program,shader(gl.VERTEX_SHADER,'attribute vec2 p;varying vec2 uv;void main(){uv=(p+1.0)/2.0;gl_Position=vec4(p,0,1);}'));
gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`precision mediump float;varying vec2 uv;uniform sampler2D image;uniform float head;
void main(){float y=mod(head+${HISTORY}.0-(1.0-uv.y)*${HISTORY-1}.0,${HISTORY}.0);float v=texture2D(image,vec2(uv.x,(y+.5)/${HISTORY}.0)).r;
vec3 a=vec3(.025,.04,.12),b=vec3(.04,.38,.65),c=vec3(.12,.94,.76),d=vec3(1.,.88,.38);
gl_FragColor=vec4(v<.35?mix(a,b,v/.35):v<.7?mix(b,c,(v-.35)/.35):mix(c,d,(v-.7)/.3),1.);}`));
gl.linkProgram(program);gl.useProgram(program);
const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
const loc=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);
gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
gl.texImage2D(gl.TEXTURE_2D,0,gl.LUMINANCE,FFT,HISTORY,0,gl.LUMINANCE,gl.UNSIGNED_BYTE,new Uint8Array(FFT*HISTORY));
let row=0,lastDraw=0;const colors=new Uint8Array(FFT);
function drawFFT(iq){
  const now=performance.now();if(now-lastDraw<35)return;lastDraw=now;
  let meanR=0,meanI=0;for(let i=0;i<FFT;i++){meanR+=iq[2*i];meanI+=iq[2*i+1];}meanR/=FFT;meanI/=FFT;
  for(let i=0;i<FFT;i++){re[i]=(iq[2*i]-meanR)*hann[i];im[i]=(iq[2*i+1]-meanI)*hann[i];}
  for(let i=1,j=0;i<FFT;i++){let bit=FFT>>1;for(;j&bit;bit>>=1)j^=bit;j^=bit;if(i<j){[re[i],re[j]]=[re[j],re[i]];[im[i],im[j]]=[im[j],im[i]];}}
  for(let len=2;len<=FFT;len<<=1){const angle=-2*Math.PI/len,wr=Math.cos(angle),wi=Math.sin(angle);for(let i=0;i<FFT;i+=len){let r=1,s=0;for(let j=0;j<len/2;j++){const a=i+j,b=a+len/2,tr=r*re[b]-s*im[b],ti=r*im[b]+s*re[b];re[b]=re[a]-tr;im[b]=im[a]-ti;re[a]+=tr;im[a]+=ti;const nr=r*wr-s*wi;s=r*wi+s*wr;r=nr;}}}
  const floor=Number($('floor').value);
  for(let i=0;i<FFT;i++){const k=(i+FFT/2)%FFT;db[i]=10*Math.log10((re[k]**2+im[k]**2)/(FFT*FFT/4)+1e-15);colors[i]=Math.max(0,Math.min(255,(db[i]-floor)/55*255));}
  gl.texSubImage2D(gl.TEXTURE_2D,0,0,row,FFT,1,gl.LUMINANCE,gl.UNSIGNED_BYTE,colors);gl.uniform1f(gl.getUniformLocation(program,'head'),row);gl.viewport(0,0,FFT,HISTORY);gl.drawArrays(gl.TRIANGLE_STRIP,0,4);row=(row+1)%HISTORY;
  spectrum.width=Math.round(spectrum.clientWidth*devicePixelRatio);spectrum.height=140*devicePixelRatio;
  const w=spectrum.width,h=spectrum.height;ctx.clearRect(0,0,w,h);ctx.strokeStyle='#263449';ctx.lineWidth=1;
  for(let i=1;i<5;i++){ctx.beginPath();ctx.moveTo(0,h*i/5);ctx.lineTo(w,h*i/5);ctx.stroke();}
  ctx.beginPath();for(let i=0;i<FFT;i++){const x=i*w/FFT,y=h-Math.max(0,Math.min(1,(db[i]-floor)/55))*h;if(!i)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.strokeStyle='#63dfc4';ctx.stroke();
}
labels();
window.addEventListener('beforeunload',()=>ws?.close());

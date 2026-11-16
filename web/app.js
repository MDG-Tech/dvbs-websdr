const $=id=>document.getElementById(id);
let RATE=10000000, channelRate=5000000;
const FFT=2048, HISTORY=300;
let ws, decoder, media, ready=false, connected=false, ack=0, queued=0;
let tune=741.5e6, center=745e6, packets=0, tei=0, lastPacket=0, locked=false;
let tsParts=[], tsSize=0, mediaParts=[], mediaSize=0, mediaBusy=false, overlap=null;
let frameQueue=[], nextFrame=0, audioContext, audioTime=0, audioSources=[];
const log=s=>{const el=$('log');el.textContent=(el.textContent+'\n'+s).slice(-16000);el.scrollTop=el.scrollHeight;};
const state=s=>$('state').textContent=s;
const isS2=()=>$('standard').value==='DVB-S2';
const rolloff=()=>Number($('rolloff').value);
const lo=()=>Number($('offset').value)*1e6+Number($('lo-correction').value)*1000;
const modcodNames=['Auto','QPSK 1/4','QPSK 1/3','QPSK 2/5','QPSK 1/2','QPSK 3/5','QPSK 2/3','QPSK 3/4','QPSK 4/5','QPSK 5/6','QPSK 8/9','QPSK 9/10','8PSK 3/5','8PSK 2/3','8PSK 3/4','8PSK 5/6','8PSK 8/9','8PSK 9/10','16APSK 2/3','16APSK 3/4','16APSK 4/5','16APSK 5/6','16APSK 8/9','16APSK 9/10','32APSK 3/4','32APSK 4/5','32APSK 5/6','32APSK 8/9','32APSK 9/10'];
for(let i=1;i<modcodNames.length;i++)$('modcod').add(new Option(modcodNames[i],i));
$('modcod').value=8;
let detectedModcod=0,pcrRate=0,pcrPrevious=null,tsPosition=0;
const config=()=>({type:'start',standard:$('standard').value,rate:channelRate,symbolRate:Number($('symbols').value)*1000,fec:$('fec').value,offset:0,rolloff:rolloff(),modcod:Number($('modcod').value),framesizes:Number($('framesizes').value)});
function updateMode(){
  $('fec').disabled=isS2();$('modcod').disabled=!isS2();$('framesizes').disabled=!isS2();
  $('profile').textContent=isS2()?'DVB-S2 · PLS / LDPC / BCH':'DVB-S · QPSK / Viterbi / Reed–Solomon';
  $('ber-label').textContent=isS2()?'BCH error fraction':'Viterbi BER';
  $('video-placeholder').innerHTML='Waiting for a '+$('standard').value+' transport stream<span>'+(isS2()?'PLS → LDPC → BCH':'QPSK → Viterbi → Reed–Solomon')+' → MPEG-TS → video</span>';
}
updateMode();
const capacity=()=>{
  if(pcrRate>0)return pcrRate;
  const name=isS2()?modcodNames[detectedModcod||Number($('modcod').value)||8]:'QPSK '+$('fec').value;
  const [mod,fec]=name.split(' '),[a,b]=fec.split('/').map(Number);
  return Number($('symbols').value)*1000*({QPSK:2,'8PSK':3,'16APSK':4,'32APSK':5}[mod])*a/b/8*(isS2()?.97:188/204);
};

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
  const offset=lo();$('span').textContent=(RATE/1e6)+' MS/s';
  $('tuned').innerHTML=((tune+offset)/1e6).toFixed(6)+' <small>MHz '+(offset?'RF':'IF')+'</small>';
  $('axis').replaceChildren(...Array.from({length:7},(_,i)=>{
    const s=document.createElement('span');s.textContent=((center+(i/6-.5)*RATE+offset)/1e6).toFixed(3);return s;
  }));
  const width=Number($('symbols').value)*1000*(1+rolloff());
  $('bandwidth').textContent='Occupied bandwidth '+(width/1000).toFixed(1)+' kHz';
  $('selection').style.left=(50+(tune-center-width/2)/RATE*100)+'%';
  $('selection').style.width=(width/RATE*100)+'%';
}
function validTune(){
  const symbol=Number($('symbols').value)*1000;
  if(!Number.isFinite(symbol)||symbol<10000||symbol>2000000)throw Error('Symbol rate must be 10–2000 ksym/s');
  if(!Number.isFinite(tune)||Math.abs(tune-center)+symbol*(1+rolloff())/2>=RATE*.48)throw Error('Signal is outside usable capture bandwidth. Change center frequency and restart the receiver.');
}
function restartDecoder(){
  validTune();
  decoder?.terminate(); media?.terminate();
  // Reset acquisition and discard old-generation IQ and media.
  ready=false;queued=0;locked=false;lastPacket=0;packets=0;tei=0;ack=0;
  tsParts=[];tsSize=0;mediaParts=[];mediaSize=0;overlap=null;pcrRate=0;pcrPrevious=null;tsPosition=0;detectedModcod=0;updateMode();
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
    if(m.type==='ready'){ready=true;state('Receiving IQ · acquiring '+$('standard').value);}
    else if(m.type==='consumed'){
      queued=Math.max(0,queued-1);ack++;
    }else if(m.type==='ts')receivedTS(new Uint8Array(m.data));
    else if(m.type==='info'){
      for(const line of m.text.trim().split('\n')){
        const [key,value]=line.split(/\s+/);const n=Number(value);
        if(key==='MER')$('mer').textContent=n.toFixed(1)+' dB';
        if(key==='FREQ')$('carrier').textContent=(n/1000).toFixed(2)+' kHz';
        if(key==='VBER')$('ber').textContent=n.toExponential(2);
        if(key==='LOCK')locked=n===1;
        if(key==='MODCOD'){
          detectedModcod=n;
          $('profile').textContent='DVB-S2 · '+modcodNames[n]+' · '+(line.split(/\s+/)[2]==='1'?'short':'normal')+' frames';
        }
      }
    }else if(m.type==='error'){log(m.text);stop();state('Decoder error');}
    else if(m.type==='log')log(m.text);
  };
  decoder.onerror=e=>{log(e.message);stop();state('Decoder worker failed');};
  decoder.postMessage(config());labels();
}
function receivedTS(data){
  for(let i=0;i+187<data.length;i+=188){if(data[i]===0x47){
    packets++;if(data[i+1]&0x80)tei++;
    if((data[i+3]&0x20)&&data[i+4]>=7&&(data[i+5]&0x10)){
      const pid=((data[i+1]&31)<<8)|data[i+2];
      const pcr=data[i+6]*33554432+data[i+7]*131072+data[i+8]*512+data[i+9]*2+(data[i+10]>>7);
      const position=tsPosition+i;
      if(pcrPrevious?.pid===pid){const dt=(pcr-pcrPrevious.value)/90000;if(dt>.005&&dt<2){const rate=(position-pcrPrevious.position)/dt;if(rate>100&&rate<2e7)pcrRate=rate;}}
      pcrPrevious={pid,value:pcr,position};
    }
  }}
  tsPosition+=data.length;
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
  for(const id of ['receiver','refresh','center','gain','capture-rate'])$(id).disabled=false;
  state('Offline');
}
function start(){
  try {
    RATE=Number($('capture-rate').value);channelRate=RATE/Math.max(1,Math.floor(RATE/(Number($('symbols').value)*2200)));
    $('span').textContent=(RATE/1e6)+' MS/s';
    center=Number($('center').value)*1e6;tune=Number($('frequency').value)*1e6;validTune();
    const gain=Number($('gain').value);
    if(!Number.isFinite(center)||center<50e6||center>2e9||!Number.isFinite(gain)||gain<0||gain>103)throw Error('Check center frequency and gain');
    restartDecoder();networkSequence=0;connected=true;
    ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/iq`);ws.binaryType='arraybuffer';
    ws.onopen=()=>ws.send(JSON.stringify({device:$('receiver').value,frequency:center,rate:RATE,gain,wide:true,tune,symbols:Number($('symbols').value)*1000,rolloff:rolloff()}));
    ws.onmessage=({data})=>{
      if(typeof data==='string'){
        const m=JSON.parse(data);
        if(m.type==='error'){log(m.text);stop();state(m.text);}
        else if(m.type==='log')log(m.text);
        else if(m.type==='spectrum')drawSpectrum(m.db);
        else if(m.type==='channel'){channelRate=m.rate;restartDecoder();log('Selected channel IQ: '+Math.round(channelRate)+' samples/s');}
        else if(m.type==='radio'){log('Opened '+m.device.label+' at '+m.frequency+' Hz, '+m.rate+' samples/s');}
        else if(m.type==='throughput')$('rate').textContent='Capture '+(m.samples/m.seconds/1e6).toFixed(3)+' MS/s · selected IQ '+(channelRate*8/1e6).toFixed(1)+' MB/s';
      }else{
        networkSequence++;
        ws.send(JSON.stringify({type:'ack',sequence:networkSequence}));
        if(ready){queued++;decoder.postMessage({type:'iq',data},[data]);}
        else ws.send(JSON.stringify({type:'ack',sequence:networkSequence}));
        $('queue').textContent=queued;
        if(queued>Math.ceil(2*RATE/32768)+8){
          log('DSP backlog exceeded two seconds. Overview remains live; click the signal or Reacquire to restart decoding.');
          decoder?.terminate();decoder=null;ready=false;queued=0;locked=false;
          state('Decoder busy · overview live · click Reacquire');
        }
      }
    };
    ws.onclose=()=>{if(connected){stop();state('Receiver disconnected');}};
    ws.onerror=()=>log('WebSocket connection failed');
    $('connect').textContent='Stop receiver';
    for(const id of ['receiver','refresh','center','gain','capture-rate'])$(id).disabled=true;
    state('Opening receiver…');
  }catch(e){log(String(e));state(e.message);}
}
$('connect').onclick=()=>connected?stop():start();
function retune(){try{tune=Number($('frequency').value)*1e6;validTune();
  if(connected){ready=false;ws.send(JSON.stringify({type:'tune',tune,symbols:Number($('symbols').value)*1000,rolloff:rolloff()}));}
  updateMode();labels();}catch(e){log(e.message);state(e.message);}}
$('decode').onclick=retune;
for(const id of ['frequency','symbols','fec','standard','rolloff','modcod','framesizes'])$(id).onchange=retune;
$('offset').oninput=labels;$('lo-correction').oninput=labels;
$('capture-rate').onchange=()=>{RATE=Number($('capture-rate').value);labels();};
$('center').onchange=()=>{if(!connected){center=Number($('center').value)*1e6;tune=center;$('frequency').value=(tune/1e6).toFixed(6);labels();}};
async function satellitePreset(beacon){
 const wasConnected=connected,old=ws,needsRestart=wasConnected&&(RATE!==10000000||center!==745e6);
 if(needsRestart){stop();if(old.readyState!==3)await new Promise(resolve=>old.addEventListener('close',resolve,{once:true}));}
 $('offset').value=9750;$('center').value=745;$('capture-rate').value=10000000;
 RATE=10000000;center=745e6;tune=(beacon?741.5e6:747.25e6)-Number($('lo-correction').value)*1000;
 $('frequency').value=(tune/1e6).toFixed(6);$('standard').value='DVB-S2';
 $('symbols').value=beacon?1500:333;$('modcod').value=beacon?8:0;updateMode();labels();
 if(needsRestart)start();else if(wasConnected)retune();
}
$('qo').onclick=()=>satellitePreset(false);$('beacon').onclick=()=>satellitePreset(true);
$('bench').onclick=async()=>{
 const old=ws,wasConnected=connected;if(wasConnected){stop();if(old.readyState!==3)await new Promise(resolve=>old.addEventListener('close',resolve,{once:true}));}
 $('offset').value=0;$('lo-correction').value=0;$('center').value=739;$('frequency').value=739;
 $('capture-rate').value=2048000;$('symbols').value=333;$('standard').value='DVB-S';
 RATE=2048000;center=tune=739e6;updateMode();labels();if(wasConnected)start();
};
$('plot').onclick=e=>{
  const r=$('plot').getBoundingClientRect();
  const half=Number($('symbols').value)*1000*(1+rolloff())/2;
  tune=center+Math.max(-RATE*.479+half,Math.min(RATE*.479-half,((e.clientX-r.left)/r.width-.5)*RATE));
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

// Wideband FFT values arrive independently from the selected channel IQ.
const db=new Float32Array(FFT);
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
function drawSpectrum(values){
  const floor=Number($('floor').value);db.set(values);
  for(let i=0;i<FFT;i++)colors[i]=Math.max(0,Math.min(255,(db[i]-floor)/55*255));
  gl.texSubImage2D(gl.TEXTURE_2D,0,0,row,FFT,1,gl.LUMINANCE,gl.UNSIGNED_BYTE,colors);gl.uniform1f(gl.getUniformLocation(program,'head'),row);gl.viewport(0,0,FFT,HISTORY);gl.drawArrays(gl.TRIANGLE_STRIP,0,4);row=(row+1)%HISTORY;
  spectrum.width=Math.round(spectrum.clientWidth*devicePixelRatio);spectrum.height=140*devicePixelRatio;
  const w=spectrum.width,h=spectrum.height;ctx.clearRect(0,0,w,h);ctx.strokeStyle='#263449';ctx.lineWidth=1;
  for(let i=1;i<5;i++){ctx.beginPath();ctx.moveTo(0,h*i/5);ctx.lineTo(w,h*i/5);ctx.stroke();}
  ctx.beginPath();for(let i=0;i<FFT;i++){const x=i*w/FFT,y=h-Math.max(0,Math.min(1,(db[i]-floor)/55))*h;if(!i)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.strokeStyle='#63dfc4';ctx.stroke();
}
labels();
window.addEventListener('beforeunload',()=>ws?.close());

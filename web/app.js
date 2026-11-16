const $=id=>document.getElementById(id);
let RATE=10000000;
const FFT=2048, HISTORY=300;
let ws, media, connected=false, serverState="overview", viewers=0,replayActive=false,acceptedSelection=null;
let tune=741.5e6, center=745e6, packets=0, tei=0,serverTei=0,lastPacket=0, locked=false;
let tsParts=[], tsSize=0, mediaParts=[], mediaSize=0, mediaBusy=false, overlap=null;
let frameQueue=[], nextFrame=0, audioContext, audioTime=0, audioSources=[];
const log=s=>{const el=$('log');el.textContent=(el.textContent+'\n'+s).slice(-16000);el.scrollTop=el.scrollHeight;};
const state=s=>$('state').textContent=(replayActive?'Replay · ':'')+s;
const isS2=()=>$('standard').value!=='DVB-S';
const rolloff=()=>Number($('rolloff').value);
const lo=()=>Number($('offset').value)*1e6+Number($('lo-correction').value)*1000;
const modcodNames=['Auto','QPSK 1/4','QPSK 1/3','QPSK 2/5','QPSK 1/2','QPSK 3/5','QPSK 2/3','QPSK 3/4','QPSK 4/5','QPSK 5/6','QPSK 8/9','QPSK 9/10','8PSK 3/5','8PSK 2/3','8PSK 3/4','8PSK 5/6','8PSK 8/9','8PSK 9/10','16APSK 2/3','16APSK 3/4','16APSK 4/5','16APSK 5/6','16APSK 8/9','16APSK 9/10','32APSK 3/4','32APSK 4/5','32APSK 5/6','32APSK 8/9','32APSK 9/10'];
for(let i=1;i<modcodNames.length;i++)$('modcod').add(new Option(modcodNames[i],i));
$('modcod').value=0;
let detectedModcod=0,pcrRate=0,pcrPrevious=null,tsPosition=0,confirmedSymbols=0,serverBitrate=0,lastSearchMessage='',estimatedSymbols=0;
const selection=()=>({type:'tune',tune,symbols:Number($('symbols').value)*1000,
  standard:$('standard').value,auto_symbols:$('auto-symbols').checked,fec:$('fec').value,
  modcod:Number($('modcod').value),framesizes:Number($('framesizes').value),rolloff:rolloff()});
function updateMode(){
  $('fec').disabled=$('standard').value==='DVB-S2';
  $('modcod').disabled=$('standard').value==='DVB-S';$('framesizes').disabled=!isS2();
  $('ber-label').textContent='Decoder error fraction';
  $('video-placeholder').innerHTML='Waiting for a server-decoded transport stream<span>Server DVB-S/S2 recovery → MPEG-TS → browser video/audio</span>';
}
updateMode();
const capacity=()=>{
  if(pcrRate>0)return pcrRate;
  if(serverBitrate>0)return serverBitrate/8;
  const name=isS2()?modcodNames[detectedModcod||Number($('modcod').value)||8]:'QPSK '+$('fec').value;
  const [mod,fec]=name.split(' '),[a,b]=(fec==='Auto'?'1/2':fec).split('/').map(Number);
  return Number($('symbols').value)*1000*({QPSK:2,'8PSK':3,'16APSK':4,'32APSK':5}[mod])*a/b/8*(isS2()?.97:188/204);
};
const receiverDetails=new Map();
function adoptSharedCapture(){
  const active=receiverDetails.get($('receiver').value)?.active;
  if(connected||!active)return;
  center=active.frequency;RATE=active.rate;
  $('center').value=center/1e6;$('capture-rate').value=RATE;$('gain').value=active.gain;
  if(Math.abs(tune-center)>=RATE*.48){tune=center;$('frequency').value=(tune/1e6).toFixed(6);}
  state('Receiver already shared · select a signal in its current capture');labels();
}
$('receiver').onchange=adoptSharedCapture;

async function refresh(){
  const old=$('receiver').value;
  try {
    const devices=await (await fetch('/api/devices')).json();
    receiverDetails.clear();for(const device of devices)receiverDetails.set(device.id,device);
    $('receiver').replaceChildren(...devices.map(d=>{
      const option=new Option(d.label+(d.active?' · shared by '+d.active.viewers+' user(s)':''),d.id);
      option.disabled=d.selectable===false;return option;
    }));
    $('receiver').value=(devices.find(d=>d.active)||devices.find(d=>d.id===old&&d.selectable!==false)||devices.find(d=>d.preferred)||devices[0])?.id||'';
    if(!devices.length)$('receiver').add(new Option('No SDRone receivers found',''));
    $('connect').disabled=!devices.length;
    adoptSharedCapture();
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
  const width=(confirmedSymbols||estimatedSymbols||Number($('symbols').value)*1000)*(1+rolloff());
  $('bandwidth').textContent=(confirmedSymbols?'Occupied bandwidth ':'Estimated bandwidth ')+(width/1000).toFixed(1)+' kHz';
  $('selection').style.left=(50+(tune-center-width/2)/RATE*100)+'%';
  $('selection').style.width=(width/RATE*100)+'%';
}
function validTune(){
  const symbol=Number($('symbols').value)*1000;
  if(!Number.isFinite(symbol)||symbol<10000||symbol>2000000)throw Error('Symbol rate must be 10–2000 ksym/s');
  if(!Number.isFinite(tune)||Math.abs(tune-center)+($('auto-symbols').checked?0:symbol*(1+rolloff())/2)>=RATE*.48)throw Error('Signal is outside usable capture bandwidth. Change center frequency and restart the receiver.');
}
function resetPlayback(){
  media?.terminate();
  // Clear old TS and decoded media when selecting another channel.
  locked=false;lastPacket=0;packets=0;tei=0;serverTei=0;confirmedSymbols=0;estimatedSymbols=0;
  tsParts=[];tsSize=0;mediaParts=[];mediaSize=0;overlap=null;pcrRate=0;pcrPrevious=null;tsPosition=0;detectedModcod=0;serverBitrate=0;lastSearchMessage='';updateMode();
  frameQueue=[];nextFrame=0;mediaBusy=false;audioTime=0;
  for(const source of audioSources)try{source.stop();}catch{}
  audioSources=[];
  $('packets').textContent='0';$('tei').textContent='0';$('download').disabled=true;
  $('video-placeholder').style.display='block';
  for(const id of ['mer','carrier','ber'])$(id).textContent='—';
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
  labels();
}
function decoderStatus(m){
  viewers=m.viewers;serverState=m.state;
  locked=m.state==='locked';
  if(!locked)confirmedSymbols=0;
  estimatedSymbols=m.estimate?.symbols||0;
  if(m.profile){
    const p=m.profile,metrics=m.metrics||{};
    if(locked){
      confirmedSymbols=p.symbols;detectedModcod=p.modcod||0;
      $('profile').textContent=p.standard+' · '+p.modulation+' · '+(p.symbols/1000)+' ksym/s'+
        (p.standard==='DVB-S2'?' · '+(p.short?'short':'normal')+' frames':'');
      state('TS locked · server decoder · '+viewers+' viewer'+(viewers===1?'':'s'));
    }else{
      $('profile').textContent='Searching '+p.standard+' · '+(p.symbols/1000)+' ksym/s'+(p.standard==='DVB-S'?' · FEC '+p.fec:' · PLS auto');
      state(m.message||'Server acquiring signal · attempt '+m.trial);
    }
    if(metrics.MER!==undefined)$('mer').textContent=metrics.MER.toFixed(1)+' dB';
    if(metrics.FREQ!==undefined)$('carrier').textContent=(metrics.FREQ/1000).toFixed(2)+' kHz';
    if(metrics.VBER!==undefined)$('ber').textContent=metrics.VBER.toExponential(2);
  }
  if(m.bitrate>0){serverBitrate=m.bitrate;$('rate').textContent='TS '+(m.bitrate/1000).toFixed(1)+' kbit/s · '+viewers+' viewer(s) sharing decoder';}
  $('queue').textContent=m.iq_queue??0;
  serverTei=m.tei||0;$('tei').textContent=Math.max(serverTei,tei).toLocaleString();
  $('viewers').textContent=viewers;
  const text=m.estimate?'Estimated '+Math.round(m.estimate.symbols/1000)+' ksym/s; '+(locked?'TS-validated lock':'search hint only'):'No reliable spectrum estimate; trying rate hint';
  $('detection').textContent=text;
  if(m.message&&m.message!==lastSearchMessage){log(m.message);lastSearchMessage=m.message;}
  labels();
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
  $('packets').textContent=packets.toLocaleString();$('tei').textContent=Math.max(serverTei,tei).toLocaleString();
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
function stop(){
  const socket=ws;ws=null;socket?.close();media?.terminate();media=null;
  connected=false;locked=false;lastPacket=0;serverState='overview';replayActive=false;
  frameQueue=[];audioTime=0;
  for(const source of audioSources)try{source.stop();}catch{}
  audioSources=[];
  $('connect').textContent='Start receiver';
  for(const id of ['receiver','refresh','center','gain','capture-rate'])$(id).disabled=false;
  state('Offline');
}
function start(){
  try {
    RATE=Number($('capture-rate').value);center=Number($('center').value)*1e6;
    tune=Number($('frequency').value)*1e6;validTune();
    const gain=Number($('gain').value);
    if(!Number.isFinite(center)||center<50e6||center>2e9||!Number.isFinite(gain)||gain<0||gain>103)throw Error('Check center frequency and gain');
    resetPlayback();connected=true;
    const socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/stream`);
    ws=socket;socket.binaryType='arraybuffer';
    socket.onopen=()=>socket.send(JSON.stringify({...selection(),device:$('receiver').value,frequency:center,rate:RATE,gain}));
    socket.onmessage=({data})=>{
      if(ws!==socket)return;
      if(typeof data==='string'){
        const m=JSON.parse(data);
        if(m.type==='error'){log(m.text);stop();state(m.text);}
        else if(m.type==='selection_error'){
          if(acceptedSelection){
            const previous=acceptedSelection.requested;
            tune=acceptedSelection.tune;$('frequency').value=(tune/1e6).toFixed(6);
            $('symbols').value=previous.symbols/1000;$('standard').value=previous.standard;
            $('auto-symbols').checked=previous.auto_symbols;$('fec').value=previous.fec;
            $('modcod').value=previous.modcod;$('framesizes').value=previous.framesizes;
            $('rolloff').value=previous.rolloff;updateMode();labels();
          }
          log(m.text);state(m.text);
        }
        else if(m.type==='log')log(m.text);
        else if(m.type==='welcome'){
          replayActive=m.replay;
          center=m.frequency;RATE=m.rate;
          if(![...$('capture-rate').options].some(o=>Number(o.value)===RATE))$('capture-rate').add(new Option((RATE/1e6)+' MHz · replay',RATE));
          $('capture-rate').value=RATE;$('center').value=(center/1e6);$('gain').value=m.gain;
          log((m.replay?'REPLAY fixture (not live RF). ':'')+'Shared capture '+(RATE/1e6)+' MS/s; network carries TS and FFT only.');
          state(m.replay?'Replay acquisition · not live RF':'Shared receiver connected');labels();
        }else if(m.type==='selected'){
          resetPlayback();tune=m.tune;
          if(document.activeElement!==$('frequency'))$('frequency').value=(tune/1e6).toFixed(6);
          acceptedSelection=m.requested?{requested:m.requested,tune:m.tune}:null;
          serverState=m.state||'searching';$('profile').textContent='Server acquiring selected signal';labels();
        }else if(m.type==='decoder')decoderStatus(m);
        else if(m.type==='capture'){
          $('capture-users').textContent=m.viewers;
          if(!serverBitrate)$('rate').textContent='Capture '+(m.samples/m.seconds/1e6).toFixed(3)+' MS/s · '+m.viewers+' user(s) · '+m.decoders+' decoder(s)';
        }
      }else{
        const bytes=new Uint8Array(data);
        if(bytes[0]===70&&bytes.length===FFT+1)drawSpectrum(Float32Array.from(bytes.subarray(1),v=>v/255*140-140));
        else if(bytes[0]===84)receivedTS(bytes.subarray(1));
        else{log('Unexpected binary stream frame');stop();}
      }
    };
    socket.onclose=e=>{if(ws===socket&&connected){stop();state(e.code===1013?'Client fell behind; reconnect to resume':'Receiver disconnected');}};
    socket.onerror=()=>log('WebSocket connection failed');
    $('connect').textContent='Stop receiver';
    for(const id of ['receiver','refresh','center','gain','capture-rate'])$(id).disabled=true;
    state('Opening shared receiver…');
  }catch(e){log(String(e));state(e.message);}
}
$('connect').onclick=()=>connected?stop():start();
function retune(rescan=false){try{
  tune=Number($('frequency').value)*1e6;confirmedSymbols=0;validTune();
  if(connected)ws.send(JSON.stringify({...selection(),rescan}));
  updateMode();labels();
}catch(e){log(e.message);state(e.message);}}
$('decode').onclick=()=>retune(true);
$('overview').onclick=()=>{if(connected){ws.send(JSON.stringify({type:'overview'}));resetPlayback();serverState='overview';state('Waterfall only · click a signal to decode');}};
for(const id of ['frequency','symbols','fec','standard','rolloff','modcod','framesizes','auto-symbols'])$(id).onchange=()=>retune();
$('offset').oninput=labels;$('lo-correction').oninput=labels;
$('capture-rate').onchange=()=>{RATE=Number($('capture-rate').value);labels();};
$('center').onchange=()=>{if(!connected){center=Number($('center').value)*1e6;labels();}};
async function satellitePreset(beacon){
 const wasConnected=connected,old=ws,needsRestart=wasConnected&&(RATE!==10000000||center!==745e6);
 if(needsRestart){stop();if(old.readyState!==3)await new Promise(resolve=>old.addEventListener('close',resolve,{once:true}));}
 $('offset').value=9750;$('center').value=745;$('capture-rate').value=10000000;
 RATE=10000000;center=745e6;tune=(beacon?741.5e6:747.25e6)-Number($('lo-correction').value)*1000;
 $('frequency').value=(tune/1e6).toFixed(6);$('standard').value='DVB-S2';
 $('symbols').value=beacon?1500:333;$('modcod').value=beacon?8:0;$('standard').value=beacon?'DVB-S2':'Auto';$('auto-symbols').checked=!beacon;updateMode();labels();
 if(needsRestart)start();else if(wasConnected)retune();
}
$('qo').onclick=()=>satellitePreset(false);$('beacon').onclick=()=>satellitePreset(true);
$('bench').onclick=async()=>{
 const old=ws,wasConnected=connected;if(wasConnected){stop();if(old.readyState!==3)await new Promise(resolve=>old.addEventListener('close',resolve,{once:true}));}
 $('offset').value=0;$('lo-correction').value=0;$('center').value=739;$('frequency').value=739;
 $('capture-rate').value=2048000;$('symbols').value=333;$('standard').value='Auto';$('auto-symbols').checked=true;$('modcod').value=0;$('fec').value='Auto';
 RATE=2048000;center=tune=739e6;updateMode();labels();if(wasConnected)start();
};
$('plot').onclick=e=>{
  const r=$('plot').getBoundingClientRect();
  const half=$('auto-symbols').checked?0:Number($('symbols').value)*1000*(1+rolloff())/2;
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
  $('lock').textContent=good?'● TS locked':connected?(serverState==='overview'?'○ Overview':'○ Searching'):'○ Offline';$('lock').classList.toggle('good',good);
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

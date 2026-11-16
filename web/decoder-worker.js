let decoder;
onmessage = async ({data: m}) => {
  if (m.type === 'start') {
    try {
      const s2=m.standard==='DVB-S2';
      importScripts(s2?'vendor/leandvb-s2.js':'vendor/leandvb.js');
      decoder = await createLeanDVB({noInitialRun:true,
        locateFile:p => 'vendor/'+p,
        printErr:text => postMessage({type:'log', text}),
        print:text => postMessage({type:'log', text})});
      decoder.iqQueue=[]; decoder.iqOffset=0; decoder.eof=false;
      postMessage({type:'ready'});
      const args=['--f32','--float-scale','128','-f',String(m.rate),
        '--sr',String(m.symbolRate),'--sampler','rrc','--roll-off',String(m.rolloff||.35),
        '--rrc-rej','30','--fastlock','--anf','0',
        '--derotate',String(m.offset || 0),'--fd-info','3'];
      if(s2)args.push('--standard','DVB-S2','--ldpc-bf',String(m.bitflips??100),
        '--framesizes',String(m.framesizes||3), '--modcods',String(m.modcod?2**m.modcod:0x1ffffffe));
      else args.push('--cr',m.fec,'--viterbi');
      decoder.callMain(args);
    } catch(e) {postMessage({type:'error',text:String(e)});}
  } else if (m.type === 'iq' && decoder) {
    // RSP1 clones can have a large ADC DC bias. Remove it before carrier recovery.
    const iq=new Float32Array(m.data);let r=0,i=0;
    for(let j=0;j<iq.length;j+=2){r+=iq[j];i+=iq[j+1];}
    r/=iq.length/2;i/=iq.length/2;
    for(let j=0;j<iq.length;j+=2){iq[j]-=r;iq[j+1]-=i;}
    decoder.iqQueue.push(new Uint8Array(m.data));
    if(decoder.wakeIQ) {const wake=decoder.wakeIQ; decoder.wakeIQ=null; wake();}
  } else if(m.type==='end' && decoder) {
    decoder.eof=true; if(decoder.wakeIQ) decoder.wakeIQ();
  }
};

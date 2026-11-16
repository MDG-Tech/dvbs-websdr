"""Streaming, phase-continuous receive channel extraction for wideband mode."""
import numpy as np
from scipy.signal import firwin, upfirdn


class Channelizer:
    def __init__(self, rate, symbol_rate, offset):
        self.rate=float(rate)
        self.decimation=max(1,int(rate/(symbol_rate*2.2)))
        self.output_rate=rate/self.decimation
        self.offset=float(offset)
        self.position=0
        # Filter only when decimating; the browser's RRC handles symbol shaping.
        self.taps=(firwin(16*self.decimation+1,
            min(symbol_rate*.8,self.output_rate*.42),fs=rate).astype(np.float32)
            if self.decimation>1 else np.array([1],np.float32))
        self.history=np.zeros(len(self.taps)-1,np.complex64)
        self.phase=0.
        self.oscillator=None

    def process(self, samples):
        n=len(samples)
        if self.offset:
            if self.oscillator is None or len(self.oscillator)!=n:
                self.oscillator=np.exp(-2j*np.pi*self.offset/self.rate*np.arange(n)).astype(np.complex64)
            samples=samples*self.oscillator*np.complex64(np.exp(-1j*self.phase))
            self.phase=(self.phase+2*np.pi*self.offset/self.rate*n)%(2*np.pi)
        if self.decimation==1:
            return samples.astype('<c8',copy=False)
        # Prefix enough true input history to preserve FIR state across blocks.
        combined=np.concatenate((self.history,samples))
        prefix=len(self.history)
        start=(-self.position)%self.decimation
        # upfirdn's first output is the convolution at index zero; align to the
        # next desired absolute input index rather than restarting decimation.
        shift=(prefix+start)%self.decimation
        filtered=upfirdn(self.taps,combined[shift:],down=self.decimation)
        first=(prefix+start-shift)//self.decimation
        count=max(0,(n-start+self.decimation-1)//self.decimation)
        out=filtered[first:first+count]
        self.history=combined[-prefix:].copy()
        self.position+=n
        return out.astype('<c8',copy=False)

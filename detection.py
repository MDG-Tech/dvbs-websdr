"""Bounded acquisition plans; estimates are distinct from TS-validated locks."""
from dataclasses import dataclass
import math
import numpy as np
from scipy.ndimage import uniform_filter1d

COMMON_RATES = (33000, 66000, 125000, 250000, 333000, 500000, 1000000, 1500000, 2000000)
DVBS_FEC = ('1/2', '2/3', '3/4', '5/6', '7/8')
MODCOD_NAMES = ['Unknown', 'QPSK 1/4', 'QPSK 1/3', 'QPSK 2/5', 'QPSK 1/2',
    'QPSK 3/5', 'QPSK 2/3', 'QPSK 3/4', 'QPSK 4/5', 'QPSK 5/6', 'QPSK 8/9',
    'QPSK 9/10', '8PSK 3/5', '8PSK 2/3', '8PSK 3/4', '8PSK 5/6', '8PSK 8/9',
    '8PSK 9/10', '16APSK 2/3', '16APSK 3/4', '16APSK 4/5', '16APSK 5/6',
    '16APSK 8/9', '16APSK 9/10', '32APSK 3/4', '32APSK 4/5', '32APSK 5/6',
    '32APSK 8/9', '32APSK 9/10']


@dataclass(frozen=True)
class Selection:
    tune: float
    symbols: int = 1500000  # manual rate or search hint
    standard: str = 'Auto'
    auto_symbols: bool = True
    fec: str = 'Auto'
    modcod: int = 0
    framesizes: int = 3
    rolloff: float = .35

    @classmethod
    def parse(cls, data, center, rate):
        s = cls(float(data.get('tune', center)), int(float(data.get('symbols', 1500000))),
                str(data.get('standard', 'Auto')), bool(data.get('auto_symbols', True)),
                str(data.get('fec', 'Auto')), int(data.get('modcod', 0)),
                int(data.get('framesizes', 3)), float(data.get('rolloff', .35)))
        if (s.standard not in ('Auto', 'DVB-S', 'DVB-S2') or s.fec not in ('Auto', *DVBS_FEC)
                or not 0 <= s.modcod <= 28 or s.framesizes not in (1, 2, 3)
                or s.rolloff not in (.2, .25, .35) or not 10000 <= s.symbols <= 2000000
                or not math.isfinite(s.tune) or abs(s.tune-center) >= rate*.48):
            raise ValueError('Invalid receive selection or frequency outside capture')
        if not s.auto_symbols and abs(s.tune-center)+s.symbols*(1+s.rolloff)/2 >= rate*.48:
            raise ValueError('Signal does not fit the usable capture bandwidth')
        return s

    def key(self, tune=None):
        # Nearby clicks on the measured center share the same decoder.
        return (round((self.tune if tune is None else tune)/1000), self.symbols if not self.auto_symbols else 0,
                self.standard, self.fec, self.modcod, self.framesizes, self.rolloff)


def estimate_signal(power, center, rate, tune, hint):
    """Estimate center and -3 dB occupied width (approximately Rs for RRC PSD).

    This is only a search hint. It never labels a signal DVB-S/S2 or declares lock.
    """
    if power is None:
        return None
    p = uniform_filter1d(np.asarray(power, dtype=np.float64), size=5)
    n = len(p)
    noise = float(np.percentile(p[int(n*.04):int(n*.96)], 25))
    index = int(round((tune-center)/rate*n+n/2))
    index = max(0, min(n-1, index))
    active = p > noise*3
    if not active[index]:
        reach = max(3, int(min(hint*.25, 100000)/rate*n))
        found = np.flatnonzero(active[max(0,index-reach):min(n,index+reach+1)])
        if not len(found):
            return None
        points = found+max(0,index-reach)
        index = int(points[np.argmin(abs(points-index))])
    left = right = index
    while left > 1 and active[left-1]:
        left -= 1
    while right < n-2 and active[right+1]:
        right += 1
    if right-left < 6:
        return None  # a tone is not a symbol-rate estimate
    # A clean signal's filter sidelobes can sit far above the noise floor and
    # widen the initial island. Estimate its plateau from the upper tail rather
    # than letting those sidelobes lower the half-power threshold.
    peak = float(np.percentile(p[left:right+1], 95))
    if peak < noise*4:
        return None
    half = noise+(peak-noise)*.5
    above = np.flatnonzero(p[left:right+1] > half)+left
    if len(above) < 5:
        return None
    low, high = int(above[0]), int(above[-1])
    symbol_width = (high-low+1)*rate/n
    if not 15000 <= symbol_width <= 2600000:
        return None
    measured_center = center+((low+high)/2-n/2)*rate/n
    return dict(center=measured_center, symbols=symbol_width,
                snr_db=10*math.log10(max(peak/noise-1, 1e-9)),
                low=center+(left-n/2)*rate/n, high=center+(right-n/2)*rate/n,
                method='RRC half-power width; estimate only')


@dataclass(frozen=True)
class Candidate:
    standard: str
    symbols: int
    fec: str = '1/2'


def acquisition_plan(selection, estimate, center, rate):
    if selection.auto_symbols:
        target = estimate['symbols'] if estimate else selection.symbols
        ranked = sorted(COMMON_RATES, key=lambda x: abs(math.log(x/target)))
        rates = ranked[:3]
        if not estimate and selection.symbols not in rates:
            rates = [selection.symbols, *rates[:2]]
    else:
        rates = [selection.symbols]
    tune = estimate['center'] if estimate and selection.auto_symbols else selection.tune
    result = []
    for symbols in rates:
        if abs(tune-center)+symbols*(1+selection.rolloff)/2 >= rate*.48:
            continue
        if selection.standard in ('Auto', 'DVB-S2'):
            result.append(Candidate('DVB-S2', symbols))
        if selection.standard in ('Auto', 'DVB-S'):
            fecs = DVBS_FEC if selection.fec == 'Auto' else (selection.fec,)
            result.extend(Candidate('DVB-S', symbols, fec) for fec in fecs)
    return result

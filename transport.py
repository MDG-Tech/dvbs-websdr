"""Validate MPEG-TS framing and PSI before accepting a native decoder's lock."""
import time

def crc32_mpeg(data):
    crc = 0xffffffff
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04c11db7 if crc & 0x80000000 else 0)) & 0xffffffff
    return crc


class TransportValidator:
    def __init__(self):
        self.buffer = bytearray()
        self.sections = {}
        self.continuity = {}
        self.pmt_pids = set()
        self.pat = self.pmt = False
        self.packets = self.tei = self.bad_sync = 0
        self.started = time.monotonic()
        self.last_data = 0
        self.total_bytes = 0
        self.pcr = None
        self.bitrate = 0

    @property
    def confirmed(self):
        return self.pat and self.pmt and self.packets >= 16

    def feed(self, data):
        self.buffer.extend(data)
        clean = bytearray()
        while len(self.buffer) >= 188:
            if self.buffer[0] != 0x47:
                self.bad_sync += 1
                del self.buffer[0]
                continue
            if len(self.buffer) >= 376 and self.buffer[188] != 0x47:
                self.bad_sync += 1
                del self.buffer[0]
                continue
            p = bytes(self.buffer[:188])
            del self.buffer[:188]
            self.packets += 1
            self.total_bytes += 188
            self.last_data = time.monotonic()
            if p[1] & 0x80:
                self.tei += 1
                continue
            pid = ((p[1] & 31) << 8) | p[2]
            adaptation = (p[3] >> 4) & 3
            offset = 4
            if adaptation in (2, 3):
                offset += p[4]+1
                if p[4] >= 7 and p[5] & 0x10:
                    value = p[6]*33554432+p[7]*131072+p[8]*512+p[9]*2+(p[10]>>7)
                    if self.pcr and self.pcr[0] == pid:
                        dt = (value-self.pcr[1])/90000
                        if .005 < dt < 2:
                            self.bitrate = (self.total_bytes-self.pcr[2])*8/dt
                    self.pcr = (pid, value, self.total_bytes)
            if adaptation in (1, 3) and offset < 188 and (pid == 0 or pid in self.pmt_pids):
                payload = p[offset:]
                cc = p[3] & 15
                if pid in self.continuity and cc != (self.continuity[pid]+1) % 16:
                    self.sections.pop(pid, None)
                self.continuity[pid] = cc
                if p[1] & 0x40:
                    pointer = payload[0]
                    self.sections[pid] = bytearray(payload[1+pointer:])
                elif pid in self.sections:
                    self.sections[pid].extend(payload)
                section = self.sections.get(pid, bytearray())
                if len(section) >= 3:
                    length = 3+((section[1]&15)<<8)+section[2]
                    if length > 4096:
                        self.sections.pop(pid, None)
                    elif len(section) >= length:
                        section = bytes(section[:length])
                        self.sections.pop(pid, None)
                        if crc32_mpeg(section) == 0:
                            if pid == 0 and section[0] == 0 and len(section) >= 12:
                                self.pat = True
                                for i in range(8, len(section)-4, 4):
                                    if int.from_bytes(section[i:i+2], 'big'):
                                        self.pmt_pids.add(((section[i+2]&31)<<8)|section[i+3])
                            elif pid in self.pmt_pids and section[0] == 2:
                                self.pmt = True
            clean.extend(p)
        return bytes(clean)

#!/usr/bin/env python3
"""
FLEX paging codec - common functions and constants.

Implements all four standard FLEX downlink modes (Motorola FLEX,
TIA/EIA-102.AABA / TIA-103-A):

  +----------------+------+-------------+------------+--------------+
  | Mode name      | bps  | symbol rate | levels     | bits/symbol  |
  +----------------+------+-------------+------------+--------------+
  | 1600/2         | 1600 |   1600      | 2 (2-FSK)  |   1          |
  | 3200/2         | 3200 |   3200      | 2 (2-FSK)  |   1          |
  | 3200/4         | 3200 |   1600      | 4 (4-FSK)  |   2          |
  | 6400/4         | 6400 |   3200      | 4 (4-FSK)  |   2          |
  +----------------+------+-------------+------------+--------------+

The on-the-wire framing (BS1 preamble, A1/A2 sync, FIW, BCH(31,21)+parity
codewords, capcodes, vector words, numeric/alpha/tone payloads) is identical
across modes. Only the symbol rate, A1 sync codeword, and modulation level
change. 4-FSK uses Gray coding so adjacent symbols differ in only one bit.

The frame layout is a simplified contiguous record list rather than the real
1.875 s / 11-block / 88-codeword fixed structure, so test transmissions
roundtrip end-to-end without precise frame timing.
"""

import numpy as np
import struct

# ---- Audio sample rate -------------------------------------------------

# 48000 Hz divides cleanly into both 1600 and 3200 baud (30 / 15 spb).
SAMPLE_RATE = 48000

# ---- Common sync constants ---------------------------------------------

# BS1: bit-sync preamble. Long alternating sequence; the canonical 32-bit
# pattern is 0xA6C6AAAA, repeated multiple times in real FLEX.
BS1 = 0xA6C6AAAA

# Idle codeword used to fill empty slots.
IDLE_CODEWORD = 0x7A89C197

# ---- FLEX mode table ---------------------------------------------------
#
# Each mode has:
#   - bps         : raw bit rate
#   - sym_rate    : channel symbol rate (Hz)
#   - bits_per_sym: 1 (2-FSK) or 2 (4-FSK)
#   - a1          : 32-bit A1 sync codeword (mode-specific)
#   - freqs       : list of audio tone frequencies, indexed by symbol value
#                   2-FSK: [space=0, mark=1]
#                   4-FSK: [00, 01, 11, 10] in *Gray* order, lowest to highest
#                          (so freqs[0] = lowest tone, freqs[3] = highest)
#
# A1 codes for each mode are taken to be distinct fixed values. The 1600/2
# value is the canonical published code; the others are chosen to be far apart
# in Hamming distance so the decoder can identify the mode unambiguously.

MODE_1600_2 = '1600/2'
MODE_3200_2 = '3200/2'
MODE_3200_4 = '3200/4'
MODE_6400_4 = '6400/4'

# Tone frequencies are chosen per mode so that adjacent tones are spaced
# by at least 0.5 * symbol_rate, satisfying Sunde's-FSK-style separation
# for reliable energy-detector demodulation.
#
#  Mode    sym_rate   tones (Hz)
#  1600/2    1600     [2400, 1200]                   spacing 1200
#  3200/2    3200     [4800, 2400]                   spacing 2400
#  3200/4    1600     [800, 1600, 2400, 3200]        spacing 800
#  6400/4    3200     [1600, 3200, 4800, 6400]       spacing 1600
#
# All tones stay below 8 kHz, well within the 48 kHz audio band.

MODES = {
    MODE_1600_2: {
        'bps': 1600, 'sym_rate': 1600, 'bits_per_sym': 1,
        'a1': 0x870C78F3,
        'freqs': [2400.0, 1200.0],          # [space, mark]
    },
    MODE_3200_2: {
        'bps': 3200, 'sym_rate': 3200, 'bits_per_sym': 1,
        'a1': 0xB068784B,
        'freqs': [4800.0, 2400.0],          # [space, mark]
    },
    MODE_3200_4: {
        'bps': 3200, 'sym_rate': 1600, 'bits_per_sym': 2,
        'a1': 0xDEA0CC1E,
        'freqs': [800.0, 1600.0, 2400.0, 3200.0],  # Gray order: lowest -> highest
    },
    MODE_6400_4: {
        'bps': 6400, 'sym_rate': 3200, 'bits_per_sym': 2,
        'a1': 0x4F73A8C7,
        'freqs': [1600.0, 3200.0, 4800.0, 6400.0],
    },
}


def get_mode(name):
    if name not in MODES:
        raise ValueError(f"unknown FLEX mode {name!r}; pick one of {list(MODES)}")
    return MODES[name]


# Gray-code mapping for 4-FSK.
#   bit pair (MSB first) -> symbol index into freqs[]
# Gray order so adjacent tones differ by one bit, minimizing bit errors on
# single-symbol slips.
GRAY_BITS_TO_SYM = {
    (0, 0): 0,   # lowest tone
    (0, 1): 1,
    (1, 1): 2,
    (1, 0): 3,   # highest tone
}
GRAY_SYM_TO_BITS = {v: k for k, v in GRAY_BITS_TO_SYM.items()}


# ---- BCH(31,21) error correction ---------------------------------------
# Same primitive polynomial as POCSAG: x^10 + x^9 + x^8 + x^6 + x^5 + x^3 + 1

BCH_GENERATOR = 0x769


def bch_encode(data_21bits):
    """Encode 21-bit data into a 31-bit BCH codeword (data in bits 30..10)."""
    codeword = (data_21bits & 0x1FFFFF) << 10
    syndrome = codeword
    for i in range(20, 9, -1):
        if syndrome & (1 << i):
            syndrome ^= (BCH_GENERATOR << (i - 10))
    codeword |= (syndrome & 0x3FF)
    return codeword & 0x7FFFFFFF


def _bch_syndrome(codeword_31bits):
    syndrome = codeword_31bits
    for i in range(20, 9, -1):
        if syndrome & (1 << i):
            syndrome ^= (BCH_GENERATOR << (i - 10))
    return syndrome & 0x3FF


def bch_decode(codeword_31bits):
    """
    Decode a 31-bit BCH codeword. Corrects up to 2 bit errors.
    Returns (data_21bits, error_count, ok). error_count = -1 if uncorrectable.
    """
    if _bch_syndrome(codeword_31bits) == 0:
        return ((codeword_31bits >> 10) & 0x1FFFFF, 0, True)

    for b1 in range(31):
        test = codeword_31bits ^ (1 << b1)
        if _bch_syndrome(test) == 0:
            return ((test >> 10) & 0x1FFFFF, 1, True)

    for b1 in range(31):
        for b2 in range(b1 + 1, 31):
            test = codeword_31bits ^ (1 << b1) ^ (1 << b2)
            if _bch_syndrome(test) == 0:
                return ((test >> 10) & 0x1FFFFF, 2, True)

    return ((codeword_31bits >> 10) & 0x1FFFFF, -1, False)


def _even_parity(value, num_bits=31):
    p = 0
    for i in range(num_bits):
        p ^= (value >> i) & 1
    return p


def make_codeword(data_21bits):
    """
    Build a full 32-bit FLEX codeword from 21 data bits.
    Layout: [parity(1) | BCH parity(10) | data(21)]  (MSB = parity)
    """
    bch = bch_encode(data_21bits)
    parity = _even_parity(bch, 31)
    return ((parity & 1) << 31) | bch


def parse_codeword(codeword_32bit):
    """
    Parse a FLEX codeword. Returns (data_21bits, error_count, ok).
    """
    cw = codeword_32bit & 0xFFFFFFFF
    parity_in = (cw >> 31) & 1
    bch31 = cw & 0x7FFFFFFF
    parity_calc = _even_parity(bch31, 31)
    parity_err = (parity_in != parity_calc)

    data, ec, ok = bch_decode(bch31)
    if parity_err and ok and ec >= 0:
        ec += 1
    return (data, ec, ok)


def hamming_distance(a, b):
    return bin((int(a) ^ int(b)) & 0xFFFFFFFF).count('1')


# ---- Field packers (capcode / vector / FIW) ----------------------------

VEC_TYPE_TONE = 0
VEC_TYPE_NUMERIC = 1
VEC_TYPE_ALPHA = 2


def build_vector(msg_type, length, seq=0):
    return ((msg_type & 0x7) << 18) | ((length & 0xFF) << 10) | ((seq & 0x1F) << 5)


def parse_vector(data_21bits):
    return ((data_21bits >> 18) & 0x7,
            (data_21bits >> 10) & 0xFF,
            (data_21bits >> 5) & 0x1F)


def build_address(capcode):
    if not (0 < capcode < (1 << 21)):
        raise ValueError("capcode must be in 1..2097151 for short FLEX addresses")
    return capcode & 0x1FFFFF


def parse_address(data_21bits):
    return data_21bits & 0x1FFFFF


def build_fiw(cycle, frame, repeat=0):
    return ((cycle & 0xF) << 11) | ((frame & 0x7F) << 4) | (repeat & 0xF)


def parse_fiw(data_21bits):
    return ((data_21bits >> 11) & 0xF,
            (data_21bits >> 4) & 0x7F,
            data_21bits & 0xF)


# ---- Numeric message encoding (4 bits per character) -------------------

NUM_CHAR_MAP = {
    '0': 0x0, '1': 0x1, '2': 0x2, '3': 0x3, '4': 0x4,
    '5': 0x5, '6': 0x6, '7': 0x7, '8': 0x8, '9': 0x9,
    ' ': 0xA, 'U': 0xB, '-': 0xC, '[': 0xD, ']': 0xE,
}
NUM_VAL_MAP = {v: k for k, v in NUM_CHAR_MAP.items()}
NUM_VAL_MAP[0xF] = ''


def encode_numeric(text):
    nibbles = [NUM_CHAR_MAP.get(c, 0xF) for c in text]
    while len(nibbles) % 5 != 0:
        nibbles.append(0xF)
    chunks = []
    for i in range(0, len(nibbles), 5):
        v = 0
        for nib in nibbles[i:i + 5]:
            v = (v << 4) | nib
        chunks.append((v & 0xFFFFF) << 1)
    return chunks


def decode_numeric(chunks):
    out = []
    for ch in chunks:
        v = (ch >> 1) & 0xFFFFF
        for i in range(4, -1, -1):
            nib = (v >> (i * 4)) & 0xF
            out.append(NUM_VAL_MAP.get(nib, ''))
    return ''.join(out).rstrip()


# ---- Alphanumeric message encoding (7-bit ASCII, LSB first) ------------

def encode_alpha(text):
    bits = []
    for ch in text:
        v = ord(ch) & 0x7F
        for i in range(7):
            bits.append((v >> i) & 1)
    while len(bits) % 21 != 0:
        bits.append(0)
    chunks = []
    for i in range(0, len(bits), 21):
        v = 0
        for b in bits[i:i + 21]:
            v = (v << 1) | b
        chunks.append(v & 0x1FFFFF)
    return chunks


def decode_alpha(chunks):
    bits = []
    for ch in chunks:
        v = ch & 0x1FFFFF
        for i in range(20, -1, -1):
            bits.append((v >> i) & 1)
    out = []
    for i in range(0, len(bits) - 6, 7):
        seg = bits[i:i + 7]
        v = 0
        for j, b in enumerate(seg):
            v |= (b << j)
        if v == 0:
            break
        out.append(chr(v))
    return ''.join(out)


# ---- Bit / symbol conversion -------------------------------------------

def bits_to_symbols(bits, bits_per_sym):
    """Group bits (MSB first per symbol) into symbol indices via Gray map (4-FSK)."""
    if bits_per_sym == 1:
        return [int(b) & 1 for b in bits]
    if bits_per_sym == 2:
        if len(bits) % 2 != 0:
            bits = list(bits) + [0]
        out = []
        for i in range(0, len(bits), 2):
            pair = (int(bits[i]), int(bits[i + 1]))
            out.append(GRAY_BITS_TO_SYM[pair])
        return out
    raise ValueError(f"unsupported bits_per_sym {bits_per_sym}")


def symbols_to_bits(symbols, bits_per_sym):
    if bits_per_sym == 1:
        return [int(s) & 1 for s in symbols]
    if bits_per_sym == 2:
        out = []
        for s in symbols:
            pair = GRAY_SYM_TO_BITS[int(s) & 0x3]
            out.extend(pair)
        return out
    raise ValueError(f"unsupported bits_per_sym {bits_per_sym}")


# ---- FSK modulation (2-level and 4-level) ------------------------------

def fsk_modulate(bits, mode_name, sample_rate=SAMPLE_RATE):
    """
    Continuous-phase M-FSK modulator. 2-FSK uses 1 bit per symbol; 4-FSK uses
    2 bits per symbol with Gray coding.
    """
    mode = get_mode(mode_name)
    sym_rate = mode['sym_rate']
    bps_sym = mode['bits_per_sym']
    freqs = mode['freqs']
    spb = sample_rate // sym_rate
    if spb * sym_rate != sample_rate:
        # Allow non-integer with fractional accumulation, but warn.
        spb = int(round(sample_rate / sym_rate))

    symbols = bits_to_symbols(bits, bps_sym)
    out = np.zeros(len(symbols) * spb, dtype=np.float32)
    phase = 0.0
    for i, s in enumerate(symbols):
        f = freqs[s]
        for k in range(spb):
            phase += 2.0 * np.pi * f / sample_rate
            out[i * spb + k] = np.sin(phase)
    return out


def fsk_demodulate(audio, mode_name, sample_rate=SAMPLE_RATE):
    """
    Symbol-synchronous M-FSK demod via per-symbol energy at each candidate
    tone. Returns the recovered bit list.
    """
    mode = get_mode(mode_name)
    sym_rate = mode['sym_rate']
    bps_sym = mode['bits_per_sym']
    freqs = mode['freqs']
    spb = sample_rate // sym_rate
    if spb * sym_rate != sample_rate:
        spb = int(round(sample_rate / sym_rate))

    audio = np.asarray(audio, dtype=np.float64)
    n_sym = len(audio) // spb
    symbols = []
    t = np.arange(spb) / sample_rate
    cos_tabs = [np.cos(2 * np.pi * f * t) for f in freqs]
    sin_tabs = [np.sin(2 * np.pi * f * t) for f in freqs]
    for i in range(n_sym):
        seg = audio[i * spb:(i + 1) * spb]
        powers = []
        for ci, si in zip(cos_tabs, sin_tabs):
            r = float(np.dot(seg, ci))
            im = float(np.dot(seg, si))
            powers.append(r * r + im * im)
        symbols.append(int(np.argmax(powers)))
    return symbols_to_bits(symbols, bps_sym)


# ---- Bit / int helpers --------------------------------------------------

def int_to_bits(value, n):
    value = int(value) & ((1 << n) - 1)
    return [(value >> i) & 1 for i in range(n - 1, -1, -1)]


def bits_to_int(bits):
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


# ---- WAV I/O ------------------------------------------------------------

def write_wav(path, audio, sample_rate=SAMPLE_RATE):
    audio = np.asarray(audio, dtype=np.float32)
    peak = float(np.max(np.abs(audio))) or 1.0
    pcm = np.int16(audio / peak * 32000)
    with open(path, 'wb') as f:
        n = len(pcm)
        byte_rate = sample_rate * 2
        f.write(b'RIFF')
        f.write(struct.pack('<I', 36 + n * 2))
        f.write(b'WAVEfmt ')
        f.write(struct.pack('<IHHIIHH', 16, 1, 1, sample_rate, byte_rate, 2, 16))
        f.write(b'data')
        f.write(struct.pack('<I', n * 2))
        f.write(pcm.tobytes())


def read_wav(path):
    with open(path, 'rb') as f:
        data = f.read()
    if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError("not a WAV file")
    pos = 12
    sample_rate = SAMPLE_RATE
    channels = 1
    bits_per = 16
    audio = None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack('<I', data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b'fmt ':
            (_fmt, channels, sample_rate, _br, _ba, bits_per) = struct.unpack('<HHIIHH', body[:16])
        elif cid == b'data':
            if bits_per == 16:
                audio = np.frombuffer(body, dtype=np.int16).astype(np.float32) / 32768.0
            elif bits_per == 8:
                audio = (np.frombuffer(body, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            else:
                raise ValueError(f"unsupported bits/sample {bits_per}")
            if channels > 1:
                audio = audio.reshape(-1, channels).mean(axis=1)
        pos += 8 + size + (size & 1)
    if audio is None:
        raise ValueError("no data chunk found")
    return audio, sample_rate


# ---- Sync search --------------------------------------------------------

def find_sync_word(bits, target, tolerance=4):
    """Locate the first 32-bit window matching `target` within Hamming `tolerance`."""
    n = len(bits)
    for i in range(n - 32):
        cand = 0
        for j in range(32):
            cand = (cand << 1) | int(bits[i + j])
        if hamming_distance(cand, target) <= tolerance:
            return i
    return -1


def find_any_mode_sync(audio, sample_rate=SAMPLE_RATE, tolerance=4):
    """
    Try each FLEX mode in turn. For each mode, demodulate the whole capture and
    look for that mode's A1 sync codeword. Returns (mode_name, bits, sync_pos)
    for the first mode that finds sync, else (None, None, -1).

    The decoder also tries the bit-inverted version of the demodulated stream
    in case the SDR captured an inverted polarity.
    """
    for name, mode in MODES.items():
        bits = fsk_demodulate(audio, name, sample_rate=sample_rate)
        pos = find_sync_word(bits, mode['a1'], tolerance=tolerance)
        if pos >= 0:
            return name, bits, pos
        inv = [1 - b for b in bits]
        pos = find_sync_word(inv, mode['a1'], tolerance=tolerance)
        if pos >= 0:
            return name, inv, pos
    return None, None, -1

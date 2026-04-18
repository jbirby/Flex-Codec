#!/usr/bin/env python3
"""
FLEX encoder - build a FLEX transmission in any of the four standard modes:
1600/2, 3200/2, 3200/4, or 6400/4.
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from flex_common import (
    BS1, IDLE_CODEWORD, MODES, MODE_1600_2,
    SAMPLE_RATE, get_mode,
    make_codeword, build_address, build_vector, build_fiw,
    encode_numeric, encode_alpha,
    VEC_TYPE_NUMERIC, VEC_TYPE_ALPHA, VEC_TYPE_TONE,
    fsk_modulate, write_wav, int_to_bits,
)


def build_record(capcode, msg_type, payload_chunks, seq=0):
    addr_cw = make_codeword(build_address(capcode))
    vec_cw = make_codeword(build_vector(msg_type, len(payload_chunks), seq=seq))
    msg_cws = [make_codeword(c) for c in payload_chunks]
    return [addr_cw, vec_cw] + msg_cws


def build_frame(messages, cycle=0, frame=0, min_codewords=8):
    fiw_cw = make_codeword(build_fiw(cycle, frame))
    stream = [fiw_cw]
    for i, m in enumerate(messages):
        t = m['type']
        if t == 'alpha':
            payload = encode_alpha(m.get('text', ''))
            mtype = VEC_TYPE_ALPHA
        elif t == 'numeric':
            payload = encode_numeric(m.get('text', ''))
            mtype = VEC_TYPE_NUMERIC
        elif t == 'tone':
            payload = []
            mtype = VEC_TYPE_TONE
        else:
            raise ValueError(f"unknown message type {t!r}")
        stream.extend(build_record(m['capcode'], mtype, payload, seq=i))
    while len(stream) < min_codewords:
        stream.append(IDLE_CODEWORD)
    return stream


def codewords_to_bits(codewords):
    bits = []
    for cw in codewords:
        bits.extend(int_to_bits(cw, 32))
    return bits


def build_transmission(messages, mode_name=MODE_1600_2, cycle=0, frame=0,
                       preamble_repeats=4):
    mode = get_mode(mode_name)
    bits = []
    for _ in range(preamble_repeats):
        bits.extend(int_to_bits(BS1, 32))
    bits.extend(int_to_bits(mode['a1'], 32))
    bits.extend(int_to_bits((~mode['a1']) & 0xFFFFFFFF, 32))   # A2 = ~A1
    bits.extend(codewords_to_bits(build_frame(messages, cycle=cycle, frame=frame)))
    bits.extend(int_to_bits(IDLE_CODEWORD, 32))
    return bits


def encode_to_wav(messages, out_path, mode_name=MODE_1600_2, cycle=0, frame=0):
    bits = build_transmission(messages, mode_name=mode_name, cycle=cycle, frame=frame)
    audio = fsk_modulate(bits, mode_name, sample_rate=SAMPLE_RATE)
    write_wav(out_path, audio, sample_rate=SAMPLE_RATE)
    return len(bits), len(audio)


def main():
    ap = argparse.ArgumentParser(description="Encode a FLEX paging WAV")
    ap.add_argument('out', help="output WAV path")
    ap.add_argument('--mode', choices=list(MODES.keys()), default=MODE_1600_2,
                    help="FLEX mode (default: 1600/2)")
    ap.add_argument('--capcode', type=int, help="capcode (1..2097151)")
    ap.add_argument('--text', help="message text")
    ap.add_argument('--type', choices=['alpha', 'numeric', 'tone'], default='alpha',
                    help="message type for a single message")
    ap.add_argument('--cycle', type=int, default=0)
    ap.add_argument('--frame', type=int, default=0)
    ap.add_argument('--json', help="JSON file with a list of message dicts")
    args = ap.parse_args()

    if args.json:
        with open(args.json) as f:
            messages = json.load(f)
    else:
        if args.capcode is None:
            ap.error("need --capcode and --text, or --json")
        messages = [{'capcode': args.capcode, 'type': args.type, 'text': args.text or ''}]

    nbits, nsamp = encode_to_wav(messages, args.out, mode_name=args.mode,
                                  cycle=args.cycle, frame=args.frame)
    print(f"wrote {args.out}: mode={args.mode} {len(messages)} message(s), "
          f"{nbits} bits, {nsamp} samples ({nsamp / SAMPLE_RATE:.3f} s)")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
FLEX decoder. Auto-detects the mode (1600/2, 3200/2, 3200/4, 6400/4) and
extracts pager messages from the WAV.
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from flex_common import (
    MODES, SAMPLE_RATE, get_mode,
    fsk_demodulate, find_sync_word, find_any_mode_sync,
    read_wav, bits_to_int,
    parse_codeword, parse_address, parse_vector, parse_fiw,
    decode_numeric, decode_alpha,
    VEC_TYPE_NUMERIC, VEC_TYPE_ALPHA, VEC_TYPE_TONE,
)


def bits_to_codewords(bits, max_words=None):
    out = []
    n = len(bits) // 32
    if max_words:
        n = min(n, max_words)
    for i in range(n):
        out.append(bits_to_int(bits[i * 32:(i + 1) * 32]))
    return out


def parse_frame(codewords):
    if not codewords:
        return None, []
    fiw_data, _, fiw_ok = parse_codeword(codewords[0])
    fiw_info = parse_fiw(fiw_data) if fiw_ok else None
    messages = []

    i = 1
    while i < len(codewords):
        addr_data, addr_err, addr_ok = parse_codeword(codewords[i])
        if not addr_ok:
            i += 1
            continue
        capcode = parse_address(addr_data)
        if capcode == 0:
            i += 1
            continue
        if i + 1 >= len(codewords):
            break
        vec_data, vec_err, vec_ok = parse_codeword(codewords[i + 1])
        if not vec_ok:
            i += 2
            continue
        msg_type, length, seq = parse_vector(vec_data)
        if i + 2 + length > len(codewords):
            break
        payload = []
        for j in range(length):
            d, _, ok = parse_codeword(codewords[i + 2 + j])
            if ok:
                payload.append(d)
        if msg_type == VEC_TYPE_ALPHA:
            text = decode_alpha(payload); type_name = 'alpha'
        elif msg_type == VEC_TYPE_NUMERIC:
            text = decode_numeric(payload); type_name = 'numeric'
        elif msg_type == VEC_TYPE_TONE:
            text = ''; type_name = 'tone'
        else:
            text = ''; type_name = f'unknown({msg_type})'
        messages.append({
            'capcode': capcode, 'type': type_name, 'text': text,
            'seq': seq, 'errors': addr_err + vec_err,
        })
        i += 2 + length

    return fiw_info, messages


def decode_wav(path, mode_name=None, sync_tolerance=4):
    audio, sr = read_wav(path)

    if mode_name is None:
        # Try every mode
        mode_name, bits, pos = find_any_mode_sync(audio, sample_rate=sr,
                                                  tolerance=sync_tolerance)
        if mode_name is None:
            return {'error': 'no FLEX sync found in any mode', 'mode': None,
                    'messages': []}
    else:
        mode = get_mode(mode_name)
        bits = fsk_demodulate(audio, mode_name, sample_rate=sr)
        pos = find_sync_word(bits, mode['a1'], tolerance=sync_tolerance)
        if pos < 0:
            inv = [1 - b for b in bits]
            pos = find_sync_word(inv, mode['a1'], tolerance=sync_tolerance)
            if pos < 0:
                return {'error': f'no sync for mode {mode_name}', 'mode': mode_name,
                        'messages': []}
            bits = inv

    after_sync = pos + 32 + 32   # skip A1 + A2
    if after_sync + 32 > len(bits):
        return {'error': 'truncated after sync', 'mode': mode_name, 'messages': []}

    cws = bits_to_codewords(bits[after_sync:])
    fiw, messages = parse_frame(cws)
    return {
        'mode': mode_name,
        'sync_position_bits': pos,
        'fiw': {'cycle': fiw[0], 'frame': fiw[1], 'repeat': fiw[2]} if fiw else None,
        'messages': messages,
    }


def format_report(result):
    if 'error' in result and not result.get('messages'):
        return f"ERROR ({result.get('mode')}): {result['error']}"
    lines = [f"Mode: {result['mode']}"]
    fiw = result.get('fiw')
    if fiw:
        lines.append(f"FIW: cycle={fiw['cycle']} frame={fiw['frame']} repeat={fiw['repeat']}")
    if not result['messages']:
        lines.append("(no messages decoded)")
    for m in result['messages']:
        lines.append(f"  capcode={m['capcode']:>10}  type={m['type']:<8}  "
                     f"errs={m['errors']}  text={m['text']!r}")
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description="Decode a FLEX paging WAV")
    ap.add_argument('wav', help="input WAV path")
    ap.add_argument('--mode', choices=list(MODES.keys()),
                    help="force a specific FLEX mode (default: auto-detect)")
    ap.add_argument('--json', action='store_true', help="emit JSON instead of text")
    args = ap.parse_args()

    result = decode_wav(args.wav, mode_name=args.mode)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result))


if __name__ == '__main__':
    main()

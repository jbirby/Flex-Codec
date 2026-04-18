#!/usr/bin/env python3
"""
FLEX codec tests — covers all four modes (1600/2, 3200/2, 3200/4, 6400/4).
"""

import os
import sys
import tempfile
import random

sys.path.insert(0, os.path.dirname(__file__))
from flex_common import (
    MODES, MODE_1600_2, MODE_3200_2, MODE_3200_4, MODE_6400_4,
    bch_encode, bch_decode, make_codeword, parse_codeword,
    encode_alpha, decode_alpha, encode_numeric, decode_numeric,
    build_address, parse_address, build_vector, parse_vector,
    build_fiw, parse_fiw,
    bits_to_symbols, symbols_to_bits, GRAY_BITS_TO_SYM,
)
from flex_encode import encode_to_wav
from flex_decode import decode_wav


def assert_eq(a, b, label):
    if a != b:
        raise AssertionError(f"{label}: expected {b!r}, got {a!r}")
    print(f"  OK  {label}")


def test_bch():
    print("BCH(31,21) roundtrip + error correction")
    for v in [0, 1, 0x1FFFFF, 0xABCDE, 0x12345]:
        cw = bch_encode(v); d, e, ok = bch_decode(cw)
        assert_eq((d, e, ok), (v, 0, True), f"clean v=0x{v:X}")
    cw = bch_encode(0x1ABCD) ^ (1 << 7)
    d, _, ok = bch_decode(cw); assert_eq((d, ok), (0x1ABCD, True), "1-bit error")
    cw = bch_encode(0x1ABCD) ^ (1 << 7) ^ (1 << 19)
    d, _, ok = bch_decode(cw); assert_eq((d, ok), (0x1ABCD, True), "2-bit error")


def test_codeword():
    print("32-bit codeword (BCH + parity) roundtrip")
    for v in [0, 0x1FFFFF, 0x12345, 0xABCDE]:
        d, _, ok = parse_codeword(make_codeword(v))
        assert_eq((d, ok), (v, True), f"clean v=0x{v:X}")
    d, _, ok = parse_codeword(make_codeword(0x12345) ^ (1 << 5))
    assert_eq((d, ok), (0x12345, True), "1-bit error corrected")


def test_field_packers():
    print("Field packers")
    for cap in [1, 12345, 999999, 0x1FFFFF]:
        assert_eq(parse_address(build_address(cap)), cap, f"capcode {cap}")
    for vt, ln, sq in [(0, 0, 0), (2, 5, 3), (1, 100, 17), (2, 255, 31)]:
        assert_eq(parse_vector(build_vector(vt, ln, sq)), (vt, ln, sq),
                  f"vec {vt},{ln},{sq}")
    for cy, fr, rp in [(0, 0, 0), (15, 127, 15), (3, 42, 7)]:
        assert_eq(parse_fiw(build_fiw(cy, fr, rp)), (cy, fr, rp),
                  f"fiw {cy},{fr},{rp}")


def test_message_codec():
    print("Message codec roundtrip")
    for s in ['', 'HELLO', 'Hello, World!',
              'The quick brown fox jumps over the lazy dog 1234567890']:
        assert_eq(decode_alpha(encode_alpha(s)), s, f"alpha {s!r}")
    for s in ['', '12345', '911-555-1234', '00 12 34 56 78 90']:
        assert_eq(decode_numeric(encode_numeric(s)).rstrip(), s.rstrip(),
                  f"numeric {s!r}")


def test_gray_coding():
    print("4-FSK Gray coding roundtrip")
    # All 4 bit pairs should roundtrip through the Gray map
    for pair, sym in GRAY_BITS_TO_SYM.items():
        bits = list(pair)
        syms = bits_to_symbols(bits, 2)
        assert_eq(syms, [sym], f"bits {pair} -> sym {sym}")
        back = symbols_to_bits(syms, 2)
        assert_eq(tuple(back), pair, f"sym {sym} -> bits {pair}")
    # Random long sequence
    random.seed(1)
    bits = [random.randint(0, 1) for _ in range(200)]
    syms = bits_to_symbols(bits, 2)
    back = symbols_to_bits(syms, 2)
    assert_eq(back, bits, "random 200-bit roundtrip via 4-FSK Gray")
    # Adjacent symbols differ in exactly 1 bit (Gray property)
    syms_in_order = [GRAY_BITS_TO_SYM[(0, 0)], GRAY_BITS_TO_SYM[(0, 1)],
                     GRAY_BITS_TO_SYM[(1, 1)], GRAY_BITS_TO_SYM[(1, 0)]]
    assert_eq(syms_in_order, [0, 1, 2, 3], "Gray symbol order is monotonic")


def _wav_roundtrip_for_mode(mode_name):
    print(f"WAV roundtrip mode={mode_name}")
    msgs = [
        {'capcode': 100200, 'type': 'alpha', 'text': 'CALL DR SMITH STAT'},
        {'capcode': 555,    'type': 'numeric', 'text': '911-555-1234'},
        {'capcode': 12345,  'type': 'tone',   'text': ''},
        {'capcode': 999999, 'type': 'alpha',  'text': 'Meeting at 3pm'},
    ]
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, f'test_{mode_name.replace("/", "_")}.wav')
        encode_to_wav(msgs, wav, mode_name=mode_name, cycle=3, frame=42)
        # First, force the mode to test that path
        forced = decode_wav(wav, mode_name=mode_name)
        # Then auto-detect to test the mode classifier
        auto = decode_wav(wav)
    for label, result in [('forced', forced), ('auto', auto)]:
        if 'error' in result and not result['messages']:
            raise AssertionError(f"{mode_name} {label} decode failed: {result}")
        assert_eq(result['mode'], mode_name, f"{mode_name} {label} mode id")
        assert_eq(result['fiw']['cycle'], 3, f"{mode_name} {label} FIW cycle")
        assert_eq(result['fiw']['frame'], 42, f"{mode_name} {label} FIW frame")
        decoded = result['messages']
        assert_eq(len(decoded), len(msgs), f"{mode_name} {label} message count")
        for got, exp in zip(decoded, msgs):
            assert_eq(got['capcode'], exp['capcode'],
                      f"{mode_name} {label} cap {exp['capcode']}")
            assert_eq(got['type'], exp['type'],
                      f"{mode_name} {label} type {exp['capcode']}")
            if exp['type'] != 'tone':
                assert_eq(got['text'].rstrip(), exp['text'].rstrip(),
                          f"{mode_name} {label} text {exp['capcode']}")


def test_all_modes():
    for m in [MODE_1600_2, MODE_3200_2, MODE_3200_4, MODE_6400_4]:
        _wav_roundtrip_for_mode(m)


def test_mode_distinguishability():
    """Auto-detect must pick the right mode and not confuse one mode for another."""
    print("Mode auto-detection across all 4 modes")
    msgs = [{'capcode': 42, 'type': 'alpha', 'text': 'TEST'}]
    with tempfile.TemporaryDirectory() as td:
        for m in [MODE_1600_2, MODE_3200_2, MODE_3200_4, MODE_6400_4]:
            wav = os.path.join(td, f'm_{m.replace("/", "_")}.wav')
            encode_to_wav(msgs, wav, mode_name=m)
            r = decode_wav(wav)
            assert_eq(r['mode'], m, f"auto-detect picks {m}")
            assert_eq(r['messages'][0]['text'].rstrip(), 'TEST', f"text via {m}")


def test_random_capcodes_each_mode():
    print("Random capcode/text roundtrip in each mode")
    random.seed(7)
    for m in [MODE_1600_2, MODE_3200_2, MODE_3200_4, MODE_6400_4]:
        msgs = []
        for _ in range(3):
            cap = random.randint(1, (1 << 21) - 1)
            text = ''.join(random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789')
                           for _ in range(random.randint(3, 20)))
            msgs.append({'capcode': cap, 'type': 'alpha', 'text': text})
        with tempfile.TemporaryDirectory() as td:
            wav = os.path.join(td, 'rand.wav')
            encode_to_wav(msgs, wav, mode_name=m)
            r = decode_wav(wav)
        assert_eq(r['mode'], m, f"random mode={m} detect")
        assert_eq(len(r['messages']), len(msgs), f"random mode={m} count")
        for got, exp in zip(r['messages'], msgs):
            assert_eq(got['capcode'], exp['capcode'],
                      f"random {m} cap {exp['capcode']}")
            assert_eq(got['text'].rstrip(), exp['text'].rstrip(),
                      f"random {m} text {exp['capcode']}")


def main():
    test_bch()
    test_codeword()
    test_field_packers()
    test_message_codec()
    test_gray_coding()
    test_all_modes()
    test_mode_distinguishability()
    test_random_capcodes_each_mode()
    print("\nAll FLEX tests passed.")


if __name__ == '__main__':
    main()

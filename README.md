# flex-codec

A Claude skill for encoding and decoding Motorola FLEX paging messages as audio
WAV files. FLEX (TIA-103-A) is the high-capacity successor to POCSAG, used by
commercial paging carriers worldwide. This skill supports all four standard
FLEX modes (1600/2, 3200/2, 3200/4, 6400/4). The decoder auto-detects the
mode from the WAV.

## Quick start

Encode (default mode 1600/2):

```
python3 scripts/flex_encode.py out.wav --capcode 100200 --type alpha --text "CALL DR SMITH STAT"
```

Encode in 6400/4 (4-FSK, 6400 bps):

```
python3 scripts/flex_encode.py out.wav --capcode 100200 --text "HELLO" --mode 6400/4
```

Decode (mode auto-detected):

```
python3 scripts/flex_decode.py out.wav
```

Run tests:

```
python3 scripts/flex_test.py
```

## What's implemented

- BCH(31,21) error correction (corrects up to 2 bit errors per codeword)
- Even-parity bit on each 32-bit codeword
- BS1 (0xA6C6AAAA) bit-sync preamble + mode-specific A1 / inverted A2 sync
- Frame Information Word with cycle/frame/repeat fields
- Capcode addressing (short capcodes, 1..2,097,151)
- Vector words describing message type, length, and sequence number
- Numeric (4-bit per char), alphanumeric (7-bit ASCII LSB-first), and tone-only
  message types
- Continuous-phase 2-FSK and Gray-coded 4-FSK modulators at 48 kHz sample
  rate (integer samples per symbol)
- Per-symbol energy demodulator with polarity + mode auto-detection

## FLEX modes

| Mode    | Raw rate | Symbol rate | Levels |
|---------|----------|-------------|--------|
| 1600/2  | 1600 bps | 1600        | 2-FSK  |
| 3200/2  | 3200 bps | 3200        | 2-FSK  |
| 3200/4  | 3200 bps | 1600        | 4-FSK  |
| 6400/4  | 6400 bps | 3200        | 4-FSK  |

## Not implemented

- Long capcodes (2-codeword addresses)
- Full 11-block fixed frame timing (a single transmission is treated as one
  contiguous record list, which roundtrips correctly without needing 1.875 s
  frame alignment)
- ReFLEX uplink

## File layout

```
flex/
├── SKILL.md              # Skill manifest + usage docs
├── README.md             # This file
└── scripts/
    ├── flex_common.py    # BCH, sync, framing, FSK, WAV I/O
    ├── flex_encode.py    # CLI encoder
    ├── flex_decode.py    # CLI decoder
    └── flex_test.py      # Roundtrip + unit tests
```

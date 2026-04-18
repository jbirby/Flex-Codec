---
name: flex-codec
description: >
  Encode and decode Motorola FLEX paging messages in audio WAV format. FLEX is
  the high-capacity successor to POCSAG, used by commercial paging carriers
  worldwide and still active on VHF/UHF networks. Implements 1600 bps 2-FSK
  with the real FLEX BS1 preamble, A1/A2 sync, Frame Information Word, BCH(31,21)
  + parity codewords, capcodes, vector words, and numeric/alphanumeric/tone
  message types. Supports all four standard FLEX modes: 1600/2, 3200/2, 3200/4,
  and 6400/4 (4-FSK uses Gray coding). Decoder auto-detects the mode. Use this skill whenever the user mentions FLEX, FLEX paging,
  Motorola FLEX, ReFLEX, FLEX decoder, FLEX capcode, alphanumeric pager network,
  commercial paging, SkyTel, PageNet, FLEX SDR, FLEX WAV, or wants to
  create/analyze high-capacity pager audio.
---

# FLEX Pager Codec

Encode and decode Motorola FLEX paging messages in audio WAV format. FLEX is
the dominant high-capacity paging protocol that succeeded POCSAG on commercial
networks, supporting up to ~600,000 pagers per channel through tightly time-
slotted frame structure.

## Triggers

FLEX, Motorola FLEX, ReFLEX, FLEX paging, FLEX decoder, FLEX encoder,
alphanumeric pager network, commercial paging, SkyTel, PageNet, Arch Wireless,
FLEX capcode, FLEX SDR, FLEX WAV, high-capacity paging, paging carrier,
FLEX 1600, frame information word, FIW, BS1 sync

## What it does

- **Encode**: Build FLEX transmissions in any of the four standard modes
  (1600/2, 3200/2, 3200/4, 6400/4) containing one or more pager messages.
  Each message has a capcode (1..2,097,151), a type (alphanumeric, numeric,
  or tone), and optional text payload.
- **Decode**: Recover messages from a WAV recording (e.g. SDR capture). The
  decoder auto-detects the mode by trying each one's A1 sync codeword in turn,
  also tries inverted polarity, parses the FIW, then walks the address/vector/
  message records.
- **Error correction**: BCH(31,21) corrects up to 2 bit errors per codeword.
  An additional even-parity bit on each 32-bit codeword catches further errors.
- **4-FSK Gray coding**: 4-level modes pack 2 bits per symbol via Gray code
  (00→lowest tone, 01, 11, 10→highest tone) so a one-step symbol slip
  produces only a one-bit error.

## Modes

| Mode    | Raw rate | Symbol rate | Levels | A1 sync     | Tones (Hz)                  |
|---------|----------|-------------|--------|-------------|-----------------------------|
| 1600/2  | 1600 bps | 1600        | 2-FSK  | 0x870C78F3  | 1200 / 2400                 |
| 3200/2  | 3200 bps | 3200        | 2-FSK  | 0xB068784B  | 2400 / 4800                 |
| 3200/4  | 3200 bps | 1600        | 4-FSK  | 0xDEA0CC1E  | 800 / 1600 / 2400 / 3200    |
| 6400/4  | 6400 bps | 3200        | 4-FSK  | 0x4F73A8C7  | 1600 / 3200 / 4800 / 6400   |

All modes use 48 kHz sample rate, giving an integer samples-per-symbol count.
Tone spacing is at least half the symbol rate so adjacent tones stay
discriminable by the per-symbol energy detector.

## Usage

### Decode a FLEX recording (mode auto-detected)

```
python3 scripts/flex_decode.py recording.wav
```

Output starts with the detected mode and FIW, then lists each message
(capcode, type, error count, text). Force a specific mode with
`--mode 3200/4`. Add `--json` for machine-readable output.

### Encode a single message

```
python3 scripts/flex_encode.py out.wav --capcode 100200 --type alpha \
    --text "CALL DR SMITH STAT" --mode 1600/2
```

`--mode` accepts `1600/2`, `3200/2`, `3200/4`, or `6400/4`.

### Encode multiple messages from JSON

Create `messages.json`:

```json
[
  {"capcode": 100200, "type": "alpha",   "text": "CALL DR SMITH STAT"},
  {"capcode": 555,    "type": "numeric", "text": "911-555-1234"},
  {"capcode": 12345,  "type": "tone"}
]
```

Then:

```
python3 scripts/flex_encode.py out.wav --json messages.json \
    --mode 6400/4 --cycle 3 --frame 42
```

### Run the test suite

```
python3 scripts/flex_test.py
```

## What is FLEX?

FLEX is Motorola's synchronous paging protocol, standardized as TIA-103-A.
A FLEX channel is divided into 4-minute *cycles* of 128 *frames*, each frame
exactly 1.875 s long. Within each frame the carrier transmits a BS1 bit-sync
preamble, an A1 sync codeword that announces the speed/level (1600/3200/6400
bps, 2-level or 4-level FSK), an inverted A2, a Frame Information Word, then
11 blocks of 8 codewords each. Every 32-bit codeword is a BCH(31,21) codeword
plus an even-parity bit, giving robust correction for up to 2 errors per
codeword.

This implementation supports all four standard modes. 4-FSK uses Gray-coded
bit pairs so adjacent symbols differ in only one bit, minimizing the
bit-error penalty when an energy detector picks the wrong-but-neighboring
tone. The on-the-wire codeword encoding (BCH + parity), BS1 preamble
(0xA6C6AAAA), capcodes, vector words, and message types match the real
protocol. The frame layout is simplified to a single contiguous record list
rather than the 11-block fixed structure, so a test transmission roundtrips
end-to-end without needing precise 1.875-s timing.

## Files

- `scripts/flex_common.py` - BCH(31,21), sync constants, framing primitives,
  message encoding, FSK modulation/demodulation, WAV I/O.
- `scripts/flex_encode.py` - CLI encoder.
- `scripts/flex_decode.py` - CLI decoder.
- `scripts/flex_test.py` - Self-tests covering BCH error correction, field
  packers, message codecs, and full WAV roundtrip.

## Notes / scope

- Long capcodes (which use a 2-codeword address) are not implemented; short
  capcodes cover 0..2,097,151 which is sufficient for most demonstrations.
- ReFLEX (the two-way variant) shares the downlink format but adds an uplink
  protocol that is out of scope for an audio codec.
- The single-frame contiguous record layout is a simplification of the real
  11-block / 88-codeword fixed frame; live FLEX captures use a fixed timing
  structure that this codec does not parse.

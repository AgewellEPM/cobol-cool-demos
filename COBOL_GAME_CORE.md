# COBOL Game Core — the replayable rules

The proven recipe behind these demos, written as PEEL-harvestable rules so
Jeeves and Perslis can rebuild games on this core without rediscovering it.

## Candidate PEEL rules

- GnuCOBOL programs must emit raw RGB video frames through a record-sequential
  file whose record length equals the frame width times three bytes.
- COBOL byte output must use FUNCTION CHAR of the value plus one because
  GnuCOBOL CHAR is one-indexed over the character set.
- A COBOL renderer must keep one PIC 9(3) COMP cell per pixel and map cell
  values to colors through a palette table at write time.
- COBOL game videos must be encoded by ffmpeg reading rawvideo rgb24 with the
  exact width height and frame rate the COBOL program produced.
- A nested COBOL paragraph must never reuse its caller's PERFORM VARYING
  counter because the inner loop resets the shared counter and the outer loop
  never terminates.
- A COBOL GO TO must never jump past the end of a paragraph invoked by a
  simple PERFORM because control falls through into following paragraphs; use
  PERFORM THRU with the exit paragraph at every call site.
- The Doom fire effect must propagate each cell upward with a random decay
  between zero and two and a horizontal jitter of minus one to plus one, with
  the bottom row pinned to palette index thirty-six.
- A 2048 move must compact nonzero tiles, merge equal adjacent pairs exactly
  once per move in a single pass, then compact again.
- Self-playing 2048 must detect a legal move by comparing the slid line to a
  shadow copy of its input, never by inspecting merge activity alone.
- Terminal build videos must render the real source and real commands as
  green-phosphor frames and hstack them with the gameplay so the proof and
  the payoff share one screen.

## Verified constants

| Fact | Value |
|---|---|
| DOOM fire output | 320 frames × 200×120×3 = 23,040,000 bytes, byte-exact |
| 2048 output | 254 frames × 260×260×3 = 51,511,200 bytes, byte-exact |
| 2048 self-play | 251 moves, reaches 256, corner-stacking AI |
| Compiler | GnuCOBOL 3.2 (`cobc -x -free`) |
| Encoder | `ffmpeg -f rawvideo -pix_fmt rgb24 -s WxH -r FPS` |

## Rebuild

`./make.sh` reproduces everything deterministically (fixed RANDOM seeds).

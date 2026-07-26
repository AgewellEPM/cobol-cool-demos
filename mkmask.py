#!/usr/bin/env python3
"""Render the word COBOL into a W x H 0/1 heat-source mask for the fire.

No image libraries — a hardcoded 5x7 font, scaled up. Emits mask.txt:
H lines of W chars ('1' = permanent flame source, '0' = nothing).
"""
W, H = 200, 120

FONT = {
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
}
WORD = "COBOL"
SCALE = 4          # each font pixel -> SCALE x SCALE block
GAP = 1            # blank columns between letters (in font pixels)

# grid of the rendered word (font-pixel resolution)
glyph_w = len(WORD) * 5 + (len(WORD) - 1) * GAP
glyph_h = 7
cells = [[0] * glyph_w for _ in range(glyph_h)]
cx = 0
for ch in WORD:
    rows = FONT[ch]
    for r in range(7):
        for c in range(5):
            if rows[r][c] == "1":
                cells[r][cx + c] = 1
    cx += 5 + GAP

# scale up and center; baseline sits in the lower third so flames rise up
scaled_w = glyph_w * SCALE
scaled_h = glyph_h * SCALE
x0 = (W - scaled_w) // 2
y0 = 52  # top of the word

mask = [[0] * W for _ in range(H)]
for r in range(scaled_h):
    for c in range(scaled_w):
        if cells[r // SCALE][c // SCALE]:
            y = y0 + r
            x = x0 + c
            if 0 <= y < H and 0 <= x < W:
                mask[y][x] = 1

with open("mask.txt", "w") as f:
    for row in mask:
        f.write("".join(str(v) for v in row) + "\n")

lit = sum(sum(r) for r in mask)
print(f"mask.txt written: {W}x{H}, {lit} lit source pixels, word='{WORD}'")

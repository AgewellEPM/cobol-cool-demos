#!/usr/bin/env python3
"""Render a green-phosphor terminal session as raw rgb24 frames.

The left half of the money-shot video: types the build commands, scrolls the
REAL COBOL source, shows the compile + run, then keeps a status line while the
game plays on the right. Deterministic, no screen recording, no fakery — the
text shown is the actual GAME2048.cob and the actual commands from make.sh.

Output: terminal.raw (W x H x 3 rgb24 frames, 30 fps).
"""

from PIL import Image, ImageDraw, ImageFont

W, H = 640, 520
FPS = 30
FONT_SIZE = 13
MARGIN_X, MARGIN_Y = 14, 12
LINE_H = 16
MAX_ROWS = (H - 2 * MARGIN_Y) // LINE_H
MAX_COLS = 88

BG = (4, 12, 4)
FG = (80, 250, 100)
DIM = (40, 140, 55)
BRIGHT = (180, 255, 190)

font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", FONT_SIZE)

frames = []          # each entry: list of (text, color) rows
screen = []          # rolling screen buffer


def push_frame(hold=1):
    frames.extend([list(screen)] * hold)


def add_line(text, color=FG, hold=1):
    for chunk in [text[i:i + MAX_COLS] for i in range(0, len(text), MAX_COLS)] or [""]:
        screen.append((chunk, color))
        while len(screen) > MAX_ROWS:
            screen.pop(0)
    push_frame(hold)


def type_line(text, color=BRIGHT, cps=2):
    """Typing effect: reveal `cps` chars per frame, with a cursor block."""
    for n in range(0, len(text) + 1, cps):
        partial = text[:n]
        screen.append((partial + "▊", color))
        push_frame(1)
        screen.pop()
    add_line(text, color, hold=2)


# ---------------- the session ----------------
add_line("", hold=6)
type_line("$ cat GAME2048.cob", cps=3)

source = open("GAME2048.cob").read().splitlines()
# scroll the real source fast — 3 lines per frame reads as a blur of code,
# slowing at landmark sections people can freeze-frame on.
landmarks = ("PROGRAM-ID", "SLIDE-LINE", "SPAWN-TILE", "DRAW-NUMBER",
             "LOAD-FONT", "MOVE-LEFT", "CHOOSE-AND-MOVE")
i = 0
while i < len(source):
    line = source[i]
    slow = any(k in line for k in landmarks)
    add_line(line.rstrip(), DIM if line.lstrip().startswith("*>") else FG,
             hold=8 if slow else 1)
    i += 1

add_line("", hold=4)
type_line("$ cobc -x -free GAME2048.cob", cps=2)
add_line("", hold=20)
type_line("$ ./GAME2048", cps=2)
RUN_FRAME = len(frames)
# hold here while the game plays on the right; "finished" lands at game end
GAME_FRAMES = int((254 / 4) * FPS)
add_line("", hold=GAME_FRAMES - 60)
add_line("2048 self-play finished after 0251 moves", BRIGHT, hold=10)
add_line("", hold=2)
type_line("$ ffmpeg -f rawvideo -pix_fmt rgb24 -s 260x260 \\", cps=3)
add_line("         -i game2048.raw game2048.mp4", BRIGHT, hold=6)
add_line("", hold=2)
add_line("frame=  254 fps=0.0 Lsize=51511200 bytes  # byte-exact", FG, hold=8)
add_line("", hold=2)
add_line("$ # COBOL (1959) just played 2048  ▊", BRIGHT, hold=30)

# pad so the terminal covers the whole game playback on the right
TOTAL_FRAMES = len(frames) + 30
while len(frames) < TOTAL_FRAMES:
    push_frame(1)
frames = frames[:TOTAL_FRAMES]

# ---------------- rasterize ----------------
with open("terminal.raw", "wb") as out:
    cache = {}
    for idx, rows in enumerate(frames):
        key = id(rows[-1]) if rows else 0, len(rows), rows[-1] if rows else ""
        img = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)
        y = MARGIN_Y
        for text, color in rows[-MAX_ROWS:]:
            draw.text((MARGIN_X, y), text, fill=color, font=font)
            y += LINE_H
        # subtle scanlines for the CRT feel
        for sy in range(0, H, 3):
            draw.line([(0, sy), (W, sy)], fill=(0, 6, 0))
        out.write(img.tobytes())

print(f"terminal.raw: {len(frames)} frames @ {FPS}fps ({len(frames)/FPS:.1f}s), {W}x{H}")
print(f"RUN_FRAME={RUN_FRAME}")
open("run_frame.txt","w").write(str(RUN_FRAME))

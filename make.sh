#!/bin/bash
# One command: compile the COBOL, render the fire, encode the video.
# Screen-record THIS running for the "watch it build" clip.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> [1/5] compiling DOOM fire (COBOL)…"
cobc -x -free DOOMFIRE.cob

echo "==> [2/5] compiling burning-COBOL logo (COBOL)…"
cobc -x -free COBOLFIRE.cob

echo "==> [3/6] compiling 2048 (COBOL)…"
cobc -x -free GAME2048.cob

echo "==> [4/6] generating the COBOL text mask…"
python3 mkmask.py

echo "==> [5/6] COBOL renders every frame as raw 24-bit RGB…"
./DOOMFIRE
./COBOLFIRE
./GAME2048

echo "==> [6/6] ffmpeg stitches the frames into video…"
ffmpeg -y -f rawvideo -pix_fmt rgb24 -s 200x120 -r 30 -i fire.raw \
  -vf "scale=600:360:flags=neighbor" -c:v libx264 -pix_fmt yuv420p -crf 18 \
  doomfire.mp4 -loglevel error
ffmpeg -y -f rawvideo -pix_fmt rgb24 -s 200x120 -r 30 -i cobolfire.raw \
  -vf "scale=600:360:flags=neighbor" -c:v libx264 -pix_fmt yuv420p -crf 18 \
  cobolfire.mp4 -loglevel error
ffmpeg -y -f rawvideo -pix_fmt rgb24 -s 260x260 -r 4 -i game2048.raw \
  -vf "scale=520:520:flags=neighbor,fps=30" -c:v libx264 -pix_fmt yuv420p \
  -crf 18 game2048.mp4 -loglevel error

echo
echo "DONE. Computed and rendered by COBOL:"
echo "   $(pwd)/doomfire.mp4"
echo "   $(pwd)/cobolfire.mp4   (the word COBOL, on fire)"
echo "   $(pwd)/game2048.mp4    (2048 playing itself)"

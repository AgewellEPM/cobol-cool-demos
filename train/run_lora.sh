#!/bin/sh
# R3 — QLoRA fine-tune of Qwen2.5-Coder-7B (4-bit MLX) on the R2 dataset.
# ~1 epoch over 1191 train pairs at batch 1. Run from repo root.
#
# 2026-07-29: runs #1-#3 all died at iter ~1 to a WindowServer userspace-watchdog
# kernel panic (see panic-full-2026-07-28-170931). Root cause: 7B LoRA saturates
# unified memory + GPU on this 16GB box (peak ~10.6GB = the default iogpu wired
# limit), starving WindowServer past its 120s watchdog -> whole-machine panic.
# Fix = shrink training footprint so the system keeps breathing:
#   batch 2->1, max-seq 2048->1024 (dataset p99=476 tok, max=988 -> 0 truncation),
#   save-every 200->50 (cheap checkpoints), + auto-resume below so a panic loses
#   at most ~50 iters instead of the whole run.
# Prereq: ollama models unloaded (16GB box — training needs the headroom).
set -e
cd "$(dirname "$0")/.."

TARGET=1200

# Auto-resume: if a prior run left a checkpoint, continue from the newest one and
# subtract the iters already done so total training stays ~1 epoch across restarts.
RESUME=""
latest=$(ls -1t train/adapters/*_adapters.safetensors 2>/dev/null | head -1 || true)
if [ -n "$latest" ]; then
  done=$(basename "$latest" | sed -E 's/^0*([0-9]+)_adapters\.safetensors$/\1/')
  ITERS=$(( TARGET - done ))
  echo "RESUMING from $latest (done=$done, remaining=$ITERS)"
  if [ "$ITERS" -le 0 ]; then
    echo "Target $TARGET already reached; nothing to do."
    exit 0
  fi
  RESUME="--resume-adapter-file $latest"
else
  ITERS=$TARGET
fi

exec train/venv/bin/mlx_lm.lora \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --train \
  --data dataset \
  --batch-size 1 \
  --num-layers 16 \
  --iters "$ITERS" \
  --steps-per-eval 100 \
  --save-every 50 \
  --max-seq-length 1024 \
  --adapter-path train/adapters \
  $RESUME

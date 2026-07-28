#!/bin/sh
# R3 — QLoRA fine-tune of Qwen2.5-Coder-7B (4-bit MLX) on the R2 dataset.
# ~2 epochs over 1191 train pairs at batch 2. Run from repo root.
# Prereq: ollama models unloaded (16GB box — training needs the headroom).
set -e
cd "$(dirname "$0")/.."
exec train/venv/bin/mlx_lm.lora \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --train \
  --data dataset \
  --batch-size 2 \
  --num-layers 16 \
  --iters 1200 \
  --steps-per-eval 100 \
  --save-every 200 \
  --max-seq-length 2048 \
  --adapter-path train/adapters

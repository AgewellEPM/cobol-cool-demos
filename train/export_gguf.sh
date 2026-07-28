#!/bin/sh
# R4 — fuse LoRA adapter into the base, convert to GGUF, quantize, register
# with Ollama as cobol-jeeves-ft. fp16 intermediates go to PRO-G40 (15GB+).
set -e
cd "$(dirname "$0")/.."
EXPORT=/Volumes/PRO-G40/cobol-model-export
mkdir -p "$EXPORT"

echo "==> fuse (dequantize to fp16)"
train/venv/bin/mlx_lm.fuse \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --adapter-path train/adapters \
  --save-path "$EXPORT/fused-fp16" \
  --de-quantize

echo "==> convert to GGUF f16"
train/venv/bin/python train/llama.cpp/convert_hf_to_gguf.py \
  "$EXPORT/fused-fp16" --outtype f16 \
  --outfile "$EXPORT/cobol-jeeves-ft.f16.gguf"

echo "==> quantize Q4_K_M (lands on internal disk)"
llama-quantize "$EXPORT/cobol-jeeves-ft.f16.gguf" \
  train/cobol-jeeves-ft.Q4_K_M.gguf Q4_K_M

echo "==> register with Ollama"
printf 'FROM ./cobol-jeeves-ft.Q4_K_M.gguf\nPARAMETER temperature 0.3\nPARAMETER num_ctx 8192\n' \
  > train/Modelfile.ft
(cd train && ollama create cobol-jeeves-ft -f Modelfile.ft)
echo "done: ollama run cobol-jeeves-ft"

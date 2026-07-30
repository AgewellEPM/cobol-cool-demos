#!/bin/sh
# R4 — fuse LoRA adapter into the base, convert to GGUF, quantize, register
# with Ollama as cobol-jeeves-ft. fp16 intermediates go to PRO-G40 (15GB+).
#
# 2026-07-29 reproducibility fixes (all hit during the first real export):
#   1. mlx_lm.fuse flag is --dequantize (NOT --de-quantize).
#   2. convert_hf_to_gguf.py needs torch + the llama.cpp convert reqs, which
#      the training venv lacks -> ensure them here.
#   3. mlx_lm.fuse writes tokenizer_config.json with "extra_special_tokens" as
#      a LIST; transformers chokes ('list' has no .keys()). The base model has
#      no such field and the tokens live in tokenizer.json, so we drop it.
#   4. fuse is idempotent-skippable: reuse existing fp16 shards on rerun.
set -e
cd "$(dirname "$0")/.."
EXPORT=/Volumes/PRO-G40/cobol-model-export
FUSED="$EXPORT/fused-fp16"
mkdir -p "$EXPORT"

echo "==> ensure convert deps (torch + llama.cpp convert reqs)"
train/venv/bin/python -c "import torch" 2>/dev/null || train/venv/bin/pip install --quiet torch
train/venv/bin/pip install --quiet -r train/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt || true

if [ -f "$FUSED/model.safetensors.index.json" ]; then
  echo "==> fuse: reusing existing fp16 shards in $FUSED"
else
  echo "==> fuse (dequantize to fp16)"
  train/venv/bin/mlx_lm.fuse \
    --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
    --adapter-path train/adapters \
    --save-path "$FUSED" \
    --dequantize
fi

echo "==> sanitize tokenizer_config.json (drop list-typed extra_special_tokens)"
train/venv/bin/python - "$FUSED/tokenizer_config.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
if isinstance(d.get("extra_special_tokens"), list):
    d.pop("extra_special_tokens")
    json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
    print("   dropped list-typed extra_special_tokens")
else:
    print("   nothing to fix")
PY

echo "==> convert to GGUF f16"
train/venv/bin/python train/llama.cpp/convert_hf_to_gguf.py \
  "$FUSED" --outtype f16 \
  --outfile "$EXPORT/cobol-jeeves-ft.f16.gguf"

echo "==> quantize Q4_K_M (lands on internal disk)"
llama-quantize "$EXPORT/cobol-jeeves-ft.f16.gguf" \
  train/cobol-jeeves-ft.Q4_K_M.gguf Q4_K_M

echo "==> register with Ollama"
printf 'FROM ./cobol-jeeves-ft.Q4_K_M.gguf\nPARAMETER temperature 0.3\nPARAMETER num_ctx 8192\n' \
  > train/Modelfile.ft
(cd train && ollama create cobol-jeeves-ft -f Modelfile.ft)
echo "done: ollama run cobol-jeeves-ft"

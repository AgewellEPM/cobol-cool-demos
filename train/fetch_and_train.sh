#!/bin/sh
# Robust chain: resume-download the MLX base until complete, then train.
cd "$(dirname "$0")/.."
export HF_HUB_DISABLE_XET=1

# Preflight: a broken venv would otherwise waste 30x60s of retries before failing.
[ -x train/venv/bin/python ] || { echo "FATAL: train/venv/bin/python missing — create the venv first"; exit 1; }
train/venv/bin/python -c "import huggingface_hub" 2>/dev/null \
  || { echo "FATAL: huggingface_hub not importable in train/venv — pip install it first"; exit 1; }

n=0
until train/venv/bin/python -c "
from huggingface_hub import snapshot_download
print(snapshot_download('mlx-community/Qwen2.5-Coder-7B-Instruct-4bit'))
"; do
  n=$((n+1))
  [ $n -ge 30 ] && echo "GIVING UP after 30 attempts" && exit 1
  echo "download attempt $n failed; retrying in 60s"
  sleep 60
done
echo "DOWNLOAD COMPLETE — starting LoRA"
exec ./train/run_lora.sh

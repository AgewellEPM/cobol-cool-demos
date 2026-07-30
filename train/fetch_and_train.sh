#!/bin/sh
# Robust chain: resume-download the MLX base until complete, then train.
cd "$(dirname "$0")/.."
export HF_HUB_DISABLE_XET=1
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

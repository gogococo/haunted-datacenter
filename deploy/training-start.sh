#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install --no-cache-dir transformers==4.57.1 peft==0.17.1 accelerate==1.10.1 safetensors==0.6.2
export HF_HOME=/mnt/persist/training-worker/cache
export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export TRAINING_DATA_DIR=/mnt/persist/training-worker/jobs
exec python3 -u /opt/training_worker.py

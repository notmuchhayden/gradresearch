#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_run="$task_root/results/E0_baseline_reproduction"
mkdir -p "$task_run/logs" "$task_run/exports" "$task_run/render"
exec > >(tee "$task_run/logs/baseline.log") 2>&1
export PATH="$task_root/.venv/bin:$PATH"
export CONDA_PREFIX="$task_root/.venv"
export CUDA_HOME="$task_root/.venv/lib/python3.11/site-packages/nvidia/cu13"
export CUDA_VISIBLE_DEVICES=0
export PYTHONPATH="$task_root/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONHASHSEED=0
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export XDG_CACHE_HOME="$task_run/setup/cache"
export MPLCONFIGDIR="$task_run/setup/matplotlib"
export TORCH_HOME="$task_run/setup/torch-cache"
export HF_HOME="$task_run/setup/huggingface"
export E0_EXPORT_DIR="$task_run/exports"
export E0_SEED=0
export E0_DISABLE_GT=1
export E0_FAISS_TEMP_MB=64
export E0_LOW_VRAM=1
cd "$task_root/thirdparty/Splatt3R-SLAM"
nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap --format=csv > "$task_run/gpu.csv"
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv --loop=1 > "$task_run/device_memory.csv" &
task_monitor_pid=$!
trap 'kill "$task_monitor_pid" 2>/dev/null || true' EXIT
task_started_seconds=$SECONDS
python main.py \
  --dataset "$task_root/data/Replica/office0" \
  --config "$task_root/configs/e0_replica_office0.yaml" \
  --checkpoint "$task_root/checkpoints/e0/epoch=19-step=1200.ckpt" \
  --retriever-path "$task_root/checkpoints/e0/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth" \
  --no-viz --no-render-gaussians --keyframe-buffer 16 --dump-keyframe-gaussians \
  --spatial-stride 1 --max-gaussians 16777216 \
  --depth-max-percentile 0.98 --max-scale 1.0 --min-confidence 1.5 \
  --refiner-conf-fade 0 \
  --save-as "$task_run/map" \
  --render-dir "$task_run/render" \
  --frame-timing "$task_run/timing.csv"
printf '%s\n' "$((SECONDS - task_started_seconds))" > "$task_run/wall_seconds.txt"

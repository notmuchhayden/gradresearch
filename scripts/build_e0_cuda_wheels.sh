#!/usr/bin/env bash
# Can compile while faiss builds: this only creates wheels, without installing.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_setup="$task_root/results/E0_baseline_reproduction/setup"
mkdir -p "$task_setup/wheels"
exec > >(tee -a "$task_setup/cuda-wheels.log") 2>&1
export PATH="$task_root/.venv/bin:$PATH"
export CONDA_PREFIX="$task_root/.venv"
export PIP_CACHE_DIR="$task_setup/pip-cache"
export XDG_CACHE_HOME="$task_setup/cache"
export CUDA_HOME="$task_root/.venv/lib/python3.11/site-packages/nvidia/cu13"
export TORCH_CUDA_ARCH_LIST=12.0
export MAX_JOBS=2
cd "$task_root/thirdparty/Splatt3R-SLAM"
python -m pip wheel --no-deps --no-build-isolation --wheel-dir "$task_setup/wheels" thirdparty/lietorch
python -m pip wheel --no-deps --no-build-isolation --wheel-dir "$task_setup/wheels" thirdparty/diff-gaussian-rasterization-modified

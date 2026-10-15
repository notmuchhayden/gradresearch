#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_setup="$task_root/results/E0_baseline_reproduction/setup"
exec > >(tee -a "$task_setup/backend.log") 2>&1
export PATH="$task_root/.venv/bin:$PATH"
export CONDA_PREFIX="$task_root/.venv"
export PIP_CACHE_DIR="$task_setup/pip-cache"
export XDG_CACHE_HOME="$task_setup/cache"
export CUDA_HOME="$task_root/.venv/lib/python3.11/site-packages/nvidia/cu13"
export TORCH_CUDA_ARCH_LIST=12.0
export MAX_JOBS=2
cd "$task_root/thirdparty/Splatt3R-SLAM"
python -m pip install --no-build-isolation -e .
cd splatt3r_core/src/mast3r_src/dust3r/croco/models/curope
python setup.py build_ext --inplace

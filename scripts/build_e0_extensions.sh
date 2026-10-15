#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_setup="$task_root/results/E0_baseline_reproduction/setup"
mkdir -p "$task_setup"
exec > >(tee -a "$task_setup/extensions.log") 2>&1
export PATH="$task_root/.venv/bin:$PATH"
export CONDA_PREFIX="$task_root/.venv"
export PIP_CACHE_DIR="$task_setup/pip-cache"
export XDG_CACHE_HOME="$task_setup/cache"
export CUDA_HOME=/usr/local/cuda
export TORCH_CUDA_ARCH_LIST=12.0
export MAX_JOBS=2
cd "$task_root/thirdparty/Splatt3R-SLAM"
python -c 'import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name())'
cmake -S thirdparty/faiss -B thirdparty/faiss/build \
  -DCMAKE_CUDA_ARCHITECTURES=120 -DFAISS_ENABLE_EXTRAS=OFF \
  -DPython_NumPy_INCLUDE_DIR="$(python -c 'import numpy; print(numpy.get_include())')"
cmake --build thirdparty/faiss/build --parallel 2 --target faiss swigfaiss
python -m pip install --no-build-isolation --no-deps ./thirdparty/faiss/build/faiss/python
export CUDA_HOME="$task_root/.venv/lib/python3.11/site-packages/nvidia/cu13"
python -m pip install --no-build-isolation thirdparty/lietorch
python -m pip install --no-build-isolation thirdparty/diff-gaussian-rasterization-modified
python -m pip install --no-build-isolation -e .
cd splatt3r_core/src/mast3r_src/dust3r/croco/models/curope
python setup.py build_ext --inplace
python -m pip freeze > "$task_setup/pip-freeze.txt"
python -m pip check

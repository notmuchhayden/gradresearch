#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_setup="$task_root/results/E0_baseline_reproduction/setup"
mkdir -p "$task_setup"
exec > >(tee -a "$task_setup/dependencies.log") 2>&1
export PATH="$task_root/.venv/bin:$PATH"
export CONDA_PREFIX="$task_root/.venv"
export PIP_CACHE_DIR="$task_setup/pip-cache"
export XDG_CACHE_HOME="$task_setup/cache"
export CUDA_HOME=/usr/local/cuda
export TORCH_CUDA_ARCH_LIST=12.0
export MAX_JOBS=2
python -m pip install 'torch==2.13.0+cu132' 'torchvision==0.28.0+cu132' \
  --index-url https://download.pytorch.org/whl/cu132
python - <<'PY'
import json
import torch
assert torch.cuda.is_available(), 'CUDA must be available before building extensions'
x = torch.randn(128, 128, device='cuda')
y = x @ x.T
torch.cuda.synchronize()
print(json.dumps(dict(torch=torch.__version__, cuda=torch.version.cuda,
    gpu=torch.cuda.get_device_name(), capability=torch.cuda.get_device_capability(),
    arch_list=torch.cuda.get_arch_list(), matmul_finite=y.isfinite().all().item())))
PY
python -m pip install 'setuptools>=77.0.3' wheel mkl-devel
python -m pip install 'cuda-toolkit[nvcc,cccl]==13.2.1'
python - <<'PY'
from pathlib import Path
import sysconfig
lib = Path(sysconfig.get_path('purelib')) / 'nvidia/cu13/lib'
link = lib / 'libcudart.so'
if not link.exists():
    link.symlink_to('libcudart.so.13')
PY
cd "$task_root/thirdparty/Splatt3R-SLAM"
python -m pip install -r requirements.txt
python -m pip install -e thirdparty/in3d 'numpy>=2.0'
python -m pip install --no-build-isolation thirdparty/asmk
python -m pip freeze > "$task_setup/pip-after-dependencies.txt"

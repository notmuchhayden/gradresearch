#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_run="$task_root/results/E0_baseline_reproduction"
mkdir -p "$task_run/evaluation"
exec > >(tee "$task_run/evaluation/checks-and-metrics.log") 2>&1
export PATH="$task_root/.venv/bin:$PATH"
export CONDA_PREFIX="$task_root/.venv"
export TORCH_HOME="$task_run/setup/torch-cache"
export XDG_CACHE_HOME="$task_run/setup/cache"
export MPLCONFIGDIR="$task_run/setup/matplotlib"
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
if [[ "${1:-}" != "--metrics-only" ]]; then
  python "$task_root/scripts/check_e0_exports.py"
fi
python "$task_root/scripts/evaluate_e0.py"

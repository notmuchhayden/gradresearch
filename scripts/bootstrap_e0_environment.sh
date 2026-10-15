#!/usr/bin/env bash
# Run from any directory. Keep the manager, cache and environment in the project.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_setup="$task_root/results/E0_baseline_reproduction/setup"
mkdir -p "$task_setup/bin"
exec > >(tee -a "$task_setup/bootstrap.log") 2>&1
export MAMBA_ROOT_PREFIX="$task_setup/micromamba"
export CONDA_PKGS_DIRS="$task_setup/conda-pkgs"
export PIP_CACHE_DIR="$task_setup/pip-cache"
export XDG_CACHE_HOME="$task_setup/cache"
task_mamba="$task_setup/bin/micromamba"
if [[ ! -x "$task_mamba" ]]; then
  wget -q --timeout=60 --tries=3 -O "$task_setup/micromamba.tar.bz2" \
    https://micro.mamba.pm/api/micromamba/linux-64/latest
  tar -xjf "$task_setup/micromamba.tar.bz2" -C "$task_setup" bin/micromamba
fi
"$task_mamba" --version
if [[ ! -x "$task_root/.venv/bin/python" ]]; then
  "$task_mamba" create --yes --prefix "$task_root/.venv" \
    --file "$task_root/configs/e0_environment.yml"
fi
"$task_root/.venv/bin/python" --version
"$task_mamba" list --prefix "$task_root/.venv" --explicit > "$task_setup/conda-explicit.txt"

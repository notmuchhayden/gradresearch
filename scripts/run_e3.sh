#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
task_out="$task_root/results/E3_admission_decision"
mkdir -p "$task_out/logs"
task_step="${1:-test}"
task_scene="${2:-room0}"
case "$task_step" in
  test) .venv/bin/python -m unittest discover -s tests -v 2>&1 | tee "$task_out/logs/tests.log" ;;
  prepare|replay|evaluate) .venv/bin/python scripts/run_e3.py "$task_step" "$task_scene" 2>&1 | tee "$task_out/logs/${task_step}_${task_scene}.log" ;;
  report) .venv/bin/python scripts/report_e3.py ;;
  verify) .venv/bin/python scripts/check_e3.py ;;
  *) printf 'usage: bash scripts/run_e3.sh test|prepare|replay|evaluate|report|verify [office0|room0]\n' >&2; exit 2 ;;
esac

#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
task_out="$task_root/results/E1_error_taxonomy"
mkdir -p "$task_out/logs"
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export MPLCONFIGDIR="$task_out/.mplconfig"
case "${1:-all}" in
  check) .venv/bin/python scripts/check_e1_baseline.py 2>&1 | tee "$task_out/logs/baseline_integrity.log" ;;
  analyze) .venv/bin/python scripts/analyze_e1.py 2>&1 | tee "$task_out/logs/analyze.log" ;;
  render) .venv/bin/python scripts/render_e1.py 2>&1 | tee "$task_out/logs/render.log" ;;
  plot) .venv/bin/python scripts/plot_e1.py ;;
  all)
    .venv/bin/python -m unittest discover -s tests -v 2>&1 | tee "$task_out/logs/tests.log"
    .venv/bin/python scripts/check_e1_baseline.py 2>&1 | tee "$task_out/logs/baseline_integrity.log"
    .venv/bin/python scripts/analyze_e1.py 2>&1 | tee "$task_out/logs/analyze.log"
    .venv/bin/python scripts/render_e1.py 2>&1 | tee "$task_out/logs/render.log"
    .venv/bin/python scripts/plot_e1.py
    ;;
  *) echo "usage: bash scripts/run_e1.sh [all|check|analyze|render|plot]" >&2; exit 2 ;;
esac

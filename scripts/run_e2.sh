#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
task_out="$task_root/results/E2_signal_discriminability"
mkdir -p "$task_out/logs"
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export MPLCONFIGDIR="$task_out/.mplconfig"
case "${1:-all}" in
  test) .venv/bin/python -m unittest discover -s tests -v 2>&1 | tee "$task_out/logs/tests.log" ;;
  score) .venv/bin/python scripts/score_e2.py 2>&1 | tee "$task_out/logs/score.log" ;;
  render) .venv/bin/python scripts/render_e2_premaps.py 2>&1 | tee "$task_out/logs/render.log" ;;
  analyze) .venv/bin/python scripts/analyze_e2.py 2>&1 | tee "$task_out/logs/analyze.log" ;;
  plot) .venv/bin/python scripts/plot_e2.py ;;
  all)
    .venv/bin/python -m unittest discover -s tests -v 2>&1 | tee "$task_out/logs/tests.log"
    .venv/bin/python scripts/score_e2.py 2>&1 | tee "$task_out/logs/score.log"
    .venv/bin/python scripts/render_e2_premaps.py 2>&1 | tee "$task_out/logs/render.log"
    .venv/bin/python scripts/analyze_e2.py 2>&1 | tee "$task_out/logs/analyze.log"
    .venv/bin/python scripts/plot_e2.py
    ;;
  *) echo "usage: bash scripts/run_e2.sh [all|test|score|render|analyze|plot]" >&2; exit 2 ;;
esac

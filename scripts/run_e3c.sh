#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
task_out="$task_root/results/E3c_matched_evidence"
mkdir -p "$task_out/logs"
task_step="${1:-test}"
task_scene="${2:-office0}"
case "$task_step" in
  test) .venv/bin/python -m unittest discover -s tests -v 2>&1 | tee "$task_out/logs/tests.log" ;;
  initialize|prepare|replay|evaluate) .venv/bin/python scripts/run_e3c.py "$task_step" "$task_scene" 2>&1 | tee "$task_out/logs/${task_step}_${task_scene}.log" ;;
  score) .venv/bin/python scripts/score_e3c.py "$task_scene" 2>&1 | tee "$task_out/logs/score_${task_scene}.log" ;;
  fresh-download|fresh-baseline|fresh-labels) .venv/bin/python scripts/e3c_fresh.py "$task_step" ;;
  verify) .venv/bin/python scripts/check_e3c.py ;;
  report) .venv/bin/python scripts/report_e3c.py ;;
  *) echo 'usage: bash scripts/run_e3c.sh test|initialize|score|prepare|replay|evaluate|fresh-download|fresh-baseline|fresh-labels|verify|report [office0|room0|room1|room2]' >&2; exit 2 ;;
esac

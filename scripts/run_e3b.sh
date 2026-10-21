#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
task_out="$task_root/results/E3b_provisional_admission"
mkdir -p "$task_out/logs"
task_step="${1:-test}"
task_scene="${2:-room0}"
case "$task_step" in
  test) .venv/bin/python -m unittest discover -s tests -v 2>&1 | tee "$task_out/logs/tests.log" ;;
  prepare|replay|evaluate) .venv/bin/python scripts/run_e3b.py "$task_step" "$task_scene" 2>&1 | tee "$task_out/logs/${task_step}_${task_scene}.log" ;;
  fresh-status|fresh-download|fresh-baseline|fresh-labels) .venv/bin/python scripts/e3b_fresh.py "$task_step" ;;
  fresh-score) .venv/bin/python scripts/score_e3b_fresh.py room1 2>&1 | tee "$task_out/logs/fresh_score_room1.log" ;;
  verify) .venv/bin/python scripts/check_e3b.py ;;
  report) .venv/bin/python scripts/report_e3b.py ;;
  *) printf 'usage: bash scripts/run_e3b.sh test|prepare|replay|evaluate|fresh-status|fresh-download|fresh-baseline|fresh-score|fresh-labels|verify|report [office0|room0|room1]\n' >&2; exit 2 ;;
esac

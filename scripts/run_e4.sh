#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
export PYTHONPATH="$task_root/results/E4_matched_budget/deps${PYTHONPATH:+:$PYTHONPATH}"
export TORCH_HOME="$task_root/results/E0_baseline_reproduction/setup/torch-cache"
export MPLCONFIGDIR="$task_root/results/E4_matched_budget/.mplconfig"
task_step="${1:-test}"; task_scene="${2:-office0}"
mkdir -p results/E4_matched_budget/logs
case "$task_step" in
 test) .venv/bin/python -m unittest discover -s tests -v 2>&1 | tee results/E4_matched_budget/logs/tests.log ;;
 initialize|prepare|replay) .venv/bin/python scripts/run_e4.py "$task_step" "$task_scene" 2>&1 | tee "results/E4_matched_budget/logs/${task_step}_${task_scene}.log" ;;
 score) .venv/bin/python scripts/score_e4.py "$task_scene" 2>&1 | tee "results/E4_matched_budget/logs/score_${task_scene}.log" ;;
 fresh-download|fresh-baseline|fresh-labels) .venv/bin/python scripts/e4_fresh.py "$task_step" ;;
 evaluate) .venv/bin/python scripts/evaluate_e4.py "$task_scene" 2>&1 | tee "results/E4_matched_budget/logs/evaluate_${task_scene}.log" ;;
 verify) .venv/bin/python scripts/check_e4.py ;;
 report) .venv/bin/python scripts/report_e4.py ;;
 *) echo 'usage: bash scripts/run_e4.sh test|initialize|prepare|score|replay|fresh-download|fresh-baseline|fresh-labels|evaluate|verify|report [scene]' >&2; exit 2 ;;
esac

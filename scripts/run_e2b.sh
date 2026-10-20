#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
task_out="$task_root/results/E2b_repeated_observations_threshold_transfer"
mkdir -p "$task_out/logs"
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
export MPLCONFIGDIR="$task_out/.mplconfig"
task_step="${1:-test}"
task_scene="${2:-office0}"
case "$task_scene" in office0|room0) ;; *) exit 2 ;; esac
case "$task_step" in
  download) python3 scripts/download_e0_replica.py --scene "$task_scene" --frames 1000 \
    --destination data/E2b/Replica --manifest "configs/e2b_${task_scene}_download_manifest.json" \
    --reuse-from data/E1/Replica --workers 8 2>&1 | tee "$task_out/logs/download_${task_scene}.log" ;;
  baseline) bash scripts/run_e2b_baseline.sh "$task_scene" ;;
  score) .venv/bin/python scripts/score_e2b.py "$task_scene" 2>&1 | tee "$task_out/logs/score_${task_scene}.log" ;;
  render) .venv/bin/python scripts/render_e2b_premaps.py "$task_scene" 2>&1 | tee "$task_out/logs/render_${task_scene}.log" ;;
  development|evaluation) .venv/bin/python scripts/analyze_e2b.py "$task_step" 2>&1 | tee "$task_out/logs/${task_step}.log" ;;
  plot) .venv/bin/python scripts/plot_e2b.py ;;
  verify) .venv/bin/python scripts/check_e2b.py ;;
  test) .venv/bin/python -m unittest discover -s tests -v 2>&1 | tee "$task_out/logs/tests.log" ;;
  *) printf 'usage: bash scripts/run_e2b.sh download|baseline|score|render [office0|room0], or development|evaluation|plot|verify|test\n' >&2; exit 2 ;;
esac

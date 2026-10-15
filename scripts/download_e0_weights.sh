#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_weights="$task_root/checkpoints/e0"
task_setup="$task_root/results/E0_baseline_reproduction/setup"
mkdir -p "$task_weights" "$task_setup"
exec > >(tee -a "$task_setup/weights.log") 2>&1
task_base=https://download.europe.naverlabs.com/ComputerVision/MASt3R
for task_name in \
  MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth \
  MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_codebook.pkl; do
  wget -q --continue --timeout=60 --tries=3 -O "$task_weights/$task_name" "$task_base/$task_name"
done
wget -q --continue --timeout=60 --tries=3 \
  -O "$task_weights/epoch=19-step=1200.ckpt" \
  'https://huggingface.co/brandonsmart/splatt3r_v1.0/resolve/main/epoch%3D19-step%3D1200.ckpt'
sha256sum "$task_weights/"* > "$task_setup/weights.sha256"
cat "$task_setup/weights.sha256"

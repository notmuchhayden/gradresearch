#!/usr/bin/env python3
"""Run the sealed RGB-only E4f B1 baseline on the selected KITTI drive."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_e2b_run import digest, save_json

UPSTREAM = ROOT / "thirdparty/Splatt3R-SLAM"
DRIVE = "2011_09_26_drive_0015_sync"
DATASET = ROOT / f"data/E4f/eth3d/{DRIVE}"
RUN = ROOT / f"results/E4f_kitti_geometry_diagnostic/{DRIVE}/baseline_A2b"
WEIGHTS = json.loads((ROOT / "configs/e0_weights_manifest.json").read_text())
CODE_PATHS = [
    "scripts/prepare_e4f_kitti_inputs.py", "scripts/run_e4f_kitti_baseline.py",
    "scripts/register_e4f_a2_sampling.py", "scripts/prepare_e2b_run.py",
    "configs/e4f_kitti_b1.yaml", "configs/e4f_kitti_geometry_diagnostic.json",
    "configs/e4f_kitti_input_split.json", "configs/e4f_kitti_selection.json",
    "configs/e4f_kitti_dataset_manifest.json", "configs/e4f_amendment_A1.json",
    "configs/e4f_amendment_A2.json",
    "configs/e4f_amendment_A2b.json",
]
UPSTREAM_PATHS = ["main.py", "config/base.yaml", "splatt3r_slam/dataloader.py",
                  "splatt3r_slam/tracker.py", "splatt3r_slam/frame.py",
                  "splatt3r_slam/splatt3r_utils.py"]


def run() -> None:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not visible; run through the host-enabled execution session")
    if (RUN / "run_manifest.json").exists() or (RUN / "logs/baseline.log").exists():
        raise RuntimeError(f"Existing run preserved at {RUN}")
    split = json.loads((ROOT / "configs/e4f_kitti_input_split.json").read_text())
    rows = split["frames"]
    if len(rows) != 240 or sum(bool(x["model_input_rgb"]) for x in rows) != 120:
        raise RuntimeError("A2 split must contain 240 selected rows and exactly 120 RGB model inputs")
    if any(x["model_input_lidar"] or x["model_input_oxts"] for x in rows):
        raise RuntimeError("GT modality is marked as model input")
    rgb_rows = [x.split() for x in (DATASET / "rgb.txt").read_text().splitlines() if x.strip()]
    if len(rgb_rows) != 240 or not all((DATASET / p[1]).is_file() for p in rgb_rows):
        raise RuntimeError("RGB-only model input is incomplete")
    sampled_rgb_rows = rgb_rows[::2]
    inputs = [digest(DATASET / p[1]) for p in sampled_rgb_rows]
    if len(inputs) != 120:
        raise RuntimeError("A2 RGB stride must provide 120 model input frames")
    for item in WEIGHTS:
        actual = digest(ROOT / item["file"])
        if actual["bytes"] != item["bytes"] or actual["sha256"] != item["sha256"]:
            raise RuntimeError(f"checkpoint hash mismatch: {item['file']}")
    RUN.mkdir(parents=True, exist_ok=False)
    for folder in ("logs", "exports", "audit", "render", "code"):
        (RUN / folder).mkdir()
    code = [digest(ROOT / p) for p in CODE_PATHS]
    code += [digest(UPSTREAM / p) for p in UPSTREAM_PATHS]
    command = [str(ROOT / ".venv/bin/python"), "main.py",
        "--dataset", str(DATASET), "--config", str(ROOT / "configs/e4f_kitti_b1.yaml"),
        "--checkpoint", str(ROOT / "checkpoints/e0/epoch=19-step=1200.ckpt"),
        "--retriever-path", str(ROOT / "checkpoints/e0/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth"),
        "--no-viz", "--no-render-gaussians", "--keyframe-buffer", "128",
        "--dump-keyframe-gaussians", "--spatial-stride", "1", "--max-gaussians", "16777216",
        "--depth-max-percentile", "0.98", "--max-scale", "1.0", "--min-confidence", "1.5",
        "--refiner-conf-fade", "0", "--save-as", str(RUN / "map"),
        "--render-dir", str(RUN / "render"), "--frame-timing", str(RUN / "timing.csv")]
    env = os.environ.copy()
    venv = str(ROOT / ".venv")
    env.update(PATH=venv + "/bin:" + env.get("PATH", ""), CONDA_PREFIX=venv,
        CUDA_HOME=venv + "/lib/python3.11/site-packages/nvidia/cu13", CUDA_VISIBLE_DEVICES="0",
        PYTHONPATH=str(ROOT / "src") + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
        PYTHONHASHSEED="0", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2",
        E0_EXPORT_DIR=str(RUN / "exports"), E0B_AUDIT_DIR=str(RUN / "audit"), E0_SEED="0",
        E0_DISABLE_GT="1", E0_FAISS_TEMP_MB="64", E0_LOW_VRAM="1",
        MPLCONFIGDIR=str(RUN / ".mplconfig"),
        XDG_CACHE_HOME=str(ROOT / "results/E0_baseline_reproduction/setup/cache"),
        TORCH_HOME=str(ROOT / "results/E0_baseline_reproduction/setup/torch-cache"),
        HF_HOME=str(ROOT / "results/E0_baseline_reproduction/setup/huggingface"))
    gpu = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv"], text=True)
    manifest = {
        "experiment":"E4f KITTI outdoor geometry consistency diagnostic",
        "drive":DRIVE,"status":"started","started_at":datetime.now(timezone.utc).isoformat(),
        "spec":digest(ROOT / "configs/e4f_kitti_geometry_diagnostic.json"),
        "amendment":digest(ROOT / "configs/e4f_amendment_A1.json"),
        "amendment_A2":digest(ROOT / "configs/e4f_amendment_A2.json"),
        "amendment_A2b":digest(ROOT / "configs/e4f_amendment_A2b.json"),
        "selection":digest(ROOT / "configs/e4f_kitti_selection.json"),
        "input_split":digest(ROOT / "configs/e4f_kitti_input_split.json"),
        "dataset_manifest":digest(ROOT / "configs/e4f_kitti_dataset_manifest.json"),
        "code":code,"rgb_inputs":inputs,"rgb_input_count":len(inputs),
        "evaluation_gt_passed_to_model":False,"command":command,
        "environment":{"torch":torch.__version__,"cuda":torch.version.cuda,
                        "device":torch.cuda.get_device_name(0),"nvidia_smi":gpu,
                        "seed":0,"refinement":False},
        "native_filtering":"unchanged E4 B1 settings",
    }
    save_json(RUN / "run_manifest.json", manifest)
    for p in CODE_PATHS:
        dst = RUN / "code" / p
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / p, dst)
    for p in UPSTREAM_PATHS:
        dst = RUN / "code/thirdparty/Splatt3R-SLAM" / p
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(UPSTREAM / p, dst)
    status = 0
    with (RUN / "logs/baseline.log").open("w") as log:
        result = subprocess.run(command, cwd=UPSTREAM, env=env, stdout=log, stderr=subprocess.STDOUT)
        status = result.returncode
    manifest["status"] = "complete" if status == 0 else "failed"
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["return_code"] = status
    save_json(RUN / "run_manifest.json", manifest)
    if status:
        raise SystemExit(status)
    print(json.dumps({"drive":DRIVE,"status":manifest["status"],"run_dir":str(RUN)}, indent=2))


if __name__ == "__main__":
    run()

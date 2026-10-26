#!/usr/bin/env python3
"""Run registered office2 A0 RGB-only baseline, preserving all earlier runs."""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from prepare_e2b_run import digest,save_json


def main():
    if not torch.cuda.is_available():raise RuntimeError("Use a GPU-visible execution context")
    cfg=ROOT/"configs/a0_office2_factorial.json";spec=json.loads(cfg.read_text())
    out=ROOT/spec["output"];run=out/"baseline";upstream=ROOT/"thirdparty/Splatt3R-SLAM"
    assert spec["scene"]=="office2" and spec["access_scope"].startswith("office2 only")
    if (out/"registration.json").exists():raise RuntimeError("Existing registered run preserved")
    out.mkdir(parents=True,exist_ok=True)
    save_json(out/"registration.json",{"registered_at":datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "specification":spec,"specification_file":digest(cfg),"before_baseline_or_oracle_results":True})
    manifest=json.loads((ROOT/spec["n2_manifest"]).read_text())
    dataset=ROOT/spec["dataset"]
    paths={r["path"]:r for r in manifest["files"] if r["path"].startswith(str(dataset.relative_to(ROOT))+"/")
           or r["path"]=="data/N2/Replica/cam_params.json"}
    for p,row in paths.items():assert digest(ROOT/p)["sha256"]==row["sha256"],p
    weights=json.loads((ROOT/"configs/e0_weights_manifest.json").read_text())
    for w in weights:assert digest(ROOT/w["file"])["sha256"]==w["sha256"]
    run.mkdir(exist_ok=False)
    for folder in ("logs","exports","audit","code"):(run/folder).mkdir()
    source=[cfg,Path(__file__),ROOT/"configs/e0b_replica_office0.yaml",ROOT/"src/e0_export.py",ROOT/"src/e0b_export.py"]
    source += [upstream/p for p in ["main.py","config/base.yaml","splatt3r_slam/dataloader.py",
        "splatt3r_slam/frame.py","splatt3r_slam/tracker.py","splatt3r_slam/splatt3r_utils.py","splatt3r_slam/evaluate.py"]]
    for p in source:
        target=run/"code"/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    args=[str(ROOT/".venv/bin/python"),"main.py","--dataset",str(dataset),"--config",str(ROOT/spec["baseline"]["configuration"]),
        "--checkpoint",str(ROOT/"checkpoints/e0/epoch=19-step=1200.ckpt"),"--retriever-path",
        str(ROOT/"checkpoints/e0/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth"),
        "--no-viz","--no-render-gaussians","--keyframe-buffer",str(spec["baseline"]["keyframe_buffer"]),
        "--dump-keyframe-gaussians","--spatial-stride","1","--max-gaussians","16777216",
        "--depth-max-percentile","0.98","--max-scale","1.0","--min-confidence","1.5","--refiner-conf-fade","0",
        "--save-as",str(run/"map"),"--render-dir",str(run/"render"),"--frame-timing",str(run/"timing.csv")]
    env=os.environ.copy();venv=str(ROOT/".venv")
    env.update(PATH=venv+"/bin:"+env.get("PATH",""),CONDA_PREFIX=venv,CUDA_VISIBLE_DEVICES="0",
        CUDA_HOME=venv+"/lib/python3.11/site-packages/nvidia/cu13",PYTHONPATH=str(ROOT/"src"),
        PYTHONHASHSEED="0",OMP_NUM_THREADS="2",MKL_NUM_THREADS="2",OPENBLAS_NUM_THREADS="2",
        E0_EXPORT_DIR=str(run/"exports"),E0B_AUDIT_DIR=str(run/"audit"),E0_SEED="0",E0_DISABLE_GT="1",
        E0_FAISS_TEMP_MB="64",E0_LOW_VRAM="1",HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",
        TORCH_HOME=str(ROOT/"results/E0_baseline_reproduction/setup/torch-cache"),
        HF_HOME=str(ROOT/"results/E0_baseline_reproduction/setup/huggingface"),
        XDG_CACHE_HOME=str(ROOT/"results/E0_baseline_reproduction/setup/cache"),MPLCONFIGDIR=str(run/"matplotlib"))
    record={"status":"started","scene":"office2","specification":spec,"code":[digest(p) for p in source],
        "inputs":[paths[str((dataset/"results"/f"frame{i:06d}.jpg").relative_to(ROOT))] for i in range(0,1000,2)],
        "weights":weights,"command":args,"gt_depth_trajectory_passed_to_mapper":False,"env_overrides":{k:env[k] for k in
        ["E0_SEED","E0_DISABLE_GT","E0_LOW_VRAM","E0_FAISS_TEMP_MB","HF_HUB_OFFLINE","OMP_NUM_THREADS"]},
        "environment":{"torch":torch.__version__,"cuda":torch.version.cuda,"gpu":torch.cuda.get_device_name(0),
        "nvidia_smi":subprocess.check_output(["nvidia-smi","--query-gpu=name,memory.total,driver_version","--format=csv"],text=True)},
        "started_at":datetime.now(ZoneInfo("Asia/Seoul")).isoformat()}
    save_json(run/"run_manifest.json",record)
    started=time.monotonic()
    with (run/"device_memory.csv").open("w") as gpu,(run/"logs/baseline.log").open("w") as log:
        monitor=subprocess.Popen(["nvidia-smi","--query-gpu=timestamp,memory.used,utilization.gpu","--format=csv","--loop-ms=200"],stdout=gpu)
        try:result=subprocess.run(args,cwd=upstream,env=env,stdout=log,stderr=subprocess.STDOUT)
        finally:monitor.terminate();monitor.wait()
    record.update(status="complete" if result.returncode==0 else "failed",returncode=result.returncode,
                  wall_seconds=time.monotonic()-started,finished_at=datetime.now(ZoneInfo("Asia/Seoul")).isoformat())
    save_json(run/"run_manifest.json",record)
    if result.returncode:raise SystemExit(result.returncode)
    poses=np.loadtxt(run/"map/office2_frames.txt")
    dump=torch.load(run/"map/office2_kfgauss.pt",weights_only=True,map_location="cpu")
    post=[k for k in dump["keyframes"] if 2*k["frame_id"]>=200]
    qualification={"tracked_poses":len(poses),"expected_inputs":500,"tracking_fraction":len(poses)/500,
        "matched_calibration_poses":int(np.sum(poses[:,0]<200)),"keyframes":dump["n"],"post_prefix_keyframes":len(post),
        "raw_events":len(list((run/"exports/raw_pairs").glob("*.pt")))}
    passed=(qualification["tracking_fraction"]>=spec["baseline"]["min_tracking_fraction"] and
            qualification["matched_calibration_poses"]>=spec["baseline"]["min_matched_calibration_poses"] and
            len(post)>=spec["baseline"]["min_post_prefix_keyframes"])
    qualification["status"]="PASS" if passed else "FAIL"
    save_json(run/"qualification.json",qualification)
    print(json.dumps(qualification,indent=2),flush=True)
    if not passed:raise RuntimeError("Preserve run and inspect qualification before proceeding")


if __name__=="__main__":main()

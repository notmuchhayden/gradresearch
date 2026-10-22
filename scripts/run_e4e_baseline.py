"""Run E4e's unchanged B1 baseline on a prepared mapping-only sequence."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from prepare_e2b_run import digest, save_json

UPSTREAM=ROOT/"thirdparty/Splatt3R-SLAM"
WEIGHTS=json.loads((ROOT/"configs/e0_weights_manifest.json").read_text())
CODE_PATHS=["scripts/run_e4e_baseline.py","scripts/prepare_e4e_uav_inputs.py",
 "scripts/check_e4e_representativeness.py","configs/e4e_uav_dataset_pilot.json",
 "configs/e4e_uav_b1.yaml","configs/e0b_replica_office0.yaml",
 "configs/e0_weights_manifest.json","configs/e4e_dataset_manifest.json",
 "configs/e4e_input_split.json","configs/e4e_window_amendment_A1.json",
 "configs/e4e_window_selection_A1.json"]
CODE_PATHS.append("data/E4e/calibration_results.py")
UPSTREAM_PATHS=["main.py","config/base.yaml","splatt3r_slam/dataloader.py",
 "splatt3r_slam/tracker.py","splatt3r_slam/frame.py","splatt3r_slam/splatt3r_utils.py"]

def run(scene):
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not visible in this execution context; run through the host-enabled execution session")
    if scene not in ("HKairport01","AMtown01","AMvalley01"):
        raise ValueError(scene)
    role="development" if scene=="HKairport01" else "primary_evaluation"
    if role=="primary_evaluation":
        raise RuntimeError("Primary evaluation is sealed until HKairport01 development and protocol registration finish")
    dataset=ROOT/f"data/E4e/eth3d/{scene}"
    run_dir=ROOT/f"results/E4e_uav_dataset_pilot/{role}/{scene}/baseline"
    if (run_dir/"run_manifest.json").exists() or (run_dir/"logs/baseline.log").exists():
        raise RuntimeError(f"Existing run preserved at {run_dir}")
    rgb_rows=[r.strip() for r in (dataset/"rgb.txt").read_text().splitlines() if r.strip()]
    image_paths=[dataset/r.split()[1] for r in rgb_rows]
    assert len(image_paths)==240 and all(p.is_file() for p in image_paths)
    split=json.loads((ROOT/"configs/e4e_input_split.json").read_text())
    frames=split["scene_splits"][scene]["frames"]
    assert sum(f["role"]=="mapping" for f in frames)==240
    assert len({f["rgb_timestamp"] for f in frames})==300
    assert len([f for f in frames if f["role"]=="heldout"])==60
    checked_weights=[]
    for entry in WEIGHTS:
        actual=digest(ROOT/entry["file"])
        assert actual["bytes"]==entry["bytes"] and actual["sha256"]==entry["sha256"],entry["file"]
        checked_weights.append({**actual,"source_url":entry["url"]})
    run_dir.mkdir(parents=True,exist_ok=True)
    for folder in ["logs","exports","audit","render","code"]:
        (run_dir/folder).mkdir(exist_ok=True)
    code=[digest(ROOT/p) for p in CODE_PATHS]
    code += [digest(UPSTREAM/p) for p in UPSTREAM_PATHS]
    imgs=[digest(p) for p in image_paths]
    inputs=[digest(dataset/"rgb.txt"),digest(dataset/"calibration.txt"),*imgs]
    input_manifest=json.loads((ROOT/f"results/E4e_uav_dataset_pilot/{role}/{scene}/input_manifest.json").read_text())
    for item in input_manifest["files"]:
        if item["role"]=="mapping_rgb":
            source=ROOT/"data/E4e/archives/interval1_HKairport01.zip"
            # The compressed source archive hash and mapping member names are
            # retained separately; extracted RGB bytes are hashed above.
            assert source.exists()
    command=[str(ROOT/".venv/bin/python"),"main.py","--dataset",str(dataset),
      "--config",str(ROOT/"configs/e4e_uav_b1.yaml"),
      "--checkpoint",str(ROOT/"checkpoints/e0/epoch=19-step=1200.ckpt"),
      "--retriever-path",str(ROOT/"checkpoints/e0/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth"),
      "--no-viz","--no-render-gaussians","--keyframe-buffer","32","--dump-keyframe-gaussians",
      "--spatial-stride","1","--max-gaussians","16777216","--depth-max-percentile","0.98",
      "--max-scale","1.0","--min-confidence","1.5","--refiner-conf-fade","0",
      "--save-as",str(run_dir/"map"),"--render-dir",str(run_dir/"render"),
      "--frame-timing",str(run_dir/"timing.csv")]
    env=os.environ.copy(); venv=str(ROOT/".venv")
    env.update(PATH=venv+"/bin:"+env.get("PATH",""),CONDA_PREFIX=venv,
      CUDA_HOME=venv+"/lib/python3.11/site-packages/nvidia/cu13",CUDA_VISIBLE_DEVICES="0",
      PYTHONPATH=str(ROOT/"src")+(":"+env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
      PYTHONHASHSEED="0",OMP_NUM_THREADS="2",MKL_NUM_THREADS="2",OPENBLAS_NUM_THREADS="2",
      E0_EXPORT_DIR=str(run_dir/"exports"),E0B_AUDIT_DIR=str(run_dir/"audit"),E0_SEED="0",
      E0_DISABLE_GT="1",E0_FAISS_TEMP_MB="64",E0_LOW_VRAM="1",
      MPLCONFIGDIR=str(run_dir/".mplconfig"),
      XDG_CACHE_HOME=str(ROOT/"results/E0_baseline_reproduction/setup/cache"),
      TORCH_HOME=str(ROOT/"results/E0_baseline_reproduction/setup/torch-cache"),
      HF_HOME=str(ROOT/"results/E0_baseline_reproduction/setup/huggingface"))
    gpu=subprocess.check_output(["nvidia-smi","--query-gpu=name,memory.total,driver_version","--format=csv"],text=True)
    manifest={"scene":scene,"role":role,"status":"started","started_at":datetime.now(timezone.utc).isoformat(),
      "experiment":json.loads((ROOT/"configs/e4e_uav_dataset_pilot.json").read_text()),
      "spec_sha256":digest(ROOT/"configs/e4e_uav_dataset_pilot.json")["sha256"],
      "upstream_commit":subprocess.check_output(["git","-C",str(UPSTREAM),"rev-parse","HEAD"],text=True).strip(),
      "code":code,"inputs":inputs,"source_archive_manifest":digest(ROOT/"configs/e4e_dataset_manifest.json"),
      "mapping_only_input_count":len(image_paths),"heldout_input_count":0,
      "input_selection":digest(ROOT/"configs/e4e_input_split.json"),"weights":checked_weights,
      "command":command,"environment":{"torch":torch.__version__,"cuda":torch.version.cuda,
         "device":torch.cuda.get_device_name(0),"nvidia_smi":gpu,"seed":0,"refinement":False},
      "gt_pose_or_lidar_used_for_mapping":False,"native_filtering":"unchanged E4 B1 settings"}
    save_json(run_dir/"run_manifest.json",manifest)
    for p in CODE_PATHS:
        target=run_dir/"code"/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/p,target)
    for p in UPSTREAM_PATHS:
        target=run_dir/"code"/"thirdparty/Splatt3R-SLAM"/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(UPSTREAM/p,target)
    status=0
    with (run_dir/"logs/baseline.log").open("w") as log:
        proc=subprocess.run(command,cwd=UPSTREAM,env=env,stdout=log,stderr=subprocess.STDOUT)
        status=proc.returncode
    manifest["status"]="complete" if status==0 else "failed"
    manifest["finished_at"]=datetime.now(timezone.utc).isoformat()
    manifest["return_code"]=status
    save_json(run_dir/"run_manifest.json",manifest)
    if status:
        raise SystemExit(status)
    print(json.dumps({"scene":scene,"status":manifest["status"],"run_dir":str(run_dir)},indent=2))

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("scene",nargs="?",default="HKairport01");a=p.parse_args();run(a.scene)

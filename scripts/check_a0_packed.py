#!/usr/bin/env python3
"""Independently invert saved compact maps and verify intervention invariants."""
from pathlib import Path
import json
import sys
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from pointmap_contract import project,sim3_from_xyzw,metric_placement,transform_points


def main():
    out=ROOT/"results/A0_pointmap_pose_factorial/office2"
    m=json.loads((out/"oracles/manifest.json").read_text());gauge=np.array(m["gauge"]);C=m["C"]
    K=np.load(out/"oracles/K.npy");lookup={v["id"]:v for v in m["variants"]}
    maps={key:np.memmap(ROOT/v["map_file"],dtype=np.float32,mode="r",shape=(v["count"],13)) for key,v in lookup.items()}
    for scope in ["strict","full_map_sensitivity"]:
        ref=maps[f"{scope}_A00_C1"]
        for arm in ["A00","A10","A01","A11"]:
            assert np.array_equal(ref[:,9:13],maps[f"{scope}_{arm}_C1"][:,9:13])
        assert np.array_equal(maps[f"{scope}_A00_C1"][:,3:9],maps[f"{scope}_A10_C1"][:,3:9])
        assert np.array_equal(maps[f"{scope}_A01_C1"][:,3:9],maps[f"{scope}_A11_C1"][:,3:9])
    dump=torch.load(out/"baseline/map/office2_kfgauss.pt",map_location="cpu",weights_only=True)
    gt=np.loadtxt(ROOT/"data/N2/Replica/office2/groundtruth.txt");rows=[];offset=0
    for block in lookup["strict_A11_C1"]["blocks"]:
        index,n=block["kf_idx"],block["count"];kf=dump["keyframes"][index];frame=2*kf["frame_id"]
        registry=np.load(out/f"oracles/kf{index:04d}_registry.npz");use=registry["common_mask"]
        uv=registry["pixel_uv"][use];depth=registry["gt_depth"][use];raw=registry["raw_xyz"][use]
        gt_pose=sim3_from_xyzw([*gt[frame,1:8],1])
        est_pose=metric_placement(sim3_from_xyzw(kf["T_WC"].numpy()),gauge,C)
        local={arm:transform_points(maps[f"strict_{arm}_C1"][offset:offset+n,:3],np.linalg.inv(pose))
               for arm,pose in [("A00",est_pose),("A10",est_pose),("A01",gt_pose),("A11",gt_pose)]}
        ray_error=float(np.max(np.abs(project(local["A11"],K)-uv)))
        z_error=float(np.max(np.abs(local["A11"][:,2]-depth)))
        raw_error=float(np.max(np.abs(local["A00"]-raw*C)))
        local0_error=float(np.max(np.abs(local["A00"]-local["A01"])))
        local1_error=float(np.max(np.abs(local["A10"]-local["A11"])))
        assert ray_error<.001 and max(z_error,raw_error,local0_error,local1_error)<1e-5
        rows.append({"kf_idx":index,"candidates":n,"GT_world_roundtrip_max_reprojection_px":ray_error,
            "GT_Z_roundtrip_max_abs_error_m":z_error,"predicted_local_invariance_max_error_m":local0_error,
            "GT_local_invariance_max_error_m":local1_error,"raw_unit_reexpression_max_error_m":raw_error})
        offset+=n
    assert offset==lookup["strict_A11_C1"]["count"]
    sensitivity=[]
    for factor in [.8,1.25]:
        error=float(np.max(np.abs(maps["strict_A00_C1"]-maps[f"strict_A00_C{factor}"])))
        assert error<1e-6
        sensitivity.append({"C_multiplier":factor,"A00_packed_max_abs_difference":error})
    result={"status":"PASS","actual_packed_RGB_opacity_equal_all_arms":True,
        "actual_world_covariance_equal_for_local_only_interventions":True,"checks":rows,
        "C_A00_invariance":sensitivity,"float32_reprojection_tolerance_px":.001,"float32_local_tolerance_m":1e-5}
    (out/"analysis/packed_map_independence_checks.json").write_text(json.dumps(result,indent=2)+"\n")
    print(f"Packed map invariants: PASS, {offset} strict candidates")


if __name__=="__main__":main()

#!/usr/bin/env python3
"""Freeze native IDs, then construct independent metric A0 maps and controls."""
from datetime import datetime
import csv
import gzip
import json
from pathlib import Path
import shutil
import sys
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1];UP=ROOT/"thirdparty/Splatt3R-SLAM"
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts"),str(UP),str(UP/"scripts"),str(UP/"splatt3r_core")]
from prepare_e2b_run import digest,save_json
from pointmap_contract import (array_hash,backproject_z,build_arms,fit_prefix_gauge,metric_placement,
                              project,sim3_from_xyzw,sim3_parts,transform_points,stratified_subset)
from e1_taxonomy import camera_geometry,depth_masks,resize_depth
from e0b_audit import Audit
from e4_budget import pack_parameters
from run_n1_contract import native_mask,percentiles,pose_from_tum
from splatt3r_slam.splatt3r_utils import prepare_gaussians_local,bake_gaussians_world
from splatt3r_slam.gaussian_ply_codec import decode_gaussians_from_ply
from utils.geometry import build_covariance


def main():
    torch.set_num_threads(2)
    spec_path=ROOT/"configs/a0_office2_factorial.json";spec=json.loads(spec_path.read_text())
    out=ROOT/spec["output"];run=out/"baseline";dest=out/"oracles"
    reg=json.loads((out/"registration.json").read_text());assert reg["specification_file"]==digest(spec_path)
    assert json.loads((run/"qualification.json").read_text())["status"]=="PASS"
    if not torch.cuda.is_available():raise RuntimeError("GPU native-map parity requires host CUDA")
    dest.mkdir(exist_ok=False)
    cfg=json.loads((ROOT/spec["n1_contract"]).read_text());nf=cfg["native_filter"];mask_spec=cfg["common_mask"]
    # Reuse the proven E0b replay through a read-only filename/manifest adapter.
    view=dest/"audit_view";view.mkdir();(view/"map").mkdir()
    for name in ("exports","audit"):(view/name).symlink_to(run/name,target_is_directory=True)
    for suffix in ("_kfgauss.pt","_frames.txt"):(view/"map"/f"office0{suffix}").symlink_to(run/"map"/f"office2{suffix}")
    audit_spec=json.loads((ROOT/"configs/e0b_audit.json").read_text());audit_spec["cases"]["a0"]={"expected_inputs":500}
    save_json(view/"run_manifest.json",{"case":"a0","specification":audit_spec})
    print("Replaying provenance and pose journal",flush=True)
    audit=Audit(view);checks=audit.validate();save_json(dest/"journal_checks.json",checks)
    final_e=[e for e in audit.events if e["kind"]=="snapshot" and e["stage"]=="final"][-1]
    final=torch.load(run/"audit"/final_e["file"],map_location="cpu",weights_only=True)
    dump=torch.load(run/"map/office2_kfgauss.pt",map_location="cpu",weights_only=True)
    poses=np.loadtxt(run/"map/office2_frames.txt");ids=poses[:,0].astype(int)
    data=ROOT/spec["dataset"];gt_rows=np.loadtxt(data/"groundtruth.txt")
    np.testing.assert_array_equal(gt_rows[ids,0],ids)
    gauge,cal_ids=fit_prefix_gauge(poses[:,1:4],gt_rows[ids,1:4],ids,spec["calibration"]["prefix_original_frame_stop_exclusive"])
    C=sim3_parts(gauge)[0]*float(dump["keyframes"][0]["T_WC"].reshape(8)[7])
    save_json(dest/"alignment.json",{"matrix":gauge.tolist(),"global_scale":sim3_parts(gauge)[0],"local_C":C,
        "calibration_original_frame_ids":cal_ids.tolist(),"post_prefix_gt_used_in_fit":False,"pose_revision":final["pose_revision"]})
    camera=json.loads((data.parent/"cam_params.json").read_text())["camera"];K,_,_=camera_geometry(camera)
    sources=[spec_path,Path(__file__),ROOT/"src/pointmap_contract.py",ROOT/"src/e1_taxonomy.py",ROOT/"src/e0b_audit.py",
        ROOT/"src/e4_budget.py",ROOT/"scripts/run_n1_contract.py",UP/"splatt3r_slam/splatt3r_utils.py",UP/"splatt3r_core/utils/geometry.py"]
    for p in sources:
        target=dest/"source"/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    save_json(dest/"source_manifest.json",[digest(p) for p in sources])
    variants=[]
    for scope in ("strict","full_map_sensitivity"):
        for name in ("A00","A10","A01","A11"):
            variants.append({"scope":scope,"arm":name,"C_multiplier":1.,"id":f"{scope}_{name}_C1"})
    for name in ("Z10","Z11"):variants.append({"scope":"strict","arm":name,"C_multiplier":1.,"id":f"strict_{name}_C1"})
    for factor in (.8,1.25):
        for name in ("A00","A10","A01","A11"):
            variants.append({"scope":"strict","arm":name,"C_multiplier":factor,"id":f"strict_{name}_C{factor}"})
    for v in variants:
        v.update(count=0,map_file=str((dest/(v["id"]+".f32")).relative_to(ROOT)),blocks=[])
        (ROOT/v["map_file"]).touch(exist_ok=False)
    baked=[];candidates=[];input_files=[run/"map/office2_kfgauss.pt",run/"map/office2_frames.txt",run/"audit/events.jsonl",
                                     run/"audit"/final_e["file"],data/"groundtruth.txt",data.parent/"cam_params.json"]
    proxy={v["id"]:[] for v in variants}
    with gzip.open(dest/"candidate_registry.csv.gz","wt",newline="") as stream:
        writer=csv.writer(stream);writer.writerow(["candidate_id","kf_idx","original_frame","u","v","native_active","gt_valid","edge","common","post_prefix"])
        for kf,meta,pose in zip(dump["keyframes"],final["metadata"],final["poses"]):
            index,frame=kf["kf_idx"],2*kf["frame_id"];assert frame<1000
            assert torch.equal(kf["T_WC"].reshape(8),pose.reshape(8))
            event=meta["candidate_event"];raw_path=run/"exports/raw_pairs"/(event+".pt")
            raw=torch.load(raw_path,map_location="cpu",weights_only=True)
            assert raw["coordinate_frame"]=="first_source_camera" and raw["source_pair_ids"][0][0]==kf["frame_id"]
            for key in ("means","scales","rotations","sh","opacities","conf"):
                assert torch.equal(kf[key],raw["outputs"][0][key].reshape_as(kf[key])),key
            assert torch.equal(raw["outputs"][0]["means"],raw["outputs"][0]["pts3d"])
            mask=native_mask(kf,nf);h,w=kf["img_shape"];n=h*w;yy,xx=np.indices((h,w));uv=np.column_stack([xx.ravel(),yy.ravel()])
            cids=np.array([f"{event}:self:{j}" for j in range(n)])
            local={key:kf[key] for key in ("means","scales","rotations","sh","opacities","conf")}
            prepared=prepare_gaussians_local(local,kf["img"],h,w,**nf)
            assert torch.equal(prepared[0],kf["means"][mask])
            cov=build_covariance(prepared[1],prepared[2]).numpy()
            rgb=prepared[3].numpy();opacity=prepared[4].numpy()
            cpu_xyz=kf["means"].numpy()[mask];pix=uv[mask];cid=cids[mask]
            cov_all=np.zeros((n,3,3),np.float32);cov_all[mask]=cov
            dp=data/"results"/f"depth{frame:06d}.png";depth=resize_depth(cv2.imread(str(dp),cv2.IMREAD_UNCHANGED).astype(np.float32)/camera["scale"],camera)
            valid,edge=depth_masks(depth,mask_spec);common=mask&valid.ravel()&~edge.ravel();replace=common[mask]
            assert np.isfinite(cpu_xyz).all() and np.isfinite(cov).all() and np.isfinite(rgb).all()
            gt_local=cpu_xyz.astype(float)*C
            gt_local[replace]=backproject_z(pix[replace],depth.ravel()[mask][replace],K)
            gt_pose=pose_from_tum(gt_rows[frame]);raw_pose=sim3_from_xyzw(kf["T_WC"].numpy())
            metric_pose=metric_placement(raw_pose,gauge,C)
            for j in range(n):writer.writerow([cids[j],index,frame,int(uv[j,0]),int(uv[j,1]),int(mask[j]),int(valid.ravel()[j]),int(edge.ravel()[j]),int(common[j]),int(frame>=200)])
            np.savez_compressed(dest/f"kf{index:04d}_registry.npz",native_mask=mask,common_mask=common,pixel_uv=uv,
                raw_xyz=kf["means"].numpy(),gt_depth=depth.ravel(),active_candidate_ids=cid)
            sample=stratified_subset(uv,kf["means"].numpy()[:,2]*C,common,(h,w),index,[8,8],[1.,2.,4.],8)
            active_indexes=np.flatnonzero(mask);sample_in_active=np.searchsorted(active_indexes,sample)
            attrs={"rgb":rgb,"opacity":opacity,"raw_scales":kf["scales"].numpy()[mask],
                   "raw_rotation":kf["rotations"].numpy()[mask],"raw_sh":kf["sh"].numpy()[mask]}
            for factor in (1.,.8,1.25):
                oracle=cpu_xyz.astype(float)*C*factor
                oracle[replace]=gt_local[replace]
                arms=build_arms(cpu_xyz,oracle,raw_pose,gt_pose,gauge,C*factor,cov,cid,replace,attrs)
                predicted_ray_gt_z=oracle.copy()
                predicted_ray_gt_z[replace]=cpu_xyz[replace]/cpu_xyz[replace,2:3]*depth.ravel()[mask][replace,None]
                for v in variants:
                    if v["C_multiplier"]!=factor:continue
                    select=replace.copy() if v["scope"]=="strict" else np.ones(len(cid),bool)
                    if v["scope"]=="strict" and frame<200:select[:]=False
                    if not select.any():continue
                    name=v["arm"]
                    if name in arms:geometry=arms[name]
                    else:
                        from pointmap_contract import transform_covariance
                        placement=arms["A10" if name=="Z10" else "A11"]["placement"]
                        geometry={"world_points_m":transform_points(predicted_ray_gt_z,placement),
                            "world_covariance_m2":transform_covariance(cov*C*C,placement)}
                    packed=pack_parameters(geometry["world_points_m"][select],geometry["world_covariance_m2"][select],rgb[select],opacity[select])
                    with (ROOT/v["map_file"]).open("ab") as f:packed.tofile(f)
                    v["blocks"].append({"kf_idx":index,"count":int(select.sum()),"id_hash":array_hash(cid[select]),
                         "attributes_hashes":{k:array_hash(a[select]) for k,a in attrs.items()},"common_mask_hash":array_hash(common)})
                    v["count"]+=len(packed)
                    s=sample_in_active[select[sample_in_active]]
                    proxy[v["id"]].append(geometry["world_points_m"][s])
                # Exact preservation of original placement, including C sensitivity.
                np.testing.assert_allclose(arms["A00"]["world_points_m"],transform_points(cpu_xyz,gauge@raw_pose),atol=1e-9)
            reproj=np.linalg.norm(project(cpu_xyz[replace],K)-pix[replace],axis=1)
            candidates.append({"kf_idx":index,"original_frame":frame,"event":event,"raw_count":n,"active_count":int(mask.sum()),
                "common_count":int(common.sum()),"post_prefix":frame>=200,"raw_scale":sim3_parts(raw_pose)[0],
                "metric_scale":sim3_parts(metric_pose)[0],"ray_reprojection_error_px":percentiles(reproj),
                "raw_local_depth_abs_error_m":percentiles(np.abs(cpu_xyz[replace,2]*C-depth.ravel()[mask][replace])),
                "common_mask_hash":array_hash(common),"pose_revision":final["pose_revision"]})
            # Factual native-map parity under its original numeric mode.
            import lietorch
            torch.backends.cuda.matmul.allow_tf32=True
            gpu={k:a.cuda() for k,a in local.items()}
            baked.append(tuple(a.cpu() for a in bake_gaussians_world(gpu,kf["img"].cuda(),h,w,lietorch.Sim3(kf["T_WC"].cuda()),**nf)))
            input_files.extend([raw_path,dp]);print(f"Built KF {index}: frame={frame}, common={common.sum()}",flush=True)
    means,tri,rgb,opa=[torch.cat([b[k] for b in baked]) for k in range(4)]
    ply=decode_gaussians_from_ply(run/"map/office2_gaussians.ply",device="cpu")
    torch.testing.assert_close(ply["means"],means,atol=1e-5,rtol=1e-5)
    rc=torch.triu_indices(3,3)
    torch.testing.assert_close(ply["covariances"][:,rc[0],rc[1]],tri,atol=1e-5,rtol=1e-4)
    torch.testing.assert_close(ply["rgb"],rgb,atol=1e-5,rtol=1e-5);torch.testing.assert_close(ply["opacity"],opa,atol=1e-6,rtol=1e-5)
    for scope in ("strict","full_map_sensitivity"):
        group=[v for v in variants if v["scope"]==scope]
        for v in group:assert v["blocks"]==group[0]["blocks"] and v["count"]==group[0]["count"]
    for v in variants:
        assert (ROOT/v["map_file"]).stat().st_size==v["count"]*52
        v["map_hash"]=digest(ROOT/v["map_file"])
        np.save(dest/(v["id"]+"_center_proxy.npy"),np.concatenate(proxy[v["id"]]))
    np.save(dest/"K.npy",K)
    inputs=[digest(p) for p in sorted(set(input_files))]
    save_json(dest/"candidate_manifest.json",candidates)
    save_json(dest/"manifest.json",{"registered_spec":digest(spec_path),"C":C,"gauge":gauge.tolist(),"variants":variants,
        "candidate_manifest":digest(dest/"candidate_manifest.json"),"inputs":inputs,"journal_checks":checks,
        "native_ply_parity":"PASS","native_ply_count":ply["n"],"world_covariance_placement_dependent":True,
        "raw_attributes_frozen":True,"pose_revision":final["pose_revision"],"created_at":datetime.now(ZoneInfo("Asia/Seoul")).isoformat()})
    print(json.dumps({"C":C,"keyframes":len(candidates),"strict_candidates":variants[0]["count"],"native_active":ply["n"],"maps":len(variants)},indent=2))


if __name__=="__main__":main()

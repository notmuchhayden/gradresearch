#!/usr/bin/env python3
"""Verify existing office0 coordinate contracts; never modify a source run."""
from __future__ import annotations

import argparse
from datetime import datetime
import gzip
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import torch
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "thirdparty/Splatt3R-SLAM"
sys.path[:0] = [str(ROOT / "src"), str(UPSTREAM), str(UPSTREAM / "scripts"), str(UPSTREAM / "splatt3r_core")]
from e0b_audit import Audit
from e1_taxonomy import camera_geometry, depth_masks, resize_depth
from pointmap_contract import (array_hash, backproject_z, build_arms, fit_prefix_gauge,
                               metric_placement, project, sim3_from_xyzw, sim3_parts,
                               source_points_in_anchor, stratified_subset,
                               transform_covariance, transform_points)
from utils.geometry import build_covariance


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def digest(path):
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha}


def percentiles(values):
    values = np.asarray(values)
    values = values[np.isfinite(values)]
    return {"n": len(values), "median": float(np.median(values)),
            "p95": float(np.percentile(values, 95)), "max": float(values.max())}


def native_mask(kf, config):
    z = kf["means"][:, 2]
    mask = z > config["depth_min"]
    if mask.any():
        mask &= z <= torch.quantile(z[mask], config["depth_max_percentile"])
    mask &= kf["scales"].max(-1).values < config["max_scale"]
    mask &= kf["conf"].reshape(-1) >= config["min_confidence"]
    mask &= kf["opacities"].reshape(-1) > config["min_opacity"]
    return mask.numpy()


def pose_from_tum(row):
    return sim3_from_xyzw([*row[1:8], 1])


def run(config_path, out, use_gpu):
    torch.set_num_threads(2)
    spec = json.loads(config_path.read_text())
    run_path, dataset = ROOT / spec["baseline"], ROOT / spec["dataset"]
    n0 = json.loads((ROOT / spec["n0_summary"]).read_text())
    for row in n0["frozen_artifact_index"]:
        assert digest(ROOT / row["path"]) == row, f"N0 artifact changed: {row['path']}"
    input_paths = sorted(p for p in run_path.rglob("*") if p.is_file())
    input_paths += [ROOT / spec["n0_summary"], config_path, ROOT / spec["camera"],
                    ROOT / "configs/e0b_audit.json", dataset / "traj.txt", dataset / "groundtruth.txt"]
    data_manifest = json.loads((ROOT / "configs/e0_replica_download_manifest.json").read_text())
    for row in data_manifest["files"]:
        path = ROOT / row["path"]
        actual = digest(path)
        assert actual["sha256"] == row["sha256"] and actual["bytes"] == row["bytes"]
        input_paths.append(path)
    before = [digest(p) for p in sorted(set(input_paths))]
    save(out / "input_manifest.json", before)
    sources = [config_path, ROOT / "scripts/run_n1_contract.py", ROOT / "src/pointmap_contract.py",
               ROOT / "configs/e0b_audit.json",
               ROOT / "tests/test_pointmap_contract.py", ROOT / "src/e0b_audit.py", ROOT / "src/e1_taxonomy.py",
               UPSTREAM / "splatt3r_slam/splatt3r_utils.py", UPSTREAM / "splatt3r_slam/gaussian_ply_codec.py",
               UPSTREAM / "splatt3r_core/utils/geometry.py", UPSTREAM / "scripts/eval_map_geometry.py"]
    for p in sources:
        target = out / "source" / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    save(out / "source_manifest.json", {"files": [digest(p) for p in sources],
         "research_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
         "upstream_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=UPSTREAM, text=True).strip()})

    # The N0 manifest has no E0b 'specification'. Adapt metadata in a new view,
    # leaving the source manifest, events and tensors untouched.
    view = out / "audit_view"
    view.mkdir()
    for name in ("exports", "audit", "map"):
        (view / name).symlink_to(run_path / name, target_is_directory=True)
    save(view / "run_manifest.json", {"case": "short", "specification": json.loads((ROOT / "configs/e0b_audit.json").read_text()),
                                    "source_manifest": str((run_path / "run_manifest.json").relative_to(ROOT))})
    audit = Audit(view)
    journal_checks = audit.validate()
    save(out / "journal_checks.json", journal_checks)
    events = audit.events
    final_event = [e for e in events if e["kind"] == "snapshot" and e["stage"] == "final"][-1]
    final = torch.load(run_path / "audit" / final_event["file"], map_location="cpu", weights_only=True)
    dump = torch.load(run_path / "map/office0_kfgauss.pt", map_location="cpu", weights_only=True)
    assert final["pose_revision"] == final_event["pose_revision"]
    assert len(final["metadata"]) == dump["n"]
    for kf, meta, actual in zip(dump["keyframes"], final["metadata"], final["poses"]):
        assert kf["kf_idx"] == meta["kf_idx"] and kf["frame_id"] == meta["frame_id"]
        assert torch.equal(kf["T_WC"].reshape(8), actual.reshape(8))

    poses = np.loadtxt(run_path / "map/office0_frames.txt")
    gt_rows = np.loadtxt(dataset / "groundtruth.txt")
    ids = poses[:, 0].astype(int)
    np.testing.assert_array_equal(ids, poses[:, 0])
    np.testing.assert_array_equal(gt_rows[ids, 0], ids)
    prefix = spec["alignment"]["prefix_original_frame_stop_exclusive"]
    gauge, calibration_ids = fit_prefix_gauge(poses[:, 1:4], gt_rows[ids, 1:4], ids, prefix)
    a, _, _ = sim3_parts(gauge)
    first_scale = float(dump["keyframes"][0]["T_WC"].reshape(8)[7])
    C = a * first_scale
    # Verify that changing every post-prefix GT position cannot change gauge.
    corrupted = gt_rows[ids, 1:4].copy()
    corrupted[ids >= prefix] += [10000, -5000, 3000]
    other, _ = fit_prefix_gauge(poses[:, 1:4], corrupted, ids, prefix)
    np.testing.assert_array_equal(gauge, other)
    calibration_error = transform_points(poses[ids < prefix, 1:4], gauge) - gt_rows[ids[ids < prefix], 1:4]
    save(out / "alignment_manifest.json", {"gauge_world_raw_to_gt_metric": gauge.tolist(),
         "global_scale_m_per_world_raw": a, "local_C_m_per_raw": C,
         "first_keyframe_raw_scale": first_scale, "calibration_original_frame_ids": calibration_ids.tolist(),
         "post_prefix_gt_not_used_for_fit": True,
         "calibration_position_rmse_m": float(np.sqrt(np.mean(np.sum(calibration_error**2, axis=1)))),
         "gauge_singular_values": np.linalg.svd(poses[ids < prefix, 1:4]-poses[ids < prefix, 1:4].mean(0), compute_uv=False).tolist(),
         "scope": "offline final-revision placement; input poses can include later SLAM backend information",
         "local_unit_rule": spec["alignment"]["local_unit_rule"]})

    camera = json.loads((ROOT / spec["camera"]).read_text())["camera"]
    K, resize_hw, crop = camera_geometry(camera)
    # Cross-check the existing evaluator's K against upstream RGB transformation.
    from splatt3r_slam.splatt3r_utils import resize_img
    from eval_map_geometry import resize_depth_like_rgb
    _, (sw, sh, cw, ch) = resize_img(np.zeros((camera["h"], camera["w"], 3)), 512, return_transformation=True)
    upstream_K = np.array([[camera["fx"]/sw, 0, camera["cx"]/sw-cw],
                           [0, camera["fy"]/sh, camera["cy"]/sh-ch], [0,0,1.]])
    np.testing.assert_allclose(K, upstream_K, atol=1e-12)
    save(out / "camera_manifest.json", {"raw_camera": camera, "resized_hw": list(resize_hw),
         "crop_top_left_height_width": list(crop), "K": K.tolist(),
         "distortion": "none; synthetic pinhole, mapper use_calib=false; no remap",
         "pixel_center_convention": spec["camera_convention"], "depth_definition": "camera Z, metric = uint16 / 6553.5",
         "alternative_half_pixel_K_principal_point_delta": [(512/camera["w"]-1)/2, (resize_hw[0]/camera["h"]-1)/2]})
    registries, samples, arm_rows, branch_rows, sensitivity = [], [], [], [], []
    native_points, native_covariance, active_ids = [], [], []
    gpu_inputs = []
    n_raw = n_common = 0
    with gzip.open(out / "candidate_registry.csv.gz", "wt", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["candidate_id", "anchor_kf", "input_frame", "original_frame", "u", "v", "native_active",
                         "gt_valid", "depth_edge", "common", "prediction_event", "final_pose_revision"])
        for kf, meta in zip(dump["keyframes"], final["metadata"]):
            index, frame = kf["kf_idx"], 2*kf["frame_id"]
            event = meta["candidate_event"]
            raw = torch.load(run_path / "exports/raw_pairs" / f"{event}.pt", map_location="cpu", weights_only=True)
            assert raw["coordinate_frame"] == "first_source_camera" and raw["anchor_frame_id"] == kf["frame_id"]
            assert raw["source_pair_ids"][0][0] == kf["frame_id"]
            assert raw["source_image_ids"] == meta["candidate_sources"]
            for branch, output in enumerate(raw["outputs"]):
                assert torch.equal(output["means"], output["pts3d"])
                branch_rows.append({"anchor_kf":index,"branch":branch,"source_input_frame":raw["source_pair_ids"][0][branch],
                                    "coordinate_frame":"first-source/anchor camera", "mean_pointmap_exact":True,
                                    "primary_included":branch==0})
            assert torch.equal(raw["outputs"][0]["means"].reshape(-1,3),kf["means"])
            for key in ("scales", "rotations", "sh", "opacities", "conf"):
                assert torch.equal(kf[key], raw["outputs"][0][key].reshape_as(kf[key])), key
                assert torch.isfinite(kf[key]).all(), key
            h,w = kf["img_shape"]; n=h*w
            v,u=np.indices((h,w)); uv=np.column_stack([u.ravel(),v.ravel()]).astype(np.int32)
            candidate_ids=np.array([f"{event}:self:{p}" for p in range(n)])
            active=native_mask(kf,spec["native_filter"])
            gt_raw=cv2.imread(str(dataset/"results"/f"depth{frame:06d}.png"),cv2.IMREAD_UNCHANGED)
            depth=resize_depth(gt_raw.astype(np.float32)/camera["scale"],camera)
            np.testing.assert_array_equal(depth,resize_depth_like_rgb(gt_raw.astype(np.float32)/camera["scale"],512))
            valid,edge=depth_masks(depth,spec["common_mask"])
            common=active & valid.ravel() & ~edge.ravel()
            finite=np.isfinite(kf["means"].numpy()).all(1)
            assert finite[active].all(), "Native bake's final finite filter would change candidate IDs"
            q=kf["rotations"]/kf["rotations"].norm(dim=-1,keepdim=True).clamp_min(1e-6)
            cov=build_covariance(kf["scales"],q).numpy()
            assert np.isfinite(cov[active]).all()
            raw_xyz=kf["means"].numpy()
            selected=stratified_subset(uv,raw_xyz[:,2]*C,common,(h,w),spec["subset"]["seed"]+index,
                        spec["subset"]["grid_hw"],spec["subset"]["predicted_depth_bin_edges_m"],spec["subset"]["per_stratum"])
            assert len(selected)>0
            np.testing.assert_array_equal(selected,stratified_subset(uv,raw_xyz[:,2]*C,common,(h,w),spec["subset"]["seed"]+index,
                        spec["subset"]["grid_hw"],spec["subset"]["predicted_depth_bin_edges_m"],spec["subset"]["per_stratum"]))
            np.savez_compressed(out/f"kf{index:04d}_registry.npz",pixel_uv=uv,native_active=active,gt_valid=valid.ravel(),
                depth_edge=edge.ravel(),common=common,sample_pixel_index=selected,raw_xyz=raw_xyz,
                covariance_raw=cov,gt_depth_z_m=depth.ravel())
            for p in range(n):
                writer.writerow([candidate_ids[p],index,kf["frame_id"],frame,int(uv[p,0]),int(uv[p,1]),int(active[p]),
                    int(valid.ravel()[p]),int(edge.ravel()[p]),int(common[p]),event,final["pose_revision"]])
            gt_local=backproject_z(uv[selected],depth.ravel()[selected],K)
            np.testing.assert_allclose(project(gt_local,K),uv[selected],atol=1e-9)
            gt_pose=pose_from_tum(gt_rows[frame]); raw_pose=sim3_from_xyzw(kf["T_WC"].numpy())
            attrs={key:kf[key].numpy()[selected] for key in ("scales","rotations","sh","opacities","conf")}
            # Store the raw attribute tensors; covariance gets the one C^2 unit change.
            arms=build_arms(raw_xyz[selected],gt_local,raw_pose,gt_pose,gauge,C,cov[selected],
                            candidate_ids[selected],common[selected],attrs)
            sample_hash=array_hash(candidate_ids[selected])
            for name,arm in arms.items():
                np.savez_compressed(out/f"kf{index:04d}_{name}_contract.npz",
                    **{k:v for k,v in arm.items() if k!="attributes"}, **{f"attribute_{k}":v for k,v in arm["attributes"].items()})
                arm_rows.append({"kf_idx":index,"arm":name,"count":len(selected),"ids_hash":sample_hash,
                    "common_mask_hash":array_hash(arm["common_mask"]),"local_points_hash":array_hash(arm["local_points_m"]),
                    "placement_hash":array_hash(arm["placement"]),"covariance_local_hash":array_hash(arm["local_covariance_m2"]),
                    "attribute_hashes":{k:array_hash(v) for k,v in arm["attributes"].items()},
                    "placement_scale":sim3_parts(arm["placement"])[0]})
            expected=transform_points(transform_points(raw_xyz[selected],raw_pose),gauge)
            error=np.abs(arms["A00"]["world_points_m"]-expected).max()
            np.testing.assert_allclose(arms["A00"]["world_points_m"],expected,atol=1e-9)
            restored=transform_points(arms["A00"]["world_points_m"],np.linalg.inv(metric_placement(raw_pose,gauge,C)))/C
            np.testing.assert_allclose(restored,raw_xyz[selected],atol=1e-9)
            roundtrip=transform_points(transform_points(gt_local,gt_pose),np.linalg.inv(gt_pose))
            np.testing.assert_allclose(roundtrip,gt_local,atol=1e-9)
            np.testing.assert_allclose(project(roundtrip,K),uv[selected],atol=1e-9)
            # Show gauge dependence without computing/tuning oracle GT errors.
            for multiplier in spec["alignment"]["sensitivity_C_multipliers"]:
                alt=build_arms(raw_xyz[selected],gt_local,raw_pose,gt_pose,gauge,C*multiplier,cov[selected],
                               candidate_ids[selected],common[selected],attrs)
                np.testing.assert_allclose(alt["A00"]["world_points_m"],expected,atol=1e-9)
                np.testing.assert_allclose(alt["A00"]["world_covariance_m2"],arms["A00"]["world_covariance_m2"],atol=1e-9)
                sensitivity.append({"kf_idx":index,"C_multiplier":multiplier,
                    "A00_mean_max_abs_change_m":float(np.max(np.abs(alt["A00"]["world_points_m"]-arms["A00"]["world_points_m"]))),
                    "A01_position_change_m":percentiles(np.linalg.norm(alt["A01"]["world_points_m"]-arms["A01"]["world_points_m"],axis=1)),
                    "note":"Gauge sensitivity only; not a comparison of GT reconstruction errors"})
            reproj=np.linalg.norm(project(raw_xyz[common],K)-uv[common],axis=1)
            row={"kf_idx":index,"original_frame":frame,"calibration_anchor":frame<prefix,
                 "event_id":event,"pose_revision":final["pose_revision"],"fused_ancestry":meta["fused"]["status"],
                 "raw_attributes_match_KF_dump":True,
                 "raw_count":n,"native_active":int(active.sum()),"valid_gt":int(valid.sum()),
                 "common_count":int(common.sum()),"sample_count":len(selected),
                 "common_mask_hash":array_hash(common),"sample_ids_hash":sample_hash,
                 "raw_pose_scale":sim3_parts(raw_pose)[0],"metric_pose_scale":sim3_parts(metric_placement(raw_pose,gauge,C))[0],
                 "predicted_ray_reprojection_error_px":percentiles(reproj),
                 "A00_unit_reexpression_max_abs_error_m":float(error)}
            registries.append(row)
            native_points.append(transform_points(raw_xyz[active],raw_pose))
            native_covariance.append(transform_covariance(cov[active],raw_pose))
            active_ids.extend(candidate_ids[active].tolist())
            gpu_inputs.append((kf,active,cov,raw_pose))
            samples.append({"kf_idx":index,"sampled_ids":candidate_ids[selected].tolist(),"sampled_pixel_indices":selected.tolist()})
            n_raw+=n; n_common+=int(common.sum())
            # The real cross-view pixel branch is a SECONDARY relative-pose oracle.
            source_frame=2*raw["source_pair_ids"][0][1]
            source_depth=resize_depth(cv2.imread(str(dataset/"results"/f"depth{source_frame:06d}.png"),cv2.IMREAD_UNCHANGED).astype(np.float32)/camera["scale"],camera)
            ok=np.flatnonzero(np.isfinite(source_depth.ravel()) & (source_depth.ravel()>0))[::1024]
            source_local=backproject_z(uv[ok],source_depth.ravel()[ok],K)
            source_pose=pose_from_tum(gt_rows[source_frame])
            anchor_local=source_points_in_anchor(source_local,source_pose,gt_pose)
            np.testing.assert_allclose(transform_points(anchor_local,gt_pose),transform_points(source_local,source_pose),atol=1e-9)
    save(out/"candidate_manifest.json",registries)
    save(out/"sample_manifest.json",samples)
    save(out/"arm_invariants.json",arm_rows)
    save(out/"branch_contract.json",branch_rows)
    save(out/"gauge_sensitivity.json",sensitivity)
    save(out/"active_ply_candidate_ids.json",active_ids)

    gpu_report={"status":"NOT_RUN"}
    if use_gpu:
        assert torch.cuda.is_available(), "Run --gpu in a GPU-visible context"
        from splatt3r_slam.splatt3r_utils import prepare_gaussians_local,bake_gaussians_world,_sim3_to_4x4
        from splatt3r_slam.gaussian_ply_codec import decode_gaussians_from_ply
        import lietorch
        baked=[]; precision_rows=[]
        for kf,mask,cov,raw_pose in gpu_inputs:
            local={k:kf[k].to("cuda") for k in ("means","scales","rotations","sh","opacities","conf")}
            image=kf["img"].to("cuda"); hw=kf["img_shape"]
            prepared=prepare_gaussians_local(local,image,*hw,**spec["native_filter"])
            assert torch.equal(prepared[0].cpu(),kf["means"][mask])
            assert torch.equal(prepared[4].cpu(),kf["opacities"].reshape(-1)[mask])
            T=lietorch.Sim3(kf["T_WC"].to("cuda"))
            matrix=_sim3_to_4x4(T)[0].cpu().numpy()
            np.testing.assert_allclose(matrix,raw_pose,atol=1e-6)
            torch.backends.cuda.matmul.allow_tf32=False
            exact=bake_gaussians_world(local,image,*hw,T,**spec["native_filter"])
            expected=transform_points(kf["means"].numpy()[mask],raw_pose)
            np.testing.assert_allclose(exact[0].cpu().numpy(),expected,atol=1e-5,rtol=1e-6)
            rc=torch.triu_indices(3,3)
            expected_cov=transform_covariance(cov[mask],raw_pose)
            np.testing.assert_allclose(exact[1].cpu().numpy(),expected_cov[:,rc[0],rc[1]],atol=1e-5,rtol=1e-5)
            precision_rows.append({"kf_idx":kf["kf_idx"],"candidate_mask_matches_upstream":True,
                "mean_max_abs_error_without_TF32":float(np.max(np.abs(exact[0].cpu().numpy()-expected)))})
            torch.backends.cuda.matmul.allow_tf32=True
            baked.append(bake_gaussians_world(local,image,*hw,T,**spec["native_filter"]))
        means,tri,rgb,opacity=[torch.cat([b[k] for b in baked]) for k in range(4)]
        persisted=decode_gaussians_from_ply(run_path/"map/office0_gaussians.ply",device="cuda")
        assert len(means)==persisted["n"]==len(active_ids)
        torch.testing.assert_close(persisted["means"],means,atol=1e-5,rtol=1e-5)
        torch.testing.assert_close(persisted["covariances"][:,rc[0],rc[1]],tri,atol=1e-5,rtol=1e-4)
        torch.testing.assert_close(persisted["rgb"],rgb,atol=1e-5,rtol=1e-5)
        torch.testing.assert_close(persisted["opacity"],opacity,atol=1e-6,rtol=1e-5)
        gpu_report={"status":"PASS","device":torch.cuda.get_device_name(0),"active_ply_count":persisted["n"],
            "PLY_candidate_order_verified":True,"PLY_native_bake_TF32_enabled":True,
            "mean_PLY_max_abs_error":float((persisted["means"]-means).abs().max()),
            "contract_float64_vs_gpu_float32":precision_rows,
            "limit":"GPU verification allocations are not full mapping resource measurements"}
    save(out/"gpu_parity.json",gpu_report)
    after=[digest(ROOT/row["path"]) for row in before]
    assert before==after,"Input mutated"
    save(out/"preservation.json",{"status":"PASS","input_files_rehashed":len(before),"unchanged":True})
    result={"status":"PASS" if use_gpu else "INCOMPLETE","stage":"N1","source_run":spec["baseline"],
            "scope":"development contract only; no novel-scene A0 result",
            "raw_candidates":n_raw,"native_active":len(active_ids),"common_candidates":n_common,
            "sample_candidates":sum(r["sample_count"] for r in registries),"keyframes":len(registries),
            "journal_checks":journal_checks,"calibration_prefix_stop_exclusive":prefix,
            "global_scale":a,"local_C":C,"camera_K":K.tolist(),"candidate_checks":registries,"gpu":gpu_report,
            "input_files_preserved":len(before),"real_data_no_leakage_checks":"PASS",
            "next":"A0 protocol registration on a new scene; these dev arrays are QA only",
            "interpretation_limits":["Local oracle replaces both Z-depth and GT-calibrated ray direction.",
                "C/gauge defines a conditional factorization, not unique causal attribution.",
                "Final-revision backend poses make this an offline diagnostic.",
                "Source GT validity/edge masks do not certify target-view visibility.",
                "No new scene or correction efficacy has been evaluated."]}
    save(out/"result.json",result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",default="configs/n1_coordinate_contract.json")
    parser.add_argument("--output")
    parser.add_argument("--gpu",action="store_true")
    args=parser.parse_args()
    config_path=ROOT/args.config
    spec=json.loads(config_path.read_text())
    out=(ROOT/(args.output or spec["output"])).resolve()
    if not out.is_relative_to(ROOT/"results/N1_coordinate_contract"):
        parser.error("Output must be inside results/N1_coordinate_contract")
    out.mkdir(parents=True,exist_ok=False)
    started=datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    try:
        result=run(config_path,out,args.gpu)
    except Exception:
        save(out/"failure.json",{"status":"FAIL","traceback":traceback.format_exc()})
        raise
    save(out/"execution.json",{"started_at":started,"finished_at":datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
                               "command":sys.argv,"python":sys.version,"torch":torch.__version__})
    print(json.dumps({k:result[k] for k in ("status","raw_candidates","native_active","common_candidates","sample_candidates","global_scale","local_C")},indent=2))
    return 0 if result["status"]=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())

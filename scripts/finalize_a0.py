#!/usr/bin/env python3
"""Shared-denominator contrasts, sensitivity and auditable A0 result tables."""
from datetime import datetime
import csv
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
from prepare_e2b_run import digest,save_json
from a0_metrics import common_covered_metrics,factorial
from e1_taxonomy import camera_geometry,depth_masks,resize_depth
from pointmap_contract import sim3_parts,transform_points


def write_csv(path,rows):
    with path.open("w",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def main():
    cfg=ROOT/"configs/a0_office2_factorial.json";spec=json.loads(cfg.read_text());out=ROOT/spec["output"];evaluation=out/"evaluation"
    dest=out/"analysis";dest.mkdir(exist_ok=False)
    complete=json.loads((evaluation/"completion.json").read_text())
    for row in complete["metric_files"]:assert digest(ROOT/row["path"])==row
    oracle=json.loads((out/"oracles/manifest.json").read_text())
    assert oracle["registered_spec"]==digest(cfg)
    results={v["id"]:json.loads((evaluation/v["id"]/"metrics.json").read_text()) for v in oracle["variants"]}
    dataset=ROOT/spec["dataset"];camera=json.loads((dataset.parent/"cam_params.json").read_text())["camera"]
    mask_spec=json.loads((ROOT/spec["n1_contract"]).read_text())["common_mask"]
    depth={};valid={};edge={}
    for frame in range(201,1000,2):
        d=resize_depth(cv2.imread(str(dataset/"results"/f"depth{frame:06d}.png"),cv2.IMREAD_UNCHANGED).astype(np.float32)/camera["scale"],camera)
        depth[frame]=d;valid[frame],edge[frame]=depth_masks(d,mask_spec)

    def shared_group(name,variant_ids,frames):
        arrays={key:(np.load(evaluation/key/"depth.npy",mmap_mode="r"),np.load(evaluation/key/"covered.npy",mmap_mode="r")) for key in variant_ids}
        indices={key:{f:i for i,f in enumerate(results[key]["frame_ids"])} for key in variant_ids}
        rows=[];per_frame=[];bins={}
        for frame in frames:
            pred={key:arrays[key][0][indices[key][frame]] for key in variant_ids}
            covered={key:arrays[key][1][indices[key][frame]] for key in variant_ids}
            interior=valid[frame]&~edge[frame]
            mask,metrics=common_covered_metrics(pred,covered,depth[frame],interior)
            per_frame.append({"frame":frame,"common_pixels":int(mask.sum()),"gt_interior_pixels":int(interior.sum()),
                              "mae_m":{key:m["mae_m"] for key,m in metrics.items()},"absrel":{key:m["absrel"] for key,m in metrics.items()}})
            for key,m in metrics.items():rows.append({"frame":frame,"variant":key,**m})
            for lo,hi in zip(spec["evaluation"]["depth_bins_m"][:-1],spec["evaluation"]["depth_bins_m"][1:]):
                b=f"{lo}-{hi}";take=mask&(depth[frame]>=lo)&(depth[frame]<hi)
                if take.any():
                    bins.setdefault(b,{k:[] for k in variant_ids})
                    for key in variant_ids:bins[b][key].append(float(np.abs(pred[key][take]-depth[frame][take]).mean()))
        summary={key:{"common_covered_mae_m":float(np.mean([r["mae_m"][key] for r in per_frame if r["mae_m"][key] is not None])),
                      "common_covered_absrel":float(np.mean([r["absrel"][key] for r in per_frame if r["absrel"][key] is not None]))} for key in variant_ids}
        output={"name":name,"frames":len(frames),"frames_with_nonempty_common_mask":sum(r["common_pixels"]>0 for r in per_frame),
                "common_pixels_per_frame":{"min":min(r["common_pixels"] for r in per_frame),"mean":float(np.mean([r["common_pixels"] for r in per_frame]))},
                "mean_common_fraction_of_gt_interior":float(np.mean([r["common_pixels"]/r["gt_interior_pixels"] for r in per_frame])),
                "summary":summary,"per_frame":per_frame,"common_depth_bin_mae_m":{b:{key:float(np.mean(v)) for key,v in values.items()} for b,values in bins.items()}}
        save_json(dest/(name+".json"),output);write_csv(dest/(name+".csv"),rows)
        return output

    frames=list(range(201,1000,2));names=["A00","A10","A01","A11"]
    groups={scope:shared_group(scope+"_common4",[f"{scope}_{arm}_C1" for arm in names],frames)
            for scope in ["strict","full_map_sensitivity"]}
    auxiliary=shared_group("strict_aux_common6",[f"strict_{arm}_C1" for arm in names+["Z10","Z11"]],frames)
    sens_ids=[f"strict_{arm}_C{factor}" for factor in [1,.8,1.25] for arm in names]
    sensitivity=shared_group("C_sensitivity_common12",sens_ids,spec["evaluation"]["surface_fusion_original_frame_ids"])
    effects=[];table=[]
    for scope in groups:
        errors={arm:groups[scope]["summary"][f"{scope}_{arm}_C1"]["common_covered_mae_m"] for arm in names}
        effect={"scope":scope,"error_metric":"common-covered interior depth MAE (m)",**factorial(errors)}
        effect.update(delta_local_given_GT_placement=errors["A01"]-errors["A11"],delta_placement_given_GT_local=errors["A10"]-errors["A11"])
        effects.append(effect)
        effects.append({"scope":scope,"error_metric":"observed-region TSDF sample Chamfer (m)",
                        **factorial({a:results[f"{scope}_{a}_C1"]["surface"]["chamfer_m"] for a in names}),
                        "delta_local_given_GT_placement":None,"delta_placement_given_GT_local":None})
        for arm in names:
            r=results[f"{scope}_{arm}_C1"];s=r["summary"];surf=r["surface"]
            table.append({"scene":"office2","scope":scope,"arm":arm,"candidates":r["count"],
                "common_covered_MAE_m":errors[arm],"own_covered_interior_MAE_m":s["interior_mae_m"],
                "own_covered_all_valid_MAE_m":s["mae_m"],"depth_coverage":s["coverage"],"correct_depth_coverage":s["correct_coverage"],
                "surface_accuracy_m":surf["accuracy_m"],"surface_completion_distance_m":surf["completion_m"],
                "surface_completion_5cm":surf["completion_ratio_5cm"],"sample_chamfer_m":surf["chamfer_m"],
                "PSNR_dB":s["psnr_db"],"SSIM":s["ssim"]})
    write_csv(dest/"A0_four_arms.csv",table);write_csv(dest/"A0_effects.csv",effects)
    sensitivity_effects=[]
    for factor in [1,.8,1.25]:
        e={a:sensitivity["summary"][f"strict_{a}_C{factor}"]["common_covered_mae_m"] for a in names}
        sensitivity_effects.append({"C_multiplier":factor,"errors":e,**factorial(e)})
    save_json(dest/"C_sensitivity_effects.json",sensitivity_effects)
    aux_errors={a:auxiliary["summary"][f"strict_{a}_C1"]["common_covered_mae_m"] for a in names+["Z10","Z11"]}
    aux={"errors_common6":aux_errors,"ray_preserving_Z_gain_estimated_placement":aux_errors["A00"]-aux_errors["Z10"],
         "ray_preserving_Z_gain_GT_placement":aux_errors["A01"]-aux_errors["Z11"],"all_GT_geometry_vs_GT_Z_remaining_ray_effect":aux_errors["Z11"]-aux_errors["A11"]}
    save_json(dest/"ray_preserving_controls.json",aux)
    # Independent GT-mesh vertex proxy; deliberately separate from rendered surface.
    n2=json.loads((ROOT/spec["n2_manifest"]).read_text());mesh_path=next(r["triangulated_mesh"] for r in n2["scenes"] if r["scene"]=="office2")
    mesh=np.load(ROOT/mesh_path);tree=cKDTree(mesh["vertices"]);proxy=[]
    for v in oracle["variants"]:
        points=np.load(out/"oracles"/(v["id"]+"_center_proxy.npy"));d,_=tree.query(points,workers=2)
        proxy.append({"variant":v["id"],"points":len(points),"median_m":float(np.median(d)),"p95_m":float(np.percentile(d,95)),"mean_m":float(d.mean())})
    save_json(dest/"Gaussian_center_mesh_vertex_proxy.json",proxy)
    # Pose diagnostics retain the one prefix gauge; no post-prefix refitting.
    trajectory=np.loadtxt(out/"baseline/map/office2_frames.txt");gt=np.loadtxt(dataset/"groundtruth.txt");ids=trajectory[:,0].astype(int)
    gauge=np.asarray(oracle["gauge"]);_,Q,_=sim3_parts(gauge)
    t=transform_points(trajectory[:,1:4],gauge);R=Q@Rotation.from_quat(trajectory[:,4:8]).as_matrix();G=Rotation.from_quat(gt[ids,4:8]).as_matrix()
    angle=Rotation.from_matrix(R.transpose(0,2,1)@G).magnitude()*180/np.pi
    trans=np.linalg.norm(t-gt[ids,1:4],axis=1);relative_rot=Rotation.from_matrix((R[:-1].transpose(0,2,1)@R[1:]).transpose(0,2,1)@(G[:-1].transpose(0,2,1)@G[1:])).magnitude()*180/np.pi
    pred_relative=np.einsum('nij,nj->ni',R[:-1].transpose(0,2,1),np.diff(t,axis=0))
    gt_relative=np.einsum('nij,nj->ni',G[:-1].transpose(0,2,1),np.diff(gt[ids,1:4],axis=0))
    pose_metrics={}
    for region,m in [("calibration",ids<200),("post_prefix",ids>=200),("all",np.ones(len(ids),bool))]:
        pose_metrics[region]={"poses":int(m.sum()),"ATE_RMSE_m":float(np.sqrt(np.mean(trans[m]**2))),
            "orientation_median_deg":float(np.median(angle[m])),"orientation_p95_deg":float(np.percentile(angle[m],95))}
    pose_metrics["consecutive_input_RPE"]={"translation_RMSE_m":float(np.sqrt(np.mean(np.sum((pred_relative-gt_relative)**2,axis=1)))),
                                             "rotation_median_deg":float(np.median(relative_rot))}
    candidate=json.loads((out/"oracles/candidate_manifest.json").read_text())
    pose_metrics["keyframe_metric_scales"]=[{"kf_idx":r["kf_idx"],"original_frame":r["original_frame"],"scale":r["metric_scale"]} for r in candidate]
    save_json(dest/"pose_scale_metrics.json",pose_metrics)
    e=effects[0];denom=abs(e["delta_local"])+abs(e["delta_placement"])
    large=abs(e["interaction"])>=spec["diagnostic_decision_rule"]["large_interaction_fraction_of_abs_contrasts"]*denom
    decision={"status":"REVISE","reason":"Strong factorial interaction and/or no robust single-factor dominance; no correction efficacy GO",
        "large_interaction":bool(large),"single_scene_only":True,"scope":"office2 diagnostic only",
        "next":"Inspect local-unit/KF-scale/rigid-pose coupling in A1, then reproduce the frozen A0 protocol on office3 before choosing a correction method",
        "depth_correction_authorized_by_this_result":False,"universal_error_contribution_percentages":False}
    # This experiment may yield a simple dominant effect on other scenes, but
    # never turn a strong-interaction or antagonistic result into a GO.
    if not large and e["delta_local"]>0 and e["delta_placement"]>0:
        decision["reason"]="Both factors improve but method selection still needs cross-scene and observability checks"
    save_json(dest/"decision.json",decision)
    # Verify all immutable input/map hashes again after GPU evaluation.
    for row in oracle["inputs"]:assert digest(ROOT/row["path"])==row
    for v in oracle["variants"]:assert digest(ROOT/v["map_file"])==v["map_hash"]
    save_json(dest/"preservation.json",{"status":"PASS","source_inputs_rehashed":len(oracle["inputs"]),"map_files_rehashed":len(oracle["variants"]),"unchanged":True})
    baseline_files=[digest(p) for folder in ["exports","audit","map"] for p in sorted((out/"baseline"/folder).rglob("*")) if p.is_file()]
    save_json(dest/"baseline_artifact_manifest.json",baseline_files)
    summary={"experiment":"A0 office2 Pointmap x Pose factorial oracle","date":"2026-10-26","execution_status":"COMPLETE",
        "diagnostic_decision":decision,"specification":digest(cfg),"table":table,"effects":effects,"C_sensitivity_effects":sensitivity_effects,
        "ray_controls":aux,"center_proxy":proxy,"pose_metrics":pose_metrics,
        "primary_common_support":{k:v for k,v in groups["strict"].items() if k not in ["per_frame"]},
        "baseline_qualification":json.loads((out/"baseline/qualification.json").read_text()),
        "unit_C":oracle["C"],"candidate_manifest":candidate,"native_active":oracle["native_ply_count"],
        "tests":{"A0_metric_tests":6,"N1_coordinate_tests":12},
        "report":"docs/experiments/A0_office2_factorial_results.md","output":spec["output"],
        "office3_predictions_run":False,"office4_predictions_run":False,
        "limitations":["One scene; no scene-level confidence interval or generalization claim.","All contrasts conditional on fixed local-unit/gauge contract.",
            "Local oracle changes GT ray and Z-depth; Z controls keep predicted rays.","No appearance/covariance refiner; P changes covariance through its world transform.",
            "Full-map sensitivity retains non-common boundary/invalid-source candidates unchanged in local geometry.",
            "TSDF samples approximate observed-region surface; Gaussian centers are separate nearest-vertex proxies.","LPIPS not computed; no runtime improvement claim."]}
    save_json(dest/"results.json",summary)
    save_json(dest/"source_manifest.json",[digest(Path(__file__)),digest(ROOT/"src/a0_metrics.py")])
    print(json.dumps({"strict_errors":{r['arm']:r['common_covered_MAE_m'] for r in table if r['scope']=='strict'},"effect":effects[0],"decision":decision},indent=2))


if __name__=="__main__":main()

#!/usr/bin/env python3
"""Offline integrity and GT-only QA for the preregistered N2 data split."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback
import zlib
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from plyfile import PlyData,PlyElementParseError
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from dataset_contract import cross_view_gt_depth,frame_split,triangulate_faces,validate_poses
from e1_taxonomy import camera_geometry,depth_masks,resize_depth
from pointmap_contract import backproject_z,project,transform_points


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+"\n")


def digest(path):
    with path.open("rb") as stream:sha=hashlib.file_digest(stream,"sha256").hexdigest()
    return {"path":str(path.relative_to(ROOT)),"bytes":path.stat().st_size,"sha256":sha}


def validate(out,registration_path,selected_scene=None):
    cv2.setNumThreads(1)
    registration=json.loads(registration_path.read_text())
    spec_path=ROOT/"configs/n2_dataset_registration.json"
    assert registration==json.loads(spec_path.read_text()),"Registration changed after acquisition"
    acquisition=registration_path.parent
    prereg=json.loads((acquisition/"preregistration.json").read_text())
    assert prereg["before_acquisition"] and prereg["new_scene_directories_absent"]
    assert prereg["registration_sha256"]==digest(spec_path)["sha256"]
    mesh_spec_path=ROOT/"configs/n2_mesh_qa_amendment_A1.json"
    mesh_registration=acquisition/mesh_spec_path.name
    assert mesh_registration.read_bytes()==mesh_spec_path.read_bytes()
    mesh_gate=json.loads(mesh_spec_path.read_text())["changes"]
    amendment=json.loads((acquisition/"amendment_A1_registration.json").read_text())
    assert amendment["before_geometry_decode_or_gt_analysis"]
    assert amendment["sha256"]==digest(mesh_spec_path)["sha256"]
    parser_amendment=ROOT/"configs/n2_mesh_qa_amendment_A2.json"
    assert (acquisition/parser_amendment.name).read_bytes()==parser_amendment.read_bytes()
    scene_names=[r["scene"] for r in registration["scenes"]]
    assert len(set(scene_names))==len(scene_names)==3
    assert not set(scene_names)&set(registration["previously_used_scenes"])
    assert [r["role"] for r in registration["scenes"]]==["diagnostic_development","validation","sealed_final_test"]
    if selected_scene is not None:
        assert selected_scene in scene_names
        scene_names=[selected_scene]
    scene_specs=[row for row in registration["scenes"] if row["scene"] in scene_names]
    root=ROOT/registration["dataset_root"]
    camera=json.loads((root/"cam_params.json").read_text())["camera"]
    assert camera==json.loads((ROOT/"data/Replica/cam_params.json").read_text())["camera"]
    K,resize_hw,crop=camera_geometry(camera)
    raw_K=np.array([[camera["fx"],0,camera["cx"]],[0,camera["fy"],camera["cy"]],[0,0,1.]])
    stop=registration["frame_interval"][1]
    prefix=registration["calibration"]["original_frame_interval"][1]
    split=frame_split(stop,prefix)
    assert not (split["model_input_rgb"]&split["primary_eval_view"]).any()
    qa=registration["qa"]
    downloaded={}
    for name in scene_names:
        manifest=json.loads((acquisition/f"{name}_download_manifest.json").read_text())
        assert manifest["archive_bytes"]==registration["expected_archive_bytes"]
        assert manifest["archive_etag"]==registration["expected_archive_etag"]
        assert manifest["scene"]==name and manifest["frame_stop_exclusive"]==stop and not manifest["rgb_only"]
        for row in manifest["files"]:
            if row["path"] in downloaded:assert downloaded[row["path"]]==row
            downloaded[row["path"]]=row
    meshes=json.loads((acquisition/"mesh_download_manifest.json").read_text())
    assert meshes["archive_bytes"]==registration["expected_archive_bytes"]
    assert meshes["archive_etag"]==registration["expected_archive_etag"]
    for row in meshes["files"]:
        if row["scene"] in scene_names:
            downloaded[row["path"]]={k:v for k,v in row.items() if k!="scene"}

    def check(row):
        path=ROOT/row["path"]
        assert path.resolve().is_relative_to(root.resolve()),row["path"]
        data=path.read_bytes()
        assert len(data)==row["bytes"] and hashlib.sha256(data).hexdigest()==row["sha256"],str(path)
        assert zlib.crc32(data)==row["zip_crc"],str(path)
        result={"path":row["path"],"bytes":len(data),"sha256":row["sha256"],"zip_crc":row["zip_crc"]}
        if path.suffix in (".jpg",".png"):
            image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_UNCHANGED)
            assert image is not None,str(path)
            assert image.shape[:2]==tuple(qa_hw),str(path)
            if path.suffix==".jpg":
                assert image.shape==(camera["h"],camera["w"],3) and image.dtype==np.uint8,str(path)
                result["modality"]="RGB"
            else:
                assert image.ndim==2 and image.dtype==np.uint16,str(path)
                lo,hi=qa["gt_valid_range_m"]
                valid=(image>=lo*camera["scale"])&(image<=hi*camera["scale"])
                fraction=float(valid.mean())
                assert fraction>=qa["min_per_frame_valid_depth_fraction"],str(path)
                sample=np.flatnonzero(valid.ravel())[::50000]
                v,u=np.divmod(sample,camera["w"])
                pixels=np.column_stack([u,v])
                local=backproject_z(pixels,image.ravel()[sample].astype(float)/camera["scale"],raw_K)
                error=float(np.max(np.abs(project(local,raw_K)-pixels)))
                assert error<=qa["self_projection_atol_px"]
                result.update(modality="GT_Z_DEPTH",valid_fraction=fraction,self_projection_max_abs_error_px=error)
        return result

    qa_hw=registration["camera_contract"]["expected_rgb_hw"]
    verified=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for index,row in enumerate(pool.map(check,[downloaded[p] for p in sorted(downloaded)]),1):
            verified.append(row)
            if index%500==0:print(f"Integrity/decode: {index}/{len(downloaded)}",flush=True)
    save(out/"verified_files.json",verified)

    def depth(scene,frame):
        raw=cv2.imread(str(root/scene/"results"/f"depth{frame:06d}.png"),cv2.IMREAD_UNCHANGED)
        return resize_depth(raw.astype(np.float32)/camera["scale"],camera)

    results=[];derived=[]
    for scene_spec in scene_specs:
        scene,role=scene_spec["scene"],scene_spec["role"]
        print(f"Scene QA: {scene} ({role})",flush=True)
        images=root/scene/"results"
        assert sorted(p.name for p in images.glob("frame*.jpg"))==[f"frame{i:06d}.jpg" for i in range(stop)]
        assert sorted(p.name for p in images.glob("depth*.png"))==[f"depth{i:06d}.png" for i in range(stop)]
        poses=np.loadtxt(root/scene/"traj.txt").reshape(-1,4,4)
        pose_report=validate_poses(poses,stop,qa["pose_rotation_atol"])
        calibration=poses[split["original_frame_id"][split["calibration_pose"]],:3,3]
        centered=calibration-calibration.mean(0)
        singular=np.linalg.svd(centered,compute_uv=False)
        span=float(np.max(np.linalg.norm(calibration-calibration[0],axis=1)))
        assert span>=registration["calibration"]["min_gt_prefix_position_span_m"]
        assert singular[1]>=registration["calibration"]["min_gt_prefix_second_singular_value_m"]
        # Derived TUM file has exactly the acquired image ordinals, no assumed FPS.
        gt_path=root/scene/"groundtruth.txt"
        quaternions=Rotation.from_matrix(poses[:stop,:3,:3]).as_quat()
        gt=np.column_stack([np.arange(stop),poses[:stop,:3,3],quaternions])
        lines="".join(" ".join(f"{v:.12f}" for v in row)+"\n" for row in gt)
        if gt_path.exists():assert gt_path.read_text()==lines,"Existing derived GT preserved"
        else:gt_path.write_text(lines)
        gt_reload=np.loadtxt(gt_path)
        np.testing.assert_allclose(gt_reload[:,1:4],poses[:stop,:3,3],atol=1e-11)
        np.testing.assert_allclose(Rotation.from_quat(gt_reload[:,4:8]).as_matrix(),poses[:stop,:3,:3],atol=1e-7)
        derived.append(digest(gt_path))
        csv_path=out/f"{scene}_frame_split.csv"
        with csv_path.open("w",newline="") as stream:
            writer=csv.writer(stream)
            writer.writerow(["scene","role",*split,"timestamp_definition"])
            for i in range(stop):
                writer.writerow([scene,role,*[int(split[k][i]) for k in split],"original_frame_ordinal"])
        frame_rows=[r for r in verified if f"/{scene}/results/" in r["path"]]
        rgb=[r for r in frame_rows if r["modality"]=="RGB"]
        depths=[r for r in frame_rows if r["modality"]=="GT_Z_DEPTH"]
        assert len(rgb)==len(depths)==stop
        # A supplied archive mesh is checked structurally for all roles.
        try:
            mesh=PlyData.read(root/f"{scene}_mesh.ply",mmap="r",known_list_len={"face":{"vertex_indices":4}})
        except PlyElementParseError:
            mesh=PlyData.read(root/f"{scene}_mesh.ply",mmap="r")
        vertices=np.column_stack([mesh["vertex"][key] for key in ("x","y","z")])
        faces=mesh["face"]["vertex_indices"]
        assert len(vertices)>0 and np.isfinite(vertices).all()
        triangles,arity_counts=triangulate_faces(faces,len(vertices))
        mesh_report={"status":"PASS","vertices":len(vertices),"source_polygon_faces":len(faces),
                     "face_arity_counts":arity_counts,"derived_triangles":len(triangles),"finite_vertices_and_valid_indices":True}
        derived_mesh=out/f"{scene}_mesh_triangles.npz"
        np.savez_compressed(derived_mesh,vertices=vertices,triangles=triangles)
        derived.append(digest(derived_mesh))
        mesh_report["derived_mesh"]=str(derived_mesh.relative_to(ROOT))
        cross=[]
        if scene_spec["cross_view_gt_qa"]:
            for source,target in qa["cross_view_pairs"]:
                row=cross_view_gt_depth(depth(scene,source),depth(scene,target),poses[source],poses[target],K,qa)
                row.update(source_original_frame=source,target_original_frame=target)
                cross.append(row)
                # Persist failed QA too; never drop the pair or tune the threshold.
                save(out/f"{scene}_cross_view_qa.json",cross)
                assert row["status"]=="PASS",f"GT cross-view QA failed: {scene} {source}->{target}: {row}"
            gt_world=[]
            for frame in [0,200,800]:
                d=depth(scene,frame);valid,edge=depth_masks(d,qa["edge_mask"])
                y,x=np.indices(d.shape);keep=valid&~edge&(y%32==0)&(x%32==0)
                local=backproject_z(np.column_stack([x[keep],y[keep]]),d[keep],K)
                gt_world.append(transform_points(local,poses[frame]))
            gt_world=np.concatenate(gt_world)
            assert len(gt_world)>=mesh_gate["minimum_points"]
            distances,_=cKDTree(vertices).query(gt_world,workers=2)
            mesh_report["depth_to_mesh_vertices"]={"points":len(gt_world),"median_m":float(np.median(distances)),
                                                   "p95_m":float(np.percentile(distances,95)),"coordinate_fit":"none"}
            save(out/f"{scene}_mesh_qa.json",mesh_report)
            assert np.median(distances)<=mesh_gate["nearest_vertex_median_max_m"],scene
            assert np.percentile(distances,95)<=mesh_gate["nearest_vertex_p95_max_m"],scene
        else:
            assert role=="sealed_final_test"
            mesh_report["depth_to_mesh_vertices"]="NOT_COMPUTED: final test integrity-only policy"
        row={"scene":scene,"role":role,"status":"PASS","rgb_files":len(rgb),"depth_files":len(depths),
             "pose":pose_report,"derived_gt_pose_rows":stop,"mapping_rgb_frames":int(split["model_input_rgb"].sum()),
             "calibration_mapping_poses":int(split["calibration_pose"].sum()),
             "primary_heldout_views":int(split["primary_eval_view"].sum()),
             "candidate_eligible_input_frames":int(split["primary_candidate_anchor_eligible"].sum()),
             "min_gt_valid_depth_fraction":min(r["valid_fraction"] for r in depths),
             "self_projection_max_abs_error_px":max(r["self_projection_max_abs_error_px"] for r in depths),
             "prefix_gt_position_span_m":span,"prefix_gt_singular_values":singular.tolist(),
             "mesh":mesh_report,"cross_view_gt_qa":cross if cross else "NOT_COMPUTED: final test integrity-only policy",
             "model_predictions_run":False,"images_displayed":False}
        results.append(row)
        save(out/f"{scene}_qa.json",row)
        del mesh,vertices,faces,triangles
    # Rehash after QA. Source archive data and derived TUM records remain fixed.
    for row in verified:
        now=digest(ROOT/row["path"])
        assert now["sha256"]==row["sha256"] and now["bytes"]==row["bytes"],row["path"]
    save(out/"derived_files.json",derived)
    save(out/"preservation.json",{"status":"PASS","archive_files_rehashed":len(verified),"unchanged":True})
    source_paths=[spec_path,mesh_spec_path,parser_amendment,ROOT/"scripts/validate_n2_datasets.py",ROOT/"src/dataset_contract.py",
                  ROOT/"tests/test_dataset_contract.py",ROOT/"src/pointmap_contract.py",ROOT/"src/e1_taxonomy.py",
                  ROOT/"scripts/download_e0_replica.py",ROOT/"scripts/download_e3b_replica.py",ROOT/"scripts/acquire_n2_meshes.py"]
    for p in source_paths:
        target=out/"source"/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    save(out/"source_manifest.json",[digest(p) for p in source_paths])
    result={"stage":"N2_SCENE_QA" if selected_scene else "N2","status":"PASS","scenes":results,"unique_archive_files_verified":len(verified),
            "archive_payload_bytes":sum(r["bytes"] for r in verified),"derived_gt_pose_files":len(results),"derived_files":len(derived),
            "camera":camera,"processed_K":K.tolist(),"resize_hw":list(resize_hw),"crop":list(crop),
            "source_archive":{"url":registration["source_url"],"bytes":registration["expected_archive_bytes"],"etag":registration["expected_archive_etag"]},
            "final_test_integrity_only":True,"next":"A0 on office2 diagnostic scene; keep office4 sealed until final protocol freeze",
            "scope":"Data readiness only; no model tracking, Gaussian generation, A0 oracle effects or correction efficacy"}
    save(out/"result.json",result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration",default="results/N2_dataset_preparation/2026-10-26/registration.json")
    parser.add_argument("--output",default="results/N2_dataset_preparation/2026-10-26/qa")
    parser.add_argument("--scene",choices=["office2","office3","office4"])
    args=parser.parse_args()
    out=(ROOT/args.output).resolve()
    if not out.is_relative_to(ROOT/"results/N2_dataset_preparation"):
        parser.error("Output must be under results/N2_dataset_preparation")
    out.mkdir(parents=True,exist_ok=False)
    started=datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    try:result=validate(out,ROOT/args.registration,args.scene)
    except Exception:
        save(out/"failure.json",{"status":"FAIL","traceback":traceback.format_exc()});raise
    save(out/"execution.json",{"started_at":started,"finished_at":datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
                               "command":sys.argv,"python":sys.version})
    print(json.dumps({k:result[k] for k in ["status","unique_archive_files_verified","archive_payload_bytes","derived_gt_pose_files"]},indent=2))


if __name__=="__main__":main()

#!/usr/bin/env python3
"""Collect the three successful N2 scene checks into tracked frozen metadata."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"results/N2_dataset_preparation/2026-10-26"


def digest(path):
    with path.open("rb") as stream:sha=hashlib.file_digest(stream,"sha256").hexdigest()
    return {"path":str(path.relative_to(ROOT)),"bytes":path.stat().st_size,"sha256":sha}


def save(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+"\n")


def main():
    manifest_path=ROOT/"configs/n2_dataset_manifest.json"
    summary_path=ROOT/"configs/n2_results_summary.json"
    assert not manifest_path.exists() and not summary_path.exists(),"Preserve completed metadata"
    spec=json.loads((OUT/"registration.json").read_text())
    assert spec==json.loads((ROOT/"configs/n2_dataset_registration.json").read_text())
    folders={"office2":"qa_office2_v2","office3":"qa_office3","office4":"qa_office4"}
    files={};derived=[];scenes=[];artifact_paths=[];sources={};rgb_hashes={}
    for registered in spec["scenes"]:
        scene=registered["scene"];folder=OUT/folders[scene]
        result=json.loads((folder/"result.json").read_text())
        assert result["status"]=="PASS" and len(result["scenes"])==1
        row=result["scenes"][0]
        assert row["scene"]==scene and row["role"]==registered["role"] and row["status"]=="PASS"
        assert not row["model_predictions_run"] and not row["images_displayed"]
        if row["role"]=="sealed_final_test":
            assert isinstance(row["cross_view_gt_qa"],str) and row["cross_view_gt_qa"].startswith("NOT_COMPUTED")
            assert isinstance(row["mesh"]["depth_to_mesh_vertices"],str) and row["mesh"]["depth_to_mesh_vertices"].startswith("NOT_COMPUTED")
        scenes.append(row)
        verified=json.loads((folder/"verified_files.json").read_text())
        for item in verified:
            file={k:item[k] for k in ["path","bytes","sha256","zip_crc"]}
            if file["path"] in files:assert files[file["path"]]==file
            files[file["path"]]=file
        rgb_hashes[scene]={r["sha256"] for r in verified if r.get("modality")=="RGB"}
        for item in json.loads((folder/"derived_files.json").read_text()):
            assert digest(ROOT/item["path"])==item,item["path"]
            derived.append(item)
        for item in json.loads((folder/"source_manifest.json").read_text()):
            assert digest(ROOT/item["path"])==item,item["path"]
            if item["path"] in sources:assert sources[item["path"]]==item
            sources[item["path"]]=item
        artifact_paths.extend(p for p in folder.iterdir() if p.is_file())
    overlaps={f"{a}/{b}":len(rgb_hashes[a]&rgb_hashes[b]) for i,a in enumerate(folders) for b in list(folders)[i+1:]}
    assert not any(overlaps.values()),"Exact RGB payload overlap across scene roles"
    assert len(files)==6007 and len(derived)==6
    assert all(s["rgb_files"]==s["depth_files"]==1000 for s in scenes)
    source_checks=[]
    n1=json.loads((ROOT/"configs/n1_results_summary.json").read_text())
    for item in n1["source_files"]:
        assert digest(ROOT/item["path"])==item,item["path"]
        source_checks.append(item)
    save(OUT/"prior_n1_source_preservation.json",{"status":"PASS","files":source_checks})
    own_source=OUT/"finalize_n2_source.py"
    shutil.copy2(Path(__file__),own_source)
    artifact_paths.extend(p for p in OUT.iterdir() if p.is_file())
    artifact_paths.append(OUT/"qa_office2/failure.json")
    artifact_index=[digest(p) for p in sorted(set(artifact_paths))]
    manifest={"stage":"N2","release":"NICE-SLAM rendered Replica",
              "registered_date":spec["registered_date"],"source_url":spec["source_url"],
              "archive_bytes":spec["expected_archive_bytes"],"archive_etag":spec["expected_archive_etag"],
              "whole_archive_sha256":"NOT_COMPUTED; selected ZIP members checked against CRC and recorded local SHA-256",
              "registration":"configs/n2_dataset_registration.json",
              "mesh_schema_amendments":["configs/n2_mesh_qa_amendment_A1.json","configs/n2_mesh_qa_amendment_A2.json"],
              "dataset_root":spec["dataset_root"],"scenes":[{"scene":r["scene"],"role":r["role"],
                 "image_interval":[0,1000],"raw_traj_poses":r["pose"]["pose_rows"],"paired_gt_poses":1000,
                 "frame_split":str((OUT/folders[r["scene"]]/f"{r['scene']}_frame_split.csv").relative_to(ROOT)),
                 "raw_mesh":f"{spec['dataset_root']}/{r['scene']}_mesh.ply","triangulated_mesh":r["mesh"]["derived_mesh"]} for r in scenes],
              "unique_archive_files":len(files),"archive_payload_bytes":sum(r["bytes"] for r in files.values()),
              "files":[files[k] for k in sorted(files)],"derived_files":derived,
              "exact_rgb_hash_overlap_between_roles":overlaps,
              "final_test_policy":spec["final_test_policy"]}
    save(manifest_path,manifest)
    summary={"stage":"N2","status":"PASS","finished_at":datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
             "report":"docs/experiments/N2_dataset_preparation.md","registration":"configs/n2_dataset_registration.json",
             "dataset_manifest":digest(manifest_path),"counts":{"scenes":3,"rgb":3000,"depth":3000,"raw_traj_files":3,
             "paired_gt_poses":3000,"raw_meshes":3,"camera_files":1,"unique_archive_files":len(files),"derived_files":len(derived)},
             "archive_payload_bytes":manifest["archive_payload_bytes"],"scenes":scenes,
             "tests":{"passed":8,"command":".venv/bin/python -m unittest discover -s tests -p test_dataset_contract.py -v"},
             "exact_rgb_hash_overlap_between_roles":overlaps,"prior_n1_source_files_unchanged":len(source_checks),
             "source_files":list(sources.values())+[digest(Path(__file__))],"frozen_artifact_index":artifact_index,
             "final_test_integrity_only":True,"model_predictions_run":False,
             "amendments":{"A1":"Register supplied mesh QA before geometric analysis","A2":"Correct triangular-face parser assumption for supplied quad faces; preserve initial failure and fixed thresholds"},
             "next":"Register and execute A0 on office2 diagnostic scene; office4 remains reserved for frozen final evaluation",
             "limits":["Unused refers to repository experiment history, not model pretraining exposure.",
                       "All scenes share the rendered Replica indoor domain.",
                       "No tracking, actual KF count, new-scene GPU capacity or A0 effects have been measured.",
                       "Final-test withholding is a recorded workflow policy, not filesystem access isolation.",
                       "Scene completeness must be restricted to observed/evaluable support when using the supplied full-scene mesh."]}
    save(summary_path,summary)
    save(OUT/"completion.json",{"status":"PASS","dataset_manifest":digest(manifest_path),
                               "summary":digest(summary_path),"exact_rgb_role_overlap":overlaps})
    print(json.dumps({"status":"PASS","archive_files":len(files),"derived_files":len(derived),
                      "archive_payload_bytes":manifest["archive_payload_bytes"],"exact_rgb_overlap":overlaps},indent=2))


if __name__=="__main__":main()

"""Run E1 CPU taxonomy on the frozen five-KF E0b baseline."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import shutil

import cv2
import numpy as np
from scipy.spatial import cKDTree
import torch

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "thirdparty/Splatt3R-SLAM"
sys.path[:0] = [str(ROOT / "src"), str(UPSTREAM), str(UPSTREAM / "splatt3r_core")]
from e0b_audit import sim3_matrix
from e1_taxonomy import (camera_geometry, classify, counts, depth_masks, fit_sim3,
                         gt_surface, mark_redundancy, resize_depth, transform)
from utils.geometry import build_covariance
from splatt3r_slam.gaussian_ply_codec import decode_gaussians_from_ply


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return {"path": str(Path(path).relative_to(ROOT)), "sha256": h.hexdigest(), "bytes": Path(path).stat().st_size}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def load_view(dataset, frame, camera, poses, spec):
    path = dataset / "office0/results" / f"depth{frame:06d}.png"
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None or raw.shape != (camera["h"], camera["w"]):
        raise ValueError(f"Missing/wrong GT depth: {path}")
    depth = resize_depth(raw.astype(np.float32) / camera["scale"], camera)
    valid, edge = depth_masks(depth, spec)
    return dict(frame=frame, depth=depth, valid=valid, edge=edge, pose=poses[frame])


def percentile(values):
    values = np.asarray(values)
    values = values[np.isfinite(values)]
    return {"n": len(values), **{k: float(np.percentile(values, q)) if len(values) else None
                                for k, q in (("p05", 5), ("median", 50), ("p95", 95))}}


def main():
    started = time.monotonic()
    torch.set_num_threads(2)
    spec_path = ROOT / "configs/e1_taxonomy.json"
    spec = json.loads(spec_path.read_text())
    run, dataset, out = [ROOT / spec[k] for k in ("baseline_run", "evaluation_dataset", "output")]
    out.mkdir(parents=True, exist_ok=True)
    spec_hash = digest(spec_path)
    if (out / "specification.json").exists():
        if json.loads((out / "specification.json").read_text()) != spec:
            raise RuntimeError("Existing run has a different specification; use a new output directory")
    write_json(out / "specification.json", spec)
    data_manifest = json.loads((ROOT / "configs/e1_replica_download_manifest.json").read_text())
    baseline_data_manifest = json.loads((ROOT / "configs/e0b_replica_download_manifest.json").read_text())
    baseline_rgb = {Path(r["path"]).name: r["sha256"] for r in baseline_data_manifest["files"]
                    if Path(r["path"]).name.startswith("frame")}
    for record in data_manifest["files"]:
        assert digest(ROOT / record["path"])["sha256"] == record["sha256"], record["path"]
        name = Path(record["path"]).name
        if name.startswith("frame"):
            assert record["sha256"] == baseline_rgb[name], name
    required_gt = set(range(1, 360, 2)) | set(range(0, 360, 20)) | {0, 82, 148, 222, 298}
    available_gt = {int(Path(r["path"]).stem[5:]) for r in data_manifest["files"] if Path(r["path"]).name.startswith("depth")}
    assert required_gt <= available_gt
    print("Evaluation data SHA-256 and baseline RGB identity: PASS", flush=True)
    camera = json.loads((dataset / "cam_params.json").read_text())["camera"]
    K, resize_hw, crop = camera_geometry(camera)
    gt_poses = np.loadtxt(dataset / "office0/traj.txt").reshape(-1, 4, 4)
    trajectory = np.loadtxt(run / "map/office0_frames.txt")
    frame_ids = trajectory[:, 0].astype(int)
    np.testing.assert_array_equal(frame_ids, np.arange(0, 360, 2))
    alignment = fit_sim3(trajectory[:, 1:4], gt_poses[frame_ids, :3, 3])
    global_scale = np.cbrt(np.linalg.det(alignment[:3, :3]))
    ate = np.linalg.norm(transform(trajectory[:, 1:4], alignment) - gt_poses[frame_ids, :3, 3], axis=1)
    dump = torch.load(run / "map/office0_kfgauss.pt", weights_only=True, map_location="cpu")
    journal = [json.loads(line) for line in (run / "audit/events.jsonl").read_text().splitlines()]
    final_event = [e for e in journal if e["kind"] == "snapshot" and e["stage"] == "final"][-1]
    final = torch.load(run / "audit" / final_event["file"], weights_only=True, map_location="cpu")
    assert final["pose_revision"] == 188 and len(dump["keyframes"]) == 5
    lineage, means, covariances, diagnostic_means, diagnostic_covariances = [], [], [], [], []
    anchors, active, opacity, confidence, pixel_ids = [], [], [], [], []
    provenance_files = [spec_path, run / "run_manifest.json", run / "audit/events.jsonl",
                        run / "audit" / final_event["file"], run / "map/office0_kfgauss.pt",
                        run / "map/office0_gaussians.ply", run / "map/office0_frames.txt",
                        ROOT / "configs/e1_replica_download_manifest.json"]
    for kf in dump["keyframes"]:
        anchor = kf["kf_idx"]
        meta = final["metadata"][anchor]
        event = meta["candidate_event"]
        raw_path = run / "exports/raw_pairs" / f"{event}.pt"
        raw = torch.load(raw_path, weights_only=True, map_location="cpu")
        provenance_files.append(raw_path)
        assert torch.equal(raw["outputs"][0]["means"].reshape(-1, 3), kf["means"])
        assert torch.equal(final["poses"][anchor], kf["T_WC"])
        assert meta["candidate_sources"] == raw["source_image_ids"]
        n = len(kf["means"])
        assert n == 288 * 512
        local = kf["means"].numpy()
        q = kf["rotations"] / kf["rotations"].norm(dim=-1, keepdim=True).clamp_min(1e-6)
        cov = build_covariance(kf["scales"], q).numpy()
        pose = sim3_matrix(kf["T_WC"].numpy())
        metric_pose = alignment @ pose
        means.append(transform(local, metric_pose))
        covariances.append(metric_pose[:3, :3] @ cov @ metric_pose[:3, :3].T)
        frame_id = kf["frame_id"] * spec["input_subsample"]
        diagnostic_pose = gt_poses[frame_id].copy()
        diagnostic_pose[:3, :3] *= global_scale * np.cbrt(np.linalg.det(pose[:3, :3]))
        diagnostic_means.append(transform(local, diagnostic_pose))
        diagnostic_covariances.append(diagnostic_pose[:3, :3] @ cov @ diagnostic_pose[:3, :3].T)
        z = kf["means"][:, 2]
        # Match original export masks in float32 (quantile precedes other filters).
        zmax = torch.quantile(z[z > 0.05], 0.98)
        keep = ((z > 0.05) & (z <= zmax) & (kf["scales"].max(-1).values < 1.) &
                (kf["conf"] >= 1.5) & (kf["opacities"] > 0.3)).numpy()
        active.append(keep)
        opacity.append(kf["opacities"].numpy())
        confidence.append(kf["conf"].numpy())
        anchors.append(np.full(n, anchor, np.uint8))
        pixel_ids.append(np.arange(n, dtype=np.int32))
        lineage.append(dict(anchor_kf=anchor, original_frame_id=frame_id, prediction_event_id=event,
                            original_source_frame_ids=[i * 2 for i in raw["source_image_ids"]],
                            candidate_id_format=f"{event}:self:<pixel_index>",
                            count=n, active_count=int(keep.sum())))
    means, covariances = np.concatenate(means), np.concatenate(covariances)
    diagnostic_means, diagnostic_covariances = np.concatenate(diagnostic_means), np.concatenate(diagnostic_covariances)
    active, anchors, opacity, confidence, pixel_ids = [np.concatenate(v) for v in (active, anchors, opacity, confidence, pixel_ids)]
    persisted = decode_gaussians_from_ply(run / "map/office0_gaussians.ply")
    assert active.sum() == persisted["n"] == 705772
    expected_means = transform(persisted["means"].numpy(), alignment)
    expected_cov = alignment[:3, :3] @ persisted["covariances"].numpy() @ alignment[:3, :3].T
    gpu_integrity = json.loads((out / "baseline_gpu_integrity.json").read_text())
    assert gpu_integrity["status"] == "PASS" and gpu_integrity["active"] == int(active.sum())
    assert gpu_integrity["ply_sha256"] == digest(run / "map/office0_gaussians.ply")["sha256"]
    assert gpu_integrity["keyframe_dump_sha256"] == digest(run / "map/office0_kfgauss.pt")["sha256"]
    provenance_files.append(out / "baseline_gpu_integrity.json")
    cpu_placement_delta = dict(mean_max_euclidean_m=float(np.linalg.norm(means[active] - expected_means, axis=1).max()),
                               covariance_max_abs_m2=float(np.abs(covariances[active] - expected_cov).max()))
    # The actual baseline artifact includes upstream TF32 rounding. Keep that
    # representation for active labels and rendered geometry, without relaxing
    # a high-precision identity assertion to hide numerical-mode differences.
    means[active] = expected_means
    covariances[active] = expected_cov
    np.testing.assert_allclose(opacity[active], persisted["opacity"].numpy(), atol=1e-6, rtol=1e-5)
    opacity[active] = persisted["opacity"].numpy()
    print(f"Frozen raw/active lineage and PLY order: PASS ({len(means)}/{active.sum()})", flush=True)
    views_ids = sorted(set(range(0, 360, 20)) | {r["original_frame_id"] for r in lineage})
    assert all(i % 2 == 0 for i in views_ids)
    views = [load_view(dataset, i, camera, gt_poses, spec) for i in views_ids]
    surface, normals = gt_surface(views, K, spec["gt_surface_cloud_pixel_stride"])
    tree = cKDTree(surface)
    result = dict(specification=spec, alignment=dict(matrix=alignment.tolist(), scale=float(global_scale),
                  matched_mapping_input_poses=len(frame_ids), ate_rmse_m=float(np.sqrt(np.mean(ate ** 2))),
                  ate_p95_m=float(np.percentile(ate, 95))),
                  final_pose_revision=final["pose_revision"], intrinsics=K.tolist(), rgb_hw=list(views[0]["depth"].shape),
                  raw_camera=camera, resize_hw=list(resize_hw), crop_top_left_height_width=list(crop),
                  gpu_baseline_integrity=gpu_integrity, cpu_placement_vs_persisted=cpu_placement_delta,
                  lineage=lineage, taxonomy_gt_view_ids=views_ids, gt_surface_samples=len(surface),
                  integrity=dict(raw_candidate_identity="PASS", final_snapshot_pose_identity="PASS",
                                 active_count_and_ply_parameter_order="PASS", evaluation_data_sha256="PASS",
                                 baseline_rgb_identity="PASS"), arms={})
    arrays = dict(active=active, anchor_kf=anchors, pixel_index=pixel_ids, opacity=opacity, confidence=confidence)
    examples = []
    rng = np.random.default_rng(spec["seed"])
    for name, mu, cov in (("estimated_pose", means, covariances),
                         ("gt_anchor_pose_diagnostic", diagnostic_means, diagnostic_covariances)):
        print(f"Classifying {name} on {len(views)} GT views", flush=True)
        classified = classify(mu, cov, views, K, spec)
        distance, nearest = tree.query(mu, workers=2)
        labels_raw = mark_redundancy(classified["labels"], mu, normals[nearest], anchors,
                                     np.ones(len(mu), bool), spec)
        labels_active = mark_redundancy(classified["labels"], mu, normals[nearest], anchors, active, spec)
        summary = dict(raw=counts(labels_raw), active=counts(labels_active, active),
                       evaluable_active_fraction=float(np.mean(labels_active[active] != 0)),
                       center_only_repeated_front_raw=int(classified["center_front"].sum()),
                       center_only_repeated_front_active=int((classified["center_front"] & active).sum()),
                       center_front_but_extent_not_certified_active=int((classified["center_front"] & ~classified["ellipsoid_front"] & active).sum()),
                       raw_no_reliable_gt_view=int((classified["reliable_gt_views"] == 0).sum()),
                       active_no_reliable_gt_view=int(((classified["reliable_gt_views"] == 0) & active).sum()),
                       nearest_sampled_gt_surface_distance_m=percentile(distance[active]),
                       center_distance_gt_threshold_fractions={str(t): float(np.mean(distance[active] > t)) for t in (0.02, 0.05, 0.1)},
                       repeated_front_opacity_area_max_px2=percentile((classified["footprint_area_max"] * opacity)[active & (labels_active == 3)]),
                       by_kf=[dict(anchor_kf=int(i), raw=counts(labels_raw, anchors == i),
                                   active=counts(labels_active, (anchors == i) & active)) for i in np.unique(anchors)],
                       sensitivity={})
        arrays[name + "_labels_raw"] = labels_raw
        arrays[name + "_labels_active"] = labels_active
        arrays[name + "_nearest_gt_distance_m"] = distance.astype(np.float32)
        for key, value in classified.items():
            if key != "labels":
                arrays[name + "_" + key] = value
        for tol in spec["sensitivity_absolute_tolerances_m"]:
            if tol == spec["depth_tolerance_abs_m"]:
                alternative = classified
            else:
                print(f"  fixed tolerance sensitivity {tol} m", flush=True)
                alternative = classify(mu, cov, views, K, spec, tol)
            summary["sensitivity"][str(tol)] = dict(conservative_front_active=int(((alternative["labels"] == 3) & active).sum()),
                                                      center_front_active=int((alternative["center_front"] & active).sum()),
                                                      center_valid_active=int((alternative["center_valid"] & active).sum()))
        result["arms"][name] = summary
        for anchor in np.unique(anchors):
            for code in range(4):
                ids = np.flatnonzero(active & (anchors == anchor) & (labels_active == code))
                for i in rng.choice(ids, min(5, len(ids)), replace=False):
                    examples.append(dict(arm=name, anchor_kf=int(anchor), label_code=code,
                        candidate_id=f"{lineage[anchor]['prediction_event_id']}:self:{pixel_ids[i]}",
                        pixel_index=int(pixel_ids[i]), confidence=float(confidence[i]), opacity=float(opacity[i]),
                        center_world_m=mu[i].tolist(), nearest_sampled_gt_world_m=surface[nearest[i]].tolist(),
                        nearest_sampled_gt_distance_m=float(distance[i]),
                        center_support_views=int(classified["center_support_views"][i]),
                        center_front_views=int(classified["center_front_views"][i]),
                        ellipsoid_front_views=int(classified["ellipsoid_front_views"][i])))
        print(json.dumps({"arm": name, "active": summary["active"]}), flush=True)
    arrays["labels_cross_pose_disagreement"] = arrays["estimated_pose_labels_active"] != arrays["gt_anchor_pose_diagnostic_labels_active"]
    result["cross_pose_active_label_disagreement_fraction"] = float(np.mean(arrays["labels_cross_pose_disagreement"][active]))
    result["cross_pose_active_label_contingency"] = [
        [int(np.sum(active & (arrays["estimated_pose_labels_active"] == i) &
                    (arrays["gt_anchor_pose_diagnostic_labels_active"] == j))) for j in range(4)] for i in range(4)]
    # Raw candidate IDs are recoverable from event + pixel_index; no row reordering.
    np.savez_compressed(out / "candidate_labels.npz", **arrays)
    write_json(out / "candidate_examples.json", examples)
    np.savez_compressed(out / "diagnostic_active_geometry.npz", means=diagnostic_means[active].astype(np.float32),
                        covariance=diagnostic_covariances[active].astype(np.float32))
    result["cpu_analysis_wall_seconds"] = time.monotonic() - started
    result["not_measured"] = ["GT mesh distance / TSDF accuracy-completeness", "admission efficacy / false rejection",
                               "strict per-candidate floater ground truth", "novel-view independence or additional scenes"]
    code_paths = [ROOT / p for p in ("src/e1_taxonomy.py", "src/e0b_audit.py", "scripts/analyze_e1.py", "scripts/download_e1_gt.py",
                  "scripts/render_e1.py", "scripts/plot_e1.py", "scripts/run_e1.sh", "tests/test_e1_taxonomy.py",
                  "scripts/check_e1_baseline.py", "tests/test_e1_download.py",
                  "thirdparty/Splatt3R-SLAM/splatt3r_core/utils/geometry.py",
                  "thirdparty/Splatt3R-SLAM/splatt3r_slam/gaussian_ply_codec.py")]
    for path in code_paths:
        saved = out / "code" / path.relative_to(ROOT)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
    write_json(out / "run_manifest.json", dict(specification_sha256=spec_hash["sha256"],
               repository_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               inputs=[digest(p) for p in provenance_files], code=[digest(p) for p in code_paths],
               versions=dict(python=sys.version, numpy=np.__version__, torch=torch.__version__, opencv=cv2.__version__),
               gt_separation="evaluation-only; baseline artifacts read-only; no mapper/model execution"))
    shutil.copy2(out / "run_manifest.json", ROOT / "configs/e1_code_manifest.json")
    write_json(out / "taxonomy_summary.json", result)
    write_json(ROOT / "configs/e1_results_summary.json", result)
    print(f"E1 CPU taxonomy saved: {out}; {result['cpu_analysis_wall_seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()

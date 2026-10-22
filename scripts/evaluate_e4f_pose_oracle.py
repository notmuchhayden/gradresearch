#!/usr/bin/env python3
"""Compare estimated-pose and OXTS-pose placement of identical raw Gaussians."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import torch
from scipy.spatial import cKDTree

import evaluate_e4f_kitti_geometry as ev

ROOT, DRIVE, RUN, GT = ev.ROOT, ev.DRIVE, ev.RUN, ev.GT
OUT = ROOT / f"results/E4f_kitti_geometry_diagnostic/{DRIVE}/evaluation_pose_oracle"


def sim3_to_rt(v):
    v = np.asarray(v).reshape(-1)
    return ev.quat_xyzw(v[3:7]), v[:3], float(v[7])


def xyz_in_world(points, R, t, scale=1.):
    return scale * (points @ R.T) + t


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "metrics.json").exists():
        raise RuntimeError("Existing pose-oracle evaluation preserved")
    split = json.loads((ROOT / "configs/e4f_kitti_input_split.json").read_text())
    rows = split["frames"]
    times = np.array([x["rgb_seconds_from_start"] for x in rows])
    est = np.loadtxt(RUN / "map" / f"{DRIVE}_frames.txt")
    ids = np.array([np.argmin(np.abs(times - t)) for t in est[:, 0]], dtype=int)
    ev.calib_from_velo = ev.read_calib(GT / "calibration/calib_velo_to_cam.txt")
    oxts = sorted((GT / "oxts").glob("*.txt"))[:240]
    gt_xyz, gt_R = ev.oxts_positions_and_rotations(oxts, times)
    s, R_align, t_align = ev.fit_sim3(est[:, 1:4], gt_xyz[ids])

    cc = ev.read_calib(GT / "calibration/calib_cam_to_cam.txt")
    P = cc["P_rect_02"].reshape(3, 4)
    K, p4 = P[:, :3], P[:, 3]
    T_cam2_cam0 = ev.transform(np.eye(3), np.linalg.solve(K, p4))
    Rrect = np.eye(4); Rrect[:3, :3] = cc["R_rect_00"].reshape(3, 3)
    velo = ev.transform(ev.calib_from_velo["R"].reshape(3, 3), ev.calib_from_velo["T"])
    T_cam2_velo = T_cam2_cam0 @ Rrect @ velo
    tracklets = ev.read_tracklets()
    sx, sy = 512/1242, 155/375
    gt_world_parts = []
    for i in range(0, 240, 2):
        scan = np.fromfile(GT / f"lidar/{i:010d}.bin", dtype=np.float32).reshape(-1, 4)[:, :3]
        static = ~ev.dynamic_point_mask(scan, i, tracklets)
        homogeneous = np.column_stack([scan, np.ones(len(scan))])
        q = (P @ Rrect @ velo @ homogeneous.T).T
        z = q[:, 2]
        u, v = q[:, 0]/np.maximum(z, 1e-8), q[:, 1]/np.maximum(z, 1e-8)
        um, vm = (u+.5)*sx-.5, (v+.5)*sy-.5-5.5
        ix, iy = np.rint(um).astype(int), np.rint(vm).astype(int)
        valid = static & (z > 0) & (u >= 0) & (u < 1242) & (v >= 0) & (v < 375) & (ix >= 0) & (ix < 512) & (iy >= 0) & (iy < 144)
        src = np.flatnonzero(valid)
        key = iy[src]*512 + ix[src]
        order = np.lexsort((z[src], key))
        src, key = src[order], key[order]
        src = src[np.r_[True, key[1:] != key[:-1]]]
        cam = (T_cam2_velo @ homogeneous[src].T).T[:, :3]
        world = xyz_in_world(cam, gt_R[i], gt_xyz[i])
        gt_world_parts.append(world)
    gt_world = np.concatenate(gt_world_parts).astype(np.float32)
    tree = cKDTree(gt_world)

    dump = torch.load(RUN / "map" / f"{DRIVE}_kfgauss.pt", map_location="cpu", weights_only=True)
    estimated_parts, oracle_parts = [], []
    candidate_dir = RUN / "exports/candidate_sources"
    for kf in dump["keyframes"]:
        frame_id = int(kf["frame_id"])
        original = 2*frame_id
        meta_path = next(candidate_dir.glob(f"kf{int(kf['kf_idx']):04d}_*.json"))
        lineage = json.loads(meta_path.read_text())
        assert int(lineage["frame_id"]) == frame_id
        assert lineage["gaussian_coordinate_frame"] == "anchor_camera"
        raw = torch.load(RUN / "exports/raw_pairs" / f"{lineage['prediction_event_id']}.pt",
                         map_location="cpu", weights_only=True)
        assert raw["source_pair_ids"][0][0] == frame_id
        raw_means = raw["outputs"][0]["means"][0].reshape(-1, 3)
        assert torch.equal(kf["means"], raw_means), "keyframe Gaussian means do not equal raw pointmap means"
        points = kf["means"].numpy()
        conf = kf["conf"].numpy().reshape(-1)
        keep = (conf > 1.5) & np.isfinite(points).all(axis=1) & ((np.arange(len(points)) % 16) == 0)
        points = points[keep]
        # B1 map placement: final keyframe Sim(3), followed by the one global
        # trajectory alignment. This preserves the per-keyframe estimated pose.
        Rk, tk, sk = sim3_to_rt(kf["T_WC"].numpy())
        est_world = xyz_in_world(points, Rk, tk, sk)
        est_world = s * (est_world @ R_align) + t_align
        estimated_parts.append(est_world.astype(np.float32))
        # Pose oracle: unchanged camera-local Gaussian centres, one shared
        # trajectory scale, and that frame's evaluation-only OXTS camera pose.
        oracle_parts.append(xyz_in_world(points, gt_R[original], gt_xyz[original], s).astype(np.float32))

    def summarize(parts):
        cloud = np.concatenate(parts)
        distances, _ = tree.query(cloud, k=1, workers=-1)
        return {"point_count":int(len(cloud)),"map_to_static_lidar_nn_median_m":float(np.median(distances)),
                "map_to_static_lidar_nn_p95_m":float(np.percentile(distances,95)),
                "map_to_static_lidar_nn_mean_m":float(np.mean(distances))}

    est_metrics, oracle_metrics = summarize(estimated_parts), summarize(oracle_parts)
    # The reverse direction measures whether the estimated map covers the
    # observed static LiDAR surface; subsample the reference deterministically.
    static_ref = gt_world[::8]
    est_tree = cKDTree(np.concatenate(estimated_parts))
    oracle_tree = cKDTree(np.concatenate(oracle_parts))
    for label, query in (("estimated_pose", est_tree), ("oxts_pose_oracle", oracle_tree)):
        d, _ = query.query(static_ref, k=1, workers=-1)
        target = est_metrics if label == "estimated_pose" else oracle_metrics
        target["static_lidar_to_map_nn_median_m"] = float(np.median(d))
        target["static_lidar_to_map_nn_p95_m"] = float(np.percentile(d,95))
    result = {"status":"complete","same_raw_gaussian_geometry":"verified exact tensor equality for all exported keyframes",
        "keyframes":int(dump["n"]),"static_lidar_reference_points":int(len(gt_world)),
        "trajectory_global_scale_m_per_slam_unit":s,
        "estimated_pose_map":est_metrics,"oxts_pose_oracle_map":oracle_metrics,
        "interpretation_limit":"Evaluation-only point-to-nearest-surface distances on this single drive. The pointmap and pose scales are global; no per-frame scale fitting or ICP was used. KITTI tracklets remove annotated boxes only; unlabelled dynamic points may remain.",
        "inputs":[str((RUN/"map"/f"{DRIVE}_kfgauss.pt").relative_to(ROOT)),
                  str((RUN/"map"/f"{DRIVE}_frames.txt").relative_to(ROOT)),
                  str((GT/"tracklet_labels.xml").relative_to(ROOT))]}
    (OUT/"metrics.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()

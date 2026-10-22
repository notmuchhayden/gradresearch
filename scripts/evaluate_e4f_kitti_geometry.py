#!/usr/bin/env python3
"""Evaluation-only E4f metrics for one KITTI Raw drive and sealed B1 run."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
DRIVE = "2011_09_26_drive_0015_sync"
RUN = ROOT / f"results/E4f_kitti_geometry_diagnostic/{DRIVE}/baseline_A2b"
DATA = ROOT / f"data/E4f/eth3d/{DRIVE}"
GT = ROOT / f"data/E4f/evaluation_only/{DRIVE}"
OUT = ROOT / f"results/E4f_kitti_geometry_diagnostic/{DRIVE}/evaluation_tracklet_masked_v3"


def read_calib(path: Path) -> dict[str, np.ndarray]:
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"(\w+):\s+(.*)", line)
        if m:
            try:
                out[m.group(1)] = np.array([float(x) for x in m.group(2).split()])
            except ValueError:
                pass
    return out


def transform(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def rot_xyz(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def quat_xyzw(q: np.ndarray) -> np.ndarray:
    x, y, z, w = q / np.linalg.norm(q)
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
        [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
    ])


def fit_sim3(src: np.ndarray, dst: np.ndarray):
    a, b = src.mean(0), dst.mean(0)
    X, Y = src-a, dst-b
    U, s, Vt = np.linalg.svd(X.T @ Y / len(src))
    D = np.eye(3)
    D[2, 2] = np.linalg.det(U @ Vt)
    R = U @ D @ Vt
    scale = float(np.sum(s * np.diag(D)) / np.mean(np.sum(X*X, axis=1)))
    t = b - scale * (a @ R)
    return scale, R, t


def percentile(x, q):
    return float(np.percentile(x, q)) if len(x) else None


def oxts_positions_and_rotations(records: list[Path], times: np.ndarray):
    calib = read_calib(GT / "calibration/calib_imu_to_velo.txt")
    # OXTS poses are in the local Mercator world frame; first latitude is origin.
    rows = [np.loadtxt(p) for p in records]
    lat0 = math.radians(float(rows[0][0]))
    scale = math.cos(lat0)
    er = 6378137.0
    poses = []
    for d in rows:
        lat, lon, alt, roll, pitch, yaw = d[:6]
        tx = scale * math.radians(float(lon)) * er
        ty = scale * er * math.log(math.tan(math.pi/4 + math.radians(float(lat))/2))
        twi = transform(rot_xyz(float(roll), float(pitch), float(yaw)),
                        np.array([tx, ty, float(alt)]))
        poses.append(twi)
    origin = poses[0][:3, 3].copy()
    # camera-to-IMU is only needed to express camera centres; the rigid camera
    # lever arm is small and is retained using the KITTI calibration chain.
    v2c = transform(calib_from_velo["R"].reshape(3, 3), calib_from_velo["T"])
    i2v = transform(calib["R"].reshape(3, 3), calib["T"])
    cc = read_calib(GT / "calibration/calib_cam_to_cam.txt")
    rect0 = transform(cc["R_rect_00"].reshape(3, 3), np.zeros(3))
    T_rect0_imu = rect0 @ v2c @ i2v
    c0_to_imu = np.linalg.inv(T_rect0_imu)  # rectified camera-0 -> IMU
    # KITTI rectified camera-2 origin relative to camera-0 (from P_rect_02).
    P = cc["P_rect_02"].reshape(3, 4)
    t_c2_c0 = np.array([-P[0, 3]/P[0, 0], -P[1, 3]/P[1, 1], -P[2, 3]])
    c2_to_imu = c0_to_imu @ transform(np.eye(3), t_c2_c0)
    T_w_c = [T @ c2_to_imu for T in poses]
    return np.array([T[:3, 3]-origin for T in T_w_c]), np.array([T[:3, :3] for T in T_w_c])


def tracklet_count():
    root = ET.parse(GT / "tracklet_labels.xml").getroot()
    return sum(1 for x in root.iter("item") if x.find("objectType") is not None)


def read_tracklets():
    root = ET.parse(GT / "tracklet_labels.xml").getroot()
    out = []
    for item in root.find("tracklets").findall("item"):
        first = int(item.findtext("first_frame"))
        dims = np.array([float(item.findtext(k)) for k in ("l", "w", "h")])
        poses = []
        for pose in item.find("poses").findall("item"):
            t = np.array([float(pose.findtext(k)) for k in ("tx", "ty", "tz")])
            rpy = np.array([float(pose.findtext(k)) for k in ("rx", "ry", "rz")])
            poses.append((t, rpy, int(pose.findtext("state", "0"))))
        out.append((first, dims, poses))
    return out


def dynamic_point_mask(points: np.ndarray, frame_id: int, tracklets):
    mask = np.zeros(len(points), dtype=bool)
    for first, dims, poses in tracklets:
        i = frame_id - first
        if i < 0 or i >= len(poses):
            continue
        t, rpy, state = poses[i]
        if state == 0:
            continue
        local = (points - t) @ rot_xyz(*rpy)
        mask |= np.all(np.abs(local) <= dims[None, :] * .5, axis=1)
    return mask


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "metrics.json").exists():
        raise RuntimeError(f"Existing evaluation preserved: {OUT / 'metrics.json'}")
    split = json.loads((ROOT / "configs/e4f_kitti_input_split.json").read_text())
    rows = split["frames"]
    rgb_times = np.array([r["rgb_seconds_from_start"] for r in rows])
    # The data loader applies stride 2; its input-frame id i maps to original
    # KITTI synchronized record 2*i. The RGB timestamps in the map file retain
    # this correspondence, which is asserted rather than inferred from counts.
    sampled = rows[::2]
    map_path = RUN / "map" / f"{DRIVE}_frames.txt"
    est = np.loadtxt(map_path)
    if est.ndim == 1:
        est = est[None]
    est_t = est[:, 0]
    aligned_gt_ids = np.array([int(np.argmin(np.abs(rgb_times - t))) for t in est_t])
    time_err = np.abs(rgb_times[aligned_gt_ids] - est_t)
    assert len(est) == 120 and len(np.unique(aligned_gt_ids)) == len(est)
    assert float(time_err.max()) < 1e-5, f"map-to-RGB timestamp mismatch {time_err.max()}"

    global calib_from_velo
    calib_from_velo = read_calib(GT / "calibration/calib_velo_to_cam.txt")
    oxts = sorted((GT / "oxts").glob("*.txt"))[:240]
    gt_xyz, gt_R = oxts_positions_and_rotations(oxts, rgb_times)
    gt_xyz = gt_xyz[aligned_gt_ids]
    pred_xyz = est[:, 1:4]
    s, R, t = fit_sim3(pred_xyz, gt_xyz)
    aligned_xyz = s * (pred_xyz @ R) + t
    trans_err = np.linalg.norm(aligned_xyz - gt_xyz, axis=1)
    pred_R = np.stack([quat_xyzw(row[4:8]) for row in est])
    ang = []
    for Rp, Rg in zip(pred_R, gt_R[aligned_gt_ids]):
        dR = R.T @ Rp @ Rg.T
        ang.append(math.degrees(math.acos(float(np.clip((np.trace(dR)-1)/2, -1, 1)))))

    # Raw branch 0 is the pointmap in the first source camera; source_pair_ids
    # retains call order even though source_image_ids is sorted for audit.
    raw_by_input = {}
    for p in sorted((RUN / "exports/raw_pairs").glob("*.pt")):
        rec = torch.load(p, map_location="cpu", weights_only=True)
        pair = rec["source_pair_ids"][0]
        frame_id = int(pair[0])
        if frame_id not in raw_by_input:
            raw_by_input[frame_id] = (p, rec)
    # Read KITTI projection setup: LiDAR -> camera-0, rectification, then
    # camera-2 projection. All RGB frames are already synchronized+rectified.
    cc = read_calib(GT / "calibration/calib_cam_to_cam.txt")
    P = cc["P_rect_02"].reshape(3, 4)
    Rrect = np.eye(4); Rrect[:3, :3] = cc["R_rect_00"].reshape(3, 3)
    Tv = transform(calib_from_velo["R"].reshape(3, 3), calib_from_velo["T"])
    projection = P @ Rrect @ Tv
    # Input preprocessing: long side resized to 512, then centre-cropped to
    # 512x144 (KITTI 1242x375 -> 512x155 -> crop 5.5 px vertically).
    sx, sy = 512.0/1242.0, 155.0/375.0
    range_names = ["0-10m", "10-20m", "20-40m", "40-80m", "80-200m"]
    residual_by_bin = {name: [] for name in range_names}
    static_residual_by_bin = {name: [] for name in range_names}
    trajectory_scaled_residual_by_bin = {name: [] for name in range_names}
    trajectory_scaled_static_residual_by_bin = {name: [] for name in range_names}
    per_frame = []
    raw_frame_count = 0
    tracklet_boxes = read_tracklets()
    dynamic_masked = dynamic_lidar_total = 0
    for frame_i, row in enumerate(sampled):
        event = raw_by_input.get(frame_i)
        if event is None:
            continue
        raw_frame_count += 1
        path, rec = event
        pred = rec["outputs"][0]["pts3d"][0].numpy()
        original_i = 2 * frame_i
        scan = np.fromfile(GT / f"lidar/{original_i:010d}.bin", dtype=np.float32).reshape(-1, 4)[:, :3]
        dynamic = dynamic_point_mask(scan, original_i, tracklet_boxes)
        dynamic_masked += int(dynamic.sum())
        dynamic_lidar_total += len(scan)
        homog = np.column_stack([scan, np.ones(len(scan))])
        q = (projection @ homog.T).T
        z = q[:, 2]
        u = q[:, 0] / np.maximum(z, 1e-8)
        v = q[:, 1] / np.maximum(z, 1e-8)
        um = (u + .5)*sx - .5
        vm = (v + .5)*sy - .5 - 5.5
        ix, iy = np.rint(um).astype(int), np.rint(vm).astype(int)
        valid = (z > 0) & (u >= 0) & (u < 1242) & (v >= 0) & (v < 375) & (ix >= 0) & (ix < 512) & (iy >= 0) & (iy < 144)
        # Keep the nearest projected laser return for each model pixel.
        ids = np.flatnonzero(valid)
        key = iy[ids] * 512 + ix[ids]
        order = np.lexsort((z[ids], key))
        ids = ids[order]
        key_sorted = key[order]
        ids = ids[np.r_[True, key_sorted[1:] != key_sorted[:-1]]]
        d_pred = pred[iy[ids], ix[ids], 2]
        d_gt = z[ids]
        finite = np.isfinite(d_pred) & (d_pred > 0) & np.isfinite(d_gt)
        ids, d_pred, d_gt = ids[finite], d_pred[finite], d_gt[finite]
        err = d_pred - d_gt
        err_scaled = s * d_pred - d_gt
        static = ~dynamic[ids]
        for lo, hi, name in [(0,10,"0-10m"),(10,20,"10-20m"),(20,40,"20-40m"),(40,80,"40-80m"),(80,200,"80-200m")]:
            m = (d_gt >= lo) & (d_gt < hi)
            residual_by_bin[name].extend(err[m].tolist())
            static_residual_by_bin[name].extend(err[m & static].tolist())
            trajectory_scaled_residual_by_bin[name].extend(err_scaled[m].tolist())
            trajectory_scaled_static_residual_by_bin[name].extend(err_scaled[m & static].tolist())
        per_frame.append({"input_frame":frame_i,"original_kitti_frame":original_i,
            "raw_event":path.name,"valid_lidar_pixels":int(len(err)),
            "tracklet_static_lidar_pixels":int(static.sum()),
            "depth_error_median_signed":float(np.median(err)) if len(err) else None,
            "depth_abs_median":percentile(np.abs(err),50),"depth_abs_p95":percentile(np.abs(err),95)})

    metrics = {}
    for name, vals in residual_by_bin.items():
        a = np.asarray(vals)
        b = np.asarray(static_residual_by_bin[name])
        c = np.asarray(trajectory_scaled_residual_by_bin[name])
        d = np.asarray(trajectory_scaled_static_residual_by_bin[name])
        metrics[name] = {"all_count":int(a.size),"all_signed_median":percentile(a,50),
                         "all_absolute_median":percentile(np.abs(a),50),"all_absolute_p95":percentile(np.abs(a),95),
                         "tracklet_static_count":int(b.size),"tracklet_static_signed_median":percentile(b,50),
                         "tracklet_static_absolute_median":percentile(np.abs(b),50),
                         "tracklet_static_absolute_p95":percentile(np.abs(b),95),
                         "single_trajectory_scale":s,
                         "scaled_tracklet_static_signed_median":percentile(d,50),
                         "scaled_tracklet_static_absolute_median":percentile(np.abs(d),50),
                         "scaled_tracklet_static_absolute_p95":percentile(np.abs(d),95)}
    report = {
        "status":"evaluation_complete_with_gates_inconclusive",
        "run_dir":str(RUN.relative_to(ROOT)),
        "input_frames":120,"pose_rows":int(len(est)),"pose_coverage":float(len(est)/120),
        "keyframes":int(torch.load(RUN/"map"/f"{DRIVE}_kfgauss.pt",map_location="cpu",weights_only=True)["n"]),
        "longest_tracking_break_s":0.0 if len(est)==120 else None,
        "timestamp_max_abs_error_ms":float(time_err.max()*1000),
        "estimated_vs_oxts_single_sim3":{"scale":s,"translation_rmse_m":float(np.sqrt(np.mean(trans_err**2))),
            "translation_median_m":percentile(trans_err,50),"translation_p95_m":percentile(trans_err,95),
            "orientation_median_deg":percentile(np.asarray(ang),50),"orientation_p95_deg":percentile(np.asarray(ang),95)},
        "raw_local_pointmap_vs_projected_lidar":{"raw_input_frames_matched":raw_frame_count,
            "dynamic_tracklet_exclusion_applied":True,
            "tracklet_masked_lidar_fraction":dynamic_masked/max(1,dynamic_lidar_total),
            "residuals_are_unmasked_descriptive_only":False,
            "range_metrics":metrics,"per_frame":per_frame},
        "tracklets":{"count":tracklet_count(),"used_for_evaluation_mask":True,
            "mask":"KITTI annotated 3D tracklet boxes in each LiDAR scan frame"},
        "gates":{"pose_coverage_ge_95_percent":bool(len(est)/120 >= .95),
            "timestamp_match_le_50ms":bool(time_err.max() <= .050),
            "tracking_break_le_2s":bool(len(est)==120),
            "static_lidar_residual_gate":"PASS: at least 1000 matched points in every scored range bin" if all(metrics[n]["tracklet_static_count"] >= 1000 for n in range_names if n != "80-200m") else "INCONCLUSIVE: one or more scored range bins below 1000 static matches",
            "map_pose_oracle":"NOT RUN: evaluation pointmap trajectory is not yet verified for a complete raw-to-map oracle lineage"},
        "interpretation":"Do not attribute any residual to MASt3R alone. Tracklet boxes exclude annotated objects only; unlabelled dynamics can remain. Pose comparison is a single global Sim(3) fit.",
    }
    (OUT/"metrics.json").write_text(json.dumps(report,indent=2)+"\n")
    with (OUT/"raw_depth_per_frame.csv").open("w") as f:
        f.write("input_frame,original_kitti_frame,valid_lidar_pixels,depth_error_median_signed,depth_abs_median,depth_abs_p95\n")
        for x in per_frame:
            f.write(f"{x['input_frame']},{x['original_kitti_frame']},{x['valid_lidar_pixels']},{x['depth_error_median_signed']},{x['depth_abs_median']},{x['depth_abs_p95']}\n")
    print(json.dumps({k:v for k,v in report.items() if k not in {"raw_local_pointmap_vs_projected_lidar"}},indent=2))


if __name__ == "__main__":
    main()

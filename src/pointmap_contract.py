"""Explicit camera/local-unit contracts for offline Pointmap x Pose oracles.

No candidate selection or per-frame fitting is performed while constructing
arms. All matrices act on column vectors, with camera-to-world placement.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
from scipy.spatial.transform import Rotation


def array_hash(value):
    value = np.ascontiguousarray(value)
    header = json.dumps([value.dtype.str, value.shape], separators=(",", ":")).encode()
    return hashlib.sha256(header + value.tobytes()).hexdigest()


def sim3_from_xyzw(value):
    value = np.asarray(value, dtype=np.float64).reshape(8)
    if not np.isfinite(value).all() or value[7] <= 0:
        raise ValueError("Sim(3) needs finite t, xyzw quaternion and positive scale")
    if not np.isclose(np.linalg.norm(value[3:7]), 1, atol=2e-5, rtol=0):
        raise ValueError("Pose quaternion must be unit length and use xyzw ordering")
    result = np.eye(4)
    result[:3, :3] = value[7] * Rotation.from_quat(value[3:7]).as_matrix()
    result[:3, 3] = value[:3]
    return result


def sim3_parts(matrix):
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("Expected a finite 4x4 Sim(3)")
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-10, rtol=0):
        raise ValueError("Invalid homogeneous row")
    scale = np.cbrt(np.linalg.det(matrix[:3, :3]))
    if scale <= 0:
        raise ValueError("Reflection/nonpositive scale is not Sim(3)")
    rotation = matrix[:3, :3] / scale
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8, rtol=0):
        raise ValueError("Anisotropic or sheared pose is not Sim(3)")
    return float(scale), rotation, matrix[:3, 3].copy()


def transform_points(points, pose):
    points, pose = np.asarray(points), np.asarray(pose)
    return points @ pose[:3, :3].T + pose[:3, 3]


def transform_covariance(covariance, pose):
    linear = np.asarray(pose)[:3, :3]
    return linear @ covariance @ linear.T


def project(points, intrinsics):
    points = np.asarray(points, dtype=np.float64)
    if not np.isfinite(points).all() or np.any(points[..., 2] <= 0):
        raise ValueError("Projection requires finite points in front of camera")
    homogeneous = points @ np.asarray(intrinsics).T
    return homogeneous[..., :2] / homogeneous[..., 2:3]


def backproject_z(pixels, depth_z, intrinsics):
    pixels = np.asarray(pixels, dtype=np.float64)
    depth_z = np.asarray(depth_z, dtype=np.float64)
    if pixels.shape[:-1] != depth_z.shape or pixels.shape[-1] != 2:
        raise ValueError("Pixel/depth shapes differ")
    if not np.isfinite(pixels).all() or not np.isfinite(depth_z).all() or np.any(depth_z <= 0):
        raise ValueError("GT Z-depth must be finite and positive")
    rays = np.concatenate([pixels, np.ones((*depth_z.shape, 1))], axis=-1) @ np.linalg.inv(intrinsics).T
    rays = rays / rays[..., 2:3]
    return rays * depth_z[..., None]


def source_points_in_anchor(points, source_c2w, anchor_c2w):
    """Cross branch: source-camera -> anchor-camera; GT relative pose leaks in L."""
    for pose in (source_c2w, anchor_c2w):
        if not np.isclose(sim3_parts(pose)[0], 1, atol=1e-10):
            raise ValueError("GT branch conversion expects metric SE(3)")
    return transform_points(points, np.linalg.inv(anchor_c2w) @ source_c2w)


def fit_prefix_gauge(estimated_positions, gt_positions, original_frame_ids, stop_exclusive):
    """Fit one global gauge using only frame IDs below an explicit prefix end.

    The positions may be final-backend poses; this is an offline diagnostic,
    not an online prefix-only SLAM estimate. Test GT is excluded from the fit.
    """
    from e1_taxonomy import fit_sim3
    frame_ids = np.asarray(original_frame_ids)
    if len(np.unique(frame_ids)) != len(frame_ids) or np.any(np.diff(frame_ids) <= 0):
        raise ValueError("Frame IDs must be unique and sorted")
    if np.shape(estimated_positions) != np.shape(gt_positions) or np.shape(estimated_positions) != (len(frame_ids), 3):
        raise ValueError("One matched position per frame is required")
    selected = frame_ids < stop_exclusive
    if selected.sum() < 3 or selected.all():
        raise ValueError("Need >=3 prefix poses and a separate post-prefix region")
    gauge = fit_sim3(np.asarray(estimated_positions)[selected], np.asarray(gt_positions)[selected])
    sim3_parts(gauge)
    return gauge, frame_ids[selected].copy()


def metric_placement(raw_pose, gauge, local_m_per_raw):
    if not np.isfinite(local_m_per_raw) or local_m_per_raw <= 0:
        raise ValueError("One positive fixed local-unit conversion is required")
    sim3_parts(raw_pose)
    sim3_parts(gauge)
    result = np.asarray(gauge) @ raw_pose
    result = result.copy()
    result[:3, :3] /= local_m_per_raw
    sim3_parts(result)
    return result


def build_arms(raw_points, gt_local_m, raw_pose, gt_pose, gauge, local_m_per_raw, covariance_raw,
               candidate_ids, common_mask, attributes):
    """Four arms with the same registry/mask/local attributes and two factors.

    Local covariance is converted once by C^2; world covariance changes only
    with placement. Native filters MUST be frozen before this function.
    """
    if not np.isclose(sim3_parts(gt_pose)[0], 1, atol=1e-10):
        raise ValueError("GT placement must have unit scale")
    predicted = np.asarray(raw_points, dtype=np.float64) * local_m_per_raw
    oracle = np.asarray(gt_local_m, dtype=np.float64)
    covariance_m = np.asarray(covariance_raw, dtype=np.float64) * local_m_per_raw ** 2
    n = len(predicted)
    if oracle.shape != (n, 3) or covariance_m.shape != (n, 3, 3):
        raise ValueError("Local geometry/covariance sizes differ")
    if any(not np.isfinite(x).all() for x in (predicted, oracle, covariance_m)):
        raise ValueError("Nonfinite arm input")
    ids, mask = np.asarray(candidate_ids), np.asarray(common_mask)
    if ids.shape != (n,) or mask.shape != (n,) or mask.dtype != bool or len(np.unique(ids)) != n:
        raise ValueError("Invalid fixed candidate registry/mask")
    if any(len(np.asarray(v)) != n for v in attributes.values()):
        raise ValueError("Attribute size differs from registry")
    placement = metric_placement(raw_pose, gauge, local_m_per_raw)
    result = {}
    for name, local, pose in (("A00", predicted, placement), ("A10", oracle, placement),
                              ("A01", predicted, gt_pose), ("A11", oracle, gt_pose)):
        result[name] = {"candidate_ids": ids.copy(), "common_mask": mask.copy(),
                        "local_points_m": local.copy(), "placement": np.asarray(pose).copy(),
                        "local_covariance_m2": covariance_m.copy(),
                        "world_points_m": transform_points(local, pose),
                        "world_covariance_m2": transform_covariance(covariance_m, pose),
                        "attributes": {k: np.asarray(v).copy() for k, v in attributes.items()}}
    validate_arms(result)
    return result


def validate_arms(arms):
    if set(arms) != {"A00", "A10", "A01", "A11"}:
        raise ValueError("Exactly four arms are required")
    first = arms["A00"]
    for name, arm in arms.items():
        for key in ("candidate_ids", "common_mask", "local_covariance_m2"):
            if array_hash(arm[key]) != array_hash(first[key]):
                raise ValueError(f"{name}: changed {key}")
        if set(arm["attributes"]) != set(first["attributes"]):
            raise ValueError("Attribute names differ")
        for key in first["attributes"]:
            if array_hash(arm["attributes"][key]) != array_hash(first["attributes"][key]):
                raise ValueError(f"{name}: changed attribute {key}")
        sim3_parts(arm["placement"])
        np.testing.assert_allclose(arm["world_points_m"], transform_points(arm["local_points_m"], arm["placement"]), atol=1e-12)
        np.testing.assert_allclose(arm["world_covariance_m2"], transform_covariance(arm["local_covariance_m2"], arm["placement"]), atol=1e-12)
    for a, b, key in (("A00", "A10", "placement"), ("A01", "A11", "placement"),
                      ("A00", "A01", "local_points_m"), ("A10", "A11", "local_points_m")):
        if array_hash(arms[a][key]) != array_hash(arms[b][key]):
            raise ValueError(f"Non-independent intervention: {a}/{b}/{key}")
    if not np.isclose(sim3_parts(arms["A01"]["placement"])[0], 1, atol=1e-10):
        raise ValueError("GT arm scale is not one")


def stratified_subset(pixels, raw_depth_metric, common, hw, seed, grid_hw, depth_edges, per_stratum):
    """Sample by source pixel and predicted depth only; never by GT error."""
    pixels, depth = np.asarray(pixels), np.asarray(raw_depth_metric)
    h, w = hw
    gh, gw = grid_hw
    cells = np.minimum(pixels[:, 1] * gh // h, gh - 1) * gw + np.minimum(pixels[:, 0] * gw // w, gw - 1)
    bins = np.digitize(depth, depth_edges)
    labels = cells * (len(depth_edges) + 1) + bins
    rng = np.random.default_rng(seed)
    selected = []
    eligible = np.flatnonzero(common)
    for label in np.unique(labels[eligible]):
        group = eligible[labels[eligible] == label]
        selected.extend(rng.choice(group, min(per_stratum, len(group)), replace=False).tolist())
    return np.sort(np.asarray(selected, dtype=np.int64))

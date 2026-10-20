"""GT-free causal evidence features for E2. Missing evidence stays NaN."""
import warnings

import cv2
import numpy as np
from scipy.ndimage import uniform_filter, maximum_filter
from scipy.spatial import cKDTree

from e0b_audit import disjoint, transform

CROSS_METHODS = ("B6_depth_front", "B7_rgb_l1_region", "B7_rgb_ncc_region",
                 "P1_plane_front_1view", "P1_plane_front_2view")
METHODS = ("B2_confidence", "B2_opacity", "B5_self_residual", *CROSS_METHODS,
           "B8_dog_redundancy")


def causal_pair(candidate, evidence, decision_sequence, evidence_sequence):
    if evidence_sequence >= decision_sequence:
        raise ValueError("Future evidence cannot enter a decision")
    return disjoint(candidate, evidence)


def original_active(kf):
    """CPU float32 quantile matches the frozen original local filter."""
    import torch
    z = kf["means"][:, 2]
    return ((z > 0.05) & (z <= torch.quantile(z[z > 0.05], 0.98)) &
            (kf["scales"].max(-1).values < 1) & (kf["conf"] >= 1.5) &
            (kf["opacities"] > 0.3)).numpy()


def image_rgb(kf):
    return np.clip(kf["img"].numpy().transpose(1, 2, 0) * 0.5 + 0.5, 0, 1)


def prepare_observation(raw, image, spec):
    points = raw["pts3d"].numpy().reshape(*image.shape[:2], 3).astype(np.float64)
    confidence = raw["conf"].numpy().reshape(image.shape[:2])
    h, w = image.shape[:2]
    radius = np.linalg.norm(points, axis=-1)
    valid = (np.isfinite(points).all(-1) & (radius > 1e-8) & (points[..., 2] > 0) &
             (confidence >= spec["confidence_min"]))
    rays = points / np.maximum(radius[..., None], 1e-12)
    tree_indices = np.flatnonzero(valid)
    if not len(tree_indices):
        raise ValueError("No confident raw pointmap rays")
    tree = cKDTree(rays.reshape(-1, 3)[tree_indices])
    edge = ~valid
    for axis in (0, 1):
        a = [slice(None), slice(None)]
        b = a.copy()
        a[axis], b[axis] = slice(1, None), slice(None, -1)
        a, b = tuple(a), tuple(b)
        jump = np.abs(radius[a] - radius[b]) > spec["depth_edge_relative"] * np.minimum(radius[a], radius[b])
        jump |= ~valid[a] | ~valid[b]
        edge[a] |= jump
        edge[b] |= jump
    r = spec["patch_radius_pixels"]
    edge = maximum_filter(edge.astype(np.uint8), size=2 * r + 1, mode="constant", cval=1).astype(bool)
    edge[:r] = edge[-r:] = True
    edge[:, :r] = edge[:, -r:] = True
    weight = valid.astype(float)
    size = 2 * r + 1
    count = uniform_filter(weight, size, mode="constant") * size ** 2
    denom = np.maximum(count, 1)
    finite_points = np.where(valid[..., None], points, 0)
    mean = np.stack([uniform_filter(finite_points[..., j], size, mode="constant") * size ** 2 / denom
                     for j in range(3)], axis=-1)
    cov = np.empty((h, w, 3, 3))
    for j in range(3):
        for k in range(3):
            cov[..., j, k] = (uniform_filter(finite_points[..., j] * finite_points[..., k], size, mode="constant") *
                              size ** 2 / denom - mean[..., j] * mean[..., k])
    eigen, vectors = np.linalg.eigh(cov)
    normal = vectors[..., 0]
    normal[np.einsum("...i,...i->...", normal, mean) > 0] *= -1
    reliable = (valid & ~edge & (count >= spec["patch_min_points"]) &
                (eigen[..., 1] > 1e-12) &
                (eigen[..., 0] / np.maximum(eigen[..., 1], 1e-12) <= spec["plane_eigen_small_to_middle_max"]) &
                (eigen[..., 1] / np.maximum(eigen[..., 2], 1e-12) >= spec["plane_eigen_middle_to_large_min"]))
    spacing = np.full((h, w), np.inf)
    for axis in (0, 1):
        a = [slice(None), slice(None)]; b = a.copy()
        a[axis], b[axis] = slice(1, None), slice(None, -1)
        a, b = tuple(a), tuple(b)
        step = np.linalg.norm(points[a] - points[b], axis=-1)
        spacing[a] = np.minimum(spacing[a], step)
        spacing[b] = np.minimum(spacing[b], step)
    return dict(points=points.reshape(-1, 3), confidence=confidence.reshape(-1), image=image,
                radius=radius.reshape(-1), rays=rays.reshape(-1, 3), tree=tree, tree_indices=tree_indices,
                edge=edge.reshape(-1), patch_reliable=reliable.reshape(-1),
                mean=mean.reshape(-1, 3), normal=normal.reshape(-1, 3),
                spacing=np.maximum(spacing.reshape(-1), 1e-6), hw=(h, w))


def match_rays(points, observation, max_angle):
    radius = np.linalg.norm(points, axis=-1)
    valid = np.isfinite(points).all(-1) & (points[..., 2] > 0) & (radius > 1e-8)
    ids = np.zeros(len(points), dtype=np.int64)
    angle = np.full(len(points), np.inf)
    if valid.any():
        distance, nearest = observation["tree"].query(points[valid] / radius[valid, None], workers=2)
        ids[valid] = observation["tree_indices"][nearest]
        angle[valid] = np.degrees(2 * np.arcsin(np.clip(distance / 2, 0, 1)))
    return ids, valid & (angle <= max_angle), angle, radius


def photometric_warp(candidate, evidence, relative, candidate_ids, spec):
    """Depth-masked predicted-geometry patch warp; region-level attribution."""
    h, w = candidate["hw"]
    r = spec["patch_radius_pixels"]
    dy, dx = np.mgrid[-r:r + 1, -r:r + 1]
    offsets = (dy * w + dx).reshape(1, -1)
    size = offsets.shape[1]
    l1, ncc = np.full(len(candidate_ids), np.nan), np.full(len(candidate_ids), np.nan)
    for start in range(0, len(candidate_ids), 8192):
        ids = candidate_ids[start:start + 8192]
        pixel = ids[:, None] + offsets
        row, col = ids // w, ids % w
        in_source = (row >= r) & (row < h - r) & (col >= r) & (col < w - r)
        pixel = np.clip(pixel, 0, h * w - 1)
        p = transform(candidate["points"][pixel.reshape(-1)], relative)
        target, ray_ok, _, radius = match_rays(p, evidence, spec["ray_angle_max_degrees"])
        band = spec["occlusion_relative_band"] * evidence["radius"][target]
        good = ray_ok & (radius - evidence["radius"][target] <= band) & ~evidence["edge"][target]
        good = good.reshape(-1, size) & in_source[:, None]
        good &= candidate["confidence"][pixel] >= spec["confidence_min"]
        source_rgb = candidate["image"].reshape(-1, 3)[pixel]
        target_rgb = evidence["image"].reshape(-1, 3)[target].reshape(-1, size, 3)
        count = good.sum(1)
        usable = count >= int(np.ceil(size * spec["rgb_patch_min_valid_fraction"]))
        difference = np.mean(np.abs(source_rgb - target_rgb), axis=2)
        l1[start:start + len(ids)][usable] = (np.sum(difference * good, axis=1) / np.maximum(count, 1))[usable]
        gray_a = source_rgb @ np.array([0.299, 0.587, 0.114])
        gray_b = target_rgb @ np.array([0.299, 0.587, 0.114])
        ma = (gray_a * good).sum(1) / np.maximum(count, 1)
        mb = (gray_b * good).sum(1) / np.maximum(count, 1)
        a, b = (gray_a - ma[:, None]) * good, (gray_b - mb[:, None]) * good
        va, vb = (a * a).sum(1) / np.maximum(count, 1), (b * b).sum(1) / np.maximum(count, 1)
        textured = usable & (va >= spec["rgb_patch_std_min"] ** 2) & (vb >= spec["rgb_patch_std_min"] ** 2)
        correlation = (a * b).sum(1) / np.maximum(np.sqrt((a * a).sum(1) * (b * b).sum(1)), 1e-12)
        ncc[start:start + len(ids)][textured] = (1 - np.clip(correlation, -1, 1))[textured]
    return l1, ncc


def cross_pair(means, covariance, candidate, evidence, candidate_pose, evidence_pose, spec):
    relative = np.linalg.inv(evidence_pose) @ candidate_pose
    p = transform(means, relative)
    ids, ray_ok, angle, radius = match_rays(p, evidence, spec["ray_angle_max_degrees"])
    world = transform(means, candidate_pose)
    a, b = world - candidate_pose[:3, 3], world - evidence_pose[:3, 3]
    cosine = np.einsum("ij,ij->i", a, b) / np.maximum(np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1), 1e-12)
    parallax = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
    ray = p / np.maximum(radius[:, None], 1e-12)
    cov = relative[:3, :3] @ covariance @ relative[:3, :3].T
    sigma = np.sqrt(np.maximum(np.einsum("ni,nij,nj->n", ray, cov, ray), 0))
    band = np.maximum(spec["occlusion_relative_band"] * evidence["radius"][ids], spec["occlusion_gaussian_sigma"] * sigma)
    base = (ray_ok & (parallax >= spec["parallax_min_degrees"]) &
            (candidate["confidence"] >= spec["confidence_min"]) & ~evidence["edge"][ids])
    occluded = base & (radius - evidence["radius"][ids] > band)
    good = base & ~occluded
    depth = np.full(len(means), np.nan)
    depth[good] = np.maximum(0, (evidence["radius"][ids[good]] - radius[good] -
                                 spec["occlusion_gaussian_sigma"] * sigma[good]) / evidence["radius"][ids[good]])
    plane = np.full(len(means), np.nan)
    reliable = good & evidence["patch_reliable"][ids]
    normal = evidence["normal"][ids]
    sigma_plane = np.sqrt(np.maximum(np.einsum("ni,nij,nj->n", normal, cov, normal), 0))
    signed = np.einsum("ni,ni->n", normal, p - evidence["mean"][ids])
    plane[reliable] = np.maximum(0, (signed[reliable] - spec["occlusion_gaussian_sigma"] * sigma_plane[reliable]) /
                                 evidence["spacing"][ids[reliable]])
    l1, ncc = np.full(len(means), np.nan), np.full(len(means), np.nan)
    rgb_eligible = good & ~candidate["edge"]
    selected = np.flatnonzero(rgb_eligible)
    if len(selected):
        l1[selected], ncc[selected] = photometric_warp(candidate, evidence, relative, selected, spec)
    return dict(B6_depth_front=depth, B7_rgb_l1_region=l1, B7_rgb_ncc_region=ncc,
                P1_plane_front_1view=plane), dict(ray_and_parallax=int((ray_ok & (parallax >= spec["parallax_min_degrees"])).sum()),
                depth_eligible=int(good.sum()), occluded=int(occluded.sum()), plane_eligible=int(reliable.sum()),
                rgb_l1_eligible=int(np.isfinite(l1).sum()), rgb_ncc_eligible=int(np.isfinite(ncc).sum()))


def median_views(values, n):
    if not values:
        return np.full(n, np.nan), np.zeros(n, np.uint8)
    stack = np.stack(values)
    count = np.isfinite(stack).sum(0).astype(np.uint8)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        score = np.nanmedian(stack, axis=0)
    return score, count


def fit_camera(points, confidence, hw, spec):
    h, w = hw
    y, x = np.indices(hw)
    p = points.reshape(h, w, 3)
    keep = (np.isfinite(p).all(-1) & (p[..., 2] > 0) & (confidence.reshape(hw) >= spec["confidence_min"]))
    grid = np.zeros(hw, bool); grid[::spec["camera_fit_grid_stride"], ::spec["camera_fit_grid_stride"]] = True
    sample = keep & grid
    K = np.eye(3)
    for axis, pixels in ((0, x), (1, y)):
        coordinate = p[..., axis] / np.maximum(p[..., 2], 1e-12)
        design = np.stack([coordinate[sample], np.ones(sample.sum())], axis=1)
        focal, center = np.linalg.lstsq(design, pixels[sample], rcond=None)[0]
        if not np.isfinite(focal) or focal <= 0:
            raise ValueError("Invalid predicted pinhole surrogate")
        K[axis, axis], K[axis, 2] = focal, center
    predicted_rays = np.stack([(x - K[0, 2]) / K[0, 0], (y - K[1, 2]) / K[1, 1], np.ones(hw)], axis=-1)
    predicted_rays /= np.linalg.norm(predicted_rays, axis=-1, keepdims=True)
    rays = p / np.maximum(np.linalg.norm(p, axis=-1, keepdims=True), 1e-12)
    angle = np.degrees(np.arccos(np.clip(np.einsum("...i,...i->...", predicted_rays, rays), -1, 1)))
    eligible = keep & (angle <= spec["camera_fit_angular_error_max_degrees"])
    return K, eligible.reshape(-1), dict(median_ray_error_degrees=float(np.median(angle[keep])),
                                         p95_ray_error_degrees=float(np.percentile(angle[keep], 95)),
                                         fit_eligible_fraction=float(eligible.mean()))


def dog(image, sigmas):
    small = cv2.GaussianBlur(image.astype(np.float32), (0, 0), sigmas[0], borderType=cv2.BORDER_REFLECT101)
    large = cv2.GaussianBlur(image.astype(np.float32), (0, 0), sigmas[1], borderType=cv2.BORDER_REFLECT101)
    return np.linalg.norm(small - large, axis=-1)


def sample_bilinear(image, x, y):
    h, w = image.shape[:2]
    good = np.isfinite(x) & np.isfinite(y) & (x >= 0) & (x <= w - 1) & (y >= 0) & (y <= h - 1)
    sx, sy = np.clip(np.nan_to_num(x), 0, w - 1), np.clip(np.nan_to_num(y), 0, h - 1)
    x0, y0 = np.floor(sx).astype(int), np.floor(sy).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    dx, dy = sx - x0, sy - y0
    value = ((1 - dx) * (1 - dy) * image[y0, x0] + dx * (1 - dy) * image[y0, x1] +
             (1 - dx) * dy * image[y1, x0] + dx * dy * image[y1, x1])
    value[~good] = np.nan
    return value, good

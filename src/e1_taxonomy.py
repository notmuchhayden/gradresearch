"""Evaluation-only E1 geometry diagnostics. No map/admission updates.

GT depth is camera z. Behind-surface, missing GT, depth edges and conflicting
views cannot certify a front error. These labels remain geometric proxies.
"""
import cv2
import numpy as np
from scipy.spatial import cKDTree

LABELS = {0: "unobserved_or_ambiguous", 1: "well_placed_proxy",
          2: "redundant_but_valid_proxy", 3: "repeated_front_error_proxy"}


def transform(points, matrix):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def fit_sim3(source, target):
    source, target = np.asarray(source), np.asarray(target)
    if len(source) < 3 or not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("At least three finite pose pairs required")
    a, b = source - source.mean(0), target - target.mean(0)
    if np.linalg.matrix_rank(a, tol=1e-8) < 2:
        raise ValueError("Degenerate trajectory alignment")
    u, values, vt = np.linalg.svd(b.T @ a / len(a))
    sign = np.eye(3)
    sign[2, 2] = np.sign(np.linalg.det(u @ vt))
    rotation = u @ sign @ vt
    scale = float(np.sum(values * np.diag(sign)) / np.mean(np.sum(a * a, axis=1)))
    matrix = np.eye(4)
    matrix[:3, :3] = scale * rotation
    matrix[:3, 3] = target.mean(0) - scale * rotation @ source.mean(0)
    if scale <= 0 or not np.isfinite(matrix).all():
        raise ValueError("Invalid alignment")
    return matrix


def camera_geometry(camera, size=512):
    """Exact integer resize and center crop used by upstream resize_img."""
    raw_w, raw_h = camera["w"], camera["h"]
    ratio = size / max(raw_w, raw_h)
    w, h = round(raw_w * ratio), round(raw_h * ratio)
    half_w, half_h = (w // 16) * 8, (h // 16) * 8
    if w == h:
        half_h = 3 * half_w // 4
    left, top = w // 2 - half_w, h // 2 - half_h
    K = np.array([[camera["fx"] * w / raw_w, 0, camera["cx"] * w / raw_w - left],
                  [0, camera["fy"] * h / raw_h, camera["cy"] * h / raw_h - top],
                  [0, 0, 1.]])
    return K, (h, w), (top, left, half_h * 2, half_w * 2)


def resize_depth(depth, camera):
    _, (h, w), (top, left, out_h, out_w) = camera_geometry(camera)
    result = cv2.resize(depth, (w, h), interpolation=cv2.INTER_NEAREST)
    return result[top:top + out_h, left:left + out_w]


def depth_masks(depth, spec):
    lo, hi = spec["depth_valid_range_m"]
    valid = np.isfinite(depth) & (depth >= lo) & (depth <= hi)
    edge = ~valid
    for axis in (0, 1):
        a = [slice(None), slice(None)]
        b = [slice(None), slice(None)]
        a[axis], b[axis] = slice(1, None), slice(None, -1)
        a, b = tuple(a), tuple(b)
        cutoff = np.maximum(spec["depth_edge_abs_m"],
                            spec["depth_edge_relative"] * np.minimum(depth[a], depth[b]))
        discontinuity = (np.abs(depth[a] - depth[b]) > cutoff) | ~valid[a] | ~valid[b]
        edge[a] |= discontinuity
        edge[b] |= discontinuity
    radius = spec["depth_edge_dilation_pixels"]
    if radius:
        edge = cv2.dilate(edge.astype(np.uint8), np.ones((2 * radius + 1,) * 2, np.uint8)).astype(bool)
    # Image borders have no reliable local patch.
    edge[:2] = edge[-2:] = True
    edge[:, :2] = edge[:, -2:] = True
    return valid, edge


def backproject(depth, K):
    y, x = np.indices(depth.shape)
    return np.stack([(x - K[0, 2]) * depth / K[0, 0],
                     (y - K[1, 2]) * depth / K[1, 1], depth], axis=-1)


def gt_surface(views, K, stride):
    points, normals = [], []
    for view in views:
        local = backproject(view["depth"], K)
        dx = np.roll(local, -1, 1) - np.roll(local, 1, 1)
        dy = np.roll(local, -1, 0) - np.roll(local, 1, 0)
        normal = np.cross(dx, dy)
        norm = np.linalg.norm(normal, axis=-1)
        keep = view["valid"] & ~view["edge"] & (norm > 1e-10)
        grid = np.zeros(keep.shape, bool)
        grid[::stride, ::stride] = True
        keep &= grid
        points.append(transform(local[keep], view["pose"]))
        normals.append(normal[keep] / norm[keep, None] @ view["pose"][:3, :3].T)
    if not points or not sum(map(len, points)):
        raise ValueError("No reliable GT surface samples")
    return np.concatenate(points), np.concatenate(normals)


def classify(means, covariance, views, K, spec, absolute_tolerance=None):
    """Multi-view center and 3-sigma z-envelope classifications in world metres.

    Parallax qualification is conservative: one later front ray must differ
    from the first front ray by the minimum angle. An occluded candidate is
    ambiguous, never a front error. No learned confidence is used in GT labels.
    """
    n = len(means)
    abs_tol = spec["depth_tolerance_abs_m"] if absolute_tolerance is None else absolute_tolerance
    result = {}
    counters = {}
    for name in ("center", "ellipsoid"):
        counters[name] = dict(front=np.zeros(n, np.uint16), support=np.zeros(n, np.uint16),
                              behind=np.zeros(n, np.uint16), diverse=np.zeros(n, bool),
                              first_ray=np.zeros((n, 3), np.float32))
    reliable = np.zeros(n, np.uint16)
    footprint_max = np.zeros(n, np.float32)
    for view in views:
        h, w = view["depth"].shape
        R = view["pose"][:3, :3]
        for start in range(0, n, 131072):
            stop = min(n, start + 131072)
            p = (means[start:stop] - view["pose"][:3, 3]) @ R
            z = p[:, 2]
            finite = np.isfinite(p).all(1) & (z > 0.1)
            u = np.zeros(len(p), np.int64)
            v = u.copy()
            u[finite] = np.rint(K[0, 0] * p[finite, 0] / z[finite] + K[0, 2]).astype(np.int64)
            v[finite] = np.rint(K[1, 1] * p[finite, 1] / z[finite] + K[1, 2]).astype(np.int64)
            inside = finite & (u >= 0) & (u < w) & (v >= 0) & (v < h)
            u, v = np.clip(u, 0, w - 1), np.clip(v, 0, h - 1)
            good = inside & view["valid"][v, u] & ~view["edge"][v, u]
            reliable[start:stop] += good
            d = view["depth"][v, u]
            tol = np.maximum(abs_tol, spec["depth_tolerance_relative"] * d)
            variance = np.einsum("i,nij,j->n", R[:, 2], covariance[start:stop], R[:, 2])
            envelope = spec["ellipsoid_sigma"] * np.sqrt(np.maximum(variance, 0))
            ray = p / np.maximum(np.linalg.norm(p, axis=1, keepdims=True), 1e-12) @ R.T
            for name, extent in (("center", 0), ("ellipsoid", envelope)):
                c = counters[name]
                front = good & (z + extent < d - tol)
                behind = good & (z - extent > d + tol)
                support = good & ~front & ~behind
                first = front & (c["front"][start:stop] == 0)
                previous = c["first_ray"][start:stop]
                previous[first] = ray[first]
                cosine = np.einsum("ij,ij->i", previous, ray)
                c["diverse"][start:stop] |= front & (cosine <= np.cos(np.radians(spec["repeated_front_min_parallax_degrees"])))
                c["front"][start:stop] += front
                c["support"][start:stop] += support
                c["behind"][start:stop] += behind
                if name == "ellipsoid" and front.any():
                    mass = projected_opacity_area(p[front], covariance[start:stop][front], R, K)
                    current = footprint_max[start:stop]
                    current[front] = np.maximum(current[front], mass)
    for name, c in counters.items():
        bad = ((c["front"] >= spec["repeated_front_min_views"]) & c["diverse"] & (c["support"] == 0))
        valid = (c["support"] >= 1) & (c["front"] == 0)
        result[name + "_front"] = bad
        result[name + "_valid"] = valid
        for key in ("front", "support", "behind"):
            result[name + "_" + key + "_views"] = c[key]
    labels = np.zeros(n, np.uint8)
    labels[result["center_valid"]] = 1
    labels[result["center_front"] & result["ellipsoid_front"]] = 3
    result.update(labels=labels, reliable_gt_views=reliable, footprint_area_max=footprint_max)
    return result


def projected_opacity_area(camera_means, world_covariance, camera_rotation, K):
    """Effective isolated screen-space Gaussian area; multiply by opacity.

    This is a linearized, unbounded-footprint proxy, not clipped pixel mass or
    actual transmittance-weighted contribution. 0.3 I matches rasterizer floor.
    """
    p = camera_means
    J = np.zeros((len(p), 2, 3))
    J[:, 0, 0], J[:, 1, 1] = K[0, 0] / p[:, 2], K[1, 1] / p[:, 2]
    J[:, 0, 2] = -K[0, 0] * p[:, 0] / p[:, 2] ** 2
    J[:, 1, 2] = -K[1, 1] * p[:, 1] / p[:, 2] ** 2
    A = J @ camera_rotation.T
    screen = A @ world_covariance @ A.transpose(0, 2, 1) + np.eye(2) * 0.3
    return 2 * np.pi * np.sqrt(np.maximum(np.linalg.det(screen), 0))


def mark_redundancy(labels, means, normals, anchor_ids, active, spec):
    """Only cross-KF valid neighbors; active and raw universes stay separate."""
    labels = labels.copy()
    previous = []
    for anchor in np.unique(anchor_ids):
        ids = np.flatnonzero((anchor_ids == anchor) & (labels == 1) & active)
        if previous and len(ids):
            old = np.concatenate(previous)
            distance, match = cKDTree(means[old]).query(means[ids], workers=2)
            cosine = np.abs(np.einsum("ij,ij->i", normals[ids], normals[old[match]]))
            duplicate = ((distance <= spec["duplicate_distance_m"]) &
                         (cosine >= np.cos(np.radians(spec["duplicate_normal_max_angle_degrees"]))))
            labels[ids[duplicate]] = 2
        if len(ids):
            previous.append(ids)
    return labels


def counts(labels, mask=None):
    if mask is not None:
        labels = labels[mask]
    return {name: {"count": int(np.sum(labels == code)),
                   "fraction": float(np.mean(labels == code)) if len(labels) else None}
            for code, name in LABELS.items()}

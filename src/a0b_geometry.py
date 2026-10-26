"""Sparse LiDAR projection for A0b; no depth interpolation or pose fitting."""
import ast
import cv2
import numpy as np


def load_calibrations(path):
    result = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return result


def camera_model(calibrations, name):
    key = "HK_GNSS_calibration" if name == "legacy_HK_GNSS" else "HKairport_calibration"
    source = calibrations[key]
    K = np.array(source["camera_intrinsic"], float).reshape(3, 3)
    R = np.array(source["camera_ext_R"], float).reshape(3, 3)
    if name == "HKairport_polar":
        u, _, vt = np.linalg.svd(R)
        R = u @ np.diag([1., 1., np.linalg.det(u @ vt)]) @ vt
    distortion = np.array(source["camera_dist_coeffs"], float)
    if name == "HKairport_zero_distortion":
        distortion[:] = 0
    return dict(K=K, R=R, t=np.array(source["camera_ext_t"], float), distortion=distortion,
                source_key=key, determinant=float(np.linalg.det(R)),
                orthogonality_max=float(np.abs(R @ R.T - np.eye(3)).max()))


def resize_contract(width=2448, height=2048, target=512):
    nw, nh = round(width * target / max(width, height)), round(height * target / max(width, height))
    cw, ch = nw // 16 * 16, nh // 16 * 16
    if nw == nh:
        ch = 3 * cw // 4
    left, top = nw // 2 - cw // 2, nh // 2 - ch // 2
    A = np.array([[nw / width, 0., -left], [0., nh / height, -top], [0., 0., 1.]])
    return A, (ch, cw), (nw, nh), (left, top)


def processed_rgb(raw_rgb, model=None):
    from PIL import Image
    if model is not None:
        raw_rgb = cv2.undistort(raw_rgb, model["K"], model["distortion"], None, model["K"])
    _, hw, resize, (left, top) = resize_contract(raw_rgb.shape[1], raw_rgb.shape[0])
    im = Image.fromarray(raw_rgb).resize(resize, Image.Resampling.LANCZOS)
    return np.asarray(im.crop((left, top, left + hw[1], top + hw[0])))


def rasterize(uv, z, hw, min_depth=2., max_depth=200., edge_abs=.5, edge_rel=.02):
    """Nearest cell Z buffer, excluding discontinuities only where measured."""
    uv, z = np.asarray(uv), np.asarray(z)
    h, w = hw
    finite = np.isfinite(uv).all(1) & np.isfinite(z) & (z >= min_depth) & (z <= max_depth)
    # Filter before integer conversion, including nonfinite/out-of-FOV inputs.
    finite &= (uv[:, 0] >= -.5) & (uv[:, 0] < w - .5) & (uv[:, 1] >= -.5) & (uv[:, 1] < h - .5)
    xy = np.floor(uv[finite] + .5).astype(np.int64)
    ids = xy[:, 1] * w + xy[:, 0]
    low, high = np.full(h * w, np.inf), np.full(h * w, -np.inf)
    np.minimum.at(low, ids, z[finite]); np.maximum.at(high, ids, z[finite])
    count = np.bincount(ids, minlength=h * w).reshape(hw)
    observed = np.isfinite(low).reshape(hw)
    depth = np.where(observed, low.reshape(hw), 0).astype(np.float32)
    spread = np.zeros(h * w)
    spread[np.isfinite(low)] = high[np.isfinite(low)] - low[np.isfinite(low)]
    edge = observed & (spread.reshape(hw) > np.maximum(edge_abs, edge_rel * depth))
    for dy, dx in [(0, 1), (1, 0)]:
        a = (slice(0, h-dy or None), slice(0, w-dx or None))
        b = (slice(dy, None), slice(dx, None))
        jump = observed[a] & observed[b] & (np.abs(depth[a]-depth[b]) > np.maximum(edge_abs, edge_rel*np.minimum(depth[a],depth[b])))
        edge[a] |= jump; edge[b] |= jump
    edge = cv2.dilate(edge.astype(np.uint8), np.ones((3,3), np.uint8)).astype(bool) & observed
    valid = observed & ~edge
    return depth, valid, edge, count


def lidar_depth(points, model, distorted):
    xyz = np.asarray(points, float) @ model["R"].T + model["t"]
    good = np.isfinite(xyz).all(1) & (xyz[:,2] > 0)
    xyz = xyz[good]
    uv = cv2.projectPoints(xyz, np.zeros(3), np.zeros(3), model["K"],
                           model["distortion"] if distorted else np.zeros(5))[0].reshape(-1,2)
    A, hw, _, _ = resize_contract()
    uv = uv @ A[:2,:2].T + A[:2,2]
    depth, valid, edge, count = rasterize(uv, xyz[:,2], hw)
    return dict(depth=depth, valid=valid, edge=edge, count=count,
                positive_z_count=len(xyz), projected_count=int(count.sum()))


def source_rays(pixels, model):
    A, _, _, _ = resize_contract()
    raw = (np.asarray(pixels) - A[:2,2]) @ np.linalg.inv(A[:2,:2]).T
    xy = cv2.undistortPoints(raw.reshape(-1,1,2), model["K"], model["distortion"]).reshape(-1,2)
    return np.column_stack([xy, np.ones(len(xy))])


def sampson_pixels(first, second, first_c2w, second_c2w, K):
    relative = np.linalg.inv(second_c2w) @ first_c2w
    t = relative[:3,3]
    tx = np.array([[0,-t[2],t[1]], [t[2],0,-t[0]], [-t[1],t[0],0]])
    F = np.linalg.inv(K).T @ tx @ relative[:3,:3] @ np.linalg.inv(K)
    x = np.column_stack([first, np.ones(len(first))]); y = np.column_stack([second, np.ones(len(second))])
    fx = x @ F.T; fty = y @ F
    denom = np.sum(fx[:,:2]**2,axis=1) + np.sum(fty[:,:2]**2,axis=1)
    return np.abs(np.sum(y*fx,axis=1)) / np.sqrt(np.maximum(denom,1e-30))

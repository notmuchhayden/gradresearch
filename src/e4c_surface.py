"""GT-free, center-excluded surface evidence for E4c. No disk I/O."""
import numpy as np
from e0b_audit import transform
from e2_signals import match_rays


def partition(lineage, audit_indices=(2, 3)):
    audit = [i for i in audit_indices if i < len(lineage)]
    for row in lineage:
        if not row['source_images']:
            raise ValueError('Unknown source ancestry')
    images = {v for i in audit for v in lineage[i]['source_images']}
    policy = [i for i, r in enumerate(lineage)
              if i not in audit and not images.intersection(r['source_images'])]
    return policy, audit


def fit_pca(points, mask):
    count = mask.sum(1)
    p = np.where(mask[..., None], points, 0)
    mean = p.sum(1) / np.maximum(count[:, None], 1)
    delta = np.where(mask[..., None], points - mean[:, None], 0)
    cov = np.einsum('nki,nkj->nij', delta, delta) / np.maximum(count[:, None, None], 1)
    eigen, vectors = np.linalg.eigh(cov)
    normal = vectors[:, :, 0].copy()
    normal[np.einsum('ni,ni->n', normal, mean) > 0] *= -1
    reliable = ((count >= 3) & (eigen[:, 1] > 1e-12) &
                (eigen[:, 0] / np.maximum(eigen[:, 1], 1e-12) <= .1) &
                (eigen[:, 1] / np.maximum(eigen[:, 2], 1e-12) >= .05))
    return mean, normal, eigen, vectors[:, :, 1:], reliable


def fit_patches(observation, radius=2, robust=True, audit=False, batch=2048):
    """Policy: one 20% trim. Audit: deterministic 64-hypothesis RANSAC.

    Retain inlier coordinates so hull containment is evaluated exactly via
    the largest angular gap, without unbounded plane support.
    """
    h, w = observation['hw']; points = observation['points']
    offsets = np.array([(dy, dx) for dy in range(-radius, radius + 1)
                        for dx in range(-radius, radius + 1) if dy or dx])
    k = len(offsets); total = len(points)
    valid = (np.isfinite(points).all(1) & (points[:, 2] > 0) &
             (observation['confidence'] >= 1.5))
    fields = dict(mean=np.zeros((total, 3)), normal=np.zeros((total, 3)),
                  basis=np.zeros((total, 3, 2)), scale=np.zeros(total),
                  spacing=np.zeros(total), reliable=np.zeros(total, bool),
                  xy=np.full((total, k, 2), np.nan, np.float32),
                  inliers=np.zeros((total, k), bool))
    minimum = 18 if audit else 9
    rng = np.random.default_rng(0)
    triples = np.array([rng.choice(k, 3, replace=False) for _ in range(64)])
    for begin in range(0, total, batch):
        end = min(begin + batch, total); center = np.arange(begin, end)
        y, x = center // w, center % w
        yy, xx = y[:, None] + offsets[:, 0], x[:, None] + offsets[:, 1]
        inside = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
        indices = np.clip(yy, 0, h - 1) * w + np.clip(xx, 0, w - 1)
        q = points[indices]; mask = inside & valid[indices]
        q = np.where(np.isfinite(q), q, 0)
        # Every point is connected to a valid horizontal/vertical neighbour.
        steps = []
        for axis in (0, 1):
            step_ids = indices + (w if axis == 0 else 1)
            ok = inside & ((yy < h - 1) if axis == 0 else (xx < w - 1))
            si = np.clip(step_ids, 0, total - 1)
            distance = np.linalg.norm(q - points[si], axis=2)
            steps.append(np.where(ok & mask & valid[si] & (si != center[:, None]), distance, np.nan))
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            spacing = np.nanmedian(np.concatenate(steps, axis=1), axis=1)
        spacing = np.where(np.isfinite(spacing), spacing, 0)
        original_count = mask.sum(1)
        if audit:
            best = np.zeros_like(mask); best_count = np.zeros(len(center), int)
            for a, b, c in triples:
                n = np.cross(q[:, b] - q[:, a], q[:, c] - q[:, a])
                length = np.linalg.norm(n, axis=1)
                n /= np.maximum(length[:, None], 1e-20)
                residual = np.abs(np.einsum('nki,ni->nk', q - q[:, a, None], n))
                good = (mask & (residual <= 2 * spacing[:, None]) &
                        (length[:, None] > 1e-15) &
                        (mask[:, a] & mask[:, b] & mask[:, c])[:, None])
                count = good.sum(1); replace = count > best_count
                best[replace] = good[replace]; best_count[replace] = count[replace]
            mask = best
        elif robust:
            mean, normal, _, _, _ = fit_pca(q, mask)
            error = np.abs(np.einsum('nki,ni->nk', q - mean[:, None], normal))
            # Stable offset order is row-major pixel order; trim ceil(20%).
            order = np.argsort(np.where(mask, error, np.inf), axis=1, kind='stable')
            rank = np.argsort(order, axis=1)
            mask &= rank < np.floor(.8 * original_count).astype(int)[:, None]
        mean, normal, eigen, basis, reliable = fit_pca(q, mask)
        error = np.einsum('nki,ni->nk', q - mean[:, None], normal)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            median = np.nanmedian(np.where(mask, error, np.nan), axis=1)
            mad = 1.4826 * np.nanmedian(np.where(mask, np.abs(error - median[:, None]), np.nan), axis=1)
        reliable &= ((mask.sum(1) >= minimum) & ~observation['edge'][center] &
                     valid[center] & (spacing > 0) &
                     (y >= radius) & (y < h - radius) & (x >= radius) & (x < w - radius))
        if audit:
            reliable &= mask.sum(1) >= .8 * original_count
        xy = np.einsum('nki,nij->nkj', q - mean[:, None], basis)
        fields['mean'][begin:end] = mean; fields['normal'][begin:end] = normal
        fields['basis'][begin:end] = basis; fields['scale'][begin:end] = np.nan_to_num(mad)
        fields['spacing'][begin:end] = spacing; fields['reliable'][begin:end] = reliable
        fields['xy'][begin:end] = np.where(mask[..., None], xy, np.nan)
        fields['inliers'][begin:end] = mask
    return fields


def hull_contains(xy, query):
    delta = xy - query[:, None]
    valid = np.isfinite(delta).all(2)
    angle = np.arctan2(delta[:, :, 1], delta[:, :, 0])
    order = np.sort(np.where(valid, angle, np.inf), axis=1)
    count = valid.sum(1); rows = np.arange(len(xy))
    last = order[rows, np.maximum(count - 1, 0)]
    with np.errstate(invalid='ignore'):
        gaps = np.diff(order, axis=1)
    gaps = np.where(np.arange(xy.shape[1] - 1)[None] < (count - 1)[:, None], gaps, 0)
    with np.errstate(invalid='ignore'):
        biggest = np.maximum(gaps.max(1), order[:, 0] + 2 * np.pi - last)
    # A query coincident with an inlier is inside, including polygon boundary.
    coincident = np.any(valid & (np.linalg.norm(delta, axis=2) < 1e-10), axis=1)
    return (count >= 3) & ((biggest <= np.pi + 1e-7) | coincident)


def view_geometry(means, covariance, candidate, evidence, fit, a_pose, b_pose, local=False):
    relative = np.linalg.inv(b_pose) @ a_pose
    p = transform(means, relative)
    if local:
        ids = np.arange(len(p)); ray_ok = np.ones(len(p), bool)
        radius = np.linalg.norm(p, axis=1)
    else:
        ids, ray_ok, _, radius = match_rays(p, evidence, 1.)
    cov = relative[:3, :3] @ covariance @ relative[:3, :3].T
    normal = fit['normal'][ids]
    sigma = np.sqrt(np.maximum(np.einsum('ni,nij,nj->n', normal, cov, normal), 0))
    ray = p / np.maximum(radius[:, None], 1e-12)
    sigma_ray = np.sqrt(np.maximum(np.einsum('ni,nij,nj->n', ray, cov, ray), 0))
    delta = p - fit['mean'][ids]; signed = np.einsum('ni,ni->n', normal, delta)
    query = np.einsum('ni,nij->nj', delta, fit['basis'][ids])
    in_hull = hull_contains(fit['xy'][ids], query)
    world = transform(means, a_pose)
    look_a, look_b = world - a_pose[:3, 3], world - b_pose[:3, 3]
    direction = look_b / np.maximum(np.linalg.norm(look_b, axis=1, keepdims=True), 1e-12)
    cosine = np.einsum('ni,ni->n', look_a, look_b) / np.maximum(
        np.linalg.norm(look_a, axis=1) * np.linalg.norm(look_b, axis=1), 1e-12)
    parallax = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
    band = np.maximum(.03 * evidence['radius'][ids], 3 * sigma_ray)
    visible = radius - evidence['radius'][ids] <= band
    eligible = (ray_ok & fit['reliable'][ids] & in_hull &
                (candidate['confidence'] >= 1.5) & visible)
    if not local:
        eligible &= parallax >= 1.
    front = evidence['radius'][ids] - radius > 3 * sigma_ray + .03 * evidence['radius'][ids]
    return dict(eligible=eligible, signed=signed, sigma=sigma, front=front,
                depth=np.maximum(0, evidence['radius'][ids] - radius - 3 * sigma_ray) /
                      np.maximum(evidence['radius'][ids], 1e-12),
                direction=direction, ids=ids)


def states(geometry, fit, cs=3, ch=1, audit=False):
    ids = geometry['ids']
    tau = (2 * fit['spacing'][ids] if audit else np.maximum.reduce([
        cs * fit['scale'][ids], ch * fit['spacing'][ids],
        1e-6 * np.linalg.norm(fit['mean'][ids], axis=1)]))
    signed, sigma = geometry['signed'], geometry['sigma']
    eligible = geometry['eligible']
    support = eligible & (np.abs(signed) <= tau + 3 * sigma)
    plane = np.where(eligible, np.maximum(0, signed - 3 * sigma) / np.maximum(tau, 1e-20), np.nan)
    depth = np.where(eligible, geometry['depth'], np.nan)
    return support, plane, depth


def diverse_pair(masks, directions, kf_ids, minimum=1.):
    if len(kf_ids) != len(set(kf_ids)):
        raise ValueError('Duplicate evidence KF')
    if not masks:
        return None
    result = np.zeros_like(masks[0], bool)
    limit = np.cos(np.radians(minimum))
    for i in range(len(masks)):
        for j in range(i):
            cosine = np.einsum('ni,ni->n', directions[i], directions[j])
            result |= masks[i] & masks[j] & (cosine <= limit + 1e-12)
    return result


def second_diverse(scores, directions, kf_ids):
    if not scores:
        return None
    if len(kf_ids) != len(set(kf_ids)):
        raise ValueError('Duplicate evidence KF')
    result = np.full(len(scores[0]), np.nan)
    limit = np.cos(np.radians(1.))
    for i in range(len(scores)):
        for j in range(i):
            good = (np.isfinite(scores[i]) & np.isfinite(scores[j]) &
                    (np.einsum('ni,ni->n', directions[i], directions[j]) <= limit + 1e-12))
            result = np.fmax(result, np.where(good, np.minimum(scores[i], scores[j]), np.nan))
    return result

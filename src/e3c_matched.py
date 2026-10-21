"""Matched per-view geometry and aggregation. GT never enters these functions."""
import numpy as np
from e0b_audit import transform
from e2_signals import match_rays, median_views
from e2b_transfer import repeat_score


def geometry_pair(means, covariance, candidate, evidence, candidate_pose, evidence_pose, spec):
    """Exact geometric prefix of E2 cross_pair, without unused RGB patch warps."""
    relative = np.linalg.inv(evidence_pose) @ candidate_pose
    p = transform(means, relative)
    ids, ray_ok, angle, radius = match_rays(p, evidence, spec['ray_angle_max_degrees'])
    world = transform(means, candidate_pose)
    a, b = world-candidate_pose[:3, 3], world-evidence_pose[:3, 3]
    cosine = np.einsum('ij,ij->i', a, b) / np.maximum(np.linalg.norm(a, axis=1)*np.linalg.norm(b, axis=1), 1e-12)
    parallax = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
    ray = p / np.maximum(radius[:, None], 1e-12)
    cov = relative[:3, :3] @ covariance @ relative[:3, :3].T
    sigma = np.sqrt(np.maximum(np.einsum('ni,nij,nj->n', ray, cov, ray), 0))
    band = np.maximum(spec['occlusion_relative_band']*evidence['radius'][ids], spec['occlusion_gaussian_sigma']*sigma)
    base = (ray_ok & (parallax >= spec['parallax_min_degrees']) &
            (candidate['confidence'] >= spec['confidence_min']) & ~evidence['edge'][ids])
    occluded = base & (radius-evidence['radius'][ids] > band)
    good = base & ~occluded
    depth = np.full(len(means), np.nan)
    depth[good] = np.maximum(0, (evidence['radius'][ids[good]]-radius[good]-
        spec['occlusion_gaussian_sigma']*sigma[good]) / evidence['radius'][ids[good]])
    plane = np.full(len(means), np.nan)
    reliable = good & evidence['patch_reliable'][ids]
    normal = evidence['normal'][ids]
    sigma_plane = np.sqrt(np.maximum(np.einsum('ni,nij,nj->n', normal, cov, normal), 0))
    signed = np.einsum('ni,ni->n', normal, p-evidence['mean'][ids])
    plane[reliable] = np.maximum(0, (signed[reliable]-spec['occlusion_gaussian_sigma']*sigma_plane[reliable]) /
        evidence['spacing'][ids[reliable]])
    relative_plane = plane*evidence['spacing'][ids] / evidence['radius'][ids]
    return depth, relative_plane, dict(depth_eligible=int(good.sum()), plane_eligible=int(reliable.sum()),
                                     occluded=int(occluded.sum()))


def matched_scores(depth_views, plane_views, n):
    """Apply the common mask BEFORE aggregation; both pairs abstain identically."""
    if len(depth_views) != len(plane_views):
        raise ValueError('View identities must match')
    native, _ = median_views(depth_views, n)
    result = dict(D_native=native.astype(np.float32))
    if not depth_views:
        for name in ['D_maskmedian','D_shared','P_shared','D_union','P_union']:
            result[name] = np.full(n, np.nan, np.float32)
        return result, np.zeros(n, np.uint16), np.zeros(n, bool), np.zeros(n, bool)
    d, p = np.asarray(depth_views), np.asarray(plane_views)
    shared = np.isfinite(d) & np.isfinite(p)
    d, p = np.where(shared, d, np.nan), np.where(shared, p, np.nan)
    ds, count, _ = repeat_score(list(d), n, veto=False)
    ps, pc, support = repeat_score(list(p), n, veto=False)
    np.testing.assert_array_equal(count, pc)
    union = support | np.any(shared & (d == 0), axis=0)
    median, _ = median_views(list(d), n)
    median[(count < 2) | support] = np.nan
    result['D_maskmedian'] = median.astype(np.float32)
    for suffix, veto in [('shared',support), ('union',union)]:
        for prefix, score in [('D',ds), ('P',ps)]:
            v = score.copy();v[veto] = np.nan
            result[prefix+'_'+suffix] = v
        np.testing.assert_array_equal(np.isfinite(result['D_'+suffix]), np.isfinite(result['P_'+suffix]))
    return result, count, support, union

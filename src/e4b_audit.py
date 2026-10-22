"""Evaluation-only E4b reference diagnostics. Never imported by admission code."""
import warnings

import numpy as np
from scipy.ndimage import uniform_filter

from e0b_audit import transform
from e1_taxonomy import backproject, depth_masks
from e2_signals import match_rays
from e2b_transfer import repeat_score
from e3c_matched import geometry_pair


COHORTS = ['both_miss', 'b6_only', 'both_reject', 'plane_only']
FUNNELS = ['no_causal_evidence', 'no_finite_native_depth', 'no_finite_shared_plane',
           'fewer_than_two_shared_views', 'plane_zero_veto',
           'finite_but_not_above_threshold', 'above_threshold_reject']


def cohort_codes(b6_reject, plane_reject):
    return (b6_reject.astype(np.uint8) + 3 * plane_reject.astype(np.uint8) -
            2 * (b6_reject & plane_reject).astype(np.uint8))


def funnel(native_count, shared_count, support, score, threshold, causal_count):
    out = np.full(len(score), 5, np.uint8)
    out[np.isfinite(score) & (score > threshold)] = 6
    out[support] = 4
    out[shared_count < 2] = 3
    out[shared_count == 0] = 2
    out[native_count == 0] = 1
    if causal_count == 0:
        out[:] = 0
    return out


def aggregate_oracles(depths, factual_planes, oracle_planes, n):
    """Preserve factual pair masks; allow only the recomputed-veto arm to unveto."""
    if not depths:
        return [np.full(n, np.nan, np.float32) for _ in range(3)]
    shared = np.isfinite(depths) & np.isfinite(factual_planes)
    factual = np.where(shared, factual_planes, np.nan)
    changed = np.where(shared, oracle_planes, np.nan)
    assert np.array_equal(np.isfinite(factual), np.isfinite(changed))
    fs, _, fv = repeat_score(list(factual), n, veto=False)
    gs, _, gv = repeat_score(list(changed), n, veto=False)
    factual_score = fs.copy(); factual_score[fv] = np.nan
    fixed = gs.copy(); fixed[fv] = np.nan
    recomputed = gs.copy(); recomputed[gv] = np.nan
    assert np.array_equal(np.isfinite(factual_score), np.isfinite(fixed))
    return factual_score, fixed, recomputed


def patch_moments(points, valid, radius=2):
    size = 2 * radius + 1
    count = np.rint(uniform_filter(valid.astype(float), size, mode='constant') * size**2)
    denom = np.maximum(count, 1)
    p = np.where(valid[..., None], points, 0)
    mean = np.stack([uniform_filter(p[..., k], size, mode='constant') * size**2 / denom
                     for k in range(3)], axis=-1)
    cov = np.empty((*valid.shape, 3, 3))
    for j in range(3):
        for k in range(3):
            cov[..., j, k] = (uniform_filter(p[..., j]*p[..., k], size, mode='constant') *
                              size**2 / denom - mean[..., j]*mean[..., k])
    eigen, vectors = np.linalg.eigh(cov)
    normal = vectors[..., 0]
    normal[np.einsum('...i,...i->...', normal, mean) > 0] *= -1
    return count, mean, normal, eigen


def prepare_gt(observation, depth, K, label_spec, base):
    h, w = observation['hw']
    assert depth.shape == (h, w)
    valid, edge = depth_masks(depth, label_spec)
    p = observation['points'].reshape(h, w, 3)
    pred_valid = (np.isfinite(p).all(-1) & (p[..., 2] > 0) &
                  (observation['radius'].reshape(h, w) > 1e-8) &
                  (observation['confidence'].reshape(h, w) >= base['confidence_min']))
    common = pred_valid & valid & ~edge
    xyz = backproject(depth, K).astype(np.float64)
    count, mean, normal, eigen = patch_moments(xyz, common)
    reliable = (common & (count >= 9) & (eigen[..., 1] > 1e-12) &
        (eigen[..., 0]/np.maximum(eigen[..., 1], 1e-12) <= .1) &
        (eigen[..., 1]/np.maximum(eigen[..., 2], 1e-12) >= .05))
    reliable[:2] = reliable[-2:] = False
    reliable[:, :2] = reliable[:, -2:] = False
    status = np.full((h, w), 4, np.uint8)  # 4 reliable
    status[~reliable] = 3  # nonplanar/degenerate or border
    status[count < 9] = 2
    status[edge] = 1
    status[~valid] = 0
    gt_rays = xyz / np.maximum(np.linalg.norm(xyz, axis=-1, keepdims=True), 1e-12)
    angle = np.degrees(np.arccos(np.clip(np.sum(gt_rays * observation['rays'].reshape(h,w,3), -1), -1, 1)))
    return dict(depth=depth, valid=valid, edge=edge, common=common, count=count,
                mean=mean.reshape(-1,3), normal=normal.reshape(-1,3),
                reliable=reliable.reshape(-1), status=status.reshape(-1),
                ray_angle=angle.reshape(-1), K=K, xyz=xyz)


def project_depth(points_m, gt):
    """Calibrated projection, never use ray-distance as camera z-depth."""
    h, w = gt['depth'].shape
    z = points_m[:,2]
    good = np.isfinite(points_m).all(1) & (z > .1)
    u = np.zeros(len(z), np.int64); v = u.copy()
    K = gt['K']
    u[good] = np.rint(K[0,0]*points_m[good,0]/z[good]+K[0,2]).astype(np.int64)
    v[good] = np.rint(K[1,1]*points_m[good,1]/z[good]+K[1,2]).astype(np.int64)
    good &= (u>=0)&(u<w)&(v>=0)&(v<h)
    uc, vc = np.clip(u,0,w-1), np.clip(v,0,h-1)
    good &= gt['valid'][vc,uc] & ~gt['edge'][vc,uc]
    d = gt['depth'][vc,uc]
    return u, v, good, d


def window_values(values, valid, r=2):
    a = np.where(valid, values, np.nan)
    padded = np.pad(a, r, constant_values=np.nan)
    return np.stack([padded[y:y+a.shape[0], x:x+a.shape[1]]
                     for y in range(2*r+1) for x in range(2*r+1)])


def window_quantiles(values, valid):
    a = np.sort(window_values(values, valid), axis=0)
    count = np.isfinite(a).sum(0)
    out = []
    for q in [.05, .5, .95]:
        x = np.maximum(count-1, 0)*q
        lo, hi = np.floor(x).astype(int), np.ceil(x).astype(int)
        left = np.take_along_axis(a,lo[None],axis=0)[0]
        right = np.take_along_axis(a,hi[None],axis=0)[0]
        value = left+(right-left)*(x-lo)
        value[count==0] = np.nan
        out.append(value.reshape(-1).astype(np.float32))
    return out


def reference_quality(obs, gt, scale, base):
    h,w = obs['hw']; common = gt['common']; count = gt['count']
    pred = obs['points']*scale
    offset = np.abs(np.einsum('ni,ni->n',gt['normal'],obs['mean']*scale-gt['mean']))
    angle = np.degrees(np.arccos(np.clip(np.abs(np.einsum('ni,ni->n',gt['normal'],obs['normal'])),-1,1)))
    zerr = pred[:,2].reshape(h,w)-gt['depth']
    quality = dict(gt_status=gt['status'], gt_reliable=gt['reliable'],
        common_points=count.reshape(-1).astype(np.uint8), plane_offset_m=offset.astype(np.float32),
        plane_angle_degrees=angle.astype(np.float32), source_z_error_m=zerr.reshape(-1).astype(np.float32),
        ray_angle_degrees=gt['ray_angle'].astype(np.float32))
    for absolute in [.02,.05,.1]:
        tol = np.maximum(absolute,.02*gt['depth'])
        f = uniform_filter((common&(zerr < -tol)).astype(float),5,mode='constant')*25/np.maximum(count,1)
        b = uniform_filter((common&(zerr > tol)).astype(float),5,mode='constant')*25/np.maximum(count,1)
        suffix = str(round(absolute*100))
        quality['front_fraction_'+suffix] = f.reshape(-1).astype(np.float32)
        quality['behind_fraction_'+suffix] = b.reshape(-1).astype(np.float32)
        for degrees in [5,10,20]:
            quality[f'wrong_{suffix}_{degrees}'] = gt['reliable'] & ((offset > np.maximum(absolute,.02*gt['mean'][:,2]))|(angle>degrees))
    reliable_pred = obs['patch_reliable'] & (count.reshape(-1)>=9)
    f,b = quality['front_fraction_5'],quality['behind_fraction_5']
    quality['coherent_front'] = reliable_pred & (f >= .8-1e-7)
    quality['coherent_behind'] = reliable_pred & (b >= .8-1e-7)
    quality['all_points_wrong'] = reliable_pred & ((f >= 1-1e-7)|(b >= 1-1e-7))
    quality['z_error_p05'],quality['z_error_median'],quality['z_error_p95'] = window_quantiles(zerr,common)
    _,_,pg,pd = project_depth(pred,gt)
    quality['projection_valid'] = pg
    quality['projection_z_error_m'] = np.where(pg,pred[:,2]-pd,np.nan).astype(np.float32)
    return quality


def pair_details(means, covariance, candidate, evidence, a_pose, b_pose, base):
    # Scores always come from the original exact arithmetic; diagnostics are separate.
    depth, plane, _ = geometry_pair(means,covariance,candidate,evidence,a_pose,b_pose,base)
    relative = np.linalg.inv(b_pose)@a_pose
    p = transform(means,relative)
    ids,ray_ok,angle,radius = match_rays(p,evidence,base['ray_angle_max_degrees'])
    world = transform(means,a_pose)
    a,b = world-a_pose[:3,3],world-b_pose[:3,3]
    cosine = np.einsum('ij,ij->i',a,b)/np.maximum(np.linalg.norm(a,axis=1)*np.linalg.norm(b,axis=1),1e-12)
    parallax = np.degrees(np.arccos(np.clip(cosine,-1,1)))
    cov = relative[:3,:3]@covariance@relative[:3,:3].T
    ray = p/np.maximum(radius[:,None],1e-12)
    sigma_ray = np.sqrt(np.maximum(np.einsum('ni,nij,nj->n',ray,cov,ray),0))
    normal = evidence['normal'][ids]
    sigma_plane = np.sqrt(np.maximum(np.einsum('ni,nij,nj->n',normal,cov,normal),0))
    signed = np.einsum('ni,ni->n',normal,p-evidence['mean'][ids])
    band = np.maximum(base['occlusion_relative_band']*evidence['radius'][ids],3*sigma_ray)
    occlusion = radius-evidence['radius'][ids] > band
    fields = dict(evidence_pixel=ids.astype(np.int32),ray_match=ray_ok,
        ray_angle=angle.astype(np.float32),confidence=candidate['confidence']>=base['confidence_min'],
        edge=evidence['edge'][ids],parallax_degrees=parallax.astype(np.float32),
        parallax=parallax>=base['parallax_min_degrees'],occlusion=occlusion,
        patch_reliable=evidence['patch_reliable'][ids],
        depth_residual=(evidence['radius'][ids]-radius).astype(np.float32),
        plane_signed_residual=signed.astype(np.float32),sigma_ray=sigma_ray.astype(np.float32),
        sigma_plane=sigma_plane.astype(np.float32),depth_score=depth,plane_score=plane)
    return fields,p,cov


def oracle_pair(p,cov,depth,plane,ids,evidence,gt,scale):
    changed = plane.copy()
    use = np.isfinite(depth)&np.isfinite(plane)&gt['reliable'][ids]
    normal = gt['normal'][ids]
    signed = np.einsum('ni,ni->n',normal,p-gt['mean'][ids]/scale)
    sigma = np.sqrt(np.maximum(np.einsum('ni,nij,nj->n',normal,cov,normal),0))
    # Preserve the original spacing division/multiplication order.
    value = np.maximum(0,(signed-3*sigma)/evidence['spacing'][ids])
    value = value*evidence['spacing'][ids]/evidence['radius'][ids]
    changed[use] = value[use]
    assert np.array_equal(np.isfinite(changed),np.isfinite(plane))
    return changed,use


def gt_front(p,cov,gt,scale,ids):
    pm = p*scale
    u,v,good,d = project_depth(pm,gt)
    w = gt['depth'].shape[1]
    in_patch = (np.abs(u-ids%w)<=2)&(np.abs(v-ids//w)<=2)
    sigma_z = np.sqrt(np.maximum(cov[:,2,2],0))*scale
    front = good&in_patch&(pm[:,2]+3*sigma_z < d-np.maximum(.05,.02*d))
    return front,good&in_patch


def change_metrics(factual,changed,labels,active,primary):
    result = {}
    for name,mask in [('bad',labels==3),('normal',np.isin(labels,[1,2])),('unknown',labels==0)]:
        mask = mask&active
        result[name+'_newly_rejected'] = int((mask&~factual&changed).sum())
        result[name+'_no_longer_rejected'] = int((mask&factual&~changed).sum())
        result[name+'_rejected'] = int((mask&changed).sum())
    bad = int((active&(labels==3)).sum());normal = int((active&np.isin(labels,[1,2])).sum())
    result['global_bad_recall'] = result['bad_rejected']/bad if bad else None
    result['normal_retention'] = 1-result['normal_rejected']/normal if normal else None
    result['primary_cohort_recovered'] = int((primary&changed).sum())
    result['primary_cohort_recovery'] = float((primary&changed).sum()/primary.sum()) if primary.any() else None
    return result

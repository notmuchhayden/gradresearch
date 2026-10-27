"""Reference-free scalar RGB measurement for A2-O-M.

Legacy validity deliberately retains the archived missing y>=0 check for parity.
R1 validity implements all image bounds. No reference or filesystem I/O here.
"""
from __future__ import annotations

import hashlib
import numpy as np

GRID = np.round(np.arange(-.20, .200001, .01), 8)
GRAY = np.array([.299, .587, .114])
VARIANTS = {'L4': (4, True), 'L2': (2, True),
            'R4': (4, False), 'R1': (2, False)}


def mask_sha(mask):
    return hashlib.sha256(np.ascontiguousarray(mask, dtype=np.uint8).tobytes()).hexdigest()


def sample(image, xy):
    """Bilinear values, strict bounds, archived bounds, and four-neighbor grid."""
    image = np.asarray(image)
    scalar = image.ndim == 2
    if scalar:
        image = image[..., None]
    h, w = image.shape[:2]
    x, y = xy[..., 0], xy[..., 1]
    old = np.isfinite(x) & np.isfinite(y) & (x >= 0) & (x < w-1) & (y < h-1)
    inside = old & (y >= 0)
    x0 = np.clip(np.floor(np.nan_to_num(x)).astype(np.int64), 0, w-2)
    y0 = np.clip(np.floor(np.nan_to_num(y)).astype(np.int64), 0, h-2)
    dx, dy = (x-x0)[..., None], (y-y0)[..., None]
    out = (image[y0, x0]*(1-dx)*(1-dy) + image[y0, x0+1]*dx*(1-dy)
           + image[y0+1, x0]*(1-dx)*dy + image[y0+1, x0+1]*dx*dy)
    return out[..., 0] if scalar else out, inside, old, (x0, y0)


def warp(pair, a, *, photo=False):
    P = pair['patches']
    Y, S = P['points'], P['rgb']
    qs, qe, K = pair['source_Q'], pair['evidence_Q'], pair['K']
    world = (Y*np.exp(a)) @ qs[:3, :3].T + qs[:3, 3]
    pe = (world-qe[:3, 3]) @ qe[:3, :3]
    z = pe[..., 2]
    safe = np.maximum(z, 1e-12)
    xy = np.stack([K[0, 0]*pe[..., 0]/safe+K[0, 2],
                   K[1, 1]*pe[..., 1]/safe+K[1, 2]], -1)
    rgb, inside, old_inside, (x0, y0) = sample(pair['evidence_rgb'], xy)
    zz, _, _, _ = sample(pair['evidence_z'], xy)
    vm = pair['evidence_valid']
    valid4 = vm[y0, x0] & vm[y0, x0+1] & vm[y0+1, x0] & vm[y0+1, x0+1]
    finite = np.isfinite(rgb).all(-1)
    positive = z > 0
    agrees = np.abs(z-zz) <= np.maximum(.05, .05*np.maximum(zz, 0))
    base = inside & positive & finite & valid4
    legacy = old_inside & positive & finite & valid4 & agrees
    gray = rgb @ GRAY
    out = dict(projection=base.all(1), legacy=legacy.all(1),
               bounds=(inside & positive & finite).all(1),
               legacy_bounds=(old_inside & positive & finite).all(1),
               evidence=valid4.all(1), agreement=agrees.all(1),
               warped_texture=gray.var(1) >= .02**2,
               signed_residual=z[:, 4]-zz[:, 4], xy=xy,
               projected_z=z, sampled_evidence_z=zz)
    if photo:
        x = S @ GRAY
        xc = x-x.mean(1, keepdims=True)
        yc = gray-gray.mean(1, keepdims=True)
        den = np.sqrt(np.sum(xc*xc, 1)*np.sum(yc*yc, 1))
        corr = np.clip(np.sum(xc*yc, 1)/(den+1e-12), -1, 1)
        zncc = (1-corr)/2
        l1 = np.mean(np.abs(S-rgb), (1, 2))
        r = np.log(np.maximum(z, 1e-12)/np.maximum(zz, 1e-12))
        geom = np.where(np.abs(r) <= .05, .5*r*r, .05*(np.abs(r)-.025)).mean(1)
        out.update(loss=.85*zncc+.15*l1, zncc=zncc, l1=l1, geometry=geom)
    return out


def subset_pair(pair, indices):
    p = dict(pair)
    n = len(pair['patches']['points'])
    p['patches'] = {k: v[indices] if isinstance(v, np.ndarray) and len(v) == n else v
                    for k, v in pair['patches'].items()}
    return p


def source_flags(pair):
    p = pair['patches']
    y = p['points']
    z = y[:, 4, 2]
    jumps = np.abs(y[:, [1, 3, 5, 7], 2]-z[:, None])/np.maximum(np.abs(z[:, None]), 1e-8)
    return dict(source_edge=~(jumps > .05).any(1),
                source_texture=(p['rgb'] @ GRAY).std(1) >= .02,
                ray=p.get('ray_grid_match', np.ones(len(y), bool)),
                parallax=p.get('primary_parallax', np.ones(len(y), bool)))


def diagnose(pair):
    """Support only; never computes or returns candidate photo loss."""
    p = pair['patches']
    n = len(p['points'])
    flags = source_flags(pair)
    zero = warp(pair, 0.)
    flags.update({k: zero[k] for k in ('bounds', 'legacy_bounds', 'evidence',
                                     'agreement', 'warped_texture')})
    pre = flags['source_edge'] & flags['source_texture'] & flags['ray'] & flags['parallax']
    elig_old = pre & zero['legacy'] & zero['warped_texture']
    elig_new = pre & zero['projection'] & zero['warped_texture']
    relevant = elig_old | elig_new
    idx = np.flatnonzero(relevant)
    small = subset_pair(pair, idx)
    cv_new = np.zeros((len(GRID), n), bool)
    cv_old = np.zeros_like(cv_new)
    for i, a in enumerate(GRID):
        out = warp(small, float(a))
        cv_new[i, idx] = out['projection']
        cv_old[i, idx] = out['legacy']
    result = dict(flags=flags, cv_new=cv_new, cv_old=cv_old,
                  signed_residual=zero['signed_residual'])
    centers = p['centers']
    for name, (stride, agreement) in VARIANTS.items():
        stride_mask = ((centers % 512) % stride == 0) & ((centers // 512) % stride == 0)
        eligible = (elig_old if agreement else elig_new) & stride_mask
        cv = cv_old if agreement else cv_new
        common = eligible & cv.all(0)
        counts = np.cumprod(cv.astype(np.int8), axis=0).astype(bool) & eligible[None]
        retained, base = int(common.sum()), int(eligible.sum())
        result[name] = dict(eligible=eligible, mask=common, retained=retained,
                           eligible_count=base, support=retained >= 256 and retained >= .5*base,
                           candidate_retained=(cv & eligible[None]).sum(1).tolist(),
                           intersection_progress=counts.sum(1).tolist(), mask_sha256=mask_sha(common))
    return result


def profile(pair, mask, grid=GRID):
    """Evaluate an already-fixed mask. No per-candidate sample removal."""
    small = subset_pair(pair, np.flatnonzero(mask))
    if not mask.any():
        return None
    out = {k: [] for k in ('loss', 'geometry', 'zncc', 'l1')}
    for a in grid:
        w = warp(small, float(a), photo=True)
        if not w['projection'].all():
            raise ValueError('frozen common mask lost projection validity')
        for key in out:
            out[key].append(float(w[key].mean()))
    return {k: np.asarray(v) for k, v in out.items()}


def choose(losses, grid=GRID):
    loss = np.asarray(losses)
    if len(loss) != len(grid) or not np.isfinite(loss).all():
        raise ValueError('finite complete profile required')
    tied = np.flatnonzero(loss <= loss.min()+1e-8)
    i = min(tied, key=lambda j: (abs(grid[j]), grid[j]))
    return dict(a=float(grid[i]), index=int(i), loss=float(loss[i]),
                gain_over_zero=float(loss[np.argmin(np.abs(grid))]-loss[i]),
                flat=bool(np.ptp(loss) <= 1e-4), boundary=bool(i in (0, len(grid)-1)),
                tie_count=int(len(tied)))


def classify_effect(photo_gain, error_before, error_after, *, supported=True):
    if not supported:
        return 'INSUFFICIENT_SUPPORT'
    if photo_gain <= 1e-4:
        return 'NO_RESOLVED_PHOTO_GAIN'
    if error_after >= error_before:
        return 'PHOTO_GEOMETRY_MISMATCH'
    return 'DIRECTION_SUPPORTED'


def context_support(records, native_counts, *, pool='rgb_fit'):
    ids = sorted(native_counts)
    supported = []
    pair_counts = {}
    for k in ids:
        count = sum(r['source_kf'] == k and r['pool'] == pool and r['support'] for r in records)
        pair_counts[str(k)] = int(count)
        if count >= 2:
            supported.append(k)
    fraction = sum(native_counts[k] for k in supported)/sum(native_counts.values())
    return dict(supported_kfs=supported, pair_counts=pair_counts,
                kf_count=len(supported), denominator=len(ids),
                kf_fraction=len(supported)/len(ids), candidate_fraction=fraction,
                passed=len(supported)/len(ids) >= .8 and fraction >= .8)

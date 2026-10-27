"""Registered analytic synthetic controls; truth used only by generator/evaluator."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from a2_o_m_common import dump, write_csv, legacy
from rgb_mask_diagnostic import (GRID, GRAY, diagnose, warp, profile, choose,
                                 classify_effect, mask_sha)

H, W = 288, 512
K = np.array([[400., 0, 255.5], [0, 400., 143.5], [0, 0, 1.]])


def texture(world, depth, *, repeated=False, low=False, foreground=False):
    if low:
        return np.full(world.shape, .5)
    x, y = world[..., 0]/depth, world[..., 1]/depth
    if repeated:
        t = .5+.4*np.sin(2*np.pi*(x*400)/8)
    else:
        t = .5+.23*np.sin(110*x+67*y)+.22*np.cos(73*x-99*y+.02*x*x)
    out = np.stack([t, np.clip(t+.03*np.sin(17*x), 0, 1),
                    np.clip(t+.03*np.cos(19*y), 0, 1)], -1)
    if foreground:
        out = out[..., ::-1]*np.array([1., .7, .8])
    return np.clip(out, 0, 1)


def render(q, depth, slope=(0., 0.), *, low=False, repeated=False, occluder=False):
    v, u = np.indices((H, W))
    local_ray = np.stack([(u-255.5)/400, (v-143.5)/400, np.ones((H, W))], -1)
    ray = local_ray @ q[:3, :3].T
    center = q[:3, 3]
    sx, sy = slope
    lam = (depth+sx*center[0]+sy*center[1]-center[2])/(ray[..., 2]-sx*ray[..., 0]-sy*ray[..., 1])
    world = center+lam[..., None]*ray
    rgb = texture(world, depth, repeated=repeated, low=low)
    surface = np.zeros((H, W), np.int8)
    if occluder:
        front_t = (2-center[2])/ray[..., 2]
        fw = center+front_t[..., None]*ray
        hit = ((fw[..., 0] >= -.35) & (fw[..., 0] <= .15)
               & (fw[..., 1] >= -.6) & (fw[..., 1] <= .6) & (front_t < lam))
        world[hit] = fw[hit]
        rgb[hit] = texture(fw, 2., foreground=True)[hit]
        surface[hit] = 1
    local = (world-center) @ q[:3, :3]
    return dict(rgb=rgb, local=local, depth=local[..., 2], surface=surface)


def fixture(depth=4., slope=(0., 0.), *, bias=0., baseline=.4,
            rotation=0., low=False, repeated=False, occluder=False, dynamic=False):
    qs, qe = np.eye(4), np.eye(4)
    qe[0, 3] = baseline
    qe[:3, :3] = Rotation.from_euler('y', rotation, degrees=True).as_matrix()
    src = render(qs, depth, slope, low=low, repeated=repeated, occluder=occluder)
    ev = render(qe, depth, slope, low=low, repeated=repeated, occluder=occluder)
    if dynamic:
        left, right = int(W*.4), int(W*.6)
        moved = np.roll(ev['rgb'], 8, axis=1)
        ev['rgb'][:, left:right] = moved[:, left:right]
    u, v = np.meshgrid(np.arange(128, 288, 8), np.arange(64, 224, 8))
    centers = np.stack([u.ravel(), v.ravel()], -1)
    offsets = np.stack([np.tile(np.arange(-1, 2), 3), np.repeat(np.arange(-1, 2), 3)], -1)
    xy = centers[:, None]+offsets[None]
    points = src['local'][xy[..., 1], xy[..., 0]]*np.exp(bias)
    # Use the same predicted native raster/edge contract as real input.
    with np.errstate(invalid='ignore'):
        z, valid, _ = legacy().rasterize_predicted_depth(ev['local'].reshape(-1, 3), np.arange(H*W), K)
    p = dict(points=points, rgb=src['rgb'][xy[..., 1], xy[..., 0]], xy=xy,
             centers=centers[:, 1]*W+centers[:, 0], ray_grid_match=np.ones(len(centers), bool),
             primary_parallax=np.full(len(centers), baseline > 0))
    pair = dict(patches=p, source_Q=qs, evidence_Q=qe, K=K,
                evidence_rgb=ev['rgb'], evidence_z=z, evidence_valid=valid)
    truth = dict(source_z=src['depth'][xy[:, 4, 1], xy[:, 4, 0]],
                 source_surface=src['surface'][xy[:, 4, 1], xy[:, 4, 0]],
                 evidence_depth=ev['depth'], evidence_surface=ev['surface'],
                 evidence_Q=qe.copy())
    return pair, truth


def true_visibility(pair, truth, a, mask):
    """Truth audit only; called after the RGB coefficient has been selected."""
    y = pair['patches']['points'][:, 4]*np.exp(a)
    world = y @ pair['source_Q'][:3, :3].T+pair['source_Q'][:3, 3]
    q = truth['evidence_Q']
    pe = (world-q[:3, 3]) @ q[:3, :3]
    u = np.rint(400*pe[:, 0]/np.maximum(pe[:, 2], 1e-12)+255.5).astype(int)
    v = np.rint(400*pe[:, 1]/np.maximum(pe[:, 2], 1e-12)+143.5).astype(int)
    inside = (u >= 0) & (u < W) & (v >= 0) & (v < H) & (pe[:, 2] > 0)
    uu, vv = np.clip(u, 0, W-1), np.clip(v, 0, H-1)
    same = truth['evidence_surface'][vv, uu] == truth['source_surface']
    zz = truth['evidence_depth'][vv, uu]
    visible = inside & same & (np.abs(pe[:, 2]-zz) <= np.maximum(.05, .05*zz))
    return float((~visible & mask).sum()/max(1, mask.sum()))


def measure(pair, truth, *, raw_rotation=False):
    d = diagnose(pair)
    mask = d['R1']['mask']
    if raw_rotation:
        raw = copy.deepcopy(pair)
        raw['patches']['primary_parallax'][:] = True
        mask = diagnose(raw)['R1']['mask']
        pair_eval = raw
    else:
        pair_eval = pair
    scores = profile(pair_eval, mask)
    if scores is None:
        return dict(supported=d['R1']['support'], eligible=d['R1']['eligible_count'],
                    retained=d['R1']['retained'], selection=None,
                    status='INSUFFICIENT_SUPPORT'), None
    selection = choose(scores['loss'])
    # Selection is complete before any truth access.
    z = pair['patches']['points'][:, 4, 2]
    e0 = float(np.mean(np.abs(z-truth['source_z'])))
    e1 = float(np.mean(np.abs(z*np.exp(selection['a'])-truth['source_z'])))
    effect = classify_effect(selection['gain_over_zero'], e0, e1,
                             supported=d['R1']['support'])
    vis = []
    for a in GRID:
        vis.append(true_visibility(pair, truth, float(a), mask))
    row = dict(supported=d['R1']['support'], eligible=d['R1']['eligible_count'],
               retained=d['R1']['retained'], selection=selection, source_error_before=e0,
               source_error_after=e1, status=effect,
               selected_false_visibility_fraction=vis[selection['index']],
               mask_sha256=mask_sha(mask))
    curves = dict(photo=scores['loss'].tolist(), geometry=scores['geometry'].tolist(),
                  true_visibility_failure=vis)
    return row, curves


def run_controls(spec, out):
    """All amplitudes/fixtures are fixed by the already-registered specification."""
    out = Path(out)
    rows, profiles, mandatory = [], {}, []

    def record(name, pair, truth, *, check=None, raw_rotation=False):
        row, curves = measure(pair, truth, raw_rotation=raw_rotation)
        row['control'] = name
        row['mandatory'] = check is not None
        if check is not None:
            row['check_passed'] = bool(check(row, curves))
            mandatory.append(row['check_passed'])
        else:
            # A photo-only success is never accepted if truth does not improve.
            row['check_passed'] = not (row['status'] == 'DIRECTION_SUPPORTED'
                                      and row.get('source_error_after', 0) >= row.get('source_error_before', 0))
            mandatory.append(row['check_passed'])
        rows.append(row)
        profiles[name] = curves
        return row, curves

    pair, truth = fixture()
    old = legacy()
    n = len(pair['patches']['points'])
    # Reproduce the original random-texture primitive fixture exactly in kind:
    # 40px lateral shift at 4m, all 400 patches above the texture threshold.
    image = np.random.default_rng(spec['seed']).random((H, W, 3))
    xy = pair['patches']['xy']
    pair['patches']['rgb'] = image[xy[..., 1], xy[..., 0]]
    pair['evidence_rgb'] = np.roll(image, -40, axis=1)
    pair['patches']['texture'] = np.ones(n, bool)
    modes = old.dct_modes()
    only0 = old.evaluate_pair_candidates(pair, [old.scalar_candidates()[20]], modes)
    all41 = old.evaluate_pair_candidates(pair, old.scalar_candidates(), modes)
    r1 = diagnose(pair)['R1']
    collapse = dict(control='legacy_plane_collapse', zero_retained=only0['retained'],
                    legacy_retained=all41['retained'], r1_retained=r1['retained'],
                    check_passed=only0['retained'] == 400 and all41['retained'] == 0 and r1['support'],
                    mandatory=True)
    mandatory.append(collapse['check_passed'])
    rows.append(collapse)
    for depth in spec['depths']:
        for slope in spec['slopes']:
            tag = f'd{depth:g}_s{slope[0]:g}_{slope[1]:g}'
            p, t = fixture(depth, slope)
            record('clean_'+tag, p, t, check=lambda r, c: r['supported'] and
                   abs(r['selection']['a']) <= spec['clean_tolerance'] and
                   r['selection']['gain_over_zero'] <= 1e-4)
            for e in spec['source_log_bias']:
                p, t = fixture(depth, slope, bias=e)
                record(f'source_bias_{e:g}_'+tag, p, t,
                       check=lambda r, c, e=e: r['supported'] and
                       abs(r['selection']['a']+e) <= spec['recovery_tolerance'])
    for rot in spec['pure_rotation_deg']:
        p, t = fixture(baseline=0, rotation=rot)
        record(f'pure_rotation_{rot:g}', p, t, raw_rotation=True,
               check=lambda r, c: not r['supported'] and c is not None and
               np.ptp(c['photo']) <= spec['invariance_tolerance'])
    p, t = fixture(low=True)
    record('low_texture', p, t, check=lambda r, c: not r['supported'] and r['selection'] is None)
    clean_p, clean_t = fixture()
    clean_r, clean_c = measure(clean_p, clean_t)
    for e in spec['shared_log_bias']:
        p = copy.deepcopy(clean_p)
        p['patches']['points'] *= np.exp(e)
        p['evidence_z'] *= np.exp(e)
        p['source_Q'][:3, 3] *= np.exp(e)
        p['evidence_Q'][:3, 3] *= np.exp(e)
        record(f'joint_scale_{e:g}', p, clean_t,
               check=lambda r, c: r['mask_sha256'] == clean_r['mask_sha256'] and
               np.max(np.abs(np.asarray(c['photo'])-clean_c['photo'])) <= spec['invariance_tolerance'])
        p, t = fixture(bias=e)
        p['evidence_z'] *= np.exp(e)
        record(f'shared_depth_bias_{e:g}', p, t)
    for kind in ('translation', 'rotation'):
        for axis in range(3):
            for sign in (-1, 1):
                delta = np.eye(4)
                if kind == 'translation':
                    delta[axis, 3] = sign*spec['pose_translation_m']
                else:
                    angles = np.zeros(3)
                    angles[axis] = sign*spec['pose_rotation_deg']
                    delta[:3, :3] = Rotation.from_euler('xyz', angles, degrees=True).as_matrix()
                for e in spec['pose_source_log_bias']:
                    p, t = fixture(bias=e)
                    # Left multiply relative source->evidence transform.
                    T = np.linalg.inv(p['evidence_Q']) @ p['source_Q']
                    p['evidence_Q'] = p['source_Q'] @ np.linalg.inv(delta @ T)
                    record(f'pose_{kind}_{axis}_{sign}_bias{e:g}', p, t)
    for name in ('occluder', 'dynamic', 'repeated'):
        p, t = fixture(bias=.1, **{name: True})
        record(name, p, t)
    result = dict(status='PASS' if all(mandatory) else 'FAIL',
                  control_count=len(rows), checks_passed=sum(mandatory),
                  checks_total=len(mandatory), rows=rows,
                  interpretation='Nuisance failures describe limitations; mandatory positives/invariances must pass.')
    dump(out/'results.json', result)
    dump(out/'profiles.json', dict(grid=GRID.tolist(), controls=profiles))
    write_csv(out/'synthetic_controls.csv', rows)
    return result

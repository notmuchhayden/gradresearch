"""Native-only input adapter and immutable I/O helpers for A2-O-M."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'results/A2_O_rgb_observability/2026-10-27/profile_selection_v2'
OUT = ROOT/'results/A2_O_M_rgb_mask_diagnostic/2026-10-27'
U = ROOT/'results/A1_U_scale_reparameterization/2026-10-26/construction/office2'
V = ROOT/'results/V1_office3_diagnostic/2026-10-26'
H, W = 288, 512


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def digest(path):
    p = Path(path).resolve()
    return dict(path=str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                bytes=p.stat().st_size, sha256=sha(p))


def dump(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    tmp.replace(p)


def write_csv(path, rows):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with p.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in r.items()})


@lru_cache(None)
def legacy():
    path = OLD/'registered_code/src/rgb_observability.py'
    spec = importlib.util.spec_from_file_location('a2om_archived_rgb', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(None)
def camera():
    c = json.loads((ROOT/'data/N2/Replica/cam_params.json').read_text())['camera']
    nw, nh = round(c['w']*512/max(c['w'], c['h'])), round(c['h']*512/max(c['w'], c['h']))
    hw, hh = (nw//16)*8, (nh//16)*8
    if nw == nh:
        hh = 3*hw//4
    left, top = nw//2-hw, nh//2-hh
    K = np.array([[c['fx']*nw/c['w'], 0, c['cx']*nw/c['w']-left],
                  [0, c['fy']*nh/c['h'], c['cy']*nh/c['h']-top], [0, 0, 1.]])
    assert (2*hh, 2*hw) == (H, W)
    return K


@lru_cache(24)
def rgb(scene, frame):
    p = ROOT/f'data/N2/Replica/{scene}/results/frame{frame:06d}.jpg'
    bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(p)
    im = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    rw, rh = im.size
    ratio = 512/max(rw, rh)
    nw, nh = round(rw*ratio), round(rh*ratio)
    im = im.resize((nw, nh), Image.Resampling.LANCZOS if max(rw, rh) > 512 else Image.Resampling.BICUBIC)
    hw, hh = (nw//16)*8, (nh//16)*8
    if nw == nh:
        hh = 3*hw//4
    im = im.crop((nw//2-hw, nh//2-hh, nw//2+hw, nh//2+hh))
    a = np.asarray(im, dtype=np.float32)/255.
    assert a.shape == (H, W, 3)
    return a


def native_rows(scene):
    """Explicit NPZ allow-list: never read reference/common_mask/strict arrays."""
    out = []
    if scene == 'office2':
        manifest = json.loads((U/'manifest.json').read_text())
        for row in manifest['keyframes']:
            lp = ROOT/row['local_file']['path']
            assert sha(lp) == row['local_file']['sha256']
            with np.load(lp) as a:
                pred = dict(y=a['y'], Q=a['rigid_Q'], pixel_indices=a['active_pixel_indices'])
            i = int(row['kf_idx'])
            rp = ROOT/f'results/A0_pointmap_pose_factorial/office2/oracles/kf{i:04d}_registry.npz'
            with np.load(rp) as reg:
                ids = reg['active_candidate_ids']
                assert np.array_equal(np.flatnonzero(reg['native_mask']), pred['pixel_indices'])
            out.append(dict(kf_idx=i, original_frame=2*int(row['frame_id']),
                            candidate_event=row['candidate_event'], candidate_ids=ids,
                            local_path=lp, registry_path=rp, **pred))
    elif scene == 'office3':
        manifest = json.loads((V/'maps/manifest.json').read_text())
        blocks = manifest.get('blocks')
        if blocks is None:
            blocks = sorted(int(p.stem[2:]) for p in (V/'maps/local').glob('kf*.npz'))
        for b in blocks:
            i = int(b['kf_idx'] if isinstance(b, dict) else b)
            lp = V/f'maps/local/kf{i:03d}.npz'
            with np.load(lp) as a:
                out.append(dict(kf_idx=i, original_frame=int(a['source_frame']),
                                y=a['y'], Q=a['rigid_Q'], pixel_indices=a['active_pixel_indices'],
                                candidate_ids=a['candidate_ids'], local_path=lp, registry_path=None))
    else:
        raise ValueError('scene excluded')
    for k in out:
        assert k['y'].shape == (len(k['pixel_indices']), 3)
        assert len(k['candidate_ids']) == len(k['y'])
        assert np.isfinite(k['y']).all() and (k['y'][:, 2] > 0).all()
    return out


def load_pairs(scene):
    p = OLD/scene/'pair_manifest.csv' if scene == 'office2' else ROOT/'results/A2_O_rgb_observability/2026-10-27/office3/pair_manifest.csv'
    with p.open() as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in ('source_kf', 'source_frame', 'evidence_kf', 'evidence_frame',
                    'final_pose_revision', 'evidence_pose_revision'):
            if row.get(key, '') != '':
                row[key] = int(row[key])
        if row['status'] == 'PROVENANCE_DISJOINT':
            assert set(json.loads(row['source_images'])).isdisjoint(json.loads(row['evidence_images']))
    return rows, p


@lru_cache(32)
def gauge_native(scene, kf, gauge):
    k = DATA[scene][kf]
    y, q = np.asarray(k['y'], float), np.asarray(k['Q'], float)
    if gauge == 'orientation':
        path = ROOT/'results/A1_G_gauge_sensitivity/2026-10-26/gauges/office2.json' if scene == 'office2' else V/'maps/alignment.json'
        D = np.asarray(json.loads(path.read_text())['relative'], float)
        scale = float(np.cbrt(np.linalg.det(D[:3, :3])))
        q = q.copy()
        q[:3, :3] = D[:3, :3]/scale @ q[:3, :3]
        q[:3, 3] = D[:3, :3] @ q[:3, 3]+D[:3, 3]
        y = y*scale
    return y, q


DATA = {}


def init_scene(scene):
    if scene not in DATA:
        DATA[scene] = {k['kf_idx']: k for k in native_rows(scene)}
    return DATA[scene]


@lru_cache(32)
def evidence(scene, kf, gauge):
    k = DATA[scene][kf]
    y, q = gauge_native(scene, kf, gauge)
    with np.errstate(invalid='ignore'):
        z, valid, edge = legacy().rasterize_predicted_depth(y, k['pixel_indices'], camera())
        _, before, _ = legacy().rasterize_predicted_depth(y, k['pixel_indices'], camera(), edge_dilation=0)
    # Raw raster occupancy, before edge rejection.
    zz = y[:, 2]
    px = np.rint(camera()[0, 0]*y[:, 0]/zz+camera()[0, 2]).astype(int)
    py = np.rint(camera()[1, 1]*y[:, 1]/zz+camera()[1, 2]).astype(int)
    ok = (px >= 0) & (px < W) & (py >= 0) & (py < H)
    occupancy = np.zeros(H*W, bool)
    occupancy[py[ok]*W+px[ok]] = True
    return z, valid, dict(raw_raster_pixels=int(occupancy.sum()),
                         valid_before_dilation=int(before.sum()), valid_after_dilation=int(valid.sum()),
                         edge_pixels=int(edge.sum()))


@lru_cache(32)
def patches(scene, kf, gauge, fold):
    k = DATA[scene][kf]
    y, _ = gauge_native(scene, kf, gauge)
    p = legacy().native_patch_samples(y, k['pixel_indices'], rgb(scene, k['original_frame']), fold=fold, stride=2)
    yc = p['points'][:, 4]
    z = np.maximum(yc[:, 2], 1e-12)
    ray = np.hypot(camera()[0, 0]*yc[:, 0]/z+camera()[0, 2]-p['centers'] % W,
                   camera()[1, 1]*yc[:, 1]/z+camera()[1, 2]-p['centers']//W)
    p['ray_error'] = ray
    p['ray_grid_match'] = ray <= 1.
    return p


def pair_bundle(scene, row, gauge, fold):
    init_scene(scene)
    s, e = row['source_kf'], row['evidence_kf']
    _, qs = gauge_native(scene, s, gauge)
    _, qe = gauge_native(scene, e, gauge)
    p = dict(patches(scene, s, gauge, fold))
    world = p['points'][:, 4] @ qs[:3, :3].T+qs[:3, 3]
    rs, re = qs[:3, 3]-world, qe[:3, 3]-world
    den = np.linalg.norm(rs, axis=1)*np.linalg.norm(re, axis=1)
    cosine = np.sum(rs*re, 1)/np.maximum(den, 1e-12)
    p['parallax_deg'] = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
    p['primary_parallax'] = p['parallax_deg'] >= 1.
    z, valid, raster_stats = evidence(scene, e, gauge)
    return dict(patches=p, source_Q=qs, evidence_Q=qe, K=camera(),
                evidence_rgb=rgb(scene, DATA[scene][e]['original_frame']),
                evidence_z=z, evidence_valid=valid, raster_stats=raster_stats,
                camera_baseline=float(np.linalg.norm(qs[:3, 3]-qe[:3, 3])))

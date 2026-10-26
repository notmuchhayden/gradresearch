"""Frozen office3 validation adapters, separate from historical development runs."""
from pathlib import Path
import json
import sys
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'src')]
from prepare_e2b_run import digest, save_json
from e1_taxonomy import camera_geometry, resize_depth, depth_masks
from evaluate_e4 import reference_rgb

SPEC = ROOT/'configs/v1_office3_analysis.json'
ARMS = ['C00', 'C10', 'C01', 'C11']
CZ = ['CZ10', 'CZ11']
OLD = ['A00', 'A10', 'A01', 'A11']


def context():
    spec = json.loads(SPEC.read_text())
    return spec, ROOT/spec['output']


def checked():
    spec, out = context()
    r = json.loads((out/'analysis_registration.json').read_text())
    amendment_path = out/'implementation_amendment_A1.json'
    changes = {}
    if amendment_path.exists():
        amendment = json.loads(amendment_path.read_text())
        assert amendment['protocol_changed'] is False
        for change in amendment['changes']:
            old = change['before']
            assert old in r['code']
            archived = out/'registered_code'/old['path']
            assert digest(archived)['sha256'] == old['sha256']
            changes[old['path']] = change['after']
    for row in r['inputs'] + r['code']:
        assert digest(ROOT/row['path']) == changes.get(row['path'],row), row['path']
    return spec, out


def views():
    data = ROOT/'data/N2/Replica/office3'
    cp = data.parent/'cam_params.json'
    camera = json.loads(cp.read_text())['camera']
    K, _, crop = camera_geometry(camera)
    poses = np.loadtxt(data/'traj.txt').reshape(-1, 4, 4)
    mask = json.loads((ROOT/'configs/n1_coordinate_contract.json').read_text())['common_mask']
    first = data/'results/frame000000.jpg'
    first_mean = (cv2.cvtColor(cv2.imread(str(first)), cv2.COLOR_BGR2RGB).astype(np.float32)/255.).reshape(-1, 3).mean(0)
    result = {}
    for f in range(201, 1000, 2):
        d = resize_depth(cv2.imread(str(data/'results'/f'depth{f:06d}.png'), cv2.IMREAD_UNCHANGED).astype(np.float32)/camera['scale'], camera)
        valid, edge = depth_masks(d, mask)
        result[f] = dict(gt=d, valid=valid & ~edge, all_valid=valid, edge=edge,
                         pose=poses[f], K=K, hw=tuple(crop[2:]),
                         target=(reference_rgb(data/'results'/f'frame{f:06d}.jpg', first_mean)*255).round().astype(np.uint8).astype(np.float32)/255.)
    return result


def definitions():
    spec, _ = context()
    cases = {
        'position_strict': dict(kind='strict', gauge='position', arms=ARMS+CZ),
        'original_strict': dict(kind='original', gauge='position', arms=OLD),
        'orientation_strict': dict(kind='strict', gauge='orientation', arms=ARMS),
        'position_full': dict(kind='full_mixed', gauge='position', arms=ARMS),
        'fixed_world_strict': dict(kind='fixed_world', gauge='position', arms=ARMS),
    }
    for p in spec['source_thinning']['patterns']:
        for d in spec['source_thinning']['densities']:
            tag = f'{p}_{int(d*100):02d}'
            for kind in ['source_only', 'target_only']:
                cases[f'{kind}_{tag}'] = dict(kind=kind, gauge='position', arms=ARMS, pattern=p, density=d)
    return cases


def stats(x):
    x = np.asarray(x)
    x = x[np.isfinite(x)]
    return dict(n=len(x), mean=float(x.mean()), median=float(np.median(x)),
                p95=float(np.percentile(x, 95)), min=float(x.min()), max=float(x.max())) if len(x) else dict(n=0, mean=None, median=None, p95=None, min=None, max=None)

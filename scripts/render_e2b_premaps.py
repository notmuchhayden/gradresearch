"""Render identical causal original-map prefixes for the E2b DoG control."""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'src'), str(ROOT / 'thirdparty/Splatt3R-SLAM')]
import lietorch
from splatt3r_slam.splatt3r_utils import bake_gaussians_world
from render_e1 import render_values
from prepare_e2b_run import digest, save_json
from score_e2b import forbid_e2b_gt_reads
from e0b_audit import sim3_matrix
from e2_signals import dog, image_rgb


@torch.no_grad()
def main(scene):
    started = time.monotonic()
    torch.set_num_threads(2)
    spec = json.loads((ROOT / 'configs/e2b_observation_transfer.json').read_text())
    base = json.loads((ROOT / spec['feature_base_config']).read_text())
    root = ROOT / spec['output']
    run, out = root / 'baselines' / scene, root / 'scores' / scene
    meta = json.loads((out / 'score_metadata.json').read_text())
    score_manifest = json.loads((out / 'score_manifest.json').read_text())
    assert digest(out/'features.npz') == score_manifest['features']
    dump = torch.load(run / 'map' / f'{scene}_kfgauss.pt', weights_only=True, map_location='cpu')
    scores, rows = [], []
    for i, frame in enumerate(dump['keyframes']):
        path = run / 'audit' / meta['lineage'][i]['decision_file']
        snap = torch.load(path, weights_only=True, map_location='cpu')
        assert len(snap['metadata']) == i + 1
        assert snap['pose_revision'] == meta['lineage'][i]['pose_revision']
        K = np.array(meta['predicted_cameras'][i]['K'])
        h, w = frame['img_shape']
        pose = sim3_matrix(snap['poses'][i].numpy())
        camera_pose = pose.copy()
        camera_pose[:3, :3] /= np.cbrt(np.linalg.det(camera_pose[:3, :3]))
        baked = []
        torch.backends.cuda.matmul.allow_tf32 = True
        for j in range(i):
            old = dump['keyframes'][j]
            local = {k: old[k].to('cuda') for k in ('means', 'scales', 'rotations', 'sh', 'opacities', 'conf')}
            baked.append(bake_gaussians_world(local, old['img'].to('cuda'), h, w,
                lietorch.Sim3(snap['poses'][j].to('cuda')), spatial_stride=1,
                depth_max_percentile=0.98, max_scale=1., min_confidence=1.5,
                min_opacity=0.3, inflate_scales_for_stride=False))
        torch.backends.cuda.matmul.allow_tf32 = False
        if baked:
            means, tri, rgb, opacity = [torch.cat([b[k] for b in baked]) for k in range(4)]
            covariance = torch.zeros((len(means), 3, 3), device='cuda')
            r, c = torch.triu_indices(3, 3, device='cuda')
            covariance[:, r, c] = tri
            covariance[:, c, r] = tri
            rendered = render_values(dict(means=means, covariances=covariance, opacity=opacity),
                                     camera_pose, K, (h, w), rgb).cpu().numpy().transpose(1, 2, 0)
            active = len(means)
        else:
            rendered, active = np.zeros((h, w, 3), np.float32), 0
        p = frame['means'].numpy()
        z = p[:, 2]
        x = K[0, 0]*p[:, 0]/np.maximum(z, 1e-12) + K[0, 2]
        y = K[1, 1]*p[:, 1]/np.maximum(z, 1e-12) + K[1, 2]
        warped = cv2.remap(rendered, x.reshape(h,w).astype(np.float32), y.reshape(h,w).astype(np.float32),
                           cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        yy, xx = np.indices((h,w))
        ray = np.stack([(xx-K[0,2])/K[0,0], (yy-K[1,2])/K[1,1], np.ones((h,w))], -1).reshape(-1,3)
        ray /= np.linalg.norm(ray, axis=1, keepdims=True)
        predicted = p / np.maximum(np.linalg.norm(p, axis=1, keepdims=True), 1e-12)
        angle = np.degrees(np.arccos(np.clip((ray*predicted).sum(1), -1, 1)))
        good = ((z>0) & (frame['conf'].numpy() >= base['confidence_min']) &
                (angle <= base['camera_fit_angular_error_max_degrees']) &
                (x>=0) & (x<=w-1) & (y>=0) & (y<=h-1))
        margin = int(np.ceil(3*max(base['dog_sigmas_pixels'])))
        good &= ((xx>=margin)&(xx<w-margin)&(yy>=margin)&(yy<h-margin)).reshape(-1)
        score = (dog(warped, base['dog_sigmas_pixels'])-dog(image_rgb(frame), base['dog_sigmas_pixels'])).reshape(-1)
        score[~good] = np.nan
        scores.append(score)
        image_dir = out/'premaps'
        image_dir.mkdir(exist_ok=True)
        np.savez_compressed(image_dir/f'kf{i:04d}.npz', source=image_rgb(frame), render=warped, score=score.reshape(h,w))
        rows.append(dict(anchor_kf=i, included_kfs=list(range(i)), active_gaussians=active,
                         pose_revision=snap['pose_revision'], snapshot=digest(path), eligible=int(good.sum())))
        print(f'{scene}: B8 pre-map {i+1}/{len(dump["keyframes"])} with {active} Gaussians', flush=True)
        del baked
        if i:
            del local, means, tri, rgb, opacity, covariance
        torch.cuda.empty_cache()
    np.savez_compressed(out/'b8_features.npz', B8_dog_redundancy=np.concatenate(scores))
    save_json(out/'b8_manifest.json', dict(features=digest(out/'b8_features.npz'),
        score_manifest=digest(out/'score_manifest.json'), gt_reads='forbidden', final_map_used=False,
        maps=rows, gpu=torch.cuda.get_device_name(), seconds=time.monotonic()-started,
        code=[digest(Path(__file__)), digest(ROOT/'scripts/render_e1.py'),
              digest(ROOT/'src/e2_signals.py'), digest(ROOT/'thirdparty/Splatt3R-SLAM/splatt3r_slam/splatt3r_utils.py')]))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('scene', choices=['office0','room0'])
    with forbid_e2b_gt_reads():
        main(ap.parse_args().scene)

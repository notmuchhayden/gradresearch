"""Calibrate on office0, seal choices, then evaluate room0 without retuning."""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts'), str(ROOT/'thirdparty/Splatt3R-SLAM/splatt3r_core')]
from prepare_e2b_run import digest, save_json
from e0b_audit import sim3_matrix, transform
from e1_taxonomy import fit_sim3, camera_geometry, resize_depth, depth_masks, classify
from e2_metrics import calibrate_normal_threshold, pr_metrics
from e2b_transfer import operation, progress_checks
from utils.geometry import build_covariance


def features(scene, spec):
    out = ROOT/spec['output']/'scores'/scene
    manifest = json.loads((out/'score_manifest.json').read_text())
    for entry in manifest['code'] + manifest['inputs'] + manifest['history'] + [manifest['features'], manifest['metadata']]:
        assert digest(ROOT/entry['path']) == entry, entry['path']
    assert manifest['gt_reads'] == 'forbidden' and not manifest['final_poses']
    b8_manifest = json.loads((out/'b8_manifest.json').read_text())
    assert digest(out/'b8_features.npz') == b8_manifest['features']
    assert digest(out/'score_manifest.json') == b8_manifest['score_manifest']
    assert not b8_manifest['final_map_used']
    for entry in b8_manifest['code']:
        assert digest(ROOT/entry['path']) == entry
    f = dict(np.load(out/'features.npz'))
    b8 = np.load(out/'b8_features.npz')['B8_dog_redundancy']
    f['max__B8_dog_redundancy'] = b8
    f['creation__B8_dog_redundancy'] = b8
    meta = json.loads((out/'score_metadata.json').read_text())
    return f, meta


def labels(scene, spec, f, meta):
    """Evaluation-only placement and GT proxies; never feeds feature scoring."""
    root = ROOT/spec['output']
    run = root/'baselines'/scene
    dataset = ROOT/'data/E2b/Replica'
    target = root/'evaluation'/scene
    target.mkdir(parents=True, exist_ok=True)
    lspec = json.loads((ROOT/spec['label_base_config']).read_text())
    data_manifest = json.loads((ROOT/f'configs/e2b_{scene}_download_manifest.json').read_text())
    for entry in data_manifest['files']:
        assert digest(ROOT/entry['path'])['sha256'] == entry['sha256']
    camera = json.loads((dataset/'cam_params.json').read_text())['camera']
    poses = np.loadtxt(dataset/scene/'traj.txt').reshape(-1,4,4)
    trajectory = np.loadtxt(run/'map'/f'{scene}_frames.txt')
    frame_ids = trajectory[:,0].astype(int)
    np.testing.assert_array_equal(frame_ids, np.arange(0, spec['scenes'][scene]['original_frame_stop'], 2))
    alignment = fit_sim3(trajectory[:,1:4], poses[frame_ids,:3,3])
    global_scale = np.cbrt(np.linalg.det(alignment[:3,:3]))
    ate = np.linalg.norm(transform(trajectory[:,1:4], alignment)-poses[frame_ids,:3,3], axis=1)
    view_ids = sorted(set(range(0, spec['scenes'][scene]['original_frame_stop'],20)) |
                      {row['original_frame'] for row in meta['lineage']})
    views = []
    for frame in view_ids:
        raw = cv2.imread(str(dataset/scene/'results'/f'depth{frame:06d}.png'), cv2.IMREAD_UNCHANGED)
        assert raw is not None and raw.shape == (camera['h'], camera['w'])
        depth = resize_depth(raw.astype(np.float32)/camera['scale'], camera)
        valid, edge = depth_masks(depth, lspec)
        views.append(dict(frame=frame, depth=depth, valid=valid, edge=edge, pose=poses[frame]))
    K = camera_geometry(camera)[0]
    dump = torch.load(run/'map'/f'{scene}_kfgauss.pt', weights_only=True, map_location='cpu')
    output = {name: [] for name in ('creation', 'final_estimated', 'gt_anchor')}
    for i, kf in enumerate(dump['keyframes']):
        q = kf['rotations']/kf['rotations'].norm(dim=-1, keepdim=True).clamp_min(1e-6)
        cov = build_covariance(kf['scales'],q).numpy()
        final_pose = sim3_matrix(kf['T_WC'].numpy())
        gt_anchor = poses[meta['lineage'][i]['original_frame']].copy()
        gt_anchor[:3,:3] *= global_scale*np.cbrt(np.linalg.det(f['creation_poses'][i,:3,:3]))
        placements = dict(creation=alignment@f['creation_poses'][i],
                          final_estimated=alignment@final_pose, gt_anchor=gt_anchor)
        for name, matrix in placements.items():
            mu = transform(kf['means'].numpy(), matrix)
            sigma = matrix[:3,:3]@cov@matrix[:3,:3].T
            output[name].append(classify(mu, sigma, views, K, lspec)['labels'])
        print(f'{scene}: GT proxies {i+1}/{len(dump["keyframes"])}', flush=True)
    output = {k: np.concatenate(v) for k,v in output.items()}
    consensus = np.zeros(len(output['creation']), np.uint8)
    a,b = output['creation'], output['gt_anchor']
    consensus[(a==3)&(b==3)] = 3
    consensus[np.isin(a,[1,2])&np.isin(b,[1,2])] = 1
    output['cross_pose_consensus'] = consensus
    np.savez_compressed(target/'labels.npz', **output)
    info = dict(scene=scene, primary='creation', specification=lspec, views=view_ids,
        alignment=alignment.tolist(), global_scale=float(global_scale), ate_rmse=float(np.sqrt(np.mean(ate**2))),
        label_counts={k:{str(c):int((a==c).sum()) for c in (0,1,2,3)} for k,a in output.items()},
        gt_use='evaluation only; no score or test threshold tuning', creation_pose_fixed_label=True,
        inputs=[digest(ROOT/f'configs/e2b_{scene}_download_manifest.json'),
                digest(dataset/'cam_params.json'), digest(dataset/scene/'traj.txt'),
                digest(run/'map'/f'{scene}_frames.txt'), digest(run/'map'/f'{scene}_kfgauss.pt'),
                *[digest(dataset/scene/'results'/f'depth{v:06d}.png') for v in view_ids]])
    save_json(target/'label_manifest.json',info)
    return output, info


def evaluate(f, label, spec, thresholds):
    results = {}
    for scope, mask in [('raw',np.ones(len(label),bool)), ('active',f['active'])]:
        table = {}
        for method in spec['methods']:
            s = f['max__'+method]
            eligible = f['repeat_ever'] if method.startswith('P1_second') else np.isfinite(s)
            used = mask & np.isin(label,[1,2,3]) & np.isfinite(s)
            ap = pr_metrics(label[used]==3, s[used])[0]
            ap.update(score_eligible=int((mask & np.isfinite(s)).sum()),
                      coverage=float((mask & np.isfinite(s)).sum()/max(mask.sum(),1)))
            ap['operating_points'] = {ret:operation(s,label,t,eligible,mask)
                                     for ret,t in thresholds[scope][method].items()}
            table[method] = ap
        results[scope] = table
    return results


def freeze_code(root):
    paths = [ROOT/'configs/e2b_observation_transfer.json']
    paths += [ROOT/p for p in ('scripts/analyze_e2b.py','scripts/score_e2b.py','scripts/render_e2b_premaps.py',
        'scripts/prepare_e2b_run.py','scripts/run_e2b_baseline.sh','src/e2b_transfer.py',
        'src/e2_signals.py','src/e2_metrics.py','src/e1_taxonomy.py','tests/test_e2b.py')]
    import shutil
    for p in paths:
        target = root/'sealed_code'/p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p,target)
    return [digest(p) for p in paths]


def main(stage):
    started = time.monotonic()
    torch.set_num_threads(2)
    cfg = ROOT/'configs/e2b_observation_transfer.json'
    spec = json.loads(cfg.read_text())
    prereg=json.loads((ROOT/'configs/e2b_preregistration.json').read_text())
    assert digest(cfg)==prereg['configuration']
    assert digest(ROOT/spec['feature_base_config'])==prereg['feature_base']
    assert digest(ROOT/spec['label_base_config'])==prereg['label_base']
    root = ROOT/spec['output']
    seal_path = root/'thresholds_development_only.json'
    if stage == 'development':
        if seal_path.exists():
            raise RuntimeError('Development seal already exists; do not overwrite after evaluation')
        scene = 'office0'
    else:
        scene = 'room0'
        seal = json.loads(seal_path.read_text())
        for entry in seal['sealed_code']:
            assert digest(ROOT/entry['path']) == entry, entry['path']
        assert seal['configuration_sha256'] == digest(cfg)['sha256']
    f, meta = features(scene,spec)
    label, label_info = labels(scene,spec,f,meta)
    primary = label['creation']
    if stage == 'development':
        thresholds = {}
        for scope, mask in [('raw',np.ones(len(primary),bool)),('active',f['active'])]:
            thresholds[scope] = {method:{str(ret):calibrate_normal_threshold(f['max__'+method],
                mask & np.isin(primary,[1,2]),ret) for ret in spec['normal_retention_targets']}
                for method in spec['methods']}
        development = evaluate(f,primary,spec,thresholds)
        choices = ['P1_second_front_spacing','P1_second_front_relative']
        def selection_key(m):
            op = development['raw'][m]['operating_points']['0.99']
            safe = (op['threshold'] is not None and op['global_normal_retention'] is not None and
                    op['global_normal_retention']>=0.99 and op['eligible_normal_retention'] is not None and
                    op['eligible_normal_retention']>=0.99)
            return (safe, op['global_bad_recall'] or 0., m==choices[0])
        selected = max(choices,key=selection_key)
        legacy_path=ROOT/'results/E2_signal_discriminability/thresholds_development_only.json'
        legacy=json.loads(legacy_path.read_text())
        seal = dict(configuration_sha256=digest(cfg)['sha256'], thresholds=thresholds, selected_method=selected,
            legacy_e2_threshold_source=digest(legacy_path),
            legacy_e2_thresholds={scope:legacy[scope]['at_creation']['P1_plane_front_1view'] for scope in ('raw','active')},
            development_scene=scene, evaluation_scene='room0', development=development,
            development_labels=digest(root/'evaluation'/scene/'labels.npz'),
            development_features=digest(root/'scores'/scene/'features.npz'),
            sealed_code=freeze_code(root),
            note='cumulative candidate max calibrates any causal crossing; only office0 GT labels used')
        save_json(seal_path,seal)
        print(json.dumps(dict(selected=selected, thresholds=thresholds['raw'][selected],
                              development=development['raw'][selected]),indent=2),flush=True)
        return
    threshold_hash = digest(seal_path)['sha256']
    thresholds = seal['thresholds']
    result = dict(specification=spec, selected_method=seal['selected_method'], threshold_sha256=threshold_hash,
        label_info=label_info, results={name:evaluate(f,l,spec,thresholds) for name,l in label.items()},
        development=seal['development'], availability={}, common_cohorts={})
    result['legacy_e2_frozen_at_creation']={}
    for scope,mask in [('raw',np.ones(len(primary),bool)),('active',f['active'])]:
        s=f['creation__P1_median_1view']
        result['legacy_e2_frozen_at_creation'][scope]={name:{ret:operation(s,l,t,np.isfinite(s),mask)
            for ret,t in seal['legacy_e2_thresholds'][scope].items()} for name,l in label.items()}
    anchors = f['anchor_kf']
    creation_input = np.array([r['input_frame'] for r in meta['lineage']])[anchors]
    for mode,key in [('one_view','first_single'),('two_views','first_repeat')]:
        seen = f[key]>=0
        delay = f[key][seen]-creation_input[seen]
        result['availability'][mode] = dict(candidates=len(seen),eligible=int(seen.sum()),
            coverage=float(seen.mean()), never_eligible_fraction=float((~seen).mean()),
            conditional_delay_input_median=float(np.median(delay)) if len(delay) else None,
            conditional_delay_input_p95=float(np.percentile(delay,95)) if len(delay) else None,
            conditional_delay_original_p95=float(2*np.percentile(delay,95)) if len(delay) else None)
    result['availability']['creation_two_views'] = dict(eligible=int((f['creation_count']>=2).sum()),
                                                        coverage=float((f['creation_count']>=2).mean()))
    groups = [ ['B2_confidence','B6_depth_front',seal['selected_method']],
               ['B2_confidence','B6_depth_front','B7_rgb_ncc_region','B8_dog_redundancy',seal['selected_method']] ]
    for i,group in enumerate(groups):
        mask = np.ones(len(primary),bool)
        for m in group:
            mask &= np.isfinite(f['max__'+m])
        result['common_cohorts'][str(i)] = dict(methods=group, candidates=int(mask.sum()),
            raw_fraction=float(mask.mean()), same_candidate_different_first_evidence_times=True,
            metrics={name:{m:dict(ranking=pr_metrics(l[mask & np.isin(l,[1,2,3])]==3,
                f['max__'+m][mask & np.isin(l,[1,2,3])])[0],
                at_99=operation(f['max__'+m],l,thresholds['raw'][m]['0.99'],np.isfinite(f['max__'+m]),mask))
                for m in group} for name,l in label.items()})
    op = result['results']['creation']['raw'][seal['selected_method']]['operating_points']['0.99']
    checks = progress_checks(float(f['repeat_ever'].mean()),op,spec['progress'])
    checks.update(scene_separated=True, gt_free_features=True, sealed_thresholds=True)
    result['decision'] = dict(checks=checks, go_for_e3_validation=all(checks.values()),
        status='GO_FOR_E3_VALIDATION' if all(checks.values()) else 'REVISE', research_wide_go=False,
        failed_checks=[k for k,v in checks.items() if not v], map_admission_executed=False)
    # Save first crossing at real snapshots, rather than assigning retrospective
    # argmax times. Peak scores above are equivalent only for rejection existence.
    decision = root/'evaluation'/scene/'decision_logs'
    decision.mkdir(exist_ok=True)
    for method in spec['methods']:
        for retention in ('0.99','0.95'):
            t = thresholds['raw'][method][retention]
            first = np.full(len(primary),-1,np.int32)
            revision = np.full(len(primary),-1,np.int32)
            for path in sorted((root/'scores'/scene/'history').glob('*.npz')):
                h = np.load(path)
                if method=='B8_dog_redundancy':
                    size = h['support_count'].size
                    values = np.full(size,np.nan,np.float32)
                    anchor = len(h['support_count'])-1
                    n = meta['raw_per_kf']
                    values[anchor*n:(anchor+1)*n] = f['max__'+method][anchor*n:(anchor+1)*n]
                else:
                    values = h[method].reshape(-1)
                cross = (first[:len(values)]<0) & np.isfinite(values)
                cross &= values>t if t is not None else False
                rows = np.flatnonzero(cross)
                first[rows] = int(h['input_frame'])
                revision[rows] = int(h['pose_revision'])
            expected = np.isfinite(f['max__'+method]) & (f['max__'+method]>t) if t is not None else np.zeros(len(first),bool)
            np.testing.assert_array_equal(first>=0,expected)
            np.savez_compressed(decision/f'{method}_{retention}.npz',first_reject_input=first,
                                pose_revision=revision, labels=primary, active=f['active'], anchor_kf=anchors)
    result['evaluation_seconds'] = time.monotonic()-started
    save_json(root/'metrics.json',result)
    save_json(ROOT/'configs/e2b_results_summary.json',result)
    save_json(root/'evaluation_manifest.json',dict(code=seal['sealed_code'], threshold_sha256=threshold_hash,
        labels=digest(root/'evaluation'/scene/'labels.npz'), features=digest(root/'scores'/scene/'features.npz'),
        metrics=digest(root/'metrics.json'), decisions=[digest(p) for p in sorted(decision.glob('*.npz'))]))
    assert digest(seal_path)['sha256']==threshold_hash
    print(json.dumps(result['decision'],indent=2),flush=True)
    print(json.dumps(op,indent=2),flush=True)


if __name__=='__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage',choices=['development','evaluation'])
    main(ap.parse_args().stage)

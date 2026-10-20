"""Recompute E2b decisions/thresholds and verify immutable provenance."""
import json
from pathlib import Path
import sys
import platform

import numpy as np
import torch
import scipy
import cv2

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from prepare_e2b_run import digest, save_json
from analyze_e2b import features
from e2_metrics import calibrate_normal_threshold, pr_metrics
from e2b_transfer import operation, progress_checks


def main():
    spec=json.loads((ROOT/'configs/e2b_observation_transfer.json').read_text())
    root=ROOT/spec['output']
    seal=json.loads((root/'thresholds_development_only.json').read_text())
    metrics=json.loads((root/'metrics.json').read_text())
    assert digest(ROOT/seal['legacy_e2_threshold_source']['path'])==seal['legacy_e2_threshold_source']
    assert digest(root/'thresholds_development_only.json')['sha256']==metrics['threshold_sha256']
    for entry in seal['sealed_code']:
        assert digest(ROOT/entry['path'])==entry,entry['path']
    count=0
    checks={}
    scene_rgb={}
    for scene in ('office0','room0'):
        f,meta=features(scene,spec)
        ply=root/'baselines'/scene/'map'/f'{scene}_gaussians.ply'
        vertices=None
        with ply.open('rb') as handle:
            for _ in range(100):
                line=handle.readline().decode('ascii').strip()
                if line.startswith('element vertex '):
                    vertices=int(line.split()[-1])
                if line=='end_header':
                    break
        assert vertices==meta['active'], (scene,vertices,meta['active'])
        labels=np.load(root/'evaluation'/scene/'labels.npz')['creation']
        manifest=json.loads((root/'baselines'/scene/'run_manifest.json').read_text())
        scene_rgb[scene]={entry['sha256'] for entry in manifest['inputs']}
        np.testing.assert_array_equal(f['anchor_kf'],np.repeat(np.arange(meta['keyframes']),meta['raw_per_kf']))
        np.testing.assert_array_equal(f['pixel_index'],np.tile(np.arange(meta['raw_per_kf']),meta['keyframes']))
        for weight in manifest['weights']:
            assert digest(ROOT/weight['file'])['sha256']==weight['sha256']
        assert len(manifest['inputs'])==spec['scenes'][scene]['original_frame_stop']//2
        for entry in manifest['inputs']+manifest['code']:
            # Baseline code was frozen at execution; shared code can be checked
            # against its archived copy if later non-baseline analysis evolves.
            p=ROOT/entry['path']
            if entry in manifest['code']:
                p=root/'baselines'/scene/'code'/entry['path']
            assert digest(p)['sha256']==entry['sha256'],entry['path']
        pair_rows=[json.loads(s) for s in (root/'scores'/scene/'pair_audit.jsonl').read_text().splitlines()]
        for row in pair_rows:
            a=meta['lineage'][row['candidate_kf']]['source_images']
            b=meta['lineage'][row['evidence_kf']]['source_images']
            assert a and b and not set(a)&set(b)
            assert row['evidence_raw_sequence']<row['decision_sequence']
        if scene=='office0':
            for scope,mask in [('raw',np.ones(len(labels),bool)),('active',f['active'])]:
                for method in spec['methods']:
                    for retention,t in seal['thresholds'][scope][method].items():
                        got=calibrate_normal_threshold(f['max__'+method],mask&np.isin(labels,[1,2]),float(retention))
                        assert got==t,(method,retention,got,t)
                        count+=1
        else:
            for method in spec['methods']:
                for ret,t in seal['thresholds']['raw'][method].items():
                    d=np.load(root/'evaluation'/scene/'decision_logs'/f'{method}_{ret}.npz')
                    expected=np.isfinite(f['max__'+method])&(f['max__'+method]>t) if t is not None else np.zeros(len(labels),bool)
                    np.testing.assert_array_equal(d['first_reject_input']>=0,expected)
                    actual=metrics['results']['creation']['raw'][method]['operating_points'][ret]
                    eligible=f['repeat_ever'] if method.startswith('P1_second') else np.isfinite(f['max__'+method])
                    assert operation(f['max__'+method],labels,t,eligible)==actual
            # Compare ranking to an independent implementation, including ties.
            from sklearn.metrics import average_precision_score
            compared=0
            for method in spec['methods']:
                s=f['max__'+method]
                good=np.isfinite(s)&np.isin(labels,[1,2,3])
                y=labels[good]==3
                if y.any() and (~y).any():
                    actual=metrics['results']['creation']['raw'][method]['average_precision']
                    assert abs(average_precision_score(y,s[good])-actual)<1e-12
                    compared+=1
            selected=metrics['selected_method']
            op=metrics['results']['creation']['raw'][selected]['operating_points']['0.99']
            recomputed=progress_checks(float(f['repeat_ever'].mean()),op,spec['progress'])
            for key,value in recomputed.items():
                assert metrics['decision']['checks'][key]==value
            assert metrics['decision']['go_for_e3_validation']==all(metrics['decision']['checks'].values())
        checks[scene]=dict(status='PASS',raw=meta['candidate_count'],keyframes=meta['keyframes'],
                           active_ply_vertices=vertices,source_causal_pairs_checked=len(pair_rows))
    assert not scene_rgb['office0']&scene_rgb['room0'], 'Cross-scene identical input RGB detected'
    em=json.loads((root/'evaluation_manifest.json').read_text())
    for entry in [em['metrics'],em['labels'],em['features'],*em['decisions']]:
        assert digest(ROOT/entry['path'])==entry
    figures=json.loads((root/'figure_manifest.json').read_text())
    for entry in figures['figures']+[figures['metrics']]:
        assert digest(ROOT/entry['path'])==entry
    result=dict(status='PASS',scenes=checks,cross_scene_shared_rgb_hashes=0,development_thresholds_recomputed=count,
        sklearn_ap_comparisons=compared,cumulative_first_crossing='PASS',sealed_code='PASS',
        threshold_hash=metrics['threshold_sha256'],decision=metrics['decision'],code=digest(Path(__file__)))
    save_json(ROOT/'configs/e2b_validation.json',result)
    save_json(root/'validation.json',result)
    save_json(ROOT/'configs/e2b_code_manifest.json',dict(
        environment=dict(python=platform.python_version(),torch=torch.__version__,numpy=np.__version__,
                         scipy=scipy.__version__,opencv=cv2.__version__,cuda=torch.version.cuda),
        configuration=digest(ROOT/'configs/e2b_observation_transfer.json'),
        preregistration=digest(ROOT/'configs/e2b_preregistration.json'),
        sealed_analysis=seal['sealed_code'],thresholds=digest(root/'thresholds_development_only.json'),
        baselines={scene:json.loads((root/'baselines'/scene/'run_manifest.json').read_text()) for scene in ('office0','room0')},
        score_manifests={scene:digest(root/'scores'/scene/'score_manifest.json') for scene in ('office0','room0')},
        b8_manifests={scene:digest(root/'scores'/scene/'b8_manifest.json') for scene in ('office0','room0')},
        gpu={scene:digest(root/'baselines'/scene/'gpu.csv') for scene in ('office0','room0')},
        evaluation=digest(root/'evaluation_manifest.json'),figures=digest(root/'figure_manifest.json'),
        metrics=digest(root/'metrics.json'),validation=digest(root/'validation.json'),
        runner=digest(ROOT/'scripts/run_e2b.sh'),downloader=digest(ROOT/'scripts/download_e0_replica.py')))
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()

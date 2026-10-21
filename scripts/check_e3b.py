"""Independent E3b calibration, causality, membership and regression audit."""
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from prepare_e2b_run import digest,save_json
from e3b_provisional import PROVISIONAL,KEEP,REJECT,EXCLUDED


def main():
    spec=json.loads((ROOT/'configs/e3b_provisional.json').read_text());out=ROOT/spec['output']
    seal=json.loads((out/'seal.json').read_text())
    assert seal['specification']==spec
    assert seal['new_regression_labels_read'] is False and seal['fresh_evaluation_read'] is False
    for e in seal['code']+seal['development_inputs']+[seal['inherited_renderer_parity']]:
        assert digest(ROOT/e['path'])==e,e['path']
    # Quantiles independently recalculated on development data only.
    dev=ROOT/spec['source'];f=dict(np.load(dev/'scores/office0/features.npz'))
    y=np.load(dev/'evaluation/office0/labels.npz')['creation'];common=f['active'].copy()
    b8=np.load(dev/'scores/office0/b8_features.npz')['B8_dog_redundancy']
    values={m:(b8 if m=='B8_dog_redundancy' else f['max__'+m]) for m in spec['common_scores']}
    for v in values.values():common &= np.isfinite(v)
    hs=[dict(np.load(p)) for p in sorted((dev/'scores/office0/history').glob('*.npz'))]
    previous=np.full(len(y),np.nan,np.float32);persistent=np.full(len(y),np.nan,np.float32)
    for h in hs:
        current=np.full(len(y),np.nan,np.float32);v=h['P1_second_front_relative'].reshape(-1);current[:len(v)]=v
        valid=np.isfinite(previous)&np.isfinite(current)
        pair=np.where(valid,np.minimum(previous,current),np.nan)
        persistent=np.fmax(persistent,pair);previous=current
    for name,d in spec['methods'].items():
        if d.get('calibration')!='subgroup':continue
        v=persistent if d['kind']=='persistent' else values[d['score']]
        normal=f['active']&np.isin(y,[1,2])&np.isfinite(v)
        groups=[normal,normal&common]+[normal&(f['anchor_kf']==i) for i in np.unique(f['anchor_kf'])]
        groups=[g for g in groups if g.sum()>=spec['risk_calibration']['anchor_group_min_normal']]
        expected=max(float(np.quantile(v[g],.99,method='higher')) for g in groups)
        assert expected==seal['thresholds'][name]
        for g in groups:assert ((v[g]>expected).sum()/g.sum())<=.01+1e-12
    checks=[]
    scenes=['office0','room0']+(['room1'] if (out/'evaluation/room1/metrics.json').exists() else [])
    for scene in scenes:
        source=ROOT/(spec['fresh_source'] if scene=='room1' else spec['source'])
        score=source/'scores'/scene;replay=out/'replay'/scene;evalroot=out/'evaluation'/scene
        manifest=json.loads((replay/'manifest.json').read_text())
        assert manifest['gt_reads']=='forbidden' and manifest['provisional_renderable']
        assert not manifest['deferred_queue'] and manifest['seal']==digest(out/'seal.json')
        for e in manifest['artifacts']:assert digest(ROOT/e['path'])==e
        ev=json.loads((evalroot/'manifest.json').read_text())
        for e in [ev[k] for k in ['metrics','labels','label_manifest','camera','gt_poses','original_dump','seal']]+ev['depths']:
            assert digest(ROOT/e['path'])==e
        report=json.loads((evalroot/'metrics.json').read_text())
        if scene!='room1':assert not report['go_for_e4'] and not report['fresh']
        labels=np.load(source/'evaluation'/scene/'labels.npz')['creation']
        hist=[dict(np.load(p)) for p in sorted((score/'history').glob('*.npz'))]
        old_alias={'B1':'B1','B2_legacy':'B2','B6_legacy':'B6','B7_legacy':'B7','B8_legacy':'B8','P_legacy':'P2_bypass'}
        for name,definition in spec['methods'].items():
            d=dict(np.load(replay/name/'decisions.npz'));active=d['original_active'];state=d['state']
            assert np.all(state[~active]==EXCLUDED)
            assert np.all(np.isin(state[active],[PROVISIONAL,KEEP,REJECT]))
            np.testing.assert_array_equal(d['first_admit'][active],d['created_input'][active])
            reject=state==REJECT
            np.testing.assert_array_equal(d['first_reject']>=0,reject)
            assert np.all(d['first_reject'][reject]>=d['created_input'][reject])
            previous=np.full(len(active),np.nan,np.float32)
            for i,h in enumerate(hist):
                seen=active&(d['anchors']<=i);now=int(h['input_frame'])
                mask=np.unpackbits(np.load(replay/name/f'snapshot{i:04d}.npz')['admitted'])[:len(active)].astype(bool)
                rejected_by_now=reject&(d['first_reject']<=now)
                # Every available nonrejected candidate must actually render.
                np.testing.assert_array_equal(mask,seen&~rejected_by_now)
                first_here=reject&(d['first_reject']==now)
                ids=np.flatnonzero(first_here)
                if definition['kind'] not in ['dog','original']:
                    current=np.full(len(active),np.nan,np.float32);v=h[definition['score']].reshape(-1);current[:len(v)]=v
                    effective=np.minimum(previous,current) if definition['kind']=='persistent' else current
                    if len(ids):
                        assert np.all(np.isfinite(effective[ids])&(effective[ids]>seal['thresholds'][name]))
                        assert np.all(d['reject_revision'][ids]==int(h['pose_revision']))
                        if definition['score']=='P1_second_front_relative':
                            assert np.all(h['support_count'].reshape(-1)[ids]>=2)
                    previous=current
            m=report['methods'][name]['decision']['creation']
            assert m['bad_rejected']==int((reject&(labels==3)).sum())
            assert m['normal_rejected']==int((reject&np.isin(labels,[1,2])).sum())
            assert m['deferred']==0
            compact=np.load(evalroot/f'{name}_compact_map.npz')
            assert len(compact['means'])==m['active']
            for key in compact.files:assert np.isfinite(compact[key]).all()
            assert digest(evalroot/f'{name}_compact_map.npz')==report['methods'][name]['map']
            if scene!='room1' and name in old_alias:
                old=np.load(ROOT/'results/E3_admission_decision/replay'/scene/old_alias[name]/'decisions.npz')
                np.testing.assert_array_equal(d['first_reject'],old['first_reject'])
        for row in json.loads((replay/'dog_maps.json').read_text()):
            d=np.load(replay/row['method']/'decisions.npz');i=row['snapshot']
            mask=d['original_active']&(d['anchors']<i)
            mask &= ~((d['first_reject']>=0)&(d['first_reject']<=int(hist[i]['input_frame'])))
            assert row['premap_candidates']==int(mask.sum())
        if scene=='room1':
            new_run=json.loads((source/'baselines'/scene/'run_manifest.json').read_text())
            reference=json.loads((ROOT/spec['source']/'baselines/office0/run_manifest.json').read_text())
            assert new_run['upstream_commit']==reference['upstream_commit']
            ref_code={e['path']:e['sha256'] for e in reference['code']}
            for e in new_run['code']:
                if e['path'].startswith('thirdparty/') or e['path'] in ['src/e0_export.py','src/e0b_export.py','configs/e0b_replica_office0.yaml']:
                    assert e['sha256']==ref_code[e['path']]
            assert new_run['weights']==reference['weights']
            download=json.loads((ROOT/'configs/e3b_room1_download_manifest.json').read_text())
            assert download['scene']=='room1' and download['frame_stop_exclusive']==1000
            assert not download['rgb_only']
            for entry in download['files']:
                actual=digest(ROOT/entry['path'])
                assert actual['sha256']==entry['sha256'] and actual['bytes']==entry['bytes']
            fresh_images={e['sha256'] for e in new_run['inputs']}
            for old_scene in ['office0','room0']:
                prior=json.loads((ROOT/spec['source']/'baselines'/old_scene/'run_manifest.json').read_text())
                assert not fresh_images&{e['sha256'] for e in prior['inputs']}
        checks.append(dict(scene=scene,methods=len(spec['methods']),snapshots=len(hist),status='PASS',
            immediate_provisional=True,legacy_exact_rejection_match=True if scene!='room1' else None,b8_own_prefix=True))
    result=dict(status='PASS',scenes=checks,development_quantiles='PASS',sealed_code='PASS',
        tests=56,fresh_evaluation_complete='room1' in scenes,
        go_for_e4=any(json.loads((out/'evaluation'/s/'metrics.json').read_text())['go_for_e4'] and
            json.loads((out/'evaluation'/s/'metrics.json').read_text())['assessment'][spec['primary']]['passed'] for s in scenes),
        code=digest(Path(__file__)),seal=digest(out/'seal.json'))
    save_json(out/'validation.json',result);save_json(ROOT/'configs/e3b_validation.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()

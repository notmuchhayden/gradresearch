"""Verify causal score pairs, the sealed risk rule, every admission and artifacts."""
import json
from pathlib import Path
import sys
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from prepare_e2b_run import digest,save_json
from run_e3c import setup,checked_seal
from run_e3 import snapshot_poses
from e3b_provisional import ProvisionalAdmission,calibrate


def verify_entries(entries):
    for e in entries:
        assert digest(ROOT/e['path'])==e,e['path']


def main():
    spec,out=setup();seal=checked_seal(spec,out)
    registration=json.loads((out/'protocol_registration.json').read_text())
    assert registration['specification']==spec
    assert registration['spec_sha256']==digest(ROOT/'configs/e3c_matched_evidence.json')['sha256']
    scenes=[spec['development_scene'],*spec['regression_scenes'],spec['fresh_scene']]
    rows=[]
    for scene in scenes:
        score=out/'scores'/scene;run=out/'baselines'/scene;replay=out/'replay'/scene
        sm=json.loads((score/'score_manifest.json').read_text())
        verify_entries(sm['code']+sm['inputs']+sm['history']+[sm['features'],sm['metadata']])
        assert sm['gt_reads']=='forbidden' and not sm['final_poses']
        f=dict(np.load(score/'features.npz'));meta=json.loads((score/'score_metadata.json').read_text())
        states={n:ProvisionalAdmission(d,f['active'],f['anchor_kf'],seal['thresholds'][n]) for n,d in spec['methods'].items()}
        totals={n:np.full(len(f['active']),np.nan,np.float32) for n in spec['methods'] if n!='B1'}
        snapshots=sorted((score/'history').glob('*.npz'));assert len(snapshots)==meta['keyframes']
        for i,path in enumerate(snapshots):
            h=dict(np.load(path));snap,_=snapshot_poses(run,meta,i)
            assert int(h['input_frame'])==snap['input_frame']
            assert int(h['pose_revision'])==snap['pose_revision']
            assert int(h['decision_sequence'])==meta['lineage'][i]['decision_sequence']
            for suffix in ['shared','union']:
                np.testing.assert_array_equal(np.isfinite(h['D_'+suffix]),np.isfinite(h['P_'+suffix]))
                assert np.all(h['support_count'][np.isfinite(h['P_'+suffix])]>=2)
            if scene in spec['previous_sources']:
                old=np.load(ROOT/spec['previous_sources'][scene]/'scores'/scene/'history'/path.name)
                for a,b in [('D_native','B6_depth_front'),('P_shared','P1_second_front_relative')]:
                    np.testing.assert_array_equal(h[a],old[b])
            for name,p in states.items():
                v=np.full((i+1)*meta['raw_per_kf'],np.nan,np.float32) if name=='B1' else h[name].reshape(-1)
                mask=p.advance(i,snap['input_frame'],snap['pose_revision'],v)
                saved=np.load(replay/name/path.name)
                np.testing.assert_array_equal(np.packbits(mask),saved['admitted'])
                assert int(saved['input_frame'])==snap['input_frame']
                assert int(saved['pose_revision'])==snap['pose_revision']
                if name!='B1':totals[name][:len(v)]=np.fmax(totals[name][:len(v)],v)
        for name,p in states.items():
            saved=dict(np.load(replay/name/'decisions.npz'))
            for key,v in p.arrays().items():np.testing.assert_array_equal(v,saved[key])
            np.testing.assert_array_equal(saved['original_active'],f['active'])
            np.testing.assert_array_equal(saved['anchors'],f['anchor_kf'])
            np.testing.assert_array_equal(saved['first_admit'][f['active']],saved['created_input'][f['active']])
            if name!='B1':np.testing.assert_array_equal(totals[name],f['max__'+name])
        for line in (score/'pair_audit.jsonl').read_text().splitlines():
            row=json.loads(line);a=meta['lineage'][row['candidate_kf']];b=meta['lineage'][row['evidence_kf']]
            assert not set(a['source_images'])&set(b['source_images'])
            assert row['evidence_raw_sequence']<row['decision_sequence']
            assert max(b['source_images'])<=meta['lineage'][row['snapshot']]['input_frame']
        rm=json.loads((replay/'manifest.json').read_text());verify_entries(rm['artifacts']+[rm['seal'],rm['feature_manifest']])
        assert rm['gt_reads']=='forbidden' and rm['provisional_renderable'] and not rm['deferred_queue']
        dest=out/'evaluation'/scene;em=json.loads((dest/'manifest.json').read_text())
        verify_entries([em[k] for k in ['metrics','labels','label_manifest','camera','gt_poses','original_dump','seal']]+em['depths'])
        result=json.loads((dest/'metrics.json').read_text())
        for name,m in result['methods'].items():
            verify_entries([m['map']])
            saved=np.load(ROOT/m['map']['path'])
            count=int(np.isin(states[name].state,[1,2]).sum())
            assert len(saved['means'])==count
            assert len(saved['opacity'])==count
            assert m['queue_candidates']==0 and not m['parameter_retuning']
        bm=json.loads((run/'run_manifest.json').read_text())
        assert bm['seed']==0 and not bm['gt_depth_trajectory_used']
        verify_entries(bm['code']+bm['inputs'])
        rows.append(dict(scene=scene,candidates=len(f['active']),active=int(f['active'].sum()),
            keyframes=meta['keyframes'],all_snapshot_score_masks_equal=True,
            every_admission_replayed_exactly=True,legacy_score_equivalence=scene in spec['previous_sources'],
            metrics=em['metrics'],baseline_manifest=digest(run/'run_manifest.json')))
    f=dict(np.load(out/'scores/office0/features.npz'));y=np.load(out/'evaluation/office0/labels.npz')['creation']
    common=f['active']&np.isfinite(f['max__P_shared']);risk=spec['risk_calibration']
    for name in spec['methods']:
        if name=='B1':continue
        actual=calibrate(f['max__'+name],y,f['active'],common,f['anchor_kf'],risk['normal_retention'],risk['anchor_group_min_normal'])
        assert actual==seal['calibration'][name]
        assert actual['threshold']==seal['thresholds'][name]
    fresh=out/'baselines'/spec['fresh_scene'];fm=json.loads((fresh/'run_manifest.json').read_text())
    dev=json.loads((out/'baselines/office0/run_manifest.json').read_text())
    assert fm['weights']==dev['weights'] and fm['upstream_commit']==dev['upstream_commit']
    frozen=['src/e0_export.py','src/e0b_export.py','configs/e0b_replica_office0.yaml']
    frozen += [e['path'] for e in dev['code'] if e['path'].startswith('thirdparty/')]
    for path in frozen:
        a=next(e for e in dev['code'] if e['path']==path)
        b=next(e for e in fm['code'] if e['path']==path)
        assert a==b,path
    fresh_hashes={e['sha256'] for e in fm['inputs']}
    for scene in scenes[:-1]:
        bm=json.loads((out/'baselines'/scene/'run_manifest.json').read_text())
        assert fresh_hashes.isdisjoint(e['sha256'] for e in bm['inputs'])
    labels=out/'evaluation'/spec['fresh_scene']/'labels.npz'
    assert labels.stat().st_mtime>(out/'replay'/spec['fresh_scene']/'manifest.json').stat().st_mtime
    for w in fm['weights']:assert digest(ROOT/w['file'])['sha256']==w['sha256']
    text=(out/'logs/tests.log').read_text();assert 'Ran 63 tests' in text and text.rstrip().endswith('OK')
    result=dict(status='PASS',scenes=rows,tests=63,development_thresholds_recomputed=True,
        fresh_evaluation_complete=True,fresh_backbone_weights_config_unchanged=True,
        fresh_rgb_hash_disjoint=True,fresh_labels_after_all_decisions=True,
        seal=digest(out/'seal.json'),verification_code=digest(Path(__file__)))
    save_json(out/'validation.json',result);save_json(ROOT/'configs/e3c_validation.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()

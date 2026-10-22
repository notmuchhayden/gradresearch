"""Audit exact resource equality, sealed policies and all E4 evaluation artifacts."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from run_e4 import setup,checked_seal
from prepare_e2b_run import digest,save_json
from e4_budget import random_priority
from e3b_provisional import calibrate


def main():
    spec,out=setup();seal=checked_seal(spec,out);seen=set();checked=0
    def verify(e):
        nonlocal checked
        path=ROOT/e['path']
        if e['path'] not in seen:
            assert digest(path)==e,e['path'];seen.add(e['path']);checked+=1
    revision=out/'seal_revisions/v1_before_evaluation/seal.json'
    assert hashlib.sha256(revision.read_bytes()).hexdigest()==seal['pre_evaluation_code_amendment']['previous_seal_sha256']
    previous=json.loads(revision.read_text());assert previous['thresholds']==seal['thresholds'] and previous['specification']==spec
    registration=json.loads((out/'protocol_registration.json').read_text());assert registration['specification']==spec
    scenes=['office0',*spec['regression_scenes'],spec['fresh_scene']];rows=[]
    for scene in scenes:
        replay=out/'replay'/scene;rm=json.loads((replay/'manifest.json').read_text())
        assert rm['gt_reads']=='forbidden' and rm['causal_natural_only']
        for e in rm['artifacts']+[rm['seal'],rm['source_features'],rm['broad_features']]:verify(e)
        for manifest_entry in [rm['source_features'],rm['broad_features']]:
            m=json.loads((ROOT/manifest_entry['path']).read_text())
            assert m['gt_reads']=='forbidden' and not m['final_poses']
            for e in m['code']+m['inputs']+m['history']+[m['features'],m['metadata']]:verify(e)
        index=json.loads((out/'selection'/scene/'index.json').read_text())
        assert len(index)==len(spec['methods'])*(1+2*len(spec['keep_fractions']))
        assert {x['method'] for x in index}==set(spec['methods'])
        em=json.loads((out/'evaluation'/scene/'manifest.json').read_text())
        for e in [em['metrics'],em['seal'],em['replay']]+em['inputs']+em['row_files']:verify(e)
        result=json.loads((out/'evaluation'/scene/'metrics.json').read_text());assert len(result['rows'])==len(index)
        decisions={m:dict(np.load(replay/m/'decisions.npz')) for m in spec['methods']}
        active=decisions['B1']['active'];N=int(active.sum());priority={s:random_priority(len(active),s) for s in [0,1,2]}
        labelroot=out/'evaluation'/scene if scene==spec['fresh_scene'] else ROOT/spec['prior']/'evaluation'/scene
        labels=np.load(labelroot/'labels.npz')['creation'];normal=active&np.isin(labels,[1,2]);bad=active&(labels==3)
        outputs={r['id']:r for r in result['rows']};counts={};unreachable=0
        for entry in index:
            d=decisions[entry['method']];natural=d['natural_membership'];row=outputs[entry['id']]
            assert row['reachable']==entry['reachable']
            if not entry['reachable']:
                unreachable+=1
                if entry['reason']=='natural_survivors_below_quota':assert natural.sum()<entry['target']
                else:assert (active&np.isfinite(d['score'])).sum()<N-entry['target']
                continue
            s=np.load(out/'selection'/scene/(entry['id']+'.npz'));mask=np.unpackbits(s['mask'])[:int(s['size'])].astype(bool)
            assert not (mask&~active).any();assert int(mask.sum())==row['count']
            if entry['arm']=='natural':np.testing.assert_array_equal(mask,natural)
            else:
                expected=int(np.floor(N*entry['fraction']));assert mask.sum()==expected
                counts.setdefault(entry['fraction'],set()).add(row['map']['bytes'])
                random_control=entry['method']=='B1' or entry['method'].startswith('B3_')
                if entry['arm']=='policy_fallback' or random_control:
                    allowed=active if random_control else natural
                    assert not (mask&~allowed).any()
                    p=priority[entry['seed']]
                    assert not (allowed&~mask).any() or p[mask].max()<p[allowed&~mask].min()
                else:
                    rejected=active&~mask;finite=active&np.isfinite(d['score']);kept=mask&finite
                    assert not (rejected&~finite).any()
                    if kept.any() and rejected.any():assert d['score'][rejected].min()>=d['score'][kept].max()
            assert row['map']['bytes']==52*int(mask.sum())
            assert row['memory']['actual_n_resident']==mask.sum()
            assert row['memory']['parameter_tensor_bytes']==52*mask.sum() and row['memory']['physical_compaction']
            verify(row['map']);verify(row['tsdf']);verify(row['membership'])
            assert [r['frame'] for r in row['frames']]==spec['rgb_frames']
            for frame in row['frames']:assert frame['frame']%2==1
            c=row['natural_classification'];reject=active&~mask
            assert c['bad_rejected']==int((reject&bad).sum()) and c['normal_rejected']==int((reject&normal).sum())
            assert c['finite_normal']==int((normal&np.isfinite(d['score'])).sum())
        assert all(len(v)==1 for v in counts.values()),'Matched counts must imply identical serialized parameter bytes'
        if scene in spec['previous_sources']:
            prior=ROOT/spec['prior']/'replay'/scene
            for method,old in [('D_shared','D_shared'),('D_maskmedian','D_maskmedian'),('P2_plane','P_shared')]:
                expected=dict(np.load(prior/old/'decisions.npz'))
                for key in ['state','first_admit','first_reject','reject_revision','ever_finite']:
                    np.testing.assert_array_equal(decisions[method][key],expected[key])
        dog=json.loads((replay/'dog_audit.json').read_text())
        assert all(a['premap_count']==a['expected'] for a in dog)
        base=out/'baselines'/scene;bm=json.loads((base/'run_manifest.json').read_text())
        assert bm['seed']==0 and not bm['gt_depth_trajectory_used']
        for e in bm['code']+bm['inputs']:verify(e)
        for w in bm['weights']:assert digest(ROOT/w['file'])['sha256']==w['sha256']
        rows.append(dict(scene=scene,active=N,arms=len(index),reachable=len(index)-unreachable,unreachable=unreachable,
            identical_count_and_parameter_bytes=True,original_filter_preserved=True,natural_policy_legacy_equivalence=scene in spec['previous_sources'],
            metrics=digest(out/'evaluation'/scene/'metrics.json')))
    fresh=out/'baselines'/spec['fresh_scene'];fm=json.loads((fresh/'run_manifest.json').read_text())
    features=np.load(ROOT/spec['prior']/'scores/office0/features.npz');dev_labels=np.load(ROOT/spec['prior']/'evaluation/office0/labels.npz')['creation']
    extras=np.load(out/'development_extra_scores.npz');common=features['active']&np.isfinite(features['max__P_shared'])
    for name in ['B4_voxel','B5_self','P1_creation','P3_rgb_and']:
        c=calibrate(extras[name],dev_labels,features['active'],common,features['anchor_kf'],.99,100)
        assert c==seal['calibration'][name] and c['threshold']==seal['thresholds'][name]
    dev=json.loads((out/'baselines/office0/run_manifest.json').read_text());assert fm['weights']==dev['weights'] and fm['upstream_commit']==dev['upstream_commit']
    for e in dev['code']:
        if e['path'].startswith('thirdparty/') or e['path'] in ['src/e0_export.py','src/e0b_export.py','configs/e0b_replica_office0.yaml']:
            assert e==next(v for v in fm['code'] if v['path']==e['path'])
    hashes={e['sha256'] for e in fm['inputs']}
    for scene in scenes[:-1]:assert hashes.isdisjoint(e['sha256'] for e in json.loads((out/'baselines'/scene/'run_manifest.json').read_text())['inputs'])
    assert (out/'evaluation'/spec['fresh_scene']/'labels.npz').stat().st_mtime>(out/'replay'/spec['fresh_scene']/'manifest.json').stat().st_mtime
    text=(out/'logs/tests.log').read_text();assert 'Ran 75 tests' in text and text.rstrip().endswith('OK')
    smoke=(out/'logs/smoke.log').read_text();assert 'TSDF planar-depth smoke PASS' in smoke
    result=dict(status='PASS',tests=75,cuda_compact_parity_tsdf_smoke=True,scenes=rows,unique_artifacts_hashed=checked,
        fresh_evaluation_after_decisions=True,fresh_backbone_weights_unchanged=True,fresh_rgb_disjoint=True,
        pre_evaluation_amendment_preserved=True,new_development_thresholds_recomputed=True,
        seal=digest(out/'seal.json'),verification_code=digest(Path(__file__)))
    save_json(out/'validation.json',result);save_json(ROOT/'configs/e4_validation.json',result);print(json.dumps(result,indent=2))


if __name__=='__main__':main()

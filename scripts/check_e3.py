"""Independently audit persisted E3 decisions, map membership and evidence."""
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'src')]
from prepare_e2b_run import digest,save_json
from e3_admission import KEEP,REJECT,DEFER,BYPASS,EXCLUDED


def main():
    spec = json.loads((ROOT/'configs/e3_admission.json').read_text())
    out = ROOT/spec['output']
    seal = json.loads((out/'preregistration.json').read_text())
    for entry in seal['code']+[seal['threshold_source'],seal['parity']]:
        assert digest(ROOT/entry['path'])==entry
    assert seal['new_evaluation_labels_read'] is False
    assert seal['evaluation_previously_inspected'] is True
    assert json.loads((out/'renderer_parity.json').read_text())['passed']
    checks = []
    for scene in ['office0','room0']:
        root = out/'replay'/scene
        manifest = json.loads((root/'manifest.json').read_text())
        assert manifest['gt_reads']=='forbidden' and manifest['policy_specific_b8']
        assert digest(out/'preregistration.json')==manifest['seal']
        for entry in manifest['artifacts']:
            assert digest(ROOT/entry['path'])==entry
        eval_root = out/'evaluation'/scene
        ev = json.loads((eval_root/'evaluation_manifest.json').read_text())
        for entry in [ev[k] for k in ['labels','label_manifest','camera','gt_poses','metrics','seal']]+ev['depths']:
            assert digest(ROOT/entry['path'])==entry
        metrics = json.loads((eval_root/'metrics.json').read_text())
        labels = np.load(ROOT/ev['labels']['path'])['creation']
        score = ROOT/spec['source']/'scores'/scene
        hist = [dict(np.load(p)) for p in sorted((score/'history').glob('*.npz'))]
        n = hist[0]['support_count'].size
        all_decisions = {p:dict(np.load(root/p/'decisions.npz')) for p in spec['policies']}
        for p,d in all_decisions.items():
            state,active = d['state'],d['original_active']
            assert np.all(state[~active]==EXCLUDED)
            assert np.all(np.isin(state[active],[KEEP,REJECT,DEFER,BYPASS]))
            rejected = state==REJECT
            np.testing.assert_array_equal(d['first_reject']>=0,rejected)
            assert np.all(d['first_reject'][rejected]>=d['created_input'][rejected])
            if p=='P1':
                np.testing.assert_array_equal(d['first_reject'][rejected],d['created_input'][rejected])
            for i,h in enumerate(hist):
                checkpoint = np.load(root/p/f'snapshot{i:04d}.npz')
                mask = np.unpackbits(checkpoint['admitted'])[:len(active)].astype(bool)
                pending = np.unpackbits(checkpoint['deferred'])[:len(active)].astype(bool)
                assert not (mask&pending).any()
                assert not ((mask|pending)&~active).any()
                assert not ((mask|pending)&(d['anchor']>i)).any()
                past_reject = rejected&(d['first_reject']<=int(h['input_frame']))
                assert not (mask&past_reject).any()
                first_here = rejected&(d['first_reject']==int(h['input_frame']))
                ids = np.flatnonzero(first_here)
                if p in ['P1','P2_bypass','P2','P2_unbounded','P3'] and len(ids):
                    values = h['P1_second_front_relative'].reshape(-1)[ids]
                    assert np.all(np.isfinite(values)&(values>seal['thresholds']['P1_second_front_relative']))
                    assert np.all(h['support_count'].reshape(-1)[ids]>=2)
                    if p=='P3':
                        photo = h['B7_rgb_ncc_region'].reshape(-1)[ids]
                        assert np.all(np.isfinite(photo)&(photo>seal['thresholds']['B7_rgb_ncc_region']))
                    assert np.all(d['rejected_revision'][ids]==int(h['pose_revision']))
            a = metrics['policies'][p]['decision']['creation']
            assert a['bad_rejected']==int((rejected&(labels==3)).sum())
            assert a['normal_rejected']==int((rejected&np.isin(labels,[1,2])).sum())
            assert a['active']==int(np.isin(state,[KEEP,BYPASS]).sum())
            compact_path = eval_root/f'{p}_compact_map.npz'
            compact = np.load(compact_path)
            assert len(compact['means'])==a['active']
            for k in compact.files:
                assert np.isfinite(compact[k]).all()
            assert digest(compact_path)==metrics['policies'][p]['compact_map_file']
        # Isolates queue behavior: changing missing-evidence handling cannot
        # change the geometric rejection set when all live candidates recheck.
        for p in ['P2','P2_unbounded']:
            np.testing.assert_array_equal(all_decisions[p]['first_reject'],all_decisions['P2_bypass']['first_reject'])
        # Independent temporal-max calculation from each decision snapshot.
        peak = np.full(len(labels),np.nan,np.float32)
        for h in hist:
            values = h['P1_second_front_relative'].reshape(-1)
            peak[:len(values)] = np.fmax(peak[:len(values)],values)
        expected = all_decisions['P2']['original_active']&np.isfinite(peak)&(peak>seal['thresholds']['P1_second_front_relative'])
        np.testing.assert_array_equal(expected,all_decisions['P2']['state']==REJECT)
        for row in json.loads((root/'b8_causal_maps.json').read_text()):
            i = row['snapshot']
            d = all_decisions['B8']
            earlier_alive = (d['anchor']<i)&d['original_active']&~((d['state']==REJECT)&(d['first_reject']<=int(hist[i]['input_frame'])))
            assert row['policy_active_premap']==int(earlier_alive.sum())
        checks.append(dict(scene=scene,policies=len(spec['policies']),snapshots=len(hist),
            candidate_count=len(labels),active=int(all_decisions['B1']['original_active'].sum()),
            status='PASS',temporal_crossing_matches=True,b8_own_map=True,compact_maps_checked=True))
    result = dict(status='PASS',scenes=checks,code_seal='PASS',renderer_parity='PASS',
        tests='45 passed; see logs/tests.log',fresh_test=False,cuda_measured=False,
        code=[digest(Path(__file__))],seal=digest(out/'preregistration.json'))
    save_json(out/'validation.json',result)
    save_json(ROOT/'configs/e3_validation.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
